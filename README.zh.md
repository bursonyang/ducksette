# Ducksette

> 基于 DuckDB 的数据浏览服务，提供与 [Datasette](https://datasette.io/) 兼容的 HTTP API。

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Ducksette 通过统一的只读 HTTP 接口浏览异构数据源——Parquet 文件、CSV 文件、PostgreSQL、MySQL。底层使用 DuckDB 的 `ATTACH` 机制，路由结构和 JSON 响应格式与 Datasette 保持兼容，现有 Datasette 客户端无需修改即可使用。

[English README](README.md)

---

## 目录

- [特性](#特性)
- [安装](#安装)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 参考](#api-参考)
- [SQL 安全](#sql-安全)
- [错误响应](#错误响应)
- [开发](#开发)
- [License](#license)

---

## 特性

- **多数据源** — Parquet、CSV、PostgreSQL、MySQL，通过 DuckDB ATTACH 统一挂载
- **Datasette 兼容** — 相同路由、相同 JSON 格式、支持 `.json` 后缀
- **强制只读** — 写操作 SQL 直接返回 HTTP 403
- **分页支持** — 基于游标的分页，`_next` + `_size` 参数
- **灵活响应格式** — `arrays`、`objects`、`array`、`arrayfirst`
- **Swagger UI** — 访问 `/docs` 使用交互式 API 文档
- **结构化访问日志** — 每个请求记录方法、路径、状态码、耗时
- **优雅降级** — 启动时单个数据源失败不影响其他；连接断开时自动重连一次

---

## 安装

需要 Python 3.10+，推荐使用 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/yourname/ducksette.git
cd ducksette

uv venv .venv --python 3.11
uv pip install -e ".[dev]" --python .venv/bin/python
```

<details>
<summary>使用 pip</summary>

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
</details>

---

## 快速开始

**1. 创建配置文件**

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

**2. 启动服务**

```bash
.venv/bin/ducksette --config ducksette.yaml
# INFO  Successfully mounted data sources: ['sales', 'logs', 'analytics', 'warehouse']
# INFO  Uvicorn running on http://127.0.0.1:8000
```

**3. 开始查询**

```bash
curl http://127.0.0.1:8000/          # 列出所有数据源
curl http://127.0.0.1:8000/sales     # 列出 sales 下的表
curl http://127.0.0.1:8000/sales/sales_2024   # 查询数据
```

或打开 **http://127.0.0.1:8000/docs** 使用 Swagger UI。

---

## 配置说明

支持 `.yaml`、`.yml`、`.json` 格式。

### 顶层字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_returned_rows` | int | `100` | 单次查询最大返回行数上限 |
| `default_page_size` | int | `100` | 未指定 `_size` 时的默认每页行数 |
| `cors` | bool | `false` | 是否启用 CORS |
| `sources` | list | `[]` | 数据源列表 |

### 数据源字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 数据源别名，用作 URL 中的 `{database}` |
| `type` | string | ✅ | 类型：`parquet`、`csv`、`postgresql`、`mysql` |
| `path` | string | CSV/Parquet 必填 | 文件绝对路径 |
| `connection_string` | string | PostgreSQL/MySQL 必填 | 数据库连接串 |
| `options` | dict | 否 | 额外选项（如 CSV 的 `header`、`delimiter`） |

### 表名规则

| 数据源类型 | 表名来源 |
|------------|----------|
| `csv` / `parquet` | 文件名（去掉路径和扩展名），如 `sales_2024.csv` → `sales_2024` |
| `postgresql` / `mysql` | 数据库中的实际表名，多 schema 时格式为 `schema.table` |

---

## API 参考

### `GET /`

列出所有已挂载数据源。

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

列出指定数据源下的所有表及列信息。

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

查询表数据。

```bash
curl "http://127.0.0.1:8000/warehouse/mydb.orders?_size=10&_shape=objects"
```

**查询参数**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `sql` | — | 自定义 SELECT 语句 |
| `_size` | `default_page_size` | 每页行数（不超过 `max_returned_rows`） |
| `_next` | `0` | 分页游标（行偏移量） |
| `_shape` | `arrays` | 响应数据格式（见下表） |

**`_shape` 取值**

| 值 | rows 格式 |
|----|-----------|
| `arrays`（默认） | `[1, "alice", 99.9]` |
| `objects` | `{"id": 1, "name": "alice", "amount": 99.9}` |
| `array` | 响应直接为对象数组（无外层包装字段） |
| `arrayfirst` | 每行为第一列的值 |

**响应示例**

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

### `.json` 后缀

所有路由均支持 `.json` 后缀（Datasette 兼容）：

```
GET /.json
GET /{database}.json
GET /{database}/{table}.json
```

---

### CLI 参数

```
ducksette --config PATH [--host HOST] [--port PORT]

  --config PATH   配置文件路径（YAML 或 JSON）  [必填]
  --host HOST     监听地址                       [默认: 127.0.0.1]
  --port PORT     监听端口                       [默认: 8000]
```

---

## SQL 安全

所有查询在执行前都会经过安全校验。以下关键字开头的 SQL 会被拒绝，返回 **HTTP 403**：

```
INSERT  UPDATE  DELETE  DROP  CREATE  ALTER
TRUNCATE  REPLACE  MERGE  COPY  ATTACH  DETACH
```

所有数据源在 DuckDB 层面也以只读模式挂载。

---

## 错误响应

所有错误统一格式：

```json
{"ok": false, "error": "Database 'foo' not found", "status": 404}
```

| 状态码 | 触发条件 |
|--------|----------|
| `400` | SQL 语法错误或运行时错误 |
| `403` | 写操作 SQL 被拒绝 |
| `404` | 数据库或表不存在 |
| `500` | 服务内部错误（不暴露堆栈信息） |
| `503` | 数据源连接断开且重连失败 |

---

## 开发

```bash
# 运行所有测试
.venv/bin/pytest tests/ -q

# 运行单个测试文件
.venv/bin/pytest tests/test_engine.py -v

# 只运行属性测试
.venv/bin/pytest tests/ -k "property"
```

**项目结构**

```
ducksette/
├── ducksette/
│   ├── __init__.py
│   ├── __main__.py    # CLI 入口
│   ├── config.py      # 配置解析与验证
│   ├── engine.py      # QueryEngine + DuckDB 集成
│   ├── errors.py      # 异常层次
│   ├── security.py    # SQL 安全过滤
│   └── server.py      # FastAPI 路由
├── tests/
│   ├── test_config.py
│   ├── test_security.py
│   ├── test_serializer.py
│   ├── test_engine.py
│   └── test_api.py
├── ducksette.yaml     # 示例配置
└── pyproject.toml
```

测试使用 [pytest](https://pytest.org/) 做单元/集成测试，[Hypothesis](https://hypothesis.readthedocs.io/) 做属性测试。

---

## License

[MIT](LICENSE)
