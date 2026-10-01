"""需求草稿 API（批B/D）：CRUD + 续写副本 + AI 处理作业。

AI 处理（批D，需求草稿概念设计 2.6-2.9）：
- 单轮对话 + 多轮工具调用（run_tools_loop 非会话同步通道）；
- 上下文 = 草稿全文(标记块剥离) + 指令（预设按钮 or 自定义 or ```agent 标记块嵌入）；
- 工具白名单 = 只读查询类（语义资产/代码/图谱/结构图生成）；
- 产物写 last_proposed_md（未采纳保留仅 UI 参考，不进下轮上下文——用户裁决）。
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
    draft = ReqDraftsStore.create(pid, body.get("title") or "", body.get("contentMd") or "")
    return ok(draft)


@router.get("/req-drafts/{draft_id}")
async def api_req_drafts_get(draft_id: str):
    from ..store import ReqDraftsStore
    draft = ReqDraftsStore.get(draft_id)
    if not draft:
        return err(404, "草稿不存在")
    return ok(draft)


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

_AGENT_FENCE_RE = _re.compile(r"```agent[ \t]*\r?\n(.*?)```", _re.S)


def split_agent_blocks(content_md: str) -> tuple:
    """拆 ```agent 围栏标记块 → (剥离后的正文, [嵌入指令...])。

    高级自定义需求与指令以特殊文本标记块实现（2.6）；程序拆分后与
    显式指令合并提交模型，正文不含标记块（避免模型复读指令语法）。
    """
    instructions: list = []

    def _drop(m) -> str:
        instructions.append(m.group(1).strip())
        return ""

    clean = _AGENT_FENCE_RE.sub(_drop, content_md or "")
    return clean, instructions


_DRAFT_AI_SYSTEM = (
    "你是需求工程助手，工作在「需求草稿」场景：用户给出一份需求文本草稿与一条处理指令，"
    "你按指令处理草稿并输出**完整的新版草稿全文**（Markdown）。\n"
    "规则：\n"
    "1. 输出即替换：只输出新版全文，不要输出解释、寒暄或差异说明；\n"
    "2. 保留原稿中未受指令影响的内容与结构，不做未经要求的大改；\n"
    "3. 可调用只读查询工具检索语义资产/代码/图谱作为依据，图表用 ```mermaid 或 "
    "```plantuml 围栏嵌入；\n"
    "4. 自定义指令以「用户指令」为准，正文中的 ```agent 标记块已由程序拆出合并；\n"
    "5. 不产出需求卡/不落库——落库由用户发布环节完成。"
)

_PRESETS = {
    "generate": ("需求生成：基于草稿现有内容，补全为一份完整的需求文本——"
                 "补齐背景/场景/功能点/约束/验收标准；已有内容尽量保留原貌，缺失处合理补写。"),
    "review": ("需求审核：逐项审查草稿的完整性/一致性/可测性/歧义，直接给出修订后的全文"
               "（在原结构上修订；发现的问题以「> ⚠ 审核：」引用块标注在对应章节）。"),
    "relate": ("需求关联分析：结合语义资产与代码图谱，分析本需求涉及的资产/组件/依赖，"
               "在草稿末尾追加「## 关联分析」章节（涉及资产清单+依赖说明），其余内容原样保留。"),
}

# 只读工具白名单（2.6/设计裁决：写路径走既有任务化闭环，AI 不写）
_AI_TOOLS = [
    "asset.semantic.search", "asset.semantic.detail", "asset.semantic.stats",
    "asset.semantic.mappings", "asset.read_source", "code.read_symbols",
    "kb.asset.search", "kb.graph", "kb.baseline", "kb.code_mappings",
    "map.assets", "map.component", "map.graph", "map.overview",
    "diagram.build", "diagram.validate", "project.ctx",
]


def _job_draft_ai(ctx) -> dict:
    """draft_ai 作业执行体：scope = {draftId, preset, instruction, root, project}。

    单轮对话+多轮工具（run_tools_loop 同步通道）；产物写 last_proposed_md。
    """
    from ..agent.tools.req_agent import run_tools_loop
    from ..store import ReqDraftsStore
    sc = ctx.scope or {}
    draft = ReqDraftsStore.get(sc.get("draftId") or "")
    if not draft:
        return {"error": "草稿不存在"}
    if (draft.get("status") or "editing") == "archived":
        return {"error": "草稿已归档（只读）"}
    content_clean, embedded = split_agent_blocks(draft.get("contentMd") or "")
    preset_key = sc.get("preset") or ""
    parts = []
    if preset_key in _PRESETS:
        parts.append(_PRESETS[preset_key])
    instr = (sc.get("instruction") or "").strip()
    if instr:
        parts.append("用户指令：" + instr)
    if embedded:
        parts.append("正文标记块指令：\n" + "\n---\n".join(embedded))
    if not parts:
        return {"error": "缺少处理指令（preset/instruction/标记块至少其一）"}
    ctx.progress(total=1, done=0, current="AI 处理中")
    msgs = [
        {"role": "system", "content": _DRAFT_AI_SYSTEM},
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
            allowed=_AI_TOOLS, on_progress=_prog)
    except Exception as e:  # noqa: BLE001 — 作业线程吞异常保状态一致
        return {"error": f"AI 处理失败: {str(e)[:200]}"}
    content = (res.get("content") or "").strip()
    if not content:
        return {"error": "AI 未返回内容" + (f"（{res.get('error')}）" if res.get("error") else "")}
    ReqDraftsStore.update(draft["id"], {
        "lastProposedMd": content,
        "lastProposedAt": int(__import__("time").time() * 1000)})
    return {"saved": 1, "summary": "AI 处理完成（待比对采纳）",
            "toolCalls": sorted(tools_used)}


from ..sem import job_runner as _job_runner
_job_runner.register("draft_ai", _job_draft_ai)


@router.post("/req-drafts/{draft_id}/ai")
async def api_req_drafts_ai(draft_id: str, request: Request = None):
    """提交 AI 处理作业：{preset: generate|review|relate|custom, instruction?, root?, project?}。

    作业执行体同步跑 LLM 工具循环（LLM 类全局串行）；产物写 last_proposed_md，
    完成后 FE 拉取草稿做 diff 预览（批E 采纳/放弃）。
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
        job_runner.start_job, pid, "draft_ai",
        {"draftId": draft_id, "preset": body.get("preset") or "",
         "instruction": body.get("instruction") or "",
         "root": body.get("root") or "", "project": body.get("project") or ""},
        llm=True)
    if not r.get("started") and r.get("reason") == "already_running":
        return ok(r)
    if not r.get("started"):
        return err(400, f"作业提交失败: {r.get('reason')}")
    return ok(r)
