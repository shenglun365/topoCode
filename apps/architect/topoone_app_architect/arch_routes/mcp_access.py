"""执行器 MCP 接入辅助(2610)——cline/opencode/qwen-code/codex 探测+一键接入。

对每家执行器:
- 探测: 可执行文件/扩展目录 + 配置文件存在性 + 是否已接入 topo-architect;
- 接入: 合并写入其 MCP 配置(保留既有键, 写前 .bak 备份), 幂等(已配置=already)。

形态单源(业界事实, 2026-10 官方文档):
- cline       JSON  .cline/mcp_settings.json(项目) / VS Code globalStorage(全局)
              远程形态 {transportType: streamableHttp, url}
- opencode    JSON  opencode.json(项目/全局 ~/.config/opencode)
              {mcp: {topo-architect: {type: remote, url, enabled: true}}}
- qwen-code   JSON  .qwen/settings.json(项目) / ~/.qwen/settings.json(全局)
              gemini-cli 风格 {mcpServers: {topo-architect: {httpUrl: url}}}
- codex       TOML  ~/.codex/config.toml(仅全局)
              stdio [mcp_servers.topo-architect](command=sys.executable + 数据目录)

stdio 需同机 python 环境; cline/opencode/qwen 默认走 HTTP(architect 已在跑,
零依赖); codex 无稳定 HTTP 支持故 stdio(用 architect 自身解释器, 包可达)。
"""
from __future__ import annotations

import glob
import json
import logging
import os
import shutil
from typing import Any, Dict, Optional

from fastapi import APIRouter
from fastapi import Request

from ..common import err, ok

logger = logging.getLogger("arch_routes.mcp_access")

router = APIRouter()

SERVER_KEY = "topo-architect"
_MARKER = SERVER_KEY  # 各配置文件中的接入标记(键名命中即视为已接入)

# vscode cline 全局配置候选(Linux 主, 附 mac/win 常见路径)
_CLINE_GLOBAL_GLOBS = [
    "~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
    "~/.vscode-server/data/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
    "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
]


def _first_path(patterns: list) -> str:
    for p in patterns:
        hits = sorted(glob.glob(os.path.expanduser(p)))
        if hits:
            return hits[0]
    return ""


def _home() -> str:
    """用户目录(可注入隔离: TOPOCODE_MCP_HOME, 测试防写真实 HOME)。"""
    return os.environ.get("TOPOCODE_MCP_HOME") or os.path.expanduser("~")


def _targets(root: str) -> Dict[str, Dict[str, Any]]:
    """key → {kind, global: path|"", project: path|""}。"""
    home_global_cline = _first_path(_CLINE_GLOBAL_GLOBS)
    if not home_global_cline:
        # 接入时按平台主候选生成(不探测也可见路径)
        home_global_cline = os.path.join(_home(), _CLINE_GLOBAL_GLOBS[0]
                                         .replace("~/", ""))
    return {
        "cline": {
            "kind": "json-cline",
            "global": home_global_cline,
            "project": os.path.join(root or "", ".cline", "mcp_settings.json"),
        },
        "opencode": {
            "kind": "json-opencode",
            "global": os.path.join(_home(), ".config/opencode/opencode.json"),
            "project": os.path.join(root or "", "opencode.json"),
        },
        "qwen-code": {
            "kind": "json-gemini",
            "global": os.path.join(_home(), ".qwen/settings.json"),
            "project": os.path.join(root or "", ".qwen", "settings.json"),
        },
        "codex": {
            "kind": "toml-codex",
            "global": os.path.join(_home(), ".codex/config.toml"),
            "project": "",
        },
    }


def _detect_bin(key: str) -> bool:
    if key == "cline":
        return bool(_first_path(["~/.vscode/extensions/saoudrizwan.claude-dev*",
                                 "~/.vscode-server/extensions/saoudrizwan.claude-dev*"]))
    if key == "opencode":
        return bool(shutil.which("opencode"))
    if key == "qwen-code":
        return bool(shutil.which("qwen") or shutil.which("qwen-code"))
    if key == "codex":
        return bool(shutil.which("codex"))
    return False


