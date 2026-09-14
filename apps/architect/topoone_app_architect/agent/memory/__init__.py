"""④ 记忆管理层 — 会话派生记忆的统一归所。

units.py     上下文注册表(工具轨迹/产物/决策/摘要/执行回执单元 + ctx.search/get/summarize)
dossier.py   前置上下文装配(裁决3: 收集→裁剪→装配, 预算约束)
working.py   工作记忆(对话历史窗口 + prompt 装配)
store.py     MemoryStore 统一读面门面(消息/单元/文档/检索/装配/摘要)

三面暴露: 会话 agent 工具 / MCP(run_tool) / REST(context_registry shim)。
"""

from .store import MemoryStore  # noqa: F401
