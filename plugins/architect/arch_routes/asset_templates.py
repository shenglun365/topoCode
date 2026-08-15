"""实现层资产验收模板 —— 分类别必填项 + LLM 增强 schema + 种子⊕增强合并 + 校验。

核心不变量(严谨性支柱)：
  - 骨架(fields/steps/branches/relations-http/constraints)只来自种子(确定性分析)
    或工具返回的 ground truth；LLM 只能贴语义(name/desc/invariants/语义注释)，
    结构上无法伪造骨架条目。
  - LLM 输出的骨架副本仅在「与种子逐项匹配」时被采纳为语义注释(then/else/semantic)。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ── 验收模板(分类别) ───────────────────────────────────────────

KIND_TEMPLATES: Dict[str, dict] = {
    "entity": {
        "skeleton": ["fields"],
        "llm_fills": ["name", "desc", "invariants", "relations", "field_semantics"],
        "desc": "实体：数据对象/领域实体。必填 fields(name/type)；可选 invariants/relations。",
    },
    "contract": {
        "skeleton": ["relations"],
        "llm_fills": ["name", "desc", "invariants", "relations", "relation_semantics"],
        "desc": "契约：交换的形状(API 端点/接口签名)。必填 relations(http 类须有真实 path/methods)。",
    },
    "state": {
        "skeleton": ["states", "transitions"],
        "llm_fills": ["name", "desc", "invariants", "transition_semantics"],
        "desc": "状态：生命周期定义。必填 states(≥2)+transitions(≥1)。",
    },
    "rule": {
        "skeleton": ["constraints"],
        "llm_fills": ["name", "desc", "invariants", "constraint_semantics"],
        "desc": "规则：配置化的约束/阈值。必填 constraints 或 configSource。",
    },
    "process": {
        "skeleton": ["steps"],
        "llm_fills": ["name", "desc", "invariants", "relations", "step_semantics"],
        "desc": "过程：输入→有序步骤→输出。必填 steps(按真实调用序)。",
    },
    "decision": {
        "skeleton": ["branches"],
        "llm_fills": ["name", "desc", "invariants", "branch_semantics"],
        "desc": "决策：运行时分支。必填 branches(condition 代码原文 + then/else)。",
    },
}

_REL_TYPES = ("calls", "uses", "reads", "writes", "contains", "extends",
              "implements", "references", "constrains", "sends", "triggers",
              "1:1", "1:N", "N:M")


# ── LLM 增强输出 schema(按类别收窄) ───────────────────────────

_REL_ITEM = {
    "type": "object",
    "properties": {
        "target": {"type": "string", "description": "关联目标：其它资产业务名或符号名"},
        "type": {"type": "string", "description": f"关系类型: {'/'.join(_REL_TYPES)}"},
        "semantic": {"type": "string", "description": "关系语义一句话"},
    },
}


def enrichment_schema(kind: str) -> dict:
    """该类别定向提取的 structured output schema(只含增强字段，不含骨架)。"""
    props: Dict[str, Any] = {
        "symbol": {"type": "string", "description": "候选符号名(必须与候选表一致)"},
        "name": {"type": "string", "description": "业务语义命名(非符号名)"},
        "desc": {"type": "string", "description": "语义描述(作用与边界)"},
        "invariants": {"type": "array", "items": {"type": "string"},
                       "description": "不变式/约束(可空)"},
    }
    if kind in ("entity",):
        props["field_semantics"] = {
            "type": "array",
            "items": {"type": "object", "properties": {
                "name": {"type": "string"},
                "semantic": {"type": "string", "description": "字段业务语义一句话"}}},
            "description": "逐字段语义(name 必须与种子字段一致)"}
    if kind in ("contract", "process", "entity"):
        props["relations"] = {"type": "array", "items": _REL_ITEM,
                              "description": "跨资产关系(1~3 条，可空)"}
    if kind in ("process",):
        props["step_semantics"] = {
            "type": "array",
            "items": {"type": "object", "properties": {
                "order": {"type": "integer"},
                "semantic": {"type": "string", "description": "该步骤业务含义"}}},
            "description": "逐步语义(order 必须与种子步骤一致)"}
    if kind in ("decision",):
        props["branch_semantics"] = {
            "type": "array",
            "items": {"type": "object", "properties": {
                "condition": {"type": "string", "description": "种子中的条件原文(用于对齐)"},
                "then": {"type": "string", "description": "条件成立时做什么(业务语言)"},
                "else": {"type": "string", "description": "条件不成立时做什么(业务语言)"}}},
            "description": "逐分支语义(condition 必须与种子条件一致)"}
    if kind in ("state",):
        props["transition_semantics"] = {
            "type": "array",
            "items": {"type": "object", "properties": {
                "from": {"type": "string"}, "to": {"type": "string"},
                "event": {"type": "string", "description": "触发事件(业务语言)"},
                "condition": {"type": "string", "description": "迁移守卫条件(可空)"}}},
            "description": "逐迁移语义(from/to 必须与种子一致)"}
    if kind in ("rule",):
        props["constraint_semantics"] = {
            "type": "array",
            "items": {"type": "object", "properties": {
                "name": {"type": "string"},
                "semantic": {"type": "string", "description": "该约束的业务含义"}}},
            "description": "逐约束语义(name 必须与种子常量一致)"}
    return {
        "type": "object",
        "required": ["assets"],
        "properties": {
            "assets": {
                "type": "array",
                "items": {"type": "object", "required": ["symbol", "name", "desc"],
                          "properties": props},
            }
        },
    }


# ── 种子 ⊕ 增强 合并 ──────────────────────────────────────────


def _match_semantics(items: List[dict], key: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for it in items or []:
        if isinstance(it, dict) and it.get(key) is not None:
            out[str(it[key]).strip()] = it
    return out


def merge_seed_enrichment(kind: str, seed: dict, enrichment: Optional[dict],
                          ) -> dict:
    """合并种子骨架与 LLM 增强 → 资产 detail。

    骨架只来自 seed；enrichment 提供 name/desc/invariants 与逐项语义注释。
    """
    seed = seed or {}
    en = enrichment or {}
    detail: Dict[str, Any] = {}

    if kind == "entity":
        fields = list(seed.get("fields") or [])
        sem = _match_semantics(en.get("field_semantics"), "name")
        for f in fields:
            s = sem.get(str(f.get("name") or "").strip())
            if s:
                f["semantic"] = s.get("semantic") or ""
        detail["kind"] = "type"
        detail["fields"] = fields
        detail["signature"] = seed.get("signature") or ""
    elif kind == "contract":
        rels = list(seed.get("relations") or [])
        if not rels:
            rels = [{"target": "", "type": "signature",
                     "semantic": seed.get("signature") or ""}]
        rs = _match_semantics(en.get("relation_semantics"), "target")
        for r in rels:
            s = rs.get(str(r.get("target") or "").strip())
            if s and s.get("semantic"):
                r["semantic"] = s["semantic"]
        detail["kind"] = "message_contract"
        detail["relations"] = rels
    elif kind == "state":
        detail["states"] = list(seed.get("states") or [])
        trans = list(seed.get("transitions") or [])
        ts: Dict[tuple, dict] = {}
        for t in en.get("transition_semantics") or []:
            if isinstance(t, dict):
                ts[(str(t.get("from") or ""), str(t.get("to") or ""))] = t
        for t in trans:
            s = ts.get((str(t.get("from") or ""), str(t.get("to") or "")))
            if s:
                t["event"] = s.get("event") or t.get("event") or ""
                if s.get("condition"):
                    t["condition"] = s["condition"]
        detail["transitions"] = trans
    elif kind == "rule":
        detail["kind"] = "config_item"
        detail["configSource"] = seed.get("configSource") or ""
        cons = list(seed.get("constraints") or [])
        cs = _match_semantics(en.get("constraint_semantics"), "name")
        for c in cons:
            s = cs.get(str(c.get("name") or "").strip())
            if s:
                c["semantic"] = s.get("semantic") or ""
        detail["constraints"] = cons
    elif kind == "decision":
        branches = [dict(b) for b in (seed.get("branches") or [])]
        bs: Dict[str, dict] = {}
        for b in en.get("branch_semantics") or []:
            if isinstance(b, dict) and b.get("condition"):
                bs[str(b["condition"]).strip()] = b
        for b in branches:
            s = bs.get(str(b.get("condition") or "").strip())
            if s:
                b["then"] = s.get("then") or ""
                b["else"] = s.get("else") or ""
            b.setdefault("semantic", "")
            b.setdefault("symbols", [])
        detail["kind"] = "branch_logic"
        detail["branches"] = branches
    else:  # process
        steps = [dict(s) for s in (seed.get("steps") or [])]
        ss: Dict[int, dict] = {}
        for s in en.get("step_semantics") or []:
            if isinstance(s, dict) and s.get("order") is not None:
                try:
                    ss[int(s["order"])] = s
                except (TypeError, ValueError):
                    continue
        for i, s in enumerate(steps, 1):
            m = ss.get(i) or ss.get(int(s.get("order") or i))
            if m and m.get("semantic"):
                s["semantic"] = m["semantic"]
            else:
                s["semantic"] = "调用 " + str(s.get("symbol") or "")
        detail["trigger"] = ""
        detail["kind"] = "call_chain"
        detail["steps"] = steps
        detail["conditions"] = list(seed.get("conditions") or [])
    detail.setdefault("invariants", [])
    return detail


# ── 验收(必填 + 溯源) ─────────────────────────────────────────


def validate_kind(kind: str, detail: dict, seed: Optional[dict] = None) -> List[str]:
    """返回缺失/违规项列表(空 = 通过)。"""
    issues: List[str] = []
    detail = detail or {}
    seed = seed or {}
    if kind == "entity":
        if not (detail.get("fields") or []):
            # 类体源码不可读/确无字段 → 不算缺失(诚实地板)
            if seed.get("source"):
                issues.append("fields(类体有源码但未识别出字段，可用 asset_read_source 复核)")
    elif kind == "contract":
        rels = detail.get("relations") or []
        if not rels:
            issues.append("relations(须有至少一条签名/http 约定)")
    elif kind == "state":
        if len(detail.get("states") or []) < 2:
            issues.append("states(状态数 < 2)")
        if not (detail.get("transitions") or []):
            issues.append("transitions(无迁移)")
    elif kind == "rule":
        if not (detail.get("constraints") or []) and not (detail.get("configSource") or ""):
            issues.append("constraints(可用 asset_query_constants 取真实常量值)")
    elif kind == "process":
        if not (detail.get("steps") or []) and not (detail.get("trigger") or "").strip():
            issues.append("steps(可用 asset_query_calls 取真实调用链)")
    elif kind == "decision":
        br = detail.get("branches") or []
        if not br:
            issues.append("branches(可用 asset_query_calls/上下文语句清单补齐)")
        elif not any((b.get("condition") or "").strip() for b in br):
            issues.append("branches.condition(条件不得为空)")
    if not isinstance(detail.get("invariants"), list):
        detail["invariants"] = []
    return issues


def repair_hint(kind: str, issues: List[str], node: dict) -> str:
    """缺项回喂提示：具体缺哪条 + 哪个工具可取(ground truth)。"""
    file_ = node.get("file_path") or ""
    sym = node.get("qualified_name") or node.get("name") or ""
    lines = [f"- [{kind}] {sym} ({file_}): 缺少 {'; '.join(issues)}"]
    tool_map = {
        "entity": f"asset_read_source(file=\"{file_}\", symbol=\"{sym}\") 取类体源码后按字段名/类型补齐",
        "contract": f"asset_query_routes(file=\"{file_}\") 取真实路由 path/methods",
        "state": "状态成员来自 AST 枚举/类成员，无需工具；请按种子 states 填写 transitions 语义",
        "rule": f"asset_query_constants(file=\"{file_}\") 取真实常量值",
        "process": f"asset_query_calls(file=\"{file_}\", symbol=\"{sym}\") 取行序调用链",
        "decision": f"asset_query_calls(file=\"{file_}\", symbol=\"{sym}\") 或复核上下文语句清单",
    }
    lines.append(f"  补齐方式: {tool_map.get(kind, '复核种子数据')}")
    return "\n".join(lines)


# ── 增强输出解析 ───────────────────────────────────────────────

def parse_enrichments(output: Any, symbol_names: List[str]
                      ) -> Dict[str, dict]:
    """LLM 增强输出 → {symbol: enrichment}。symbol 不匹配候选表的条目丢弃。"""
    if not isinstance(output, dict):
        return {}
    out: Dict[str, dict] = {}
    want = {str(s) for s in symbol_names}
    for a in output.get("assets") or []:
        if not isinstance(a, dict):
            continue
        sym = str(a.get("symbol") or "").strip()
        if not sym:
            continue
        # 容忍 qualified_name 与 name 两种写法
        key = sym if sym in want else (sym.split("::")[-1] if sym.split("::")[-1] in want else sym)
        if key not in want and sym not in want:
            continue
        out[key if key in want else sym] = a
    return out
