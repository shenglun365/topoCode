"""收件人路由(感知层) — v2 统一会话混合触发路由。

P2 自 websocket._handle_kb_chat 迁入。回合输入三向分发:
  - attachTo=taskId(显式)         → transfer: 转达指定活跃任务
  - agent=executor(显式指派)      → 有活跃同型任务 → transfer;
                                     仅待确认任务 → 不吸收(引导用户确认);
                                     无任务 → assign: 注入指派契约走 architect 回合
  - 缺省                          → chat: architect 自由对话(可自主 task.propose)

特征测试: apps/architect/tests/test_kb_chat_routing.py(P0 契约固化)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RouteDecision:
    action: str                        # transfer | assign | chat
    reply: str = ""                    # transfer: 已回执文本(直接落库+回传, 零 LLM)
    task: Optional[dict] = None        # transfer: 命中的任务行
    contract: Optional[str] = ""       # assign: 指派契约(注入 system)


def decide(conv_id: str, question: str, attach_to: str, agent_pick: str,
           store, exec_bridge, digest: str = "") -> RouteDecision:
    """路由决策(纯输入→决策, IO 仅 task_input 转达)。

    digest: 语境摘要(用户选史生成)——仅 transfer 时随文本下发给执行器。"""
    if not (attach_to or (agent_pick and agent_pick not in ("architect", ""))):
        return RouteDecision(action="chat")
    task = None
    if attach_to:
        task = store.TasksStore.get(attach_to)
        if not task or (task.get("status") or "") not in ("running", "waiting_input"):
            task = None
    else:
        task = exec_bridge.active_task_of(conv_id)
        if task and (task.get("status") or "") == "pending_confirm":
            task = None   # 待确认任务不吸收输入——引导用户确认/取消
    if task and (attach_to or (task.get("executorType") or "opencode") == agent_pick
                 or not agent_pick):
        payload_text = question + (
            f"\n\n[附] 会话历史摘要(供参考):\n{digest}" if digest else "")
        res = exec_bridge.task_input(task["id"], payload_text)
        if res.get("ok"):
            queued = bool(res.get("queued"))
            ex = task.get("executorType") or "opencode"
            tail = f"（含历史摘要 {len(digest)} 字）" if digest else ""
            reply = (f"📥 已排队转达 `{ex}`{tail}（当前回合执行中，回合结束自动续跑）。"
                     if queued else
                     f"➡️ 已转达 `{ex}`{tail}（任务「{task.get('title', '')}」继续）。")
            return RouteDecision(action="transfer", reply=reply, task=task)
        err = str(res.get("error") or "")
        reply = (f"❌ 转达失败：{err or 'runner 不可达'}。可稍后重试。"
                 if err != "task-not-active" else
                 "该任务已不在执行中。可让 architect 重新发起任务。")
        return RouteDecision(action="transfer", reply=reply, task=task)
    if agent_pick:
        # 显式指派但无活跃任务: architect 回合 + 指派契约(评估→任务卡)
        contract = (
            f"【subagent 指派】用户直接指派执行器 `{agent_pick}` 处理上文, "
            "但当前没有活跃任务。请结合会话上下文整理任务(目标/方案要点/边界), "
            "调用 task.propose 创建任务卡(可指定 executorType="
            f"{agent_pick})供用户确认; 指令/上下文不足时先集中提问。")
        return RouteDecision(action="assign", contract=contract)
    return RouteDecision(action="chat")
