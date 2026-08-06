"""Agent connection config routes — 三方 coding agent 连接配置 + 连通性测试。

设计原则(架构师不存三方 agent 的密码/模型)：
- 仅保存连接参数(host/port/username/url)，**不存 password**；
- 模型由 agent 自身配置提供(模型多选 + 默认模型来自 agent 自身已配置的 auth)；
- 连通性测试 = 真实 HTTP 探测(如 opencode `GET /global/health` + `GET /provider`)。
- 任务执行(经 /ws/coding-agent 实际跑 agent)后续阶段再做。

当前已适配：opencode(server 模式)；其余 adapter 显示但标记待适配。
"""
import json
import logging
import urllib.error
import urllib.request
from typing import Optional
from fastapi import APIRouter, Request

from .common import _ts, _id, ok, err
from . import store

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_OPENSE_HOST = "127.0.0.1"
DEFAULT_OPENSE_PORT = 4096
DEFAULT_USERNAME = "opencode"

# 已适配的连接模式(其余 adapter 仅展示)。
_SUPPORTED = {"opencode"}


# ── HTTP 探测工具 ──────────────────────────────────────────────

def _http_json(url: str, timeout: float = 3.0, username: str = None) -> tuple:
    """GET JSON。返回 (data, error)。成功 data 为解析后的 dict/list；失败 error 为可读原因。"""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if username:
        import base64
        token = base64.b64encode(f"{username}:".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        return None, f"无法连接: {reason}"
    except Exception as e:
        return None, str(e)


def _opencode_base(cfg: dict) -> str:
    url = (cfg.get("url") or "").strip()
    if url:
        return url.rstrip("/")
    host = cfg.get("host") or DEFAULT_OPENSE_HOST
    port = int(cfg.get("port") or DEFAULT_OPENSE_PORT)
    return f"http://{host}:{port}"


def probe_opencode(cfg: dict) -> dict:
    """opencode server 连通性测试：
    1. GET /global/health → {healthy, version}；
    2. GET /provider → connected 提供商(即已配置好 auth 的模型来源)。
    返回 { status: ok|fail, detail, version, models, connected }。
    """
    base = _opencode_base(cfg)
    username = cfg.get("username") or DEFAULT_USERNAME
    health, err_ = _http_json(f"{base}/global/health", username=username)
    if err_ or not health or not health.get("healthy"):
        return {
            "status": "fail",
            "detail": err_ or "opencode 服务未就绪(healthy != true)",
            "version": (health or {}).get("version") or "",
            "models": [], "connected": [],
        }
    models = []
    connected = []
    providers, perr = _http_json(f"{base}/provider", username=username)
    if perr is None and isinstance(providers, dict):
        connected = providers.get("connected") or []
        for p in providers.get("all") or []:
            if p.get("id") not in connected:
                continue
            pm = p.get("models")
            # models 可能是 dict(modelId → info) 或 list(info)
            items = list(pm.values()) if isinstance(pm, dict) else (pm or [])
            for m in items:
                if not isinstance(m, dict):
                    continue
                models.append({"id": m.get("id"), "name": m.get("name") or m.get("id")})
    return {
        "status": "ok",
        "detail": "opencode 服务连通",
        "version": health.get("version") or "",
        "models": models,
        "connected": connected,
    }


def probe_adapter(cfg: dict) -> dict:
    """按 adapter 分派探测。未适配的类型返回 fail(带提示)。"""
    adapter = (cfg.get("adapter") or "").lower()
    if adapter == "opencode":
        return probe_opencode(cfg)
    return {
        "status": "fail",
        "detail": f"「{adapter or '未知'}」接入待适配",
        "version": "", "models": [], "connected": [],
    }


# ── 路由 ─────────────────────────────────────────────────────────

def _api_shape(row: dict) -> dict:
    models = row.get("models")
    if isinstance(models, str):
        try:
            models = json.loads(models)
        except (TypeError, ValueError):
            models = []
    return {**row, "models": models or []}


@router.get("/agent/configs")
async def list_agent_configs():
    """列出已保存的三方 agent 连接配置(含最近一次测试状态)。"""
    return ok([_api_shape(r) for r in store.AgentConfigsStore.all()])


@router.post("/agent/configs")
async def create_agent_config(request: Request):
    """新建连接配置。Body: { adapter, name?, mode?, host?, port?, username?, url?, models?, default_model? }"""
    body = await request.json() or {}
    adapter = (body.get("adapter") or "").strip().lower()
    if not adapter:
        return err(400, "缺少 adapter")
    now = _ts()
    cfg_id = _id("agcfg")
    cfg = {
        "id": cfg_id,
        "adapter": adapter,
        "name": (body.get("name") or adapter).strip(),
        "mode": body.get("mode") or "server",
        "host": body.get("host") or DEFAULT_OPENSE_HOST,
        "port": int(body.get("port") or DEFAULT_OPENSE_PORT),
        "username": body.get("username") or DEFAULT_USERNAME,
        "url": body.get("url") or "",
        "models": body.get("models") or [],
        "default_model": body.get("default_model") or body.get("defaultModel") or "",
        "last_status": "unknown",
        "last_detail": "",
        "last_check_at": 0,
        "created_at": now,
        "updated_at": now,
    }
    store.AgentConfigsStore.create(cfg)
    return ok(_api_shape(store.AgentConfigsStore.get(cfg_id) or cfg))


@router.patch("/agent/configs/{cfg_id}")
async def update_agent_config(cfg_id: str, request: Request):
    """更新连接配置(可只传部分字段)。"""
    body = await request.json() or {}
    existing = store.AgentConfigsStore.get(cfg_id)
    if not existing:
        return err(404, "Config not found")
    allowed = {"name", "mode", "host", "port", "username", "url", "models", "default_model", "defaultModel"}
    patch = {}
    for k in allowed:
        if k in body:
            patch[k] = body[k]
    if "defaultModel" in patch and "default_model" not in patch:
        patch["default_model"] = patch.pop("defaultModel")
    patch["updatedAt"] = _ts()
    row = store.AgentConfigsStore.update(cfg_id, patch)
    return ok(_api_shape(row or existing))


@router.delete("/agent/configs/{cfg_id}")
async def delete_agent_config(cfg_id: str):
    if not store.AgentConfigsStore.delete(cfg_id):
        return err(404, "Config not found")
    return ok({"deleted": cfg_id})


@router.post("/agent/configs/{cfg_id}/test")
async def test_agent_config(cfg_id: str):
    """真实连通性测试，并写回 last_status/last_detail/last_check_at。"""
    cfg = store.AgentConfigsStore.get(cfg_id)
    if not cfg:
        return err(404, "Config not found")
    result = probe_adapter(cfg)
    now = _ts()
    store.AgentConfigsStore.update(cfg_id, {
        "lastStatus": result["status"], "lastDetail": result["detail"],
        "lastCheckAt": now, "updatedAt": now,
    })
    return ok({"test": result, **_api_shape(store.AgentConfigsStore.get(cfg_id) or {**cfg, **result})})


@router.post("/agent/configs/preview")
async def preview_agent_config(request: Request):
    """未保存前的连通性预测试(弹窗内「测试连通性」用)。Body 同新建。"""
    body = await request.json() or {}
    adapter = (body.get("adapter") or "opencode").strip().lower()
    cfg = {
        "adapter": adapter,
        "host": body.get("host") or DEFAULT_OPENSE_HOST,
        "port": int(body.get("port") or DEFAULT_OPENSE_PORT),
        "username": body.get("username") or DEFAULT_USERNAME,
        "url": body.get("url") or "",
    }
    return ok(probe_adapter(cfg))