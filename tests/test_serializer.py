"""
Ducksette 序列化模块属性测试。
"""

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given, settings, strategies as st

from ducksette.serializer import QueryResult, coerce_value, serialize

# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

_duckdb_value_strategy = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(),
    st.dates(),
    st.datetimes(),
    st.decimals(allow_nan=False, allow_infinity=False),
    st.binary(),
    st.timedeltas(),
)

_query_result_strategy = st.builds(
    QueryResult,
    columns=st.lists(st.text(min_size=1), min_size=1, max_size=5),
    rows=st.lists(
        st.lists(st.one_of(st.none(), st.integers(), st.text()), max_size=5)
    ),
    truncated=st.booleans(),
    next_cursor=st.one_of(st.none(), st.text(min_size=1)),
    query_ms=st.floats(min_value=0, allow_nan=False, allow_infinity=False),
)

# ---------------------------------------------------------------------------
# Property 11: DuckDB 类型值均可 JSON 序列化
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(_duckdb_value_strategy)
def test_coerce_value_json_serializable(value):
    # Feature: ducksette, Property 11: DuckDB 类型值均可 JSON 序列化
    result = coerce_value(value)
    # Should not raise TypeError or ValueError
    json.dumps(result)


# ---------------------------------------------------------------------------
# Property 10: 序列化响应包含所有必需顶层字段
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {"columns", "rows", "truncated", "next", "next_url", "query_ms", "query"}


@settings(max_examples=100)
@given(_query_result_strategy)
def test_serialize_contains_required_fields(result):
    # Feature: ducksette, Property 10: 序列化响应包含所有必需顶层字段
    response = serialize(result)
    assert isinstance(response, dict), "serialize() should return a dict for default shape"
    for field in REQUIRED_FIELDS:
        assert field in response, f"Missing required field: {field}"
    assert isinstance(response["columns"], list)
    assert all(isinstance(c, str) for c in response["columns"])
    assert isinstance(response["rows"], list)


# ---------------------------------------------------------------------------
# Property 12: JSON 序列化 round-trip
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(_query_result_strategy)
def test_json_round_trip(result):
    # Feature: ducksette, Property 12: JSON 序列化 round-trip
    serialized = serialize(result)
    assert json.loads(json.dumps(serialized)) == serialized


# ---------------------------------------------------------------------------
# Property 15: _shape 参数控制 rows 格式
# ---------------------------------------------------------------------------

_shape_strategy = st.sampled_from(["arrays", "objects", "array", "arrayfirst"])


@settings(max_examples=100)
@given(_query_result_strategy, _shape_strategy)
def test_shape_controls_rows_format(result, shape):
    # Feature: ducksette, Property 15: _shape 参数控制 rows 格式
    response = serialize(result, shape=shape)

    if shape == "array":
        # Response is a list of dicts; keys are columns present in the (possibly shorter) row
        assert isinstance(response, list)
        for item in response:
            assert isinstance(item, dict)
            # All keys must be valid column names
            for key in item:
                assert key in result.columns
    elif shape == "objects":
        assert isinstance(response, dict)
        for row in response["rows"]:
            assert isinstance(row, dict)
            # All keys must be valid column names
            for key in row:
                assert key in result.columns
    elif shape == "arrayfirst":
        assert isinstance(response, dict)
        for i, row in enumerate(response["rows"]):
            original_row = result.rows[i]
            if original_row:
                # First column value (coerced)
                assert row == coerce_value(original_row[0])
            else:
                assert row is None
    else:
        # "arrays" (default)
        assert isinstance(response, dict)
        for row in response["rows"]:
            assert isinstance(row, list)
