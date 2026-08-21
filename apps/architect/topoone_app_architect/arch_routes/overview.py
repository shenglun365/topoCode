"""Overview routes — 概览页聚合接口。

`GET /overview` 一次返回概览页四组栏目所需数据，避免前端多次并发小请求：
  - launch   : 组① 启动命令 (execRoot/kbRoot)
  - recent   : 组② 近期项目 (arch_projects 按最近更新倒序)
  - adapters : 组③ coding agent 适配器 + 每项联通性
  - kb       : 组③ 知识库关联项与项目计数
  - missions : 组④ 引导任务(按 launch.mode / ?mode= 选择)

各分片逻辑均取自既有路由的可复用 helper；旧端点保持原样，供其他页面使用。
契约见 docs/architect/api-overview.md。
"""
from typing import Optional
from fastapi import APIRouter

from .common import ok
from . import agent as agent_routes
from . import agent_config as agent_config_routes
from . import mcp_collab as mcp_collab_routes
from . import project as project_routes
from . import greenfield as greenfield_routes

router = APIRouter()


def _build_overview(mode: str = "existing") -> dict:
    kb_projects = project_routes._list_kb_projects()
    return {
        "launch": greenfield_routes.launch_info(),
        "recent": project_routes.list_recent_projects(),
        "adapters": agent_routes.list_adapter_connectivity(),
        "agentConfigs": [c for c in (agent_config_routes.store.AgentConfigsStore.all())],
        "kb": {
            "count": len(kb_projects),
            "linked": bool(kb_projects),
            "projects": kb_projects,
        },
        "kbConfig": mcp_collab_routes.get_kb_config(),
        "missions": greenfield_routes.guide_missions(mode),
    }


@router.get("/overview")
async def get_overview(mode: Optional[str] = None):
    """概览页聚合数据。mode 缺省跟随 launch.mode(existing|greenfield)。"""
    launch = greenfield_routes.launch_info()
    mode = mode or launch.get("mode") or "existing"
    data = _build_overview(mode)
    data["launch"] = launch
    return ok(data)