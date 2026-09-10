"""三方 Coding Agent 执行器注册表 — architect 侧配置面。

存储：arch_collab_config["agent.executors"]（JSON 列表），
条目 {id, type, enabled, default, config{...}}，type ∈
  opencode      会话化 opencode serve（自动拉起/权限自动应答/会话 diff）
  cline-sdk     Cline sidecar（architect 自主模式，@cline/sdk 内嵌）
  cli           一次性 CLI 命令模板（codex exec / claude -p 兜底）
  serve-generic 旧一次性 serve 端点（/run 协议）
  mock          测试用

runner 启动经 GET /agent/executors/runtime 拉取（X-Internal token）；
保存后 POST {RUNNER}/api/executors/refresh 原子换池。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Request

from .common import _ts, ok, err
from . import store

logger = logging.getLogger(__name__)
router = APIRouter()

CONFIG_KEY = "agent.executors"
RUNNER_BASE_URL = os.environ.get("RUNNER_BASE_URL", "http://127.0.0.1:3458")

DEFAULT_EXECUTORS = [
    {
        "id": "opencode", "type": "opencode", "enabled": True, "default": True,
        "config": {"auto_start": True, "base_port": 3478, "permission": "auto",
                   "timeout": 1800, "model": ""},
    },
    {
        "id": "cline", "type": "cline-sdk", "enabled": True, "default": False,
        "config": {"node_bin": "node", "sidecar_script": "", "provider_id": "",
                   "model_id": "", "api_key": "", "max_iterations": 40},
    },
]

_TYPES = {"opencode", "cline-sdk", "cli", "serve-generic", "codex-server", "remote-agent", "mock"}
_SECRET_KEYS = {"api_key"}
_HOSTS = {"local", "remote"}


def _norm_models(raw) -> list:
    """实例内模型列表归一化: [{id, name, model, url, apiKey?, maxTokens?}]。"""
    out = []
    for i, m in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()
        model = str(m.get("model") or "").strip()
        if not name or not model:
            continue
        out.append({
            "id": m.get("id") or f"m{i + 1}",
            "name": name, "model": model,
            "url": str(m.get("url") or "").strip(),
            "apiKey": str(m.get("apiKey") or "").strip(),
            "maxTokens": int(m.get("maxTokens") or 0),
        })
    return out


def load_executors() -> list[dict]:
    raw = store.CollabConfigStore.get(CONFIG_KEY, "")
    if not raw:
        return json.loads(json.dumps(DEFAULT_EXECUTORS))
    try:
        entries = json.loads(raw)
        return entries if isinstance(entries, list) else []
    except Exception:  # noqa: BLE001
        return []


def save_executors(entries: list[dict]) -> None:
    store.CollabConfigStore.set(CONFIG_KEY, json.dumps(entries, ensure_ascii=False))


def _normalize(entries: list[dict]) -> list[dict]:
    """旧数据兜底: PR2 之前的存量注册项缺 host 字段 → 默认 local。

    不兜底会导致: GET 返回 host=None(前端下拉显示空) 且 PUT 校验
    e.get("host", "local") 命中已存在的 None 值而误判非法。
    """
    for e in entries:
        if not e.get("host"):
            e["host"] = "local"
        if "enabled" not in e:
            e["enabled"] = True
    return entries


def _validate(entries: list[dict]) -> Optional[str]:
    ids = set()
    defaults = 0
    for e in entries:
        eid = (e.get("id") or "").strip()
        if not eid:
            return "执行器 id 不能为空"
        if eid in ids:
            return f"执行器 id 重复: {eid}"
        ids.add(eid)
        if e.get("type") not in _TYPES:
            return f"未知执行器类型: {e.get('type')}"
        if e.get("host", "local") not in _HOSTS:
            return f"非法 host: {e.get('host')}(local|remote)"
        cfg = e.get("config") or {}
        cfg["models"] = _norm_models(cfg.get("models"))
        names = [m["name"] for m in cfg["models"]]
        if len(names) != len(set(names)):
            return f"执行器 {eid} 模型名称重复"
        if e.get("default"):
            defaults += 1
    if defaults > 1:
        return "只能有一个默认执行器"
    return None


def _mask(entries: list[dict]) -> list[dict]:
    out = []
    for e in entries:
        cfg = dict(e.get("config") or {})
        for k in _SECRET_KEYS:
            if cfg.get(k):
                cfg[k] = "******"
        cfg["models"] = [
            {**m, "apiKey": "******"} if m.get("apiKey") else m
            for m in cfg.get("models") or []
        ]
        out.append({**e, "config": cfg})
    return out


def _merge_secret_models(entries: list, old: dict) -> None:
    """前端提交 ****** 视为不变: 与已存密钥合并。"""
    for e in entries:
        old_models = {m.get("name"): m for m in ((old.get(e.get("id")) or {}).get("config") or {}).get("models") or []}
        for m in (e.get("config") or {}).get("models") or []:
            if m.get("apiKey") == "******":
                prev = old_models.get(m.get("name")) or {}
                if prev.get("apiKey"):
                    m["apiKey"] = prev["apiKey"]


def _post_runner(path: str, payload: dict | None = None, timeout: float = 8.0) -> Optional[dict]:
    try:
        req = urllib.request.Request(
            f"{RUNNER_BASE_URL}{path}",
            data=json.dumps(payload or {}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001
        logger.info("[agent-executors] runner %s 不可达: %s", path, e)
        return None


def _get_runner(path: str, timeout: float = 5.0) -> Optional[dict]:
    try:
        with urllib.request.urlopen(f"{RUNNER_BASE_URL}{path}", timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:  # noqa: BLE001
        return None


def refresh_runner() -> bool:
    return bool(_post_runner("/api/executors/refresh"))


# ── 路由 ──

@router.get("/agent/executors")
async def list_executors():
    """注册表（脱敏）+ runner 运行态（若可达）。"""
    entries = _normalize(load_executors())
    runtime = _get_runner("/api/executors")
    return ok({
        "executors": _mask(entries),
        "runtime": runtime or {"reachable": False},
        "runnerBaseUrl": RUNNER_BASE_URL,
    })


@router.put("/agent/executors")
async def put_executors(request: Request, background: BackgroundTasks):
    """保存注册表（全量覆盖）→ 后台触发 runner 热刷新。

    刷新必须脱离本请求：runner 刷新时会回调 architect /runtime 拉配置，
    同步执行会让 architect 阻塞在 runner 上、runner 又阻塞在 architect
    上（互等→6s 超时→runner 静默回退内置池）。
    """
    body = await request.json()
    entries = body.get("executors")
    if not isinstance(entries, list):
        return err("executors 必须为列表")
    # 与已存密钥合并（前端提交 ****** 视为不变）
    _normalize(entries)
    old = {e.get("id"): e for e in load_executors()}
    for e in entries:
        cfg = e.get("config") or {}
        old_cfg = (old.get(e.get("id")) or {}).get("config") or {}
        for k in _SECRET_KEYS:
            if cfg.get(k) == "******" and old_cfg.get(k):
                cfg[k] = old_cfg[k]
    _merge_secret_models(entries, old)
    msg = _validate(entries)
    if msg:
        return err(msg)
    save_executors(entries)
    background.add_task(refresh_runner)
    return ok({"saved": len(entries), "runnerRefreshed": True,
               "runnerRefresh": "background", "updatedAt": _ts()})


@router.post("/agent/executors/probe")
async def probe_executor(request: Request):
    """单条配置探活：本地可探的（opencode 端口/serve url/cline sidecar 文件）直接探，
    会话型执行器委托 runner 健康检查。"""
    body = await request.json()
    entry = body.get("entry") or {}
    etype, cfg = entry.get("type"), entry.get("config") or {}
    try:
        if etype in ("opencode", "serve-generic"):
            url = (cfg.get("base_url") or f"http://127.0.0.1:{cfg.get('base_port', 3478)}").rstrip("/")
            path = "/global/health" if etype == "opencode" else "/health"
            try:
                with urllib.request.urlopen(f"{url}{path}", timeout=3) as r:
                    return ok({"status": "ok" if r.status == 200 else "fail",
                               "detail": f"{url} HTTP {r.status}"})
            except Exception as e:  # noqa: BLE001
                # 连接拒绝 = serve 未运行: auto_start 开启属预期状态(执行时自动拉起),
                # 单独标记 stopped 而非 fail, 前端以中性样式展示
                refused = "Connection refused" in str(e) or isinstance(
                    getattr(getattr(e, "reason", None), "errno", None), int) and getattr(
                    getattr(e, "reason", None), "errno", 0) == 111
                if refused and etype == "opencode" and cfg.get("auto_start"):
                    return ok({"status": "stopped", "detail": f"{url} 未运行",
                               "note": "auto_start 已开启——执行时自动拉起，无需手动启动"})
                raise
        if etype == "cline-sdk":
            script = cfg.get("sidecar_script") or _default_sidecar_path()
            exists = os.path.isfile(script)
            return ok({"status": "ok" if exists else "fail",
                       "detail": f"sidecar: {script} {'存在' if exists else '缺失（需 npm run build -w packages/agent-sidecar）'}"})
        if etype == "cli":
            import shutil
            cmd = (cfg.get("command") or "").split()
            binpath = shutil.which(cmd[0]) if cmd else None
            return ok({"status": "ok" if binpath else "fail",
                       "detail": f"{cmd[0] if cmd else '?'}: {binpath or '未找到'}"})
        if etype == "remote-agent":
            url = (cfg.get("agent_url") or "").rstrip("/")
            if not url:
                return ok({"status": "fail", "detail": "缺少 agent_url（远端 opencode serve 地址）"})
            with urllib.request.urlopen(f"{url}/global/health", timeout=5) as r:
                return ok({"status": "ok" if r.status == 200 else "fail",
                           "detail": f"{url} HTTP {r.status}"})
        if etype == "codex-server":
            import shutil as _sh
            binpath = _sh.which(cfg.get("codex_bin", "codex"))
            return ok({"status": "ok" if binpath else "fail", "detail": f"codex: {binpath or '未找到'}"})
        return ok({"status": "ok", "detail": f"type={etype} 无需探活"})
    except Exception as e:  # noqa: BLE001
        return ok({"status": "fail", "detail": str(e),
                   "note": "serve 未运行属正常（执行时自动拉起）"})


def _probe_llm_model(url: str, model: str, api_key: str = "") -> dict:
    """模型连通性测试: OpenAI 兼容。先 GET /models(廉价), 失败再 1-token 对话。"""
    base = (url or "").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if not base:
        return {"status": "fail", "detail": "缺少模型服务 url"}
    try:
        req = urllib.request.Request(f"{base}/models", headers=headers)
        with urllib.request.urlopen(req, timeout=6) as r:
            body = r.read().decode()[:4096]
            hit = model in body
            return {"status": "ok",
                    "detail": f"{base}/models HTTP {r.status}" + ("" if hit else f"(列表未见 {model}, 仍可达)")}
    except Exception as e1:  # noqa: BLE001
        try:
            payload = json.dumps({"model": model, "messages": [
                {"role": "user", "content": "ping"}], "max_tokens": 1}).encode()
            req = urllib.request.Request(
                f"{base}/chat/completions", data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                return {"status": "ok", "detail": f"{base}/chat/completions HTTP {r.status}"}
        except Exception as e2:  # noqa: BLE001
            return {"status": "fail", "detail": f"/models: {e1} | /chat/completions: {e2}"}


@router.post("/agent/executors/model-probe")
async def model_probe(request: Request):
    """实例内模型连通性测试。Body: { url, model, apiKey? }。"""
    body = await request.json() or {}
    url = str(body.get("url") or "").strip()
    model = str(body.get("model") or "").strip()
    if not model:
        return err(400, "缺少 model")
    return ok(_probe_llm_model(url, model, str(body.get("apiKey") or "")))


@router.get("/agent/executors/runtime")
async def runtime_executors():
    """runner 拉取面（内部）：解析后的完整注册表（不脱敏，含密钥）。"""
    entries = load_executors()
    enabled = [e for e in entries if e.get("enabled", True)]
    return ok({"executors": enabled, "updatedAt": _ts()})


def _default_sidecar_path() -> str:
    # arch_routes → topoone_app_architect → architect → apps → 仓库根
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    return os.path.join(root, "..", "packages", "agent-sidecar", "dist", "index.js")
