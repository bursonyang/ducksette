"""
配置解析模块单元测试。

覆盖：
- load_config / dump_config 基本功能
- YAML 和 JSON 格式支持
- 缺少必填字段时抛出 ConfigError
- 默认值正确性
"""

import json
import os
import tempfile

import pytest
import yaml

from ducksette.config import Config, DataSourceConfig, dump_config, load_config, _load_from_string
from ducksette.errors import ConfigError


# ---------------------------------------------------------------------------
# DataSourceConfig 单元测试
# ---------------------------------------------------------------------------

class TestDataSourceConfig:
    def test_minimal_valid(self):
        ds = DataSourceConfig(name="sales", type="parquet")
        assert ds.name == "sales"
        assert ds.type == "parquet"
        assert ds.path is None
        assert ds.connection_string is None
        assert ds.options == {}

    def test_full_fields(self):
        ds = DataSourceConfig(
            name="db",
            type="postgresql",
            connection_string="postgresql://localhost/db",
            options={"schema": "public"},
        )
        assert ds.connection_string == "postgresql://localhost/db"
        assert ds.options == {"schema": "public"}

    def test_invalid_type_raises(self):
        with pytest.raises(ConfigError, match="type"):
            DataSourceConfig(name="x", type="sqlite")

    def test_empty_name_raises(self):
        with pytest.raises(ConfigError, match="name"):
            DataSourceConfig(name="", type="parquet")

    def test_options_defaults_to_empty_dict(self):
        ds = DataSourceConfig(name="x", type="csv", options=None)
        assert ds.options == {}


# ---------------------------------------------------------------------------
# Config 单元测试
# ---------------------------------------------------------------------------

class TestConfig:
    def test_defaults(self):
        cfg = Config()
        assert cfg.sources == []
        assert cfg.max_returned_rows == 100
        assert cfg.default_page_size == 100
        assert cfg.cors is False


# ---------------------------------------------------------------------------
# load_config — YAML 格式
# ---------------------------------------------------------------------------

VALID_YAML = """\
max_returned_rows: 1000
default_page_size: 50
cors: true

sources:
  - name: sales
    type: parquet
    path: /data/sales.parquet
  - name: analytics
    type: postgresql
    connection_string: "postgresql://user:pass@host:5432/db"
"""