def _configured(path: str, kind: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
        text = open(path, encoding="utf-8").read()
    except Exception:  # noqa: BLE001
        return False
    if kind == "toml-codex":
        return f"[mcp_servers.{_MARKER}]" in text or f'"{_MARKER}"' in text
    return f'"{_MARKER}"' in text


def _codex_stdio() -> Dict[str, Any]:
    import sys
    from .. import ctx
    return {"command": sys.executable,
            "args": ["-m", "topoone_app_architect.mcp"],
            "env": {"TOPOCODE_DATA_DIR": ctx.data_dir()}}


def inspect_executors(root: str = "") -> list:
    targets = _targets(root)
    rows = []
    for key, t in targets.items():
        rows.append({
            "key": key,
            "installed": _detect_bin(key),
            "kind": t["kind"],
            "scopes": {
                scope: ({"path": path,
                         "exists": bool(path) and os.path.isfile(path),
                         "configured": _configured(path, t["kind"])}
                        if path else None)
                for scope, path in (("global", t["global"]),
                                    ("project", t["project"]))
            },
        })
    return rows


def _load_json(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        data = json.loads(open(path, encoding="utf-8").read())
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — 坏 JSON 不吞用户文件: 报错由调用方提示
        raise


def _entry(kind: str, url: str) -> Dict[str, Any]:
    if kind == "json-cline":
        return {"type": "streamableHttp", "transportType": "streamableHttp",
                "url": url, "alwaysAllow": []}
    if kind == "json-opencode":
        return {"type": "remote", "url": url, "enabled": True}
    if kind == "json-gemini":
        return {"httpUrl": url}
    raise ValueError(kind)


def apply_access(key: str, scope: str, root: str, url: str) -> Dict[str, Any]:
    """合并写入(幂等): 已配置 → already; 写前 .bak 备份既有文件。"""
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return {"error": "url 须为 http(s) 地址"}
    targets = _targets(root)
    if key not in targets:
        return {"error": f"未知执行器: {key}"}
    t = targets[key]
    path = t.get(scope) or ""
    if not path:
        return {"error": f"{key} 不支持 {scope} 接入(scope 仅 global)"}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    if t["kind"] == "toml-codex":
        text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
        if f"[mcp_servers.{_MARKER}]" in text:
            return {"written": False, "already": True, "path": path}
        if text and not text.endswith("\n"):
            text += "\n"
        stdio = _codex_stdio()
        block = (f"\n[mcp_servers.{_MARKER}]\n"
                 f'command = "{stdio["command"]}"\n'
                 f'args = ["-m", "topoone_app_architect.mcp"]\n'
                 f"env = {{ TOPOCODE_DATA_DIR = \"{stdio['env']['TOPOCODE_DATA_DIR']}\" }}\n")
        _backup(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + block)
        return {"written": True, "already": False, "path": path,
                "entry": stdio}

    try:
        data = _load_json(path) if os.path.isfile(path) else {}
    except Exception:  # noqa: BLE001 — 坏 JSON 不吞用户文件
        return {"error": "配置文件不是合法 JSON——请手工修复后重试: " + path}
    if kind_scope_marker(t["kind"], data):
        return {"written": False, "already": True, "path": path}
    entry = _entry(t["kind"], url)
    if t["kind"] == "json-opencode":
        data.setdefault("mcp", {})[_MARKER] = entry
    else:  # cline / gemini 风格 mcpServers
        data.setdefault("mcpServers", {})[_MARKER] = entry
    _backup(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return {"written": True, "already": False, "path": path, "entry": entry}


def kind_scope_marker(kind: str, data: Dict[str, Any]) -> bool:
    if kind == "json-opencode":
        return _MARKER in (data.get("mcp") or {})
    return _MARKER in (data.get("mcpServers") or {})


def _backup(path: str) -> None:
    if os.path.isfile(path):
        bak = path + ".bak"
        try:
            open(bak, "wb").write(open(path, "rb").read())
        except Exception:  # noqa: BLE001 — 备份失败不阻塞(内容已在内存)
            logger.warning("[mcp-access] .bak 备份失败: %s", bak)


def _http_url(raw: str) -> str:
    u = (raw or "").strip()
    if not u.startswith("http://") and not u.startswith("https://"):
        raise ValueError("url 须为 http(s) 地址")
    return u


@router.get("/arch/mcp-access")
async def api_mcp_access(root: str = ""):
    """四执行器探测(安装态/配置文件/接入态)。"""
    return ok(inspect_executors(root or ""))


@router.post("/arch/mcp-access/apply")
async def api_mcp_access_apply(request: Request):
    """一键接入 {executor, scope: global|project, root, url}(幂等合并)。"""
    body = await request.json() or {}
    try:
        url = _http_url(str(body.get("url") or ""))
    except ValueError as e:
        return err(400, str(e))
    res = apply_access(str(body.get("executor") or ""),
                       str(body.get("scope") or "global"),
                       str(body.get("root") or ""), url)
    if res.get("error"):
        return err(400, res["error"])
    return ok(res)
