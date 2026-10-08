"""工具能力展示面(2610)——architect 原生工具注册表快照(只读)。

工具是能力执行面(与 skills 执行路线目录分工, D-1/W6); 本面为管理视角:
按前缀分组 + brief/参数形状, 供「系统管理 → 工具能力」页消费。
"""
from fastapi import APIRouter

from ..common import ok

router = APIRouter()


@router.get("/arch/tools")
async def list_tools():
    """原生工具注册表快照(按名称前缀分组; 只读, 无状态)。"""
    from ..agent.tools.registry import architect_tools_full
    groups: dict = {}
    for t in architect_tools_full():
        prefix = str(t["name"]).split(".")[0]
        groups.setdefault(prefix, []).append(t)
    return ok([{"group": g, "tools": items}
               for g, items in sorted(groups.items())])
