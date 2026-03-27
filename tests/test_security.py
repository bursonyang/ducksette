"""
SQL 安全过滤属性测试。

**Validates: Requirements 4.1, 4.2**
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ducksette.errors import ForbiddenQueryError
from ducksette.security import validate_sql

WRITE_STARTERS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
    "ALTER", "TRUNCATE", "REPLACE", "MERGE", "COPY",
    "ATTACH", "DETACH",
]


# Feature: ducksette, Property 9: 写操作 SQL 被拒绝
@settings(max_examples=100)
@given(
    st.sampled_from(WRITE_STARTERS).flatmap(
        lambda kw: st.text().map(lambda rest: kw + " " + rest)
    )
)
def test_write_sql_rejected(sql: str) -> None:
    """**Validates: Requirements 4.1, 4.2**"""
    with pytest.raises(ForbiddenQueryError):
        validate_sql(sql)


# Feature: ducksette, Property 9: 只读 SQL 被允许
@settings(max_examples=100)
@given(st.text().map(lambda t: "SELECT " + t))
def test_select_sql_allowed(sql: str) -> None:
    """**Validates: Requirements 4.1**"""
    try:
        validate_sql(sql)
    except ForbiddenQueryError:
        pytest.fail("SELECT should not be rejected")
