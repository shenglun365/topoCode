"""会话中心 routes(P1) —— 会话是唯一主体。

裁决对齐:
  - 只有会话没有流程: 列表/分组全部基于元数据(标题/时间/模块/自定义分组)，
    不再有需求池/待执行等流程分组;
  - 需求文档 = 备案文档(DocsStore): 从会话随时总结提取、随时增删;
  - 全量持久化: ConversationsStore + tags/summary, 支撑历史总结。

项目路由: 与 /requirements 同口径, 经 ProjectContextMiddleware 的 ?project=。
"""
import asyncio
import json
import re
from typing import Optional

from fastapi import APIRouter, Request
import fastapi
from fastapi.responses import StreamingResponse

from .common import _ts, ok, err
from . import store
from .store import states as ST
from . import ws_events

router = APIRouter()

# 会话中心全量口径(含资产/设计对话; execution/unit-test 会话由对应域自持, 此处也收录)
SESSION_KINDS = ["requirement", "asset", "unit-test", "generic"]

# PR1 双维度状态机: 生命周期(status) + 查看状态(review_state)
# (旧 LIFECYCLES 残留值 "running" 已清退——执行相位语义由 flow_state 承载
#  [governance/flow.py 派生缓存], status 只管 active/archived 生命周期)
LIFECYCLES = ("active", "archived")                      # archived 不可逆终态
REVIEW_STATES = ("read", "unread", "awaiting_reply", "error")

_GROUPS_KEY = "session.groups"      # 用户自定义分组(collab config, JSON 数组)


def _tags_of(conv: dict) -> dict:
    tags = conv.get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (TypeError, ValueError):
            tags = None
    if not isinstance(tags, dict):
        tags = {}
    return {
        "modules": [str(x) for x in (tags.get("modules") or []) if str(x).strip()],
        "groups": [str(x) for x in (tags.get("groups") or []) if str(x).strip()],
    }


def _norm_tags(data: dict) -> Optional[dict]:
    """请求体 tags → 规范形 {modules,groups}(str 列表)；非法返回 None。"""
    tags = data.get("tags")
    if tags is None:
        return None
    if not isinstance(tags, dict):
        return None
    out = {}
    for key in ("modules", "groups"):
        vals = tags.get(key)
        if vals is None:
            vals = []
        if not isinstance(vals, list):
            return None
        out[key] = [str(x).strip() for x in vals if str(x).strip()]
    return out


def _user_groups() -> list:
    raw = store.CollabConfigStore.get(_GROUPS_KEY, "")
    try:
        vals = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        vals = []
    return [str(x) for x in vals if str(x).strip()] if isinstance(vals, list) else []


@router.get("/events")
async def sse_events(request: Request):
    """会话事件流(SSE): job 消息等后端异步写入实时通知前端刷新信息流。

    事件形如 {"type":"conv-message","conversationId":...}; 前端按会话过滤后
    重拉消息(满队列/断线由重连+重拉兜底)。启动时首帧绑事件循环(线程安全发布)。
    """
    ws_events.bind_loop()
    q = ws_events.subscribe()

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            ws_events.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/sessions")
async def list_sessions(kind: str = "", q: str = "", limit: int = 400, scope: str = "",
                        project: str = ""):
    """会话列表(全量会话 + 消息数/预览)。q: 标题/摘要模糊过滤(前端侧也过滤)。

    project=<id>: 项目隔离视图(全库扫描后按 project_id 列过滤——历史行可能
    落在主库, 不走单库路由); scope=all: 跨全库统一视图(显式开启才生效);
    两者缺省: 按请求上下文 ?project= 路由的既有行为。
    """
    # coding 子会话不进列表(防污染): 经主会话「子会话池」弹层管理/进入;
    # 显式 ?kind=coding 查询(子会话管理面)不受影响
    rows = store.ConversationsStore.summaries(
        kind=kind or None, limit=limit, project_id=project or None,
        all_scopes=(scope == "all") or bool(project))
    if kind != "coding":
        rows = [c for c in rows if (c.get("kind") or "") != "coding"]
    items = []
    for c in rows:
        title = c.get("title") or ""
        item = {
            "id": c["id"],
            "kind": c.get("kind") or "requirement",
            "reqId": c.get("reqId") or "",
            "title": title,
            "status": c.get("status") or "active",
            "workState": c.get("workState") or "architect",
            "analysisMode": c.get("analysisMode") or "strict",
            "clarifyMode": c.get("clarifyMode") or "auto",
            "isolated": bool(c.get("isolated")),
            "reviewState": c.get("reviewState") or "read",
            "flowState": c.get("flowState") or "",
            "roles": _roles_of(c),
            "executorId": c.get("executorId") or "",
            "executorModel": c.get("executorModel") or "",
            "parentConvId": c.get("parentConvId") or "",
            "runningRole": _running_role_of(c),
            "tags": _tags_of(c),
            "summary": c.get("summary") or "",
            "msgCount": c.get("msgCount") or 0,
            "preview": (c.get("preview") or "").strip()[:160],
            "firstUserTime": c.get("firstUserTime") or 0,
            "createdAt": c.get("createdAt"),
            "updatedAt": c.get("updatedAt"),
            "projectId": c.get("projectId") or "",
        }
        if q and q.strip():
            ql = q.strip().lower()
            if ql not in title.lower() and ql not in (item["summary"] or "").lower():
                continue
        items.append(item)
    return ok(items)


@router.get("/sessions/groups")
async def list_groups(scope: str = "", project: str = ""):
    """分组维度: 用户自定义分组 + 会话身上出现过的 modules/groups 并集。

    project=<id>: 项目隔离(与 /sessions 同口径); scope=all: 跨全库统一视图。"""
    convs = store.ConversationsStore.summaries(
        limit=400, project_id=project or None,
        all_scopes=(scope == "all") or bool(project))
    modules, groups = [], []
    for c in convs:
        t = _tags_of(c)
        for m in t["modules"]:
            if m not in modules:
                modules.append(m)
        for g in t["groups"]:
            if g not in groups:
                groups.append(g)
    for g in _user_groups():
        if g not in groups:
            groups.append(g)
    # 用户自定义分组置前(稳定顺序: 保存序优先)
    ordered = [g for g in _user_groups() if g in groups] + \
              [g for g in groups if g not in _user_groups()]
    return ok({"groups": ordered, "modules": sorted(modules)})


@router.put("/sessions/groups")
async def put_groups(request: Request):
    """保存用户自定义分组列表(仅分组名; 会话归属经 PATCH /sessions/{id} tags.groups)。"""
    data = await request.json()
    groups = data.get("groups")
    if not isinstance(groups, list):
        return err(400, "groups 必须为数组")
    names = [str(x).strip() for x in groups if str(x).strip()]
    store.CollabConfigStore.set(_GROUPS_KEY, json.dumps(names, ensure_ascii=False))
    return ok({"groups": names})


