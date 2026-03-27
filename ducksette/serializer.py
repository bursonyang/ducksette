"""
Ducksette JSON 序列化模块（PrettyPrinter）。

将 QueryResult 序列化为符合 Datasette 格式的 JSON 响应。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    next_cursor: str | None
    query_ms: float


def coerce_value(value: Any) -> Any:
    """将 DuckDB 返回的特殊类型转换为 JSON 兼容类型。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, bytearray):
        return bytes(value).hex()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [coerce_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): coerce_value(v) for k, v in value.items()}
    # Fallback: convert to string
    return str(value)


def serialize(
    result: QueryResult,
    shape: str = "arrays",
    database: str | None = None,
    table: str | None = None,
    request_url: str | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """将 QueryResult 序列化为 Datasette 兼容的 JSON 响应。

    shape 参数：
      - "arrays"    : rows 中每个元素为列表（默认）
      - "objects"   : rows 中每个元素为字典，键为列名
      - "array"     : 响应直接为对象列表
      - "arrayfirst": rows 中每个元素为第一列的值
    """
    columns = result.columns

    # Coerce all values in rows
    coerced_rows = [[coerce_value(v) for v in row] for row in result.rows]

    # Build next_url
    next_url: str | None = None
    if result.next_cursor is not None and request_url is not None:
        separator = "&" if "?" in request_url else "?"
        next_url = f"{request_url}{separator}_next={result.next_cursor}"

    if shape == "array":
        # Return a list of dicts directly
        return [dict(zip(columns, row)) for row in coerced_rows]

    if shape == "objects":
        rows_out: Any = [dict(zip(columns, row)) for row in coerced_rows]
    elif shape == "arrayfirst":
        rows_out = [row[0] if row else None for row in coerced_rows]
    else:
        # "arrays" (default)
        rows_out = coerced_rows

    response: dict[str, Any] = {
        "columns": columns,
        "rows": rows_out,
        "truncated": result.truncated,
        "next": result.next_cursor,
        "next_url": next_url,
        "query_ms": result.query_ms,
        "query": {
            "sql": None,
            "params": [],
        },
    }

    if database is not None:
        response["database"] = database
    if table is not None:
        response["table"] = table

    return response
