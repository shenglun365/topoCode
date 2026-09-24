"""tAgent 适配层(实现迁至 agent 层, P1)。

两个领域, 一处适配(勿混):
- 资产助理(GET/PUT /agent/roles → agent.cognition.roles)——数据资产·语义提取
  管线的工种→模型绑定;
- 轻任务模型(GET/PUT /agent/light-tasks → agent.governance.light_tasks)——
  编码编排侧轻任务(标题摘要/范围探针)的模型绑定。
"""
from typing import Any, List
import json

from fastapi import APIRouter, Request

from ..common import err, ok
from ..agent.cognition.roles import (  # noqa: F401
    DEFAULT_ROLES,
    get_roles,
    resolve_role_model,
    role_model_id,
    scenario_role,
    set_roles,
)
from ..agent.governance.light_tasks import (  # noqa: F401
    LIGHT_TASKS_KEY,
    light_tasks_vocab,
    normalize_light_tasks,
)

router = APIRouter()


@router.get("/agent/roles")
async def api_roles_get():
    return ok({"roles": get_roles()})


@router.put("/agent/roles")
async def api_roles_put(request: Request):
    body = await request.json()
    roles = body.get("roles") if isinstance(body, dict) else None
    if roles is None or not isinstance(roles, list):
        return err(400, "roles 必须是数组")
    return ok({"roles": set_roles(roles)})


@router.get("/agent/light-tasks")
async def api_light_tasks_get():
    return ok({"lightTasks": get_light_tasks()})


@router.put("/agent/light-tasks")
async def api_light_tasks_put(request: Request):
    body = await request.json()
    tasks = body.get("lightTasks") if isinstance(body, dict) else None
    if not isinstance(tasks, dict):
        return err(400, "lightTasks 必须是对象(键: summary/probe)")
    return ok({"lightTasks": set_light_tasks(tasks)})


# ── 轻任务模型: 存储读写(适配层职责; 纯校验在 governance.light_tasks) ──

def get_light_tasks() -> dict:
    """读配置(词表全集, 缺键补空; 坏 JSON → 空值兜底)。"""
    from ..store import CollabConfigStore
    raw = CollabConfigStore.get(LIGHT_TASKS_KEY, "") or "{}"
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        data = {}
    src = data if isinstance(data, dict) else {}
    return {k: str(src.get(k) or "").strip() for k in light_tasks_vocab()}


def set_light_tasks(data: dict) -> dict:
    """写入(词表键 + 模型目录越界剥离——cv-168 同源教训)。"""
    from ..store import CollabConfigStore
    from ..agent.cognition.roles import _known_model_ids
    clean = normalize_light_tasks(data, _known_model_ids())
    CollabConfigStore.set(LIGHT_TASKS_KEY, json.dumps(clean, ensure_ascii=False))
    return get_light_tasks()


def load_light_tasks_cfg() -> dict:
    """消费方注入入口(units/scope_probe 经此读原始 cfg——不做全集补齐)。"""
    from ..store import CollabConfigStore
    raw = CollabConfigStore.get(LIGHT_TASKS_KEY, "") or "{}"
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}