@router.post("/sessions")
async def create_session(request: Request):
    data = await request.json()
    kind = data.get("kind") or "requirement"
    if kind not in SESSION_KINDS:
        kind = "requirement"
    title = (data.get("title") or "").strip()
    executor_id = str(data.get("executorId") or "").strip()
    executor_model = ""
    if executor_id:
        from .agent_executors import load_executors
        ex = next((e for e in load_executors() if e.get("id") == executor_id), None)
        if not ex:
            return err(400, f"执行器实例不存在: {executor_id}")
        executor_model = str(data.get("model") or "").strip()
        if executor_model:
            allowed = _executor_model_names(ex)
            if allowed and executor_model not in allowed:
                return err(400, f"模型 {executor_model} 不在执行器 {executor_id} 白名单内")
            if not allowed:
                executor_model = ""
    conv = store.ConversationsStore.create({
        "kind": kind,
        "projectId": data.get("projectId") or "",
        "title": title or f"{kind} 会话",
        "status": "active",
        "executorId": executor_id,
        "executorModel": executor_model,
        "parentConvId": str(data.get("parentConvId") or "").strip(),
        "roles": ["architect"],
        "tags": _norm_tags(data) or {"modules": [], "groups": []},
        "meta": data.get("meta") or {},
    })
    # create 返回 snake_case payload; 回显统一取 API 形状行
    return ok(_conv_api(store.ConversationsStore.get(conv["id"]) or conv))


@router.patch("/sessions/{conv_id}")
async def update_session(conv_id: str, request: Request):
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    data = await request.json()
    patch: dict = {}
    if "title" in data:
        title = str(data.get("title") or "").strip()
        if not title:
            return err(400, "标题不能为空")
        if title != (conv.get("title") or ""):
            patch["title"] = title
            # 手动改名留痕: 后续系统自动摘要不再覆盖该标题
            try:
                meta = json.loads(conv.get("meta") or "{}") if isinstance(conv.get("meta"), str) else (conv.get("meta") or {})
            except (TypeError, ValueError):
                meta = {}
            if isinstance(meta, dict):
                meta["titleEdited"] = True
                patch["meta"] = meta
    if "summary" in data:
        patch["summary"] = str(data.get("summary") or "")
    if "status" in data:
        status = str(data.get("status") or "").strip()
        if status not in ("active", "archived"):
            return err(400, f"非法生命周期状态: {status}(active|archived)")
        if (conv.get("status") or "active") == "archived" and status != "archived":
            return err(400, "归档不可逆：归档会话只读，请复制到新会话继续")
        patch["status"] = status
    if "reviewState" in data:
        rs = str(data.get("reviewState") or "").strip()
        if rs not in REVIEW_STATES:
            return err(400, f"非法查看状态: {rs}(read|unread|awaiting_reply|error)")
        patch["reviewState"] = rs
    # 执行器绑定不可经 PATCH 变更(一次绑定; 换=克隆)——显式拒绝防误用
    if "executorId" in data and str(data.get("executorId") or "").strip() != (conv.get("executorId") or ""):
        return err(409, "执行器绑定不可修改(一次绑定)。请克隆会话绑定其他执行器。")
    tags = _norm_tags(data)
    if tags is not None:
        patch["tags"] = tags
    if not patch:
        return err(400, "无可更新字段")
    updated = store.ConversationsStore.update(conv_id, patch)
    result = _conv_api(updated or conv)
    # P5: 会话归档即时提示可提炼内容(廉价启发: 消息数达标)
    if patch.get("status") == "archived":
        try:
            n = len(store.ConversationsStore.messages(conv_id, limit=200))
            result["mineableHint"] = n >= 8
        except Exception:
            result["mineableHint"] = False
    return ok(result)


@router.delete("/sessions/{conv_id}")
async def delete_session(conv_id: str):
    if not store.ConversationsStore.get(conv_id):
        return err(404, "会话不存在")
    cascade = _delete_session_cascade(conv_id)
    return ok({"deleted": True, "id": conv_id, "cascadeConversations": cascade})


def _delete_session_cascade(conv_id: str) -> int:
    """级联删除会话及其关联数据条目(左侧删除 → 库内不留孤儿):

    - 停止该会话运行中作业(账本将随消息删除, 先终态化避免 runner 侧跑飞)
    - 递归删除 coding 子会话(parent_conv_id 链)
    - 需求: sourceConversationId=本会话且未定稿(draft/cancelled)的提案 → 删
      (孤儿提案无演进上下文); 已定稿/完结(ready/done)是项目资产 → 保留,
      仅清空悬空 ownerConv 引用
    - 本体 + 消息(含 job_* 账本消息)随 ConversationsStore.delete

    返回级联删除的会话数(含自身)。"""
    from . import exec_bridge
    try:
        exec_bridge.stop(conv_id, reason="deleted")  # 无运行作业时为 no-op
    except Exception:  # noqa: BLE001 — runner 不可达不阻断删除
        pass
    # v2: 活跃任务终态化(runner 侧停止) + 任务行级联删除
    try:
        from .store import TasksStore
        for t in TasksStore.of_conv(conv_id):
            if (t.get("status") or "") in ("running", ST.TASK_WAITING_INPUT, ST.TASK_PENDING_CONFIRM):
                if t.get("runnerJobId"):
                    try:
                        exec_bridge._runner(f"/api/implement/{t['runnerJobId']}/finish",
                                            {"keepWorktree": True}, timeout=10.0)
                    except Exception:  # noqa: BLE001
                        pass
        TasksStore.delete_by_conv(conv_id)
    except Exception:  # noqa: BLE001
        pass
    # 需求跟踪台账: 清该会话(直接/主线)的条目——主会话删除时其子会话条目
    # 经 main_conversation_id 一并清除; 递归子会话调用各清残留(失败不阻断)
    try:
        from .store.tracking import TrackingItemsStore
        TrackingItemsStore.delete_by_conversation(conv_id)
    except Exception:  # noqa: BLE001
        pass
    n = 0
    for sub in store.ConversationsStore.by_parent(conv_id):
        n += _delete_session_cascade(sub["id"])
    for r in store.RequirementsStore.all():
        if r.get("sourceConversationId") == conv_id and (r.get("status") or "draft") in ("draft", "cancelled"):
            store.RequirementsStore.delete(r["id"])
        elif r.get("ownerConv") == conv_id:
            store.RequirementsStore.update(r["id"], {"ownerConv": ""})
    store.ConversationsStore.delete(conv_id)
    return n + 1


