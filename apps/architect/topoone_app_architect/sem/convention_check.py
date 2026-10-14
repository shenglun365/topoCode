"""规约违约检查 — agent 通道(structured LLM + 机器取证, 零硬编码规则)。

设计纪律:
- NamingConvention.ruleText 是自然语言(供 prompt), 因此**不存在**机器可执行
  规则语义 — 检查器绝不发明正则/关键词规则(硬编码补丁的典型来源)。
- 裁决 = LLM structured 输出; **取证 = 机器**(工作区符号快照, KB
  workspace.snapshot 的稳定 ID/行号), 每条违约必须带真实符号证据。
- 无状态: 按需检查, 结果不落库(调用方决定展示/回写策略)。

复用: changed_files(基线口径) + KB workspace.snapshot(A1 稳定 ID) +
agent.cognition.llm.llm_sync(structured)。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_SYMBOLS = 400        # 送检符号上限(防上下文爆炸; 按文件序截断)
_MAX_RULES = 30           # 送检规约上限

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "violations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ruleId": {"type": "string"},
                    "symbol": {"type": "string"},
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "evidence": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "severity": {"type": "string", "enum": ["error", "warn", "info"]},
                },
                "required": ["ruleId", "symbol", "file", "evidence"],
            },
        },
        "checkedSymbols": {"type": "integer"},
        "notes": {"type": "string"},
    },
    "required": ["violations", "checkedSymbols"],
}


def _gather_symbols(root: Optional[str], project: Optional[str],
                    base: str, files: Optional[List[str]]) -> Dict[str, object]:
    """送检符号集: 显式 files 或 基线..工作区 变更文件的符号(KB 快照)。"""
    from .. import ctx
    from ..kb_gateway import call_kb
    from .paths import resolve_root
    from .symbols import _resolve_core_pid

    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"error": "项目根未解析"}
    pid = _resolve_core_pid(rid)
    if not pid:
        return {"error": "KB 注册表无此仓库对应项目，无法获取符号(请先建立基线)"}

    target_files = [str(f) for f in (files or []) if f]
    if not target_files:
        from .engine import changed_files
        ch = changed_files(rid, project or ctx.get_project()) or {}
        target_files = sorted(set(ch.get("added") or []) | set(ch.get("modified") or []))

    res = call_kb('workspace.snapshot', project_id=pid,
                  files=target_files or None, base=base or "")
    if res is None:
        return {"error": "KB 服务不可达(workspace.snapshot 失败)"}
    nodes = res.get("nodes") or []
    if len(nodes) > _MAX_SYMBOLS:
        nodes = nodes[:_MAX_SYMBOLS]
    return {"symbols": nodes, "files": target_files, "base": res.get("base") or "",
            "truncated": bool(res.get("truncated"))}


def convention_check(root: Optional[str], project: Optional[str],
                     base: str = "", files: Optional[List[str]] = None) -> dict:
    """开发规约违约检查主入口(路由转 400 on error)。"""
    from .rules_file import ensure_rules_synced
    if root:
        try:
            ensure_rules_synced(root, project or "")
        except Exception:  # noqa: BLE001 — 同步失败不阻塞检查(缓存照旧)
            pass
    from ..store import NamingConventionStore
    from .paths import project_id_for

    pid = project_id_for(root, project)
    if not pid:
        return {"error": "项目未解析"}
    rules = [r for r in NamingConventionStore.list(pid, status="active")
             if (r.get("ruleText") or "").strip()][:_MAX_RULES]
    if not rules:
        return {"error": "无 active 命名规约——请先在项目规约页定义规则"}

    gathered = _gather_symbols(root, project, base, files)
    if gathered.get("error"):
        return gathered
    symbols: list = gathered["symbols"]
    if not symbols:
        return {"violations": [], "checkedSymbols": 0,
                "message": "送检范围内无变更符号", "rules": len(rules),
                "files": gathered.get("files") or []}

    # ── 机器取证 → LLM 裁决(structured): 规则语义由模型读, 证据由代码给 ──
    from ..agent.cognition.llm import llm_sync
    rule_brief = "\n".join(
        f'- id={r["id"]}: {r["ruleText"]}' for r in rules)
    sym_brief = "\n".join(
        f'- {s["name"]} ({s["kind"]}, file={s["file"]}, L{s["startLine"]}-L{s["endLine"]})'
        for s in symbols)
    messages = [
        {"role": "system", "content":
            "你是代码命名规约审查员。依据给定规约(自然语言)逐条检查符号清单。"
            "只报告有真实证据的违约(证据必须引用符号名/文件/行号)；"
            "不确定的不要报。checkedSymbols 填实际检查的符号数。"},
        {"role": "user", "content":
            f"## 命名规约\n{rule_brief}\n\n## 待检符号\n{sym_brief}"},
    ]
    res = llm_sync(messages, mode="structured", output_schema=_OUTPUT_SCHEMA)
    if res is None:
        return {"error": "LLM 不可达，无法执行规约检查(请检查模型配置)"}
    out = res.get("output")
    if not isinstance(out, dict):
        return {"error": "LLM 结构化输出为空(裁决失败)",
                "raw": (res.get("content") or "")[:400]}
    valid_rule_ids = {r["id"] for r in rules}
    valid_files = set(gathered.get("files") or [])
    violations = []
    for v in out.get("violations") or []:
        if not isinstance(v, dict) or v.get("ruleId") not in valid_rule_ids:
            continue
        # 证据防伪: symbol/file 必须来自送检集合(模型不得虚构对象)
        if valid_files and v.get("file") not in valid_files:
            continue
        violations.append({
            "ruleId": v.get("ruleId"),
            "symbol": str(v.get("symbol") or "")[:200],
            "file": v.get("file"),
            "line": int(v.get("line") or 0),
            "evidence": str(v.get("evidence") or "")[:500],
            "suggestion": str(v.get("suggestion") or "")[:300],
            "severity": v.get("severity") or "warn",
        })
    return {
        "violations": violations,
        "checkedSymbols": int(out.get("checkedSymbols") or len(symbols)),
        "rules": len(rules),
        "files": gathered.get("files") or [],
        "base": gathered.get("base") or "",
        "truncated": gathered.get("truncated") or len(symbols) >= _MAX_SYMBOLS,
        "notes": str(out.get("notes") or "")[:300],
    }
