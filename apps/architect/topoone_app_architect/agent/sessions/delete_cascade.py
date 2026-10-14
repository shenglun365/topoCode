"""会话删除域(2610 裁决)——删除预览/执行守卫/级联清理的单一事实源。

用户裁决口径:
  - 主会话删除 = 整树删除(本体 + coding 子会话 + 关联需求 + 需求跟踪条目
    + 执行器会话留痕);
  - 删除前预览: 需求完成情况仅展示(不强制校验), 子会话运行状态必查;
  - 执行器会话必须执行完成: 本会话或任一子孙执行中 → 阻断整树删除;
  - 跨会话共享需求(克隆链经 reqId 引用)保留为项目资产, 仅清 ownerConv;
  - 非执行状态的子会话可单独删除(同守卫: 自身执行中则拒绝)。

路由层(arch_routes/sessions.py)只做 HTTP 编排; 本模块不感知路由。
"""
from __future__ import annotations

from ... import store
from ...store import states as ST

# 执行中状态口径: 活跃任务(running/waiting_input/pending_confirm) + 直通作业(proxy)
_ACTIVE_EXEC_STATES = ("running", ST.TASK_WAITING_INPUT, ST.TASK_PENDING_CONFIRM)


def active_execution_of(conv_id: str) -> str:
    """会话执行中状态(""=空闲): 活跃任务或直通执行器作业(quick 挡)。"""
    try:
        from ..execution import exec_bridge as _eb
        t = _eb.active_task_of(conv_id) if conv_id else None
        if t and (t.get("status") or "") in _ACTIVE_EXEC_STATES:
            return t.get("status") or "running"
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..execution.proxy import proxy_state
        if proxy_state(conv_id).get("active"):
            return "running"
    except Exception:  # noqa: BLE001
        pass
    return ""


def descendants_of(conv_id: str) -> list:
    """全部子孙会话(coding 子会话树, 广度收集; 防脏数据成环)。"""
    out, stack, seen = [], [conv_id], set()
    while stack:
        cur = stack.pop()
        for s in store.ConversationsStore.by_parent(cur):
            if s["id"] in seen or s["id"] == conv_id:
                continue
            seen.add(s["id"])
            out.append(s)
            stack.append(s["id"])
    return out


def delete_blockers(conv_id: str) -> list:
    """删除阻断清单: 本会话 + 子孙会话中执行中者(用户裁决: 须执行完成)。"""
    out = []
    conv = store.ConversationsStore.get(conv_id) or {}
    st = active_execution_of(conv_id)
    if st:
        out.append({"id": conv_id, "title": conv.get("title") or conv_id,
                    "executorId": conv.get("executorId") or "", "status": st})
    for s in descendants_of(conv_id):
        st = active_execution_of(s["id"])
        if st:
            out.append({"id": s["id"], "title": s.get("title") or s["id"],
                        "executorId": s.get("executorId") or "", "status": st})
    return out


def linked_requirements(conv: dict) -> list:
    """会话关联需求: conv.reqId 绑定 + source/owner 挂靠(去重)。"""
    out: dict = {}
    rid = str((conv or {}).get("reqId") or "").strip()
    if rid:
        r = store.RequirementsStore.get(rid)
        if r:
            out[r["id"]] = r
    conv_id = (conv or {}).get("id") or ""
    for r in store.RequirementsStore.all():
        if str(r.get("sourceConversationId") or "") == conv_id \
                or str(r.get("ownerConv") or "") == conv_id:
            out[r["id"]] = r
    return list(out.values())


def requirement_shared_elsewhere(req_id: str, exclude_conv_ids: set) -> bool:
    """需求是否被删除树之外的会话引用(克隆链经 reqId 共享) → 保留防误删。"""
    for c in store.ConversationsStore.all(limit=1000):
        if str(c.get("reqId") or "") == req_id and c.get("id") not in exclude_conv_ids:
            return True
    return False