@router.get("/sessions/{conv_id}/messages")
async def session_messages(conv_id: str):
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    # T3 恢复扩面: 打开会话(只读查看)即惰性核对 running/waiting_input 任务——
    # 不再要求用户必须发消息才自愈(cv-161: 服务重启后泵丢失, 任务假 running)
    try:
        from . import exec_bridge as _eb
        if any((t.get("status") or "") in ("running", ST.TASK_WAITING_INPUT)
               for t in store.TasksStore.of_conv(conv_id)):
            rec = await asyncio.to_thread(_eb.recover_conv_tasks, conv_id)
            for tid, jid, rid, ag in (rec or {}).get("repump", []):
                _eb._start_task_pump(conv_id, tid, jid, rid, ag)
    except Exception:  # noqa: BLE001
        pass
    # 流程相位惰性回填/对账(governance/flow.py; 空缓存与漂移在此自修复)
    try:
        from ..agent.governance import flow as _flow
        await asyncio.to_thread(_flow.recompute, conv_id, trigger="open")
    except Exception:  # noqa: BLE001
        pass
    msgs = store.ConversationsStore.messages(conv_id, limit=1000)
    # A6.2 UI 守门: 卡片消息读侧投影为 item——前端只渲染 item, 零 meta.kind 分支
    try:
        from ..agent.execution.items import item_from_card
        for m in msgs:
            it_ = item_from_card(m.get("meta"), m.get("content") or "",
                                 ts=m.get("time"), msg_id=m.get("id") or "")
            if it_:
                m["item"] = it_
    except Exception:  # noqa: BLE001 — 投影失败降级为原始消息(不影响读取)
        pass
    return ok({"id": conv_id, "messages": msgs})


@router.get("/sessions/{conv_id}/items")
async def session_stream_items(conv_id: str,
                               task_id: str = fastapi.Query("", alias="taskId"),
                               before_ts: int = fastapi.Query(0, alias="beforeTs"),
                               limit: int = fastapi.Query(200, alias="limit")):
    """会话流 item(A6.2: 工具轨迹/文件变更/通知, 新→旧; beforeTs 分页回载挂点)。

    落消息类卡片经 /messages 的 item 投影渲染, 不入流表(单一来源)。
    """
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    rows = store.StreamItemsStore.for_conv(conv_id, task_id=task_id or None,
                                           before_ts=before_ts or None,
                                           limit=max(1, min(limit, 500)))
    return ok({"items": rows})


@router.post("/sessions/{conv_id}/summarize")
async def summarize_session(conv_id: str, force: int = 0):
    """生成/刷新会话标题与摘要(标题兜底: 首条用户消息截断) + session_summary 单元。

    force=1: 用户显式触发(悬停按钮) → 总是重新生成标题; 默认(系统自动)尊重手改标题。
    """
    from . import context_registry
    conv = context_registry.summarize_conversation(conv_id, force=bool(force))
    if not conv:
        return err(404, "会话不存在")
    return ok(_conv_api(conv))


@router.get("/sessions/{conv_id}/context")
async def session_context(conv_id: str):
    """会话上下文单元列表(会话中心详情「上下文」块)。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    units = store.ContextUnitsStore.all(conversation_id=conv_id, limit=100)
    return ok([{
        "id": u["id"], "type": u.get("type") or "note",
        "title": u.get("title") or "", "content": (u.get("content") or "")[:400],
        "importance": u.get("importance") or 0, "createdAt": u.get("createdAt"),
    } for u in units])


def _roles_of(conv: dict) -> list:
    """legacy(T4 清退): 会话角色字段已僵尸化——恒回默认值保持 API 兼容。
    实际会话身份: executor_id 绑定(工具栏) + runningRole 推导(work_state)。"""
    return ["architect"]


def _running_role_of(conv: dict) -> dict:
    """running 归属推导(纯提示): v2 活跃任务(running|waiting_input) → coding+执行器。

    P6 单读: 仅 arch_tasks 驱动(旧 meta.jobs 账本写路径已清退, 不再双读)。"""
    try:
        from . import exec_bridge as _eb
        t = _eb.active_task_of(conv["id"]) if conv.get("id") else None
        if t and (t.get("status") or "") in ("running", ST.TASK_WAITING_INPUT):
            out = {"role": "coding",
                   "executorId": t.get("executorType") or "opencode",
                   "status": t.get("status") or "",
                   "taskId": t.get("id") or ""}
            if isinstance(t.get("progress"), dict):
                out["progress"] = t["progress"]
            return out
    except Exception:  # noqa: BLE001
        pass
    return {"role": "architect", "executorId": "", "status": ""}


def _tasks_of_conv(conv: dict) -> list:
    """v2 统一会话: 会话任务清单(arch_tasks, 倒序)。失败静默(旧库无表)。"""
    try:
        from .store import TasksStore
        ts = TasksStore.of_conv(conv.get("id") or "") or []
        ts.sort(key=lambda t: (t.get("createdAt") or 0), reverse=True)
        return ts
    except Exception:  # noqa: BLE001
        return []


def _conv_api(conv: dict) -> dict:
    meta = conv.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta or "{}")
        except Exception:  # noqa: BLE001
            meta = {}
    return {
        "id": conv["id"],
        "kind": conv.get("kind") or "generic",
        "reqId": conv.get("reqId") or "",
        "title": conv.get("title") or "",
        "status": conv.get("status") or "active",
        "workState": conv.get("workState") or "architect",
        "reviewState": conv.get("reviewState") or "read",
        "flowState": conv.get("flowState") or "",
        "flowStateAt": conv.get("flowStateAt") or 0,
        "roles": _roles_of(conv),
        "executorId": conv.get("executorId") or "",
        "executorModel": conv.get("executorModel") or "",
        "parentConvId": conv.get("parentConvId") or "",
        "sessionRef": conv.get("sessionRef") or "",
        "runningRole": _running_role_of(conv),
        "tasks": _tasks_of_conv(conv),
        "tags": _tags_of(conv),
        "summary": conv.get("summary") or "",
        "subUnread": int(meta.get("subUnread") or 0),
        "activeCodingSession": str(meta.get("activeCodingSession") or ""),
        "createdAt": conv.get("createdAt"),
        "updatedAt": conv.get("updatedAt"),
    }


def _executor_model_names(entry: dict) -> list:
    """执行器白名单模型名(config.models[].name)。"""
    return [str(m.get("name") or m.get("model") or "")
            for m in ((entry.get("config") or {}).get("models") or [])
            if (m.get("name") or m.get("model"))]


@router.post("/sessions/{conv_id}/distill-errors")
async def distill_errors_route(conv_id: str, limit: int = 20):
    """错误提炼(P1, 手动触发): 会话错误历史 → error_pattern 项目级知识单元。

    提炼即沉淀(build/land 分离为扩展点, 本期直连); 归因以 coding agent
    失败回执为准; 同签名追加场景不增行。前端触发位后续再定。
    """
    from ..agent.memory.distill import distill_errors
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    result = await asyncio.to_thread(distill_errors, conv_id, max(1, min(limit, 50)))
    if not result.get("ok"):
        return err(502, result.get("error") or "distill-failed")
    return ok(result)


@router.post("/sessions/{conv_id}/bind")
async def bind_executor(conv_id: str, request: Request):
    """绑定 coding 执行器——一次绑定不可换(换=克隆)。architect 角色恒有, 不在绑定面。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    if (conv.get("executorId") or "").strip():
        return err(409, f"已绑定执行器 {conv['executorId']}(一次绑定不可切换)。"
                        "请克隆会话绑定其他执行器。")
    data = await request.json()
    executor_id = str(data.get("executorId") or "").strip()
    if not executor_id:
        return err(400, "executorId 必填")
    from .agent_executors import load_executors
    ex = next((e for e in load_executors() if e.get("id") == executor_id), None)
    if not ex:
        return err(400, f"执行器实例不存在: {executor_id}")
    patch = {"executorId": executor_id}
    model = str(data.get("model") or "").strip()
    if model:
        allowed = _executor_model_names(ex)
        if allowed and model not in allowed:
            return err(400, f"模型 {model} 不在执行器 {executor_id} 白名单内, "
                            f"可选: {', '.join(allowed[:8])}")
        patch["executorModel"] = model
    updated = store.ConversationsStore.update(conv_id, patch)
    return ok(_conv_api(updated or conv))


