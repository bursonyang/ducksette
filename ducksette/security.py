"""
SQL 安全过滤模块。

使用 sqlglot tokenizer 解析 SQL 的第一个有效 token，
若为写操作关键字则抛出 ForbiddenQueryError。
"""

from sqlglot import tokens as sqlglot_tokens

from ducksette.errors import ForbiddenQueryError

WRITE_KEYWORDS = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
    "ALTER", "TRUNCATE", "REPLACE", "MERGE", "COPY",
    "ATTACH", "DETACH",
})

_TOKENIZER = sqlglot_tokens.Tokenizer()


def _first_token_text(sql: str) -> str | None:
    """返回 SQL 第一个有效 token 的文本（大写），忽略空白和注释。

    若 tokenizer 抛出异常，回退到按空白分词取第一个词。
    """
    try:
        token_list = _TOKENIZER.tokenize(sql)
        if token_list:
            return token_list[0].text.upper()
        return None
    except Exception:
        # Tokenizer 失败时（如未闭合字符串），回退到简单空白分词
        # 这样 "INSERT \"" 仍能被正确识别为写操作
        stripped = sql.strip()
        if not stripped:
            return None
        parts = stripped.split()
        return parts[0].upper() if parts else None


def validate_sql(sql: str) -> None:
    """解析 SQL 的第一个 token（忽略注释和空白）。

    若第一个有效关键字为写操作，抛出 ForbiddenQueryError。
    使用 sqlglot tokenizer 而非简单字符串匹配，防止绕过。
    """
    first = _first_token_text(sql)
    if first is not None and first in WRITE_KEYWORDS:
        raise ForbiddenQueryError(sql)
