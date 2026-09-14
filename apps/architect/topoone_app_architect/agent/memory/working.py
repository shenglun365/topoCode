"""④ 工作记忆 — 对话回合的历史窗口装配。

build_chat_messages: 能力文档 system(tier 分级+预算裁剪) + 最近 N 条历史。
P4 自 orchestrator._build_chat_messages 迁入(委托保真)。
"""
from __future__ import annotations

from typing import List, Optional


def history_window(history, cap: int = 20) -> List[dict]:
    """滑动历史窗口: 仅保留 user/assistant 且非空消息, 尾部 cap 条。"""
    out = []
    for m in (history or [])[-cap:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") \
                and (m.get("content") or "").strip():
            out.append({"role": m["role"], "content": m["content"]})
    return out


def build_chat_messages(root, project, history, cap=20, diagram_skill: bool = False,
                        skill_scenarios: Optional[List[str]] = None,
                        model_id: str = "") -> List[dict]:
    """组装 prompt: 能力文档(system) + 最近 N 条历史。

    skill_scenarios 非空 → 按场景注入语义资产 skill 文档（资产管理对话='extract'）。
    model_id 非空 → 查模型能力档案(小模型收紧预算/大模型放开)。
    """
    from ...arch_routes.req_agent import chat_system_prompt
    msgs: List[dict] = [{"role": "system", "content": chat_system_prompt(
        root, project, diagram_skill=diagram_skill, skill_scenarios=skill_scenarios,
        model_id=model_id)}]
    msgs.extend(history_window(history, cap=cap))
    return msgs
