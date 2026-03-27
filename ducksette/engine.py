"""
QueryEngine 模块：持有 DuckDB 连接，负责数据源挂载和 SQL 执行。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import duckdb

from ducksette.config import Config, DataSourceConfig
from ducksette.errors import DatabaseNotFoundError, QueryError
from ducksette.security import validate_sql
from ducksette.serializer import QueryResult

logger = logging.getLogger(__name__)

_CREDENTIALS_RE = re.compile(r"(://[^:@/]+):([^@]+)@")


def _redact(value: object) -> str:
    """Replace passwords in connection-string-like text with '***'."""
    return _CREDENTIALS_RE.sub(r"\1:***@", str(value))

# Type mapping for ATTACH statements
TYPE_MAP = {
    "parquet": "parquet",
    "csv": "csv",
    "postgresql": "postgres",
    "mysql": "mysql",
}

# Internal sentinel for the in-process DuckDB memory catalog (used in tests)
class _MemorySource:
    name = "memory"
    type = "duckdb_memory"
    path = None
    connection_string = None
    options: dict = {}


@dataclass
class DatabaseMeta:
    name: str
    type: str
    table_count: int


@dataclass
class ColumnMeta:
    name: str
    dtype: str


@dataclass
class TableMeta:
    name: str
    schema: str
    columns: list[ColumnMeta]
    row_count: int | None


def build_attach_sql(config: DataSourceConfig) -> str:
    """Generate ATTACH SQL for a data source config (database-type sources only)."""
    db_type = TYPE_MAP.get(config.type, config.type)
    conn_str = config.connection_string or ""
    return f"ATTACH '{conn_str}' AS {config.name} (TYPE {db_type}, READ_ONLY)"


def _stem_from_path(path: str) -> str:
    """Extract filename stem from a path, e.g. '/data/sales.csv' -> 'sales'."""
    import os
    return os.path.splitext(os.path.basename(path))[0]


def build_view_sql(config: DataSourceConfig) -> str:
    """Generate CREATE VIEW SQL for file-based sources (CSV, Parquet).

    The view name is derived from the file stem (e.g. sales.csv -> sales),
    not from config.name, so the table name reflects the actual file.
    """
    path = config.path or ""
    view_name = _stem_from_path(path) if path else config.name
    if config.type == "csv":
        opts = config.options or {}
        header = str(opts.get("header", True)).lower()
        delim = opts.get("delimiter", ",")
        return (
            f"CREATE VIEW {view_name} AS "
            f"SELECT * FROM read_csv('{path}', header={header}, delim='{delim}')"
        )
    elif config.type == "parquet":
        return (
            f"CREATE VIEW {view_name} AS "
            f"SELECT * FROM read_parquet('{path}')"
        )
    raise ValueError(f"build_view_sql called for unsupported type: {config.type}")


class QueryEngine:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._conn = duckdb.connect(":memory:")
        self._attached: dict[str, DataSourceConfig] = {}

    def initialize(self) -> list[str]:
        """Attach all data sources, skip failures with WARNING."""
        succeeded = []
        for src in self.config.sources:
            try:
                if src.type in ("csv", "parquet"):
                    sql = build_view_sql(src)
                    self._conn.execute(sql)
                else:
                    sql = build_attach_sql(src)
                    self._conn.execute(sql)
                self._attached[src.name] = src
                succeeded.append(src.name)
                logger.info("Attached data source: %s (%s)", src.name, src.type)
            except Exception as exc:
                logger.warning("Failed to attach %s: %s", src.name, _redact(exc))
        return succeeded

    def list_databases(self) -> list[DatabaseMeta]:
        """Return all user-attached catalogs with metadata."""
        result = []
        for name, src in self._attached.items():
            if src.type in ("csv", "parquet"):
                # File-based sources are views in the memory catalog — always 1 "table"
                result.append(DatabaseMeta(name=name, type=src.type, table_count=1))
            else:
                try:
                    count_row = self._conn.execute(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        f"WHERE table_catalog = '{name}' "
                        "AND table_schema NOT IN ('information_schema', 'pg_catalog')"
                    ).fetchone()
                    table_count = count_row[0] if count_row else 0
                except Exception:
                    table_count = 0
                result.append(DatabaseMeta(name=name, type=src.type, table_count=table_count))
        return result

    def list_tables(self, database: str) -> list[TableMeta]:
        """Return tables in a database. Raises DatabaseNotFoundError if not found."""
        if database not in self._attached:
            raise DatabaseNotFoundError(database)

        src = self._attached[database]

        # File-based sources (csv/parquet) are views — table name = file stem
        if src.type in ("csv", "parquet"):
            view_name = _stem_from_path(src.path) if src.path else database
            try:
                desc = self._conn.execute(f"SELECT * FROM {view_name} LIMIT 0").description or []
                columns = [ColumnMeta(name=d[0], dtype=str(d[1])) for d in desc]
            except Exception:
                columns = []
            return [TableMeta(name=view_name, schema="main", columns=columns, row_count=None)]

        # Database-type sources (postgresql, mysql, duckdb_memory, etc.)
        catalog = "memory" if src.type == "duckdb_memory" else database

        tables = self._conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            f"WHERE table_catalog = '{catalog}' "
            "AND table_schema NOT IN ('information_schema', 'pg_catalog') "
            "ORDER BY table_schema, table_name"
        ).fetchall()

        result = []
        for (schema_name, table_name) in tables:
            cols = self._conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_catalog = '{catalog}' AND table_schema = '{schema_name}' "
                f"AND table_name = '{table_name}' ORDER BY ordinal_position"
            ).fetchall()
            columns = [ColumnMeta(name=col[0], dtype=col[1]) for col in cols]
            result.append(TableMeta(name=table_name, schema=schema_name, columns=columns, row_count=None))
        return result

    def execute(
        self,
        sql: str,
        params: list[Any] | None = None,
        page_size: int | None = None,
        cursor: int = 0,
    ) -> QueryResult:
        """Execute SQL, validate first, wrap DuckDB errors as QueryError."""
        validate_sql(sql)

        limit = page_size or self.config.default_page_size
        max_limit = self.config.max_returned_rows
        limit = min(limit, max_limit)

        # Fetch limit+1 to detect truncation
        fetch_sql = f"SELECT * FROM ({sql}) __q LIMIT {limit + 1} OFFSET {cursor}"

        start = time.monotonic()
        try:
            if params:
                rows_raw = self._conn.execute(fetch_sql, params).fetchall()
            else:
                rows_raw = self._conn.execute(fetch_sql).fetchall()
        except Exception as exc:
            raise QueryError(exc) from exc
        elapsed_ms = (time.monotonic() - start) * 1000

        truncated = len(rows_raw) > limit
        rows = [list(r) for r in rows_raw[:limit]]

        # Get column names
        try:
            desc = self._conn.execute(f"SELECT * FROM ({sql}) __q LIMIT 0").description or []
            columns = [d[0] for d in desc]
        except Exception:
            columns = []

        next_cursor = str(cursor + limit) if truncated else None

        return QueryResult(
            columns=columns,
            rows=rows,
            truncated=truncated,
            next_cursor=next_cursor,
            query_ms=elapsed_ms,
        )

    def reconnect(self, source_name: str) -> bool:
        """Try to re-attach a data source. Returns True if successful."""
        src = self._attached.get(source_name) or next(
            (s for s in self.config.sources if s.name == source_name), None
        )
        if src is None:
            return False
        try:
            if src.type in ("csv", "parquet"):
                view_name = _stem_from_path(src.path) if src.path else source_name
                try:
                    self._conn.execute(f"DROP VIEW IF EXISTS {view_name}")
                except Exception:
                    pass
                self._conn.execute(build_view_sql(src))
            else:
                sql = build_attach_sql(src)
                try:
                    self._conn.execute(f"DETACH {source_name}")
                except Exception:
                    pass
                self._conn.execute(sql)
            self._attached[source_name] = src
            return True
        except Exception as exc:
            logger.warning("Reconnect failed for %s: %s", source_name, _redact(exc))
            return False
