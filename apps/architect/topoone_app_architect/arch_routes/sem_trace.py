"""链路跟踪 API：单资产上/下游处理链条的符号级 DFS(深度探索模式)。

与邻域聚焦(/kb/semantic/graph 的 focus+hops)互补不交叉：
- mode=asset   整链跟踪(资产锚点为根)
- mode=expand  侧栏懒加载(以任意中途符号为根继续展开)
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Request

from ..common import err, ok
from .semantic_assets import project_id_for

router = APIRouter()


@router.get("/kb/semantic/trace")
async def api_trace(root: Optional[str] = None, project: Optional[str] = None,
                    asset: str = "", symbol: str = "", direction: str = "down",
                    max_depth: int = 6, branch_limit: int = 3,
                    max_nodes: int = 400):
    """链路跟踪：mode 由 asset/symbol 参数区分(asset=整链, symbol=展开)。

    direction: down(它调谁=影响扩散) | up(谁调它=依赖来源)。
    预算: max_depth/branch_limit/max_nodes 三闸(默认 6/3/400)。
    """
    from ..sem import trace as T
    if not asset and not symbol:
        return err(400, "缺少 asset 或 symbol")
    kw = dict(direction=direction,
              max_depth=max(1, min(int(max_depth), 12)),
              branch_limit=max(1, min(int(branch_limit), 10)),
              max_nodes=max(20, min(int(max_nodes), 2000)))
    if asset:
        res = await asyncio.to_thread(T.trace, root, project, asset.strip(), **kw)
    else:
        res = await asyncio.to_thread(T.trace_expand, root, project, symbol.strip(), **kw)
    if isinstance(res, dict) and res.get("error"):
        return err(404, res["error"])
    return ok(res)
