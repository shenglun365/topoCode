"""上下文注册表(P2) —— 会话派生单元的写入/检索/提取。

设计对齐(裁决3): 上下文统一 = 每个任务会话执行前可「拉取」关联内容构造完整上下文；
不是把所有内容塞进一个会话。本模块提供:

  写入侧(自动 hook):
    - 对话工具轨迹(tool_call) → 单元(含 req.propose 等产物 artifact 单元)
    - 会话摘要(session_summary) → 单元(POST /sessions/{id}/summarize 时)
    - 执行回执(execution_report) → 单元(执行终态: done/failed/stopped)
    消息本体不复制(存 arch_conversation_messages)，检索时联查——注册表保持轻。

  读取侧(拉取式):
    - ctx.search(query, types, conversation_id) → 跨会话检索单元+消息+备案文档(MD)
    - ctx.get(conversation_id) → 会话上下文包(摘要+单元+文档清单, MD)
    - ctx.summarize(conversation_id) → 生成/刷新会话摘要并返回
  三面暴露: 会话 agent 工具(register_architect_tool) / MCP(map.* 同款 run_tool) / REST。
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

# 惰性访问(P4): agent 侧模块不得在 import 期触发 arch_routes 初始化(循环导入)
def _store():
    from ... import store
    return store


def _arch_ts():
    from ...common import _ts
    return _arch_ts()


# MCP 工具描述(asset_map_tools.TOOLS 同形)
TOOLS = [
    {"name": "ctx.search", "desc": "跨会话检索历史上下文(单元+消息+备案文档；返回 Markdown 命中列表)",
     "args": {"query": "关键词", "type": "单元类型(tool_call/artifact/decision/session_summary/execution_report)",
              "conversation": "限定会话 id", "limit": "条数", "project": "项目 id"}},
    {"name": "ctx.get", "desc": "会话上下文包：摘要+关键单元+备案文档(MD)",
     "args": {"conversation": "会话 id", "project": "项目 id"}},
    {"name": "ctx.summarize", "desc": "生成/刷新会话摘要(标题+结论/决策/待办)",
     "args": {"conversation": "会话 id"}},
]

_ARTIFACT_TOOLS = {"req.propose", "contract.propose", "convention.propose"}


# ── 写入侧 ────────────────────────────────────────────────

def _project_of(conv_id: str) -> str:
    conv = _store().ConversationsStore.get(conv_id) or {}
    return conv.get("projectId") or ""


def _conv_tags(conv: dict) -> dict:
    tags = conv.get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (TypeError, ValueError):
            tags = None
    if not isinstance(tags, dict):
        tags = {}
    return {"modules": tags.get("modules") or [], "groups": tags.get("groups") or []}


def record_tool_call(conv_id: str, name: str, args: Dict[str, Any],
                     ok: bool, summary: str) -> None:
    """对话中的工具轨迹 → 单元；产物类工具另记 artifact 单元(importance=1)。"""
    if not conv_id:
        return
    try:
        project = _project_of(conv_id)
        _store().ContextUnitsStore.create({
            "conversationId": conv_id, "projectId": project,
            "type": "tool_call",
            "title": f"{name}({'ok' if ok else 'error'})",
            "content": f"参数: {json.dumps(args, ensure_ascii=False)[:600]}\n\n结果: {summary[:1200]}",
            "refs": {}, "importance": 0,
        })
        if ok and name in _ARTIFACT_TOOLS:
            _store().ContextUnitsStore.create({
                "conversationId": conv_id, "projectId": project,
                "type": "artifact",
                "title": f"产物: {name}",
                "content": summary[:2000],
                "refs": {}, "importance": 1,
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("[ctx-registry] 工具单元写入失败: %s", e)



def record_turn_error(conv_id: str, detail: str,
                      project_id: str = "") -> None:
    """回合级错误(turnError) → error 单元——错误历史进入检索面(ctx.search 可捞)。

    与消息卡并行落库: 卡面向用户呈现, 单元面向 agent 检索/后续提炼(P1 distill 材料)。
    """
    if not conv_id:
        return
    try:
        _store().ContextUnitsStore.create({
            "conversationId": conv_id, "projectId": project_id,
            "type": "error",
            "title": f"回合错误: {detail.strip()[:60]}",
            "content": detail[:2000],
            "refs": {}, "importance": 1,
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("[ctx-registry] error 单元写入失败: %s", e)


def _conv_meta(conv: dict) -> dict:
    """会话 meta 字段(JSON) → dict。"""
    raw = conv.get("meta")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = {}
    return raw if isinstance(raw, dict) else {}


_TITLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "不超过 24 字的会话标题"},
        "summary": {"type": "string", "description": "不超过 120 字的会话摘要(结论/决策/待办)"},
    },
    "required": ["title", "summary"],
}


def summarize_conversation(conv_id: str, force: bool = False) -> Optional[dict]:
    """生成/刷新会话标题与摘要 → 落库 + session_summary 单元。返回更新后会话。

    标题保护: 用户手动改过标题(meta.titleEdited)后, 非 force(系统自动摘要)
    不再覆盖标题(仅刷新摘要); force=1(用户显式点击自动摘要)总是重新生成。
    """
    conv = _store().ConversationsStore.get(conv_id)
    if not conv:
        return None
    meta = _conv_meta(conv)
    title_edited = bool(meta.get("titleEdited"))
    msgs = _store().ConversationsStore.messages(conv_id, limit=30)
    transcript = "\n".join(
        f"[{'用户' if m.get('role') == 'user' else '助手'}] {(m.get('content') or '').strip()[:400]}"
        for m in msgs if (m.get("content") or "").strip()
    )
    title, summary = "", ""
    need_title = force or not title_edited
    if transcript:
        from ..reflection.repair import summarize_task
        from ...arch_routes.agent_roles import load_light_tasks_cfg
        from ..governance.light_tasks import resolve_light_task_model
        out = summarize_task(
            task_id="conv_summary",
            system="你是会话归档助手。根据对话记录生成简短标题与摘要，只输出结构化结果。",
            material=f"对话记录:\n{transcript[:6000]}",
            mode="structured", output_schema=_TITLE_SCHEMA,
            model_id=resolve_light_task_model("summary", load_light_tasks_cfg()),
            parse=lambda r: r.get("output") if isinstance(r.get("output"), dict) else None)
        if out["ok"] and isinstance(out["output"], dict):
            if need_title:
                title = str(out["output"].get("title") or "").strip()[:48]
            summary = str(out["output"].get("summary") or "").strip()[:400]
    if need_title:
        if not title:
            first_user = next((m.get("content") or "" for m in msgs if m.get("role") == "user"), "")
            title = first_user.strip().replace("\n", " ")[:24] or (conv.get("title") or "会话")
    else:
        # 手改标题保护: 系统自动摘要只刷新摘要, 标题维持用户所改
        title = conv.get("title") or ""
    if not summary:
        summary = (conv.get("summary") or "").strip()
    # 显式自动摘要生成的标题视同已定稿, 后续系统自动不再覆盖
    if force and title:
        meta["titleEdited"] = True
    updated = _store().ConversationsStore.update(conv_id, {"title": title, "summary": summary, "meta": meta})
    # 摘要单元(高优先级；refs 继承会话 tags)
    try:
        tags = _conv_tags(conv)
        _store().ContextUnitsStore.create({
            "conversationId": conv_id, "projectId": conv.get("projectId") or "",
            "type": "session_summary",
            "title": f"会话摘要: {title}",
            "content": summary or "(空摘要)",
            "refs": {"modules": tags.get("modules") or []},
            "importance": 1,
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("[ctx-registry] 摘要单元写入失败: %s", e)
    return updated or conv


# ── 读取侧(ctx.* → Markdown) ──────────────────────────────

def _fmt_ts(ts) -> str:
    try:
        import time as _t
        return _t.strftime("%m-%d %H:%M", _t.localtime((int(ts) or 0) / 1000))
    except Exception:  # noqa: BLE001
        return "-"


def ctx_search(query: str, type_: str = "", conversation_id: str = "",
               project_id: str = "", limit: int = 20) -> str:
    """跨会话检索单元+消息+备案文档 → Markdown 命中列表(带溯源)。

    P2 词典检索侧映射: 查询词经 glossary(term/alias)扩展同义/规范词,
    合并检索(命中带 via 溯源)——外围独立循环, 不涉主模型上下文。
    """
    if not (query or "").strip():
        return "# ctx.search\n\nquery 为空。用法: ctx.search(query=\"支付\")"

    def _gather(qs: str, per_limit: int) -> List[dict]:
        hits: List[dict] = []
        # 1) 上下文单元
        try:
            for u in _store().ContextUnitsStore.search(qs, type_=type_ or None,
                                                       conversation_id=conversation_id or None,
                                                       project_id=project_id or None,
                                                       limit=per_limit):
                hits.append({"src": "unit", "type": u.get("type"), "title": u.get("title") or "-",
                             "excerpt": (u.get("content") or "")[:200], "conv": u.get("conversationId") or "",
                             "ts": u.get("createdAt"), "importance": u.get("importance") or 0})
        except Exception as e:  # noqa: BLE001
            logger.warning("[ctx.search] units: %s", e)

        # 2) 会话消息(不限定类型；按内容命中)
        if not type_:
            try:
                rows = _store().ConversationsStore.summaries(limit=200)
            except Exception:
                rows = []
            for c in rows:
                if conversation_id and c.get("id") != conversation_id:
                    continue
                for m in _store().ConversationsStore.messages(c.get("id") or "", limit=50):
                    content = (m.get("content") or "")
                    if qs.lower() in content.lower():
                        hits.append({"src": "message", "type": f"消息/{c.get('kind')}",
                                     "title": c.get("title") or "-",
                                     "excerpt": content[:200], "conv": c.get("id"),
                                     "ts": m.get("time"), "importance": 0})
                        if len(hits) >= per_limit * 2:
                            break
                if len(hits) >= per_limit * 2:
                    break

        # 3) 备案文档
        if not type_:
            try:
                for d in _store().DocsStore.all(project_id=project_id or None, limit=100):
                    blob = f"{d.get('title') or ''}\n{d.get('contentMd') or ''}"
                    if qs.lower() in blob.lower():
                        hits.append({"src": "doc", "type": f"备案/{d.get('type')}",
                                     "title": d.get("title") or "-",
                                     "excerpt": (d.get("contentMd") or "")[:200],
                                     "conv": d.get("conversationId") or "",
                                     "ts": d.get("updatedAt"), "importance": 1})
            except Exception as e:  # noqa: BLE001
                logger.warning("[ctx.search] docs: %s", e)
        return hits

    hits = _gather(query.strip(), limit)
    # 词典扩展(项目作用域; 无词典/无 pid 零开销)
    extras: List[str] = []
    try:
        pid = project_id
        if not pid and conversation_id:
            pid = (_store().ConversationsStore.get(conversation_id) or {}).get("projectId") or ""
        if pid:
            from .glossary_map import expand_query
            extras = expand_query(query, _store().GlossaryStore.list(pid, limit=500))
    except Exception as e:  # noqa: BLE001 — 词典映射失败不阻断检索
        logger.warning("[ctx.search] glossary 扩展失败: %s", e)
    if extras:
        seen = {(h.get("src"), h.get("conv"), h.get("title"), h.get("ts"))
                for h in hits}
        for extra in extras:
            for h in _gather(extra, max(3, limit // 3)):
                key = (h.get("src"), h.get("conv"), h.get("title"), h.get("ts"))
                if key in seen:
                    continue
                seen.add(key)
                h["via"] = extra
                hits.append(h)

    hits.sort(key=lambda h: (-(h.get("importance") or 0), -(int(h.get("ts") or 0))))
    hits = hits[:limit]
    out = [f"# ctx.search「{query.strip()}」({len(hits)} 命中)", ""]
    if extras:
        out.append(f"词典扩展: {', '.join(extras)}")
        out.append("")
    if not hits:
        out.append("无命中。")
    for h in hits:
        via = f" · 经「{h['via']}」扩展命中" if h.get("via") else ""
        out.append(f"## [{h['type']}] {h['title']}")
        out.append(f"会话 `{h['conv'] or '-'}` · {_fmt_ts(h.get('ts'))} · 来源 {h['src']}{via}")
        out.append("")
        out.append((h["excerpt"] or "").strip().replace("\n", " ")[:180])
        out.append("")
    return "\n".join(out)


def ctx_get(conversation_id: str) -> str:
    """会话上下文包：基础信息+摘要+关键单元(高优先级在前)+备案文档。"""
    conv = _store().ConversationsStore.get(conversation_id)
    if not conv:
        return f"# ctx.get\n\n会话 `{conversation_id}` 不存在。"
    tags = _conv_tags(conv)
    units = _store().ContextUnitsStore.all(conversation_id=conversation_id, limit=50)
    units.sort(key=lambda u: (-(u.get("importance") or 0), -(u.get("createdAt") or 0)))
    docs = _store().DocsStore.all(conversation_id=conversation_id, limit=20)
    out = [
        f"# 会话上下文包 `{conversation_id}`",
        f"- 标题: {conv.get('title') or '-'} · 类型: {conv.get('kind')} · 状态: {conv.get('status')}",
        f"- 模块: {', '.join(tags['modules']) or '-'} · 分组: {', '.join(tags['groups']) or '-'}",
        "",
        "## 摘要",
        (conv.get("summary") or "(未生成——可 ctx.summarize)").strip(),
        "",
        f"## 关键单元({len(units)})",
    ]
    if not units:
        out.append("(无)")
    for u in units[:15]:
        out.append(f"- **[{u.get('type')}] {u.get('title') or '-'}** · {_fmt_ts(u.get('createdAt'))}")
        body = (u.get("content") or "").strip()
        if body:
            out.append(f"  > {body[:160].replace(chr(10), ' ')}")
    out.append("")
    out.append(f"## 备案文档({len(docs)})")
    if not docs:
        out.append("(无)")
    for d in docs:
        out.append(f"- [{d.get('type')}] {d.get('title') or '-'} · {_fmt_ts(d.get('updatedAt'))}")
    return "\n".join(out)


def ctx_summarize(conversation_id: str) -> str:
    conv = summarize_conversation(conversation_id)
    if not conv:
        return f"# ctx.summarize\n\n会话 `{conversation_id}` 不存在。"
    return f"# ctx.summarize\n\n- 标题: {conv.get('title')}\n- 摘要: {conv.get('summary') or '(空)'}"


def run_tool(name: str, args: dict) -> str:
    """MCP 统一入口(map.* 同款)。"""
    handlers = {
        "ctx.search": lambda: ctx_search(args.get("query") or "",
                                         type_=args.get("type") or "",
                                         conversation_id=args.get("conversation") or "",
                                         project_id=args.get("project") or "",
                                         limit=int(args.get("limit") or 20)),
        "ctx.get": lambda: ctx_get(args.get("conversation") or ""),
        "ctx.summarize": lambda: ctx_summarize(args.get("conversation") or ""),
    }
    fn = handlers.get(name)
    if not fn:
        return f"未知工具: {name}（可用: {', '.join(handlers)}）"
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return f"工具执行失败: {e}"


# ── 会话 agent 工具面(register_architect_tool) ────────────

def register_chat_tools() -> None:
    """注册 ctx.* 为会话 agent 工具(幂等)。"""
    from ...agent.tools.req_agent import register_architect_tool

    @register_architect_tool(
        "ctx.search", "跨会话检索历史上下文(单元/消息/备案文档)",
        params_doc='{"query": "检索关键词(必填)", "type": "可选过滤: unit|message|doc", '
                   '"conversation": "可选限定会话 id", "limit": "可选(默认20)"}')
    def _ctx_search(query: str, type: str = "", conversation: str = "",  # noqa: A002
                    limit: int = 20, project: Optional[str] = None, root: Optional[str] = None) -> dict:
        return {"markdown": ctx_search(query, type_=type, conversation_id=conversation,
                                       project_id=project or "", limit=limit)}

    @register_architect_tool(
        "ctx.get", "读取会话上下文包(摘要+关键单元+备案文档)",
        params_doc='{"conversation": "会话 id(必填)"}')
    def _ctx_get(conversation: str, project: Optional[str] = None,
                 root: Optional[str] = None) -> dict:
        return {"markdown": ctx_get(conversation)}

    @register_architect_tool(
        "ctx.summarize", "生成/刷新会话摘要",
        params_doc='{"conversation": "会话 id(必填)"}')
    def _ctx_summarize(conversation: str, project: Optional[str] = None,
                       root: Optional[str] = None) -> dict:
        return {"markdown": ctx_summarize(conversation)}


# ── P3: probe(方案草图) + 前置上下文构造(Context Assembly) ──

def run_probe(conv_id: str, instruction: str, root: str,
              executor_id: str = "", files: Optional[list] = None,
              base_commit: str = "", timeout_s: int = 600) -> dict:
    """调 runner /api/probe(worktree 方案草图) → 产物落 artifact 单元。

    probe 语义: 只读分析+伪 diff 表达方案；不建分支不提交(与 execute 分支协议互斥)。
    """
    import httpx
    import os as _os

    if not (instruction or "").strip():
        return {"error": "instruction 为空"}
    payload = {
        "root": root,
        "instruction": instruction.strip(),
        "executorId": executor_id or "",
        "files": files or [],
        "baseCommit": base_commit or "HEAD",
        "timeoutS": timeout_s,
    }
    # 环境变量调用时覆盖(get_runner 单例可能缓存旧 base_url；测试/多 runner 场景)
    base = (_os.environ.get("RUNNER_BASE_URL") or "http://127.0.0.1:3458").rstrip("/")
    try:
        with httpx.Client(timeout=timeout_s + 60) as client:
            r = client.post(f"{base}/api/probe", json=payload)
            result = r.json() if r.status_code == 200 else {"error": f"runner {r.status_code}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"runner 不可达: {e}"}
    if result.get("ok"):
        changed = result.get("changedFiles") or []
        diff = (result.get("diff") or "")[:8000]
        try:
            _store().ContextUnitsStore.create({
                "conversationId": conv_id, "projectId": _project_of(conv_id),
                "type": "artifact",
                "title": f"方案草图: {instruction.strip()[:40]}",
                "content": (f"{result.get('summary') or ''}\n\n"
                            f"变更文件: {', '.join(changed) or '-'}\n\n```diff\n{diff}\n```"),
                "refs": {"files": changed[:50]},
                "importance": 1,
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("[ctx-registry] probe 产物单元写入失败: %s", e)
    return result


# dossier 装配(裁决3)已拆至 .dossier(P4); 此处 re-export 保持原名可用
from .dossier import _DOSSIER_BUDGET, _clip, assemble_dossier  # noqa: F401


def register_probe_tool() -> None:
    """注册 probe.run 会话 agent 工具(L2 方案草图: 对话中调 coding agent)。"""
    from ...agent.tools.req_agent import register_architect_tool

    @register_architect_tool(
        "probe.run",
        "方案草图(probe): 调 coding agent 在 git worktree 快照上产出改动思路与伪 diff；"
        "讨论方案可行性/让用户预览改动时使用；不产生真实分支/提交",
        params_doc='{"instruction": "方案草图任务描述(必填: 目标+涉及文件+期望产出)", '
                   '"files": "可选逗号/换行分隔的相关文件清单", '
                   '"executorId": "可选执行器 id", "timeoutS": "可选超时秒数(默认600)"}')
    def _probe_run(instruction: str, files: str = "", executorId: str = "",
                   timeoutS: int = 600, project: Optional[str] = None,
                   root: Optional[str] = None) -> dict:
        from ... import ctx as _ctx
        from ...arch_routes.project import resolve_project
        conv_id = _ctx.get_conv() or ""
        try:
            proj = resolve_project(root, project)
        except Exception:
            proj = None
        wt_root = root or ((proj or {}).get("rootPath") or "")
        if not wt_root:
            return {"error": "无法解析项目根(root/project)"}
        # files 兼容逗号/中文逗号/换行分隔(_coerce_args 会把模型传的数组收敛为换行拼接)
        file_list = [f.strip() for f in re.split(r"[,，\n]", (files or "")) if f.strip()]
        result = run_probe(conv_id, instruction, wt_root,
                           executor_id=executorId, files=file_list,
                           timeout_s=int(timeoutS))
        if result.get("error"):
            return result
        changed = result.get("changedFiles") or []
        diff = _clip(result.get("diff") or "", 3000)
        md = (f"# 方案草图(probe)\n\n- 状态: {result.get('status')}\n"
              f"- {result.get('summary') or ''}\n"
              f"- 变更文件: {', '.join(changed) or '-'}\n\n```diff\n{diff}\n```")
        return {"markdown": md}


# ── WS3: coding 任务通道(plan 只读方案 / execute 正式执行) ─────────────
