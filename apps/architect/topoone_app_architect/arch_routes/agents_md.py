"""项目级 AGENTS.md 生成/维护(用户需求 2026-09-26: architect 主 agent 具备
生成、更新、维护 AGENTS.md 的能力)。

- 内容源全部复用既有能力单源: 规约全集(sem.map_tools.tool_rules——KB 规约文档
  +命名规约+词汇表) + 资产统计(SemanticAssetsStore)。不新建知识管道。
- 语义: 用户/主 agent 显式触发(问什么答什么——不自动写仓库); 幂等 sync
  (内容无变化不动文件)。
- 执行器侧读取能力已内建(任务下发按 caps 映射 AGENTS.md/规则目录——见
  exec_bridge._build_workspace_files); 本模块补的是 repo 根常驻文件的生成/刷新。
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


def build_project_agents_md(root: str, project: Optional[str] = None) -> str:
    """组装项目级 AGENTS.md(规约全集 + 资产概览)。纯组装, 不落盘。"""
    from ..sem.map_tools import tool_overview, tool_rules
    from .. import store as _store

    proj = None
    try:
        rows = _store.ProjectsStore.all() or []
        for r in rows:
            if project and r.get("id") == project:
                proj = r
                break
            if not project and os.path.normpath(str(r.get("root_path") or "")) \
                    == os.path.normpath(root):
                proj = r
                break
    except Exception:  # noqa: BLE001
        proj = None
    pid = (proj or {}).get("id") or project or ""

    name = (proj or {}).get("name") or os.path.basename(root or "") or "project"
    out = [f"# AGENTS.md — {name}",
           "",
           "> 本文件由 architect 维护(源: 自管编码规约/词汇表 + .topo/rules 项目规则)。"
           "编码代理开工前必读；本文件只含约束性信息，参考/概览性内容不进入"
           "(规约定型 2610)；冲突时以人工规则 > 用户显式 > 派生约束。",
           ""]

    rules = ""
    try:
        rules = tool_rules(project or None) or ""
        # 去掉 tool_rules 自身 H1, 标题并入本文档结构
        lines = rules.split("\n")
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        rules = "\n".join(lines).strip()
    except Exception as e:  # noqa: BLE001
        rules = f"(规约集合不可用: {e})"
    out.append(rules)
    return "\n".join(out).rstrip() + "\n"


def sync_agents_md(root: str, project: Optional[str] = None,
                   force: bool = False) -> Dict[str, Any]:
    """幂等落盘 repo 根 AGENTS.md。返回 {path, changed, bytes}。

    W4(D-2 方案 A): 生成段指纹定界 + .topo/rules/ 追加; 定界段被手改 →
    manual_edit_conflict(不静默覆盖, force=True 才覆盖)——见 agents_md_chain。
    """
    if not root or not os.path.isdir(root):
        return {"ok": False, "error": f"root 不可用: {root!r}"}
    from .agents_md_chain import detect_manual_edit, merge_agents_md
    md = merge_agents_md(build_project_agents_md(root, project), root)
    path = os.path.join(root, "AGENTS.md")
    try:
        old = open(path, "r", encoding="utf-8").read() if os.path.exists(path) else None
    except Exception:
        old = None
    if old == md:
        return {"ok": True, "path": path, "changed": False,
                "bytes": len(md.encode("utf-8"))}
    chk = detect_manual_edit(old, md)
    if chk["status"] == "conflict" and not force:
        return {"ok": True, "path": path, "changed": False,
                "status": "manual_edit_conflict",
                "manual_excerpt": chk.get("manual_excerpt"),
                "options": ["force_overwrite", "cancel"]}
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    return {"ok": True, "path": path, "changed": True,
            "bytes": len(md.encode("utf-8"))}


@router.post("/arch/agents-md/sync")
async def api_sync_agents_md(request: Request):
    """生成/刷新 repo 根 AGENTS.md(显式触发; 幂等; force 处置手改冲突)。"""
    try:
        body = await request.json() or {}
    except Exception:  # noqa: BLE001
        body = {}
    root = str(body.get("root") or "")
    project = str(body.get("project") or "")
    force = bool(body.get("force"))
    res = sync_agents_md(root, project or None, force=force)
    if not res.get("ok"):
        return err(res.get("error") or "sync failed")
    return ok(res)


from ..agent.tools.req_agent import register_architect_tool  # noqa: E402


@register_architect_tool(
    "agents.md.sync",
    "生成/刷新项目根 AGENTS.md(规约全集+命名规约+词汇表+资产概览+项目规则目录,"
    "幂等)。用户要求 维护/更新/生成 AGENTS.md 或「把规约固化给执行器」时调用。"
    "写用户仓库属显式动作——仅用户表达该意图时调用。"
    "返回 manual_edit_conflict=生成段被手改: 询问用户是否覆盖, 确认后带 force=true 重调。",
)
def tool_agents_md_sync(root: Optional[str] = None,
                        project: Optional[str] = None,
                        force: bool = False) -> Dict[str, Any]:
    return sync_agents_md(root or "", project or None, force=force)