def delete_preview(conv: dict) -> dict:
    """删除预览数据(路由透传): 级联清单 + 可删性。

    - 关联需求: 完成情况(status/doneMark)仅展示, 不强制校验;
    - 执行器会话(子孙/本会话直通)执行中 → deletable=false + blockers;
    - 共享需求(克隆链 reqId 被其他会话引用)保留, willDelete=false。
    """
    conv_id = conv.get("id") or ""
    tree_ids = {conv_id, *(s["id"] for s in descendants_of(conv_id))}

    blockers, subs = [], []
    self_st = active_execution_of(conv_id)
    if self_st:
        blockers.append({"id": conv_id, "title": conv.get("title") or conv_id,
                         "executorId": conv.get("executorId") or "",
                         "status": self_st, "self": True})
    for s in descendants_of(conv_id):
        st = active_execution_of(s["id"])
        subs.append({"id": s["id"], "title": s.get("title") or "coding 子会话",
                     "executorId": s.get("executorId") or "",
                     "status": s.get("status") or "active",
                     "execution": st, "msgCount": s.get("msgCount") or 0})
        if st:
            blockers.append({"id": s["id"], "title": s.get("title") or s["id"],
                             "executorId": s.get("executorId") or "",
                             "status": st, "self": False})
    reqs = []
    for r in linked_requirements(conv):
        shared = requirement_shared_elsewhere(r["id"], tree_ids)
        reqs.append({"id": r["id"], "title": (r.get("title") or r["id"])[:120],
                     "status": r.get("status") or "draft",
                     "doneMark": int(r.get("doneMark") or 0),
                     "shared": shared, "willDelete": not shared})
    try:
        from ...store.tracking import TrackingItemsStore
        pid = conv.get("projectId") or ""
        tracking_count = len(TrackingItemsStore.all(
            conversation_id=conv_id, project_id=pid or None, limit=1000)) if pid else 0
    except Exception:  # noqa: BLE001
        tracking_count = 0
    return {
        "id": conv_id, "title": conv.get("title") or "",
        "deletable": not blockers, "blockers": blockers,
        "requirements": reqs, "subSessions": subs,
        "trackingItemCount": tracking_count,
    }


def delete_session_cascade(conv_id: str) -> int:
    """级联删除会话及其关联数据条目(左侧删除 → 库内不留孤儿):

    - 停止该会话运行中作业(账本将随消息删除, 先终态化避免 runner 侧跑飞)
    - 递归删除 coding 子会话(parent_conv_id 链)
    - 需求跟踪台账: 清该会话(直接/主线)的条目(主会话删除时其子会话条目
      经 main_conversation_id 一并清除)
    - 需求: 关联需求(reqId 绑定 + source/owner 挂靠)随会话一并删除——
      状态不强制校验(用户裁决 2610); 跨会话共享(克隆链 reqId 引用)的
      需求保留为项目资产, 仅清空悬空 ownerConv 引用
    - 执行器会话留痕(arch_exec_events)随任务 runner 作业一并清理
    - 本体 + 消息(含 job_* 账本消息)随 ConversationsStore.delete

    返回级联删除的会话数(含自身)。"""
    from ..execution import exec_bridge
    try:
        exec_bridge.stop(conv_id, reason="deleted")  # 无运行作业时为 no-op
    except Exception:  # noqa: BLE001 — runner 不可达不阻断删除
        pass
    # v2: 活跃任务终态化(runner 侧停止) + 任务行级联删除 + 执行留痕清理
    job_ids: list = []
    try:
        from ...store import TasksStore
        for t in TasksStore.of_conv(conv_id):
            jid = str(t.get("runnerJobId") or "").strip()
            if jid:
                job_ids.append(jid)
            if (t.get("status") or "") in _ACTIVE_EXEC_STATES:
                if t.get("runnerJobId"):
                    try:
                        exec_bridge._runner(f"/api/implement/{t['runnerJobId']}/finish",
                                            {"keepWorktree": True}, timeout=10.0)
                    except Exception:  # noqa: BLE001
                        pass
        TasksStore.delete_by_conv(conv_id)
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..execution.proxy import proxy_job_of
        pjob = proxy_job_of(conv_id) or {}
        if pjob.get("job_id"):
            job_ids.append(str(pjob["job_id"]))
    except Exception:  # noqa: BLE001
        pass
    try:
        from ...store import exec_events
        exec_events.delete_by_jobs(job_ids)
    except Exception:  # noqa: BLE001
        pass
    # 需求跟踪台账: 清该会话(直接/主线)的条目; 递归子会话调用各清残留(失败不阻断)
    try:
        from ...store.tracking import TrackingItemsStore
        TrackingItemsStore.delete_by_conversation(conv_id)
    except Exception:  # noqa: BLE001
        pass
    n = 0
    for sub in store.ConversationsStore.by_parent(conv_id):
        n += delete_session_cascade(sub["id"])
    # 关联需求: 删除树外无引用 → 随会话删除; 共享(克隆链) → 保留+清 ownerConv
    tree_ids = {conv_id, *(s["id"] for s in descendants_of(conv_id))}
    for r in linked_requirements(store.ConversationsStore.get(conv_id) or {"id": conv_id}):
        if not requirement_shared_elsewhere(r["id"], tree_ids):
            store.RequirementsStore.delete(r["id"])
        elif (r.get("ownerConv") or "") == conv_id:
            store.RequirementsStore.update(r["id"], {"ownerConv": ""})
    store.ConversationsStore.delete(conv_id)
    return n + 1
