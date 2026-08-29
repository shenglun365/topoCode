"""实现层定向提取管线 —— 规则候选 → (文件×类型) 批量定向调用 → 种子⊕增强 →
验收 → 工具补齐(确定性回提取) → 种子地板。

与旧 `_llm_extract`(整包自由识别)的区别：
  - 类别由规则定死(asset_rules)，LLM 不做识别/分类；
  - 每 (文件×类型) 一次定向调用，prompt 为候选表(每候选一行结构摘要)+验收模板+工具清单；
  - 骨架只来自种子/工具 ground truth，LLM 只贴语义(asset_templates.merge)；
  - 验收不过 → 定向修复轮(≤1 次, 可工具) → 仍不过 → 种子原样落库(地板)。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .asset_rules import RuleContext, business_value_score, candidates_for_file
from .asset_templates import (KIND_TEMPLATES, enrichment_schema, merge_seed_enrichment,
                              parse_enrichments, render_summary_desc, repair_hint,
                              validate_kind)

logger = logging.getLogger(__name__)

# 每 (文件×类型) 送 LLM 的候选上限(按业务价值取 top-N；控制输出规模)。
# 未入选者走确定性地板(规则汇总 desc，全量覆盖，不依赖 LLM)。
_GROUP_LLM_CAP = 15
# 每 (文件×类型) 候选材料 char 预算(控制输入规模；小模型上下文受限)。
_GROUP_PROMPT_BUDGET = 8000
# 每 (文件×类型) 落库资产上限(防超大文件爆炸)。
_GROUP_CAP = 80

_TAG_SIGNALS = (
    ("transactional", ("commit", "rollback", "atomic", "事务")),
    ("caching", ("redis", "cache", "@lru_cache", "cachetools")),
    ("security", ("auth", "login", "jwt", "token", "permission", "密码", "鉴权")),
    ("observability", ("logger", "trace", "metrics")),
    ("async", ("async ", "await", "thread", "semaphore", "pool")),
    ("middleware", ("middleware", "interceptor", "hook")),
    ("resilience", ("rate_limit", "retry", "backoff", "限流", "重试")),
)


def _auto_tags(node: dict, seed: dict) -> List[str]:
    """确定性横向切面打标(签名/docstring/文件特征词)。"""
    text = f"{node.get('signature') or ''} {node.get('docstring') or ''} " \
           f"{node.get('file_path') or ''}".lower()
    tags = []
    for tag, toks in _TAG_SIGNALS:
        if any(t in text for t in toks):
            tags.append(tag)
    return tags[:4]


def _seed_summary(seed: dict, kind: str) -> str:
    """种子结构 → 一行紧凑摘要(替代整包 seed JSON，省 token)。逐项细节靠工具取。"""
    seed = seed or {}
    if kind == "entity":
        f = seed.get("fields") or []
        if f:
            names = [str(x.get("name") or "") for x in f if isinstance(x, dict)][:6]
            more = "…" if len(f) > 6 else ""
            return f"{len(f)} 字段: {', '.join(n for n in names if n)}{more}"
        return "(类体源码已备好，字段待补)" if seed.get("source") else "无字段"
    if kind == "process":
        st = seed.get("steps") or []
        if st:
            syms = [str(s.get("symbol") or "") for s in st if s.get("symbol")][:6]
            n_br = len([s for s in st if s.get("op") in ("if", "switch", "case")])
            return (f"{len(st)} 步: {'→'.join(s for s in syms if s)}"
                    + (f"（{n_br} 分支）" if n_br else ""))
        return "无步骤(可用 asset_query_calls 补)"
    if kind == "decision":
        br = seed.get("branches") or []
        conds = [str(b.get("condition") or "") for b in br if b.get("condition")][:4]
        return f"{len(br)} 分支: {' / '.join(c for c in conds if c)}" if br else "无分支"
    if kind == "contract":
        rels = seed.get("relations") or []
        if rels:
            parts = [f"{'/'.join(r.get('methods') or ['GET'])} {r.get('target')}"
                     for r in rels[:4] if r.get("target")]
            return "; ".join(p for p in parts if p) or "签名契约"
        return seed.get("signature") or "签名契约(可用 asset_query_routes 补)"
    if kind == "state":
        st = seed.get("states") or []
        names = [str(s.get("name") or "") for s in st][:8]
        return "→".join(n for n in names if n) or "无状态"
    if kind == "rule":
        cons = seed.get("constraints") or []
        parts = [f"{c.get('name')}={c.get('value')}" for c in cons[:4] if c.get("name")]
        return f"{len(cons)} 约束: {'; '.join(parts)}" if cons else "配置项"
    return ""


def _candidate_lines(cands: List[dict], kind: str) -> str:
    lines = []
    for i, c in enumerate(cands, 1):
        n = c["node"]
        head = (f"{i}. symbol=`{n.get('qualified_name') or n.get('name')}` "
                f"@L{n.get('start_line')}-{n.get('end_line')} kind={kind}")
        sig = (n.get("signature") or "").strip()
        doc = (n.get("docstring") or "").strip().replace("\n", " ")
        if sig:
            head += f" sig=({sig[:120]})"
        if doc:
            head += f" // {doc[:100]}"
        summary = _seed_summary(c["seed"], kind)
        if summary:
            head += f"\n   结构: {summary}"
        lines.append(head)
    return "\n".join(lines)


def _tool_protocol_text() -> str:
    return (
        "可用工具(缺数据时输出工具调用块获取，格式 "
        "[TOOL_CALL]{\"tool\":\"asset.xxx\",\"arguments\":{...}}[/TOOL_CALL]，可多次)：\n"
        "  - asset.read_source(file, symbol): 符号源码切片(补 entity 字段)\n"
        "  - asset.query_constants(file): 常量值清单(补 rule 约束)\n"
        "  - asset.query_calls(file, symbol): 行序调用链(补 process steps)\n"
        "  - asset.query_routes(file): 框架路由清单(补 contract relations)\n"
        "  - asset.query_symbol(file, symbol): 符号 AST 信息"
    )


def _sys_base() -> str:
    """系统提示基座（两路共用）；tAgent 路不附 _tool_protocol_text——
    TextFallback 策略自行把工具清单与 [TOOL_CALL: name] 协议注入 system 末尾。"""
    return (
        "你是代码语义资产补齐器。候选表已由规则分类(类别定死不可更改)，"
        "种子数据由确定性分析预填(字段/调用链/分支条件/路由/常量值均为 ground truth)。"
        "你只负责语义层：业务命名、描述、不变式、跨资产关系、逐项语义注释。"
        "desc 必须是一段自洽的白话说明(它在本项目里做什么、边界在哪、为什么存在、关键输入/输出)，"
        "让不读代码的工程师也能直接看懂，而非堆砌符号名；name 用简洁业务名(可作图节点标签)。"
        "不得臆造种子与工具返回中不存在的数据。"
    )


def _task_spec(file_: str, kind: str) -> str:
    """任务规格（context Base 层钉驻）：定向 prompt 头，不含候选表。"""
    tpl = KIND_TEMPLATES[kind]
    return (
        f"文件: {file_}\n候选类别(规则定死，不可更改): {kind}\n"
        f"验收模板: {tpl['desc']}\n"
        "任务: 对下列每个候选，填写业务 name(简洁业务名，非符号名，可作图标签)、"
        "desc(自洽白话说明:作用/边界/为什么存在/关键输入输出)、"
        "invariants(可空)、跨资产 relations(1~3 条，可空)，以及按类别的逐项语义"
        "(field_semantics/step_semantics/branch_semantics/constraint_semantics/"
        "transition_semantics，键必须与种子完全一致)。\n"
        "严禁: 臆造种子与工具返回中不存在的符号/字段/条件/path/常量值；更改类别。\n"
        "只输出 JSON 对象 {\"assets\": [...]}，不要 Markdown 代码块。"
    )


def _directed_prompt(file_: str, kind: str, cands: List[dict]) -> str:
    return _task_spec(file_, kind) + "\n\n候选表:\n" + _candidate_lines(cands, kind)


def _floor_asset(kind: str, node: dict, seed: dict, file_: str) -> dict:
    """种子地板：LLM 增强缺失/未入选时，确定性种子原样成资产。

    desc 由 render_summary_desc 渲染(代码级白话，全量覆盖，不依赖 LLM)。
    """
    detail = merge_seed_enrichment(kind, seed, None)
    name = node.get("name") or node.get("qualified_name") or "?"
    return {"kind": kind, "level": "implementation", "name": name,
            "desc": render_summary_desc(kind, node, detail),
            "detail": detail,
            "astRefs": [{"file": node.get("file_path"), "symbol": node.get("qualified_name") or name,
                          "kind": _ast_kind_of(node), "startLine": int(node.get("start_line") or 0),
                          "endLine": int(node.get("end_line") or 0)}],
            "tags": _auto_tags(node, seed)}


def _ast_kind_of(node: dict) -> str:
    from .semantic_assets import _AST_KIND_MAP
    return _AST_KIND_MAP.get(node.get("kind"), "func")


# ── 工具事实 → 确定性回提取(模型触发，管线应用) ────────────────


def _apply_tool_facts(kind: str, node: dict, seed: dict, facts: List[dict]) -> dict:
    """把工具返回的 ground truth 确定性地并入种子(不信任模型转述)。"""
    seed = dict(seed or {})
    sym = node.get("name") or ""
    file_ = node.get("file_path") or ""

    def _facts_of(tool: str) -> List[dict]:
        out = []
        for f in facts or []:
            if f.get("tool") != tool or not isinstance(f.get("result"), dict):
                continue
            a = f.get("args") or {}
            if a.get("file") and a.get("file") != file_:
                continue
            if a.get("symbol") and a.get("symbol") != sym and \
                    a.get("symbol") != (node.get("qualified_name") or ""):
                continue
            out.append(f["result"])
        return out

    if kind == "entity" and not (seed.get("fields") or []):
        from .asset_rules import fields_from_source_text
        for r in _facts_of("asset.read_source"):
            got = fields_from_source_text(r.get("source") or "")
            if got:
                seed["fields"] = got
                break
    elif kind == "rule" and not (seed.get("constraints") or []):
        for r in _facts_of("asset.query_constants"):
            if r.get("constants"):
                seed["constraints"] = [{"name": c.get("name", ""), "value": c.get("value", ""),
                                        "line": int(c.get("line") or 0)}
                                       for c in r["constants"][:50]]
                break
    elif kind == "contract" and not (seed.get("relations") or []):
        from .semantic_assets import _relations_from_routes
        for r in _facts_of("asset.query_routes"):
            if r.get("routes"):
                seed["relations"] = _relations_from_routes(
                    {file_: {"routes": r["routes"]}}, node)
                break
    elif kind == "process" and not (seed.get("steps") or []):
        for r in _facts_of("asset.query_calls"):
            if r.get("calls"):
                seed["steps"] = [{"order": i, "symbol": c.get("symbol") or ""}
                                 for i, c in enumerate(r["calls"][:8], 1)]
                break
    return seed


# ── 分组定向提取 ───────────────────────────────────────────────


def _extract_group(root: str, project: Optional[str], ctx: dict, file_: str,
                   kind: str, cands: List[dict], model_id: Optional[str],
                   use_llm: bool, context_manager=None,
                   rc: Optional["RuleContext"] = None) -> List[dict]:
    from . import asset_tools

    out: List[dict] = []
    cands = cands[:_GROUP_CAP]

    # 工具上下文一次设定，facts 跨轮累积(与工具同线程)。
    asset_tools.set_extraction_context(root, project, ctx)
    facts: List[dict] = asset_tools._tl.facts  # 同一列表对象，工具 append 可见
    try:
        return _extract_group_inner(root, project, ctx, file_, kind, cands,
                                    model_id, use_llm, facts, rc,
                                    context_manager=context_manager)
    finally:
        asset_tools.clear_extraction_context()


def _extract_group_inner(root: str, project: Optional[str], ctx: dict, file_: str,
                         kind: str, cands: List[dict], model_id: Optional[str],
                         use_llm: bool, facts: List[dict],
                         rc: Optional["RuleContext"] = None,
                         context_manager=None) -> List[dict]:
    from .req_agent import get_max_tokens_preference, run_tools_loop
    from . import tagent_extract

    out: List[dict] = []
    cands = cands[:_GROUP_CAP]
    if rc is None:
        node_by_id = {n.get("id"): n for n in ctx.get("nodes") or []}
        rc = RuleContext(ctx.get("edges") or [], ctx.get("implDetails") or {},
                         node_by_id, extra_names=ctx.get("calleeNames"))
    # 送 LLM 的 top-N：按业务价值降序，受 char 预算 + 上限约束(控制上下文，
    # 小模型只在"高价值 + 小 prompt"下高质量处理；未入选走确定性地板)。
    if use_llm and cands:
        scored = sorted(cands,
                        key=lambda c: business_value_score(c["node"], c.get("kind") or kind, rc),
                        reverse=True)
        llm_part: List[dict] = []
        used = 0
        for c in scored:
            cost = len(_candidate_lines([c], c.get("kind") or kind))
            if llm_part and (used + cost > _GROUP_PROMPT_BUDGET
                             or len(llm_part) >= _GROUP_LLM_CAP):
                break
            llm_part.append(c)
            used += cost
        llm_part.sort(key=lambda c: int(c["node"].get("start_line") or 0))
    else:
        llm_part = []

    # 上下文编译循环(方案 B)：开关默认开，每 file×kind 组一实例；可外部注入共享
    # cm(知识库自我更新等长 cm 场景跨文件累积，见 tagent_extract)。
    cm = context_manager
    if cm is None and use_llm and llm_part and tagent_extract.ctx_asset_enabled():
        cm = tagent_extract.build_extraction_context(
            file_=file_, kind=kind, task_spec=_task_spec(file_, kind))

    enrich: Dict[str, dict] = {}
    if use_llm and llm_part:
        user_msg = _directed_prompt(file_, kind, llm_part)
        names = [c["node"].get("qualified_name") or c["node"].get("name")
                 for c in llm_part]
        res = None
        if cm is not None:
            # tAgent agentic_loop + ContextManager(phase=kb_analysis, 可达性豁免)
            try:
                res = tagent_extract.run_extraction_agentic(
                    sys_msg=_sys_base(), user_msg=user_msg,
                    root=root, project=project, model_id=model_id,
                    max_rounds=2, max_tokens=get_max_tokens_preference(),
                    context_manager=cm, file_=file_, kind=kind,
                    task_spec=_task_spec(file_, kind))
            except Exception as e:
                logger.warning("[asset_extract] %s %s 提取异常(tagent): %s",
                               file_, kind, e)
        else:
            # 旧路径(TOPOCODE_CTX_ASSET=0 双轨对拍)
            sys_msg = _sys_base() + _tool_protocol_text()
            try:
                res = run_tools_loop(
                    [{"role": "system", "content": sys_msg},
                     {"role": "user", "content": user_msg}],
                    root=root, project=project, mode="structured",
                    output_schema=enrichment_schema(kind), max_rounds=2,
                    max_tokens=get_max_tokens_preference(), model_id=model_id)
            except Exception as e:
                logger.warning("[asset_extract] %s %s 提取异常: %s", file_, kind, e)
        if res and isinstance(res.get("output"), dict):
            enrich = parse_enrichments(res["output"], names)
        else:
            logger.warning("[asset_extract] %s %s LLM 无结构化输出(content_len=%d)",
                           file_, kind, len((res or {}).get("content") or ""))

    # 合并 + 验收
    pending: List[dict] = []
    for c in cands:
        n = c["node"]
        sym = n.get("qualified_name") or n.get("name") or ""
        seed = _apply_tool_facts(kind, n, c["seed"], facts)
        en = enrich.get(sym) or enrich.get(n.get("name") or "")
        detail = merge_seed_enrichment(kind, seed, en)
        issues = validate_kind(kind, detail, seed)
        if issues and use_llm:
            pending.append({"_cand": c, "_seed": seed, "_en": en, "_issues": issues})
        out.append({"_cand": c, "_seed": seed, "_en": en, "_detail": detail,
                    "_issues": issues})

    # 定向修复轮(仅对验收不过的候选)
    if pending and use_llm:
        try:
            hints = "\n".join(repair_hint(kind, it["_issues"], it["_cand"]["node"])
                              for it in pending)
            syms = [(it["_cand"]["node"].get("qualified_name")
                     or it["_cand"]["node"].get("name")) for it in pending]
            repair_user = (
                f"文件: {file_}，类别: {kind}。以下资产未通过验收，请仅针对它们重新输出完整资产"
                f"(symbol/name/desc 及语义字段)：\n{hints}\n只输出 JSON 对象 "
                f'{{"assets": [...]}}。')
            res2 = None
            if cm is not None:
                # 复用同一 cm：继承首轮任务规格钉驻 + 工具结果工作集
                res2 = tagent_extract.run_extraction_agentic(
                    sys_msg="你是代码语义资产补齐器(修复轮)。",
                    user_msg=repair_user,
                    root=root, project=project, model_id=model_id,
                    max_rounds=2, max_tokens=get_max_tokens_preference(),
                    context_manager=cm)
            else:
                res2 = run_tools_loop(
                    [{"role": "system", "content": "你是代码语义资产补齐器(修复轮)。"},
                     {"role": "user", "content": repair_user}],
                    root=root, project=project, mode="structured",
                    output_schema=enrichment_schema(kind), max_rounds=2,
                    max_tokens=get_max_tokens_preference(), model_id=model_id)
        except Exception as e:
            logger.warning("[asset_extract] %s %s 修复轮异常: %s", file_, kind, e)
            res2 = None
        if res2 and isinstance(res2.get("output"), dict):
            enrich2 = parse_enrichments(res2["output"], syms)
            for it in pending:
                n = it["_cand"]["node"]
                sym = n.get("qualified_name") or n.get("name") or ""
                en2 = enrich2.get(sym) or enrich2.get(n.get("name") or "")
                if not en2:
                    continue
                seed2 = _apply_tool_facts(kind, n, it["_seed"], facts)
                detail2 = merge_seed_enrichment(kind, seed2, en2)
                issues2 = validate_kind(kind, detail2, seed2)
                # 仅当修复结果更完整时采用
                if len(issues2) < len(it["_issues"]):
                    it["_seed"], it["_en"], it["_detail"], it["_issues"] = \
                        seed2, en2, detail2, issues2

    # 成资产(增强名优先，地板兜底)
    assets: List[dict] = []
    for it in out:
        c, seed, en, detail, issues = (it["_cand"], it["_seed"], it["_en"],
                                       it["_detail"], it["_issues"])
        n = c["node"]
        if en and (en.get("name") or "").strip():
            name = str(en["name"]).strip()
            desc = str(en.get("desc") or "").strip() or render_summary_desc(kind, n, detail)
            inv = [str(x) for x in (en.get("invariants") or []) if str(x).strip()][:6]
            if inv and not (detail.get("invariants") or []):
                detail["invariants"] = inv
            rels = _norm_llm_rels(en.get("relations"))
            if rels:  # 追加跨资产关系(http 骨架关系已在 detail 中，不覆盖)
                base = detail.get("relations") if kind == "contract" else []
                detail["relations"] = list(base or []) + rels
            asset = {"kind": kind, "level": "implementation", "name": name, "desc": desc,
                     "detail": detail,
                     "astRefs": [{"file": n.get("file_path"),
                                  "symbol": n.get("qualified_name") or n.get("name"),
                                  "kind": _ast_kind_of(n),
                                  "startLine": int(n.get("start_line") or 0),
                                  "endLine": int(n.get("end_line") or 0)}],
                     "tags": _auto_tags(n, seed)}
            if issues:
                asset["meta"] = {"degraded": True, "issues": issues}
        else:
            asset = _floor_asset(kind, n, seed, n.get("file_path") or "")
        assets.append(asset)
    logger.info("[asset_extract] %s %s: cands=%d llm=%d enriched=%d degraded=%d",
                file_, kind, len(cands), len(llm_part), len(enrich),
                sum(1 for a in assets if a.get("meta", {}).get("degraded")))
    return assets


def _norm_llm_rels(rels) -> List[dict]:
    """LLM 跨资产关系归一(仅保留结构合法项；http 类关系不进此通道——骨架专属)。"""
    out = []
    from .asset_templates import _REL_TYPES
    for r in rels or []:
        if not isinstance(r, dict):
            continue
        target = str(r.get("target") or "").strip()
        rtype = str(r.get("type") or "references").strip()
        if not target:
            continue
        if rtype.lower() == "http":
            continue  # http 关系只能来自种子路由(防臆造端点)
        if rtype not in _REL_TYPES:
            rtype = "references"
        item = {"target": target, "type": rtype}
        sem = str(r.get("semantic") or "").strip()
        if sem:
            item["semantic"] = sem[:120]
        out.append(item)
        if len(out) >= 3:
            break
    return out


# ── 管线入口 ───────────────────────────────────────────────────


def extract_directed(root: str, project: Optional[str], ctx: dict,
                     kinds: Optional[List[str]] = None,
                     model_id: Optional[str] = None,
                     use_llm: bool = True,
                     context_manager=None) -> List[dict]:
    """实现层定向提取(文件×类型批量)。返回资产列表(与 _save_assets 同构)。

    context_manager: 可选共享 ContextManager——传入则所有 (文件×类型) 组共用
    (清单跨文件累积，知识库自我更新等长 cm 场景)；缺省每组建新(开关关闭则纯旧路径)。
    """
    nodes = ctx.get("nodes") or []
    node_by_id = {n.get("id"): n for n in nodes}
    rc = RuleContext(ctx.get("edges") or [], ctx.get("implDetails") or {}, node_by_id,
                     extra_names=ctx.get("calleeNames"))
    by_file: Dict[str, List[dict]] = {}
    for n in nodes:
        by_file.setdefault(n.get("file_path") or "", []).append(n)

    all_assets: List[dict] = []
    for file_ in sorted(by_file):
        if not file_:
            continue
        cands = candidates_for_file(root, by_file[file_], rc, kinds)
        if not cands:
            continue
        groups: Dict[str, List[dict]] = {}
        for c in cands:
            groups.setdefault(c["kind"], []).append(c)
        for kind in sorted(groups):
            try:
                all_assets += _extract_group(root, project, ctx, file_, kind,
                                             groups[kind], model_id, use_llm,
                                             context_manager, rc=rc)
            except Exception as e:
                logger.warning("[asset_extract] %s %s 分组提取失败(走地板): %s",
                               file_, kind, e)
                for c in groups[kind]:
                    all_assets.append(_floor_asset(kind, c["node"], c["seed"], file_))
    from collections import Counter
    logger.info("[asset_extract] 定向提取完成: files=%d assets=%d %s",
                len(by_file), len(all_assets), dict(Counter(a["kind"] for a in all_assets)))
    return all_assets
