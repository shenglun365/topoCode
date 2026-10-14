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

from ..common import _ts, ok, err
from .. import store
from ..store import states as ST
from ..agent.collab import sse as ws_events

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
    # 子会话计数(主行展开箭头依据): 过滤前从 coding 行按 parent 聚合, 零额外查询
    _sub_counts: dict = {}
    for c in rows:
        if (c.get("kind") or "") == "coding":
            pid = c.get("parentConvId") or ""
            if pid:
                _sub_counts[pid] = _sub_counts.get(pid, 0) + 1
    if kind != "coding":
        rows = [c for c in rows if (c.get("kind") or "") != "coding"]
    # 生效执行器(2610 统一模型): executorId 单源; legacy quick 无绑定 → 默认
    # coding 执行器(默认注册表解析一次, 防 400 行×注册表读)
    _default_eid = ""
    try:
        from .agent_executors import default_executor
        _default_eid = str((default_executor() or {}).get("id") or "")
    except Exception:  # noqa: BLE001
        pass

    def _eff_executor(c: dict) -> str:
        eid = str(c.get("executorId") or "").strip()
        if eid == "architect":
            return ""
        if eid:
            return eid
        return _default_eid if str(c.get("analysisMode") or "") == "quick" else ""

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
            "effectiveExecutorId": _eff_executor(c),
            "executorModel": c.get("executorModel") or "",
            "parentConvId": c.get("parentConvId") or "",
            "runningRole": _running_role_of(c),
            "tags": _tags_of(c),
            # meta 透传(通用契约): 各特性落 conv.meta 的状态(如 ctxUsage)自动可达前端
            "meta": c.get("meta") or {},
            "summary": c.get("summary") or "",
            "msgCount": c.get("msgCount") or 0,
            "preview": (c.get("preview") or "").strip()[:160],
            "firstUserTime": c.get("firstUserTime") or 0,
            "createdAt": c.get("createdAt"),
            "updatedAt": c.get("updatedAt"),
            "projectId": c.get("projectId") or "",
            "subCount": _sub_counts.get(c["id"], 0),
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


