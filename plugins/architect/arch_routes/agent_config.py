"""Agent connection config routes — 三方 coding agent 连接配置 + 连通性测试。

设计原则(架构师不存三方 agent 的密码/模型)：
- 仅保存连接参数(host/port/username/url)，**不存 password**；
- 模型由 agent 自身配置提供(模型多选 + 默认模型来自 agent 自身已配置的 auth)；
- 连通性测试 = 真实 HTTP 探测(如 opencode `GET /global/health` + `GET /provider`)。
- 实例层见 agent_server.py(AgentInstancePool)：config 是连接模板，(project,adapter,host)
  的实例才是在具体项目上运行/执行任务的实体。

适配器：探测/默认参数统一走 `agent_adapters` 注册表(当前仅 opencode)。
"""
import json
import logging
from typing import Optional
from fastapi import APIRouter, Request

from .common import _ts, _id, ok, err
from . import store
from . import agent_server
from .agent_adapters import get_agent, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_USERNAME

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_OPENSE_HOST = DEFAULT_HOST
DEFAULT_OPENSE_PORT = DEFAULT_PORT


# ── 连通性探测 ─────────────────────────────────────────────────

def probe_adapter(cfg: dict) -> dict:
    """按 adapter 分派探测(走注册表)。未注册的类型返回 fail(带提示)。"""
    adapter = (cfg.get("adapter") or "").lower()
    impl = get_agent(adapter)
    if impl is None:
        return {
            "status": "fail",
            "detail": f"「{adapter or '未知'}」接入待适配",
            "version": "", "models": [], "connected": [],
        }
    return impl.probe(cfg)


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
    inst_mode = (body.get("instanceMode") or body.get("mode") or "managed").strip().lower()
    if inst_mode not in ("managed", "external"):
        inst_mode = "managed"
    if (body.get("url") or "").strip():
        inst_mode = "external"
    cfg = {
        "id": cfg_id,
        "adapter": adapter,
        "name": (body.get("name") or adapter).strip(),
        "mode": body.get("mode") or "server",
        "instanceMode": inst_mode,
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
    allowed = {"name", "mode", "host", "port", "username", "url", "models", "default_model", "defaultModel", "instanceMode"}
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


# ── 实例层(AgentInstancePool) ─────────────────────────────────

@router.get("/agent/instances")
async def list_agent_instances():
    """列出全部 agent 实例((project, adapter, host) 维度)。"""
    return ok(store.AgentInstancesStore.all())


@router.get("/agent/instances/{instance_id}")
async def get_agent_instance(instance_id: str):
    inst = store.AgentInstancesStore.get(instance_id)
    if not inst:
        return err(404, "Instance not found")
    return ok(inst)


@router.post("/agent/instances/{instance_id}/stop")
async def stop_agent_instance(instance_id: str):
    """停止实例(managed terminate / external 置 stopped)。"""
    inst = store.AgentInstancesStore.get(instance_id)
    if not inst:
        return err(404, "Instance not found")
    await agent_server.get_pool().stop(instance_id)
    return ok(store.AgentInstancesStore.get(instance_id) or inst)


@router.post("/agent/instances/{instance_id}/restart")
async def restart_agent_instance(instance_id: str, request: Request):
    """重启实例(项目 + 配置)。managed 重新 spawn, external 重新探测。"""
    inst = store.AgentInstancesStore.get(instance_id)
    if not inst:
        return err(404, "Instance not found")
    await agent_server.get_pool().stop(instance_id)
    project = store.ProjectsStore.get(inst.get("projectId") or "")
    if not project:
        return err(400, "实例无绑定项目")
    cfg = _find_config_for_adapter(inst.get("adapter") or "opencode")
    if not cfg:
        return err(400, "无对应 agent 连接配置")
    return ok(await agent_server.get_pool().ensure(project, cfg))


def _find_config_for_adapter(adapter: str) -> Optional[dict]:
    for c in store.AgentConfigsStore.all():
        if (c.get("adapter") or "").lower() == adapter:
            return c
    return None