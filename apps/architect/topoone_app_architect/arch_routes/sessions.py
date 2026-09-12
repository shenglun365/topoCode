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
SESSION_KINDS = ["requirement", "asset", "unit-test", "generic"]

# PR1 双维度状态机: 生命周期(status) + 查看状态(review_state)
LIFECYCLES = ("active", "running", "archived")          # archived 不可逆终态
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
            "workState": c.get("workState") or "architect",
            "reviewState": c.get("reviewState") or "read",
            "roles": _roles_of(c),
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

# 技能场景简介(功能/使用场景一句话, 前端 tooltip+已选说明展示)
_SKILL_INTROS = {
    "extract": "对话式语义提取——从对话/代码中识别接口、实体与语义结构。用于需求澄清、资产盘点。",
    "plan": "方案生成——产出执行方案与任务分解。用于需求入池后的设计阶段。",
    "coding": "coding agent 委派——把编码任务委派给绑定的执行器实例。executor 角色默认启用。",
    "capability": "能力评估与提炼——执行结果图文评估、从历史会话沉淀规约与技巧。",
    "accept": "验收比对——对照验收标准逐条核对交付物。建议搭配强模型。",
    "naming": "命名治理——实体/接口命名规范化与冲突检测。用于认知编辑前审计。",
    "contract": "接口契约——契约条款生成与一致性校验。用于跨模块/跨团队接口对齐。",
    "linenote": "代码逐行解读——为存量代码生成逐行讲解与知识沉淀。",
}


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
        r["skillIntros"] = _SKILL_INTROS
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
    # 模型白名单校验: modelId 必须属于绑定执行器实例的模型表
    # (运行时只在实例白名单内调用模型, 防止旁路高付费模型)
    model_id = str(data.get("modelId") or "").strip()
    if model_id and str(data.get("executorId") or "").strip():
        from .agent_executors import load_executors
        ex = next((e for e in load_executors()
                   if e.get("id") == str(data.get("executorId")).strip()), None)
        if not ex:
            return err(400, f"执行器实例不存在: {data.get('executorId')}")
        allowed = {str(m.get(k)) for m in (ex.get("config") or {}).get("models") or []
                   for k in ("name", "model") if m.get(k)}
        if allowed and model_id not in allowed:
            return err(400, f"模型 {model_id} 不在执行器实例模型白名单内, 可选: {', '.join(sorted(allowed)[:8])}")
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
            if role_id in _roles_of(c)
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
    roles = ["architect"]
    for rid in (data.get("roles") or []):
        rid = str(rid or "").strip()
        if rid and rid != "architect":
            if not store.SessionRolesStore.get(rid):
                return err(400, f"角色不存在: {rid}")
            if rid not in roles:
                roles.append(rid)
    conv = store.ConversationsStore.create({
        "kind": kind,
        "projectId": data.get("projectId") or "",
        "title": title or f"{kind} 会话",
        "status": "active",
        "roles": roles,
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
    # 角色集更新(生命周期重构: 声明即用, 不锁定; architect 恒在)
    if "roles" in data:
        if (conv.get("status") or "active") == "archived":
            return err(400, "归档会话只读，不可更新角色")
        roles = ["architect"]
        for rid in (data.get("roles") or []):
            rid = str(rid or "").strip()
            if rid and rid != "architect":
                if not store.SessionRolesStore.get(rid):
                    return err(400, f"角色不存在: {rid}")
                if rid not in roles:
                    roles.append(rid)
        if roles != _roles_of(conv):
            patch["roles"] = roles
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


def _roles_of(conv: dict) -> list:
    r = conv.get("roles")
    return r if isinstance(r, list) and r else ["architect"]


def _conv_api(conv: dict) -> dict:
    return {
        "id": conv["id"],
        "kind": conv.get("kind") or "generic",
        "reqId": conv.get("reqId") or "",
        "title": conv.get("title") or "",
        "status": conv.get("status") or "active",
        "workState": conv.get("workState") or "architect",
        "reviewState": conv.get("reviewState") or "read",
        "roles": _roles_of(conv),
        "tags": _tags_of(conv),
        "summary": conv.get("summary") or "",
        "createdAt": conv.get("createdAt"),
        "updatedAt": conv.get("updatedAt"),
    }


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


# ── 指令引导(按需 agent 建议) ──
# 「指令引导」按钮: 基于会话当前状态(RQ 版本链/作业账本/最近消息)由 LLM 生成
# 下一步操作建议。旁路 REST——不落库、不进对话上下文; LLM 不可达 →
# fallback=True, 前端回退静态触发词提示。

_GUIDE_SYSTEM = (
    "你是「架构师工作台」的会话导航助手。基于给定的会话状态，给出 2-4 条下一步操作建议。\n"
    "要求：\n"
    "1. 每条建议必须引用会话中的具体内容（如需求标题、方案要点、作业分支、agent 提出的问题、"
    "待确认的版本），让建议与当前进展强相关；禁止泛泛而谈。\n"
    "2. 在语义确实匹配时才在句尾用「触发词：X」附加触发词（可用：执行方案 / 方案调整+调整点 / "
    "确认执行 / 继续执行 / 查看差异 / 标记完成）；无匹配触发词时给自然语言操作建议，不要硬贴。\n"
    "3. 输出 markdown 无序列表，每条一句话；只输出列表本身，不要标题、不要解释、不要代码围栏。"
)


def _guide_req_state(req_id: str) -> Optional[dict]:
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


def _guide_jobs_state(conv_id: str) -> list:
    try:
        from .exec_bridge import jobs_of, waiting_job
        jobs = jobs_of(conv_id)[-3:]
        w = waiting_job(conv_id)
        out = [{
            "jobId": j.get("jobId"), "status": j.get("status"),
            "branch": j.get("branch") or "",
        } for j in jobs]
        if w and w.get("jobId") and w.get("jobId") not in {j["jobId"] for j in out}:
            out.append({"jobId": w.get("jobId"), "status": "waiting_input", "branch": w.get("branch") or ""})
        return out
    except Exception:  # noqa: BLE001
        return []


@router.post("/sessions/{conv_id}/stop-exec")
async def stop_exec_session(conv_id: str):
    """UI 停止按钮(REST, 裁决#5): 结束会话全部运行中作业(保留 worktree/分支)。

    作业句柄已不在 runner(重启清空)时 _runner 调用静默失败, 账本仍终态化。
    """
    from . import exec_bridge
    if not store.ConversationsStore.get(conv_id):
        return err(404, "会话不存在")
    return ok({"message": exec_bridge.stop(conv_id, reason="user")})


@router.post("/sessions/{conv_id}/guide")
async def session_guide(conv_id: str):
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")

    msgs = store.ConversationsStore.messages(conv_id, limit=1000)[-10:]
    state = {
        "title": conv.get("title") or "",
        "kind": conv.get("kind") or "",
        "status": conv.get("status") or "active",
        "workState": conv.get("workState") or "architect",
        "requirement": _guide_req_state(conv.get("reqId") or ""),
        "execJobs": _guide_jobs_state(conv_id),
        "recentMessages": [
            {"role": m.get("role"), "content": (m.get("content") or "")[:240]}
            for m in msgs if (m.get("content") or "").strip()
        ],
    }

    def _fallback():
        return ok({"text": "", "fallback": True})

    try:
        from .req_agent import llm_sync
        res = llm_sync(
            [{"role": "system", "content": _GUIDE_SYSTEM},
             {"role": "user", "content": json.dumps(state, ensure_ascii=False)}],
            mode="chat", max_tokens=500)
    except Exception:  # noqa: BLE001
        return _fallback()
    content = ((res or {}).get("content") or "").strip() if isinstance(res, dict) else ""
    if not content:
        return _fallback()
    return ok({"text": content, "fallback": False})
