"""需求草稿 API（批B/D + 意图空间一期 B1）：CRUD + 续写副本 + 技能处理作业。

技能处理（B1 统一 Skill Runner；批D 通道泛化，行为等价）：
- 指令 = 预设技能(注册表 agent/skills 单源) or 自定义 or 标记块嵌入
  (```topo-cmd 自由指令 / ```topo-skill:<id> 技能直呼)；
- 上下文 = 草稿全文(标记块剥离) + 指令；单轮对话+多轮只读工具
  (run_tools_loop 非会话同步通道)；产物写 last_proposed_md(用户裁决采纳)；
- 作业类型 skill_run(新) 与 draft_ai(存量兼容别名) 同执行体。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Request

from ..common import err, ok
from .semantic_assets import project_id_for

router = APIRouter()


@router.get("/req-drafts")
async def api_req_drafts_list(root: Optional[str] = None, project: Optional[str] = None):
    """草稿列表（资产管理页右栏草稿列表数据源；updated_at 倒序）。"""
    from ..store import ReqDraftsStore
    pid = project_id_for(root, project)
    if not pid:
        return ok({"drafts": []})
    rows = ReqDraftsStore.list(pid)
    for r in rows:
        # 列表不携带正文全量（体积）；摘要取首行
        r["excerpt"] = (r.get("contentMd") or "").strip().splitlines()[0][:80] if r.get("contentMd") else ""
        r.pop("contentMd", None)
        r.pop("lastProposedMd", None)
    return ok({"drafts": rows})


@router.post("/req-drafts")
async def api_req_drafts_create(request: Request = None):
    """新建草稿：{title?, contentMd?, root?, project?}。"""
    from ..store import ReqDraftsStore
    body = await request.json() if request else {}
    pid = project_id_for(body.get("root"), body.get("project"))
    if not pid:
        return err(400, "缺少项目")
    draft = ReqDraftsStore.create(pid, body.get("title") or "", body.get("contentMd") or "",
                                  tags=body.get("tags"))
    return ok(draft)


@router.get("/req-drafts-tags")
async def api_req_drafts_tags(root: Optional[str] = None, project: Optional[str] = None):
    """项目内 tag 全集(草稿 tag 联想备选): 去重计数按引用数降序。"""
    from ..store import ReqDraftsStore
    pid = project_id_for(root, project)
    if not pid:
        return ok({"tags": []})
    return ok({"tags": await asyncio.to_thread(ReqDraftsStore.all_tags, pid)})


@router.get("/req-drafts/{draft_id}")
async def api_req_drafts_get(draft_id: str):
    from ..store import ReqDraftsStore
    draft = ReqDraftsStore.get(draft_id)
    return ok(draft) if draft else err(404, "草稿不存在")


@router.put("/req-drafts/{draft_id}")
async def api_req_drafts_update(draft_id: str, request: Request = None):
    """保存草稿：{title?, contentMd?}。归档态只读拒绝（续写走 copy）。"""
    from ..store import ReqDraftsStore
    body = await request.json() if request else {}
    draft = ReqDraftsStore.get(draft_id)
    if not draft:
        return err(404, "草稿不存在")
    if (draft.get("status") or "editing") == "archived":
        return err(409, "草稿已发布归档（只读）；如需修改请续写副本")
    data = {}
    if "title" in body:
        data["title"] = str(body.get("title") or "")
    if "contentMd" in body:
        data["contentMd"] = str(body.get("contentMd") or "")
    if "tags" in body:
        data["tags"] = body.get("tags")   # store 层 _dump_tags 归一(去重/截限)
    updated = ReqDraftsStore.update(draft_id, data)
    return ok(updated)


@router.delete("/req-drafts/{draft_id}")
async def api_req_drafts_delete(draft_id: str):
    from ..store import ReqDraftsStore
    if not ReqDraftsStore.delete(draft_id):
        return err(404, "草稿不存在")
    return ok({"deleted": draft_id})


@router.post("/req-drafts/{draft_id}/copy")
async def api_req_drafts_copy(draft_id: str, request: Request = None):
    """续写：复制草稿为新的 editing 副本（归档草稿继续编写的主路径）。"""
    from ..store import ReqDraftsStore
    body = await request.json() if request else {}
    copy = ReqDraftsStore.copy(draft_id, title_suffix=body.get("titleSuffix") or "")
    if not copy:
        return err(404, "草稿不存在")
    return ok(copy)


# ── AI 处理（批D）：标记块拆分 + 预设指令 + 作业执行体 ──────────────────

import re as _re

_AGENT_FENCE_RE = _re.compile(r"```(?:topo-cmd|topo-skill(?P<sid>:[^\n]*?))?[ \t]*\r?\n(.*?)```", _re.S)


def split_agent_blocks(content_md: str, resolve_skill=None) -> tuple:
    """拆 ```topo-cmd / ```topo-skill:<id> 围栏标记块 → (正文, [嵌入指令...])。

    topo-cmd: 自由指令(2.6)；topo-skill:<id> 技能直呼(B1)——围栏首部
    ``topo-skill: review`` 形态, 其余行为附加指令; resolve_skill(id) 回调
    命中注册技能时指令替换为「技能指令\n附加指令」, 未命中按自由指令
    (不虚构技能)。程序拆分后与显式指令合并提交模型, 正文不含标记块
    (避免复读指令语法)。
    """
    instructions: list = []

    def _drop(m) -> str:
        sid = (m.group("sid") or "").lstrip(":").strip()
        # 注释行(# //开头)剥离——模板引导注释不进指令; 全注释块不产生空指令
        text = "\n".join(l for l in m.group(2).splitlines()
                         if not l.strip().startswith(("#", "//"))).strip()
        if sid:
            spec = resolve_skill(sid) if resolve_skill else None
            if spec is not None:
                instructions.append("\n".join(x for x in (spec.instruction, text) if x))
                return ""
            # 未注册技能 id: 不虚构技能, 余文按自由指令
        if text:
            instructions.append(text)
        return ""

    clean = _AGENT_FENCE_RE.sub(_drop, content_md or "")
    return clean, instructions


from ..agent import skills as _skills


def _job_skill_run(ctx) -> dict:
    """skill_run 作业执行体(统一 Skill Runner, B1)。

    scope = {draftId, skillId?, preset?, instruction?, root, project}——
    skillId 缺省回落 preset(存量兼容); 二者皆空 = 纯自定义指令。
    单轮对话+多轮只读工具(run_tools_loop)；产物写 last_proposed_md。
    """
    from ..agent.tools.req_agent import run_tools_loop
    from ..store import ReqDraftsStore
    sc = ctx.scope or {}
    draft = ReqDraftsStore.get(sc.get("draftId") or "")
    if not draft:
        return {"error": "草稿不存在"}
    if (draft.get("status") or "editing") == "archived":
        return {"error": "草稿已归档（只读）"}
    spec = _skills.get_skill(str(sc.get("skillId") or sc.get("preset") or ""))
    content_clean, embedded = split_agent_blocks(
        draft.get("contentMd") or "",
        resolve_skill=_skills.get_skill)
    parts = []
    if spec is not None:
        parts.append(spec.instruction)
    instr = (sc.get("instruction") or "").strip()
    if instr:
        parts.append("用户指令：" + instr)
    if embedded:
        parts.append("正文标记块指令：\n" + "\n---\n".join(embedded))
    if not parts:
        return {"error": "缺少处理指令（技能/自定义指令/标记块至少其一）"}
    ctx.progress(total=1, done=0, current="技能处理中")
    msgs = [
        {"role": "system", "content": spec.system if spec else _skills.SKILL_SYSTEM_DRAFT},
        {"role": "user", "content": "\n\n".join(parts)
         + "\n\n--- 草稿全文（处理后完整输出） ---\n" + (content_clean or "(空草稿)")},
    ]
    tools_used: set = set()

    def _prog(ev: str, detail: dict) -> None:
        if ev == "tool" and detail.get("tool"):
            tools_used.add(detail["tool"])
        ctx.progress(total=1, done=0,
                     current=f"{ev}:{detail.get('tool') or detail.get('round') or ''}")

    try:
        res = run_tools_loop(
            msgs, root=sc.get("root") or None, project=sc.get("project") or None,
            allowed=(spec.tools if spec else _skills.SKILL_TOOLS_READONLY),
            on_progress=_prog)
    except Exception as e:  # noqa: BLE001 — 作业线程吞异常保状态一致
        return {"error": f"技能处理失败: {str(e)[:200]}"}
    content = (res.get("content") or "").strip()
    if not content:
        return {"error": "AI 未返回内容" + (f"（{res.get('error')}）" if res.get("error") else "")}
    ReqDraftsStore.update(draft["id"], {
        "lastProposedMd": content,
        "lastProposedAt": int(__import__("time").time() * 1000)})
    return {"saved": 1, "summary": f"技能处理完成（{spec.id if spec else 'custom'}，待比对采纳）",
            "toolCalls": sorted(tools_used)}


from ..sem import job_runner as _job_runner
_job_runner.register("skill_run", _job_skill_run)
_job_runner.register("draft_ai", _job_skill_run)   # 存量别名(同执行体)


@router.get("/skills")
async def api_skills_list(domain: str = "draft"):
    """技能注册表(FE 预设按钮/建议引擎动态取用; 指令全文不列)。"""
    return ok({"skills": _skills.list_skills(domain or "")})


MAX_PICKER_KW = 5       # 关键字数量上限(空格分割)
PICKER_PAGE_DEFAULT = 10


@router.get("/sessions/picker")
async def list_sessions_picker(kw: str = "", limit: int = PICKER_PAGE_DEFAULT,
                               offset: int = 0, project: str = ""):
    """发布目标会话选择器（需求草稿发布配套；归入草稿域避免 sessions.py 膨胀）：

    - 只显示**活跃**会话（archived/closed 不显示）；
    - kw 多关键字（空格分割，上限 5，超限截断）：AND 组合优先（全部命中）；
      AND 无结果自动降级 OR（任一命中），响应 orFallback=true 标注；
      匹配字段：标题/摘要/预览；
    - limit/offset 分页，默认每页 10；返回 {items, total, offset, orFallback}。
    """
    from .. import store
    rows = store.ConversationsStore.summaries(
        limit=400, project_id=project or None, all_scopes=bool(project))
    rows = [c for c in rows
            if (c.get("kind") or "") != "coding"
            and (c.get("status") or "active") == "active"]

    def _haystack(c: dict) -> str:
        return " ".join([
            c.get("title") or "", c.get("summary") or "", c.get("preview") or ""]).lower()

    keywords = [k for k in (kw or "").lower().split() if k.strip()][:MAX_PICKER_KW]
    or_fallback = False
    if keywords:
        pool = [{"row": c, "hay": _haystack(c)} for c in rows]
        hit = [p["row"] for p in pool if all(k in p["hay"] for k in keywords)]
        if not hit:
            hit = [p["row"] for p in pool if any(k in p["hay"] for k in keywords)]
            or_fallback = bool(hit)
        rows = hit
    total = len(rows)
    page = rows[int(offset):int(offset) + max(1, int(limit))]
    items = [{
        "id": c["id"], "title": c.get("title") or "",
        "reqId": c.get("reqId") or "",
        "updatedAt": c.get("updatedAt") or 0,
    } for c in page]
    return ok({"items": items, "total": total, "offset": int(offset),
               "limit": int(limit), "orFallback": or_fallback,
               "keywords": keywords})


@router.post("/req-drafts/{draft_id}/publish")
async def api_req_drafts_publish(draft_id: str, request: Request = None):
    """发布草稿为需求卡（批F，2.4/2.5）：目标=新会话或已有会话。

    - 无 targetConvId → 创建新会话（requirement/architect 角色）；
    - 有 → 会话绑定的需求**未交付完结**（活跃）→ 发布即 amend 覆盖，须
      overwrite 确认（409 回执冲突详情，用户确认后重发）；已完结/无绑定 →
      propose 新建（apply_spec_payload 内建归属三分，cv-248 同源判据）；
    - 落库走 apply_spec_payload（幂等指纹/三级降级复用）+ 会话写 assistant
      规约消息（会话管理页可见来源）；
    - 草稿置 archived（只读）；修改走续写副本。
    """
    from ..agent.planning.req_spec import _plan_delivered, apply_spec_payload
    from .. import ctx as _ctx
    from .. import store
    body = await request.json() if request else {}
    draft = store.ReqDraftsStore.get(draft_id)
    if not draft:
        return err(404, "草稿不存在")
    if (draft.get("status") or "editing") == "archived":
        return err(409, "草稿已发布归档；如需修改请续写副本")
    content = (draft.get("contentMd") or "").strip()
    if not content:
        return err(400, "草稿正文为空，无法发布")
    pid = project_id_for(body.get("root"), body.get("project")) or draft.get("projectId") or ""
    target_conv_id = (body.get("targetConvId") or "").strip()

    # ① 目标会话解析/创建
    if target_conv_id:
        conv = store.ConversationsStore.get(target_conv_id)
        if not conv:
            return err(404, "目标会话不存在")
        bound_rid = str(conv.get("reqId") or "")
        if bound_rid and store.RequirementsStore.get(bound_rid) and not _plan_delivered(bound_rid):
            if not body.get("overwrite"):
                req_row = store.RequirementsStore.get(bound_rid) or {}
                return err(409, "目标会话存在未完结需求卡，发布将覆盖修订（amend）")
    else:
        conv = store.ConversationsStore.create({
            "kind": "requirement", "projectId": pid,
            "title": (draft.get("title") or "").strip() or "需求草稿发布",
            "status": "active", "roles": ["architect"], "tags": {"modules": [], "groups": []},
        })
        conv = store.ConversationsStore.get(conv["id"]) or conv
        target_conv_id = conv["id"]

    # ② 落库（ctx 会话上下文：propose 绑定回写依赖，cv-248 同源）
    token = _ctx.set_conv(target_conv_id)
    try:
        result = apply_spec_payload(
            {"title": (draft.get("title") or "").strip(), "requirementMd": content},
            req_id=str(conv.get("reqId") or ""),
            project=str(conv.get("projectId") or pid), root="")
    finally:
        _ctx.reset_conv(token)
    if result.get("error"):
        return err(500, f"需求落库失败: {result['error']}")
    rid = str(result.get("requirementId") or "")

    # ③ 会话消息（assistant 规约来源可溯）
    store.ConversationsStore.append_message({
        "id": store.next_id("m"), "conversationId": target_conv_id,
        # projectId 为库路由提示键(消息表无此列, _insert_into 过滤)——
        # 缺失时消息落主库而会话在项目库, messages() 按会话库直查读不到
        "projectId": str(conv.get("projectId") or pid),
        "role": "assistant", "time": int(__import__("time").time() * 1000),
        "content": f"📋 **需求草稿发布**（{draft.get('title') or '未命名'}）\n\n"
                   f"需求卡：`{rid}`（"
                   + ("修订覆盖" if conv.get("reqId") else "新建")
                   + "）。正文：\n\n---\n\n" + content[:6000],
    })

    # ④ 草稿归档回填
    updated = store.ReqDraftsStore.update(draft_id, {
        "status": "archived", "publishedConvId": target_conv_id, "publishedReqId": rid})
    return ok({"draft": updated, "convId": target_conv_id, "requirementId": rid,
               "amended": bool(conv.get("reqId"))})


@router.post("/req-drafts/{draft_id}/adopt")
async def api_req_drafts_adopt(draft_id: str):
    """采纳 AI 产物：contentMd ← lastProposedMd 并清空（批E diff 确认流）。

    放弃=不调用本端点（lastProposedMd 保留作 UI 参考，被下一轮产物覆盖）。
    """
    from ..store import ReqDraftsStore
    draft = ReqDraftsStore.get(draft_id)
    if not draft:
        return err(404, "草稿不存在")
    if (draft.get("status") or "editing") == "archived":
        return err(409, "草稿已归档（只读）")
    proposed = (draft.get("lastProposedMd") or "").strip()
    if not proposed:
        return err(400, "无可采纳的 AI 产物")
    updated = ReqDraftsStore.update(draft_id, {
        "contentMd": proposed, "lastProposedMd": "", "lastProposedAt": 0})
    return ok(updated)


@router.post("/req-drafts/{draft_id}/ai")
async def api_req_drafts_ai(draft_id: str, request: Request = None):
    """提交技能处理作业：{skill | preset, instruction?, root?, project?}。

    skill(B1)与 preset(存量)同义, skill 优先; 皆空 = 纯自定义指令。
    产物写 last_proposed_md，完成后 FE 拉取草稿做 diff 预览（采纳/放弃）。
    """
    from ..sem import job_runner
    from ..store import ReqDraftsStore
    body = await request.json() if request else {}
    draft = ReqDraftsStore.get(draft_id)
    if not draft:
        return err(404, "草稿不存在")
    if (draft.get("status") or "editing") == "archived":
        return err(409, "草稿已归档（只读）")
    pid = project_id_for(body.get("root"), body.get("project"))
    if not pid:
        return err(400, "缺少项目")
    r = await asyncio.to_thread(
        job_runner.start_job, pid, "skill_run",
        {"draftId": draft_id, "skillId": body.get("skill") or "",
         "preset": body.get("preset") or "",
         "instruction": body.get("instruction") or "",
         "root": body.get("root") or "", "project": body.get("project") or ""},
        llm=True)
    if not r.get("started") and r.get("reason") == "already_running":
        return ok(r)
    if not r.get("started"):
        return err(400, f"作业提交失败: {r.get('reason')}")
    return ok(r)
