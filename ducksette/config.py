"""
配置解析模块：DataSourceConfig、Config dataclass，以及 load_config / dump_config 函数。

支持 YAML 和 JSON 格式；缺少必填字段时抛出 ConfigError。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from ducksette.errors import ConfigError

VALID_TYPES = frozenset({"parquet", "csv", "postgresql", "mysql"})


@dataclass
class DataSourceConfig:
    """单个数据源的配置。"""

    name: str
    type: str
    path: str | None = None
    connection_string: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("DataSourceConfig 'name' must be a non-empty string")
        if self.type not in VALID_TYPES:
            raise ConfigError(
                f"DataSourceConfig 'type' must be one of {sorted(VALID_TYPES)}, got '{self.type}'"
            )
        if self.options is None:
            self.options = {}


@dataclass
class Config:
    """全局配置对象。"""

    sources: list[DataSourceConfig] = field(default_factory=list)
    max_returned_rows: int = 100
    default_page_size: int = 100
    cors: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_data_source(raw: Any, index: int) -> DataSourceConfig:
    """将原始字典解析为 DataSourceConfig，缺少必填字段时抛出 ConfigError。"""
    if not isinstance(raw, dict):
        raise ConfigError(f"sources[{index}] must be a mapping, got {type(raw).__name__}")

    name = raw.get("name")
    if not name:
        raise ConfigError(f"sources[{index}] is missing required field 'name'")

    ds_type = raw.get("type")
    if not ds_type:
        raise ConfigError(f"sources[{index}] (name='{name}') is missing required field 'type'")
    if ds_type not in VALID_TYPES:
        raise ConfigError(
            f"sources[{index}] (name='{name}') has invalid 'type' '{ds_type}'; "
            f"must be one of {sorted(VALID_TYPES)}"
        )

    return DataSourceConfig(
        name=name,
        type=ds_type,
        path=raw.get("path"),
        connection_string=raw.get("connection_string"),
        options=raw.get("options") or {},
    )


def _parse_dict(data: dict[str, Any]) -> Config:
    """将已解析的字典转换为 Config 对象。"""
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping, got {type(data).__name__}")

    raw_sources = data.get("sources") or []
    if not isinstance(raw_sources, list):
        raise ConfigError("'sources' must be a list")

    sources = [_parse_data_source(s, i) for i, s in enumerate(raw_sources)]

    return Config(
        sources=sources,
        max_returned_rows=int(data.get("max_returned_rows", 100)),
        default_page_size=int(data.get("default_page_size", 100)),
        cors=bool(data.get("cors", False)),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(path: str) -> Config:
    """读取 YAML/JSON 配置文件，验证必填字段，返回 Config 对象。

    Args:
        path: 配置文件路径（.yaml/.yml -> YAML，.json -> JSON）。

    Returns:
        解析并验证后的 Config 对象。

    Raises:
        ConfigError: 文件不存在、格式错误或缺少必填字段时抛出。
    """
    if not os.path.exists(path):
        raise ConfigError(f"Config file not found: '{path}'")

    _, ext = os.path.splitext(path.lower())

    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        raise ConfigError(f"Cannot read config file '{path}': {exc}") from exc

    return _load_from_string(content, ext, source=path)


def _load_from_string(content: str, ext: str, source: str = "<string>") -> Config:
    """从字符串内容解析配置（供 dump_config round-trip 使用）。"""
    if ext in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise ConfigError(f"YAML parse error in '{source}': {exc}") from exc
    elif ext == ".json":
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"JSON parse error in '{source}': {exc}") from exc
    else:
        raise ConfigError(
            f"Unsupported config file extension '{ext}'; use .yaml, .yml, or .json"
        )

    if data is None:
        data = {}

    return _parse_dict(data)


def dump_config(config: Config) -> str:
    """将 Config 对象序列化为 YAML 字符串。

    Args:
        config: 要序列化的 Config 对象。

    Returns:
        YAML 格式的配置字符串，可被 load_config 重新解析（round-trip）。
    """
    sources_list = []
    for src in config.sources:
        entry: dict[str, Any] = {"name": src.name, "type": src.type}
        if src.path is not None:
            entry["path"] = src.path
        if src.connection_string is not None:
            entry["connection_string"] = src.connection_string
        if src.options:
            entry["options"] = src.options
        sources_list.append(entry)

    data: dict[str, Any] = {
        "max_returned_rows": config.max_returned_rows,
        "default_page_size": config.default_page_size,
        "cors": config.cors,
        "sources": sources_list,
    }

    return yaml.dump(data, allow_unicode=True, sort_keys=False)
