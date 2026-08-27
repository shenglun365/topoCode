"""需求会话生命周期(4 段)：规划 / 待执行 / 执行中 / 已完成。

统一左栏会话分组(AgentWorkbench)与监控页状态口径。由 requirement.status 派生，
不新增列、不改写既有状态机——纯映射，保证与既有数据平滑兼容。
cancelled 单独处理：默认不进入 4 段(调用方可显式 include)。
"""
from typing import Dict

LIFECYCLE_PLANNING = "planning"    # 规划：plan 模式讨论中，未出结论
LIFECYCLE_READY = "ready"          # 待执行：方案/需求已定，可指派 subagent 执行
LIFECYCLE_EXECUTING = "executing"  # 执行中：subagent 运行中
LIFECYCLE_DONE = "done"            # 已完成

LIFECYCLE_ORDER = [LIFECYCLE_PLANNING, LIFECYCLE_READY, LIFECYCLE_EXECUTING, LIFECYCLE_DONE]

# requirement.status → 4 段 lifecycle
_STATUS_TO_LIFECYCLE: Dict[str, str] = {
    "raw": LIFECYCLE_PLANNING,
    "analyzing": LIFECYCLE_PLANNING,
    "analyzed": LIFECYCLE_READY,
    "designed": LIFECYCLE_READY,
    "planned": LIFECYCLE_READY,
    "executing": LIFECYCLE_EXECUTING,
    "done": LIFECYCLE_DONE,
    "cancelled": LIFECYCLE_PLANNING,
}


def lifecycle_of(status: str) -> str:
    """requirement.status → 4 段 lifecycle。未知/缺省 → 规划。"""
    return _STATUS_TO_LIFECYCLE.get(status or "raw", LIFECYCLE_PLANNING)


def build_session_groups(reqs: list, convs: list, include_cancelled: bool = False) -> dict:
    """会话分组(纯函数，便于单测)：需求行 + 会话行 → 4 段 lifecycle 分组。

    - 会话 = 需求 + 其对话(req_id → 最新会话)；
    - cancelled 默认排除；
    - 每组按 updatedAt 倒序。
    入参为 store 层 _row_to_api 形状(camelCase)。
    """
    conv_by_req: dict = {}
    for c in convs:  # ConversationsStore.all 已按 updatedAt 倒序，首个命中即最新
        rid = c.get("reqId") or ""
        if rid and rid not in conv_by_req:
            conv_by_req[rid] = c

    groups: dict = {k: [] for k in LIFECYCLE_ORDER}
    for r in reqs:
        status = r.get("status") or "raw"
        if status == "cancelled" and not include_cancelled:
            continue
        lc = lifecycle_of(status)
        conv = conv_by_req.get(r.get("id")) or {}
        groups[lc].append({
            "id": r.get("id"),
            "title": r.get("title") or "(未命名)",
            "priority": r.get("priority"),
            "kind": r.get("kind"),
            "status": status,
            "lifecycle": lc,
            "location": r.get("location"),
            "conversationId": conv.get("id") or "",
            "hasAnalysis": bool(r.get("analysis")),
            "hasDesign": bool(r.get("design")),
            "planId": r.get("planId") or "",
            "execId": r.get("execId") or "",
            "updatedAt": r.get("updatedAt") or 0,
        })
    for k in groups:
        groups[k].sort(key=lambda s: s.get("updatedAt") or 0, reverse=True)
    return groups