class TestLoadConfigYAML:
    def _write_tmp(self, content: str, suffix: str = ".yaml") -> str:
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "w") as f:
            f.write(content)
        return path

    def test_valid_yaml(self):
        path = self._write_tmp(VALID_YAML)
        try:
            cfg = load_config(path)
        finally:
            os.unlink(path)

        assert cfg.max_returned_rows == 1000
        assert cfg.default_page_size == 50
        assert cfg.cors is True
        assert len(cfg.sources) == 2
        assert cfg.sources[0].name == "sales"
        assert cfg.sources[0].type == "parquet"
        assert cfg.sources[1].name == "analytics"
        assert cfg.sources[1].type == "postgresql"

    def test_yml_extension(self):
        path = self._write_tmp(VALID_YAML, suffix=".yml")
        try:
            cfg = load_config(path)
        finally:
            os.unlink(path)
        assert len(cfg.sources) == 2

    def test_missing_name_raises(self):
        bad = "sources:\n  - type: parquet\n    path: /x\n"
        path = self._write_tmp(bad)
        try:
            with pytest.raises(ConfigError, match="name"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_missing_type_raises(self):
        bad = "sources:\n  - name: sales\n    path: /x\n"
        path = self._write_tmp(bad)
        try:
            with pytest.raises(ConfigError, match="type"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_invalid_type_value_raises(self):
        bad = "sources:\n  - name: sales\n    type: sqlite\n"
        path = self._write_tmp(bad)
        try:
            with pytest.raises(ConfigError, match="type"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_file_not_found_raises(self):
        with pytest.raises(ConfigError, match="not found"):
            load_config("/nonexistent/path/config.yaml")

    def test_empty_file_returns_defaults(self):
        path = self._write_tmp("", suffix=".yaml")
        try:
            cfg = load_config(path)
        finally:
            os.unlink(path)
        assert cfg.sources == []
        assert cfg.max_returned_rows == 100

    def test_unsupported_extension_raises(self):
        path = self._write_tmp(VALID_YAML, suffix=".toml")
        try:
            with pytest.raises(ConfigError, match="extension"):
                load_config(path)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# load_config — JSON 格式
# ---------------------------------------------------------------------------

VALID_JSON = {
    "max_returned_rows": 500,
    "default_page_size": 25,
    "cors": False,
    "sources": [
        {"name": "logs", "type": "csv", "path": "/data/logs.csv"},
    ],
}


class TestLoadConfigJSON:
    def _write_tmp_json(self, data: dict) -> str:
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        return path

    def test_valid_json(self):
        path = self._write_tmp_json(VALID_JSON)
        try:
            cfg = load_config(path)
        finally:
            os.unlink(path)
        assert cfg.max_returned_rows == 500
        assert len(cfg.sources) == 1
        assert cfg.sources[0].name == "logs"

    def test_missing_name_raises(self):
        bad = {"sources": [{"type": "csv", "path": "/x"}]}
        path = self._write_tmp_json(bad)
        try:
            with pytest.raises(ConfigError, match="name"):
                load_config(path)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# dump_config
# ---------------------------------------------------------------------------

class TestDumpConfig:
    def test_dump_produces_valid_yaml(self):
        cfg = Config(
            sources=[DataSourceConfig(name="sales", type="parquet", path="/data/sales.parquet")],
            max_returned_rows=200,
            default_page_size=50,
            cors=True,
        )
        output = dump_config(cfg)
        parsed = yaml.safe_load(output)
        assert parsed["max_returned_rows"] == 200
        assert parsed["cors"] is True
        assert parsed["sources"][0]["name"] == "sales"

    def test_dump_omits_none_fields(self):
        cfg = Config(sources=[DataSourceConfig(name="x", type="csv")])
        output = dump_config(cfg)
        assert "path:" not in output
        assert "connection_string:" not in output

    def test_dump_includes_options_when_present(self):
        cfg = Config(
            sources=[
                DataSourceConfig(name="x", type="csv", options={"delimiter": ","})
            ]
        )
        output = dump_config(cfg)
        parsed = yaml.safe_load(output)
        assert parsed["sources"][0]["options"]["delimiter"] == ","

    def test_dump_empty_sources(self):
        cfg = Config()
        output = dump_config(cfg)
        parsed = yaml.safe_load(output)
        assert parsed["sources"] == []


# ---------------------------------------------------------------------------
# Round-trip: dump_config -> _load_from_string
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_round_trip_basic(self):
        original = Config(
            sources=[
                DataSourceConfig(name="sales", type="parquet", path="/data/sales.parquet"),
                DataSourceConfig(
                    name="analytics",
                    type="postgresql",
                    connection_string="postgresql://user:pass@host/db",
                ),
            ],
            max_returned_rows=500,
            default_page_size=25,
            cors=True,
        )
        yaml_str = dump_config(original)
        restored = _load_from_string(yaml_str, ".yaml")

        assert restored.max_returned_rows == original.max_returned_rows
        assert restored.default_page_size == original.default_page_size
        assert restored.cors == original.cors
        assert len(restored.sources) == len(original.sources)
        for orig_src, rest_src in zip(original.sources, restored.sources):
            assert orig_src.name == rest_src.name
            assert orig_src.type == rest_src.type
            assert orig_src.path == rest_src.path
            assert orig_src.connection_string == rest_src.connection_string
            assert orig_src.options == rest_src.options

    def test_round_trip_with_options(self):
        original = Config(
            sources=[
                DataSourceConfig(
                    name="logs",
                    type="csv",
                    path="/data/logs.csv",
                    options={"header": True, "delimiter": ","},
                )
            ]
        )
        yaml_str = dump_config(original)
        restored = _load_from_string(yaml_str, ".yaml")
        assert restored.sources[0].options == {"header": True, "delimiter": ","}


# ---------------------------------------------------------------------------
# Property 13: 配置文件解析 round-trip
# ---------------------------------------------------------------------------

from hypothesis import given, settings, strategies as st


_safe_text = st.text(
    min_size=1,
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"),
)

_safe_text_or_none = st.one_of(st.none(), _safe_text)

_data_source_strategy = st.builds(
    DataSourceConfig,
    name=_safe_text,
    type=st.sampled_from(["parquet", "csv", "postgresql", "mysql"]),
    path=_safe_text_or_none,
    connection_string=_safe_text_or_none,
    options=st.dictionaries(
        _safe_text,
        st.one_of(st.booleans(), st.integers(), _safe_text),
    ),
)

_config_strategy = st.builds(
    Config,
    sources=st.lists(_data_source_strategy, max_size=5),
    max_returned_rows=st.integers(min_value=1, max_value=10000),
    default_page_size=st.integers(min_value=1, max_value=1000),
    cors=st.booleans(),
)


@settings(max_examples=100)
@given(_config_strategy)
def test_property_13_config_round_trip(config: Config) -> None:
    # Feature: ducksette, Property 13: 配置文件解析 round-trip
    # Validates: Requirements 6.1, 6.3, 6.4
    yaml_str = dump_config(config)
    restored = _load_from_string(yaml_str, ".yaml")

    assert restored.max_returned_rows == config.max_returned_rows
    assert restored.default_page_size == config.default_page_size
    assert restored.cors == config.cors
    assert len(restored.sources) == len(config.sources)

    for orig, rest in zip(config.sources, restored.sources):
        assert rest.name == orig.name
        assert rest.type == orig.type
        assert rest.path == orig.path
        assert rest.connection_string == orig.connection_string
        assert rest.options == orig.options


# ---------------------------------------------------------------------------
# Property 14: 无效配置触发 ConfigError
# ---------------------------------------------------------------------------

VALID_TYPES_SET = frozenset({"parquet", "csv", "postgresql", "mysql"})

# Strategy: dict with arbitrary keys but explicitly excluding 'name'
_dict_without_name = st.dictionaries(
    keys=st.text(min_size=1).filter(lambda k: k != "name"),
    values=st.one_of(st.text(), st.integers(), st.booleans(), st.none()),
    min_size=0,
    max_size=5,
)

# Strategy: dict with arbitrary keys but explicitly excluding 'type'
_dict_without_type = st.dictionaries(
    keys=st.text(min_size=1).filter(lambda k: k != "type"),
    values=st.one_of(st.text(), st.integers(), st.booleans(), st.none()),
    min_size=0,
    max_size=5,
).map(lambda d: {**d, "name": "test_source"})

# Strategy: dict with a 'name' and an invalid 'type' value
_invalid_type_value = st.text().filter(lambda t: t not in VALID_TYPES_SET)

_dict_with_invalid_type = st.fixed_dictionaries(
    {"name": st.text(min_size=1), "type": _invalid_type_value}
)


@settings(max_examples=100)
@given(_dict_without_name)
def test_property_14_missing_name_raises_config_error(source_dict: dict) -> None:
    # Feature: ducksette, Property 14: 无效配置触发 ConfigError
    # Validates: Requirements 6.2
    config_dict = {"sources": [source_dict]}
    content = yaml.dump(config_dict)
    with pytest.raises(ConfigError) as exc_info:
        _load_from_string(content, ".yaml")
    assert "name" in str(exc_info.value).lower()


@settings(max_examples=100)
@given(_dict_without_type)
def test_property_14_missing_type_raises_config_error(source_dict: dict) -> None:
    # Feature: ducksette, Property 14: 无效配置触发 ConfigError
    # Validates: Requirements 6.2
    config_dict = {"sources": [source_dict]}
    content = yaml.dump(config_dict)
    with pytest.raises(ConfigError) as exc_info:
        _load_from_string(content, ".yaml")
    assert "type" in str(exc_info.value).lower()


@settings(max_examples=100)
@given(_dict_with_invalid_type)
def test_property_14_invalid_type_value_raises_config_error(source_dict: dict) -> None:
    # Feature: ducksette, Property 14: 无效配置触发 ConfigError
    # Validates: Requirements 6.2
    config_dict = {"sources": [source_dict]}
    content = yaml.dump(config_dict)
    with pytest.raises(ConfigError) as exc_info:
        _load_from_string(content, ".yaml")
    assert "type" in str(exc_info.value).lower()
