"""指令引导文案与会话状态快照(M2 自 sessions.py 机械迁出, 行为等价)。

「指令引导」按钮的提示材料单源: 系统提示(引用会话指令符号 /执行 /调整)+
需求版本链/任务状态两个 state 构建器。REST 面(/guide 等)仍居 sessions.py。
"""
from __future__ import annotations

from typing import Optional

from . import store

GUIDE_SYSTEM = (
    "你是「架构师工作台」的会话导航助手。基于给定的会话状态，给出 2-4 条下一步操作建议。\n"
    "要求：\n"
    "1. 每条建议必须引用会话中的具体内容（如需求标题、方案要点、作业分支、agent 提出的问题、"
    "待确认的版本），让建议与当前进展强相关；禁止泛泛而谈。\n"
    "2. 动作类建议必须引用**会话指令符号**（用户发送 /指令 即确定性执行）："
    "/执行 按需求卡建实施任务卡(卡片确认后 subagent 启动)、"
    "/调整 修订需求(进入对话整理)。语义匹配时才引用，无匹配时给自然语言建议。\n"
    "3. 输出 markdown 无序列表，每条一句话；只输出列表本身，不要标题、不要解释、不要代码围栏。"
)


def guide_req_state(req_id: str) -> Optional[dict]:
    if not req_id:
        return None
    try:
        rq = store.RequirementsStore.get(req_id) or {}
    except Exception:  # noqa: BLE001
        return None
    vers = rq.get("specVersions") or []
    tail = []
    for v in vers[-2:]:
        snap = v.get("snapshot") or {}
        tail.append({
            "ver": v.get("ver"), "state": v.get("state"),
            "title": (snap.get("title") or "")[:80],
            "hasAcceptance": bool(snap.get("acceptance")),
        })
    return {
        "id": rq.get("id") or req_id,
        "status": rq.get("status") or "",
        "activeVer": rq.get("activeVer"),
        "recentVersions": tail,
    }


def guide_jobs_state(conv_id: str) -> list:
    """v2 任务状态(P3: 旧 jobs 账本只读兜底)——guide 提示材料。"""
    try:
        from .store import TasksStore
        out = [{"taskId": t.get("id"), "title": (t.get("title") or "")[:60],
                "status": t.get("status"), "branch": t.get("branch") or ""}
               for t in TasksStore.of_conv(conv_id)[-3:]]
        return out
    except Exception:  # noqa: BLE001
        return []
