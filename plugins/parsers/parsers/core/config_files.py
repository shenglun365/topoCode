"""配置文件键值提取 — yaml/json/env/toml/ini(单文件、只读)。

产出 [{key, value, line}]：key 为完整点分路径，value 为标量文本(截断)。
供 architect 实现层 rule(config_item) 资产提取配置项与阈值。

best-effort: 解析失败 → 回退行级正则或空列表，不抛异常。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

MAX_KEYS_PER_FILE = 500
MAX_VALUE_CHARS = 200
_MAX_DEPTH = 6


def _cap(value: Any) -> str:
    s = str(value) if value is not None else ""
    return s[:MAX_VALUE_CHARS]


def _yaml_keys(text: str) -> list[dict]:
    out: list[dict] = []
    try:
        import yaml
        root = yaml.compose(text)
    except Exception:
        return _yaml_keys_regex(text)

    def walk(node, prefix: str, depth: int) -> None:
        if depth > _MAX_DEPTH or len(out) >= MAX_KEYS_PER_FILE:
            return
        if node is None:
            return
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                if not isinstance(k, yaml.ScalarNode):
                    continue
                key = f"{prefix}.{k.value}" if prefix else str(k.value)
                line = (k.start_mark.line + 1) if k.start_mark else 0
                if isinstance(v, yaml.ScalarNode):
                    out.append({"key": key, "value": _cap(v.value), "line": line})
                elif isinstance(v, yaml.MappingNode):
                    walk(v, key, depth + 1)
                elif isinstance(v, yaml.SequenceNode):
                    out.append({"key": key, "value": f"[{len(v.value)} items]", "line": line})
        elif isinstance(node, yaml.SequenceNode) and not prefix:
            pass  # 顶层数组无键，忽略

    walk(root, "", 0)
    return out


_YAML_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*:\s*(.+?)\s*(?:#.*)?$")


def _yaml_keys_regex(text: str) -> list[dict]:
    out: list[dict] = []
    for i, ln in enumerate(text.split("\n"), 1):
        if ln.strip().startswith("-") or ln.strip().startswith("#"):
            continue
        m = _YAML_LINE_RE.match(ln)
        if m:
            v = m.group(2).strip().strip("'\"")
            if v:
                out.append({"key": m.group(1), "value": _cap(v), "line": i})
        if len(out) >= MAX_KEYS_PER_FILE:
            break
    return out


def _json_keys(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except Exception:
        return []
    out: list[dict] = []

    def find_line(key: str) -> int:
        m = re.search(r'["\']%s["\']\s*:' % re.escape(key), text)
        if not m:
            return 0
        return text.count("\n", 0, m.start()) + 1

    def walk(obj: Any, prefix: str, depth: int) -> None:
        if depth > _MAX_DEPTH or len(out) >= MAX_KEYS_PER_FILE:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, (dict, list)):
                    walk(v, key, depth + 1)
                else:
                    out.append({"key": key, "value": _cap(v), "line": find_line(str(k))})
    walk(data, "", 0)
    return out


_ENV_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][\w]*)\s*=\s*(.*)$")


def _env_keys(text: str) -> list[dict]:
    out: list[dict] = []
    for i, ln in enumerate(text.split("\n"), 1):
        s = ln.strip()
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        m = _ENV_RE.match(s)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out.append({"key": m.group(1), "value": _cap(v), "line": i})
        if len(out) >= MAX_KEYS_PER_FILE:
            break
    return out


def _toml_keys(text: str) -> list[dict]:
    try:
        import tomli
        data = tomli.loads(text)
    except Exception:
        return []
    out: list[dict] = []

    def walk(obj: Any, prefix: str, depth: int) -> None:
        if depth > _MAX_DEPTH or len(out) >= MAX_KEYS_PER_FILE:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, dict):
                    walk(v, key, depth + 1)
                else:
                    out.append({"key": key, "value": _cap(v), "line": 0})
    walk(data, "", 0)
    return out


def parse_config_file(file_path: str, text: str) -> list[dict]:
    """按扩展名分发配置文件键值提取。"""
    base = os.path.basename(file_path or "")
    ext = os.path.splitext(base)[1].lower()
    if not ext and len(base) > 1 and base.startswith("."):
        ext = base  # .env 等隐藏文件
    text = text or ""
    if not text:
        return []
    try:
        if ext in (".yaml", ".yml"):
            out = _yaml_keys(text)
        elif ext == ".json":
            out = _json_keys(text)
        elif ext in (".env", ".ini", ".properties"):
            out = _env_keys(text)
        elif ext == ".toml":
            out = _toml_keys(text)
        else:
            out = []
    except Exception as e:
        logger.warning("config parse failed for %s: %s", file_path, e)
        out = []
    return out[:MAX_KEYS_PER_FILE]
