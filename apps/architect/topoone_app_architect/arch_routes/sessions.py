"""会话中心 routes(P1) —— 会话是唯一主体。

裁决对齐:
  - 只有会话没有流程: 列表/分组全部基于元数据(标题/时间/模块/自定义分组)，
    不再有需求池/待执行等流程分组;
  - 需求文档 = 备案文档(DocsStore): 从会话随时总结提取、随时增删;
  - 全量持久化: ConversationsStore + tags/summary, 支撑历史总结。

项目路由: 与 /requirements 同口径, 经 ProjectContextMiddleware 的 ?project=。
"""
import json
from typing import Optional

from fastapi import APIRouter, Request

from .common import _ts, ok, err
from . import store

router = APIRouter()

# 会话中心全量口径(含资产/设计对话; execution/unit-test 会话由对应域自持, 此处也收录)
SESSION_KINDS = ["requirement", "design", "asset", "execution", "unit-test", "generic"]

# PR1 双维度状态机: 生命周期(status) + 查看状态(review_state)
LIFECYCLES = ("active", "running", "archived")          # archived 不可逆终态
REVIEW_STATES = ("read", "unread", "awaiting_reply", "error")

_GROUPS_KEY = "session.groups"      # 用户自定义分组(collab config, JSON 数组)


def _pending_exec(c) -> bool:
    """待执行标记(meta.pendingExec): 确认定稿生成的待执行会话(active 生命周期)。"""
    try:
        meta = json.loads(c.get("meta") or "{}") if isinstance(c.get("meta"), str) else (c.get("meta") or {})
        return bool(isinstance(meta, dict) and meta.get("pendingExec"))
    except (TypeError, ValueError):
        return False


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


