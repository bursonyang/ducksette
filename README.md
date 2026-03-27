# Ducksette

> A DuckDB-powered data browser with a [Datasette](https://datasette.io/)-compatible HTTP API.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Ducksette lets you explore heterogeneous data sources — Parquet files, CSV files, PostgreSQL, MySQL — through a single read-only HTTP API. It uses DuckDB's `ATTACH` mechanism under the hood and mirrors Datasette's URL structure and JSON response format, so existing Datasette clients and scripts work without modification.

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [SQL Safety](#sql-safety)
- [Error Responses](#error-responses)
- [Development](#development)
- [License](#license)

---

## Features

- **Multi-source** — Parquet, CSV, PostgreSQL, MySQL via DuckDB ATTACH
- **Datasette-compatible** — same routes, same JSON shape, `.json` suffix support
- **Read-only enforcement** — write-operation SQL is rejected with HTTP 403
- **Pagination** — cursor-based with `_next` and `_size` parameters
- **Flexible response shapes** — `arrays`, `objects`, `array`, `arrayfirst`
- **Swagger UI** — interactive docs at `/docs`
- **Structured access logs** — method, path, status, latency on every request
- **Graceful degradation** — failed sources are skipped at startup; one reconnect attempt on connection loss

---

## Installation

Requires Python 3.10+. [uv](https://docs.astral.sh/uv/) is recommended.

```bash
git clone https://github.com/yourname/ducksette.git
cd ducksette

# Create virtualenv and install
uv venv .venv --python 3.11
uv pip install -e ".[dev]" --python .venv/bin/python
```

<details>
<summary>Using pip instead</summary>

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```
</details>

---

## Quick Start

**1. Write a config file**

```yaml
# ducksette.yaml
max_returned_rows: 1000
default_page_size: 100

sources:
  - name: sales
    type: parquet
    path: /data/sales.parquet

  - name: logs
    type: csv
    path: /data/access_logs.csv
    options:
      header: true
      delimiter: ","

  - name: analytics
    type: postgresql
    connection_string: "postgresql://user:pass@host:5432/mydb"

  - name: warehouse
    type: mysql
    connection_string: "mysql://user:pass@host:3306/mydb"
```

**2. Start the server**

```bash
.venv/bin/ducksette --config ducksette.yaml
# INFO  Successfully mounted data sources: ['sales', 'logs', 'analytics', 'warehouse']
# INFO  Uvicorn running on http://127.0.0.1:8000
```

**3. Browse**

```bash
curl http://127.0.0.1:8000/          # list all databases
curl http://127.0.0.1:8000/sales     # list tables in 'sales'
curl http://127.0.0.1:8000/sales/sales_2024   # query data
```

Or open **http://127.0.0.1:8000/docs** for the interactive Swagger UI.

---

## Configuration

Supports `.yaml`, `.yml`, and `.json` formats.

### Top-level fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_returned_rows` | int | `100` | Hard cap on rows returned per query |
| `default_page_size` | int | `100` | Default page size when `_size` is not specified |
| `cors` | bool | `false` | Enable CORS headers |
| `sources` | list | `[]` | List of data source definitions |

### Source fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Alias used as `{database}` in URLs |
| `type` | string | ✅ | One of: `parquet`, `csv`, `postgresql`, `mysql` |
| `path` | string | CSV / Parquet | Absolute file path |
| `connection_string` | string | PostgreSQL / MySQL | Database connection URI |
| `options` | dict | — | Extra options (e.g. `header`, `delimiter` for CSV) |

### How table names are derived

| Source type | Table name |
|-------------|------------|
| `csv` / `parquet` | Filename stem — e.g. `sales_2024.csv` → `sales_2024` |
| `postgresql` / `mysql` | Actual table names from the database, prefixed with schema when needed (e.g. `public.orders`) |

---

## API Reference

### `GET /`

List all mounted data sources.

```bash
curl http://127.0.0.1:8000/
```

```json
{
  "databases": [
    {"name": "sales", "type": "parquet", "table_count": 1},
    {"name": "warehouse", "type": "mysql", "table_count": 42}
  ]
}
```

---

### `GET /{database}`

List tables and columns in a data source.

```bash
curl http://127.0.0.1:8000/warehouse
```

```json
{
  "database": "warehouse",
  "tables": [
    {
      "name": "orders",
      "schema": "mydb",
      "qualified_name": "mydb.orders",
      "columns": [
        {"name": "id", "type": "INTEGER"},
        {"name": "amount", "type": "DOUBLE"}
      ]
    }
  ]
}
```

---

### `GET /{database}/{table}`

Query table data.

```bash
curl "http://127.0.0.1:8000/warehouse/mydb.orders?_size=10&_shape=objects"
```

**Query parameters**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `sql` | — | Custom SELECT statement |
| `_size` | `default_page_size` | Rows per page (capped at `max_returned_rows`) |
| `_next` | `0` | Pagination cursor (row offset) |
| `_shape` | `arrays` | Response row format (see below) |

**`_shape` values**

| Value | Row format |
|-------|------------|
| `arrays` | `[1, "alice", 99.9]` |
| `objects` | `{"id": 1, "name": "alice", "amount": 99.9}` |
| `array` | Response is a bare list of objects (no wrapper fields) |
| `arrayfirst` | Each row is the value of the first column |

**Response**

```json
{
  "database": "warehouse",
  "table": "orders",
  "columns": ["id", "amount", "created_at"],
  "rows": [
    [1, 99.9, "2024-01-01"],
    [2, 149.0, "2024-01-02"]
  ],
  "truncated": true,
  "next": "100",
  "next_url": "http://127.0.0.1:8000/warehouse/orders.json?_next=100",
  "query_ms": 3.14,
  "query": {"sql": null, "params": []}
}
```

---

### `.json` suffix

All routes accept a `.json` suffix for explicit JSON responses (Datasette compatibility):

```
GET /.json
GET /{database}.json
GET /{database}/{table}.json
```

---

### CLI options

```
ducksette --config PATH [--host HOST] [--port PORT]

  --config PATH   Path to config file (YAML or JSON)  [required]
  --host HOST     Bind address                         [default: 127.0.0.1]
  --port PORT     Port to listen on                    [default: 8000]
```

---

## SQL Safety

All queries are validated before execution. Any SQL starting with a write-operation keyword is rejected with **HTTP 403**:

```
INSERT  UPDATE  DELETE  DROP  CREATE  ALTER
TRUNCATE  REPLACE  MERGE  COPY  ATTACH  DETACH
```

All data sources are also mounted in read-only mode at the DuckDB level.

---

## Error Responses

All errors use a consistent JSON envelope:

```json
{"ok": false, "error": "Database 'foo' not found", "status": 404}
```

| Status | Cause |
|--------|-------|
| `400` | SQL syntax error or runtime error |
| `403` | Write-operation SQL rejected |
| `404` | Database or table not found |
| `500` | Unexpected internal error (stack trace never exposed) |
| `503` | Data source unavailable after reconnect attempt |

---

## Development

```bash
# Run all tests
.venv/bin/pytest tests/ -q

# Run a specific test file
.venv/bin/pytest tests/test_engine.py -v

# Run property-based tests only
.venv/bin/pytest tests/ -k "property"
```

**Project layout**

```
ducksette/
├── ducksette/
│   ├── __init__.py
│   ├── __main__.py    # CLI entry point
│   ├── config.py      # Config parsing & validation
│   ├── engine.py      # QueryEngine + DuckDB integration
│   ├── errors.py      # Exception hierarchy
│   ├── security.py    # SQL safety filter
│   └── server.py      # FastAPI routes
├── tests/
│   ├── test_config.py
│   ├── test_security.py
│   ├── test_serializer.py
│   ├── test_engine.py
│   └── test_api.py
├── ducksette.yaml     # Example config
└── pyproject.toml
```

Tests use [pytest](https://pytest.org/) for unit/integration tests and [Hypothesis](https://hypothesis.readthedocs.io/) for property-based tests.

---

## License

[MIT](LICENSE)
