"""组件快速命名 — agent 工具调用通道(与"文件摘要→社区命名"详细通道并列)。

通道差异(勿合并, 语义不同):
- 详细通道: 预生成文件摘要 → 汇总命名(重前置成本, 产物详尽)。
- 本通道: **零前置摘要** — 直接给模型组件基本信息(文件清单/枢纽符号),
  模型按需多轮工具调用下钻(ast_structure / source_snippet)自主取证命名。
  不提供任何文件语义摘要输入(用户明确要求)。

产物: community_llm_results(edge_type=UNIFIED, comm_lv=L0, source='fast-agent')。
与详细通道同表同键位, 经 analysis_store.bulk_insert_llm_results UPSERT —
name_manual(人工命名)永不被覆盖; 详细通道重跑可覆盖本通道产物(键位同)。

Agent 循环: agent_workflow.tool_calling.agentic_chat(策略自动选择) +
本模块的有界工具执行循环(max_turns 见 config.FAST_NAMING_MAX_TURNS)。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Callable, Dict, List, Optional

from topoone.config import (
    FAST_NAMING_MAX_TURNS, FAST_NAMING_SNIPPET_MAX_LINES,
    FAST_NAMING_SNIPPET_MAX_BYTES, FAST_NAMING_AST_MAX_SYMBOLS,
    FAST_NAMING_TOP_SYMBOLS,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
你是软件架构组件命名专家。你会得到代码库的顶层组件(社区检测结果)清单,
每个组件包含成员文件与枢纽符号。请为每个组件给出:
1. name: 简洁组件名(名词短语, 2~5 个词, 与代码库主要语言一致)
2. summary: 一句话职责概括(不超过 60 字)

你可以调用工具补充证据后再下结论:
- ast_structure(file): 查看某文件的符号结构(类/函数/签名/行号)
- source_snippet(file, start_line, end_line): 查看源码片段

规则:
- 必须基于真实代码证据命名, 禁止臆造;
- 名称要体现组件职责而非文件名堆砌;
- 全部组件命名完成后, 最终回复只输出 JSON 数组(无其他文本):
  [{"commId": "...", "name": "...", "summary": "..."}]"""


# ── 上下文收集(只读) ────────────────────────────────────────

def _gather_components(project_db, task_id: str, comm_lv: str = "L0") -> List[dict]:
    """UNIFIED 指定层级组件: 成员文件(graph_doc.node_list, 与 architecture_model
    同读取口径) + 每组件枢纽符号(导出优先)。"""
    from topoone.engine.community_data import unified_components
    components = unified_components(project_db, task_id, comm_lv)
    if not components:
        return []
    file_map: Dict[str, List[str]] = {}
    try:
        for r in project_db.fetchall(
                "SELECT comm_id, node_list FROM graph_doc "
                "WHERE task_id = ? AND edge_type = 'UNIFIED' AND comm_lv = ?",
                (task_id, comm_lv)):
            nl = r["node_list"]
            files = json.loads(nl) if isinstance(nl, str) else (nl or [])
            file_map[r["comm_id"]] = [str(f) for f in files if f]
    except Exception:
        pass

    out: List[dict] = []
    for c in components:
        cid = c["id"]
        files = file_map.get(cid, [])
        top_symbols = _top_symbols(project_db, task_id, files)
        out.append({"commId": cid, "files": files, "topSymbols": top_symbols})
    return out


def _component_levels(project_db, task_id: str) -> List[str]:
    """UNIFIED 社区层级清单, 按 L0→L1→… 排序(子组件命名需父层先命名)。"""
    try:
        rows = project_db.fetchall(
            "SELECT DISTINCT comm_lv FROM community_hierarchy "
            "WHERE task_id = ? AND edge_type = 'UNIFIED'", (task_id,))
    except Exception:
        return []
    def _lv_key(v: str):
        m = re.match(r"L(\d+)$", v or "")
        return (int(m.group(1)),) if m else (999,)
    return sorted((r["comm_lv"] for r in rows), key=_lv_key)


def _parent_map(project_db, task_id: str) -> Dict[str, str]:
    """comm_id → 父 comm_id(community_hierarchy.parent_comm_id)。"""
    out: Dict[str, str] = {}
    try:
        for r in project_db.fetchall(
                "SELECT comm_id, parent_comm_id FROM community_hierarchy "
                "WHERE task_id = ? AND edge_type = 'UNIFIED' AND parent_comm_id IS NOT NULL",
                (task_id,)):
            out[r["comm_id"]] = r["parent_comm_id"]
    except Exception:
        pass
    return out


