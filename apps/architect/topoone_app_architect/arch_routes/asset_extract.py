"""实现层定向提取管线(分层版) —— 规则候选 → 名称批量解析(LLM, 10个/次) → 种子地板。

分层口径(产品定稿)：
  - 批量提取只产 名称(LLM 业务命名, 一次 10 个轻提示词) + 结构化种子(ground truth)；
  - 功能摘要(desc)不在批量流程生成——列表展开详情按需生成(/kb/semantic/asset-desc)；
  - 伪码/逐行解读在图谱资产卡按需触发；缓存腐烂由失效链路清空。
与旧管线的区别：退役 tAgent 多轮循环/修复轮/desc 富化——批量提速一个数量级。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict, List, Optional

from .asset_rules import RuleContext, candidates_for_file
from .asset_templates import (KIND_TEMPLATES, merge_seed_enrichment,
                              validate_kind)

logger = logging.getLogger(__name__)

# 名称批量解析的分块(一次 10 个候选；轻提示词短输出)。
_NAME_CHUNK = 10
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


def _sys_base() -> str:
    """系统提示基座。工具清单与 [TOOL_CALL: name] 协议由 tAgent 的
    TextFallback 策略自行注入 system 末尾，此处不重复。"""
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
        "输出 JSON 对象 {\"assets\": [...]}，不要 Markdown 代码块。"
        "每项必须带 symbol 字段=候选表中的 symbol 值逐字回填(对齐用，不可省略/改写)；"
        "各项按候选表顺序输出。"
    )


def _directed_prompt(file_: str, kind: str, cands: List[dict]) -> str:
    return _task_spec(file_, kind) + "\n\n候选表:\n" + _candidate_lines(cands, kind)


def _floor_asset(kind: str, node: dict, seed: dict, file_: str) -> dict:
    """种子地板：名称解析缺失时，确定性种子原样成资产。

    desc 留空(分层口径：功能摘要一律按需生成/asset-desc)，不批量渲染。
    """
    detail = merge_seed_enrichment(kind, seed, None)
    name = node.get("name") or node.get("qualified_name") or "?"
    return {"kind": kind, "level": "implementation", "name": name,
            "desc": "",
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


# ── 分组定向提取(分层版: 名称批量解析 + 种子地板) ──────────────


def _batch_name_enrich(root: str, project: Optional[str], file_: str, kind: str,
                       cands: List[dict], model_id: Optional[str]) -> Dict[str, dict]:
    """名称批量解析(一次 10 个)：轻提示词直连 LLM(不经 tAgent 工具循环/多轮)。

    只产业务 name；失败/解析不出 → 返回空(候选全部走地板符号名)，不影响提取主体。
    """
    from ..kb_gateway import get_gateway
    from .tagent_se import KbGatewayLLMClient
    from topocode_agent.core.utils import extract_json_object

    llm = KbGatewayLLMClient(get_gateway(), model_id=model_id or "")
    out: Dict[str, dict] = {}
    for i in range(0, len(cands), _NAME_CHUNK):
        chunk = cands[i:i + _NAME_CHUNK]
        lines = "\n".join(
            f"- {c['node'].get('qualified_name') or c['node'].get('name')}"
            f" @L{c['node'].get('start_line')}"
            + (f"  // {(c['node'].get('docstring') or '').strip()[:60]}"
               if (c['node'].get('docstring') or '').strip() else "")
            for c in chunk)
        user = (f"文件: {file_}\n类别: {kind}\n候选符号:\n{lines}\n\n"
                "为每个符号起一个简洁业务名(中文，可作图节点标签，非符号名直译)。"
                '只输出 JSON 对象 {"names": [{"symbol": "候选符号逐字回填", "name": "业务名"}]}，'
                "不要 Markdown 代码块。")
        try:
            resp = asyncio.run(llm.chat(
                [{"role": "user", "content": user}], max_tokens=600))
        except Exception as e:
            logger.warning("[asset_extract] %s 名称解析失败(走符号名): %s", file_, e)
            return out
        obj = extract_json_object(resp.content or "")
        for it in (obj or {}).get("names") or []:
            if not isinstance(it, dict):
                continue
            sym = str(it.get("symbol") or "").strip()
            nm = str(it.get("name") or "").strip()
            if not sym or not nm:
                continue
            # 模型常把候选行的 @L 行号后缀一并回填 → 归一化剥离
            sym = re.sub(r"\s*@L\d+(-\d+)?$", "", sym).strip()
            out[sym] = {"name": nm}
            short = sym.split("::")[-1]   # 短名兜底(模型可能只回末段)
            if short and short not in out:
                out[short] = {"name": nm}
    return out


def _extract_group(root: str, project: Optional[str], ctx: dict, file_: str,
                   kind: str, cands: List[dict], model_id: Optional[str],
                   use_llm: bool, context_manager=None,
                   rc: Optional["RuleContext"] = None) -> List[dict]:
    """单 (文件×类型) 组：名称批量解析 + 种子地板(确定性，无多轮/修复轮)。"""
    from .agent_roles import resolve_role_model

    # 角色模型路由(§9/B1)：名称解析走 extract 角色；显式传入优先。
    model_id = resolve_role_model("extract", model_id)

    cands = cands[:_GROUP_CAP]
    enrich: Dict[str, dict] = {}
    if use_llm and cands:
        enrich = _batch_name_enrich(root, project, file_, kind, cands, model_id)

    assets: List[dict] = []
    for c in cands:
        n = c["node"]
        sym = n.get("qualified_name") or n.get("name") or ""
        en = enrich.get(sym) or enrich.get(n.get("name") or "")
        detail = merge_seed_enrichment(kind, c["seed"], en)
        issues = validate_kind(kind, detail, c["seed"])
        name = (str(en.get("name")).strip() if en and (en.get("name") or "").strip()
                else (sym or "?"))
        asset = {"kind": kind, "level": "implementation", "name": name,
                 "desc": "",   # 分层口径: 功能摘要按需生成(/kb/semantic/asset-desc)
                 "detail": detail,
                 "astRefs": [{"file": n.get("file_path"),
                              "symbol": sym,
                              "kind": _ast_kind_of(n),
                              "startLine": int(n.get("start_line") or 0),
                              "endLine": int(n.get("end_line") or 0)}],
                 "tags": _auto_tags(n, c["seed"])}
        if issues or not en:
            asset["meta"] = {"degraded": not en, "issues": issues}
        assets.append(asset)
    logger.info("[asset_extract] %s %s: cands=%d named=%d floor=%d",
                file_, kind, len(cands), len(enrich), len(cands) - len(enrich))
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