@router.get("/sessions")
async def list_sessions(kind: str = "", q: str = "", limit: int = 400, scope: str = ""):
    """会话列表(全量会话 + 消息数/预览)。q: 标题/摘要模糊过滤(前端侧也过滤)。

    scope=all: 跨全库(主库+各项目库)汇总 —— 会话中心统一视图, 不受 ?project= 限制。
    """
    rows = store.ConversationsStore.summaries(
        kind=kind or None, limit=limit, all_scopes=(scope == "all"))
    items = []
    for c in rows:
        title = c.get("title") or ""
        item = {
            "id": c["id"],
            "kind": c.get("kind") or "requirement",
            "reqId": c.get("reqId") or "",
            "title": title,
            "status": c.get("status") or "active",
            "reviewState": c.get("reviewState") or "read",
            "roleId": c.get("roleId") or "architect",
            "pendingExec": _pending_exec(c),
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
async def list_groups(scope: str = ""):
    """分组维度: 用户自定义分组 + 会话身上出现过的 modules/groups 并集(scope=all 跨全库)。"""
    convs = store.ConversationsStore.summaries(limit=400, all_scopes=(scope == "all"))
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


# ── PR2 角色管理: architect 系统角色(唯一/不可删) + executor 绑执行器实例 ──

_ROLE_SKILL_POOL = ["extract", "plan", "coding", "capability", "accept", "naming", "contract", "linenote"]


@router.get("/session-roles")
async def list_session_roles():
    roles = store.SessionRolesStore.all()
    # 附执行器实例名(便于前端展示绑定对象)
    try:
        from .agent_executors import load_executors
        ex_names = {e.get("id"): e.get("id") for e in load_executors()}
    except Exception:  # noqa: BLE001
        ex_names = {}
    out = []
    for r in roles:
        r = dict(r)
        r["executorLabel"] = ex_names.get(r.get("executorId") or "", "")
        r["skillPool"] = _ROLE_SKILL_POOL
        out.append(r)
    return ok(out)


@router.put("/session-roles")
async def put_session_role(request: Request):
    """新增/更新角色(upsert)。内置 architect 角色仅允许改能力配置。"""
    data = await request.json()
    rid = str(data.get("id") or "").strip()
    name = str(data.get("name") or "").strip()
    if not rid or not name:
        return err(400, "角色 id 与名称必填")
    if rid == "architect" and str(data.get("kind") or "executor") != "architect":
        return err(400, "architect 为系统内置角色, kind 不可改")
    existing = store.SessionRolesStore.get(rid)
    if not existing and str(data.get("kind") or "") == "executor":
        if not str(data.get("executorId") or "").strip():
            return err(400, "executor 角色必须绑定执行器实例(executorId)")
    role = store.SessionRolesStore.upsert({
        "id": rid, "name": name,
        "kind": data.get("kind") or ("architect" if rid == "architect" else "executor"),
        "executorId": data.get("executorId") or "",
        "modelId": data.get("modelId") or "",
        "skills": data.get("skills") or [],
        "tools": data.get("tools") or [],
        "permissions": data.get("permissions") or {},
    })
    return ok(role)


@router.delete("/session-roles/{role_id}")
async def delete_session_role(role_id: str):
    """删除角色(内置 architect 拒绝; 被会话引用中的角色拒绝)。"""
    role = store.SessionRolesStore.get(role_id)
    if not role:
        return err(404, "角色不存在")
    if role.get("builtin"):
        return err(400, "architect 为系统内置角色, 不可删除")
    # 会话引用校验: 有活跃(未归档)会话使用该角色 → 拒绝删除
    used = [c for c in store.ConversationsStore.all(limit=400)
            if (c.get("roleId") or "architect") == role_id
            and (c.get("status") or "active") != "archived"]
    if used:
        return err(400, f"仍有 {len(used)} 个未归档会话使用该角色, 不可删除")
    store.SessionRolesStore.delete(role_id)
    return ok({"deleted": True, "id": role_id})


@router.post("/sessions")
async def create_session(request: Request):
    data = await request.json()
    kind = data.get("kind") or "requirement"
    if kind not in SESSION_KINDS:
        kind = "requirement"
    title = (data.get("title") or "").strip()
    role_id = data.get("roleId") or "architect"
    if role_id != "architect" and not store.SessionRolesStore.get(role_id):
        return err(400, f"角色不存在: {role_id}")
    conv = store.ConversationsStore.create({
        "kind": kind,
        "projectId": data.get("projectId") or "",
        "title": title or f"{kind} 会话",
        "status": "active",
        "roleId": role_id,
        "tags": _norm_tags(data) or {"modules": [], "groups": []},
        "meta": data.get("meta") or {},
    })
    return ok(_conv_api(conv))


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
        if status not in LIFECYCLES:
            return err(400, f"非法生命周期状态: {status}(active|running|archived)")
        if (conv.get("status") or "active") == "archived" and status != "archived":
            return err(400, "归档不可逆：归档会话只读，请复制到新会话继续")
        patch["status"] = status
    if "reviewState" in data:
        rs = str(data.get("reviewState") or "").strip()
        if rs not in REVIEW_STATES:
            return err(400, f"非法查看状态: {rs}(read|unread|awaiting_reply|error)")
        patch["reviewState"] = rs
    # PR3 角色切换: architect→executor 单向一次(切换即锁定); 再换走交接(P4)
    if "roleId" in data and (data.get("roleId") or "architect") != (conv.get("roleId") or "architect"):
        target = str(data.get("roleId") or "").strip()
        role = store.SessionRolesStore.get(target)
        if not role:
            return err(400, f"角色不存在: {target}")
        if (role.get("kind") or "executor") != "executor":
            return err(400, "只能切换到 executor 角色系统角色 architect 不可指定")
        if conv.get("roleLocked"):
            return err(400, "会话角色已锁定(首次切换后不可再改)：请用交接指令生成新会话再绑定新角色")
        if (conv.get("status") or "active") == "archived":
            return err(400, "归档会话只读，不可切换角色")
        # 规范化门槛: 会话绑定需求且已定稿入池(location=pool)
        req_id = conv.get("reqId") or ""
        req = store.RequirementsStore.get(req_id) if req_id else None
        if not req or (req.get("location") or "") != "pool":
            return err(400, "需求未规范化：请先在会话中「方案生成→确认存入」定稿入池，再切换执行角色")
        patch["roleId"] = target
        patch["roleLocked"] = True
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
    store.ConversationsStore.delete(conv_id)
    return ok({"deleted": True, "id": conv_id})


@router.get("/sessions/{conv_id}/messages")
async def session_messages(conv_id: str):
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    return ok({"id": conv_id, "messages": store.ConversationsStore.messages(conv_id, limit=1000)})


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


def _conv_api(conv: dict) -> dict:
    return {
        "id": conv["id"],
        "kind": conv.get("kind") or "requirement",
        "reqId": conv.get("reqId") or "",
        "title": conv.get("title") or "",
        "status": conv.get("status") or "active",
        "reviewState": conv.get("reviewState") or "read",
        "roleId": conv.get("roleId") or "architect",
        "roleLocked": bool(conv.get("roleLocked")),
        "pendingExec": _pending_exec(conv),
        "tags": _tags_of(conv),
        "summary": conv.get("summary") or "",
        "createdAt": conv.get("createdAt"),
        "updatedAt": conv.get("updatedAt"),
    }


# ── P3: probe(方案草图) + 前置上下文构造 ────────────────────

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


# ── 备案文档(DocsStore): 会话派生的总结性文档 ──────────────────

@router.get("/session-docs")
async def list_docs(conversation_id: str = "", type: str = "", limit: int = 200):
    return ok(store.DocsStore.all(
        conversation_id=conversation_id or None, type_=type or None, limit=limit))


@router.post("/session-docs")
async def create_doc(request: Request):
    data = await request.json()
    conv_id = (data.get("conversationId") or "").strip()
    if conv_id and not store.ConversationsStore.get(conv_id):
        return err(404, "来源会话不存在")
    doc = store.DocsStore.create({
        "projectId": data.get("projectId") or "",
        "conversationId": conv_id,
        "type": data.get("type") or "requirement_summary",
        "title": data.get("title") or "",
        "contentMd": data.get("contentMd") or "",
        "refs": data.get("refs") or {},
    })
    return ok(doc)


@router.get("/session-docs/{doc_id}")
async def get_doc(doc_id: str):
    doc = store.DocsStore.get(doc_id)
    if not doc:
        return err(404, "文档不存在")
    return ok(doc)


@router.patch("/session-docs/{doc_id}")
async def update_doc(doc_id: str, request: Request):
    doc = store.DocsStore.get(doc_id)
    if not doc:
        return err(404, "文档不存在")
    data = await request.json()
    patch = {}
    if "title" in data:
        patch["title"] = str(data.get("title") or "").strip()
    if "contentMd" in data:
        patch["contentMd"] = str(data.get("contentMd") or "")
    if "refs" in data and isinstance(data.get("refs"), dict):
        patch["refs"] = data["refs"]
    if not patch:
        return err(400, "无可更新字段")
    return ok(store.DocsStore.update(doc_id, patch))


@router.delete("/session-docs/{doc_id}")
async def delete_doc(doc_id: str):
    if not store.DocsStore.get(doc_id):
        return err(404, "文档不存在")
    store.DocsStore.delete(doc_id)
    return ok({"deleted": True, "id": doc_id})


_DOC_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "contentMd": {"type": "string", "description": "Markdown 格式的需求/方案总结文档"},
    },
    "required": ["title", "contentMd"],
}