@router.post("/sessions/{conv_id}/model")
async def set_session_model(conv_id: str, request: Request):
    """切换会话执行器模型(随时生效于**下次执行**——进行中作业模型已固化, 不受影响)。

    body: {model} 白名单内模型名 | ""(恢复默认=白名单首个)。
    """
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    if not (conv.get("executorId") or "").strip():
        return err(400, "会话未绑定执行器, 先绑定再选模型")
    data = await request.json()
    model = str(data.get("model") or "").strip()
    from .agent_executors import load_executors
    ex = next((e for e in load_executors()
               if e.get("id") == (conv.get("executorId") or "").strip()), None)
    if not ex:
        return err(400, f"绑定执行器 {conv.get('executorId')} 已不存在于注册表")
    allowed = _executor_model_names(ex)
    if model and allowed and model not in allowed:
        return err(400, f"模型 {model} 不在执行器白名单内, 可选: {', '.join(allowed[:8])}")
    if model and not allowed:
        return err(400, "该执行器未配置模型白名单(config.models), 无可选模型")
    updated = store.ConversationsStore.update(conv_id, {"executorModel": model})
    note = ("恢复默认(白名单首个)" if not model
            else f"模型已切换为 {model}")
    running = _running_role_of(conv).get("role") == "coding"
    return ok({"executorModel": model,
               "summary": note + ("；进行中作业不受影响, 下次执行生效" if running
                                  else "；下次执行生效")})


@router.post("/sessions/{conv_id}/analysis-mode")
async def set_analysis_mode(conv_id: str, request: Request):
    """切换会话分析挡位(即时生效于本会话后续回合)。

    body: {mode} — quick=T0 直通车 | strict/auto=按执行器能力自动 |
    T0-T2=钉死指定档(刻度细则见 agent/governance/gears.py; 旧 T3/T4 归一)。
    """
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    data = await request.json()
    mode = str(data.get("mode") or "").strip()
    from ..agent.governance.gears import GEAR_MODES, gear_note, normalize_mode
    mode = normalize_mode(mode)
    if mode not in GEAR_MODES:
        return err(400, f"mode 须为 {'/'.join(GEAR_MODES)}")
    store.ConversationsStore.update(conv_id, {"analysisMode": mode})
    return ok({"conversationId": conv_id, "analysisMode": mode,
               "summary": gear_note(mode)})


@router.post("/sessions/{conv_id}/isolated")
async def set_isolated(conv_id: str, request: Request):
    """worktree 隔离模式(cv-202): on=显式要求隔离执行(任务在 worktree 分支
    作业, 合并回主目录); off=就地(直接写入项目目录, 缺省)。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    data = await request.json()
    on = bool(data.get("on"))
    store.ConversationsStore.update(conv_id, {"isolated": 1 if on else 0})
    return ok({"conversationId": conv_id, "isolated": on,
               "summary": "隔离模式已开启(任务在 worktree 分支作业, 合并后生效)"
               if on else "就地模式(直接写入项目目录)"})


@router.post("/sessions/{conv_id}/clarify-mode")
async def set_clarify_mode(conv_id: str, request: Request):
    """需求澄清挡位: auto(自动, 缺口驱动) | forced(强制, 先澄清后落卡)。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    data = await request.json()
    mode = str(data.get("mode") or "").strip()
    if mode not in ("auto", "forced"):
        return err(400, "mode 须为 auto/forced")
    store.ConversationsStore.update(conv_id, {"clarifyMode": mode})
    label = ("自动(规约有缺口才集中提问)" if mode == "auto"
             else "强制(每需求回合先澄清后落卡; 明确指令自动跳过)")
    return ok({"conversationId": conv_id, "clarifyMode": mode, "summary": label})


@router.post("/sessions/{conv_id}/msg-digest")
async def msg_digest(conv_id: str, request: Request):
    """语境摘要(转达下发): 统一流中用户选中的消息 → LLM 压缩为给 coding 的转达摘要。

    body: {msgIds: [...], hint?: 关注点}。上限 50 条/条内 1500 字/素材 6000 字。
    LLM 不可达/空产出 → 确定性降级原文截断(summarized=false), 永不 5xx。
    返回 {digest, chars, summarized}。
    """
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    data = await request.json()
    ids = data.get("msgIds") or []
    if not isinstance(ids, list) or not ids:
        return err(400, "msgIds 须为非空数组")
    idset = {str(x) for x in ids[:50]}
    msgs = [m for m in store.ConversationsStore.messages(conv_id, limit=200)
            if m.get("id") in idset]
    if not msgs:
        return err(404, "选中消息不存在")
    lines = []
    for m in msgs:
        if m.get("role") == "user":
            role = "用户"
        elif (m.get("agent") or "") not in ("", "architect"):
            role = f"执行器 {m['agent']}"
        else:
            role = "assistant"
        c = (m.get("content") or "").strip()[:1500]
        if c:
            lines.append(f"[{role}] {c}")
    if not lines:
        return err(400, "选中消息无正文")
    material = "\n".join(lines)[:6000]
    hint = str(data.get("hint") or "").strip()
    sys_prompt = (
        "你把一段项目会话记录压缩成给 coding agent 的转达摘要。要求:\n"
        "- 保留: 与当前任务相关的结论/决定/约束/参数/文件名/接口/验收要点\n"
        "- 剥离: 寒暄/重复/与实现无关的讨论\n"
        "- 保持具体数值与技术术语, 不泛化、不新增推断\n"
        "- 输出纯文本可含短列表, 不加标题不加解释, 500 字以内"
        + (f"\n用户特别关注: {hint[:200]}" if hint else ""))
    from .adaptation import summarize_task
    out = await asyncio.to_thread(
        summarize_task, task_id="msg_digest", system=sys_prompt,
        material=material, max_tokens=800,
        parse=lambda r: str(r.get("content") or "").strip() or None,
        fallback=lambda: material[:2000])
    digest = str(out.get("output") or "")
    return ok({"digest": digest, "chars": len(digest),
               "summarized": not out.get("degraded")})


