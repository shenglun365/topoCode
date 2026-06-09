"""AnalysisContext — 统一上下文管理器。

为内置 Agent 提供层次化的项目分析数据访问。
四个认知层级: project → community → file → symbol。
每个层级提供"干了什么"（功能）、"怎么干的"（逻辑）、"为什么这么干"（因果）三层结构化描述。

用法:
    ctx = AnalysisContext(project_db, task_id)
    layers = ctx.get_downward_path(["project", "comm-xxx", "src/api/handler.ts", "authenticate"])
    prompt = ctx.format_for_llm(layers, direction="top-down")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 社区节点数阈值（低于此阈值的社区视为"小社区"，在摘要中降权）
SMALL_COMMUNITY_THRESHOLD = 6

# 缓存大小
_CACHE_SIZE = 128


@dataclass
class ContextLayer:
    """一层上下文的抽象表示。

    每一层都包含三个维度的信息：
      - what: 干了什么（功能描述）
      - how: 怎么干的（逻辑描述）
      - why: 为什么这么干（因果/约束/权衡）
    """

    level: str  # "project" | "community" | "file" | "symbol"
    layer_id: str  # 该层唯一标识 (task_id, comm_id, file_path, symbol_name)
    name: str  # 显示名

    # 三层描述
    what: str = ""  # 功能描述
    how: str = ""  # 逻辑描述
    why: str = ""  # 因果描述

    # 结构化详情（原始数据）
    detail: dict[str, Any] = field(default_factory=dict)

    # 子层 ID 列表
    children: list[str] = field(default_factory=list)

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)


class AnalysisContext:
    """统一上下文管理器。

    基于 AnalysisStore 构建层次化的项目认知模型。
    所有方法均为只读查询，不修改数据。
    """

    def __init__(self, project_db, task_id: str):
        """
        Args:
            project_db: SQLiteContext 实例
            task_id: 分析任务 ID
        """
        from store.analysis_store import AnalysisStore
        self._store = AnalysisStore(project_db)
        self._task_id = task_id
        self._project_root = getattr(project_db, 'project_root', None) or ""

    # ═══════════════════════════════════════════
    # 项目层
    # ═══════════════════════════════════════════

    def get_project_layer(self) -> ContextLayer:
        """构建项目级上下文：整体统计、社区分布、语言分布。"""
        nodes = self._store.get_graph_nodes(self._task_id)
        file_nodes = [n for n in nodes if n.get("kind") == "file"]
        languages = {}
        for n in nodes:
            lang = n.get("language", "unknown")
            languages[lang] = languages.get(lang, 0) + 1

        incl_comms = self._store.get_communities(self._task_id, edge_type="INCLUDE", comm_lv="L0")
        call_comms = self._store.get_communities(self._task_id, edge_type="CALL", comm_lv="L0")

        total_symbols = sum(1 for n in nodes if n.get("kind") not in ("file", "import"))

        what = (
            f"项目包含 {len(file_nodes)} 个文件，{total_symbols} 个符号，"
            f"分布在 {len(incl_comms)} 个依赖社区和 {len(call_comms)} 个调用社区中"
        )
        how = f"主要语言: {', '.join(f'{k}({v})' for k, v in sorted(languages.items(), key=lambda x: -x[1])[:5])}"
        why = f"依赖社区反映模块间的静态依赖关系，调用社区反映运行时的调用聚类。两者结合可评估架构的耦合度和内聚度。"

        # 子层：所有 L0 社区
        children = [c.get("comm_id", "") for c in incl_comms if c.get("comm_id")]
        children += [c.get("comm_id", "") for c in call_comms if c.get("comm_id")]

        return ContextLayer(
            level="project",
            layer_id=self._task_id,
            name="项目总览",
            what=what,
            how=how,
            why=why,
            detail={
                "file_count": len(file_nodes),
                "symbol_count": total_symbols,
                "languages": languages,
                "include_communities": len(incl_comms),
                "call_communities": len(call_comms),
            },
            children=children,
        )

    # ═══════════════════════════════════════════
    # 社区层
    # ═══════════════════════════════════════════

    @lru_cache(maxsize=_CACHE_SIZE)
    def _get_node_map(self) -> dict[str, dict]:
        """构建 node_id → node dict 的映射（带缓存）。"""
        nodes = self._store.get_graph_nodes(self._task_id)
        return {n.get("id", ""): n for n in nodes}

    def get_community_layer(self, comm_id: str, depth: int = 1) -> ContextLayer:
        """构建社区级上下文：节点、边、Hub、子社区。

        Args:
            comm_id: 社区 ID
            depth: 子社区展开深度 (1=仅直达子社区, 2=孙子社区)
        """
        communities = self._store.get_communities(self._task_id)
        comm = next((c for c in communities if c.get("comm_id") == comm_id), None)
        if not comm:
            return ContextLayer(level="community", layer_id=comm_id, name=comm_id, what="未找到该社区")

        node_list = self._parse_json_list(comm.get("node_list", "[]"))
        edge_list = self._parse_json_list(comm.get("edge_list", "[]"))
        node_map = self._get_node_map()

        node_count = len(node_list)
        edge_count = len(edge_list)
        edge_type = comm.get("edge_type", "INCLUDE")

        # 识别 Hub 节点（高 degree）
        degree: dict[str, int] = {}
        for e in edge_list:
            src = e if isinstance(e, str) else e.get("source_id", e.get("source", ""))
            tgt = e if isinstance(e, str) else e.get("target_id", e.get("target", ""))
            degree[src] = degree.get(src, 0) + 1
            degree[tgt] = degree.get(tgt, 0) + 1
        hub_threshold = max(5, node_count * 0.3)
        hubs = [nid for nid, d in degree.items() if d > hub_threshold]

        # 子社区
        children = self._store.get_communities(self._task_id, edge_type=edge_type)
        child_comms = [
            c.get("comm_id", "")
            for c in children
            if c.get("parent_comm_id") == comm_id and c.get("comm_lv") not in ("HUB", "ORPHAN")
        ]

        hub_names = [node_map.get(h, {}).get("name", h) for h in hubs[:5]]
        child_summary = f"，包含 {len(child_comms)} 个子社区" if child_comms else "，无显著子社区"

        what = (
            f"社区 '{comm_id}' 包含 {node_count} 个节点、{edge_count} 条 {edge_type} 边，"
            f"是 {'依赖' if edge_type == 'INCLUDE' else '调用'}关系社区{child_summary}"
        )
        how = (
            f"Hub 节点: {', '.join(hub_names[:3]) if hub_names else '无显著 Hub'}。"
            f"社区由 {node_count} 个紧密关联的符号组成"
        )
        why = (
            f"该社区的形成原因需结合 {edge_type} 边的分布分析。"
            f"Hub 节点 ({len(hubs)} 个) 是社区的骨架——它们是社区凝聚力的来源，"
            f"也是潜在的架构瓶颈。"
        )

        return ContextLayer(
            level="community",
            layer_id=comm_id,
            name=comm.get("comm_id", comm_id),
            what=what,
            how=how,
            why=why,
            detail={
                "node_count": node_count,
                "edge_count": edge_count,
                "edge_type": edge_type,
                "hubs": hubs[:10],
                "hub_names": hub_names,
                "quality_score": comm.get("quality_score"),
            },
            children=child_comms,
        )

    # ═══════════════════════════════════════════
    # 文件层
    # ═══════════════════════════════════════════

    def get_file_layer(self, file_path: str) -> ContextLayer:
        """构建文件级上下文：符号列表、导入/导出、行数。"""
        nodes = self._store.get_graph_nodes(self._task_id)
        file_nodes = [n for n in nodes if n.get("file_path") == file_path]

        if not file_nodes:
            # 宽松匹配
            file_nodes = [n for n in nodes if file_path in (n.get("file_path") or "")]

        kinds: dict[str, int] = {}
        for n in file_nodes:
            k = n.get("kind", "unknown")
            kinds[k] = kinds.get(k, 0) + 1

        exported = [n.get("name") for n in file_nodes if n.get("is_exported")]
        imports = [n.get("name") for n in file_nodes if n.get("kind") == "import"]
        functions = [n.get("name") for n in file_nodes if n.get("kind") in ("function", "method")]

        what = (
            f"文件 '{file_path}' 包含 {len(file_nodes)} 个符号"
            + (f"，其中 {len(exported)} 个公开导出" if exported else "")
        )
        kind_str = ", ".join(f"{k}({v})" for k, v in sorted(kinds.items(), key=lambda x: -x[1]))
        how = f"符号类型分布: {kind_str}" if kind_str else "无类型分布信息"

        rel_nodes = [n for n in nodes if n.get("file_path") == file_path
                     and n.get("kind") in ("function", "method", "class")]
        why = (
            f"该文件在项目中的角色由 {len(functions)} 个函数/方法定义。"
            + (f" 公开符号 ({', '.join(exported[:5])}) 是外部依赖该文件的入口。" if exported else "")
        )

        return ContextLayer(
            level="file",
            layer_id=file_path,
            name=file_path.split("/")[-1] if "/" in file_path else file_path,
            what=what,
            how=how,
            why=why,
            detail={
                "symbol_count": len(file_nodes),
                "exported_count": len(exported),
                "kinds": kinds,
                "exported": exported[:10],
                "imports": imports[:5],
                "functions": functions[:10],
            },
            children=functions[:20],  # 子层: 关键函数名
        )

    # ═══════════════════════════════════════════
    # 符号层
    # ═══════════════════════════════════════════

    def get_symbol_layer(self, symbol_name: str) -> ContextLayer:
        """构建符号级上下文：签名、调用者、被调用者、所属社区。"""
        node_map = self._get_node_map()
        edges = self._store.get_graph_edges(self._task_id)

        # 查找目标节点
        target_node = None
        for nid, node in node_map.items():
            if node.get("name") == symbol_name:
                target_node = node
                break
            if node.get("qualified_name", "").endswith(f"::{symbol_name}"):
                target_node = node
                break

        if not target_node:
            return ContextLayer(
                level="symbol", layer_id=symbol_name, name=symbol_name, what=f"未找到符号 '{symbol_name}'"
            )

        node_id = target_node.get("id", "")
        kind = target_node.get("kind", "unknown")
        signature = target_node.get("signature", "")
        file_path = target_node.get("file_path", "")

        # 调用者 (calls edges where target_id == node_id)
        callers = []
        callees = []
        for e in edges:
            if e.get("target_id") == node_id and e.get("kind") == "calls":
                src_node = node_map.get(e.get("source_id", ""), {})
                callers.append(src_node.get("name", e.get("source_id", "")))
            if e.get("source_id") == node_id and e.get("kind") == "calls":
                tgt_node = node_map.get(e.get("target_id", ""), {})
                callees.append(tgt_node.get("name", e.get("target_id", "")))

        what = f"符号 '{symbol_name}' 类型为 {kind}" + (f"，签名: {signature}" if signature else "")
        how = (
            f"被 {len(callers)} 个函数调用" + (f" ({', '.join(callers[:5])})" if callers else "，未被调用")
            + f"，调用了 {len(callees)} 个函数"
            + (f" ({', '.join(callees[:5])})" if callees else "")
        )
        why = (
            f"该符号在文件 '{file_path}' 中定义。"
            + (f" 作为被 {len(callers)} 个调用者依赖的节点，修改它会影响调用链路。" if callers else "")
        )

        return ContextLayer(
            level="symbol",
            layer_id=node_id,
            name=symbol_name,
            what=what,
            how=how,
            why=why,
            detail={
                "kind": kind,
                "signature": signature,
                "file_path": file_path,
                "visibility": target_node.get("visibility", ""),
                "is_exported": target_node.get("is_exported", 0),
                "is_async": target_node.get("is_async", 0),
                "line": target_node.get("start_line", 0),
                "callers": callers[:10],
                "callees": callees[:10],
            },
            children=callees[:10],
        )

    # ═══════════════════════════════════════════
    # 路径遍历
    # ═══════════════════════════════════════════

    def get_downward_path(self, path: list[str]) -> list[ContextLayer]:
        """自顶向下路径遍历。

        Args:
            path: 路径描述，如 ["project", "comm-xxx", "src/api/handler.ts", "authenticate"]
                  第一条必须是 "project"

        Returns:
            按路径顺序的 ContextLayer 列表
        """
        layers: list[ContextLayer] = []
        for i, segment in enumerate(path):
            if i == 0 and segment == "project":
                layers.append(self.get_project_layer())
            elif i == 1:
                layers.append(self.get_community_layer(segment))
            elif i == 2:
                layers.append(self.get_file_layer(segment))
            elif i == 3:
                layers.append(self.get_symbol_layer(segment))
        return layers

    def get_upward_path(self, start_symbol: str) -> list[ContextLayer]:
        """自底向上路径遍历。

        从符号出发 → 所属文件 → 所属社区 → 项目总览。
        """
        layer = self.get_symbol_layer(start_symbol)
        if not layer.detail:
            return [layer]

        file_path = layer.detail.get("file_path", "")
        node_id = layer.layer_id

        # 查找符号所属的社区
        communities = self._store.get_communities(self._task_id)
        symbol_comm = None
        for comm in communities:
            node_list = self._parse_json_list(comm.get("node_list", "[]"))
            if node_id in node_list:
                symbol_comm = comm
                break

        layers: list[ContextLayer] = [layer]

        if file_path:
            layers.append(self.get_file_layer(file_path))

        if symbol_comm:
            layers.append(self.get_community_layer(symbol_comm.get("comm_id", "")))

        layers.append(self.get_project_layer())
        return layers

    # ═══════════════════════════════════════════
    # LLM 格式化
    # ═══════════════════════════════════════════

    def format_for_llm(self, layers: list[ContextLayer], direction: str = "top-down") -> str:
        """将上下文层级格式化为 LLM prompt 文本。

        Args:
            layers: ContextLayer 列表
            direction: "top-down" 或 "bottom-up"

        Returns:
            结构化的 prompt 文本
        """
        if direction == "top-down":
            return self._format_top_down(layers)
        else:
            return self._format_bottom_up(layers)

    def _format_top_down(self, layers: list[ContextLayer]) -> str:
        """自顶向下格式化：从项目总览逐层细化到源码。"""
        parts: list[str] = []
        indent = 0
        for i, layer in enumerate(layers):
            prefix = "  " * indent
            level_label = {"project": "项目", "community": "社区", "file": "文件", "symbol": "符号"}.get(
                layer.level, layer.level
            )
            parts.append(f"{prefix}## {level_label}: {layer.name}")
            parts.append(f"{prefix}  - 功能: {layer.what}")
            if layer.how:
                parts.append(f"{prefix}  - 逻辑: {layer.how}")
            if layer.why:
                parts.append(f"{prefix}  - 因果: {layer.why}")
            parts.append("")
            indent += 1
        return "\n".join(parts)

    def _format_bottom_up(self, layers: list[ContextLayer]) -> str:
        """自底向上格式化：从源码细节逐层抽象到架构总览。"""
        parts: list[str] = []
        for i, layer in enumerate(layers):
            level_label = {"project": "项目", "community": "社区", "file": "文件", "symbol": "符号"}.get(
                layer.level, layer.level
            )
            parts.append(f"## [{level_label}层] {layer.name}")
            parts.append(f"  {layer.what}")
            if layer.how and i > 0:  # 底层更关注实现
                parts.append(f"  实现逻辑: {layer.how}")
            if layer.why:
                parts.append(f"  设计因果: {layer.why}")
            parts.append("")
        return "\n".join(parts)

    # ═══════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════

    def check_ready(self, task_id: str | None = None) -> bool:
        """确认分析数据是否已就绪。"""
        tid = task_id or self._task_id
        try:
            count = self._store.count_graph_nodes(tid)
            return count > 0
        except Exception:
            return False

    def get_summary(self) -> dict:
        """获取分析数据摘要统计。"""
        try:
            total_nodes = self._store.count_graph_nodes(self._task_id)
            total_edges = len(self._store.get_graph_edges(self._task_id))
            incl_comms = len(self._store.get_communities(self._task_id, edge_type="INCLUDE"))
            call_comms = len(self._store.get_communities(self._task_id, edge_type="CALL"))
            return {
                "task_id": self._task_id,
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "include_communities": incl_comms,
                "call_communities": call_comms,
                "ready": total_nodes > 0,
            }
        except Exception as e:
            return {"task_id": self._task_id, "ready": False, "error": str(e)}

    @staticmethod
    def _parse_json_list(raw) -> list:
        """解析 JSON 字符串或已解码的列表。"""
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    @staticmethod
    def _parse_json_dict(raw) -> dict:
        """解析 JSON 字符串或已解码的字典。"""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