@router.post("/session-docs/from-conversation/{conv_id}")
async def doc_from_conversation(conv_id: str, request: Request):
    """从会话提取备案文档(裁决2): LLM 总结需求/方案, 降级为对话原文拼接。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    data = {}
    try:
        data = await request.json()
    except Exception:
        data = {}
    title_hint = (data.get("title") or "").strip()
    msgs = store.ConversationsStore.messages(conv_id, limit=200)
    transcript = "\n".join(
        f"[{'用户' if m.get('role') == 'user' else '助手'}] {(m.get('content') or '').strip()[:1200]}"
        for m in msgs if (m.get("content") or "").strip()
    )
    if not transcript:
        return err(400, "会话无消息, 无法提取")
    title, content = "", ""
    from . import req_agent
    res = req_agent.llm_sync(
        messages=[
            {"role": "system",
             "content": "你是需求归档助手。把对话中的需求与方案讨论整理为一份备案文档"
                        "(Markdown: ## 需求 / ## 方案 / ## 待办 三段), 忠实于对话内容, 不新增结论。"},
            {"role": "user", "content": f"对话记录:\n{transcript[:24000]}"},
        ],
        mode="structured",
        output_schema=_DOC_SCHEMA,
        max_tokens=2048,
    )
    if res and isinstance(res.get("output"), dict):
        title = str(res["output"].get("title") or "").strip()[:80]
        content = str(res["output"].get("contentMd") or "").strip()
    if not content:
        title = title_hint or (conv.get("title") or "会话备案")
        content = f"# {title}\n\n(自动提取降级: 对话原文)\n\n{transcript[:12000]}"
    doc = store.DocsStore.create({
        "projectId": conv.get("projectId") or "",
        "conversationId": conv_id,
        "type": data.get("type") or "requirement_summary",
        "title": title_hint or title,
        "contentMd": content,
        "refs": data.get("refs") or {},
    })
    return ok(doc)