@router.post("/sessions/{conv_id}/clone")
async def clone_session(conv_id: str, request: Request):
    """克隆会话绑定其他执行器(种子: 摘要(LLM best-effort) + 尾部 N 条消息 + 作业前情简报)。

    规约版本链经 reqId 绑定天然共享, 不做复制。meta.seedFrom 留审计标记。
    """
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    data = await request.json()
    executor_id = str(data.get("executorId") or "").strip()
    if not executor_id:
        return err(400, "executorId 必填")
    from .agent_executors import load_executors
    if not any(e.get("id") == executor_id for e in load_executors()):
        return err(400, f"执行器实例不存在: {executor_id}")
    tail_n = min(max(int(data.get("tailMessages") or 10), 0), 40)

    # 库路由: 源会话在项目库时, 克隆全程显式路由到同库(调用方无需带 project)
    from . import ctx as _ctx
    pid = (conv.get("projectId") or "").strip()
    tok = _ctx.set_project(pid) if pid else None
    try:
        return ok(_clone_into_project(conv, executor_id, tail_n, conv_id,
                                      model=str(data.get("model") or "").strip()))
    finally:
        if tok is not None:
            _ctx.reset_project(tok)


def _clone_seed_summary(conv_id: str) -> str:
    """克隆摘要种子(LLM best-effort): 源会话已有摘要直接用, 否则尝试生成; 失败返回空。"""
    try:
        conv = store.ConversationsStore.get(conv_id) or {}
        summary = (conv.get("summary") or "").strip()
        if summary:
            return summary
        from .context_registry import summarize_conversation
        summary = ((summarize_conversation(conv_id, force=True) or {})
                   .get("summary") or "").strip()
        return summary
    except Exception:  # noqa: BLE001
        return ""


def _clone_into_project(conv: dict, executor_id: str, tail_n: int, conv_id: str,
                        model: str = "") -> dict:
    new_conv = store.ConversationsStore.create({
        "kind": conv.get("kind") or "generic",
        "projectId": conv.get("projectId") or "",
        "reqId": conv.get("reqId") or "",
        "title": (conv.get("title") or "会话") + "(克隆)",
        "status": "active",
        "executorId": executor_id,
        "executorModel": model or (conv.get("executorModel") or ""),
        "parentConvId": "",
        "roles": ["architect"],
        "meta": {"seedFrom": {"convId": conv_id, "at": _ts(),
                              "prevExecutorId": conv.get("executorId") or ""}},
    })
    # 摘要种子(best-effort, 失败静默跳过)
    summary = _clone_seed_summary(conv_id)
    if summary:
        store.ConversationsStore.append_message({
            "id": store.next_id("m"), "conversationId": new_conv["id"],
            "role": "assistant", "time": _ts(),
            "content": f"📋 **会话摘要**(克隆自 {conv_id})\n\n{summary[:2000]}",
            "meta": {"kind": "seed"},
        })
    msgs = store.ConversationsStore.messages(conv_id, limit=tail_n * 2)[-tail_n:] \
        if tail_n else []
    now = _ts()
    for m in msgs:
        if not (m.get("content") or "").strip():
            continue
        store.ConversationsStore.append_message({
            "id": store.next_id("m"), "conversationId": new_conv["id"],
            "role": m.get("role") or "user", "time": now,
            "content": m.get("content") or "",
            "meta": {"kind": "seed", "seedFrom": m.get("id") or ""},
        })
    # 作业前情简报(源会话有作业史时)
    try:
        from .exec_bridge import _prior_job_brief
        brief = (_prior_job_brief(conv) or "").strip()
        if brief:
            store.ConversationsStore.append_message({
                "id": store.next_id("m"), "conversationId": new_conv["id"],
                "role": "assistant", "time": _ts(),
                "content": f"📎 **前情简报**(克隆自 {conv_id})\n\n{brief}",
                "meta": {"kind": "seed"},
            })
    except Exception:  # noqa: BLE001
        pass
    return _conv_api(store.ConversationsStore.get(new_conv["id"]) or new_conv)


@router.get("/sessions/{conv_id}/coding-sessions")
async def list_coding_sessions(conv_id: str):
    """主会话的 coding 子会话池(按更新时间倒序; 含活跃标记与作业状态)。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    subs = store.ConversationsStore.by_parent(conv_id)
    active = (_meta_of(conv).get("activeCodingSession") or "")
    # P6: 旧 jobs 账本写路径已清退——作业状态不再从 meta.jobs 推导(键保留, 值空)。
    out = []
    for s in subs:
        out.append({"id": s["id"], "title": s.get("title") or "coding 子会话",
                    "executorId": s.get("executorId") or "",
                    "sessionRef": (s.get("sessionRef") or "")[:120],
                    "hasSessionRef": bool(s.get("sessionRef")),
                    "active": s["id"] == active,
                    "runningRole": {"role": "architect", "executorId": "", "status": ""},
                    "jobId": "",
                    "jobStatus": "",
                    "status": s.get("status") or "active",
                    "msgCount": s.get("msgCount") or 0,
                    "updatedAt": s.get("updatedAt")})
    return ok(out)


@router.post("/sessions/{conv_id}/coding-sessions")
async def create_coding_session(conv_id: str, request: Request):
    """新建 coding 子会话(清空 coding 自持上下文的新执行环境)。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    data = await request.json() if request else {}
    # 归档会话只读
    if (conv.get("status") or "active") == "archived":
        return err(400, "归档会话只读，不可新建子会话")
    sub = store.ConversationsStore.create({
        "kind": "coding", "projectId": conv.get("projectId") or "",
        "reqId": conv.get("reqId") or "",
        "title": str(data.get("title") or "").strip() or "coding 子会话",
        "executorId": conv.get("executorId") or "",
        "parentConvId": conv_id,
        "roles": ["architect"],
        "meta": {"createdFrom": conv_id, "createdAtTs": _ts()},
    })
    _set_active_coding_session(conv_id, sub["id"])
    return ok(_conv_api(store.ConversationsStore.get(sub["id"]) or sub))


@router.post("/sessions/{conv_id}/coding-sessions/{sub_id}/activate")
async def activate_coding_session(conv_id: str, sub_id: str):
    """切换活跃 coding 子会话(后续 /执行 作业与投喂落此子会话)。"""
    conv = store.ConversationsStore.get(conv_id)
    sub = store.ConversationsStore.get(sub_id)
    if not conv or not sub:
        return err(404, "会话或子会话不存在")
    if (sub.get("parentConvId") or "") != conv_id:
        return err(400, "该会话不属于此主会话的子会话池")
    _set_active_coding_session(conv_id, sub_id)
    return ok({"active": sub_id})


