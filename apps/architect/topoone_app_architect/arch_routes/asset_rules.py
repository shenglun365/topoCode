"""实现层资产规则引擎 —— 类别定死 + 值得提取过滤 + 关联范围装配。

设计(用户拍板)：
  - 现有 6 类由规则表定死类别，LLM 只能填语义内容，不能识别/更改类别；
  - 规则表数据驱动(RuleSpec)，未来用户自定义规则经 register_rule() 挂入(扩展点)；
  - 关联范围 = 每候选的确定性上下文装配函数：同一节点永远装配出同一上下文。

规则求值：按 priority 升序，首条命中即定类别(与旧 _primary_kind_for_node 等价)。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

# 复用旧启发式的确定性信号函数(行为等价，避免两份拷贝漂移)。
from .semantic_assets import (
    _API_NAME_PREFIXES,
    _API_SIG_TOKENS,
    SEMANTIC_KINDS,  # noqa: F401  (对外复用同一类别集)
    _branch_dense as _branch_dense_text,
    _config_carrier_signal,
    _impl_for_file,
    _is_route_handler,
)

_KIND_NODE_TYPES = {
    "entity": ("class", "interface", "struct", "component"),
    "state": ("enum",),
    "func": ("function", "method"),
}


# ── 规则上下文 ─────────────────────────────────────────────────


class RuleContext:
    """规则谓词可用的每文件上下文(edges/implDetails/节点索引)。"""

    def __init__(self, edges: Optional[List[dict]],
                 impl_by_file: Optional[Dict[str, dict]],
                 node_by_id: Optional[Dict[str, dict]] = None,
                 extra_names: Optional[Dict[str, str]] = None):
        self.edges = edges or []
        self.impl_by_file = impl_by_file or {}
        self.node_by_id = node_by_id or {}
        # 范围外节点的 名称补全(节点 id → 名称)，steps 展示避免裸 id。
        self.extra_names = extra_names or {}
        # scope 是否已有 route 节点(有则 handler 归属由边逻辑覆盖，impl 判定不介入)。
        self.has_route_node = any(
            (n.get("kind") or "").lower() == "route"
            for n in self.node_by_id.values())

    def impl(self, node: dict) -> dict:
        return _impl_for_file(self.impl_by_file, node)

    def statements_of(self, node: dict,
                      types: tuple = ("if", "switch", "case", "loop")) -> List[dict]:
        """该符号体内的控制流语句(implDetails，行序)。"""
        out = []
        for s in self.impl(node).get("statements") or []:
            if s.get("enclosing") != node.get("name"):
                continue
            if s.get("type") not in types:
                continue
            out.append(s)
        out.sort(key=lambda s: int(s.get("startLine") or 0))
        return out

    def callees_of(self, node: dict) -> List[tuple]:
        """该符号 1-hop 调用目标 (line, order, target_node) 按行序。"""
        out = []
        for i, e in enumerate(self.edges):
            if e.get("kind") == "calls" and e.get("source") == node.get("id"):
                t = self.node_by_id.get(e.get("target"))
                ln = e.get("line")
                out.append((ln if isinstance(ln, int) else 1 << 30, i, t))
        out.sort(key=lambda x: (x[0], x[1]))
        return out

    def callers_of(self, node: dict) -> int:
        return sum(1 for e in self.edges
                   if e.get("kind") == "calls" and e.get("target") == node.get("id"))

    def members_of(self, node: dict,
                   kinds: tuple = ("variable", "field", "property", "constant",
                                   "enum_member", "method")) -> List[dict]:
        out = []
        for e in self.edges:
            if e.get("kind") != "contains" or e.get("source") != node.get("id"):
                continue
            n = self.node_by_id.get(e.get("target"))
            if n and (n.get("kind") or "").lower() in kinds:
                out.append(n)
        return out


# ── 规则表 ─────────────────────────────────────────────────────


@dataclass
class RuleSpec:
    name: str
    kind: str                                   # 定死类别
    priority: int                               # 小者优先，首条命中
    predicate: Callable[[dict, RuleContext], bool]


_RULES: List[RuleSpec] = []


def register_rule(spec: RuleSpec) -> None:
    """注册规则(用户自定义规则的扩展入口)。同 name 覆盖，注册后按 priority 重排。"""
    for i, r in enumerate(_RULES):
        if r.name == spec.name:
            _RULES[i] = spec
            break
    else:
        _RULES.append(spec)
    _RULES.sort(key=lambda r: r.priority)


def _r_route_node(node: dict, rc: RuleContext) -> bool:
    return (node.get("kind") or "").lower() == "route"


def _r_contract_boundary(node: dict, rc: RuleContext) -> bool:
    """api_* 前缀函数 → 契约(被 route 节点引用的处理函数除外)。

    签名含 API 词(Request/Depends...)仅作为「无 route 节点」时的粗兜底——
    有 route 节点时不用(防 `def f(request: Request)` 误判契约)。
    """
    node_id = node.get("id")
    for e in rc.edges:
        if e.get("kind") == "references" and e.get("target") == node_id:
            src_node = rc.node_by_id.get(e.get("source") or "")
            if src_node and (src_node.get("kind") or "").lower() == "route":
                return False
    name = (node.get("name") or "").lower()
    if name.startswith(_API_NAME_PREFIXES):
        return True
    if rc.has_route_node:
        return False
    sig = node.get("signature") or ""
    return any(t in sig for t in _API_SIG_TOKENS)


def _r_route_handler(node: dict, rc: RuleContext) -> bool:
    """implDetails 路由清单：本函数是某路由 handler(仅 scope 无 route 节点时介入)。"""
    if rc.has_route_node:
        return False
    return _is_route_handler(node, rc.impl_by_file)


def _r_branch_decision(node: dict, rc: RuleContext) -> bool:
    """分支密集：优先 implDetails 真实语句计数(if/switch/case ≥2)，无则文本近似。"""
    st = rc.statements_of(node, types=("if", "switch", "case"))
    if rc.impl_by_file:
        return len(st) >= 2
    return _branch_dense_text(node)


def _r_func(node: dict, rc: RuleContext) -> bool:
    return (node.get("kind") or "").lower() in _KIND_NODE_TYPES["func"]


def _r_entity(node: dict, rc: RuleContext) -> bool:
    return (node.get("kind") or "").lower() in _KIND_NODE_TYPES["entity"]


def _r_state(node: dict, rc: RuleContext) -> bool:
    return (node.get("kind") or "").lower() in _KIND_NODE_TYPES["state"]


# 内置规则(顺序 = 优先级，与旧 _primary_kind_for_node 分支顺序等价)。
register_rule(RuleSpec("config-carrier", "rule", 10,
                       lambda n, rc: _config_carrier_signal(n)))
register_rule(RuleSpec("route-node", "contract", 20, _r_route_node))
register_rule(RuleSpec("contract-boundary", "contract", 30, _r_contract_boundary))
register_rule(RuleSpec("route-handler", "contract", 40, _r_route_handler))
register_rule(RuleSpec("enum-state", "state", 50, _r_state))
register_rule(RuleSpec("type-entity", "entity", 60, _r_entity))
register_rule(RuleSpec("branch-decision", "decision", 70,
                       lambda n, rc: _r_func(n, rc) and _r_branch_decision(n, rc)))
register_rule(RuleSpec("func-process", "process", 80, _r_func))


def classify(node: dict, rc: RuleContext) -> str:
    """规则定类别。首条命中即返回；无命中返回 ''(该符号不是资产候选)。"""
    for r in _RULES:
        try:
            if r.predicate(node, rc):
                return r.kind
        except Exception:
            continue
    return ""


# ── 值得提取(量化过滤) ─────────────────────────────────────────


def _node_span(node: dict) -> int:
    try:
        s = int(node.get("start_line") or 0)
        e = int(node.get("end_line") or 0)
        return max(0, e - s + 1)
    except (TypeError, ValueError):
        return 0


def worth_extracting(node: dict, kind: str, rc: RuleContext) -> bool:
    """量化过滤：挡掉无实体的空壳/纯噪音符号，保留一切有内容的候选。

    阈值保守(宁多勿漏)：误杀比漏提更伤(实体覆盖是本次重构核心目标)。
    """
    nk = (node.get("kind") or "").lower()
    span = _node_span(node)
    if span <= 1:
        # live 扫描退化行号(start==end)→ 行号不可信，保留(种子会源码回读)
        return True
    if kind == "entity":
        members = rc.members_of(node)
        if members:
            return True
        fields = node.get("fields")
        if isinstance(fields, list) and fields:
            return True
        return span >= 2  # 有类体(哪怕 pass)即保留；单行前向声明跳过
    if kind == "state":
        members = rc.members_of(node, kinds=("variable", "field", "constant",
                                            "enum_member"))
        return bool(members) or span >= 2
    if kind in ("process", "decision"):
        if span < 2:
            # 退化行(live 扫描)：有调用/语句/被调则保留
            if rc.callees_of(node) or rc.statements_of(node) or rc.callers_of(node):
                return True
            return not (node.get("name") or "").startswith("_")
        return True
    if kind == "contract":
        return True  # 路由/边界端点全保留
    if kind == "rule":
        return span >= 1
    return True


# ── 关联范围装配(每候选确定性上下文) ───────────────────────────


def _src_slice(root: str, node: dict, max_lines: int = 120) -> str:
    """类体/函数体源码切片(entity 字段识别权威源)。失败返回 ''。"""
    if not root or not node.get("file_path"):
        return ""
    rel = (node.get("file_path") or "").lstrip("/")
    full = os.path.join(root, rel.replace("/", os.sep))
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except Exception:
        return ""
    s0 = int(node.get("start_line") or 0)
    s1 = int(node.get("end_line") or s0)
    if s1 < s0:
        s1 = s0
    body = lines[s0 - 1:s1] if s0 >= 1 else []
    if len(body) <= 2:
        body = lines[s0 - 1:s0 - 1 + 80]
    return "\n".join(body[:max_lines])


_FIELD_PAT = re.compile(r"^\s*([A-Za-z_]\w*)\s*:\s*([^=#]+?)\s*(?:=.*)?$")
_SELF_PAT = re.compile(r"^\s*self\.([A-Za-z_]\w*)\s*=")
_ROUTE_NAME_PAT = re.compile(r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(/\S*)$",
                             re.IGNORECASE)


def fields_from_source_text(src: str, max_fields: int = 40) -> List[dict]:
    """源码文本 → 字段(注解 `name: type` + `self.x =`)。纯文本确定性解析。"""
    out, seen = [], set()
    for ln in (src or "").split("\n"):
        m = _FIELD_PAT.match(ln)
        name = m.group(1).strip() if m else None
        ftype = m.group(2).strip().rstrip(",").strip() if m else ""
        if not name:
            ms = _SELF_PAT.match(ln)
            if not ms:
                continue
            name = ms.group(1)
            ftype = ""
        if name.startswith("_") and name.endswith("__"):
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "type": ftype or ""})
        if len(out) >= max_fields:
            break
    return out


def entity_fields(root: str, node: dict) -> List[dict]:
    """entity 种子字段：节点 fields 属性 → 成员边 → 源码回读(注解字段/self.x)。"""
    fields = node.get("fields")
    if isinstance(fields, list) and fields:
        out = []
        for f in fields:
            if isinstance(f, str):
                out.append({"name": f, "type": ""})
            elif isinstance(f, dict) and f.get("name"):
                out.append({"name": str(f["name"]), "type": f.get("type") or ""})
        if out:
            return out[:40]
    return fields_from_source_text(_src_slice(root, node))


def assemble_context(node: dict, kind: str, rc: RuleContext,
                     root: str = "") -> dict:
    """每候选关联范围 → 种子数据(确定性)。同节点永远同输出。

    返回 {fields|relations|branches|steps|conditions|states|transitions|constraints, source}
    —— 作为 LLM 定向提取的预填数据与验收溯源基准。
    """
    from .semantic_assets import (_callee_names, _constants_from_impl,
                                  _fields_from_node, _member_fields_from_edges,
                                  _relations_from_routes)
    seed: Dict[str, object] = {}
    impl = rc.impl(node)
    if kind == "entity":
        fields = _fields_from_node(node)
        if not fields:
            fields = _member_fields_from_edges(node.get("id"), rc.edges, rc.node_by_id)
        if not fields:
            fields = entity_fields(root, node)
        seed["fields"] = fields
        seed["source"] = _src_slice(root, node) if not fields else ""
    elif kind == "contract":
        rels = _relations_from_routes(rc.impl_by_file, node)
        if not rels and (node.get("kind") or "").lower() == "route":
            # implDetails 缺失时，route 节点名本身即 ground truth(POST /x → http 关系)
            m = _ROUTE_NAME_PAT.match((node.get("name") or "").strip())
            if m:
                meth, path = m.group(1).upper(), m.group(2)
                rels = [{"target": path, "type": "http", "methods": [meth],
                         "line": int(node.get("start_line") or 0),
                         "semantic": f"{meth} {path}"}]
        seed["relations"] = rels
        if not rels:
            seed["signature"] = node.get("signature") or ""
    elif kind == "decision":
        seed["branches"] = [{"condition": (s.get("condition") or "").strip(),
                             "line": int(s.get("startLine") or 0)}
                            for s in rc.statements_of(node, types=("if", "switch", "case"))]
    elif kind == "state":
        members = rc.members_of(node, kinds=("variable", "field", "constant",
                                            "enum_member"))
        states = [{"name": m.get("name") or f"s{i}", "initial": i == 0,
                   "final": i == len(members) - 1}
                  for i, m in enumerate(members)]
        seed["states"] = states
        seed["transitions"] = [{"from": states[i]["name"], "to": states[i + 1]["name"],
                                "event": "", "condition": "", "action": ""}
                               for i in range(len(states) - 1)]
    elif kind == "rule":
        seed["constraints"] = _constants_from_impl(rc.impl_by_file, node)
        seed["configSource"] = node.get("file_path") or ""
    else:  # process
        name_of = {n.get("id"): (n.get("qualified_name") or n.get("name") or "")
                   for n in rc.node_by_id.values()}
        for k, v in rc.extra_names.items():
            if v:
                name_of.setdefault(k, v)
        callees = _callee_names(node.get("id"), rc.edges, name_of)
        seed["steps"] = [{"order": i, "symbol": c} for i, c in enumerate(callees, 1)]
        seed["conditions"] = [(s.get("condition") or "").strip()
                              for s in rc.statements_of(node)
                              if (s.get("condition") or "").strip()][:8]
    return seed


def candidates_for_file(root: str, file_nodes: List[dict], rc: RuleContext,
                        kinds: Optional[List[str]] = None
                        ) -> List[dict]:
    """文件内节点 → 候选表 [{node, kind, seed}]。类别定死 + 量化过滤 + 种子装配。"""
    want = set(kinds) if kinds else None
    out = []
    for n in file_nodes:
        k = classify(n, rc)
        if not k or (want and k not in want):
            continue
        if not worth_extracting(n, k, rc):
            continue
        try:
            seed = assemble_context(n, k, rc, root)
        except Exception:
            seed = {}
        out.append({"node": n, "kind": k, "seed": seed})
    out.sort(key=lambda c: int(c["node"].get("start_line") or 0))
    return out
