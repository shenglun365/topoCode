"""统一记忆门面(记忆层) — 会话派生记忆的单一读面。

P4 方案的 MemoryStore 落地: 消息/单元/备案文档/检索/装配五面统一入口,
供 orchestrator/MCP/外部集成经一个对象取用, 不再各自拼装 store 查询。
写侧仍归各 Store(Conversations/ContextUnits/Docs); 本门面只读聚合。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class MemoryStore:
    """会话记忆门面(无状态, 每方法独立解析数据面——agent 包循环导入防线)。"""

    def __init__(self, conv_id: str):
        self.conv_id = conv_id

    # ── 原始面 ──

    def messages(self, limit: int = 1000) -> List[Dict[str, Any]]:
        from ...arch_routes import store
        return store.ConversationsStore.messages(self.conv_id, limit=limit)

    def conv(self) -> Optional[Dict[str, Any]]:
        from ...arch_routes import store
        return store.ConversationsStore.get(self.conv_id)

    def units(self, limit: int = 100) -> List[Dict[str, Any]]:
        from ...arch_routes import store
        return store.ContextUnitsStore.all(conversation_id=self.conv_id, limit=limit)

    def docs(self, limit: int = 5) -> List[Dict[str, Any]]:
        from ...arch_routes import store
        return store.DocsStore.all(conversation_id=self.conv_id, limit=limit)

    # ── 加工面(委托 units/dossier) ──

    def search(self, query: str, type_: str = "", limit: int = 10) -> str:
        """跨会话检索(单元+消息+备案文档, Markdown 命中列表)。"""
        from .units import ctx_search
        return ctx_search(query, type_=type_, conversation_id=self.conv_id, limit=limit)

    def pack(self) -> str:
        """会话上下文包(摘要+关键单元+备案文档, MD)。"""
        from .units import ctx_get
        return ctx_get(self.conv_id)

    def dossier(self, reqs: Optional[list] = None, root: str = "",
                project_id: str = "", persist: bool = True) -> Optional[str]:
        """前置上下文装配(裁决3: 收集→裁剪→预算约束)。"""
        from .dossier import assemble_dossier
        return assemble_dossier(self.conv_id, reqs=reqs, root=root,
                                project_id=project_id, persist=persist)

    def summarize(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """生成/刷新会话摘要(标题+结论/决策/待办)。"""
        from .units import summarize_conversation
        return summarize_conversation(self.conv_id, force=force)