@router.get("/sessions/{conv_id}/choices-draft")
async def get_choices_draft(conv_id: str):
    """问询卡填写草稿读取(呈现层恢复源; 无草稿 → 空表)。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    try:
        meta = json.loads(conv.get("meta") or "{}") \
            if isinstance(conv.get("meta"), str) else (conv.get("meta") or {})
    except (TypeError, ValueError):
        meta = {}
    drafts = meta.get("choicesDraft") if isinstance(meta, dict) else None
    return ok({"conversationId": conv_id,
               "drafts": drafts if isinstance(drafts, dict) else {}})


@router.put("/sessions/{conv_id}/choices-draft")
async def save_choices_draft(conv_id: str, request: Request):
    """问询卡填写草稿随会话落库(cv-254: 用户输入=工作产物, 不得因呈现层
    销毁而丢失——specDraft 同类 conv.meta 草稿, 非事实写点)。

    body: {cardId, draft}——draft=null 清除该卡草稿(回复提交成功/卡消费);
    draft={selections, customs, skipped, note}(ChoicesCard 填写快照)。
    cardId 级幂等 upsert, 多卡互不覆盖。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    data = await request.json()
    card_id = str(data.get("cardId") or "").strip()
    if not card_id:
        return err(400, "缺少 cardId")
    try:
        meta = json.loads(conv.get("meta") or "{}") \
            if isinstance(conv.get("meta"), str) else (conv.get("meta") or {})
    except (TypeError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    drafts = meta.get("choicesDraft")
    drafts = dict(drafts) if isinstance(drafts, dict) else {}
    draft = data.get("draft")
    if draft is None:
        drafts.pop(card_id, None)
    else:
        if not isinstance(draft, dict):
            return err(400, "draft 须为对象或 null")
        drafts[card_id] = draft
    if drafts:
        meta["choicesDraft"] = drafts
    else:
        meta.pop("choicesDraft", None)
    store.ConversationsStore.update(conv_id, {"meta": meta})
    return ok({"conversationId": conv_id, "cardId": card_id,
               "saved": draft is not None})


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
    # 执行器变更走专用换绑端点(在跑守卫/sessionRef 清理/模型重置)——PATCH 直改拒绝
    if "executorId" in data and str(data.get("executorId") or "").strip() != (conv.get("executorId") or ""):
        return err(409, "执行器变更请用换绑端点 POST /sessions/{id}/executor"
                        "(在跑拒绝, 对话连续; architect 可切回分析管线)。")
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


@router.get("/sessions/{conv_id}/delete-preview")
async def delete_preview(conv_id: str):
    """删除预览(主会话删除前置检查): 级联清单 + 可删性裁决。

    语义单源在 agent/sessions/delete_cascade.py(用户裁决 2610):
    需求完成情况仅展示不校验; 执行器会话执行中 → deletable=false + blockers;
    共享需求(克隆链)保留。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    return ok(_delete_preview(conv))


@router.delete("/sessions/{conv_id}")
async def delete_session(conv_id: str):
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    # 执行器会话必须执行完成(用户裁决): 本会话或任一子孙会话执行中 → 拒绝
    # 整树删除(含关联需求与全部子会话); 先停止/等待完成后再删。
    blockers = _delete_blockers(conv_id)
    if blockers:
        names = "; ".join(f"「{b['title']}」({b['status']})" for b in blockers[:5])
        return err(409, f"执行中的执行器会话未完成, 不能删除: {names}。请先停止或等待执行完成。")
    parent_id = (conv.get("parentConvId") or "").strip()
    cascade = _delete_session_cascade(conv_id)
    # 单独删除 coding 子会话后: 主会话活跃子会话指针悬空 → 清空回退默认
    if parent_id:
        try:
            parent = store.ConversationsStore.get(parent_id)
            if parent and str(_meta_of(parent).get("activeCodingSession") or "") == conv_id:
                _set_active_coding_session(parent_id, "")
        except Exception:  # noqa: BLE001
            pass
    return ok({"deleted": True, "id": conv_id, "cascadeConversations": cascade})


@router.get("/sessions/{conv_id}/messages")
async def session_messages(conv_id: str):
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    # T3 恢复扩面: 打开会话(只读查看)即惰性核对 running/waiting_input 任务——
    # 不再要求用户必须发消息才自愈(cv-161: 服务重启后泵丢失, 任务假 running)
    try:
        from ..agent.execution import exec_bridge as _eb
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
    # 深链会话页(2026-10): 头信息一次取齐——子会话 meta + 主会话标题
    parent_id = conv.get("parentConvId") or ""
    parent_row = store.ConversationsStore.get(parent_id) if parent_id else None
    return ok({
        "id": conv_id,
        "conv": {
            "title": conv.get("title") or "",
            "kind": conv.get("kind") or "generic",
            "executorId": conv.get("executorId") or "",
            "parentConvId": parent_id,
            "projectId": conv.get("projectId") or "",
        },
        "parent": ({"id": parent_id, "title": (parent_row or {}).get("title") or ""}
                   if parent_id else None),
        "messages": msgs,
    })


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
    from ..agent.memory import units as context_registry
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
    """legacy(T4 清退→2610 统一模型彻底清偿): 会话角色字段已僵尸化——恒回
    默认值保持 API 兼容。会话身份单源=conv.executorId(architect/coding 执行器)。"""
    return ["architect"]


def _running_role_of(conv: dict) -> dict:
    """running 归属推导(纯提示): v2 活跃任务(running|waiting_input) → coding+执行器;
    直通作业(执行器持球会话, 2610 W5) → coding+直通执行器。

    P6 单读: 仅 arch_tasks + proxy 内存句柄驱动(旧 meta.jobs 账本写路径已清退)。"""
    try:
        from ..agent.execution import exec_bridge as _eb
        t = _eb.active_task_of(conv["id"]) if conv.get("id") else None
        if t and (t.get("status") or "") in ("running", ST.TASK_WAITING_INPUT):
            out = {"role": "coding",
                   "executorId": t.get("executorType") or "opencode",
                   "status": t.get("status") or "",
                   "taskId": t.get("id") or ""}
            if isinstance(t.get("progress"), dict):
                out["progress"] = t["progress"]
            return out
        from ..agent.execution.proxy import proxy_state as _ps
        ps = _ps(conv["id"]) if conv.get("id") else {}
        if ps.get("active"):
            # 2610 P1: state=idle(回合收束等输入) → waiting_input 口径,
            # FE 区分「执行中」与「等待输入」
            return {"role": "coding",
                    "executorId": ps.get("executorType") or "",
                    "status": ("waiting_input"
                               if str(ps.get("state") or "") == "idle" else "running"),
                    "taskId": "",
                    "jobId": ps.get("jobId") or ""}
        # 2610 F5b: 排队中(idle 让坑后其它会话占坑 / 启动排队) → queued 口径
        try:
            from ..agent.execution import executor_scheduler as _sched
            st = _sched.state_of_conv(conv["id"]) if conv.get("id") else {}
            if st.get("state") == "queued":
                return {"role": "coding",
                        "executorId": str(st.get("executorId") or ""),
                        "status": "queued", "taskId": "",
                        "queuedPosition": int(st.get("position") or 0)}
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass
    return {"role": "architect", "executorId": "", "status": ""}


def _tasks_of_conv(conv: dict) -> list:
    """v2 统一会话: 会话任务清单(arch_tasks, 倒序)。失败静默(旧库无表)。"""
    try:
        from ..store import TasksStore
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
    """执行器白名单模型名(config.models[].name)。

    内置 cline = 实例模型实时投影覆盖(与 GET /agent/executors 读侧、
    executor_hint_by_id 执行侧同源; cv-259: 落盘快照恒空 → 展示 18 个模型
    却校验"无可选模型"400——读写两侧口径分裂)。
    """
    models = list((entry.get("config") or {}).get("models") or [])
    if (entry.get("type") == "cline-sdk"
            and (entry.get("id") or "") == "cline"):
        try:
            from .agent_executors import _builtin_cline_models
            live = _builtin_cline_models()
            if live:
                models = live
        except Exception:  # noqa: BLE001
            pass
    return [str(m.get("name") or m.get("model") or "")
            for m in models
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
    """首次绑定 coding 执行器(architect 为缺省执行器, 无需绑定)。

    已绑定 coding 执行器 → 409 引导换绑端点(2610 统一模型: 可随时更换)。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    from ..agent.execution.exec_bridge import effective_executor_id
    cur = effective_executor_id(conv)
    if cur:
        return err(409, f"已绑定执行器 {cur}。换绑请用 POST /sessions/{conv_id}/executor"
                        "(在跑拒绝, 对话连续)。")
    data = await request.json()
    executor_id = str(data.get("executorId") or "").strip()
    if not executor_id:
        return err(400, "executorId 必填")
    if executor_id == "architect":
        return err(400, "architect 为缺省执行器(无需绑定); 换绑请用 /executor 端点")
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


# 分析挡位端点(POST /analysis-mode)已退役(2610 执行器统一模型):
# quick/strict 由 conv.executorId 吸收——换绑执行器见 POST /sessions/{id}/executor。
# analysisMode 列保留 legacy 读侧兼容(quick 无绑定 → 默认 coding 执行器)。


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
               if on else "融合模式(直接写入项目目录)"})


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
    from ..agent.reflection.repair import summarize_task
    out = await asyncio.to_thread(
        summarize_task, task_id="msg_digest", system=sys_prompt,
        material=material,
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
    from .. import ctx as _ctx
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
        from ..agent.memory.units import summarize_conversation
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
        from ..agent.execution.exec_bridge import _prior_job_brief
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
    # 2610 统一模型: execution=真实运行态(删除守卫/池禁用判定同源
    # delete_cascade.active_execution_of); runningRole 保留为兼容 stub。
    from ..agent.sessions.delete_cascade import active_execution_of
    out = []
    for s in subs:
        out.append({"id": s["id"], "title": s.get("title") or "coding 子会话",
                    "executorId": s.get("executorId") or "",
                    "sessionRef": (s.get("sessionRef") or "")[:120],
                    "hasSessionRef": bool(s.get("sessionRef")),
                    "active": s["id"] == active,
                    "runningRole": {"role": "architect", "executorId": "", "status": ""},
                    "execution": active_execution_of(s["id"]),
                    "jobId": "",
                    "jobStatus": "",
                    "status": s.get("status") or "active",
                    "msgCount": s.get("msgCount") or 0,
                    "updatedAt": s.get("updatedAt")})
    return ok(out)


@router.post("/sessions/{conv_id}/coding-sessions")
async def create_coding_session(conv_id: str, request: Request):
    """新建 coding 子会话。body: {title?, executorId?}——缺省继承主绑定
    (主会话可挂多执行器, 每执行器可建多个子会话)。"""
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
        "executorId": str(data.get("executorId") or "").strip()
                      or conv.get("executorId") or "",
        "parentConvId": conv_id,
        "roles": ["architect"],
        "meta": {"createdFrom": conv_id, "createdAtTs": _ts()},
    })
    _set_active_coding_session(conv_id, sub["id"])
    return ok(_conv_api(store.ConversationsStore.get(sub["id"]) or sub))


