"""资产地图工具域(map.*, 与对外 MCP 服务同源 Markdown 输出) — M3 自 req_agent 机械迁出(逐字保真, 注册随定义点)。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..registry import register_architect_tool

logger = logging.getLogger("arch_routes.req_agent")

# ── 资产地图工具(map.*): 与对外 MCP 服务同源实现(Markdown 输出) ────────
# 穷举/层级/统计/规约类提问(「有哪些组件」「L0/L1 模块」「资产统计」「编码规约」)的
# 正确入口；kb.asset.search 是关键词检索(≤6 条命中)，不适合枚举型提问。

@register_architect_tool(
    "map.overview",
    "资产地图总览(Markdown)：组件目录(名称/图层级/文件数/依赖出入)+语义资产分类统计+基线视图。"
    "穷举/统计/层级类提问(如「有哪些组件」「L0/L1 模块」「资产总数」)先调此工具",
brief='资产地图总览——组件目录(含图层级 L0/L1/文件数/依赖)+资产统计；穷举/统计/层级类提问先看',
params_doc='{}',
)
def tool_map_overview(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from ....sem.map_tools import run_tool
    return {"markdown": run_tool("map.overview", {"project": project})}


@register_architect_tool(
    "map.component",
    "组件档案(Markdown)：单个组件的图层级/文件清单/依赖出入/组件内语义资产",
brief='组件档案——单组件的层级/文件/依赖出入/组件内语义资产',
params_doc='{"name": "组件名或id"}',
)
def tool_map_component(root: Optional[str], project: Optional[str],
                       name: str = "") -> Dict[str, Any]:
    from ....sem.map_tools import run_tool
    if not (name or "").strip():
        return {"error": "缺少组件名(name)"}
    return {"markdown": run_tool("map.component", {"name": name.strip(), "project": project})}


@register_architect_tool(
    "map.assets",
    "语义资产表列检索(Markdown 表格)：kind/level 过滤+关键词，返回 名称/文件/状态 清单。"
    "需要浏览资产清单(而非前几条命中)时用",
brief='语义资产表列检索——kind/level 过滤+关键词，Markdown 表格浏览清单',
params_doc='{"query": "关键词", "kind": "类别(可选)", "level": "粒度(可选)", "limit": 30}',
)
def tool_map_assets(root: Optional[str], project: Optional[str], query: str = "",
                    kind: str = "", level: str = "", limit: int = 30) -> Dict[str, Any]:
    from ....sem.map_tools import run_tool
    return {"markdown": run_tool("map.assets", {"query": query, "kind": kind,
                                                "level": level, "limit": limit,
                                                "project": project})}


@register_architect_tool(
    "map.rules",
    "项目规约全集(Markdown)：架构规约+编码规约+命名规约+词汇表，编码/方案评估必须遵守",
brief='项目规约全集(架构+编码+命名规约+词汇表，编码/评估必须遵守)',
params_doc='{}',
)
def tool_map_rules(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from ....sem.map_tools import run_tool
    return {"markdown": run_tool("map.rules", {"project": project})}


@register_architect_tool(
    "map.graph",
    "关系图(mermaid)：kind=component 组件依赖图 / kind=semantic 语义关系图",
brief='关系图(mermaid)——component 组件依赖图 / semantic 语义关系图',
params_doc='{"kind": "component|semantic"}',
)
def tool_map_graph(root: Optional[str], project: Optional[str],
                   kind: str = "component") -> Dict[str, Any]:
    from ....sem.map_tools import run_tool
    return {"markdown": run_tool("map.graph", {"kind": kind or "component",
                                               "project": project})}
