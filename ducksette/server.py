"""
FastAPI 路由层：定义所有 HTTP 路由，处理参数解析、错误映射和响应构造。
"""

import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ducksette.engine import QueryEngine
from ducksette.errors import (
    DatabaseNotFoundError,
    DataSourceUnavailableError,
    DucksettError,
    ForbiddenQueryError,
    QueryError,
    TableNotFoundError,
)
from ducksette.serializer import serialize

logger = logging.getLogger(__name__)

# DucksettError subclass -> HTTP status code
ERROR_STATUS_MAP = {
    DatabaseNotFoundError: 404,
    TableNotFoundError: 404,
    ForbiddenQueryError: 403,
    QueryError: 400,
    DataSourceUnavailableError: 503,
}


def create_app(engine: QueryEngine) -> FastAPI:
    app = FastAPI(title="Ducksette")

    # Store engine in app state
    app.state.engine = engine

    @app.exception_handler(DucksettError)
    async def ducksett_error_handler(request: Request, exc: DucksettError):
        status = ERROR_STATUS_MAP.get(type(exc), 500)
        return JSONResponse(
            status_code=status,
            content={"ok": False, "error": str(exc), "status": status},
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        # 500 responses must NOT expose stack traces
        logger.exception("Unexpected error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Internal server error", "status": 500},
        )

    # Access log middleware
    @app.middleware("http")
    async def access_log_middleware(request: Request, call_next):
        start = time.monotonic()
        try:
            response = await call_next(request)
        except DucksettError as exc:
            status = ERROR_STATUS_MAP.get(type(exc), 500)
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.info("%s %s %d %.2fms", request.method, request.url.path, status, elapsed_ms)
            return JSONResponse(
                status_code=status,
                content={"ok": False, "error": str(exc), "status": status},
            )
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.info("%s %s 500 %.2fms", request.method, request.url.path, elapsed_ms)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": "Internal server error", "status": 500},
            )
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s %d %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    # -----------------------------------------------------------------------
    # Routes — explicit routes must be registered before dynamic ones
    # -----------------------------------------------------------------------

    @app.get("/")
    async def index(request: Request):
        eng: QueryEngine = request.app.state.engine
        databases = eng.list_databases()
        return {
            "databases": [
                {"name": db.name, "type": db.type, "table_count": db.table_count}
                for db in databases
            ]
        }

    # Register /.json explicitly BEFORE /{database} to avoid capture
    @app.get("/.json")
    async def index_json(request: Request):
        return await index(request)

    @app.get("/{database}")
    async def database_view(database: str, request: Request):
        # Strip .json suffix if present
        if database.endswith(".json"):
            database = database[:-5]
        eng: QueryEngine = request.app.state.engine
        tables = eng.list_tables(database)
        return {
            "database": database,
            "tables": [
                {
                    "name": t.name,
                    "schema": t.schema,
                    "qualified_name": f"{t.schema}.{t.name}" if t.schema not in ("main", database) else t.name,
                    "columns": [{"name": c.name, "type": c.dtype} for c in t.columns],
                }
                for t in tables
            ],
        }

    @app.get("/{database}/{table}")
    async def table_view(
        database: str,
        table: str,
        request: Request,
        sql: str | None = None,
        _size: int | None = None,
        _next: int = 0,
        _shape: str = "arrays",
    ):
        # Strip .json suffix from table if present
        if table.endswith(".json"):
            table = table[:-5]
        eng: QueryEngine = request.app.state.engine

        # Support schema.table notation for multi-schema sources (e.g. MySQL)
        if "." in table:
            schema_part, table_part = table.split(".", 1)
            query_sql = sql or f"SELECT * FROM {database}.{schema_part}.{table_part}"
        else:
            src = eng._attached.get(database)
            if src and src.type in ("csv", "parquet"):
                # File-based views: table name IS the view name (file stem), no catalog prefix
                query_sql = sql or f"SELECT * FROM {table}"
            else:
                query_sql = sql or f"SELECT * FROM {database}.{table}"

        try:
            result = eng.execute(query_sql, page_size=_size, cursor=_next)
        except DataSourceUnavailableError:
            raise
        except (ForbiddenQueryError, QueryError):
            raise
        except Exception:
            # Try reconnect once on unexpected connection errors
            if eng.reconnect(database):
                result = eng.execute(query_sql, page_size=_size, cursor=_next)
            else:
                raise DataSourceUnavailableError(database)

        request_url = str(request.url).split("?")[0]
        return serialize(
            result,
            shape=_shape,
            database=database,
            table=table,
            request_url=request_url,
        )

    return app