@router.post("/sessions/{conv_id}/executor")
async def switch_executor(conv_id: str, request: Request):
    """换绑会话执行器(主会话/子会话通用, 2610 执行器统一模型)。

    - 上下文真相源=消息流: 换绑只清执行器引用(sessionRef)+模型白名单
      重置, 对话连续(cline 类 sessionRef 可复活续上下文);
    - body: {executorId} 注册表任意执行器, 含 architect 内置条目
      (=切回分析管线, 显式落点粘滞);
    - 在跑守卫: 活跃任务/直通作业执行中 → 拒绝(先停止或等待完成)。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    body = await request.json() or {}
    eid = str(body.get("executorId") or "").strip()
    if not eid:
        return err(400, "executorId 必填")
    from .agent_executors import load_executors, ARCHITECT_EXECUTOR_ID
    if eid != ARCHITECT_EXECUTOR_ID and not any(
            e.get("id") == eid and e.get("enabled", True)
            for e in load_executors() or []):
        return err(400, f"执行器不存在或未启用: {eid}")
    from ..agent.sessions.delete_cascade import active_execution_of
    st = active_execution_of(conv_id)
    if st:
        return err(400, f"该会话执行中({st})——请先停止或等待完成再换绑执行器")
    target = eid  # architect 显式落点(粘滞, 见 effective_executor_id)
    store.ConversationsStore.update(conv_id, {"executorId": target,
                                              "sessionRef": "",
                                              "executorModel": ""})
    from ..agent.execution.exec_bridge import effective_executor_id
    note = ("已切回 architect 分析管线" if target == ARCHITECT_EXECUTOR_ID
            else f"执行器已切换为 {target}")
    if effective_executor_id(conv) == ("" if target == ARCHITECT_EXECUTOR_ID else target) \
            and (conv.get("executorId") or "").strip() == target:
        note = "执行器未变化"
    return ok({"conversationId": conv_id, "executorId": target,
               "sessionRef": "", "executorModel": "",
               "summary": note + "；下回合生效, 对话连续"})


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

# 2610 删除域迁 agent/sessions/delete_cascade.py(预览/执行守卫/级联; 行为等价)
# 下划线别名 = 既有测试接缝(test_exec_implement 直引 S._delete_session_cascade)
from ..agent.sessions.delete_cascade import (
    delete_blockers as _delete_blockers,
    delete_preview as _delete_preview,
    delete_session_cascade as _delete_session_cascade,
)


# 投喂域(2610 统一模型)迁 agent/sessions/feeds.py(交付核心/feed-up 解析);
# 路由层只做 HTTP 编排, 错误经 FeedError 转译
from ..agent.sessions.feeds import (
    FeedError as _FeedError, deliver_feed as _deliver_feed_core,
    feed_up_target as _feed_up_target, resolve_source_text as _resolve_src,
    summarize_if_asked as _summarize_if_asked)


@router.post("/sessions/{conv_id}/feed")
async def feed_to_coding(conv_id: str, request: Request):
    """投喂门: 主会话消息 → 规则过滤 → 落活跃 coding 子会话(审计 feedFrom) → 投递活跃作业。

    body: {messageId} 定向转发历史消息 | {text} 直发文本; {summarize?}。
    """
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    body = await request.json()
    try:
        text, src_msg_id = _resolve_src(conv_id, body)
        text, summarized = await _summarize_if_asked(body, text)
        data = await _deliver_feed_core(conv, text, src_conv_id=conv_id,
                                        src_msg_id=src_msg_id,
                                        summarized=summarized)
    except _FeedError as e:
        return err(400, str(e))
    return ok(data)


@router.post("/sessions/{sub_id}/feed-up")
async def feed_up_from_sub(sub_id: str, request: Request):
    """子会话产出上投(2610 统一模型): 子会话(如 architect 分析子会话)消息 →
    主会话活跃执行器子会话/作业——分析结论回 flow 编码执行。

    body: {messageId} 定向转发子会话消息 | {text} 直发文本; {summarize?}。"""
    body = await request.json()
    try:
        _sub, main_conv = _feed_up_target(sub_id)
        text, src_msg_id = _resolve_src(sub_id, body)
        text, summarized = await _summarize_if_asked(body, text)
        data = await _deliver_feed_core(main_conv, text, src_conv_id=sub_id,
                                        src_msg_id=src_msg_id,
                                        summarized=summarized)
    except _FeedError as e:
        return err(400, str(e))
    return ok(data)


@router.post("/sessions/{conv_id}/probe")
async def probe_session(conv_id: str, request: Request):
    """会话内发起方案草图(probe): worktree 快照 + coding agent + 伪 diff，产物落单元。"""
    from ..agent.memory import units as context_registry
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    body = await request.json()
    instruction = (body.get("instruction") or "").strip()
    if not instruction:
        return err(400, "instruction 为空")
    from .project import resolve_project
    try:
        proj = resolve_project(body.get("root") or None, conv.get("projectId") or None)
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
    from ..agent.memory import dossier as context_registry
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
    from ..agent.execution import exec_bridge
    if not store.ConversationsStore.get(conv_id):
        return err(404, "会话不存在")
    stopped = []
    from ..store import TasksStore
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
            from ..agent.execution import exec_bridge as _eb
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
    # 幂等(cv-248): 载荷指纹窗口内重复提交直接返回既有结果——防连点重复
    # 建需求(apply_spec_payload 的 propose/amend 均非幂等操作)。指纹=
    # title+requirementMd; 窗口 10min(超窗视为新一轮修订, 走 amend)。
    import hashlib as _h
    import time as _time
    fp = _h.sha1((str(payload.get("title") or "") + "\n"
                  + str(payload.get("requirementMd") or "")).encode("utf-8")
                 ).hexdigest()[:16]
    cm = conv.get("meta") if isinstance(conv.get("meta"), dict) else {}
    prev_fp = str((cm or {}).get("specApplyFp") or "")
    prev_ts = int((cm or {}).get("specApplyTs") or 0)
    prev_rid = str((cm or {}).get("specApplyRid") or "")
    if prev_fp and prev_fp == fp and prev_rid \
            and _time.time() * 1000 - prev_ts < 10 * 60 * 1000:
        return ok({"ok": True, "requirementId": prev_rid,
                   "idempotent": True,
                   "summary": f"需求 {prev_rid} 已写入（重复提交已幂等跳过）——"
                              "点需求卡「一键建卡执行」发起执行"})
    from ..agent.tools.req_agent import apply_spec_payload
    from .. import ctx as _ctx

    def _apply():
        # ctx 会话上下文(cv-248 根因): spec-apply 原先未设置 conv 上下文——
        # req.propose 内部 conv_id 为空 → ①specReady 卡不落流(无「一键建卡
        # 执行」按钮) ②conv.reqId 绑定回写跳过 → 重复点击重复新建
        token = _ctx.set_conv(conv_id)
        try:
            return apply_spec_payload(
                payload, req_id=str(conv.get("reqId") or ""),
                project=str(conv.get("projectId") or ""), root="")
        finally:
            _ctx.reset_conv(token)

    res = await asyncio.to_thread(_apply)
    # 落库成功 → 清除会话草稿卡暂存(草稿已兑现为真实需求) + 登记幂等指纹
    if res.get("ok"):
        try:
            cm = conv.get("meta") if isinstance(conv.get("meta"), dict) else {}
            cm = dict(cm or {})
            cm["specApplyFp"] = fp
            cm["specApplyTs"] = int(_time.time() * 1000)
            cm["specApplyRid"] = str(res.get("requirementId")
                                     or res.get("reqId") or prev_rid or "")
            store.ConversationsStore.update(conv_id, {"meta": cm})
            if cm.get("specDraft"):
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

    from ..agent.reflection.repair import summarize_task
    out = summarize_task(
        task_id="session_guide", system=_GUIDE_SYSTEM,
        material=json.dumps(state, ensure_ascii=False))
    content = out["output"]
    if not content:
        return _fallback()
    return ok({"text": content, "fallback": False})


@router.get("/sessions/{conv_id}/proxy-state")
async def proxy_state_endpoint(conv_id: str):
    """直通会话状态(cv-275): FE 持久状态条数据源(刷新安全)。"""
    from ..agent.execution.proxy import proxy_state
    return ok(proxy_state(conv_id))


@router.post("/sessions/{conv_id}/proxy-stop")
async def proxy_stop_endpoint(conv_id: str, request: Request = None):
    """停止直通执行器当前回合(cv-273)。

    主动中断: runner /abort 中止本轮; 会话行 sessionRef 保留——发消息即复活
    同执行器会话(暂停/恢复语义, 上下文延续)。无活跃直通会话 → 404。
    2610 cv-15: mode("abort"/"finish") 按钮语义显式覆盖——running 态允许
    直接结束会话, 不必先暂停; 缺省按作业状态自动分型(原行为)。"""
    from ..agent.execution.proxy import proxy_stop
    mode = ""
    if request is not None:
        try:
            data = await request.json() or {}
            mode = str(data.get("mode") or "")
        except Exception:  # noqa: BLE001 — 空 body/非 JSON 走自动分型
            mode = ""
    r = proxy_stop(conv_id, mode=mode)
    if not r.get("ok"):
        return err(404 if "无进行中" in (r.get("error") or "") else 502,
                   r.get("error") or "停止失败")
    return ok({"conversationId": conv_id, "jobId": r.get("job_id") or "",
               "summary": "已停止本轮执行（会话保留——发消息继续）"})