def _fixed_comm_ids(project_db, task_id: str, comm_lv: str) -> set:
    """该层级已有命名且不可重命名的 comm_id(name_manual/inherit)。"""
    fixed: set = set()
    try:
        for r in project_db.fetchall(
                "SELECT comm_id FROM community_llm_results "
                "WHERE task_id = ? AND edge_type = 'UNIFIED' AND comm_lv = ? "
                "AND ((name_manual IS NOT NULL AND name_manual != '') "
                "     OR (source = 'inherit' AND name IS NOT NULL AND name != ''))",
                (task_id, comm_lv)):
            fixed.add(r["comm_id"])
    except Exception:
        pass
    return fixed


def _top_symbols(project_db, task_id: str, files: List[str]) -> List[dict]:
    """组件枢纽符号: 成员文件中的导出符号(导出优先, 截 FAST_NAMING_TOP_SYMBOLS)。"""
    if not files:
        return []
    ph = ",".join("?" for _ in files)
    try:
        rows = project_db.fetchall(
            f"SELECT name, kind, file_path, signature FROM graph_node "
            f"WHERE task_id = ? AND file_path IN ({ph}) "
            f"AND kind NOT IN ('file','import') AND is_exported = 1 "
            f"ORDER BY kind LIMIT {int(FAST_NAMING_TOP_SYMBOLS) * 2}",
            (task_id, *files))
    except Exception:
        return []
    syms = [{"name": r["name"], "kind": r["kind"],
             "file": r["file_path"], "signature": (r["signature"] or "")[:120]}
            for r in (rows or [])]
    return syms[:int(FAST_NAMING_TOP_SYMBOLS)]


# ── 工具实现(全部只读, 路径约束在项目根内) ──────────────────

def _safe_join(root: str, rel: str) -> Optional[str]:
    """项目根内安全拼接; 越界(路径逃逸)返回 None。"""
    if not root or not rel:
        return None
    p = os.path.realpath(os.path.join(root, rel))
    if not p.startswith(os.path.realpath(root) + os.sep):
        return None
    return p


def _make_tools(project_db, task_id: str, root: str,
                components: List[dict]) -> tuple:
    """返回 (OpenAI 工具定义, 工具名→实现 分发表)。"""

    def list_components() -> str:
        return json.dumps(components, ensure_ascii=False)

    def ast_structure(file: str) -> str:
        ph = None
        try:
            rows = project_db.fetchall(
                f"SELECT kind, name, qualified_name, start_line, end_line, signature "
                f"FROM graph_node WHERE task_id = ? AND file_path = ? "
                f"AND kind NOT IN ('file','import') "
                f"ORDER BY start_line LIMIT {int(FAST_NAMING_AST_MAX_SYMBOLS)}",
                (task_id, file))
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        if not rows:
            return json.dumps({"error": f"no symbols: {file}"}, ensure_ascii=False)
        return json.dumps([
            {"kind": r["kind"], "name": r["name"],
             "qualifiedName": r["qualified_name"],
             "startLine": r["start_line"], "endLine": r["end_line"],
             "signature": (r["signature"] or "")[:160]}
            for r in rows], ensure_ascii=False)

    def source_snippet(file: str, start_line: int = 1, end_line: int = 0) -> str:
        abs_path = _safe_join(root, file)
        if not abs_path or not os.path.isfile(abs_path):
            return json.dumps({"error": f"file not found: {file}"}, ensure_ascii=False)
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        s = max(1, int(start_line or 1))
        e = min(len(lines), int(end_line or s + int(FAST_NAMING_SNIPPET_MAX_LINES) - 1))
        if e < s:
            e = s
        if e - s + 1 > int(FAST_NAMING_SNIPPET_MAX_LINES):
            e = s + int(FAST_NAMING_SNIPPET_MAX_LINES) - 1
        text = "".join(lines[s - 1:e])
        if len(text.encode("utf-8")) > int(FAST_NAMING_SNIPPET_MAX_BYTES):
            text = text[:int(FAST_NAMING_SNIPPET_MAX_BYTES)]
        return json.dumps({"file": file, "startLine": s, "endLine": e,
                           "content": text}, ensure_ascii=False)

    impl: Dict[str, Callable] = {
        "list_components": list_components,
        "ast_structure": ast_structure,
        "source_snippet": source_snippet,
    }
    schemas = [
        {"type": "function", "function": {
            "name": "list_components",
            "description": "列出全部待命名组件(成员文件与枢纽符号)",
            "parameters": {"type": "object", "properties": {}, "required": []}}},
        {"type": "function", "function": {
            "name": "ast_structure",
            "description": "查看某文件的符号结构(类/函数/签名/行号)",
            "parameters": {"type": "object", "properties": {
                "file": {"type": "string", "description": "组件成员文件路径"}},
                "required": ["file"]}}},
        {"type": "function", "function": {
            "name": "source_snippet",
            "description": "查看源码片段(按行号区间, 有长度上限)",
            "parameters": {"type": "object", "properties": {
                "file": {"type": "string"},
                "start_line": {"type": "integer", "description": "起始行(1-based)"},
                "end_line": {"type": "integer", "description": "结束行(可省略)"}},
                "required": ["file"]}}},
    ]
    return schemas, impl