@router.post("/sessions/{conv_id}/sub-seen")
async def mark_sub_seen(conv_id: str):
    """子会话未读清零(用户切到 coding 视图查看子会话信息流时调用)。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    meta = _meta_of(conv)
    if int(meta.get("subUnread") or 0):
        meta["subUnread"] = 0
        store.ConversationsStore.update(conv_id, {"meta": meta})
    return ok({"subUnread": 0})


# M2 拆分: coding 子会话编排迁 agent/sessions/coding.py(行为等价)
from ..agent.sessions.coding import (_meta_of, _set_active_coding_session,
                                     _summarize_for_coding)


@router.post("/sessions/{conv_id}/feed")
async def feed_to_coding(conv_id: str, request: Request):
    """投喂门: 主会话消息 → 规则过滤 → 落活跃 coding 子会话(审计 feedFrom) → 投递活跃作业。

    body: {messageId} 定向转发历史消息 | {text} 直发文本。
    过滤规则(确定性): 剥离 hint 本地提示/工具轨迹标记, 只留正文。
    """
    from . import exec_bridge
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    body = await request.json()
    text, src_msg_id = "", ""
    if body.get("messageId"):
        m = next((x for x in store.ConversationsStore.messages(conv_id, limit=200)
                  if x.get("id") == body["messageId"]), None)
        if not m:
            return err(404, "消息不存在")
        if (m.get("meta") or {}).get("kind") == "hint":
            return err(400, "本地提示消息不可转发")
        text = (m.get("content") or "").strip()
        src_msg_id = m.get("id") or ""
    else:
        text = str(body.get("text") or "").strip()
    if not text:
        return err(400, "转发内容为空")

    summarized = False
    if body.get("summarize") and text:
        text, summarized = await _summarize_for_coding(text)

    meta = _meta_of(conv)
    active_sub = meta.get("activeCodingSession") or ""
    delivered, queued, feed_note = False, False, ""
    # P3: 投喂目标 = 活跃 v2 任务(running/waiting_input → task_input 转达/排队)
    task = exec_bridge.active_task_of(conv_id)
    if task and (task.get("status") or "") in ("running", ST.TASK_WAITING_INPUT):
        # 投喂路径自带子会话审计落流 → echo=False 防主流双写(R4 回声)
        res = await asyncio.to_thread(exec_bridge.task_input, task["id"], text,
                                      echo=False)
        if res.get("ok"):
            delivered, queued = True, bool(res.get("queued"))
        else:
            e = str(res.get("error") or "")
            if e not in ("task-not-active", "runner 不可达"):
                return err(400, f"投递失败: {e}")

    # 落子会话消息流(审计: 哪些主会话信息进入了 coding 上下文)
    if active_sub:
        store.ConversationsStore.append_message({
            "id": store.next_id("m"), "conversationId": active_sub,
            "role": "user", "time": _ts(), "content": text[:12000],
            "projectId": (conv.get("projectId") or ""),
            "meta": {"kind": "feed", "feedFrom": {"convId": conv_id,
                                                  "messageId": src_msg_id,
                                                  "at": _ts(),
                                                  "summarized": summarized,
                                                  "delivered": delivered, "queued": queued}},
        })
        feed_note = f"；已记录到子会话 {active_sub}"
    else:
        feed_note = "；(无活跃子会话——仅投递作业)"
    summary = ("📥 已排队转达(回合结束自动续跑)" if queued
               else "➡️ 已转达作业" if delivered
               else "已记录(当前无活跃作业——下次 /执行 后生效于新上下文)")
    if summarized:
        summary = "🧠 (摘要) " + summary
    return ok({"delivered": delivered, "queued": queued, "summarized": summarized,
               "activeSub": active_sub, "summary": summary + feed_note})


@router.post("/sessions/{conv_id}/probe")
async def probe_session(conv_id: str, request: Request):
    """会话内发起方案草图(probe): worktree 快照 + coding agent + 伪 diff，产物落单元。"""
    from . import context_registry
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    body = await request.json()
    instruction = (body.get("instruction") or "").strip()
    if not instruction:
        return err(400, "instruction 为空")
    from .project import _resolve_project
    try:
        proj = _resolve_project(body.get("root") or None, conv.get("projectId") or None)
    except Exception:
        proj = None
    root = body.get("root") or ((proj or {}).get("rootPath") or "")
    if not root:
        return err(400, "无法解析项目根(会话未绑定项目)")
    result = context_registry.run_probe(
        conv_id, instruction, root,
        executor_id=(body.get("executorId") or "").strip(),
        files=[str(f) for f in (body.get("files") or []) if str(f).strip()],
        base_commit=(body.get("baseCommit") or "").strip(),
        timeout_s=int(body.get("timeoutS") or 600))
    if result.get("error"):
        return err(502, result["error"])
    return ok(result)


@router.post("/sessions/{conv_id}/assemble")
async def assemble_session(conv_id: str):
    """前置上下文构造: 收集→裁剪→装配 dossier(裁决3)，落 execution_brief 单元。"""
    from . import context_registry
    reqs = []
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    if conv.get("reqId"):
        r = store.RequirementsStore.get(conv["reqId"])
        if r:
            reqs = [r]
    dossier = context_registry.assemble_dossier(conv_id, reqs=reqs)
    if dossier is None:
        return err(404, "会话不存在")
    return ok({"conversationId": conv_id, "length": len(dossier), "dossier": dossier})


# ── 指令引导(按需 agent 建议) ──
# 「指令引导」按钮: 基于会话当前状态(RQ 版本链/作业账本/最近消息)由 LLM 生成
# 下一步操作建议。旁路 REST——不落库、不进对话上下文; LLM 不可达 →
# fallback=True, 前端回退静态触发词提示。

# M2 拆分: 备案文档域迁 session_docs.py(独立路由, URL 不变)
from .session_docs import _doc_outline  # noqa: F401 — 测试引用接缝

# M2 拆分: guide 文案与 state 构建器迁 session_guide.py(行为等价)
from .session_guide import GUIDE_SYSTEM as _GUIDE_SYSTEM
from .session_guide import guide_jobs_state as _guide_jobs_state
from .session_guide import guide_req_state as _guide_req_state


@router.post("/sessions/{conv_id}/stop-exec")
async def stop_exec_session(conv_id: str):
    """UI 停止按钮(REST, 裁决#5): 停止会话全部活跃任务(v2)+存量作业(兼容)。

    P3: v2 arch_tasks 为主——逐个 task_stop(runner finish 保留 worktree/分支);
    meta.jobs 存量行(历史会话)仍经 exec_bridge.stop 兜底终态化。
    """
    from . import exec_bridge
    if not store.ConversationsStore.get(conv_id):
        return err(404, "会话不存在")
    stopped = []
    from .store import TasksStore
    for t in TasksStore.of_conv(conv_id):
        if (t.get("status") or "") in ("running", ST.TASK_WAITING_INPUT, ST.TASK_PENDING_CONFIRM):
            res = await asyncio.to_thread(exec_bridge.task_stop, t["id"], "user")
            if res.get("ok"):
                stopped.append(t["id"])
    legacy_msg = await asyncio.to_thread(exec_bridge.stop, conv_id, "user")
    if stopped:
        message = f"🛑 已停止 {len(stopped)} 个任务。分支与改动已保留，可重新发起任务。"
    else:
        message = str(legacy_msg)
    return ok({"message": message, "stoppedTasks": stopped})


@router.post("/sessions/{conv_id}/recover")
async def recover_session_route(conv_id: str):
    """中断恢复(interrupted 显式出口): 核对执行器实际态收尾任务 + 重算相位。

    幂等; repump 清单在事件循环内重挂泵(同 GET messages 先例)。
    返回 {recovered: 收尾数, repump: 重挂数, flowState: 相位}。"""
    if not store.ConversationsStore.get(conv_id):
        return err(404, "会话不存在")
    from ..agent.governance import flow as _flow
    rec = await asyncio.to_thread(_flow.recover_session, conv_id)
    for tid, jid, rid, ag in (rec or {}).get("repump", []):
        try:
            from . import exec_bridge as _eb
            _eb._start_task_pump(conv_id, tid, jid, rid, ag)
        except Exception:  # noqa: BLE001
            pass
    return ok(rec)


@router.post("/sessions/{conv_id}/spec-apply")
async def session_spec_apply(conv_id: str, request: Request):
    """消息流「写入需求」按钮: 规约 JSON 载荷确定性落库(零 LLM)。

    三级降级内建(归一化自愈 → 字段降级 → LLM 格式修复); 载荷内 reqId 一律
    丢弃, 落库目标取会话绑定需求(未完结 amend / 无绑定 propose 新建)。
    body: {payload: {...}}
    """
    body = await request.json()
    payload = body.get("payload")
    if not isinstance(payload, dict) or not payload:
        return err(400, "缺少 payload")
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    from .req_agent import apply_spec_payload
    res = await asyncio.to_thread(
        apply_spec_payload, payload,
        req_id=str(conv.get("reqId") or ""),
        project=str(conv.get("projectId") or ""),
        root="")
    # 落库成功 → 清除会话草稿卡暂存(草稿已兑现为真实需求)
    if res.get("ok"):
        try:
            cm = conv.get("meta") if isinstance(conv.get("meta"), dict) else {}
            if isinstance(cm, dict) and cm.get("specDraft"):
                cm = dict(cm)
                cm.pop("specDraft", None)
                store.ConversationsStore.update(conv_id, {"meta": cm})
        except Exception:  # noqa: BLE001
            pass
    # 草稿兑现 → 占用事实变化, 重算流程相位(clarifying 出口; fail-soft)
    if res.get("ok"):
        try:
            from ..agent.governance import flow as _flow
            await asyncio.to_thread(_flow.recompute, conv_id, trigger="spec-apply")
        except Exception:  # noqa: BLE001
            pass
    return ok(res)


@router.post("/sessions/{conv_id}/guide")
async def session_guide(conv_id: str):
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")

    msgs = store.ConversationsStore.messages(conv_id, limit=1000)[-10:]
    # 流程相位事实注入(governance/flow.py): guide 从"LLM 推断阶段"升级为
    # "确定性相位 + hint 事实 → LLM 措辞增强"(软状态机收编)
    try:
        from ..agent.governance import flow as _flow
        _phase = (await asyncio.to_thread(
            lambda: (_flow.recompute(conv_id, trigger="guide") or {})
            .get("flowState") or (conv.get("flowState") or ""))) or (conv.get("flowState") or "")
        _req_row = store.RequirementsStore.get(conv.get("reqId") or "") \
            if (conv.get("reqId") or "") else None
        _hints = _flow.flow_hints(conv, store.TasksStore.of_conv(conv_id) or [],
                                  _req_row)
    except Exception:  # noqa: BLE001
        _phase, _hints = (conv.get("flowState") or ""), []
    state = {
        "title": conv.get("title") or "",
        "kind": conv.get("kind") or "",
        "status": conv.get("status") or "active",
        "workState": conv.get("workState") or "architect",
        "flowState": _phase,
        "nextActionHints": _hints,
        "requirement": _guide_req_state(conv.get("reqId") or ""),
        "execJobs": _guide_jobs_state(conv_id),
        "recentMessages": [
            {"role": m.get("role"), "content": (m.get("content") or "")[:240]}
            for m in msgs if (m.get("content") or "").strip()
        ],
    }

    def _fallback():
        return ok({"text": "", "fallback": True})

    from .adaptation import summarize_task
    out = summarize_task(
        task_id="session_guide", system=_GUIDE_SYSTEM,
        material=json.dumps(state, ensure_ascii=False), max_tokens=500)
    content = out["output"]
    if not content:
        return _fallback()
    return ok({"text": content, "fallback": False})


# ── v2 统一会话: coding subagent 任务 REST(轻门禁/投递/停止) ──

@router.post("/tasks/{task_id}/merge")
async def task_merge(task_id: str, request: Request):
    """确认合并(本地 PR 语义, 环节十五): 门禁通过后执行合并, 任务记 merged 终态。

    body: {mode?: "ff"(默认, 仅快进) | "no-ff"(强制合并提交, 冲突中止回显)}。"""
    from . import exec_bridge
    try:
        body = await request.json()
    except Exception:
        body = {}
    mode = "no-ff" if str((body or {}).get("mode") or "") == "no-ff" else "ff"
    res = await asyncio.to_thread(exec_bridge.merge_branch, task_id, mode)
    if not res.get("ok"):
        return err(int(res.get("code") or 400), res.get("error") or "merge-failed")
    # 流程相位重算: merged = 回执已消化(reviewing 出口; force 解除粘滞)
    try:
        _t = res.get("task") or {}
        _cid = _t.get("conversationId") or ""
        if _cid:
            from ..agent.governance import flow as _flow
            await asyncio.to_thread(lambda: _flow.recompute(_cid, trigger="task-merge", force=True))
    except Exception:  # noqa: BLE001
        pass
    return ok(res)


@router.get("/tasks/{task_id}/merge-precheck")
async def task_merge_precheck(task_id: str):
    """合并入口检查(环节十五): 主目录推进/任务分支内容/是否可直并。"""
    from . import exec_bridge
    res = await asyncio.to_thread(exec_bridge.merge_precheck, task_id)
    if not res.get("ok"):
        return err(int(res.get("code") or 400), res.get("error") or "precheck-failed")
    return ok(res)


@router.post("/tasks/{task_id}/cleanup")
async def task_cleanup(task_id: str, request: Request):
    """T5 终态任务对账清理: runner finish(释放执行器资源/可选删 worktree)。

    body: {keepWorktree?: bool=true}; 幂等——runner 作业不存在也视为清毕。"""
    from . import exec_bridge
    keep = True
    try:
        body = await request.json()
        keep = bool((body or {}).get("keepWorktree", True))
    except Exception:  # noqa: BLE001
        pass
    task = await asyncio.to_thread(store.TasksStore.get, task_id)
    if not task:
        return err(404, "task-not-found")
    if (task.get("status") or "") not in ("done", "failed", "cancelled"):
        return err(400, "仅终态任务可清理(先停止)")
    job_id = task.get("runnerJobId") or ""
    if job_id:
        await asyncio.to_thread(
            exec_bridge._runner, f"/api/implement/{job_id}/finish",
            {"keepWorktree": keep}, timeout=30.0)
    return ok({"taskId": task_id, "cleaned": True, "keptWorktree": keep})


@router.post("/tasks/{task_id}/ignore")
async def task_ignore(task_id: str):
    """主动忽略(2026-09-20 裁决: 默认保存/对话更新/主动忽略): 仅 saved 态。"""
    res = await asyncio.to_thread(exec_bridge.ignore_task, task_id)
    if not res.get("ok"):
        return err(res.get("code") or 400, str(res.get("error") or "忽略失败"))
    return ok({"task": res.get("task")})


@router.post("/tasks/{task_id}/confirm")
async def task_confirm(task_id: str, request: Request):
    """确认任务卡 → 拉起 runner(轻门禁唯一入口)。

    body 可选 executorType: 覆盖任务执行器(确认时换引擎, 优先级低于专用端点)。"""
    from . import exec_bridge
    etype = ""
    try:
        body = await request.json()
        etype = str((body or {}).get("executorType") or "")
    except Exception:  # noqa: BLE001
        pass
    if etype:
        await asyncio.to_thread(exec_bridge.task_set_executor, task_id, etype)
    res = await asyncio.to_thread(exec_bridge.confirm_task, task_id)
    if not res.get("ok"):
        return err(400, str(res.get("error") or "confirm-failed"))
    return ok({"task": res.get("task")})


@router.post("/tasks/{task_id}/dismiss")
async def task_dismiss(task_id: str):
    """回执已阅(dismiss, reviewing 消化出口): 仅 done 态; 不改终态, 留痕。

    与 ignore 语义区分: ignore=saved 卡不执行; dismiss=done 回执已阅
    (不合并/不建下张卡的用户显式消化)。"""
    from ..agent.execution.dispatch import dismiss_task
    res = await asyncio.to_thread(dismiss_task, task_id)
    if not res.get("ok"):
        return err(int(res.get("code") or 400), str(res.get("error") or "dismiss-failed"))
    return ok({"task": res.get("task")})


@router.post("/tasks/{task_id}/executor")
async def task_set_executor(task_id: str, request: Request):
    """设定任务执行器(待确认态切换; cline/opencode/codex)。"""
    from . import exec_bridge
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return err(400, "invalid-json")
    etype = str((body or {}).get("executorType") or "").strip()
    from ..agent.execution.capabilities import is_valid_type, executor_types
    if not is_valid_type(etype):        # B1 单源: 双命名空间归一判断
        return err(400, "executorType 取值: " + "/".join(executor_types()))
    task = await asyncio.to_thread(exec_bridge.task_set_executor, task_id, etype)
    if not task:
        return err(404, "任务不存在或已不可切换")
    return ok({"task": task})


@router.post("/tasks/{task_id}/verify-config")
async def task_verify_config(task_id: str, request: Request):
    """设定任务验收门禁配置(待确认态; V1 发现链 P0 显式来源)。

    body: {verifyConfig: {maxAttempts?, autoRepair?, timeoutMul?, build?, test?}}"""
    from . import exec_bridge
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return err(400, "invalid-json")
    cfg = (body or {}).get("verifyConfig")
    if not isinstance(cfg, dict):
        return err(400, "verifyConfig 必须为对象")
    task = await asyncio.to_thread(exec_bridge.task_set_verify_config,
                                   task_id, cfg)
    if task is None:
        return err(400, "任务不存在或已不可修改(仅待确认态可改)")
    return ok({"task": task})


@router.post("/tasks/{task_id}/cancel")
async def task_cancel(task_id: str, request: Request):
    """取消(待确认)/停止(执行中)任务; 保留 worktree/分支。"""
    from . import exec_bridge
    reason = ""
    try:
        body = await request.json()
        reason = str((body or {}).get("reason") or "")
    except Exception:  # noqa: BLE001
        pass
    res = await asyncio.to_thread(exec_bridge.task_stop, task_id, reason)
    if not res.get("ok"):
        return err(400, str(res.get("error") or "stop-failed"))
    return ok({"task": res.get("task")})


@router.post("/tasks/{task_id}/input")
async def task_input(task_id: str, request: Request):
    """向任务转达用户回复(waiting_input 立即; running 排队续跑)。"""
    from . import exec_bridge
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return err(400, "invalid-json")
    text = str((body or {}).get("text") or "").strip()
    if not text:
        return err(400, "text 为空")
    res = await asyncio.to_thread(exec_bridge.task_input, task_id, text)
    if not res.get("ok"):
        return err(400, str(res.get("error") or "input-failed"))
    # R4 回声: requestId 全链路关联(主流已落 task_input_echo 持久回执)
    return ok({"queued": bool(res.get("queued")),
               "requestId": res.get("requestId") or ""})


@router.get("/tasks")
async def tasks_of(conv_id: str = fastapi.Query("", alias="convId")):
    """会话任务清单(倒序)。?convId= 会话 id。"""
    if not conv_id:
        return err(400, "convId 必填")
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    return ok({"tasks": _tasks_of_conv(conv)})


@router.get("/units")
async def units_of(conv_id: str = fastapi.Query("", alias="convId"),
                   type: str = fastapi.Query("", alias="type"),
                   q: str = fastapi.Query("", alias="q"),
                   scope: str = fastapi.Query("", alias="scope"),
                   limit: int = fastapi.Query(100, alias="limit")):
    """会话知识单元清单(存储归一: 回执/分析/产物/错误等, 检索面读侧)。

    ?convId= 会话 id; 缺省时跨会话列示:
      - scope=all: 跨全库(主库+各项目库)汇总 —— 会话中心左栏知识资产统一视图,
        条目携带 conversationId 供前端标注/联动来源会话;
      - 其余: 按请求项目上下文路由读。
    """
    cap = max(1, min(limit, 200))
    if conv_id:
        conv = store.ConversationsStore.get(conv_id)
        if not conv:
            return err(404, "会话不存在")
        if q.strip():
            rows = store.ContextUnitsStore.search(q.strip(), type_=type or None,
                                                  conversation_id=conv_id,
                                                  limit=cap)
        else:
            rows = store.ContextUnitsStore.all(conversation_id=conv_id, type_=type or None,
                                               limit=cap)
    elif scope == "all":
        rows = store.ContextUnitsStore.all_across(type_=type or None,
                                                  q=q.strip() or None, limit=cap)
    else:
        if q.strip():
            rows = store.ContextUnitsStore.search(q.strip(), type_=type or None, limit=cap)
        else:
            rows = store.ContextUnitsStore.all(type_=type or None, limit=cap)
        # scan 归并路径未整体重排 → 按 createdAt 重排后截断
        rows = sorted(rows, key=lambda r: (r.get("createdAt") is None, r.get("createdAt") or 0),
                      reverse=True)[:cap]
    return ok({"units": rows})


@router.delete("/units/{unit_id}")
async def unit_remove(unit_id: str):
    """删除会话知识单元(误沉淀/过期清理)。"""
    removed = await asyncio.to_thread(store.ContextUnitsStore.delete, unit_id)
    if not removed:
        return err(404, "单元不存在")
    return ok({"deleted": True, "id": unit_id})
