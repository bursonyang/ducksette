"""
Ducksette 异常类层次结构。

HTTP 状态码映射：
  DatabaseNotFoundError      -> 404
  TableNotFoundError         -> 404
  ForbiddenQueryError        -> 403
  QueryError                 -> 400
  DataSourceUnavailableError -> 503
  其他未预期异常              -> 500
"""


class DucksettError(Exception):
    """所有 Ducksette 异常的基类。"""


class ConfigError(DucksettError):
    """配置解析错误，启动时终止。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return f"ConfigError: {self.message}"


class DatabaseNotFoundError(DucksettError):
    """请求的数据库（catalog）不存在 -> HTTP 404。"""

    def __init__(self, database: str) -> None:
        super().__init__(f"Database '{database}' not found")
        self.database = database

    def __str__(self) -> str:
        return f"DatabaseNotFoundError: database='{self.database}'"


class TableNotFoundError(DucksettError):
    """请求的表不存在 -> HTTP 404。"""

    def __init__(self, database: str, table: str) -> None:
        super().__init__(f"Table '{table}' not found in database '{database}'")
        self.database = database
        self.table = table

    def __str__(self) -> str:
        return f"TableNotFoundError: database='{self.database}', table='{self.table}'"


class ForbiddenQueryError(DucksettError):
    """SQL 包含写操作关键字，被拒绝执行 -> HTTP 403。"""

    def __init__(self, sql: str) -> None:
        super().__init__(f"Write operations are not allowed: {sql!r}")
        self.sql = sql

    def __str__(self) -> str:
        return f"ForbiddenQueryError: sql={self.sql!r}"


class QueryError(DucksettError):
    """DuckDB 执行 SQL 时抛出的异常，包装原始异常 -> HTTP 400。"""

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original

    def __str__(self) -> str:
        return f"QueryError: {self.original}"


class DataSourceUnavailableError(DucksettError):
    """数据源连接断开且重连失败 -> HTTP 503。"""

    def __init__(self, source_name: str) -> None:
        super().__init__(f"Data source '{source_name}' is unavailable")
        self.source_name = source_name

    def __str__(self) -> str:
        return f"DataSourceUnavailableError: source_name='{self.source_name}'"
