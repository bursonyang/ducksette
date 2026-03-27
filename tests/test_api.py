"""
FastAPI 路由集成测试（tasks 9.2–9.8）。

使用 starlette.testclient.TestClient + 内存 DuckDB。
"""

import pytest
from starlette.testclient import TestClient

from ducksette.config import Config
from ducksette.engine import QueryEngine, _MemorySource
from ducksette.server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    cfg = Config(sources=[], max_returned_rows=100, default_page_size=10)
    eng = QueryEngine(cfg)
    eng._conn.execute(
        "CREATE TABLE orders (id INTEGER, amount FLOAT, status VARCHAR)"
    )
    eng._conn.execute(
        "INSERT INTO orders VALUES (1, 99.9, 'paid'), (2, 149.0, 'pending'), (3, 50.0, 'paid')"
    )
    eng._attached["memory"] = _MemorySource()
    return eng


@pytest.fixture
def app(engine):
    return create_app(engine)


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Task 9.2 — Property 16: 500 response doesn't contain stack trace
# ---------------------------------------------------------------------------


def test_property_16_500_no_traceback(client, app):
    # Feature: ducksette, Property 16: 500 响应不包含内部堆栈信息
    # Validates: Requirements 8.1
    from unittest.mock import patch

    with patch.object(app.state.engine, "list_databases", side_effect=RuntimeError("boom")):
        response = client.get("/")
    assert response.status_code == 500
    body = response.json()
    assert "Traceback" not in body.get("error", "")
    assert 'File "' not in body.get("error", "")


# ---------------------------------------------------------------------------
# Task 9.3 — GET / and GET /.json routes
# ---------------------------------------------------------------------------


def test_index_returns_databases(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "databases" in data


def test_index_json_suffix(client):
    response = client.get("/.json")
    assert response.status_code == 200
    data = response.json()
    assert "databases" in data


# ---------------------------------------------------------------------------
# Task 9.4 — GET /{database} and GET /{database}.json routes
# ---------------------------------------------------------------------------


def test_database_view_memory(client):
    response = client.get("/memory")
    assert response.status_code == 200
    data = response.json()
    assert "tables" in data
    table_names = [t["name"] for t in data["tables"]]
    assert "orders" in table_names


def test_database_view_json_suffix(client):
    response = client.get("/memory.json")
    assert response.status_code == 200
    data = response.json()
    assert "tables" in data


def test_database_view_not_found(client):
    response = client.get("/nonexistent_db_xyz")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Task 9.5 — GET /{database}/{table} with query params
# ---------------------------------------------------------------------------


def test_table_view_basic(client):
    response = client.get("/memory/orders")
    assert response.status_code == 200
    data = response.json()
    assert "columns" in data
    assert "rows" in data
    assert "truncated" in data


def test_table_view_json_suffix(client):
    response = client.get("/memory/orders.json")
    assert response.status_code == 200
    data = response.json()
    assert "columns" in data


def test_table_view_with_sql(client):
    response = client.get(
        "/memory/orders?sql=SELECT id FROM memory.orders WHERE status='paid'"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["columns"] == ["id"]


def test_table_view_with_size(client):
    response = client.get("/memory/orders?_size=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["rows"]) <= 1


def test_table_view_forbidden_sql(client):
    response = client.get("/memory/orders?sql=DROP TABLE orders")
    assert response.status_code == 403


def test_table_view_invalid_sql(client):
    response = client.get("/memory/orders?sql=SELECT * FROM nonexistent_xyz")
    assert response.status_code == 400


def test_table_view_shape_objects(client):
    response = client.get("/memory/orders?_shape=objects")
    assert response.status_code == 200
    data = response.json()
    for row in data["rows"]:
        assert isinstance(row, dict)


# ---------------------------------------------------------------------------
# Task 9.7 — Property 17: reconnect on disconnect returns 503
# ---------------------------------------------------------------------------


def test_property_17_reconnect_once_then_503(client, app):
    # Feature: ducksette, Property 17: 连接断开时重连一次后返回 503
    # Validates: Requirements 8.4
    from unittest.mock import patch

    # Simulate execute raising an unexpected exception (connection lost),
    # and reconnect returning False (reconnect fails)
    with patch.object(app.state.engine, "execute", side_effect=Exception("connection lost")):
        with patch.object(app.state.engine, "reconnect", return_value=False):
            response = client.get("/memory/orders")
    assert response.status_code == 503
