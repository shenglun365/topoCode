"""AGENTS.md 规约文件面 REST/工具(纯文件模式, 2610 定型修订)。

真相源与缓存同步见 sem/rules_file(章节解析契约/惰性同步/采纳 append);
本模块: 读/写(乐观锁) REST + agents.md.init 初稿工具(/init 模式——
Codex/Claude Code/opencode 三家共同语义: 无文件生成初稿, 已有文件给
改进建议不盲改)。指纹定界/rules 目录合并链(agents_md_chain)已随
纯文件模式退役; 旧 .topo/rules 内容经 init 一次性迁移并入。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter
from fastapi import Request

from ..common import err, ok

logger = logging.getLogger("arch_routes.agents_md")

router = APIRouter()

_DRAFT_HEADER = (
    "# AGENTS.md — {name}\n\n"
    "> 项目规约唯一真相源(人治 markdown, git 版本化)。编码代理开工前必读。\n"
    "> 建议保持精简(<200 行): 约束性信息优先, 参考/概览性内容不进。\n")


def _proj_of(root: str, project: Optional[str]) -> dict:
    from .. import store
    rows = store.ProjectsStore.all() or []
    for r in rows:
        if project and r.get("id") == project:
            return r
        if not project and os.path.normpath(str(r.get("root_path") or "")) \
                == os.path.normpath(root or ""):
            return r
    return {}


def init_agents_md(root: str, project: Optional[str] = None) -> Dict[str, Any]:
    """/init 模式: 无文件→初稿落盘(store 缓存+.topo/rules 迁移); 有→建议。"""
    from ..sem.rules_file import agents_md_path, ensure_rules_synced, parse_agents_md
    if not root or not os.path.isdir(root):
        return {"ok": False, "error": f"root 不可用: {root!r}"}
    path = agents_md_path(root)
    proj = _proj_of(root, project)
    pid = proj.get("id") or project or ""

    if os.path.isfile(path):
        content = open(path, encoding="utf-8").read()
        parsed = parse_agents_md(content)
        suggestions = []
        if "## 命名规约" not in content:
            suggestions.append("缺 `## 命名规约` 章节(引擎消费契约位)")
        if "## 术语表" not in content:
            suggestions.append("缺 `## 术语表` 章节(引擎消费契约位)")
        n_lines = len(content.splitlines())
        if n_lines > 200:
            suggestions.append(f"当前 {n_lines} 行, 超过 200 行建议精简"
                               "(长文件降低遵从度——Claude Code 同款建议)")
        if parsed.get("skipped"):
            suggestions.append(f"{parsed['skipped']} 行不可解析(命名规约须行式"
                               " `- [场景] 规则`, 术语表须三列表格)")
        ensure_rules_synced(root, pid)
        return {"ok": True, "created": False, "lines": n_lines,
                "conventions": len(parsed["conventions"]),
                "glossary": len(parsed["glossary"]),
                "suggestions": suggestions or ["结构完好, 无必改项"]}

    from .. import store
    parts = [_DRAFT_HEADER.format(name=proj.get("name") or os.path.basename(root))]
    convs = store.NamingConventionStore.list(pid, limit=200) if pid else []
    parts.append("## 命名规约\n"
                 + ("\n".join(f"- [{' '.join(c.get('scenarios') or [])}] "
                              f"{c.get('ruleText')}" for c in convs)
                    or "- (待补充: 一行一条, `- [场景] 规则文本`)"))
    glos = store.GlossaryStore.list(pid, limit=200) if pid else []
    parts.append("## 术语表\n\n| 术语 | 别名 | 含义 |\n|---|---|---|\n"
                 + ("\n".join(f"| {g.get('term')} | "
                              f"{'，'.join(g.get('alias') or []) or '—'} | "
                              f"{g.get('definition') or ''} |" for g in glos)
                    or "| (待补充) | — | |"))
    parts.append("## 架构约束\n\n- (待补充: 分层/依赖方向/组件边界等人治约束)")
    # 一次性迁移: .topo/rules/*.md 并入(旧统一编辑器规则目录, 纯文件模式退役面)
    rules_dir = os.path.join(root, ".topo", "rules")
    if os.path.isdir(rules_dir):
        for name in sorted(os.listdir(rules_dir)):
            if name.endswith(".md"):
                body = open(os.path.join(rules_dir, name),
                            encoding="utf-8").read().strip()
                if body:
                    parts.append(f"## 项目规则·{name[:-3]}\n\n{body}")
    content = "\n\n".join(parts).rstrip() + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    ensure_rules_synced(root, pid, force=True)
    return {"ok": True, "created": True, "lines": len(content.splitlines()),
            "conventions": len(convs), "glossary": len(glos),
            "suggestions": ["初稿已生成, 请人工审阅后提交 git"]}


@router.get("/arch/agents-md")
async def api_agents_md_get(root: str = "", project: str = ""):
    """读 AGENTS.md(顺带惰性同步引擎缓存)。"""
    if not root or not os.path.isdir(root):
        return err(400, "root 不可用")
    from ..sem.rules_file import ensure_rules_synced, read_agents_md
    r = read_agents_md(root)
    if r["exists"]:
        ensure_rules_synced(root, project or _proj_of(root, project or None).get("id") or "")
    return ok(r)


@router.put("/arch/agents-md")
async def api_agents_md_put(request: Request):
    """写 AGENTS.md {root, content, baseHash, project}(乐观锁; 写后强制同步)。"""
    body = await request.json() or {}
    root = str(body.get("root") or "")
    content = str(body.get("content") or "")
    if not root or not os.path.isdir(root):
        return err(400, "root 不可用")
    if not content.strip():
        return err(400, "内容为空")
    from ..sem.rules_file import ensure_rules_synced, write_agents_md
    res = write_agents_md(root, content, str(body.get("baseHash") or ""))
    if res.get("conflict"):
        return JSONResponse(status_code=409, content={
            "code": 409, "message": "文件已被外部修改, 请重读合并",
            "data": {"currentHash": res.get("current_hash")}})
    pid = str(body.get("project") or "") or _proj_of(root, None).get("id") or ""
    ensure_rules_synced(root, pid, force=True)
    return ok(res)


@router.post("/arch/agents-md/init")
async def api_agents_md_init(request: Request):
    """初稿生成/改进建议(/init 模式)。"""
    body = await request.json() or {}
    res = init_agents_md(str(body.get("root") or ""),
                         str(body.get("project") or "") or None)
    if not res.get("ok"):
        return err(res.get("error") or "init failed")
    return ok(res)


from fastapi.responses import JSONResponse  # noqa: E402

from ..agent.tools.req_agent import register_architect_tool  # noqa: E402


@register_architect_tool(
    "agents.md.init",
    "AGENTS.md 初稿生成/体检(/init 模式): 无文件→从命名规约/术语表缓存+.topo/rules"
    " 生成初稿落盘; 已有文件→只给改进建议(缺失章节/超长/坏行), 绝不盲改。"
    "用户要求 初始化/生成 AGENTS.md 或「建立项目规约」时调用。"
    "AGENTS.md 是项目规约唯一真相源(纯人治 markdown)——修改内容应引导用户直接编辑。",
)
def tool_agents_md_init(root: Optional[str] = None,
                        project: Optional[str] = None) -> Dict[str, Any]:
    return init_agents_md(root or "", project or None)
