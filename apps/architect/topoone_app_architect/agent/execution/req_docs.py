"""需求文档投影(cv-272)——规约/设计/验收/边界 → `.topo/docs/{reqId}/` 四件。

设计裁决(用户 2026-09-27):
- DB=真相源; 文档是 dispatch 时投影的运行期快照(无陈旧窗口), 不承担持久文档职责
- 经既有 workspaceFiles 载荷下发(runner 落盘 worktree/融合根), architect 零落盘知识
- 指令瘦身: 契约要点(边界+验收)+文档强指引进指令, 全文进文档(见
  context_pack.render_context_pack_slim)
- 淘汰: runner 作业终态清理其写入的 .topo/docs 文件(融合/隔离两态统一);
  architect confirm 时孤儿清扫(见 dispatch._sweep_orphan_docs)
- 融合模式落盘由 `.git/info/exclude`(runner 幂等注入)保证 git 干净——
  cv-269 教训: 不写 .gitignore(跟踪区变更会撞任务链硬闸)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_DOCS_REL = ".topo/docs"


def docs_dir_rel(rid: str) -> str:
    """会话相对文档目录(载荷 path 前缀)。"""
    return f"{_DOCS_REL}/{rid or 'na'}"


def project_docs(rid: str, boundary_files: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """需求文档投影(纯函数): 规约快照 → workspaceFiles 形状四件。

    DB=真相源(经 store 层读 active 版本快照); 无 rid/快照 → [](调用方回落
    指令全量注入——降级语义, 送达优先)。"""
    if not rid:
        return []
    from ...store.core import RequirementsStore
    active = RequirementsStore.spec_active(rid) or {}
    snap = active.get("snapshot") or {}
    if not snap:
        return []
    req_md = str(snap.get("requirementMd") or "").strip()
    design_md = str(snap.get("designMd") or "").strip()
    allowed_scope = [str(x) for x in (snap.get("allowedScope") or [])]
    scope_out = str(snap.get("scopeOut") or "").strip()
    acceptance = [str(x) for x in (snap.get("acceptance") or [])]
    if not (req_md or design_md or acceptance or allowed_scope):
        return []
    rel = docs_dir_rel(rid)
    boundary = [str(f) for f in (boundary_files or [])]
    parts: List[Dict[str, Any]] = [
        {"path": f"{rel}/SPEC.md", "content": req_md or "(规约未附全文)"},
        {"path": f"{rel}/ACCEPTANCE.md", "content": _acceptance_md(acceptance,
                                                                  scope_out)},
        {"path": f"{rel}/BOUNDARY.md", "content": _boundary_md(allowed_scope,
                                                               boundary)},
    ]
    if design_md:
        parts.insert(1, {"path": f"{rel}/DESIGN.md", "content": design_md})
    return parts


def _acceptance_md(acceptance: List[str], scope_out: str) -> str:
    lines = ["# 验收判据", ""]
    lines += [f"- [ ] {a}" for a in acceptance] or ["- (规约未声明验收判据)"]
    if scope_out:
        lines += ["", "## 明确不做", f"- {scope_out}"]
    return "\n".join(lines)


def _boundary_md(allowed_scope: List[str], boundary_files: List[str]) -> str:
    lines = ["# 修改边界", ""]
    if allowed_scope:
        lines.append("## 声明范围\n" + "\n".join(f"- {s}" for s in allowed_scope))
    if boundary_files:
        lines.append("## 解析边界文件\n"
                     + "\n".join(f"- `{f}`" for f in boundary_files[:50]))
    if not allowed_scope and not boundary_files:
        lines.append("(未声明修改边界——按最小必要范围执行)")
    return "\n".join(lines)