def _execute_tool(impl: Dict[str, Callable], name: str, arguments: dict) -> str:
    fn = impl.get(name)
    if not fn:
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
    try:
        return fn(**(arguments or {}))
    except Exception as e:  # 单工具异常不终止循环
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ── 最终产物解析 ────────────────────────────────────────────

def _parse_naming_json(text: str) -> List[dict]:
    """从模型最终回复提取 JSON 数组(容错: 围栏/前后杂文本)。"""
    if not text:
        return []
    t = text.strip()
    if "```" in t:
        for part in t.split("```"):
            p = part.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("["):
                t = p
                break
    start, end = t.find("["), t.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("commId") or "").strip()
            name = str(item.get("name") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if cid and name:
                out.append({"commId": cid, "name": name[:80], "summary": summary[:400]})
    return out


# ── 命名继承(全量重建的命名保持) ────────────────────────────

def inherit_names(multi_db, project_id: str, new_task_id: str) -> dict:
    """新任务社区 ← 上一代 done 任务的命名继承(按成员文件集 Jaccard)。

    语义: 全量重建/新 fast 任务不改变用户已理解的组件命名 —
    新旧社区成员文件重叠 ≥ config.NAME_INHERIT_JACCARD 即继承
    name(优先 name_manual)/summary, source='inherit'。
    继承行随后被 run_fast_naming 跳过(保持稳定), 仅新社区进入命名。
    """
    from topoone.config import NAME_INHERIT_JACCARD
    main_db = multi_db.main_db
    prev = main_db.fetchone(
        "SELECT id FROM analysis_tasks WHERE project_id = ? AND id != ? "
        "AND status = 'done' ORDER BY created_at DESC LIMIT 1",
        (project_id, new_task_id))
    if not prev:
        return {"inherited": 0, "reason": "no_previous_task"}
    old_task_id = prev["id"]

    project_db = multi_db.get_project_db(project_id)

    def _file_sets(tid: str, comm_lv: str) -> Dict[str, set]:
        out: Dict[str, set] = {}
        try:
            for r in project_db.fetchall(
                    "SELECT comm_id, node_list FROM graph_doc "
                    "WHERE task_id = ? AND edge_type = 'UNIFIED' AND comm_lv = ?",
                    (tid, comm_lv)):
                nl = r["node_list"]
                files = json.loads(nl) if isinstance(nl, str) else (nl or [])
                out[r["comm_id"]] = {str(f) for f in files if f}
        except Exception:
            pass
        return out

    def _prev_names(tid: str, comm_lv: str) -> Dict[str, dict]:
        old_rows: Dict[str, dict] = {}
        try:
            for r in project_db.fetchall(
                    "SELECT comm_id, name, name_manual, summary FROM community_llm_results "
                    "WHERE task_id = ? AND edge_type = 'UNIFIED' AND comm_lv = ?",
                    (tid, comm_lv)):
                old_rows[r["comm_id"]] = dict(r)
        except Exception:
            pass
        return old_rows

    def _lv_key(v: str):
        m = re.match(r"L(\d+)$", v or "")
        return (int(m.group(1)),) if m else (999,)

    # 全层级同维度继承(子组件与顶层同语义: 同层级、同成员文件集 Jaccard)
    try:
        lv_rows = project_db.fetchall(
            "SELECT DISTINCT comm_lv FROM community_hierarchy "
            "WHERE task_id = ? AND edge_type = 'UNIFIED'", (new_task_id,))
        levels = sorted((r["comm_lv"] for r in lv_rows), key=_lv_key)
    except Exception:
        levels = ["L0"]

    rows = []
    for comm_lv in levels:
        new_sets = _file_sets(new_task_id, comm_lv)
        old_sets = _file_sets(old_task_id, comm_lv)
        old_rows = _prev_names(old_task_id, comm_lv)
        if not new_sets or not old_sets or not old_rows:
            continue
        for new_cid, new_files in new_sets.items():
            if not new_files:
                continue
            best, best_j = None, 0.0
            for old_cid, old_files in old_sets.items():
                if not old_files:
                    continue
                union = new_files | old_files
                j = len(new_files & old_files) / len(union) if union else 0.0
                if j > best_j:
                    best, best_j = old_cid, j
            if best is None or best_j < NAME_INHERIT_JACCARD:
                continue
            src_row = old_rows.get(best)
            if not src_row:
                continue
            name = (src_row.get("name_manual") or src_row.get("name") or "").strip()
            if not name:
                continue
            rows.append({
                "task_id": new_task_id, "edge_type": "UNIFIED", "comm_lv": comm_lv,
                "comm_id": new_cid, "name": name[:80],
                "summary": (src_row.get("summary") or "")[:400],
                "model_id": None, "template_id": None,
                "component_type": "community", "status": "completed",
                "source": "inherit",
            })
    if not rows:
        return {"inherited": 0, "reason": "no_overlap"}
    from topoone.engine.store.analysis_store import AnalysisStore
    AnalysisStore(project_db).bulk_insert_llm_results(rows)
    logger.info("[fast-naming] inherit task=%s <- %s: %d communities (τ=%.2f)",
                new_task_id, old_task_id, len(rows), NAME_INHERIT_JACCARD)
    return {"inherited": len(rows), "fromTask": old_task_id}


# ── 主入口 ──────────────────────────────────────────────────

async def _agent_name_level(multi_db, model_id: str, model_used: str,
                            schemas, impl, components: List[dict],
                            is_sub_level: bool) -> List[dict]:
    """单层级一次 agent 有界循环(工具补证 → JSON 数组产出)。失败上抛。"""
    from topoone.agent.agent_workflow.tool_calling import agentic_chat
    hint = ("注意: 以下为子组件, parent 字段标注其父组件——命名需体现从属关系"
            "(如「XX 模块 / 子模块名」), 不要与父组件或兄弟组件重名。\n" if is_sub_level else "")
    brief = (f"{hint}请为以下 {len(components)} 个组件命名(基本信息如下, "
             "可调用工具补充证据):\n%s\n\n完成后最终回复仅输出 JSON 数组。"
             % (json.dumps(components, ensure_ascii=False)[:12000],))
    messages: List[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": brief},
    ]
    for _turn in range(int(FAST_NAMING_MAX_TURNS)):
        resp = await agentic_chat(messages, schemas, multi_db, model_id)
        if resp.finish_reason == "error" or (not resp.content and not resp.tool_calls):
            raise RuntimeError(
                f"LLM 命名调用失败 (model={model_used or '未配置'}, "
                f"finish={resp.finish_reason}) —— 请检查模型服务可达性/默认模型配置")
        if resp.tool_calls:
            messages.append({"role": "assistant", "content": resp.content or "",
                             "tool_calls": [
                                 {"id": tc.id, "type": "function",
                                  "function": {"name": tc.name,
                                               "arguments": json.dumps(
                                                   tc.arguments, ensure_ascii=False)}}
                                 for tc in resp.tool_calls]})
            for tc in resp.tool_calls:
                result = _execute_tool(impl, tc.name, tc.arguments)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": result})
            continue
        return _parse_naming_json(resp.content)
    return []


async def run_fast_naming(multi_db, project_id: str, task_id: str,
                          model_id: str = "") -> dict:
    """对 UNIFIED 全层级组件(L0→L1→…)执行 agent 快速命名并落库。

    - 逐层调用(每层一轮 agent); 子层 payload 附父组件名(L0 先命名完成),
      命名体现从属关系。
    - 顺序: 命名继承(保持既有命名, 全层级) → 仅对未继承且无人工命名的社区命名。
    - 总量护栏 FAST_NAMING_MAX_COMPONENTS(全层级累计, 超限截断并标记 truncated)。
    失败抛错由调用方记日志/落 result_data.naming。
    """
    from topoone.config import FAST_NAMING_MAX_COMPONENTS
    inheritance = inherit_names(multi_db, project_id, task_id)
    project_db = multi_db.get_project_db(project_id)
    levels = _component_levels(project_db, task_id)
    if not levels:
        # 零组件通常是上游社区阶段被跳过/产物为空 —— 显式提示, 避免静默
        # 空转被误读为"命名完成"(实测: report_types 缺失 → 社区三线全跳)。
        logger.warning(
            "[fast-naming] task=%s 无 UNIFIED 组件可命名 —— "
            "社区阶段未产生组件, 请检查任务 report_types 是否含 "
            "dependency/callChain 及社区日志", task_id)
        return {"named": 0, "reason": "no_components"}

    proj = multi_db.main_db.fetchone(
        "SELECT root_path FROM projects WHERE id = ?", (project_id,))
    root = (proj["root_path"] if proj else "") or ""
    # root 缺失时 source_snippet 不可用, AST 工具仍可命名(降级而非失败)
    if not root or not os.path.isdir(root):
        logger.warning("[fast-naming] project root unavailable: %s", root)

    # 失败报出需含模型信息(B2): 调用方按此定位"哪个模型不可达"
    from topoone.agent.agent_workflow.tool_calling.strategy import _resolve_model_id
    model_used = model_id or _resolve_model_id(multi_db) or ""

    parent_of = _parent_map(project_db, task_id)
    parent_names: Dict[str, str] = {}   # 已命名层 comm_id → name, 供子层 payload
    total_named = 0
    total_skipped = 0
    per_level: Dict[str, int] = {}
    truncated = False
    budget = int(FAST_NAMING_MAX_COMPONENTS)

    for lv in levels:
        comps = _gather_components(project_db, task_id, lv)
        if not comps:
            per_level[lv] = 0
            continue
        if budget <= 0:
            truncated = True
            per_level[lv] = 0
            logger.warning("[fast-naming] task=%s 层级 %s 超总量护栏(%d)截断",
                           task_id, lv, FAST_NAMING_MAX_COMPONENTS)
            continue
        if len(comps) > budget:
            comps = comps[:budget]
            truncated = True
        budget -= len(comps)

        # 子层 payload 附父组件名(L0 已命名) —— 从属关系证据
        if lv != "L0":
            for c in comps:
                p = parent_of.get(c["commId"]) or ""
                c["parent"] = parent_names.get(p) or p

        schemas, impl = _make_tools(project_db, task_id, root, comps)
        naming = await _agent_name_level(multi_db, model_id, model_used,
                                         schemas, impl, comps, lv != "L0")

        known = {c["commId"] for c in comps}
        fixed = _fixed_comm_ids(project_db, task_id, lv)
        from topoone.engine.store.analysis_store import AnalysisStore
        rows = [{
            "task_id": task_id, "edge_type": "UNIFIED", "comm_lv": lv,
            "comm_id": n["commId"], "name": n["name"], "summary": n["summary"],
            "model_id": model_id or None, "template_id": None,
            "component_type": "community", "status": "completed",
            "source": "fast-agent",
        } for n in naming
            if n["commId"] in known and n["commId"] not in fixed]
        if rows:
            AnalysisStore(project_db).bulk_insert_llm_results(rows)
        for r in rows:
            parent_names[r["comm_id"]] = r["name"]
        per_level[lv] = len(rows)
        total_named += len(rows)
        total_skipped += len(fixed & known)
        logger.info("[fast-naming] task=%s level=%s named=%d skipped_fixed=%d",
                    task_id, lv, len(rows), len(fixed & known))

    if not total_named and not total_skipped:
        return {"named": 0, "reason": "no_valid_output",
                "perLevel": per_level, **inheritance}
    logger.info("[fast-naming] task=%s done named=%d perLevel=%s truncated=%s inherited=%d",
                task_id, total_named, per_level, truncated,
                inheritance.get("inherited", 0))
    return {"named": total_named, "perLevel": per_level,
            "skippedFixed": total_skipped, "truncated": truncated,
            **inheritance}
