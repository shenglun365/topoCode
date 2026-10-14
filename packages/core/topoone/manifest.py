"""App Manifest — 子项目自描述契约。

每个子项目（apps/<name>/manifest.toml）声明自己的进程/静态/路由归属，
使 gateway（静态托管+反代+RPC 路由）与 supervisor（进程注册）零硬编码。

字段语义：
  kind:
    "core"    — 后端方法注册进核心引擎进程（无独立进程，python_entry 为注册函数）
    "service" — 独立服务进程（supervisor 拉起，须有 port/python_entry）
  python_entry:
    ""                          — kind=core 且尚未切出（过渡态：核心进程仍自注册）
    "module:func"               — 包已建（如 "topoone_app_docs:main"）
    仓库根相对脚本路径(.py)      — 过渡期（如 "backend-core/doc_service_app.py"）
  static_dir   — 前端构建产物目录（相对仓库根）
  static_mount — gateway 静态挂载点列表（空 = 服务自托管静态，gateway 不挂）
  api_prefixes — gateway 反向代理前缀（页面路径与 API 路径均可，最长前缀优先匹配）
  rpc_namespaces — /api/rpc 命名空间路由归属：
      kind=core   → 路由到 kb（核心引擎进程，方法在进程内注册）
      kind=service → 路由到本服务端口

约束（load_manifest / validate_registry 强制）：
  - kind=service 必须有 port 与非空 python_entry
  - api_prefixes 不得占用网关保留前缀（RESERVED_API_PREFIXES）
  - 多 app 之间 rpc_namespaces / api_prefixes / static_mount / port 不得冲突
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10（项目依赖 tomli）
    import tomli as tomllib  # type: ignore

KIND_CORE = "core"
KIND_SERVICE = "service"
_VALID_KINDS = (KIND_CORE, KIND_SERVICE)

# 网关保留前缀：app 不得声明（网关自身功能：RPC 路由/聚合健康/事件桥/鉴权/静态资源）。
# 规则：相等或声明前缀是保留前缀的子路径 → 冲突。
RESERVED_API_PREFIXES: Tuple[str, ...] = (
    "/api/rpc",
    "/api/health",
    "/api/upload",
    "/ws",
    "/health",
    "/static",
)

# 仅"整段占用"冲突的网关挂载点：app 可以声明其子路径（如 /web/architect 资源），
# 但不得声明整段（如 /web 本身——web SPA 资产挂载归 gateway）。
RESERVED_EXACT_PREFIXES: Tuple[str, ...] = (
    "/web",
    "/app",
)

# 核心固定服务端口（非 app manifest 管辖，用于冲突检测）
CORE_FIXED_PORTS: Dict[str, int] = {
    "kb": 3459,
    "gateway": 3456,
    "llm": 3484,
    "agent": 3482,
    "mcp": 3460,
    "runner": 3458,
}

_MODULE_FUNC_RE = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)*:[A-Za-z_][\w]*$")


class ManifestError(ValueError):
    """manifest 解析或校验失败。"""


@dataclass
class AppManifest:
    name: str
    kind: str
    python_entry: str = ""
    static_dir: Optional[str] = None
    static_mount: List[str] = field(default_factory=list)
    api_prefixes: List[str] = field(default_factory=list)
    rpc_namespaces: List[str] = field(default_factory=list)
    port: Optional[int] = None
    pub_port: Optional[int] = None
    host: str = "127.0.0.1"
    health: str = "/health"
    env: Dict[str, str] = field(default_factory=dict)
    source: str = ""  # manifest 文件路径（调试用）

    @property
    def service_url(self) -> Optional[str]:
        """gateway 反代目标 base url（kind=service 且 port 存在时）。"""
        if self.kind == KIND_SERVICE and self.port:
            return f"http://{self.host}:{self.port}"
        return None

    def python_entry_is_module(self) -> bool:
        return bool(self.python_entry) and bool(_MODULE_FUNC_RE.match(self.python_entry))


def _as_str_list(value, field_name: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ManifestError(f"field '{field_name}' must be a list of strings")
    return list(value)


def _as_str_map(value, field_name: str) -> Dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ManifestError(f"field '{field_name}' must be a map of string->string")
    return dict(value)


def _check_prefix_conflict(prefix: str) -> None:
    if not prefix.startswith("/"):
        raise ManifestError(f"api_prefix '{prefix}' must start with '/'")
    for r in RESERVED_API_PREFIXES:
        # 相等、或声明前缀是保留前缀的子路径、或保留前缀是声明前缀的子路径 → 冲突
        if prefix == r or prefix.startswith(r.rstrip("/") + "/") or r.startswith(prefix.rstrip("/") + "/"):
            raise ManifestError(
                f"api_prefix '{prefix}' conflicts with reserved gateway prefix '{r}'"
            )
    for r in RESERVED_EXACT_PREFIXES:
        # 仅整段占用冲突（子路径合法，如 /web/architect）
        if prefix.rstrip("/") == r:
            raise ManifestError(
                f"api_prefix '{prefix}' claims gateway-owned mount '{r}' entirely"
            )


def _validate_single(m: AppManifest) -> None:
    if not m.name or "/" in m.name:
        raise ManifestError(f"invalid app name: {m.name!r}")
    if m.kind not in _VALID_KINDS:
        raise ManifestError(f"app '{m.name}': kind must be one of {_VALID_KINDS}")
    if m.kind == KIND_SERVICE:
        if not m.port:
            raise ManifestError(f"app '{m.name}': kind=service requires 'port'")
        if not m.python_entry:
            raise ManifestError(f"app '{m.name}': kind=service requires 'python_entry'")
    else:  # core
        if m.port is not None:
            raise ManifestError(f"app '{m.name}': kind=core must not declare 'port'")
    if m.python_entry and not (
        m.python_entry.endswith(".py") or m.python_entry_is_module()
    ):
        raise ManifestError(
            f"app '{m.name}': python_entry must be '' | 'module:func' | '*.py' script path, "
            f"got {m.python_entry!r}"
        )
    if m.static_dir is not None and not m.static_dir:
        raise ManifestError(f"app '{m.name}': static_dir must be non-empty or omitted")
    for mount in m.static_mount:
        if not mount.startswith("/"):
            raise ManifestError(f"app '{m.name}': static_mount '{mount}' must start with '/'")
    for prefix in m.api_prefixes:
        _check_prefix_conflict(prefix)
    for ns in m.rpc_namespaces:
        if not ns or "." in ns or "/" in ns:
            raise ManifestError(f"app '{m.name}': invalid rpc_namespace {ns!r}")
    if m.health and not m.health.startswith("/"):
        raise ManifestError(f"app '{m.name}': health must start with '/'")


def load_manifest(path: str | Path) -> AppManifest:
    """解析并校验单个 manifest.toml。app.name 必须与父目录名一致。"""
    path = Path(path)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    app = data.get("app", {})
    if not isinstance(app, dict):
        raise ManifestError(f"{path}: missing [app] table")
    name = app.get("name")
    expected = path.parent.name
    if name != expected:
        raise ManifestError(
            f"{path}: app.name '{name}' != parent dir name '{expected}'"
        )
    m = AppManifest(
        name=name,
        kind=str(app.get("kind", "")),
        python_entry=str(app.get("python_entry", "") or ""),
        static_dir=app.get("static_dir"),
        static_mount=_as_str_list(app.get("static_mount"), "static_mount"),
        api_prefixes=_as_str_list(app.get("api_prefixes"), "api_prefixes"),
        rpc_namespaces=_as_str_list(app.get("rpc_namespaces"), "rpc_namespaces"),
        port=app.get("port"),
        pub_port=app.get("pub_port"),
        host=str(app.get("host", "127.0.0.1")),
        health=str(app.get("health", "/health")),
        env=_as_str_map(app.get("env"), "env"),
        source=str(path),
    )
    if m.port is not None and not isinstance(m.port, int):
        raise ManifestError(f"{path}: 'port' must be an integer")
    if m.pub_port is not None and not isinstance(m.pub_port, int):
        raise ManifestError(f"{path}: 'pub_port' must be an integer")
    _validate_single(m)
    return m


def discover_apps(root: str | Path) -> Dict[str, AppManifest]:
    """扫描 root/apps/*/manifest.toml，返回 {name: AppManifest}。

    root 为仓库根目录。目录不存在时返回空 dict（骨架阶段允许）。
    """
    apps_root = Path(root) / "apps"
    found: Dict[str, AppManifest] = {}
    if not apps_root.is_dir():
        return found
    for entry in sorted(apps_root.iterdir()):
        manifest_path = entry / "manifest.toml"
        if entry.is_dir() and manifest_path.is_file():
            m = load_manifest(manifest_path)
            found[m.name] = m
    return found


def _overlaps(a: str, b: str) -> bool:
    """两个 URL 前缀是否存在包含关系（相等或一方为另一方的子路径）。"""
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def validate_registry(apps: Dict[str, AppManifest]) -> List[str]:
    """跨 app 冲突检测，返回错误列表（空 = 通过）。

    检查：
      1. rpc_namespaces 全局唯一（核心固定命名空间除外，由调用方保证）
      2. api_prefixes 全局无包含冲突
      3. static_mount 全局唯一
      4. service 端口互不冲突，且不与核心固定服务端口冲突
    """
    errors: List[str] = []
    seen_ns: Dict[str, str] = {}
    for m in apps.values():
        for ns in m.rpc_namespaces:
            if ns in seen_ns:
                errors.append(
                    f"rpc_namespace '{ns}' claimed by both '{seen_ns[ns]}' and '{m.name}'"
                )
            else:
                seen_ns[ns] = m.name
    names = list(apps)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = apps[names[i]], apps[names[j]]
            for pa in a.api_prefixes:
                for pb in b.api_prefixes:
                    if _overlaps(pa, pb):
                        errors.append(
                            f"api_prefix conflict: '{a.name}'/'{pa}' overlaps '{b.name}'/'{pb}'"
                        )
            for ma in a.static_mount:
                for mb in b.static_mount:
                    if ma == mb:
                        errors.append(
                            f"static_mount conflict: '{ma}' claimed by both "
                            f"'{a.name}' and '{b.name}'"
                        )
            if a.kind == KIND_SERVICE and b.kind == KIND_SERVICE and a.port == b.port:
                errors.append(
                    f"port conflict: {a.port} used by both '{a.name}' and '{b.name}'"
                )
    for m in apps.values():
        if m.kind != KIND_SERVICE or not m.port:
            continue
        for svc, port in CORE_FIXED_PORTS.items():
            if m.port == port:
                errors.append(
                    f"port conflict: app '{m.name}' port {m.port} equals core service "
                    f"'{svc}' fixed port"
                )
    return errors
