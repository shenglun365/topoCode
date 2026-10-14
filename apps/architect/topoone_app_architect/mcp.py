"""architect MCP 服务 — 资产地图对外暴露（S4，stdio + HTTP 双通道）。

传输：
- HTTP（streamable）：architect 服务内挂载 `POST/GET /mcp`（server.py build_app），
  与 architect 同进程同上下文；
- stdio：`python3 -m topoone_app_architect.mcp` 供 Claude Code/Cursor/Cline
  本地拉起（独立进程，自建 ctx 指向同一 data_dir）。

工具集见 sem/map_tools.TOOLS（map.overview/component/assets/rules/graph，
全部输出 Markdown 文档）。

接入示例：
  claude mcp add topo-architect -- python3 -m topoone_app_architect.mcp
  # 或 HTTP：
  claude mcp add --transport http topo-architect http://127.0.0.1:3470/mcp
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def build_mcp(name: str = "topo-architect"):
    """构建 FastMCP 实例（工具注册一次，双传输共用）。"""
    from mcp.server.fastmcp import FastMCP
    from .sem.map_tools import run_tool, TOOLS

    mcp = FastMCP(name, instructions=(
        "TopoCode architect 资产地图服务：查询项目架构资产（组件目录/语义资产/"
        "规约/关系图）。所有工具返回 Markdown 文档。先 map.overview 看全貌，"
        "再按需下钻 map.component / map.assets。写码前必读 map.rules。"))

    @mcp.tool(name="map.overview")
    def map_overview(project: Optional[str] = None) -> str:
        """项目资产地图总览（组件目录/资产统计/基线视图），写码前先看。多项目时传 project id。"""
        return run_tool("map.overview", {"project": project})

    @mcp.tool(name="map.component")
    def map_component(name: str, project: Optional[str] = None) -> str:
        """组件档案：语义资产/依赖出入。name 为组件名或 id。多项目环境必须传 project。"""
        return run_tool("map.component", {"name": name, "project": project})

    @mcp.tool(name="map.assets")
    def map_assets(query: str = "", kind: str = "", limit: int = 30,
                   project: Optional[str] = None) -> str:
        """语义资产检索（kind/level/关键词过滤，返回 Markdown 列表）。多项目环境必须传 project。"""
        return run_tool("map.assets", {"query": query, "kind": kind,
                                       "limit": limit, "project": project})

    @mcp.tool(name="map.core")
    def map_core(project: Optional[str] = None) -> str:
        """核心资产标记清单（用户标记+绑定守护规约）。改动相关文件前自查（评估性，不阻断）。多项目环境必须传 project。"""
        return run_tool("map.core", {"project": project})

    @mcp.tool(name="map.rules")
    def map_rules(project: Optional[str] = None) -> str:
        """规约全集：编码规约+命名规约+词汇表。编码必须遵守。多项目环境必须传 project。"""
        return run_tool("map.rules", {"project": project})

    @mcp.tool(name="map.graph")
    def map_graph(kind: str = "component", project: Optional[str] = None) -> str:
        """关系图（mermaid）：component=组件依赖图 / semantic=语义关系图。多项目环境必须传 project。"""
        return run_tool("map.graph", {"kind": kind, "project": project})

    @mcp.tool(name="task.mandate")
    def task_mandate(task_id: str = "", req_id: str = "",
                     project: Optional[str] = None) -> str:
        """开工前取执行契约: 规约/允许范围/约束/验收判据+项目规约全集。task_id 或 req_id 二选一。"""
        return run_tool("task.mandate", {"task_id": task_id, "req_id": req_id,
                                         "project": project})

    @mcp.tool(name="task.receipt")
    def task_receipt(task_id: str, changed_files: list[str],
                     summary: str = "") -> str:
        """完工后提交回执: architect 越界检测+验收对照+改动分布(自纠正信息)。changed_files=相对路径清单。"""
        return run_tool("task.receipt", {"task_id": task_id,
                                         "changed_files": changed_files,
                                         "summary": summary})

    @mcp.tool(name="ctx.search")
    def ctx_search(query: str, type: str = "", conversation: str = "",  # noqa: A002
                   limit: int = 20, project: Optional[str] = None) -> str:
        """跨会话检索历史上下文（工具轨迹/产物/决策/摘要/执行回执/消息/备案文档）。多项目环境建议传 project。"""
        return run_tool("ctx.search", {"query": query, "type": type,
                                       "conversation": conversation, "limit": limit,
                                       "project": project})

    @mcp.tool(name="ctx.get")
    def ctx_get(conversation: str, project: Optional[str] = None) -> str:
        """会话上下文包：摘要+关键单元+备案文档。多项目环境建议传 project。"""
        return run_tool("ctx.get", {"conversation": conversation, "project": project})

    @mcp.tool(name="ctx.summarize")
    def ctx_summarize(conversation: str) -> str:
        """生成/刷新会话摘要（标题+结论/决策/待办）。"""
        return run_tool("ctx.summarize", {"conversation": conversation})
    return mcp


def mcp_http_app():
    """streamable HTTP ASGI 子应用（挂 architect /mcp）。

    返回 (asgi_app, session_lifespan)：宿主 FastAPI 需在自身 lifespan 内
    async with session_lifespan() —— 初始化 streamable 会话任务组。
    """
    mcp = build_mcp()
    app = mcp.streamable_http_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan():
        async with mcp.session_manager.run():
            yield

    return app, _lifespan


def main_stdio() -> None:
    """stdio 模式入口（coding agent 拉起）：自建 ctx → run_stdio。"""
    logging.basicConfig(level=logging.INFO)
    data_dir = os.environ.get("TOPOCODE_DATA_DIR") or os.path.join(
        os.path.expanduser("~"), ".topocode")
    from . import ctx
    ctx.setup(data_dir=data_dir)
    mcp = build_mcp()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main_stdio()
