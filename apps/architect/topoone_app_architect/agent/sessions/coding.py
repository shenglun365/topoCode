"""coding 子会话编排(M2 自 sessions.py 机械迁出, 行为等价)。

职责: 活跃 coding 子会话指针(meta.activeCodingSession)读写 + 分析→coding
信息中继摘要(S4, best-effort)。REST 面仍居 sessions.py(/coding-sessions 等)。
"""
from __future__ import annotations

import json


def _meta_of(conv: dict) -> dict:
    meta = conv.get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (TypeError, ValueError):
            meta = {}
    return meta or {}


def _set_active_coding_session(conv_id: str, sub_id: str) -> None:
    from ...arch_routes import store
    meta = _meta_of(store.ConversationsStore.get(conv_id) or {})
    meta["activeCodingSession"] = sub_id
    store.ConversationsStore.update(conv_id, {"meta": meta})


async def _summarize_for_coding(text: str) -> tuple:
    """LLM 摘要转发(S4): 压缩为 coding 结论段(best-effort, 失败回退原文)。

    返回 (文本, 是否经摘要)。LLM 不可达/空产出 → 原文 + False。
    """
    import asyncio
    from ...arch_routes.adaptation import summarize_task
    sys_prompt = (
        "你是架构师到执行工程师的信息中继。把下面的分析内容压缩成给 coding agent "
        "的直接结论段：\n"
        "- 保留: 结论 / 约束 / 具体参数 / 接口要求 / 必须遵守的规则\n"
        "- 剥离: 分析过程 / 备选方案讨论 / 寒暄 / 与实现无关的背景\n"
        "- 保持原文的具体数值与技术术语, 不要泛化、不要新增推断\n"
        "- 输出纯文本(可含短列表), 不加标题不加解释, 200 字以内"
    )
    out = await asyncio.to_thread(
        summarize_task, task_id="coding_relay", system=sys_prompt,
        material=text[:8000], max_tokens=400,
        parse=lambda r: str(r.get("content") or "").strip() or None)
    content = out["output"]
    return (content, True) if content else (text, False)
