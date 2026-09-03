"""semantic_assets 引擎核心（A1-T2：提取/持久化/聚合/生命周期/简介/关系/影响）。

T2 九段经 AST 依赖分析确认为单一强连通分量（reconcile→extract_scope→search 等
互调真实存在），机械切分必然成环 —— 故合为本引擎模块；可独立拆分的分类法/
路径/codegraph/范围/符号上下文/锚点/增量 七类基础设施已拆至同级 T1 模块。
路由随段就地注册（router 驻留 sem/__init__），facade 仅 26 条路由映射。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import store
from ..common import _ts, err, ok  # noqa: F401
from . import router
from .anchors import _attach_step_refs, _node_to_ref, logger, resolve_ast_refs
from fastapi import Request

from .codegraph import ensure_synced, logger
from .symbols import open_symbol_conn
from .context import _kb_parse_file, _norm_cache_symbol, _rebuild_edges_from_refs, collect_context, logger
from .incremental import _anchor_hashes, _cache_content_hash, _canonical_key, _file_md5, logger
from .paths import _norm_path, logger, project_id_for, resolve_root
from .scope import _asset_scope_membership, _comm_files, _file_to_components, logger
from .taxonomy import SEMANTIC_KINDS, SEMANTIC_LEVELS, _id_prefix, logger

logger = logging.getLogger(__name__)


# ═══ queries（原第 queries 段，纯移动）═══
_RECONCILE_AT: Dict[str, float] = {}
_RECONCILE_INTERVAL = 30.0  # 秒


from . import router




def _lazy_reconcile(root: Optional[str], project: Optional[str], force: bool = False) -> None:
    """惰性 reconcile(入口限频)：读取/注入前确保资产新鲜度判定。"""
    try:
        root = resolve_root(root, project)
        if not root:
            return
        pid = project_id_for(root, project)
        import time as _t
        last = _RECONCILE_AT.get(pid, 0.0)
        now = _t.time()
        if not force and (now - last) < _RECONCILE_INTERVAL:
            return
        _RECONCILE_AT[pid] = now
        reconcile_semantic(root, project, force=force)
    except Exception as e:
        logger.warning("[semantic] lazy reconcile failed: %s", e)



def search(root: Optional[str], project: Optional[str],
           text: str = "", kind: str = "", limit: int = 20, offset: int = 0,
           scopes: Optional[List[str]] = None, level: str = "") -> List[dict]:
    _lazy_reconcile(root, project)
    pid = project_id_for(root, project)
    return store.SemanticAssetsStore.search(pid, text, kind, limit, offset,
                                            scopes=scopes, level=level)


def detail(asset_id: str, root: Optional[str] = None,
           project: Optional[str] = None) -> Optional[dict]:
    _lazy_reconcile(root, project)
    return store.SemanticAssetsStore.get(asset_id)


def _grouped_search_items(root: Optional[str], project: Optional[str],
                          q: str, kind: str, limit: int, offset: int,
                          scopes: Optional[List[str]], level: str) -> List[dict]:
    """取分页列表并按「所属组件」分组排序，保证同一组件的语义资产不跨页分散。

    组件目录(树 DFS)决定组件先后，未归属组件的资产(「其它」)排最后；
    组件内按 updated_at 倒序。先取全量再在服务端排序分页(项目规模可控)。
    """
    pid = project_id_for(root, project)
    total = store.SemanticAssetsStore.count(pid, q, kind, scopes=scopes, level=level)
    fetch = max(int(total), 1) + 1
    rows = store.SemanticAssetsStore.search(pid, q, kind, limit=fetch, offset=0,
                                            scopes=scopes, level=level)
    order, file_to_comp = _component_order_map(root, project)
    if not order:
        return rows[int(offset):int(offset) + int(limit)]

    def cidx(a: dict) -> int:
        sk = a.get("scopeKey") or ""
        if sk in order:
            return order[sk]
        refs = a.get("astRefs") or []
        if refs:
            f = _norm_path((refs[0].get("file") or "") if isinstance(refs[0], dict) else "")
            c = file_to_comp.get(f)
            if c and c in order:
                return order[c]
        return 10 ** 9

    rows.sort(key=lambda a: (cidx(a), -(a.get("updatedAt") or 0)))
    return rows[int(offset):int(offset) + int(limit)]


def _component_order_map(root: Optional[str], project: Optional[str]):
    """组件 → 展示顺序(树 DFS，父在前) 与 文件 → 组件 映射(列表按组件分组排序用)。"""
    order: Dict[str, int] = {}
    file_to_comp: Dict[str, str] = {}
    try:
        from .common import build_component_catalog
        comps = (build_component_catalog(root, project) or {}).get("components") or []
    except Exception as e:
        logger.warning("[semantic] component order map failed: %s", e)
        comps = []
    idx = 0
    seen: set = set()

    def walk(parent: Optional[str]) -> None:
        nonlocal idx
        for c in comps:
            if (c.get("parentId") or None) != parent:
                continue
            cid = c.get("id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            order[cid] = idx
            idx += 1
            for f in c.get("owns") or []:
                if f:
                    file_to_comp.setdefault(_norm_path(f), cid)
            walk(cid)
    walk(None)
    return order, file_to_comp


def _scope(body: dict) -> tuple:
    scope = body.get("scope") or {}
    return (scope.get("type") or body.get("scopeType") or "project",
            scope.get("key") or body.get("scopeKey") or "",
            scope.get("files") or body.get("files") or [],
            scope.get("symbols") or body.get("symbols") or [])


@router.get("/kb/semantic/search")
async def api_search(q: str = "", kind: str = "",
                     root: Optional[str] = None, project: Optional[str] = None,
                     limit: int = 100, offset: int = 0, scope: str = "",
                     level: str = ""):
    """分页检索：返回 items + total(超出 limit 翻页用)。

    scope: 逗号分隔的组件范围(scope_key 精确匹配)；空=全部。
    level: 抽象粒度过滤(high|medium|low)；空=全部。
    默认按「所属组件」分组排序返回，同一组件资产保持连续，不跨页分散。
    """
    _lazy_reconcile(root, project)
    scopes = [s.strip() for s in (scope or "").split(",") if s.strip()] or None
    lvl = level if level in SEMANTIC_LEVELS else ""
    items = _grouped_search_items(root, project, q, kind, limit, offset, scopes, lvl)
    pid = project_id_for(root, project)
    total = store.SemanticAssetsStore.count(pid, q, kind, scopes=scopes, level=lvl)
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})

def reconcile_semantic(root: Optional[str], project: Optional[str],
                       force: bool = False) -> Dict[str, Any]:
    """校验并失效过期资产(惰性 reconcile 的主逻辑)。

    1) git diff / 哈希比对 → 变更文件；
    2) modified 文件 → 按 anchor 哈希比对失效(仅内容真正变化时)；
       deleted 文件 → 直接失效；
    3) added 文件反向探测 → 受影响文件的资产一并失效(force)；
    4) 返回统计(不自动重提；重提由 refresh/handle_stale_asset 触发)。
    """
    root = resolve_root(root, project)
    if not root:
        return {"stale": 0, "active": 0, "changed": [], "newFiles": [], "affectedFiles": []}
    pid = project_id_for(root, project)
    ch = changed_files(root, project)
    changed = sorted(set(ch["added"]) | set(ch["modified"]) | set(ch["deleted"]))
    invalidated: List[str] = []
    if ch["modified"]:
        invalidated += invalidate_assets_for_files(
            pid, ch["modified"], change="modified", reason="文件内容变更",
            root=root, force=False)
    if ch["deleted"]:
        invalidated += invalidate_assets_for_files(
            pid, ch["deleted"], change="deleted", reason="锚定文件已删除",
            root=root, force=True)
    affected: List[str] = []
    if ch["added"]:
        probe = probe_impact(root, project, ch["added"])
        affected = probe.get("affectedFiles") or []
        invalidated += invalidate_assets_for_files(
            pid, affected, change="modified", reason="新文件依赖影响",
            root=root, force=True)
    invalidated = list(dict.fromkeys(invalidated))
    rows = store.SemanticAssetsStore.all_status(pid, limit=4000)
    stale = sum(1 for a in rows if a.get("status") == "stale")
    active = sum(1 for a in rows if a.get("status") == "active")
    return {"stale": stale, "active": active, "invalidated": invalidated,
            "changed": changed, "newFiles": ch["added"], "affectedFiles": affected}


_RECONCILE_AT: Dict[str, float] = {}
_RECONCILE_INTERVAL = 30.0  # 秒


# ═══ extract（原第 extract 段，纯移动）═══
# ── LLM 提取 ──────────────────────────────────────────────────

_KIND_ALIASES = {
    # 新 canonical(6 类)
    "entity": "entity", "contract": "contract", "state": "state",
    "rule": "rule", "process": "process", "decision": "decision",
    "实体": "entity", "契约": "contract", "状态": "state",
    "规则": "rule", "过程": "process", "决策": "decision",
    # 静态·定义：旧 asset/structure → entity
    "asset": "entity",
    "静态资产": "entity",
    "structure": "entity",
    "结构": "entity",
    "data_structure": "entity",
    "数据结构": "entity",
    "datastructure": "entity",
    "data structure": "entity",
    "data-structure": "entity",
    "data_structure类": "entity",
    "domain_entity": "entity",
    "concrete_type": "entity",
    "config_item": "entity",
    "配置项": "entity",
    # contract
    "interface": "contract",
    "接口": "contract",
    "api": "contract",
    "service_contract": "contract",
    "message_contract": "contract",
    "business_contract": "contract",
    "business_capability": "contract",
    "transport_contract": "contract",
    # state
    "state_machine": "state",
    "状态机": "state",
    "lifecycle": "state",
    "生命周期": "state",
    "state_flow": "state",
    "transition_logic": "state",
    "resource_lifecycle": "state",
    # rule(配置化定义) vs decision(运行时执行)
    "business_rule": "rule",
    "业务规则": "rule",
    "policy": "rule",
    "business_policy": "rule",
    "业务政策": "rule",
    "策略": "rule",
    # process
    "behavior": "process",
    "行为": "process",
    "行为过程": "process",
    "processing_flow": "process",
    "处理流程": "process",
    "processingflow": "process",
    "process flow": "process",
    "process-flow": "process",
    "processing": "process",
    "流程": "process",
    "flow": "process",
    "call_chain": "process",
    "business_process": "process",
    "concurrent_flow": "process",
    # decision
    "control_logic": "decision",
    "控制逻辑": "decision",
    "controllogic": "decision",
    "control logic": "decision",
    "control-logic": "decision",
    "logic": "decision",
    "分支": "decision",
    "branch_logic": "decision",
    "branch": "decision",
}

_LEVEL_ALIASES = {
    # 新 canonical(三档)
    "business": "business", "logic": "logic", "implementation": "implementation",
    "业务": "business", "功能": "business", "概念": "business",
    "逻辑": "logic", "设计": "logic",
    "实现": "implementation", "代码": "implementation",
    # 旧 high → business
    "high": "business",
    "高": "business",
    "conceptual": "business",
    "intent": "business",
    "意图": "business",
    "战略": "business",
    # 旧 medium → logic
    "medium": "logic",
    "中": "logic",
    "logical": "logic",
    "design": "logic",
    "interaction": "logic",
    "交互": "logic",
    # 旧 low → implementation
    "low": "implementation",
    "低": "implementation",
    "code": "implementation",
    "algorithm": "implementation",
    "算法": "implementation",
}


def _normalize_kind(raw: Any) -> Optional[str]:
    """LLM 返回的 kind/type → 规范枚举。兼容中文/驼峰/带空格/横线等变体。"""
    if not raw:
        return None
    s = str(raw).strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    if s in SEMANTIC_KINDS:
        return s
    for k, canonical in _KIND_ALIASES.items():
        if k.lower().replace(" ", "").replace("-", "").replace("_", "") == s:
            return canonical
    return None


def _normalize_level(raw: Any) -> Optional[str]:
    """LLM 返回的 level(可选) → 规范枚举；未提供返回 None(调用方默认 medium)。"""
    if not raw:
        return None
    s = str(raw).strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    if s in SEMANTIC_LEVELS:
        return s
    for k, canonical in _LEVEL_ALIASES.items():
        if k.lower().replace(" ", "").replace("-", "").replace("_", "") == s:
            return canonical
    return None


# ── 启发式降级 ────────────────────────────────────────────────

# 配置载体命名信号(角色判定：命中 → 倾向静态 Rule)。
_CONFIG_CARRIER_NAMES = (
    "config", "settings", "threshold", "policy", "rule", "quota", "limit",
    "allowlist", "denylist", "blacklist", "whitelist", "strategy", "feature_flag",
)
# 配置读写 API 签名信号(如 `get_config(key, default)` / `set_threshold(key, value)`)。
_CONFIG_ACCESS_SIG = ("key", "default", "get_", "set_", "load_", "read_")


def _config_carrier_signal(node: dict) -> bool:
    """强信号①：符号本身是配置载体(Config/Settings/Thresholds 类、_DEFAULT_* 常量、config 读写 API)。

    变量仅按名称/取值特征判定(避免 router/_templates/app/logger 等普通实例变量误判)。
    """
    kind = (node.get("kind") or "").lower()
    name = (node.get("name") or "").lower()
    sig = (node.get("signature") or "").lower()
    if kind == "variable":
        # 仅名称含配置语义才判(router/FastAPI/Jinja2/logger 实例不属配置载体)。
        if name in ("config", "settings", "thresholds"):
            return True
        if name.startswith(("_default_", "default_", "_limit_", "_threshold_", "_config_",
                            "config_", "setting_", "threshold_")):
            return True
        if any(t in name for t in ("config", "settings", "threshold", "policy", "quota", "limit")):
            return True
        return False
    if name in ("config", "settings", "thresholds") or name.endswith(("_config", "_settings", "_thresholds")):
        return True
    if kind in ("class", "interface", "struct") and name.endswith(("config", "settings", "thresholds", "policy")):
        return True
    if name.startswith(("_default_", "default_", "_limit_", "_threshold_", "_config_")):
        return True
    # 配置读写 API：get/set/load/read_xxx_config 或签名含 key+default。
    if any(prefix in name for prefix in ("get_config", "set_config", "get_threshold",
                                         "set_threshold", "load_config", "get_all_config",
                                         "get_settings", "set_settings")):
        return True
    if ("config" in name or "threshold" in name or "setting" in name) \
            and ("key" in sig or "default" in sig):
        return True
    return False


# ── 实现层主类别分配(每符号只产一个资产，消除跨类别重复) ──────────────

# 路由/api 边界的命名与装饰器信号(实现层 contract 的判定)。
_API_NAME_PREFIXES = ("api_", "handle_", "handler_")
_API_SIG_TOKENS = ("Request", "Depends", "Response", "Form(", "Body(")


def _is_contract_boundary_node(node: dict, edges: List[dict],
                               name_of: Optional[Dict[str, str]] = None,
                               node_by_id: Optional[Dict[str, dict]] = None) -> bool:
    """契约边界信号：route 节点；无 route 节点时的 api_* 前缀处理函数。

    - route 节点 → contract(API 端点，锚点即路由)。
    - 被 route 节点 references 引用的处理函数 → 该端点已有契约，函数本身归 process
      (实现层契约/过程不重复：同一端点 契约(路由) + 过程(处理函数) 两个资产)。
    - 无 route 节点(如 codegraph 未解析路由)时，api_*/handle_* 前缀函数退化为契约。
    内部业务函数(get_config/send_sms_code 等)不标契约。
    """
    kind = (node.get("kind") or "").lower()
    if kind == "route":
        return True
    # 被 route 节点引用的处理函数 → 路由已表达契约，函数归 process/decision。
    node_id = node.get("id")
    for e in edges or []:
        if e.get("kind") == "references" and e.get("target") == node_id:
            src = e.get("source") or ""
            if str(src).startswith("route:") or str(src).startswith("node:route:"):
                return False
            if node_by_id:
                src_node = node_by_id.get(src)
                if src_node and (src_node.get("kind") or "").lower() == "route":
                    return False
    name = (node.get("name") or "").lower()
    if name.startswith(_API_NAME_PREFIXES):
        return True
    sig = (node.get("signature") or "")
    if any(t in sig for t in _API_SIG_TOKENS):
        return True
    return False


def _branch_dense(node: dict) -> bool:
    """分支密集判定(实现层 decision)：函数体内 if/elif/for/while/match 命中 ≥2。

    以 signature/docstring 中的控制流词频近似(无源码读取时仍确定性)。
    """
    text = f"{node.get('signature') or ''} {node.get('docstring') or ''}".lower()
    hits = sum(1 for tok in ("if ", "elif", "else", "for ", "while ", "case ", "match ",
                             "switch", "==", "!=", " is ", " in ")
                if tok in text)
    return hits >= 2


# ── implDetails 消费辅助(KB 语句/路由/常量 → 资产 detail) ───────────

def _impl_for_file(impl_by_file: Optional[Dict[str, dict]], node: dict) -> dict:
    return (impl_by_file or {}).get(node.get("file_path") or "") or {}


def _branches_from_impl(impl_by_file: Optional[Dict[str, dict]], node: dict,
                        types: tuple = ("if", "switch", "case")) -> List[dict]:
    """implDetails 控制流语句清单 → branches(condition=代码原文，带行号)。"""
    branches: List[dict] = []
    impl = _impl_for_file(impl_by_file, node)
    for s in impl.get("statements") or []:
        if s.get("enclosing") != node.get("name"):
            continue
        if s.get("type") not in types:
            continue
        branches.append({
            "condition": (s.get("condition") or "").strip(),
            "then": "", "else": "",
            "line": int(s.get("startLine") or 0),
            "semantic": f"{s.get('type')} 分支: {node.get('name')}",
            "symbols": [node.get("name")],
        })
        if len(branches) >= 12:
            break
    return branches


def _relations_from_routes(impl_by_file: Optional[Dict[str, dict]], node: dict) -> List[dict]:
    """implDetails 路由清单 → contract relations(真实 path/methods/handler)。

    route 节点只匹配自己的 path(节点名含该 path)；函数节点仅当其是某路由的
    handler 时匹配。
    """
    rels: List[dict] = []
    impl = _impl_for_file(impl_by_file, node)
    is_route = (node.get("kind") or "").lower() == "route"
    node_text = f"{node.get('name') or ''} {node.get('qualified_name') or ''}"

    def _path_hit(path: str) -> bool:
        if not path:
            return False
        return re.search(re.escape(path) + r"(?![\w-])", node_text) is not None

    for r in impl.get("routes") or []:
        if is_route:
            if not _path_hit(r.get("path") or ""):
                continue
        elif r.get("handler") != node.get("name"):
            continue
        methods = r.get("methods") or ["GET"]
        rels.append({"target": r.get("path", ""), "type": "http",
                     "methods": methods,
                     "line": int(r.get("line") or 0),
                     "semantic": f"{'/'.join(methods)} {r.get('path', '')}"})
        if len(rels) >= 20:
            break
    return rels


def _constants_from_impl(impl_by_file: Optional[Dict[str, dict]], node: dict) -> List[dict]:
    """implDetails 常量值清单 → 配置约束项(同文件，name=value+行号)。"""
    impl = _impl_for_file(impl_by_file, node)
    return [{"name": c.get("name", ""), "value": c.get("value", ""),
             "line": int(c.get("line") or 0)}
            for c in (impl.get("constants") or [])[:50]]


def _is_route_handler(node: dict, impl_by_file: Optional[Dict[str, dict]]) -> bool:
    """implDetails 路由元数据: 本函数是某路由 handler → 契约边界
    (覆盖 codegraph 无 route 节点时的判定缺口)。"""
    if not impl_by_file:
        return False
    name = node.get("name") or ""
    if not name:
        return False
    impl = impl_by_file.get(node.get("file_path") or "") or {}
    return any(r.get("handler") == name for r in impl.get("routes") or [])


def _primary_kind_for_node(node: dict, edges: List[dict],
                           name_of: Optional[Dict[str, str]] = None,
                           node_by_id: Optional[Dict[str, dict]] = None,
                           impl_by_file: Optional[Dict[str, dict]] = None) -> str:
    """实现层每符号只产一个主类别(信号优先，避免跨类别重复)：

    rule(配置载体) > contract(路由/api 边界) > entity(类型) / state(枚举)
    > decision(分支密集) > process(普通函数)。
    impl_by_file 仅在 scope 无 route 节点时传入(有 route 节点时边逻辑已覆盖 handler 归属)。
    """
    kind = (node.get("kind") or "").lower()
    if _config_carrier_signal(node):
        return "rule"
    if _is_contract_boundary_node(node, edges, name_of, node_by_id):
        return "contract"
    if impl_by_file is not None and _is_route_handler(node, impl_by_file):
        return "contract"
    if kind == "enum":
        return "state"
    if kind in ("class", "interface", "struct", "component"):
        return "entity"
    if kind in ("function", "method"):
        if _branch_dense(node):
            return "decision"
        return "process"
    return ""


def _heuristic_extract_primary(ctx: Dict[str, Any],
                               kinds: List[str],
                               level: str = "implementation") -> List[dict]:
    """实现层单趟提取：每个符号只产一个主类别资产(消除跨类别重复)。

    与 `_heuristic_extract`(按 kind 全量扫)不同，本函数按 `_primary_kind_for_node`
    为每个节点分配唯一主类别，并复用各类别 detail 构造逻辑产出资产。
    """
    nodes = ctx.get("nodes") or []
    edges = ctx.get("edges") or []
    root = ctx.get("root") or ""
    node_by_id = {n.get("id"): n for n in nodes}
    name_of = {n.get("id"): (n.get("qualified_name") or n.get("name") or "") for n in nodes}
    impl_by_file = ctx.get("implDetails")
    # scope 已有 route 节点时，handler 归属由边逻辑判定，impl 路由判定不介入(防重复)。
    has_route_node = any((n.get("kind") or "").lower() == "route" for n in nodes)
    out: List[dict] = []
    per_kind_cap: Dict[str, int] = {}
    for n in nodes:
        pk = _primary_kind_for_node(n, edges, name_of, node_by_id,
                                    None if has_route_node else impl_by_file)
        if not pk or pk not in kinds:
            continue
        if per_kind_cap.get(pk, 0) >= _IMPL_KIND_CAP:
            continue
        per_kind_cap[pk] = per_kind_cap.get(pk, 0) + 1
        if pk == "entity":
            doc = (n.get("docstring") or "").strip()
            fields = _fields_from_node(n) or _member_fields_from_edges(n.get("id"), edges, node_by_id)
            if not fields:
                fields = _fields_from_source(root, n)
            out.append({"kind": "entity", "level": level, "name": n["name"],
                        "desc": doc or f"具体类型「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。",
                        "detail": {"kind": "type", "signature": n.get("signature") or "",
                                   "fields": fields, "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
        elif pk == "state":
            members = _member_fields_from_edges(n.get("id"), edges, node_by_id)
            if not members:
                continue
            states = [{"name": m.get("name") or f"s{i}", "desc": "",
                       "initial": i == 0, "final": i == len(members) - 1}
                      for i, m in enumerate(members)]
            transitions = [{"from": states[i]["name"], "to": states[i + 1]["name"],
                            "event": "", "condition": "", "action": ""}
                           for i in range(len(states) - 1)]
            out.append({"kind": "state", "level": level, "name": n["name"],
                        "desc": f"实体生命周期「{n['name']}」的状态机(枚举推导)。",
                        "detail": {"states": states, "transitions": transitions, "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
        elif pk == "rule":
            doc = (n.get("docstring") or "").strip()
            out.append({"kind": "rule", "level": level, "name": n["name"],
                        "desc": doc or f"配置/阈值「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。",
                        "detail": {"kind": "config_item", "configSource": n.get("file_path") or "",
                                   "constraints": _constants_from_impl(impl_by_file, n),
                                   "thresholds": []},
                        "astRefs": [_node_to_ref(n)]})
        elif pk == "contract":
            sig = n.get("signature") or ""
            doc = (n.get("docstring") or "").strip()
            # route 节点本身无签名/文档：取被其引用的处理函数签名补全。
            if n.get("kind") == "route":
                for e in edges or []:
                    if e.get("kind") != "references" or e.get("source") != n.get("id"):
                        continue
                    h = node_by_id.get(e.get("target"))
                    if h and (h.get("signature") or h.get("docstring")):
                        if not sig:
                            sig = h.get("signature") or ""
                        if not doc:
                            doc = (h.get("docstring") or "").strip()
                        break
            rels = _relations_from_routes(impl_by_file, n)
            if not rels:
                rels = [{"target": "", "type": "signature", "semantic": sig}]
            ep = next((f"{'/'.join(r.get('methods') or ['GET'])} {r.get('target', '')}"
                       for r in rels if r.get("type") == "http"), "")
            out.append({"kind": "contract", "level": level, "name": n["name"],
                        "desc": doc or (f"服务契约「{n['name']}」({ep})，位于 {n['file_path']}:{n['start_line']}。"
                                        if ep else
                                        f"服务契约「{n['name']}」，签名 ({sig})，位于 {n['file_path']}:{n['start_line']}。"),
                        "detail": {"kind": "message_contract", "relations": rels,
                                   "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
        elif pk == "decision":
            sig = n.get("signature") or ""
            doc = (n.get("docstring") or "").strip()
            branches = _branches_from_impl(impl_by_file, n)
            if not branches:
                branches = [{"condition": "", "then": "", "else": "",
                             "semantic": f"分支判定: {n['name']}", "symbols": [n["name"]]}]
            out.append({"kind": "decision", "level": level, "name": n["name"],
                        "desc": doc or f"分支逻辑「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。",
                        "detail": {"kind": "branch_logic", "branches": branches,
                                   "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
        else:  # process
            callees = _callee_names(n.get("id"), edges, name_of)
            branches = _branches_from_impl(
                impl_by_file, n, types=("if", "switch", "case", "loop"))
            sig = n.get("signature") or ""
            doc = (n.get("docstring") or "").strip()
            out.append({"kind": "process", "level": level, "name": n["name"],
                        "desc": doc or f"调用链「{n['name']}」，签名 ({sig})，位于 {n['file_path']}:{n['start_line']}。",
                        "detail": {"trigger": "", "kind": "call_chain",
                                   "steps": [{"order": i, "semantic": "调用 " + c, "symbols": [c]}
                                             for i, c in enumerate(callees, 1)],
                                   "conditions": [b["condition"] for b in branches
                                                  if b.get("condition")][:8],
                                   "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
    return out


def _fields_from_node(n: dict) -> List[dict]:
    """低粒度：尽力从节点信息提取字段(签名/字段符号已由 codegraph 解析时直接给)。
    无字段符号数据时返回空(真实锚点仍保留)。"""
    fields = n.get("fields")
    if isinstance(fields, list):
        out = []
        for f in fields:
            if isinstance(f, str):
                out.append({"name": f, "type": ""})
            elif isinstance(f, dict) and f.get("name"):
                out.append({"name": str(f["name"]), "type": f.get("type") or ""})
        return out
    return []


def _fields_from_source(root: str, n: dict, max_fields: int = 40) -> List[dict]:
    """源码回读扫描实体字段(类/结构体体内声明)，供 class/ER 图展示属性。

    覆盖多种声明形态：
      - `name: type`(含 dataclass `name: type = default`)
      - `self.name = ...`(__init__ 内实例属性)
      - `name = type(...)`(结构体/值对象字段)
    读取失败返回空列表(不影响锚点保留)。
    """
    if not root or not n or not (n.get("start_line") or 0):
        return []
    rel = (n.get("file_path") or "").lstrip("/")
    full = os.path.join(root, rel.replace("/", os.sep))
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except Exception:
        return []
    s0 = int(n.get("start_line") or 0)
    s1 = int(n.get("end_line") or s0)
    if s1 < s0:
        s1 = s0
    # 退化范围(live 扫描 end_line==start_line)：放宽到类声明后 80 行内，防漏字段。
    body = lines[s0 - 1:s1] if s0 >= 1 else []
    if len(body) <= 2:
        body = lines[s0 - 1:s0 - 1 + 80]
    fields: List[dict] = []
    seen: set = set()
    # ① 类体内顶层 `name: type` / `name: type = value`(dataclass/注解字段)。
    pat_ann = re.compile(r"^\s*([A-Za-z_]\w*)\s*:\s*([^=#]+?)\s*(?:=.*)?$")
    for ln in body:
        m = pat_ann.match(ln)
        if not m:
            continue
        name = m.group(1).strip()
        ftype = m.group(2).strip().rstrip(",").strip()
        if name.startswith("_") and name.endswith("__"):
            continue
        if name in seen:
            continue
        seen.add(name)
        fields.append({"name": name, "type": ftype or ""})
        if len(fields) >= max_fields:
            break
    # ② __init__ 内 `self.name = ...` 实例属性(Python 类常见无注解字段)。
    if len(fields) < max_fields:
        pat_self = re.compile(r"^\s*self\.([A-Za-z_]\w*)\s*=")
        for ln in body:
            m = pat_self.match(ln)
            if not m:
                continue
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            fields.append({"name": name, "type": ""})
            if len(fields) >= max_fields:
                break
    return fields[:max_fields]


def _callee_names(node_id: str, edges: List[dict],
                  name_of: Optional[Dict[str, str]] = None) -> List[str]:
    """低粒度调用链：取 1-hop 直接调用目标符号名(经 name_of 把节点 id 解析为符号名)。

    按边 line 排序恢复函数体内的真实调用顺序(无 line 的边保持原相对序)。
    """
    out: List[str] = []
    for i, e in enumerate(edges or []):
        if e.get("kind") == "calls" and e.get("source") == node_id and e.get("target"):
            t = e["target"]
            ln = e.get("line")
            out.append((ln if isinstance(ln, int) else 1 << 30, i,
                        name_of.get(t, t) if name_of else t))
    out.sort(key=lambda x: (x[0], x[1]))
    names = [n for _, _, n in out]
    return list(dict.fromkeys(names))[:8]


def _member_fields_from_edges(node_id: str, edges: List[dict],
                              node_by_id: Dict[str, dict]) -> List[dict]:
    """低粒度结构字段：经 contains 边取类节点的成员符号(变量/字段/常量/方法)。"""
    out: List[dict] = []
    member_kinds = ("variable", "field", "property", "constant", "enum_member")
    for e in edges or []:
        if e.get("kind") != "contains" or e.get("source") != node_id:
            continue
        n = node_by_id.get(e.get("target"))
        if not n or n.get("kind") not in member_kinds:
            continue
        nm = n.get("name")
        if not nm:
            continue
        out.append({"name": nm, "type": n.get("return_type") or n.get("signature") or ""})
    return out[:60]



_IMPL_KIND_CAP = 80


# ═══ persist（原第 persist 段，纯移动）═══



# ── 持久化(增量 change) ───────────────────────────────────────

_EDGE_SEMANTIC = {
    "calls": "调用依赖",
    "contains": "包含",
    "extends": "继承",
    "implements": "实现",
    "imports": "导入依赖",
    "references": "引用",
    "instantiates": "实例化",
    "assigns": "赋值依赖",
    "passes": "参数传递",
    "type_of": "类型引用",
    "returns": "返回",
    "overrides": "重写",
    "decorates": "装饰",
    "callback": "回调",
}


def _inherit_names(pid: str, assets: List[dict]) -> List[dict]:
    """名称继承(旧行名优先 + 墓碑承接)：re-extract 覆盖前保住用户改名。

    与 save_agent_assets 同口径，但按 canonicalKey 一次建索引(定向管线每批资产多，
    不可逐资产扫全表)。就地改写 asset['name']；返回 (assets, proposed)。
    资产身份=代码锚点(kind|level|anchors)，与组件口径无关 → 跨组件 re-extract 亦命中。
    """
    by_key: Dict[str, dict] = {}
    for old_a in store.SemanticAssetsStore.all_status(pid, limit=20000):
        ck = old_a.get("canonicalKey") or ""
        if ck and ck not in by_key:
            by_key[ck] = old_a
    for i, a in enumerate(assets):
        refs = a.get("astRefs") or []
        if not refs:
            continue
        ck = _canonical_key(a.get("kind") or "", a.get("level") or "implementation",
                            refs, name=a.get("name") or "")
        old = by_key.get(ck)
        if old:
            old_name = old.get("name") or ""
            if old_name and old_name != (a.get("name") or ""):
                a = dict(a)
                a["name"] = old_name  # 旧行名优先，re-extract 不覆盖用户改名
                assets[i] = a
        else:
            f0 = (refs[0] or {}).get("file") or ""
            s0 = (refs[0] or {}).get("symbol") or ""
            hits = store.NameTombstoneStore.lookup(pid, f0, s0, limit=1)
            if hits and hits[0].get("name"):
                a = dict(a)
                a["name"] = hits[0]["name"]  # 捞回历史命名
                assets[i] = a
    return assets


def _merge_high_details(payload: dict, old: dict) -> None:
    """同批合并 business 资产时聚合 detail：把旧行的 aggregates/invariants 并入新 payload，
    避免后写覆盖导致跨叶子聚合的子资产(id)与组件归属丢失。"""
    old_detail = old.get("detail") or {}
    if not isinstance(old_detail, dict):
        old_detail = {}
    new_detail = payload.get("detail") or {}
    if not isinstance(new_detail, dict):
        new_detail = {}
    # aggregates 按 assetId 去重合并
    merged: Dict[str, dict] = {}
    for agg in (old_detail.get("aggregates") or []) + (new_detail.get("aggregates") or []):
        if not isinstance(agg, dict):
            continue
        aid = agg.get("assetId") or ""
        if aid and aid not in merged:
            merged[aid] = dict(agg)
    new_detail["aggregates"] = list(merged.values())
    # invariants 去重合并
    inv = list(new_detail.get("invariants") or [])
    for v in (old_detail.get("invariants") or []):
        if v not in inv:
            inv.append(v)
    if inv:
        new_detail["invariants"] = inv
    payload["detail"] = new_detail


def _merge_relation(asset: dict, rel: dict) -> None:
    """合并一条 relations 到资产 detail(按 target+type 去重，防膨胀)。"""
    detail = asset.setdefault("detail", {})
    if not isinstance(detail, dict):
        detail = {}
        asset["detail"] = detail
    rels = detail.get("relations")
    if not isinstance(rels, list):
        rels = []
        detail["relations"] = rels
    key = (rel.get("target"), rel.get("type"))
    if any((r.get("target"), r.get("type")) == key for r in rels):
        return
    rels.append(rel)
    detail["relations"] = rels[:40]


def _derive_relations_from_edges(assets: List[dict], ctx: Dict[str, Any]) -> None:
    """从 AST 调用/包含边确定性派生资产间 relations(不依赖 LLM)。

    同一批资产中，若 A 的锚点符号调用/包含 B 的锚点符号，则给 A 补一条
    relations → B(type=边类型)。保证即使 LLM 未产出 relations，图谱也有边。
    """
    edges = ctx.get("edges") or []
    if not edges or not assets:
        return
    sym_to_node: Dict[str, dict] = {}
    for n in ctx.get("nodes") or []:
        nm = n.get("qualified_name") or n.get("name")
        if nm:
            sym_to_node[nm] = n
    # node id → 锚定该节点的资产下标
    node_to_assets: Dict[str, set] = {}
    for i, a in enumerate(assets):
        for r in (a.get("astRefs") or []):
            node = sym_to_node.get(r.get("symbol") or "")
            if not node:
                continue
            node_to_assets.setdefault(node.get("id"), set()).add(i)
    if not node_to_assets:
        return
    name_by_idx = {i: (a.get("name") or "") for i, a in enumerate(assets)}
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        if not src or src == tgt:
            continue
        src_a = node_to_assets.get(src)
        tgt_a = node_to_assets.get(tgt)
        if not src_a or not tgt_a:
            continue
        kind = e.get("kind") or "calls"
        semantic = _EDGE_SEMANTIC.get(kind, kind)
        for si in src_a:
            for ti in tgt_a:
                if si == ti:
                    continue
                _merge_relation(assets[si], {
                    "target": name_by_idx[ti], "type": kind, "semantic": semantic})


_ASSET_EXPECTED_ANCHOR_KIND = {
    "entity": ("class", "struct", "enum", "interface", "component"),
    "state": ("class", "struct", "enum", "interface"),
    "contract": ("func", "method", "route", "class"),
    "rule": ("func", "field", "variable", "class"),
    "process": ("func", "method", "route"),
    "decision": ("func", "method", "route"),
}

# 实现层单趟提取：每类资产每文件上限(避免超大文件全量产出)。

def _asset_anchor_kind_ok(kind: str, ast_refs: List[dict]) -> bool:
    """资产 kind ↔ 锚点 AST 节点 kind 一致性校验(实现层)。

    entity 只锚类型/枚举；contract 只锚函数/路由；rule 可锚函数/字段(配置载体)。
    锚点 kind 与资产类别明显冲突(如 entity 锚到 function)时判不合格 → 丢弃。
    """
    if not ast_refs:
        return True
    expected = _ASSET_EXPECTED_ANCHOR_KIND.get(kind)
    if not expected:
        return True
    for r in ast_refs:
        k = (r.get("kind") or "").lower()
        if k in expected:
            return True
    return False


def _save_assets(project_id: str, scope_type: str, scope_key: str,
                 assets: List[dict], ctx: Dict[str, Any]) -> List[dict]:
    _derive_relations_from_edges(assets, ctx)
    now = _ts()
    root = ctx.get("root") or ""
    # 资产身份 = 代码(锚点)，与提取口径无关 → 全项目按 canonicalKey 去重，
    # 避免 INCLUDE/CALL 两套组件对同一代码重复建行。
    existing = store.SemanticAssetsStore.all_status(project_id, limit=20000)
    by_key: Dict[str, dict] = {}
    by_name: Dict[str, dict] = {}
    for a in existing:
        ck = a.get("canonicalKey") or ""
        if ck:
            by_key.setdefault(ck, a)
        by_name.setdefault(a.get("name") or "", a)
    # 文件 → 归属组件(跨 INCLUDE/CALL 两套口径)。组件仅是下游投影，不参与身份。
    file_to_comps: Dict[str, List[str]] = {}
    if any(a.get("astRefs") for a in assets):
        try:
            file_to_comps = _file_to_components(root, ctx.get("project"))
        except Exception as e:
            logger.warning("[semantic] component membership map failed: %s", e)
    matched: set = set()
    saved: List[dict] = []
    # 同批内重复 canonicalKey(如按叶子聚合时多个叶子产出同名 business)：
    # 复用本批已创建/更新的行并合并 scopes，避免同批产生重复资产行。
    batch_seen: Dict[str, dict] = {}
    for a in assets:
        detail = a.get("detail") or {}
        for k in ("fields", "relations", "invariants", "trigger",
                  "steps", "branches", "aggregates"):
            if k not in detail and a.get(k):
                detail[k] = a[k]
        _attach_step_refs(detail, ctx.get("table") or {})
        ast_refs = a.get("astRefs") or []
        ast_refs = resolve_ast_refs(None, ctx.get("table") or {}, ast_refs)
        if not ast_refs and detail.get("steps"):
            for s in detail["steps"]:
                ast_refs += s.get("astRefs") or []
        if not ast_refs and detail.get("branches"):
            for b in detail["branches"]:
                ast_refs += b.get("astRefs") or []
        ast_refs = list({json.dumps(r, ensure_ascii=False, sort_keys=True): r for r in ast_refs}.values())
        # 实现层幻影拒绝：实现级资产必须锚定真实 AST 符号(0 astRefs 直接丢弃，
        # 避免 LLM 臆造名/无法解析锚点的空资产污染图谱)。
        if (a.get("level") or "logic") == "implementation":
            if not ast_refs:
                logger.warning("[semantic] 丢弃无锚点实现层资产: %s (kind=%s)", a.get("name"), a["kind"])
                continue
            if not _asset_anchor_kind_ok(a["kind"], ast_refs):
                logger.warning("[semantic] 丢弃锚点类别不符的实现层资产: %s (kind=%s anchor=%s)",
                               a.get("name"), a["kind"],
                               [(r.get("kind"), r.get("symbol")) for r in ast_refs[:2]])
                continue
        membership = _asset_scope_membership(ast_refs, file_to_comps)
        meta = {"componentId": scope_key if scope_type == "comm" else "",
                "scopes": membership}
        if scope_type == "files":
            meta["files"] = (ctx.get("files") or [])[:200]
        if scope_type == "symbols":
            meta["symbols"] = (ctx.get("symbols") or [])[:200]
        canonical_key = _canonical_key(a["kind"], a.get("level") or "logic", ast_refs,
                                       name=a.get("name") or "",
                                       scope_type=scope_type, scope_key=scope_key)
        payload = {
            "projectId": project_id, "kind": a["kind"],
            "level": a.get("level") or "logic",
            "name": a["name"], "desc": a.get("desc") or "",
            "detail": detail, "astRefs": ast_refs[:40],
            "scopeType": scope_type, "scopeKey": scope_key,
            "canonicalKey": canonical_key,
            "source": ctx.get("source") or "live",
            "srcHash": ctx.get("srcHash") or "",
            "meta": meta,
            "anchorHashes": _anchor_hashes(root, ast_refs[:40]),
            "needsUpdate": 0,
            "lastCheckedAt": now,
            "updatedAt": now,
            "parentId": a.get("parentId") or "",
        }
        old = batch_seen.get(canonical_key)
        if old is None:
            old = by_key.get(canonical_key)
        if old is None:
            legacy = by_name.get(a.get("name") or "")
            # 名称兜底仅承接「无 canonicalKey」的遗留行(迁移衔接)；
            # 已锚定的资产锚点漂移 → 视为新资产，避免误合并不同符号。
            if legacy and not legacy.get("canonicalKey"):
                old = legacy
        if old:
            matched.add(old["id"])
            payload["id"] = old["id"]
            payload["change"] = "modified" if (ctx.get("srcHash") and ctx.get("srcHash") != old.get("srcHash")) else "same"
            # 同批内重复(跨叶子同名 business)：合并 aggregates/invariants，避免后写覆盖
            # 导致丢前面叶子聚合的子资产(进而丢失其组件归属)。
            if old is batch_seen.get(canonical_key):
                _merge_high_details(payload, old)
            # LLM 改动语义命名但锚点不变 → 复用 id，仅记录 renamed 溯源。
            old_name = old.get("name") or ""
            if old_name and old_name != (a.get("name") or ""):
                payload["renamedFrom"] = old_name
                aliases = list(old.get("nameAlias") or []) if isinstance(old.get("nameAlias"), list) else []
                if old_name not in aliases:
                    aliases.append(old_name)
                if aliases:
                    payload["nameAlias"] = aliases
            if old.get("status") == "deleted":
                payload["status"] = "active"   # 软删后重新生成 → 恢复
            # 合并多组件归属：同一代码在 INCLUDE/CALL 下提取 → 归并到既有行。
            old_meta = dict((old.get("meta") or {}))
            old_scopes = old_meta.get("scopes") or []
            if isinstance(old_scopes, list):
                merged = sorted(set(old_scopes) | set(membership))
                old_meta["scopes"] = merged
                payload["meta"] = old_meta
            store.SemanticAssetsStore.update(old["id"], payload)
        else:
            lvl = a.get("level") or "logic"
            payload["id"] = store.next_id(_id_prefix(lvl, a["kind"]))
            payload["change"] = "added"
            payload["status"] = "active"
            payload["createdAt"] = now
            store.SemanticAssetsStore.create(payload)
        saved.append(store.SemanticAssetsStore.get(payload["id"]) or payload)
        # 同批内后续相同 canonicalKey(如按叶子聚合的跨叶子同名 business) → 复用本批已建行。
        batch_seen[canonical_key] = saved[-1]
    # 仅对「本范围曾有、本次未再生成」且无其它组件归属的资产标 stale：
    # 跨组件共享代码(meta.scopes 多归属)不会被某个组件的重提误标。
    for old in by_name.values():
        if old["id"] in matched:
            continue
        if old.get("scopeKey") != scope_key or old.get("scopeType") != scope_type:
            continue
        old_scopes = (old.get("meta") or {}).get("scopes") or []
        others = [s for s in old_scopes if s != scope_key]
        if others:
            continue
        store.SemanticAssetsStore.update(old["id"], {"status": "stale", "updatedAt": now})
    return saved


# ── 顶层提取入口 ──────────────────────────────────────────────

def extract_scope(root: Optional[str], project: Optional[str],
                  scope_type: str = "project", scope_key: str = "",
                  files: Optional[List[str]] = None,
                  symbols: Optional[List[str]] = None,
                  kinds: Optional[List[str]] = None,
                   model_id: Optional[str] = None,
                   use_llm: bool = True,
                   level: str = "implementation") -> Dict[str, Any]:
    """按范围提取语义资产并落库。返回 {assets, source, degraded, count}。

    level: 抽象粒度 implementation|logic|business。
      - implementation : LLM 归纳(代码事实层：字段/调用序/分支条件)，LLM 不可用降级增强启发式；
      - logic          : LLM 归纳(逻辑组织层)，LLM 不可用降级启发式；
      - business       : 由聚合层负责(按需，从已落库 logic/implementation 资产聚合)，本入口不直接生成。
    请求粒度权威：LLM 资产统一落为请求层级，一次提取只产出一级。
    degraded=True 表示 LLM 不可用(启发式兜底) 或 codegraph 缺失(轻量扫描)。
    """
    if level == "business":
        return {"assets": [], "source": "none", "degraded": False, "count": 0}
    root = resolve_root(root, project)
    if not root:
        logger.warning("[semantic] extract_scope 中止: 项目 root 解析失败 (root=%r project=%r)", root, project)
        return {"assets": [], "source": "none", "degraded": True, "count": 0}
    kinds = [k for k in (kinds or []) if k in SEMANTIC_KINDS] or list(SEMANTIC_KINDS)
    _lazy_reconcile(root, project)
    synced = ensure_synced(root)
    ctx = None
    try:
        ctx = collect_context(root, scope_type, scope_key, files, symbols, project)
    except Exception as e:
        logger.exception("[semantic] collect_context 异常: scope=%s(%s)", scope_type, scope_key or "-")
        return {"assets": [], "source": "error", "degraded": True, "count": 0}
    if ctx.get("scopeError"):
        # comm 范围未命中：显式返回失败原因+可选组件清单（如实报告，禁止静默空结果）
        se = ctx["scopeError"]
        logger.warning("[semantic] extract_scope 范围解析失败: %s", se.get("error"))
        return {"assets": [], "source": "none", "degraded": True, "count": 0,
                "error": se.get("error"), "candidates": se.get("candidates") or []}
    pid = project_id_for(root, project)
    # degraded 归因：index_missing=代码图谱索引缺失(与 LLM 无关)；llm_disabled=显式关 LLM；
    # heuristic_fallback=定向管线零产出走旧启发式。供前端按真实原因提示。
    _src = ctx.get("source") or "live"
    degraded = _src not in ("codegraph", "native")   # native 质量持平 → 非降级
    reason = "index_missing" if degraded else ""
    logger.info(
        "[semantic] extract_scope 范围 %s(%s) level=%s kinds=%s files=%d symbols=%d "
        "source=%s nodes=%d codegraph_synced=%s",
        scope_type, scope_key or "-", level, kinds, len(ctx.get("files") or []),
        len(ctx.get("symbols") or []), ctx.get("source"), len(ctx.get("nodes") or []), synced)
    all_assets: List[dict] = []
    llm_count = 0
    heur_counts: Dict[str, int] = {}
    if level != "implementation":
        # 逻辑层/业务层暂停再生：提取统一为实现层定向管线(tAgent 单管线)。
        # 显式请求低层返回空(如实标注，不再整包自由识别)。
        logger.info("[semantic] extract_scope level=%s 暂停再生, 统一实现层定向管线", level)
        return {"assets": [], "source": "paused", "degraded": False, "count": 0,
                "reason": f"level={level} 暂停再生，提取统一为实现层"}
    # 实现层：规则候选(类别定死) → (文件×类型)定向 tAgent → 验收 → 工具补齐 → 种子地板。
    # LLM 不可用/关闭时管线自动退化为纯确定性种子资产(不丢类别覆盖)。
    from .. import asset_extract
    all_assets = asset_extract.extract_directed(
        root, project, ctx, kinds, model_id=model_id, use_llm=use_llm)
    if not use_llm:
        degraded = True
        reason = "llm_disabled"
    for a in all_assets:
        heur_counts[a["kind"]] = heur_counts.get(a["kind"], 0) + 1
    llm_count = sum(1 for a in all_assets if not a.get("meta", {}).get("degraded"))
    if not all_assets:
        degraded = True
        reason = "heuristic_fallback"
        # 兜底(新管线异常时)：旧单趟主类别启发式。
        all_assets = _heuristic_extract_primary(ctx, kinds)
        for a in all_assets:
            heur_counts[a["kind"]] = heur_counts.get(a["kind"], 0) + 1
    logger.info(
        "[semantic] extract_scope 结果: scope=%s(%s) llm=%d heuristic=%s "
        "degraded=%s saved=%d text_len=%d",
        scope_type, scope_key or "-", llm_count, heur_counts or "-",
        degraded, len(all_assets), len(ctx.get("text") or ""))
    # 名称继承：re-extract 覆盖前保住用户改名(旧行名优先)+ 新资产墓碑承接
    _inherit_names(pid, all_assets)
    saved = _save_assets(pid, scope_type or "project", scope_key or "_", all_assets, ctx)
    # 节点简介(node_brief)：提取时按文件批量生成(LLM 路径)，失败静默(选中时可懒生成)
    try:
        if not degraded:
            nb = node_briefs_after_extract(pid, saved, ctx, model_id=ctx.get("modelId"))
            if nb:
                logger.info("[semantic] node briefs 生成 %d/%d", nb, len(saved))
    except Exception as e:
        logger.warning("[semantic] node briefs after extract failed: %s", e)
    _stale = {}
    if _src == 'native':
        try:
            from .symbols import symbol_source_state
            _ns = symbol_source_state(root, project)
            if _ns.get('stale'):
                _stale = {"indexStale": True, "staleCount": len(_ns.get('staleFiles') or []),
                          "lastHead": (_ns.get('lastHead') or '')[:12],
                          "head": (_ns.get('head') or '')[:12]}
        except Exception:
            pass
    return {"assets": saved, "source": ctx.get("source"),
            "symbolSource": _src, "degraded": degraded,
            "reason": reason, "count": len(saved), **_stale}


def _resolve_extract_levels(level: str) -> Tuple[str, ...]:
    """请求粒度 → 需提取的层级。显式层级只产该级；缺省/all 仅产 implementation。

    业务层+逻辑层当前暂停再生：默认只专注实现层。显式请求 logic/business
    (如单资产重提/按需聚合)仍可单独产出，不影响已落库资产的只读展示。
    """
    if level in SEMANTIC_LEVELS:
        return (level,)
    return ("implementation",)


# ── 对话式提取落库（agent 工具 asset.semantic.save 的实现；plan-C §4.1/§5.5） ──

def save_agent_assets(root: Optional[str], project: Optional[str],
                      assets: List[dict], executed_by: str = "") -> Dict[str, Any]:
    """agent 对话式提取的落库通道（API 归一化管线，写入口唯一）。

    - V1 框架校验：kind/level 必须在当前档位值域内（越域拒绝并说明）；
    - 名称继承：canonicalKey 命中旧行 → **旧行名优先**（用户名>历史名>新生成名），
      LLM 提议名不直接生效，作为 proposedName 返回供设计者定夺；
    - 墓碑承接：新资产查参考池，同名符号有历史命名 → 沿用；
    - 复用 _save_assets（canonicalKey 去重/实现层幻影拒绝/renamed 溯源/多归属合并）。
    """
    from .. import asset_framework as F
    pid = project_id_for(root, project)
    allowed_kinds = set(F.allowed_kinds(pid))
    allowed_levels = set(F.allowed_levels(pid))

    accepted: List[dict] = []
    rejected: List[dict] = []
    proposed: List[dict] = []
    scope_symbols: List[str] = []
    scope_files: List[str] = []

    for a in assets or []:
        name = (a.get("name") or "").strip()
        kind = (a.get("kind") or "").strip()
        level = (a.get("level") or "implementation").strip()
        refs = a.get("astRefs") or []
        if not name:
            rejected.append({"name": name, "reason": "缺少 name"})
            continue
        if kind not in allowed_kinds:
            rejected.append({"name": name, "reason": f"kind={kind} 不在当前框架值域内(允许: {sorted(allowed_kinds)})"})
            continue
        if level not in allowed_levels:
            rejected.append({"name": name, "reason": f"level={level} 不在当前框架值域内(允许: {sorted(allowed_levels)})"})
            continue
        if not refs:
            rejected.append({"name": name, "reason": "实现层资产必须携带 astRefs 锚点"})
            continue
        # 名称继承（先于 _save_assets）：canonicalKey 命中旧行 → 旧行名优先
        ck = _canonical_key(kind, level, refs, name=name,
                            scope_type="symbols", scope_key="")
        old = None
        for old_a in store.SemanticAssetsStore.all_status(pid, limit=20000):
            if (old_a.get("canonicalKey") or "") == ck:
                old = old_a
                break
        if old:
            old_name = old.get("name") or ""
            if old_name and old_name != name:
                proposed.append({"assetId": old["id"], "proposedName": name,
                                 "keptName": old_name})
                a = dict(a)
                a["name"] = old_name  # 旧行名优先，LLM 提议不直接生效
        else:
            # 墓碑承接：新资产查参考池（同名文件+符号的历史命名）
            f0 = (refs[0] or {}).get("file") or ""
            s0 = (refs[0] or {}).get("symbol") or ""
            hits = store.NameTombstoneStore.lookup(pid, f0, s0, limit=1)
            if hits and hits[0].get("name"):
                a = dict(a)
                a["name"] = hits[0]["name"]  # 捞回历史命名
        accepted.append(a)
        for r in refs:
            if r.get("file") and r["file"] not in scope_files:
                scope_files.append(r["file"])
            if r.get("symbol") and r["symbol"] not in scope_symbols:
                scope_symbols.append(r["symbol"])

    if not accepted:
        return {"count": 0, "saved": [], "rejected": rejected, "proposedNames": proposed}

    scope_key = ",".join(scope_symbols[:20])
    ctx = collect_context(root, project, "symbols", scope_key,
                          scope_files[:40], scope_symbols[:40])
    ctx["source"] = ctx.get("source") or "live"
    saved = _save_assets(pid, "symbols", scope_key, accepted, ctx)
    # 节点简介：对话式保存同样按文件批量补齐(单批，失败静默)
    try:
        node_briefs_after_extract(pid, saved, ctx)
    except Exception as e:
        logger.warning("[semantic] agent save node briefs failed: %s", e)
    logger.info("[semantic] agent save project=%s saved=%d rejected=%d proposed=%d",
                pid, len(saved), len(rejected), len(proposed))
    return {"count": len(saved), "saved": saved, "rejected": rejected,
            "proposedNames": proposed}


# ═══ aggregate（原第 aggregate 段，纯移动）═══



# ── H 级聚合(按需生成业务概念级资产) ──────────────────────────

def _high_asset_text(pid: str) -> str:
    """已落库 M/L 资产的紧凑清单(H 级聚合的候选素材)。"""
    rows = store.SemanticAssetsStore.all_status(pid, limit=4000)
    lines = []
    for a in rows:
        if a.get("status") != "active":
            continue
        lvl = a.get("level") or "logic"
        if lvl == "business":
            continue
        detail = a.get("detail") or {}
        extra = ""
        if detail.get("steps"):
            extra = f" steps={len(detail['steps'])}"
        elif detail.get("fields"):
            extra = f" fields={len(detail['fields'])}"
        elif detail.get("branches"):
            extra = f" branches={len(detail['branches'])}"
        lines.append(f"- {a.get('id')} | {a.get('kind')}/{lvl} | {a.get('name')}"
                     f"{(' — ' + (a.get('desc') or '')) if a.get('desc') else ''}{extra}")
    return "\n".join(lines) or "(暂无语义资产)"

def _leaf_components(root: Optional[str], project: Optional[str]) -> List[dict]:
    """KB 组件树 → 叶子组件(父组件文件已被其子组件 100% 覆盖，只需按叶子聚合)。

    叶子 = 非「任何组件 parentId」的组件。返回 [{id,name,desc,owns,parentId,level,edgeType}]，
    父先子后保序(便于前端逐层展示)。目录解析失败返回空列表。
    """
    from ..common import build_component_catalog
    comps = []
    try:
        comps = (build_component_catalog(root, project) or {}).get("components") or []
    except Exception as e:
        logger.warning("[semantic] leaf components 目录解析失败: %s", e, exc_info=True)
        return []
    child_ids = {c.get("parentId") for c in comps if c.get("parentId")}
    leaves = [c for c in comps if c.get("id") and c.get("id") not in child_ids]
    # 父先子后：按组件树层级稳定排序(L0 先于 L1)，同层保持目录顺序。
    by_parent: Dict[str, List[dict]] = {}
    for c in comps:
        by_parent.setdefault(c.get("parentId"), []).append(c)
    ordered: List[dict] = []
    seen: set = set()
    def _walk(p: Optional[str]) -> None:
        for c in by_parent.get(p, []):
            cid = c.get("id")
            if cid in seen:
                continue
            seen.add(cid)
            if cid in child_ids:
                _walk(cid)          # 父组件：先递归子，父本身不参与聚合(叶子集合不含父)
            else:
                ordered.append(c)
    _walk(None)
    return ordered


def _postorder_component_nodes(root: Optional[str], project: Optional[str]) -> List[dict]:
    """组件树后序遍历(子先于父)，含中间节点，每节点附带 `direct` 直属文件集。

    direct(N) = N.owns − ∪{子节点.owns} —— 只属于中间组件、未被任何叶子覆盖的文件
    归该中间节点的 direct，保证这类文件产出的逻辑资产仍能进入业务聚合(不因叶子不覆盖而丢)。

    返回 [{id,name,desc,owns,parentId,level,direct:[文件]}]，子先于父。
    """
    from ..common import build_component_catalog
    comps = []
    try:
        comps = (build_component_catalog(root, project) or {}).get("components") or []
    except Exception as e:
        logger.warning("[semantic] postorder 组件目录解析失败: %s", e, exc_info=True)
        return []
    by_parent: Dict[Optional[str], List[dict]] = {}
    for c in comps:
        if not c.get("id"):
            continue
        by_parent.setdefault(c.get("parentId") or None, []).append(c)
    # 每节点直接文件 = 自身 owns − 所有直接子节点 owns(逐层下推 → 最深拥有者)。
    child_files: Dict[str, set] = {}
    for c in comps:
        for f in (c.get("owns") or []):
            if f:
                child_files.setdefault(c.get("id"), set()).add(_norm_path(f))
    direct: Dict[str, set] = {}
    for c in comps:
        cid = c.get("id")
        own = {_norm_path(f) for f in (c.get("owns") or []) if f}
        covered: set = set()
        for ch in by_parent.get(cid, []):
            covered |= child_files.get(ch.get("id"), set())
        d = own - covered
        if not d and not by_parent.get(cid):
            d = own  # 孤立无子节点 → direct = 自身文件
        direct[cid] = d
    ordered: List[dict] = []
    seen: set = set()

    def _walk(p: Optional[str]) -> None:
        for c in by_parent.get(p, []):
            cid = c.get("id")
            if cid in seen:
                continue
            seen.add(cid)
            _walk(cid)  # 先递归子(后序)，再 append 自身
            ordered.append({**c, "direct": sorted(direct.get(cid, set()))})

    _walk(None)
    for c in comps:
        cid = c.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            ordered.append({**c, "direct": sorted(direct.get(cid, set()))})
    return ordered


def _high_asset_text_for_comp(pid: str, comp_id: str,
                              max_lines: int = 4000) -> str:
    """某组件(叶子)归属的 interaction/algorithm 候选资产清单(business 聚合候选素材)。

    过滤 meta.scopes 含 comp_id 的 active 资产，仅保留 logic/implementation(同全局语义)。
    """
    rows = store.SemanticAssetsStore.all_status(pid, limit=4000)
    lines = []
    for a in rows:
        if a.get("status") != "active":
            continue
        lvl = a.get("level") or "logic"
        if lvl not in ("logic", "implementation"):
            continue
        scopes = (a.get("meta") or {}).get("scopes") or []
        if comp_id not in scopes:
            continue
        detail = a.get("detail") or {}
        extra = ""
        if detail.get("steps"):
            extra = f" steps={len(detail['steps'])}"
        elif detail.get("fields"):
            extra = f" fields={len(detail['fields'])}"
        elif detail.get("branches"):
            extra = f" branches={len(detail['branches'])}"
        lines.append(f"- {a.get('id')} | {a.get('kind')}/{lvl} | {a.get('name')}"
                     f"{(' — ' + (a.get('desc') or '')) if a.get('desc') else ''}{extra}")
        if len(lines) >= max_lines:
            break
    return "\n".join(lines) or ""


_HIGH_SCHEMA = {
    "type": "object",
    "required": ["assets"],
    "properties": {
        "assets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "name", "desc"],
                "properties": {
                    "kind": {"type": "string", "enum": list(SEMANTIC_KINDS)},
                    "name": {"type": "string"},
                    "desc": {"type": "string"},
                    "aggregates": {
                        "type": "array",
                        "items": {"type": "object",
                                  "properties": {"assetId": {"type": "string"},
                                                 "role": {"type": "string"}}},
                        "description": "组成本业务概念的下级资产 id 列表(必须来自候选清单)"},
                    "relations": {
                        "type": "array",
                        "items": {"type": "object",
                                  "properties": {"target": {"type": "string"},
                                                 "type": {"type": "string"},
                                                 "semantic": {"type": "string"}}},
                        "description": "该 business 资产与其它 business 资产的依赖/关联(跨业务模块)"},
                    "inputs": {
                        "type": "array",
                        "items": {"type": "object",
                                  "properties": {"target": {"type": "string"},
                                                 "type": {"type": "string"},
                                                 "semantic": {"type": "string"}}},
                        "description": "该业务过程消费的资产(实体/契约等)，target 用资产 id 或业务名"},
                    "outputs": {
                        "type": "array",
                        "items": {"type": "object",
                                  "properties": {"target": {"type": "string"},
                                                 "type": {"type": "string"},
                                                 "semantic": {"type": "string"}}},
                        "description": "该业务过程产出的资产(实体/契约等)，target 用资产 id 或业务名"},
                    "invariants": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


_AGG_BATCH = 40
_AGG_MAX_ASSETS_PER_LEAF = 8


def _aggregate_one_batch(leaf: dict, batch: str, model_id: Optional[str],
                         max_assets: int) -> List[dict]:
    """对单个叶子的一批候选执行 LLM 聚合，返回 business 资产列表(含 aggregates 定向重试)。

    失败(LLM 不可达/解析失败)返回空列表，由调用方决定隔离策略。
    """
    from ..req_agent import llm_sync, get_max_tokens_preference
    cname = leaf.get("name") or leaf.get("id") or ""
    cdesc = (leaf.get("desc") or "").strip().replace("\n", " ")[:400]
    owns = (leaf.get("owns") or [])[:6]
    comp_block = (f"当前组件: {leaf.get('id')} ({cname})"
                  + (f" — {cdesc}" if cdesc else "")
                  + (f"\n组件文件: {', '.join(owns)}" if owns else ""))
    sys_prompt = (
        "你是资深架构师。基于某个组件的逻辑/实现级语义资产清单，归纳该组件下的 "
        "business 业务级语义资产(业务功能模块/共性目标)。\n"
        "类别 kind ∈ entity(聚合根/业务概念)/process(端到端业务过程)/"
        "decision(业务策略选择)/contract(对外业务能力)/state(业务生命周期)/"
        "rule(业务政策，仅当存在配置化拆分时)。\n"
        "规则：\n"
        "1. 每个 business 资产必须是该组件内多个逻辑单元的业务归纳(如「订单创建与支付结算」聚合"
        " createOrder/支付 等资产)，不得与 logic 资产重复表述；\n"
        "2. aggregates **必填**：必须引用下方候选清单中真实存在的资产 id(至少一个，"
        "推荐 3~10 个)，格式为字符串 id 数组；缺 aggregates 会导致资产无法定位到组件，"
        "这是本任务的核心要求；\n"
        "3. name 用业务命名，desc 概括业务功能与边界；\n"
        "4. relations **建议填写**：描述本批产出的各 business 资产之间的依赖/调用关系"
        "(target 用**其它 business 资产名**，type 用 uses/calls/depends 等)，"
        "让业务层资产之间也能连成图；\n"
        "5. process/contract 类资产建议填 inputs/outputs(消费/产出的资产 id 或业务名)；\n"
        "6. 只输出 JSON 对象 {\"assets\": [...]}，不要代码块。"
    )
    user_prompt = (
        f"{comp_block}\n\n"
        f"候选逻辑/实现级资产:\n{batch or '(暂无语义资产)'}\n\n"
        f"请归纳 business 级业务功能资产(每个必须填 aggregates，引用上述候选中的真实 id；"
        f"并在 relations 中表达各业务资产间的依赖关系)。"
    )
    try:
        res = llm_sync([{"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt}],
                       mode="structured", output_schema=_HIGH_SCHEMA,
                       max_tokens=get_max_tokens_preference(), model_id=model_id)
    except Exception as e:
        logger.warning("[semantic] aggregate one-batch LLM 失败: %s", e, exc_info=True)
        return []
    if not isinstance(res, dict):
        return []
    output = res.get("output") if isinstance(res, dict) else None
    if not isinstance(output, dict):
        return []

    def _parse(raw_assets: List[Any]) -> List[dict]:
        out: List[dict] = []
        for a in raw_assets:
            if not isinstance(a, dict):
                continue
            kind = _normalize_kind(a.get("kind"))
            name = (a.get("name") or "").strip()
            if not kind or not name:
                continue
            agg = []
            for x in (a.get("aggregates") or []):
                if isinstance(x, str) and x.strip():
                    agg.append({"assetId": x.strip()})
                elif isinstance(x, dict) and x.get("assetId"):
                    agg.append({"assetId": str(x.get("assetId")),
                                "role": (x.get("role") or "related").strip()})
            agg = [x for x in agg if x.get("assetId")]
            detail: Dict[str, Any] = {"aggregates": agg,
                                      "invariants": [str(v) for v in (a.get("invariants") or [])]}

            def _eps(key: str) -> List[dict]:
                out = []
                for r in (a.get(key) or []):
                    if not isinstance(r, dict):
                        continue
                    tgt = (r.get("target") or r.get("to") or "").strip()
                    if not tgt:
                        continue
                    out.append({"target": tgt,
                                "type": (r.get("type") or r.get("via") or "").strip(),
                                "semantic": (r.get("semantic") or "").strip()})
                return out

            for key in ("relations", "inputs", "outputs"):
                eps = _eps(key)
                if eps:
                    detail[key] = eps
            out.append({"kind": kind, "level": "business", "name": name,
                        "desc": (a.get("desc") or "").strip(),
                        "detail": detail,
                        "astRefs": [], "parentId": ""})
            if len(out) >= max_assets:
                break
        return out

    assets = _parse(output.get("assets") or [])
    # aggregates 完整性定向重试：LLM(尤其小模型)常跳过 aggregates，导致 business 资产
    # 无法推导组件归属(归属=被聚合子资产的 meta.scopes 并集)。缺 aggregates 时回喂
    # 提示重试(与 _llm_extract 的 detail 重试同理)。
    missing = [a for a in assets if not (a.get("detail") or {}).get("aggregates")]
    if missing:
        hint_lines = ["以下 business 资产缺少 aggregates(必须引用候选清单中真实存在的资产 id，至少一个)："]
        for a in missing:
            hint_lines.append(f"- {a['name']}(kind={a['kind']})")
        hint_lines.append("请重新输出完整 JSON 对象 {\"assets\": [...]}，为上述资产补充 aggregates(子资产 id 数组，"
                          "必须来自候选清单)，不要省略其它已完整资产，不要 Markdown 代码块。")
        try:
            res2 = llm_sync([
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": res.get("content") or ""},
                {"role": "user", "content": "\n".join(hint_lines)},
            ], mode="structured", output_schema=_HIGH_SCHEMA,
               max_tokens=get_max_tokens_preference(), model_id=model_id)
            out2 = res2.get("output") if isinstance(res2, dict) else None
            if isinstance(out2, dict):
                rebuilt = _parse(out2.get("assets") or [])
                # 仅当重试结果比首轮有更多带 aggregates 的资产时采用
                if sum(1 for a in rebuilt if (a.get("detail") or {}).get("aggregates")) \
                        > sum(1 for a in assets if (a.get("detail") or {}).get("aggregates")):
                    assets = rebuilt
        except Exception as e:
            logger.warning("[semantic] aggregate one-batch 重试失败: %s", e)
    return assets


def _aggregate_high(root: Optional[str], project: Optional[str],
                    model_id: Optional[str] = None,
                    max_assets: int = 8) -> Dict[str, Any]:
    """按需聚合 business 级(业务功能模块)资产：按 KB 组件树后序遍历逐节点聚合。

    只消费已落库的 active logic/implementation 资产(锚定真实代码)，LLM 仅作归纳并填写
    aggregates(组成资产 id)。每节点候选来自其 **direct 直属文件** 产出的逻辑资产
    (中间节点独有的、未被叶子覆盖的文件不丢失)。每候选完整覆盖(超 _AGG_BATCH 条循环分批，
    不截断)。落库后为下级资产回填 parentId(组合链)。单节点/单批失败隔离，不影响其它节点。
    """
    root = resolve_root(root, project)
    if not root:
        return {"assets": [], "count": 0, "degraded": True, "reason": "root"}
    pid = project_id_for(root, project)
    nodes = _postorder_component_nodes(root, project)
    if not nodes:
        return {"assets": [], "count": 0, "degraded": True, "reason": "comp"}
    all_assets: List[dict] = []
    node_errors: List[str] = []
    for node in nodes:
        cid = node.get("id") or ""
        if not cid:
            continue
        cand_text = _high_asset_text_for_comp(pid, cid)
        lines = [l for l in cand_text.split("\n") if l.strip()]
        if not lines:
            continue  # 该节点 direct 范围暂无 M/L 资产，无可聚合素材
        node_assets: List[dict] = []
        for i in range(0, len(lines), _AGG_BATCH):
            batch = "\n".join(lines[i:i + _AGG_BATCH])
            got = _aggregate_one_batch(node, batch, model_id, max_assets)
            node_assets += got
        if node_assets:
            all_assets += node_assets
        else:
            node_errors.append(cid)
            logger.info("[semantic] aggregate high 节点 %s(%s) 聚合产出 0", cid, node.get("name"))
    if not all_assets:
        reason = "llm" if node_errors else "empty"
        return {"assets": [], "count": 0, "degraded": True, "reason": reason}
    saved = _save_assets(pid, "project", "business", all_assets, {"root": root, "project": project,
                                                                  "table": {},
                                                                  "source": "codegraph",
                                                                  "srcHash": ""})
    # 回填组合链: 下级资产 parentId → 上级 business 资产。
    _link_parent(pid, saved)
    # 继承子资产 astRefs：business 资产锚定到真实符号 → 派生边可覆盖 business 层。
    _inherit_ast_refs_from_aggregates(pid, saved)
    # 同批合并(跨节点同名)会使 saved 含重复 id → 按 id 去重后返回。
    dedup: Dict[str, dict] = {}
    for a in saved:
        if a.get("id"):
            dedup.setdefault(a["id"], a)
    uniq = list(dedup.values())
    return {"assets": uniq, "count": len(uniq), "degraded": False, "reason": "ok"}


def _inherit_ast_refs_from_aggregates(pid: str, high_assets: List[dict]) -> None:
    """business 资产继承 aggregates 子资产的 astRefs(并集去重)。

    使 `_derive_project_edges` 能按符号把 business 资产映射到 codegraph 节点，
    从而为业务层合成稳定边(无 LLM 漂移)，同时保持 business 资产自身零符号的纯度。
    """
    for h in high_assets:
        hid = h.get("id") or ""
        if not hid:
            continue
        child_ids = [a.get("assetId") or "" for a in (h.get("detail") or {}).get("aggregates") or []]
        merged: List[dict] = []
        seen: set = set()
        for cid in child_ids:
            if not cid or not str(cid).startswith("sa-"):
                continue
            try:
                child = store.SemanticAssetsStore.get(cid)
            except Exception:
                continue
            for r in (child.get("astRefs") or []) if child else []:
                key = json.dumps(r, ensure_ascii=False, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(r)
        if not merged:
            continue
        try:
            store.SemanticAssetsStore.update(hid, {"astRefs": merged[:40], "updatedAt": _ts()})
        except Exception:
            pass


def _link_parent(pid: str, high_assets: List[dict]) -> None:
    """为 business 资产 aggregates 引用的下级资产回填 parentId(组合链)。

    同时把下级资产的组件归属(meta.scopes)聚合到 business 资产上：
    business 是跨组件业务归纳，应出现在所有被聚合组件下，而非只归「其它」。
    """
    for h in high_assets:
        hid = h.get("id") or ""
        detail = h.get("detail") or {}
        member_scopes: set = set()
        for agg in detail.get("aggregates") or []:
            aid = (agg.get("assetId") or "").strip()
            if not aid or not str(aid).startswith("sa-"):
                continue
            try:
                child = store.SemanticAssetsStore.get(aid)
                if child:
                    store.SemanticAssetsStore.update(aid, {"parentId": hid, "updatedAt": _ts()})
                    child_meta = dict((child.get("meta") or {}))
                    for s in child_meta.get("scopes") or []:
                        if s:
                            member_scopes.add(s)
            except Exception:
                pass
        if member_scopes:
            cur = dict((h.get("meta") or {}))
            cur["scopes"] = sorted(member_scopes)
            try:
                store.SemanticAssetsStore.update(hid, {"meta": cur, "updatedAt": _ts()})
            except Exception:
                pass



def _aggregate_high_best_effort(root: Optional[str], project: Optional[str],
                                model_id: Optional[str] = None) -> Dict[str, Any]:
    """按需聚合 H 级业务概念资产(失败不阻塞，仅记录日志)。

    对 LLM 瞬时不可达/输出解析失败做同任务内重试(retry=2，间隔 2s)，
    避免一次瞬时失败导致 business 级资产永久缺失。返回 _aggregate_high 的原始结果
    (含 count/reason)，供调用方把失败原因暴露给用户。
    """
    last: Optional[Dict[str, Any]] = None
    for attempt in range(3):
        try:
            res = _aggregate_high(root, project, model_id=model_id)
            last = res
        except Exception as e:
            logger.warning("[semantic] aggregate high best-effort failed: %s", e, exc_info=True)
            last = {"assets": [], "count": 0, "degraded": True, "reason": "llm"}
        if last and last.get("count"):
            return last
        reason = (last or {}).get("reason") or "unknown"
        if attempt < 2 and reason in ("llm", "parse"):
            logger.info("[semantic] aggregate high 第 %d 次失败(%s)，重试…", attempt + 1, reason)
            time.sleep(2)
            continue
        return last or {"count": 0}
    return last or {"count": 0}


# ═══ graphrelations（原第 graphrelations 段，纯移动）═══



# ── 图谱关系合成(程序化，非 LLM，不持久化) ─────────────────────

_DERIVED_EDGE_CACHE: Dict[str, Tuple[float, List[dict]]] = {}
_DERIVED_EDGE_TTL = 15.0


def _cg_symbol_to_node(conn: sqlite3.Connection) -> Dict[str, str]:
    """codegraph 符号名(qualified_name 优先，其次 name) → 节点 id。"""
    m: Dict[str, str] = {}
    try:
        for nid, qn, nm in conn.execute(
                "SELECT id, qualified_name, name FROM nodes").fetchall():
            if qn:
                m.setdefault(qn, nid)
            if nm:
                m.setdefault(nm, nid)
    except Exception as e:
        logger.warning("[semantic] cg symbol map failed: %s", e)
    return m


# 程序化派生边消费的 codegraph 边类型(全量语义关系)。
_DERIVE_EDGE_KINDS = ("calls", "contains", "extends", "imports", "references",
                      "instantiates", "implements", "type_of", "returns",
                      "overrides", "decorates", "callback", "assigns", "passes")
_DERIVE_EDGE_LIMIT = 5000


def _cg_node_file_map(conn: sqlite3.Connection, ids: List[str]) -> Dict[str, str]:
    """codegraph 节点 id → file_path(证据文件)。"""
    ph = ",".join("?" * len(ids))
    try:
        return {nid: fp for nid, fp in conn.execute(
            f"SELECT id, file_path FROM nodes WHERE id IN ({ph})", tuple(ids))}
    except Exception:
        return {}


def _cg_contains_expand(conn: sqlite3.Connection,
                        node_ids: List[str]) -> Dict[str, List[str]]:
    """锚点节点的 contains 1 层闭包：类/函数 → 其成员符号 id 列表。

    使类资产的符号集覆盖其方法/字段(单锚点资产的成员级关系可上卷到类资产)。
    """
    ph = ",".join("?" * len(node_ids))
    out: Dict[str, List[str]] = {}
    try:
        for s, t in conn.execute(
                f"SELECT source, target FROM edges WHERE kind='contains' "
                f"AND source IN ({ph})", tuple(node_ids)):
            out.setdefault(s, []).append(t)
    except Exception as e:
        logger.warning("[semantic] contains expand failed: %s", e)
    return out


def _cg_edge_evidence(metadata: Optional[str]) -> Tuple[str, str]:
    """calls 边 metadata JSON → (confidence, resolvedBy)。"""
    if not metadata:
        return "", ""
    try:
        m = json.loads(metadata)
        if isinstance(m, dict):
            c = m.get("confidence")
            return (str(c) if c is not None else "",
                    str(m.get("resolvedBy") or ""))
    except Exception:
        pass
    return "", ""


def _derive_project_edges(root: Optional[str], project: Optional[str],
                          assets: List[dict]) -> List[dict]:
    """从 codegraph 边程序化合成资产间关系(不持久化)。

    把每个资产锚点符号解析到 codegraph 节点，并经 contains 闭包扩展为
    「资产符号集」(类资产覆盖其方法/字段)；对全类型关系边，两端各锚定
    不同资产 → 产出一条边，带证据(line/file/confidence/resolvedBy)。
    供 `semantic_graph` 按粒度合成稳定关系，避免 LLM 命名的漂移。
    """
    if not assets:
        return []
    root = resolve_root(root, project)
    conn, _cg_src = open_symbol_conn(root, project)
    if conn is None:
        return []
    try:
        sym_to_node = _cg_symbol_to_node(conn)
        node_to_assets: Dict[str, set] = {}
        for a in assets:
            aid = a.get("id") or ""
            if not aid:
                continue
            for r in (a.get("astRefs") or []):
                nid = sym_to_node.get((r.get("symbol") or "").strip())
                if nid:
                    node_to_assets.setdefault(nid, set()).add(aid)
        if not node_to_assets:
            return []
        # contains 闭包展开：成员符号上卷到锚定资产
        expand = _cg_contains_expand(conn, list(node_to_assets))
        for parent, members in expand.items():
            for aid in node_to_assets.get(parent, set()):
                for m in members:
                    node_to_assets.setdefault(m, set()).add(aid)
        ids = list(node_to_assets)
        ph = ",".join("?" * len(ids))
        kinds_ph = ",".join("?" * len(_DERIVE_EDGE_KINDS))
        rows = conn.execute(
            f"SELECT e.source, e.target, e.kind, e.line, e.metadata, ns.file_path "
            f"FROM edges e JOIN nodes ns ON ns.id = e.source "
            f"WHERE e.source IN ({ph}) AND e.target IN ({ph}) "
            f"AND e.kind IN ({kinds_ph})",
            tuple(ids + ids + list(_DERIVE_EDGE_KINDS))).fetchall()
        out: List[dict] = []
        seen: set = set()
        for s, t, k, line, meta, sfile in rows:
            for a in node_to_assets.get(s, ()):
                for b in node_to_assets.get(t, ()):
                    if a == b:
                        continue
                    key = (a, b, k)
                    if key in seen:
                        continue
                    seen.add(key)
                    conf, resolved_by = _cg_edge_evidence(meta)
                    out.append({"from": a, "to": b, "type": k,
                                "semantic": _EDGE_SEMANTIC.get(k, k),
                                "derived": True,
                                "line": int(line or 0) or None,
                                "file": sfile or "",
                                **({"confidence": conf} if conf else {}),
                                **({"resolvedBy": resolved_by} if resolved_by else {})})
                    if len(out) >= _DERIVE_EDGE_LIMIT:
                        logger.warning("[semantic] derived edges 触及上限 %d，截断", _DERIVE_EDGE_LIMIT)
                        return out
        return out
    except Exception as e:
        logger.warning("[semantic] derive project edges failed: %s", e, exc_info=True)
        return []
    finally:
        conn.close()


def _derive_project_edges_kb(root: Optional[str], project: Optional[str],
                             assets: List[dict]) -> List[dict]:
    """无 codegraph 时的派生边 KB 兜底(arch_ast_cache / parseFileAst)。

    与 `_derive_project_edges` 同构：资产锚点文件 → 每文件符号+refs →
    `_rebuild_edges_from_refs` 重建统一边 → 目标名解析到其它资产 → 产边。
    """
    if not assets:
        return []
    root = resolve_root(root, project)
    if not root:
        return []
    pid = project_id_for(root, project)
    # 文件集 = 资产锚点文件
    files: List[str] = []
    seen_f: set = set()
    for a in assets:
        for r in (a.get("astRefs") or []):
            f = _norm_path(r.get("file") or "")
            if f and f not in seen_f:
                seen_f.add(f)
                files.append(f)
    if not files:
        return []
    # 资产符号集：锚点 symbol(qualified_name/name) → 资产 id
    sym_to_assets: Dict[str, set] = {}
    for a in assets:
        aid = a.get("id") or ""
        if not aid:
            continue
        for r in (a.get("astRefs") or []):
            s = (r.get("symbol") or "").strip()
            if s:
                sym_to_assets.setdefault(s, set()).add(aid)
    if not sym_to_assets:
        return []
    name_to_assets: Dict[str, set] = {}
    for s, aids in sym_to_assets.items():
        name_to_assets.setdefault(s.split("::")[-1], set()).update(aids)
    sym_to_assets.update({k: v for k, v in name_to_assets.items()
                          if k not in sym_to_assets})

    id_to_name: Dict[str, str] = {}
    file_edges: List[dict] = []
    for rel in files[:200]:
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        symbols: List[dict] = []
        refs: List[dict] = []
        cached = store.AstCacheStore.get(pid, rel)
        if cached and cached.get("contentHash") and cached.get("contentHash") == _cache_content_hash(root, rel):
            for s in cached.get("symbols") or []:
                n = _norm_cache_symbol(rel, cached.get("language") or "", s)
                if n:
                    symbols.append(n)
            refs = cached.get("refs") or []
        else:
            kb = _kb_parse_file(root, rel)
            if not (kb and kb.get("symbols")):
                continue
            lang = kb.get("language") or ""
            for s in kb["symbols"]:
                n = _norm_cache_symbol(rel, lang, s)
                if n:
                    symbols.append(n)
            refs = kb.get("refs") or []
            try:
                store.AstCacheStore.upsert(pid, rel, {
                    "contentHash": _cache_content_hash(root, rel),
                    "language": lang,
                    "symbols": symbols,
                    "imports": kb.get("imports") or [],
                    "refs": refs,
                    "statements": [], "routes": [], "constants": [],
                    "source": "kb",
                })
            except Exception as e:
                logger.warning("[semantic] kb derive cache upsert failed: %s", e)
        for s in symbols:
            if s.get("id"):
                id_to_name[s["id"]] = s.get("qualified_name") or s.get("name") or ""
        file_edges.extend(_rebuild_edges_from_refs(symbols, refs))

    out: List[dict] = []
    seen: set = set()
    for e in file_edges:
        s_name = id_to_name.get(e.get("source") or "", e.get("source") or "")
        t_name = id_to_name.get(e.get("target") or "", e.get("target") or "")
        if not s_name or not t_name:
            continue
        k = e.get("kind") or ""
        src_assets = sym_to_assets.get(s_name) or sym_to_assets.get(s_name.split("::")[-1])
        tgt_assets = sym_to_assets.get(t_name) or sym_to_assets.get(t_name.split("::")[-1])
        if not src_assets or not tgt_assets:
            continue
        for a in src_assets:
            for b in tgt_assets:
                if a == b:
                    continue
                key = (a, b, k)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"from": a, "to": b, "type": k,
                            "semantic": _EDGE_SEMANTIC.get(k, k),
                            "derived": True,
                            "line": e.get("line") or None,
                            "file": e.get("file") or ""})
                if len(out) >= _DERIVE_EDGE_LIMIT:
                    return out
    return out


def _derive_indirect_edges(root: Optional[str], project: Optional[str],
                           assets: List[dict]) -> List[dict]:
    """间接关系(1 跳中转)派生：A.anchor →(边)→ M →(边)→ B.anchor，A/B 无直接边。

    门槛：中转两跳的 codegraph 边 confidence ≥ 0.7(缺省视为达标)；
    `via` 记录中转符号 qualified_name(最多取首条最短链)。
    默认关闭，由 `semantic_graph(include_indirect=True)` 显式开启。
    """
    if not assets:
        return []
    root = resolve_root(root, project)
    conn, _cg_src = open_symbol_conn(root, project)
    if conn is None:
        return []
    try:
        sym_to_node = _cg_symbol_to_node(conn)
        anchor_ids: Dict[str, str] = {}     # node id → asset id(单资产优先)
        for a in assets:
            aid = a.get("id") or ""
            for r in (a.get("astRefs") or []):
                nid = sym_to_node.get((r.get("symbol") or "").strip())
                if nid:
                    anchor_ids.setdefault(nid, aid)
        if len(anchor_ids) < 2:
            return []
        ids = list(anchor_ids)
        ph = ",".join("?" * len(ids))
        # 一跳出边(锚点 → 中转)；confidence 门槛在 Python 侧过滤(元数据为 JSON)
        hop1 = conn.execute(
            f"SELECT e.source, e.target, e.kind, e.line, e.metadata, nt.name "
            f"FROM edges e JOIN nodes nt ON nt.id = e.target "
            f"WHERE e.source IN ({ph}) AND e.target NOT IN ({ph})",
            tuple(ids + ids)).fetchall()
        mid_keys: Dict[str, list] = {}      # 中转 id → [(src_asset, kind, line, conf, via_name)]
        for s, t, k, line, meta, tname in hop1:
            conf = _cg_edge_evidence(meta)[0]
            if conf and float(conf) < 0.7:
                continue
            mid_keys.setdefault(t, []).append(
                (anchor_ids.get(s), k, int(line or 0), tname))
        if not mid_keys:
            return []
        mids = list(mid_keys)
        mph = ",".join("?" * len(mids))
        hop2 = conn.execute(
            f"SELECT source, target, kind, metadata FROM edges "
            f"WHERE source IN ({mph}) AND target IN ({ph})",
            tuple(mids + ids)).fetchall()
        direct = {(anchor_ids[a], anchor_ids[b]) for a, b, _k in
                  conn.execute(
                      f"SELECT source, target, kind FROM edges "
                      f"WHERE source IN ({ph}) AND target IN ({ph})",
                      tuple(ids + ids))
                  if a in anchor_ids and b in anchor_ids}
        out: List[dict] = []
        seen: set = set()
        for m, t, k2, meta2 in hop2:
            conf2 = _cg_edge_evidence(meta2)[0]
            if conf2 and float(conf2) < 0.7:
                continue
            b = anchor_ids.get(t)
            if not b:
                continue
            for a, k1, line1, via in mid_keys.get(m, ()):
                if not a or a == b or (a, b) in direct:
                    continue
                key = (a, b)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"from": a, "to": b, "type": k2 or k1,
                            "semantic": _EDGE_SEMANTIC.get(k2 or k1, k2 or k1),
                            "derived": True, "indirect": True,
                            "via": via, "line": line1 or None})
                if len(out) >= 1000:
                    return out
        return out
    except Exception as e:
        logger.warning("[semantic] derive indirect edges failed: %s", e, exc_info=True)
        return []
    finally:
        conn.close()


def _cached_derived_edges(root: Optional[str], project: Optional[str],
                          assets: List[dict],
                          include_indirect: bool = False) -> List[dict]:
    """派生边进程内缓存：键 = 项目 + 资产数 + 最新 updatedAt + 间接开关。

    数据源：codegraph 可用 → codegraph 边；否则 KB 兜底(arch_ast_cache)。
    """
    if not assets:
        return []
    upd = [a.get("updatedAt") or 0 for a in assets]
    key = f"{project_id_for(root, project)}|{len(assets)}|{max(upd)}|{int(include_indirect)}"
    hit = _DERIVED_EDGE_CACHE.get(key)
    now = time.time()
    if hit and (now - hit[0]) < _DERIVED_EDGE_TTL:
        return hit[1]
    edges = _derive_project_edges(root, project, assets)
    if not edges:
        # codegraph 缺失/无锚点命中 → KB 兜底(与 codegraph 口径同构)
        edges = _derive_project_edges_kb(root, project, assets)
    if include_indirect:
        have = {(e.get("from"), e.get("to")) for e in edges}
        for e in _derive_indirect_edges(root, project, assets):
            if (e.get("from"), e.get("to")) not in have:
                edges.append(e)
    _DERIVED_EDGE_CACHE[key] = (now, edges)
    if len(_DERIVED_EDGE_CACHE) > 64:
        for k in sorted(_DERIVED_EDGE_CACHE, key=lambda kk: _DERIVED_EDGE_CACHE[kk][0])[:32]:
            _DERIVED_EDGE_CACHE.pop(k, None)
    return edges


def _relation_target_index(assets: List[dict]) -> Dict[str, str]:
    """关系目标解析索引：id / name / nameAlias / 锚点符号 → 资产 id。

    基于**全部**资产(非过滤子集)建索引，使按粒度/类别/范围筛选时，
    指向其它层级/范围的边仍能解析为稳定 id(是否渲染由前端按节点集决定)。
    """
    idx: Dict[str, str] = {}
    for a in assets:
        aid = a.get("id") or ""
        if not aid:
            continue
        idx.setdefault(aid, aid)
        nm = (a.get("name") or "").strip()
        if nm:
            idx.setdefault(nm, aid)
        for al in (a.get("nameAlias") or []) if isinstance(a.get("nameAlias"), list) else []:
            if isinstance(al, str) and al.strip():
                idx.setdefault(al.strip(), aid)
        for r in (a.get("astRefs") or []):
            s = (r.get("symbol") or "").strip()
            if s:
                idx.setdefault(s, aid)
    return idx


def _resolve_relation_target(t: str, idx: Dict[str, str]) -> Tuple[str, bool]:
    t = (t or "").strip()
    if not t:
        return "", False
    aid = idx.get(t)
    return (aid, True) if aid else (t, False)


def _graph_node_detail(a: dict) -> dict:
    """图谱节点附带的精简 detail(供类图/ER/序列/状态/聚合图生成，控制体积)。"""
    d = a.get("detail") or {}
    if not isinstance(d, dict):
        return {}
    out: Dict[str, Any] = {}
    if isinstance(d.get("fields"), list):
        out["fields"] = [f for f in d["fields"][:60]
                         if isinstance(f, dict) and f.get("name")]
    steps = d.get("steps")
    if isinstance(steps, list):
        out["steps"] = [s for s in steps[:40] if isinstance(s, dict)]
    branches = d.get("branches")
    if isinstance(branches, list):
        out["branches"] = [b for b in branches[:40] if isinstance(b, dict)]
    if d.get("trigger"):
        out["trigger"] = str(d["trigger"])
    if isinstance(d.get("invariants"), list):
        out["invariants"] = [str(x) for x in d["invariants"][:20]]
    rels = d.get("relations")
    if isinstance(rels, list):
        out["relations"] = [r for r in rels[:40] if isinstance(r, dict)]
    agg = d.get("aggregates")
    if isinstance(agg, list):
        out["aggregates"] = [x for x in agg[:60]
                             if isinstance(x, dict) and x.get("assetId")]
    return out


def _n_hop_subgraph(edges: List[dict], node_ids: set, focus_id: str, hops: int) -> set:
    """从 focus_id 出发的无向 N 跳节点集(边仅在 node_ids 内的节点间计数)。"""
    keep = {focus_id}
    for _ in range(max(1, hops)):
        add: set = set()
        for e in edges:
            if e.get("from") in keep and e.get("to") in node_ids:
                add.add(e["to"])
            if e.get("to") in keep and e.get("from") in node_ids:
                add.add(e["from"])
        keep |= add
    return keep


def semantic_graph(root: Optional[str], project: Optional[str],
                   kind: str = "", scopes: Optional[List[str]] = None,
                   level: str = "", limit: int = 2000,
                   focus: str = "", hops: int = 1,
                   include_indirect: bool = False) -> Dict[str, Any]:
    """语义层图谱：节点=语义资产，边=资产间 relations，锚点=AST 引用。

    边 = 存库基础 relations(按 id/name/nameAlias/符号解析) ∪ 程序化派生边
    (codegraph 边/KB 兜底，_derive_project_edges；带证据 line/file/confidence)。
    include_indirect=True 时追加 1 跳中转间接边(via 记录中转符号，默认关)。
    派生边不持久化，随粒度筛选稳定合成。

    focus: 单资产聚焦——仅返回该资产周围的 hops 跳子图(默认 1 跳)；
    未传 focus 时返回范围内全部节点。
    """
    _lazy_reconcile(root, project)
    pid = project_id_for(root, project)
    rows = store.SemanticAssetsStore.search(pid, text="", kind=kind,
                                            limit=limit, scopes=scopes, level=level)
    all_active = [a for a in store.SemanticAssetsStore.all_status(pid, limit=4000)
                  if a.get("status") == "active"]
    idx = _relation_target_index(all_active)
    # 关系清洗用全量索引(含 stale)：未解析到任何资产的目标才是成员/字段噪音；
    # 指向 stale 资产的真实关系必须保留(影响分析依赖)。
    idx_all = _relation_target_index([a for a in store.SemanticAssetsStore.all_status(pid, limit=4000)
                                      if a.get("status") != "deleted"])
    nodes: List[dict] = []
    edges: List[dict] = []
    anchors: List[dict] = []
    for a in rows:
        aid = a.get("id") or ""
        nodes.append({
            "id": aid, "kind": a.get("kind") or "entity",
            "level": a.get("level") or "logic",
            "name": a.get("name") or "", "desc": a.get("desc") or "",
            "change": a.get("change") or "same", "status": a.get("status") or "active",
            "scopeType": a.get("scopeType") or "", "scopeKey": a.get("scopeKey") or "",
            "needsUpdate": a.get("needsUpdate") or 0,
            "canonicalKey": a.get("canonicalKey") or "",
            "nodeBrief": (a.get("nodeBrief") or ""),
            "detail": _graph_node_detail(a),
        })
        detail = a.get("detail") or {}
        edge_notes_map: Dict[str, dict] = {}
        try:
            en = json.loads((a.get("edgeNotes") or "") or "{}")
            if isinstance(en, dict):
                edge_notes_map = en
        except Exception:
            edge_notes_map = {}
        for rel in detail.get("relations") or []:
            tgt_all, resolved_all = _resolve_relation_target((rel.get("target") or "").strip(), idx_all)
            # 关系清洗：未解析到任何资产的目标(字段/成员归属)不进图边，仅保留在卡内 detail；
            # 指向 stale 资产的真实关系保留(idx_all 含非删除全量)。
            if not tgt_all or not resolved_all:
                continue
            tgt, resolved = _resolve_relation_target(tgt_all, idx)
            edges.append({"from": aid, "to": tgt,
                          "resolved": resolved,
                          "type": rel.get("type") or "",
                          "semantic": rel.get("semantic") or "",
                          "desc": ((edge_notes_map.get(f"{aid}|{tgt_all}") or {}).get("desc") or "")})
        # 动态过程的三段端点(输入/输出) → 类型化边：inputs=uses/reads, outputs=writes/sends。
        for ep, etype in (("inputs", "uses"), ("outputs", "writes")):
            for rel in detail.get(ep) or []:
                tgt_all, resolved_all = _resolve_relation_target((rel.get("target") or "").strip(), idx_all)
                if not tgt_all or not resolved_all:
                    continue
                tgt, resolved = _resolve_relation_target(tgt_all, idx)
                edges.append({"from": aid, "to": tgt,
                              "resolved": resolved,
                              "type": rel.get("type") or etype,
                              "semantic": rel.get("semantic") or "",
                              "desc": ((edge_notes_map.get(f"{aid}|{tgt_all}") or {}).get("desc") or "")})
        for r in a.get("astRefs") or []:
            if r.get("file"):
                anchors.append({"assetId": aid, "file": r.get("file"),
                                "line": r.get("startLine") or 0,
                                "symbol": r.get("symbol") or "",
                                "kind": r.get("kind") or ""})
    # 程序化派生边(同层/跨层皆可，渲染与否由前端节点集决定)。
    derived = _cached_derived_edges(root, project, all_active,
                                    include_indirect=include_indirect)
    seen_edges: set = set()
    merged: List[dict] = []
    for e in edges + derived:
        key = (e.get("from"), e.get("to"), e.get("type"))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        merged.append(e)
    # 单资产聚焦：仅保留 focus 周围 hops 跳子图(默认 1 跳)。
    if focus:
        f_id = (focus or "").strip()
        if f_id and f_id in {n["id"] for n in nodes}:
            keep = _n_hop_subgraph(merged, {n["id"] for n in nodes}, f_id, hops)
            nodes = [n for n in nodes if n["id"] in keep]
            merged = [e for e in merged if e.get("from") in keep and e.get("to") in keep]
            anchors = [a for a in anchors if a.get("assetId") in keep]
    return {"nodes": nodes, "edges": merged, "anchors": anchors,
            "count": len(nodes)}


# ═══ briefs（原第 briefs 段，纯移动）═══

from . import router  # noqa: F401  (路由随逻辑就地注册)



# ── 上下文展开(任务执行/需求设计注入) ─────────────────────────

_SA_ID_RE = re.compile(r"\bsa-(?:s|d)-(?:i|l|b)-(?:e|c|s|r|p|d)-\d+\b")


def context_block_for(root: Optional[str], project: Optional[str],
                      context: Optional[List[str]] = None,
                      max_assets: int = 6) -> str:
    """从上下文条目中识别 `sa-*` 语义资产 id → 展开为语义块(供 coding-agent 注入)。

    返回追加文本(无资产则空串)。语义块含 名/kind/描述/AST 锚点，锁定「改哪里」。
    仅放行 `active && !needsUpdate` 资产(需更新后使用的一律不注入执行上下文)。
    """
    if not context:
        return ""
    ids = []
    for c in context:
        ids += _SA_ID_RE.findall(c or "")
    ids = list(dict.fromkeys(ids))
    if not ids:
        return ""
    _lazy_reconcile(root, project)
    block = ["\n## 语义数据资产上下文(改动锚点)"]
    for i in ids[:max_assets]:
        a = store.SemanticAssetsStore.get(i)
        if not a or a.get("status") != "active" or a.get("needsUpdate"):
            continue
        detail = a.get("detail") or {}
        line = (f"- {a.get('name')}({a.get('kind')}/{a.get('level') or 'logic'}): "
                f"{a.get('desc') or ''}")
        refs = (a.get("astRefs") or [])[:8]
        if refs:
            line += "  锚点: " + "; ".join(
                f"{r.get('file')}:L{r.get('startLine')}-L{r.get('endLine')} ({r.get('symbol')})"
                for r in refs)
        block.append(line)
    if len(block) == 1:
        return ""
    return "\n".join(block)


# ── 检索/详情 ─────────────────────────────────────────────────

# ── 伪码级说明(查询时 LLM 生成，有效生命周期内缓存) ─────────────

def _pseudo_source_snippet(root: Optional[str], ast_refs: List[dict],
                           max_chars: int = 6000) -> str:
    """读取 astRefs 指向的真实源码片段(让伪码级说明 grounded 到具体实现)。"""
    if not root or not ast_refs:
        return ""
    parts = []
    total = 0
    for r in ast_refs[:3]:
        rel = (r.get("file") or "").strip()
        if not rel:
            continue
        full = os.path.join(root, rel)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except Exception:
            continue
        start = max(0, int(r.get("startLine") or 1) - 1)
        end = int(r.get("endLine") or 0) or start + 1
        end = min(len(lines), max(end, start + 1, int(r.get("startLine") or 1) + 60))
        if start >= len(lines):
            continue
        snippet = "".join(lines[start:end])
        parts.append(f"# {rel}:{start + 1}-{end}\n{snippet}")
        total += len(snippet)
        if total >= max_chars:
            break
    return "\n\n".join(parts)[: max_chars + 200]


def _structural_pseudo(a: dict) -> str:
    """LLM 不可用/无源码时的确定性伪码级说明(基于 detail 结构，贴近实现)。"""
    detail = a.get("detail") or {}
    lines = [f"[{a.get('kind') or 'asset'}] {a.get('name') or a.get('id')}"]
    steps = detail.get("steps") or []
    if steps:
        lines.append("流程:")
        for i, s in enumerate(steps, 1):
            syms = s.get("symbols") or []
            lines.append(f"  {i}. {s.get('semantic') or (syms[0] if syms else '—')}")
    branches = detail.get("branches") or []
    if branches:
        lines.append("分支:")
        for b in branches:
            lines.append(f"  if {b.get('condition') or '?'} → {b.get('then') or '—'}"
                         + (f" / else {b.get('else')}" if b.get("else") else ""))
    fields = detail.get("fields") or []
    if fields:
        lines.append("字段: " + ", ".join((f.get("name") or "") for f in fields[:16]))
    rels = detail.get("relations") or []
    if rels:
        lines.append("关联: " + "; ".join((r.get("target") or "") for r in rels[:8]))
    return "\n".join(lines)


def generate_pseudo(asset_id: str, root: Optional[str] = None,
                    project: Optional[str] = None,
                    model_id: Optional[str] = None) -> dict:
    """查询时生成资产关联代码的伪码级说明；有效生命周期内缓存。
    stale/needsUpdate → 视为失效重生成；LLM 不可用/无源码 → 结构化作确定性降级。"""
    a = store.SemanticAssetsStore.get(asset_id)
    if not a:
        return {"pseudo": "", "cached": False, "degraded": True}
    fresh = (a.get("status") == "active") and not a.get("needsUpdate")
    cached = (a.get("pseudo") or "").strip()
    if fresh and cached:
        return {"pseudo": cached, "cached": True, "degraded": False}
    # 注册项目按 id 解析 rootPath(同 line-notes；URL 可能只带 project)
    root = resolve_root(root, project)
    snippet = _pseudo_source_snippet(root, a.get("astRefs") or [])
    pseudo, degraded = "", True
    if snippet:
        try:
            from ..req_agent import llm_sync, get_max_tokens_preference
            from ..agent_roles import resolve_role_model
            # tAgent 角色模型路由(§9/B1)：伪码解释走 pseudo 角色；显式传入优先
            model_id = resolve_role_model("pseudo", model_id)
            sys_prompt = (
                "你是资深架构师。基于给定的真实源码片段与该语义资产的类别/描述/结构，"
                "用中文写一段『伪码级』实现走查：带编号的伪码步骤概括它在本项目里具体怎么实现"
                "(关键入参 → 核心逻辑/分支 → 输出/副作用)。要贴近真实代码(可引用符号名)，"
                "比源码更抽象、比业务描述更具体。不得臆造源码中不存在的逻辑。"
            )
            user_prompt = (
                f"类别: {a.get('kind')}\n名称: {a.get('name')}\n业务描述: {a.get('desc') or '—'}\n\n"
                f"真实源码片段:\n{snippet}\n\n"
                "请输出伪码级实现走查(纯文本，不要 Markdown 代码块)。"
            )
            res = llm_sync([{"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_prompt}],
                           mode="chat", max_tokens=get_max_tokens_preference(), model_id=model_id)
            if isinstance(res, dict):
                pseudo = (res.get("content") or "").strip()
        except Exception as e:
            logger.warning("[semantic] pseudo LLM 失败: %s", e)
            pseudo = ""
    if not pseudo:
        pseudo, degraded = _structural_pseudo(a), True
    try:
        store.SemanticAssetsStore.update(asset_id, {"pseudo": pseudo})
    except Exception as e:
        logger.warning("[semantic] pseudo 落库失败: %s", e)
    return {"pseudo": pseudo, "cached": False, "degraded": degraded}


# ── AI 逐行解读(资产卡源码窗口：关键行用途说明，结合术语/规约) ──

# 单次送 LLM 的关键行数上限：兜底防失控，常规窗口全量入选(旧值 40 是
# 「长函数只有头部约 60 行被解读」的成因之一)；输入/输出超限由二分降级兜住。
_LINE_NOTE_MAX_LINES = 4000

# 上下文超限二分降级：1/2 → 1/4 → 1/8(封底，depth 上限 3)
_LN_MAX_DEPTH = 3

# 各厂商「上下文 tokens 超限」错误特征(小写子串匹配并集)。
# 注意 max_tokens 是生成量上限，不在此列；但输出截断导致 JSON 解析失败同样按可降级处理。
_CTX_OVERFLOW_MARKS = (
    "context length", "context_length", "context window", "contextwindowexceeded",
    "maximum context", "max context", "prompt is too long", "too many input tokens",
    "input tokens exceed", "input length exceed", "token limit",
    "上下文长度", "上下文超", "超出上下文", "超过上下文", "输入过长", "输入超限",
)


def _is_ctx_overflow(text: str) -> bool:
    """判断 LLM 错误文本是否上下文 tokens 超限(二分降级的触发信号)。"""
    t = (text or "").lower()
    return any(m in t for m in _CTX_OVERFLOW_MARKS)


def _is_noise_line(code: str) -> bool:
    """纯结构行(空行/纯括号/注释/导入)不值得逐行解释。"""
    t = code.strip()
    if not t or t in ("{", "}", "});", ");", ")", "}", "{", "},", "],", "]", "["):
        return True
    low = t.lower()
    return low.startswith(("#", "//", "/*", "*", "import ", "from ", "using ", "package "))


def _key_lines(codes: List[str], start: int) -> List[int]:
    """选取值得逐行解释的关键行(1-based 绝对行号)。

    声明/赋值/控制流/调用行均有语义，皆入选；仅跳过噪声行。封顶防超长。
    全窗皆噪声(如纯导入段) → 回退解释全部非空行(导入关系也可解读)。
    """
    out: List[int] = []
    fallback: List[int] = []
    for i, code in enumerate(codes):
        ln = start + i
        if code.strip():
            fallback.append(ln)
        if not _is_noise_line(code):
            out.append(ln)
    out = out[:_LINE_NOTE_MAX_LINES]
    return out if out else fallback[:_LINE_NOTE_MAX_LINES]


def _line_note_context(pid: str) -> Tuple[str, str]:
    """术语表 + 生效规约文本(注入逐行解读 prompt；为空返回空串)。"""
    terms_txt, conv_txt = "", ""
    try:
        rows = []
        for t in (store.GlossaryStore.list(pid, limit=30) or [])[:30]:
            alias = " / ".join(t.get("alias") or [])
            d = (t.get("definition") or "").strip()
            rows.append(f"- {t.get('term')}" + (f"({alias})" if alias else "")
                        + (f": {d[:60]}" if d else ""))
        if rows:
            terms_txt = "术语表:\n" + "\n".join(rows)
    except Exception as e:
        logger.warning("[semantic] line-notes 术语加载失败: %s", e)
    try:
        convs = store.NamingConventionStore.list(pid, status="active", limit=20) or []
        rows = [f"- {(c.get('ruleText') or '').strip()[:80]}"
                for c in convs[:20] if (c.get("ruleText") or "").strip()]
        if rows:
            conv_txt = "命名/设计规约:\n" + "\n".join(rows)
    except Exception as e:
        logger.warning("[semantic] line-notes 规约加载失败: %s", e)
    return terms_txt, conv_txt


# ── 节点简介(node_brief)：锚点源码 + 术语/规约 → ≤80 字代码级描述(后验校验防脱离代码) ──

def _anchor_symbols(a: dict) -> List[str]:
    """资产锚点的真实符号名集合(astRefs 符号 + 字段名 + 资产名)，用于后验校验。"""
    out: List[str] = []
    for s in [a.get("name")] + [r.get("symbol") or "" for r in (a.get("astRefs") or [])] \
             + [f.get("name") or "" for f in ((a.get("detail") or {}).get("fields") or [])]:
        s = (s or "").strip()
        if len(s) >= 3:
            out.append(s)
    return out


def _brief_grounded(brief: str, a: dict) -> bool:
    """后验校验：简介必须引用锚点源码中真实存在的符号名(不靠 prompt 自觉)。"""
    if not brief:
        return False
    return any(sym in brief for sym in _anchor_symbols(a))


def generate_node_brief(a: dict, root: Optional[str], project: Optional[str],
                        model_id: Optional[str] = None, force: bool = False) -> dict:
    """单资产 ≤80 字代码级简介(懒生成端点用)：fresh 命中缓存 / stale·force 重生成。"""
    aid = a.get("id") or ""
    fresh = (a.get("status") == "active") and not a.get("needsUpdate")
    existing = (a.get("nodeBrief") or "").strip()
    if fresh and existing and not force:
        return {"brief": existing, "cached": True, "degraded": False}
    brief, degraded = "", True
    try:
        root_r = resolve_root(root, project)
        snippet = _pseudo_source_snippet(root_r, a.get("astRefs") or [])
        if snippet:
            pid = project_id_for(root, project)
            terms_txt, conv_txt = _line_note_context(pid)
            ctx_lines = [f"资产: [{a.get('kind')}] {a.get('name')}",
                         f"业务描述: {(a.get('desc') or '—')[:160]}"]
            if terms_txt:
                ctx_lines.append(terms_txt)
            if conv_txt:
                ctx_lines.append(conv_txt)
            sys_prompt = (
                "你是资深架构师。基于真实源码片段，用中文写一句该代码实体『是什么/在做什么』的简介："
                "必须引用源码中真实存在的符号名，贴着代码说，不做高层抽象概括。不超过 80 字。"
                "只输出简介正文。"
            )
            user_prompt = "\n".join(ctx_lines) + f"\n\n真实源码片段:\n{snippet}\n\n请输出简介。"
            from ..req_agent import llm_sync, get_max_tokens_preference
            from ..agent_roles import resolve_role_model
            model_id = resolve_role_model("pseudo", model_id)
            res = llm_sync([{"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_prompt}],
                           mode="chat", max_tokens=get_max_tokens_preference(), model_id=model_id)
            brief = (res.get("content") or "").strip() if isinstance(res, dict) else ""
            brief = brief.strip('"').strip()
            if brief and not _brief_grounded(brief, a):
                logger.warning("[semantic] node brief 未通过接地校验(未引用真实符号): %s", aid)
                brief = ""
    except Exception as e:
        logger.warning("[semantic] node brief 生成失败: %s", e)
        brief = ""
    if not brief:
        return {"brief": existing or (a.get("desc") or ""), "cached": False, "degraded": True}
    try:
        store.SemanticAssetsStore.update(aid, {"nodeBrief": brief})
    except Exception as e:
        logger.warning("[semantic] node brief 落库失败: %s", e)
    return {"brief": brief, "cached": False, "degraded": False}


def generate_node_briefs_batch(pid: str, file: str, assets: List[dict],
                               root: Optional[str], project: Optional[str],
                               model_id: Optional[str] = None) -> int:
    """按文件批量生成节点简介(提取完成后调用)：同文件资产共用一份源码上下文，一次 LLM 调用。
    返回成功生成的条数。失败静默(资产保留模板 desc，选中时可懒生成)。"""
    if not assets:
        return 0
    root_r = resolve_root(root, project)
    full = os.path.join(root_r or "", file)
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.read().splitlines()
    except Exception:
        return 0
    ctx_blocks: List[str] = []
    targets: List[dict] = []
    for a in assets[:12]:   # 单批上限 12 个资产，控 token
        refs = [r for r in (a.get("astRefs") or []) if (r.get("file") or "") == file]
        if not refs:
            continue
        start = min(int(r.get("startLine") or 1) for r in refs)
        end = max(int(r.get("endLine") or start) for r in refs)
        s = max(1, start - 2)
        e = min(len(all_lines), end + 8)
        seg = "\n".join(f"{i} {all_lines[i - 1]}" for i in range(s, e + 1))[:1400]
        fields = ", ".join((f.get("name") or "") for f in ((a.get("detail") or {}).get("fields") or [])[:8])
        ctx_blocks.append(f"### [{a.get('kind')}] {a.get('name')} (id={a.get('id')})\n字段: {fields or '—'}\n源码:\n{seg}")
        targets.append(a)
    if not targets:
        return 0
    pid = pid or project_id_for(root, project)
    terms_txt, conv_txt = _line_note_context(pid)
    sys_prompt = (
        "你是资深架构师。对给定的多个代码实体，各写一句中文简介『是什么/在做什么』："
        "必须引用其源码中真实存在的符号名，贴着代码说，不做高层抽象概括。每句不超过 80 字。"
        '只输出 JSON：{"briefs":[{"id":"<实体id>","brief":"<简介>"}]}，不要输出其它内容。'
    )
    user_prompt = (terms_txt + "\n" if terms_txt else "") + (conv_txt + "\n" if conv_txt else "") \
        + "\n\n".join(ctx_blocks) + "\n\n请输出 JSON。"
    try:
        from ..req_agent import llm_sync, get_max_tokens_preference
        from ..agent_roles import resolve_role_model
        mid = resolve_role_model("pseudo", model_id)
        res = llm_sync([{"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt}],
                       mode="chat", max_tokens=max(get_max_tokens_preference() or 0, 2000), model_id=mid)
        raw = (res.get("content") or "").strip() if isinstance(res, dict) else ""
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        parsed = json.loads(raw)
        items = (parsed.get("briefs") or []) if isinstance(parsed, dict) else []
    except Exception as e:
        logger.warning("[semantic] node briefs batch 失败(%s): %s", file, e)
        return 0
    by_id = {a.get("id"): a for a in targets}
    n = 0
    for it in items if isinstance(items, list) else []:
        try:
            bid = str(it.get("id") or "")
            brief = str(it.get("brief") or "").strip()
        except AttributeError:
            continue
        a = by_id.get(bid)
        if not a or not brief:
            continue
        brief = brief[:120]
        if not _brief_grounded(brief, a):
            continue
        try:
            store.SemanticAssetsStore.update(bid, {"nodeBrief": brief})
            n += 1
        except Exception:
            pass
    return n


def node_briefs_after_extract(pid: str, saved: List[dict], ctx: Dict[str, Any],
                              model_id: Optional[str] = None) -> int:
    """提取完成后按文件批量补节点简介(最多 4 批，控制提取耗时)；失败静默。"""
    if not saved:
        return 0
    by_file: Dict[str, List[dict]] = {}
    for a in saved:
        f = ((a.get("astRefs") or [])[:1] and a["astRefs"][0].get("file")) or ""
        if f:
            by_file.setdefault(f, []).append(a)
    root = ctx.get("root")
    n = 0
    for file, group in list(by_file.items())[:4]:
        try:
            n += generate_node_briefs_batch(pid, file, group, root, ctx.get("project"), model_id)
        except Exception as e:
            logger.warning("[semantic] node briefs(%s) 失败: %s", file, e)
    return n


def generate_edge_notes(asset_id: str, root: Optional[str], project: Optional[str],
                        model_id: Optional[str] = None, force: bool = False) -> dict:
    """资产出边的关系描述(≤40 字证据式)：在 from 资产锚点源码中定位被调用符号行作为证据。
    落库 edge_notes JSON({from|to: {desc, at}})；未解析到真实资产的成员归属不生成。"""
    a = store.SemanticAssetsStore.get(asset_id)
    if not a:
        return {"notes": {}, "cached": False, "degraded": True, "error": "资产不存在"}
    pid = project_id_for(root, project)
    if not pid:
        return {"notes": {}, "cached": False, "degraded": True, "error": "缺少项目"}
    fresh = (a.get("status") == "active") and not a.get("needsUpdate")
    try:
        old = json.loads((a.get("edgeNotes") or "") or "{}")
    except Exception:
        old = {}
    idx = _relation_target_index([x for x in store.SemanticAssetsStore.all_status(pid, limit=4000)
                                  if x.get("status") != "deleted"])
    all_active = [x for x in store.SemanticAssetsStore.all_status(pid, limit=4000)
                  if x.get("status") == "active"]
    rels: List[Tuple[str, dict]] = []
    for rel in (a.get("detail") or {}).get("relations") or []:
        tgt, resolved = _resolve_relation_target((rel.get("target") or "").strip(), idx)
        if tgt and resolved:
            rels.append((tgt, rel))
    if not rels:
        return {"notes": {}, "cached": False, "degraded": True, "error": "无可解析的资产间关系"}
    keys = [f"{asset_id}|{t}" for t, _ in rels]
    if fresh and not force and all(k in old and isinstance(old.get(k), dict) and (old[k] or {}).get("desc") for k in keys):
        return {"notes": {k.split("|", 1)[1]: (old[k] or {}).get("desc") or "" for k in keys},
                "cached": True, "degraded": False}
    root_r = resolve_root(root, project)
    refs = a.get("astRefs") or []
    snippet = _pseudo_source_snippet(root_r, refs) if refs else ""
    if not snippet:
        return {"notes": {}, "cached": False, "degraded": True, "error": "源码不可读"}
    by_id = {x.get("id"): x for x in all_active}
    tgt_blocks: List[str] = []
    for t, rel in rels:
        ta = by_id.get(t) or {}
        tgt_blocks.append(f"- target={rel.get('target') or t} | [{ta.get('kind') or rel.get('type') or 'asset'}] "
                          f"{ta.get('name') or t} | {(ta.get('desc') or '')[:80]}")
    terms_txt, conv_txt = _line_note_context(pid)
    sys_prompt = (
        "你是资深架构师。基于 from 资产的真实源码片段，逐条描述它与各 target 资产的关系："
        "必须在源码中指明关系发生的位置(引用真实符号/语句)，说明『在做什么的过程中与对方发生该关系』。"
        "每条不超过 40 字，中文，贴着代码，不得臆造源码中不存在的关系。"
        '只输出 JSON：{"edges":[{"target":"<原始target名>","brief":"<描述>"}]}。'
    )
    user = (f"from 资产: [{a.get('kind')}] {a.get('name')}\n"
            + (terms_txt + "\n" if terms_txt else "") + (conv_txt + "\n" if conv_txt else "")
            + "\n真实源码片段:\n" + snippet
            + "\n\ntarget 资产清单:\n" + "\n".join(tgt_blocks) + "\n\n请输出 JSON。")
    notes: Dict[str, str] = {}
    try:
        from ..req_agent import llm_sync, get_max_tokens_preference
        from ..agent_roles import resolve_role_model
        mid = resolve_role_model("pseudo", model_id)
        res = llm_sync([{"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user}],
                       mode="chat", max_tokens=max(get_max_tokens_preference() or 0, 2000), model_id=mid)
        raw = (res.get("content") or "").strip() if isinstance(res, dict) else ""
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        parsed = json.loads(raw)
        by_target = {rel.get("target") or t: t for t, rel in rels}
        for it in (parsed.get("edges") or []) if isinstance(parsed, dict) else []:
            try:
                tn = str(it.get("target") or "").strip()
                brief = str(it.get("brief") or "").strip()[:80]
            except AttributeError:
                continue
            t = by_target.get(tn)
            if not t or not brief:
                continue
            ta = by_id.get(t) or {}
            tok_names = [ta.get("name") or ""] + [r.get("symbol") or "" for r in (ta.get("astRefs") or [])]
            if not any(len(k) >= 3 and k in brief for k in tok_names):
                continue   # 接地校验：描述必须引用 target 真实符号
            notes[f"{asset_id}|{t}"] = brief
    except Exception as e:
        logger.warning("[semantic] edge notes LLM 失败: %s", e)
        notes = {}
    if not notes:
        return {"notes": {}, "cached": False, "degraded": True, "error": "LLM 未返回有效关系描述"}
    try:
        merged = dict(old)
        now = _ts()
        for k, desc in notes.items():
            merged[k] = {"desc": desc, "at": now}
        store.SemanticAssetsStore.update(asset_id, {
            "edgeNotes": json.dumps(merged, ensure_ascii=False)})
    except Exception as e:
        logger.warning("[semantic] edge notes 落库失败: %s", e)
    out = {k.split("|", 1)[1]: v for k, v in notes.items()}
    return {"notes": out, "cached": False, "degraded": False}


@router.get("/kb/semantic/{asset_id}/edge-notes")
async def api_edge_notes(asset_id: str, root: Optional[str] = None, project: Optional[str] = None,
                         model_id: Optional[str] = None, force: bool = False):
    """资产出边的关系描述(证据式；落库 edge_notes 缓存，force 重生成)。"""
    return ok(await asyncio.to_thread(
        generate_edge_notes, asset_id, root, project, model_id, force))


# ── 存量资产描述批量增强(后台线程 + 进度查询)：节点简介(按文件批量) + 出边关系描述 ──

_ENHANCE: Dict[str, Any] = {"running": False, "done": 0, "total": 0,
                            "nodeBriefs": 0, "edgeNotes": 0, "error": ""}


def _enhance_state() -> Dict[str, Any]:
    return {k: _ENHANCE.get(k) for k in ("running", "done", "total", "nodeBriefs", "edgeNotes", "error")}


def _enhance_worker(pid: str, root: Optional[str], project: Optional[str],
                    model_id: Optional[str], force: bool) -> None:
    try:
        rows = [a for a in store.SemanticAssetsStore.all_status(pid, limit=4000)
                if a.get("status") == "active"]
        by_file: Dict[str, List[dict]] = {}
        edge_todo: List[dict] = []
        for a in rows:
            f = ((a.get("astRefs") or [])[:1] and a["astRefs"][0].get("file")) or ""
            if (force or not (a.get("nodeBrief") or "").strip()) and f:
                by_file.setdefault(f, []).append(a)
            if (a.get("detail") or {}).get("relations") and \
                    (force or not (a.get("edgeNotes") or "").strip()):
                edge_todo.append(a)
        _ENHANCE["total"] = len(by_file) + len(edge_todo)
        _ENHANCE["done"] = 0
        for file, group in by_file.items():
            try:
                _ENHANCE["nodeBriefs"] += generate_node_briefs_batch(
                    pid, file, group, root, project, model_id)
            except Exception as e:
                logger.warning("[semantic] enhance briefs(%s): %s", file, e)
            _ENHANCE["done"] += 1
        for a in edge_todo:
            try:
                r = generate_edge_notes(a.get("id") or "", root, project, model_id, force)
                if not r.get("degraded"):
                    _ENHANCE["edgeNotes"] += len(r.get("notes") or {})
            except Exception as e:
                logger.warning("[semantic] enhance edge notes: %s", e)
            _ENHANCE["done"] += 1
        _ENHANCE["error"] = ""
    except Exception as e:
        logger.warning("[semantic] enhance worker failed: %s", e)
        _ENHANCE["error"] = str(e)
    finally:
        _ENHANCE["running"] = False


@router.post("/kb/semantic/enhance-desc")
async def api_enhance_desc(root: Optional[str] = None, project: Optional[str] = None,
                           model_id: Optional[str] = None, force: bool = False):
    """存量资产描述批量增强(后台线程)：节点简介(按文件批量) + 出边关系描述。"""
    pid = project_id_for(root, project)
    if not pid:
        return err(400, "缺少项目")
    if _ENHANCE.get("running"):
        return ok({"started": False, **_enhance_state()})
    _ENHANCE.update({"running": True, "done": 0, "total": 0,
                     "nodeBriefs": 0, "edgeNotes": 0, "error": ""})
    threading.Thread(target=_enhance_worker,
                     args=(pid, resolve_root(root, project), project, model_id, force),
                     daemon=True).start()
    return ok({"started": True, **_enhance_state()})


@router.get("/kb/semantic/enhance-desc/status")
async def api_enhance_desc_status():
    return ok(_enhance_state())


@router.get("/kb/semantic/{asset_id}/in-edges")
async def api_in_edges(asset_id: str, root: Optional[str] = None, project: Optional[str] = None):
    """入边(被谁引用)：反向扫描活跃资产的 relations，解析指向本资产的边；
    描述优先取 from 资产 edge_notes 中的证据式描述(如有)。"""

    def _run():
        pid = project_id_for(root, project)
        me = store.SemanticAssetsStore.get(asset_id) if pid else None
        if not me:
            return {"inEdges": []}
        res_idx = {asset_id: asset_id}
        me_name = (me.get("name") or "").strip()
        if me_name:
            res_idx[me_name] = asset_id
        out: List[dict] = []
        for x in store.SemanticAssetsStore.all_status(pid, limit=4000):
            if x.get("status") != "active" or x.get("id") == asset_id:
                continue
            try:
                en = json.loads((x.get("edgeNotes") or "") or "{}")
            except Exception:
                en = {}
            for rel in (x.get("detail") or {}).get("relations") or []:
                tgt, resolved = _resolve_relation_target((rel.get("target") or "").strip(), res_idx)
                if not resolved or tgt != asset_id:
                    continue
                desc = (en.get(f"{x.get('id')}|{asset_id}") or {}).get("desc") \
                    or rel.get("semantic") or rel.get("type") or ""
                out.append({"fromId": x.get("id"), "fromName": x.get("name") or x.get("id"),
                            "type": rel.get("type") or "", "desc": desc})
        return {"inEdges": out}

    return ok(await asyncio.to_thread(_run))


def generate_line_notes(asset_id: str, file: str, start: int, end: int,
                        root: Optional[str] = None, project: Optional[str] = None,
                        model_id: Optional[str] = None, force: bool = False) -> dict:
    """资产卡源码窗口的关键行逐行用途说明(前端按钮手动触发)。

    缓存键 = 资产 + file + 行段 + 窗口内容 md5；fresh(active 且非 needsUpdate)且命中 → 直接返回。
    资产 stale/重提 → 缓存自然失效重生成(与 pseudo 同生命周期)。
    窗口优先**全量**送 LLM(关键行不截头)；上下文超限/输出截断 → 窗口二分
    (1/2 → 1/4 → 1/8 封底)递归重试并合并各批注解(见 _LN_MAX_DEPTH/_is_ctx_overflow)。
    LLM 失败/无可解释行 → degraded 且不落库(可重试)。
    """
    a = store.SemanticAssetsStore.get(asset_id)
    if not a:
        return {"notes": {}, "cached": False, "degraded": True, "error": "资产不存在"}
    # 注册项目按 id 解析 rootPath(URL 可能只带 project 不带 root)
    root = resolve_root(root, project)
    file = (file or "").strip()
    try:
        start, end = int(start), int(end)
    except (TypeError, ValueError):
        return {"notes": {}, "cached": False, "degraded": True, "error": "行段无效"}
    if not file or start < 1 or end < start:
        return {"notes": {}, "cached": False, "degraded": True, "error": "行段无效"}
    full = os.path.join(root or "", file)
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.read().splitlines()
    except Exception:
        return {"notes": {}, "cached": False, "degraded": True, "error": "源码不可读"}
    end = min(end, len(all_lines))
    codes = all_lines[start - 1:end]
    if not codes:
        return {"notes": {}, "cached": False, "degraded": True, "error": "行段为空"}
    win_hash = hashlib.md5("\n".join(codes).encode("utf-8")).hexdigest()
    fresh = (a.get("status") == "active") and not a.get("needsUpdate")
    # 多窗口缓存(line_notes.windows)：同资产不同窗口(多代码段/全文/分段)互不覆盖，LRU 上限 8。
    # 兼容旧单窗口格式 {file,start,end,hash,notes} → 迁移进 windows。
    try:
        cache = json.loads((a.get("lineNotes") or "") or "{}")
    except Exception:
        cache = {}
    windows: Dict[str, dict] = {}
    if isinstance(cache, dict) and isinstance(cache.get("windows"), dict):
        windows = cache["windows"]
    elif isinstance(cache, dict) and cache.get("file") and isinstance(cache.get("notes"), dict) and cache["notes"]:
        windows = {f"{cache.get('file')}|{int(cache.get('start') or 0)}|{int(cache.get('end') or 0)}|{cache.get('hash') or ''}":
                   {"notes": cache["notes"]}}
    ck = f"{file}|{start}|{end}|{win_hash}"
    # force=True(用户清除缓存重生成)：视同无缓存，重新生成并覆盖原窗口条目
    hit = windows.get(ck) if (fresh and not force) else None
    if isinstance(hit, dict) and isinstance(hit.get("notes"), dict) and hit["notes"]:
        return {"notes": {int(k): str(v) for k, v in hit["notes"].items()},
                "cached": True, "degraded": False}
    pid = project_id_for(root, project)
    terms_txt, conv_txt = _line_note_context(pid)
    ctx = [f"资产: [{a.get('kind')}] {a.get('name')}",
           f"业务描述: {(a.get('desc') or '—')[:200]}"]
    fields = (a.get("detail") or {}).get("fields") or []
    if fields:
        ctx.append("字段: " + ", ".join((f.get("name") or "") for f in fields[:12]))
    if terms_txt:
        ctx.append(terms_txt)
    if conv_txt:
        ctx.append(conv_txt)
    try:
        from ..asset_skill import skill_docs
        skill_txt = skill_docs(root, project, ["linenote"])
    except Exception as e:
        logger.warning("[semantic] line-notes skill 加载失败: %s", e)
        skill_txt = ""
    tools_doc = (
        "\n可用工具(按需调用，格式 [TOOL_CALL]{\"tool\":\"<名>\",\"arguments\":{参数}}[/TOOL_CALL])：\n"
        '- code.read_symbols: {"file": "相对路径", "symbol"?: "符号名", "startLine"?: 行, "endLine"?: 行} 读被调用符号的真实实现\n'
        '- asset.semantic.search: {"text": "关键词", "kind"?: "entity|contract|state|rule|process|decision"} 检索相关语义资产\n'
        '- asset.semantic.detail: {"asset_id": "sa-xxx"} 读相关资产完整定义\n'
    )
    base_prompt = (
        "你是资深架构师。对给定的带行号源码行逐行说明用途：结合术语表与规约解释业务含义，"
        "贴合真实代码，不得臆造源码中不存在的逻辑。每行说明不超过 40 字，用中文。"
        "信息不足时(如行内调用了看不懂的符号/想确认相关资产语义)，可先输出工具调用块收集信息再作答；"
        '信息足够后只输出 JSON：{"notes":[{"line":<行号>,"note":"<说明>"}]}，不要输出其它内容。'
    )
    sys_prompt = (skill_txt + "\n\n" if skill_txt else "") + base_prompt + tools_doc

    from ..req_agent import run_tools_loop, get_max_tokens_preference
    from ..agent_roles import resolve_role_model
    # 逐行解读与伪码走查同属 pseudo 角色(查询期轻量解读)；
    # 多轮工具调用(白名单只读工具，封顶 3 轮)允许模型补读符号/检索资产后再给注解。
    model_id = resolve_role_model("pseudo", model_id)

    def _attempt(sub_start: int, sub_codes: List[str]) -> Tuple[Dict[int, str], str, bool]:
        """解读一个子窗口。返回 (notes, err, retryable)。
        retryable=True 表示上下文超限/输出截断(tokens 不足)，窗口可二分降级重试。"""
        keys = _key_lines(sub_codes, sub_start)
        if not keys:
            return {}, "", False
        numbered = "\n".join(f"{ln}. {sub_codes[ln - sub_start]}" for ln in keys)
        user_prompt = ("\n".join(ctx)
                       + f"\n\n源码(文件 {file}，仅解释以下行):\n{numbered}\n\n请输出 JSON。")
        try:
            res = run_tools_loop(
                [{"role": "system", "content": sys_prompt},
                 {"role": "user", "content": user_prompt}],
                root=root, project=project, model_id=model_id,
                max_tokens=get_max_tokens_preference(), max_rounds=3,
                allowed=["code.read_symbols", "asset.semantic.search", "asset.semantic.detail"])
        except Exception as e:
            logger.warning("[semantic] line-notes LLM 失败: %s", e)
            return {}, str(e), _is_ctx_overflow(str(e))
        raw = ((res or {}).get("content") or "").strip()
        err_text = str((res or {}).get("error") or "")
        if not raw:
            return {}, err_text or "LLM 未返回内容", _is_ctx_overflow(err_text)
        if raw.startswith("```"):   # 容错剥离 ```json 包裹
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            parsed = json.loads(raw)
        except Exception:
            # 截断的 JSON(生成超限被掐断)同为 tokens 不足的常见表现 → 可二分降级
            return {}, f"输出无法解析({raw[:80]}…)", True
        out: Dict[int, str] = {}
        sub_end = sub_start + len(sub_codes) - 1
        for item in (parsed.get("notes") or []) if isinstance(parsed, dict) else []:
            try:
                ln, note = int(item.get("line")), str(item.get("note") or "").strip()
            except (TypeError, ValueError, AttributeError):
                continue
            if sub_start <= ln <= sub_end and note:
                out[ln] = note[:120]
        return out, "", False

    # 优先整窗全量解读；超限/截断 → 窗口二分(1/2→1/4→1/8 封底)递归重试，合并各批注解
    notes: Dict[int, str] = {}
    failures: List[str] = []

    def _recurse(sub_start: int, sub_codes: List[str], depth: int) -> None:
        part, err, retryable = _attempt(sub_start, sub_codes)
        if not err:
            notes.update(part)
            return
        if retryable and depth < _LN_MAX_DEPTH and len(sub_codes) > 1:
            mid = len(sub_codes) // 2
            _recurse(sub_start, sub_codes[:mid], depth + 1)
            _recurse(sub_start + mid, sub_codes[mid:], depth + 1)
            return
        failures.append(f"L{sub_start}-L{sub_start + len(sub_codes) - 1}: {err[:120]}")

    _recurse(start, codes, 0)
    if failures:
        return {"notes": notes, "cached": False, "degraded": True,
                "error": "部分行段解读失败(可重试): " + "; ".join(failures[:3])}
    if not notes:
        return {"notes": {}, "cached": False, "degraded": True, "error": "LLM 未返回有效注解"}
    try:
        windows[ck] = {"notes": notes, "at": _ts()}
        # LRU 裁剪：只保留最近 8 个窗口
        if len(windows) > 8:
            for k, _ in sorted(windows.items(), key=lambda kv: kv[1].get("at") or 0)[:-8]:
                windows.pop(k, None)
        store.SemanticAssetsStore.update(asset_id, {
            "lineNotes": json.dumps({"windows": windows}, ensure_ascii=False)})
    except Exception as e:
        logger.warning("[semantic] line-notes 落库失败: %s", e)
    return {"notes": notes, "cached": False, "degraded": False}


def mappings(asset_id: str, root: Optional[str] = None,
             project: Optional[str] = None) -> List[dict]:
    _lazy_reconcile(root, project)
    a = store.SemanticAssetsStore.get(asset_id)
    if not a:
        return []
    refs = a.get("astRefs") or []
    return [{"id": f"sa-{asset_id}-{i}", "targetType": "semantic",
             "targetId": asset_id, "targetName": a.get("name") or "",
             "file": r.get("file", ""), "line": f"L{r.get('startLine') or 0}",
             "level": "logical", "note": r.get("symbol", "")}
            for i, r in enumerate(refs)]


# ═══ lifecycle（原第 lifecycle 段，纯移动）═══



# ── 就地认知编辑（plan-C-M0 §7.2 rename/merge/split；R5 策略开关在端点/核心层） ──

class MainKbEditRejected(Exception):
    """R5: main-KB 关联项目的就地认知编辑被拒绝（应在主 KB 界面进行）。"""

    def __init__(self, kb_project_id: str):
        self.kb_project_id = kb_project_id
        self.deep_link = f"/kb/{kb_project_id}/assets"
        super().__init__(f"项目已关联主 KB({kb_project_id})，就地认知编辑请在主 KB 界面进行")


def _check_main_kb_policy(pid: str) -> None:
    """R5 写入口唯一：standalone 直过；main-KB(已关联) 拒绝 → 深链。"""
    proj = store.ProjectsStore.get(pid) if pid else None
    kb_pid = (proj or {}).get("kbProjectId") or ""
    if kb_pid:
        raise MainKbEditRejected(kb_pid)


def _asset_anchor_basis(asset: dict) -> List[str]:
    return [f"{r.get('file', '')}:{r.get('symbol', '')}"
            for r in (asset.get("astRefs") or []) if r.get("file")]


def rename_asset(asset_id: str, new_name: str, author: str = "") -> Dict[str, Any]:
    """资产改名（认知层编辑）：旧名 → renamedFrom + nameAlias 历史；overlay 审计。"""
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("newName 不能为空")
    asset = store.SemanticAssetsStore.get(asset_id)
    if not asset:
        raise ValueError(f"资产不存在: {asset_id}")
    if asset.get("status") != "active":
        raise ValueError(f"资产非 active 状态({asset.get('status')})，不可改名")
    _check_main_kb_policy(asset.get("projectId") or "")
    old_name = asset.get("name") or ""
    if new_name == old_name:
        raise ValueError("新名与当前名相同")
    alias = list(asset.get("nameAlias") or [])
    if old_name and old_name not in alias:
        alias.insert(0, old_name)
    updated = store.SemanticAssetsStore.update(asset_id, {
        "name": new_name, "renamedFrom": old_name, "nameAlias": alias,
        "updatedAt": _ts(),
    })
    overlay = store.UserOverlayStore.add(
        asset.get("projectId") or "", "rename", [asset_id],
        {"newName": new_name, "oldName": old_name},
        _asset_anchor_basis(asset), author=author)
    logger.info("[semantic] rename %s: %r -> %r (ovl=%s)", asset_id, old_name, new_name, overlay.get("id"))
    return {"asset": updated, "overlayId": overlay.get("id")}


def edit_asset_desc(asset_id: str, desc: str, author: str = "") -> Dict[str, Any]:
    """资产描述修订（认知层编辑）：overlay 审计 op=edit_desc。"""
    asset = store.SemanticAssetsStore.get(asset_id)
    if not asset:
        raise ValueError(f"资产不存在: {asset_id}")
    if asset.get("status") != "active":
        raise ValueError(f"资产非 active 状态({asset.get('status')})，不可编辑")
    _check_main_kb_policy(asset.get("projectId") or "")
    updated = store.SemanticAssetsStore.update(asset_id, {"desc": desc or "", "updatedAt": _ts()})
    overlay = store.UserOverlayStore.add(
        asset.get("projectId") or "", "edit_desc", [asset_id],
        {"desc": desc or ""}, _asset_anchor_basis(asset), author=author)
    return {"asset": updated, "overlayId": overlay.get("id")}


def merge_assets(into_id: str, target_ids: List[str],
                 target_name: str = "", author: str = "") -> Dict[str, Any]:
    """资产合并：目标资产锚点并入 intoId，目标行 deleted + meta.mergedInto 溯源。"""
    into = store.SemanticAssetsStore.get(into_id)
    if not into:
        raise ValueError(f"目标资产不存在: {into_id}")
    if into.get("status") != "active":
        raise ValueError(f"目标资产非 active 状态({into.get('status')})")
    targets = [t for t in (target_ids or []) if t and t != into_id]
    if not targets:
        raise ValueError("targetIds 为空")
    _check_main_kb_policy(into.get("projectId") or "")
    now = _ts()
    into_refs = list(into.get("astRefs") or [])
    anchor_basis = _asset_anchor_basis(into)
    merged: List[str] = []
    for tid in targets:
        tgt = store.SemanticAssetsStore.get(tid)
        if not tgt:
            raise ValueError(f"待合并资产不存在: {tid}")
        if tgt.get("status") != "active":
            raise ValueError(f"待合并资产非 active 状态({tid}: {tgt.get('status')})")
        tmeta = dict(tgt.get("meta") or {})
        tmeta["mergedInto"] = into_id
        store.SemanticAssetsStore.update(tid, {
            "status": "deleted", "deletedAt": now, "meta": tmeta, "updatedAt": now,
        })
        for r in (tgt.get("astRefs") or []):
            key = (r.get("file", ""), r.get("symbol", ""))
            if all((x.get("file", ""), x.get("symbol", "")) != key for x in into_refs):
                into_refs.append(r)
                if r.get("file"):
                    anchor_basis.append(f"{r.get('file', '')}:{r.get('symbol', '')}")
        merged.append(tid)
    patch: Dict[str, Any] = {"astRefs": into_refs, "updatedAt": now}
    if target_name and target_name != into.get("name"):
        alias = list(into.get("nameAlias") or [])
        old = into.get("name") or ""
        if old and old not in alias:
            alias.insert(0, old)
        patch.update({"name": target_name, "renamedFrom": old, "nameAlias": alias})
    updated = store.SemanticAssetsStore.update(into_id, patch)
    overlay = store.UserOverlayStore.add(
        into.get("projectId") or "", "merge", [into_id] + merged,
        {"intoId": into_id, "targetIds": merged, "targetName": target_name or ""},
        anchor_basis, author=author)
    logger.info("[semantic] merge into=%s merged=%d (ovl=%s)", into_id, len(merged), overlay.get("id"))
    return {"asset": updated, "merged": merged, "overlayId": overlay.get("id")}


def split_asset(asset_id: str, parts: List[Dict[str, Any]],
                author: str = "") -> Dict[str, Any]:
    """资产拆分：按锚点组(anchorKeys=file:symbol)拆出多个新资产；原行 deleted + meta.splitInto。"""
    asset = store.SemanticAssetsStore.get(asset_id)
    if not asset:
        raise ValueError(f"资产不存在: {asset_id}")
    if asset.get("status") != "active":
        raise ValueError(f"资产非 active 状态({asset.get('status')})，不可拆分")
    _check_main_kb_policy(asset.get("projectId") or "")
    parts = [p for p in (parts or []) if isinstance(p, dict) and (p.get("name") or "").strip()]
    if not parts:
        raise ValueError("parts 为空(需 {name, anchorKeys[]})")
    now = _ts()
    pid = asset.get("projectId") or ""
    refs = asset.get("astRefs") or []
    level = asset.get("level") or "implementation"
    kind = asset.get("kind") or "entity"
    created: List[Dict[str, Any]] = []
    new_ids: List[str] = []
    parts_payload: List[Dict[str, Any]] = []
    for p in parts:
        keys = [k.strip() for k in (p.get("anchorKeys") or []) if (k or "").strip()]
        if not keys:
            raise ValueError(f"拆分部分 {p.get('name')} 缺少 anchorKeys")
        sub = [r for r in refs
               if f"{r.get('file', '')}:{r.get('symbol', '')}" in set(keys)]
        if not sub:
            raise ValueError(f"拆分部分 {p.get('name')} 无匹配锚点(anchorKeys={keys})")
        new_id = store.next_id(_id_prefix(level, kind))
        meta = {"splitFrom": asset_id}
        store.SemanticAssetsStore.create({
            "id": new_id, "projectId": pid, "kind": kind, "level": level,
            "name": p["name"].strip(), "desc": (p.get("desc") or "").strip(),
            "detail": p.get("detail") or {},
            "astRefs": sub, "scopeType": asset.get("scopeType") or "",
            "scopeKey": asset.get("scopeKey") or "",
            "source": asset.get("source") or "codegraph",
            "status": "active", "meta": meta,
            "canonicalKey": _canonical_key(kind, level, sub, name=p["name"].strip()),
            "nameAlias": [], "renamedFrom": "",
            "createdAt": now, "updatedAt": now,
        })
        new_ids.append(new_id)
        created.append({"id": new_id, "name": p["name"].strip(), "anchors": len(sub)})
        parts_payload.append({"name": p["name"].strip(), "anchorKeys": keys})
    meta = dict(asset.get("meta") or {})
    meta["splitInto"] = new_ids
    store.SemanticAssetsStore.update(asset_id, {
        "status": "deleted", "deletedAt": now, "meta": meta, "updatedAt": now,
    })
    overlay = store.UserOverlayStore.add(
        pid, "split", [asset_id] + new_ids,
        {"parts": parts_payload}, _asset_anchor_basis(asset), author=author)
    logger.info("[semantic] split %s -> %s (ovl=%s)", asset_id, new_ids, overlay.get("id"))
    return {"deletedAssetId": asset_id, "created": created, "overlayId": overlay.get("id")}


def refresh_scope(root: Optional[str], project: Optional[str],
                  scope_type: str, scope_key: str,
                  files: Optional[List[str]] = None,
                  symbols: Optional[List[str]] = None,
                  model_id: Optional[str] = None) -> Dict[str, Any]:
    """增量刷新: 对已提取范围重跑提取，按 src_hash 判定 change。成功恢复 active。"""
    res = extract_scope(root, project, scope_type, scope_key,
                        files=files, symbols=symbols,
                        model_id=model_id, use_llm=True)
    # 重提即视为已消费「需更新」标记
    pid = project_id_for(root, project)
    for a in res.get("assets") or []:
        store.SemanticAssetsStore.update(a.get("id"), {
            "needsUpdate": 0, "lastCheckedAt": _ts()})
    return res


# ═══ batchclean（原第 batchclean 段，纯移动）═══



# ── 批量管理(选定组件范围: 提取/清除/更新) ──────────────────────

# 组件文件映射短 TTL 缓存：目录极少变化，而提取任务逐文件落库(每文件一次归属装配)，
# 无缓存时 N 文件 = N 次 KB 调用；KB 瞬时失败也不应让整批资产丢失组件归属。
_COMP_FILE_MAP_TTL = 60.0
_comp_file_map_cache: Dict[tuple, tuple] = {}  # (root, project) -> (ts, {cid: frozenset(files)})


def _component_file_map(root: str, project: Optional[str]) -> Dict[str, set]:
    """组件 → 文件集合。以组件目录(跨 INCLUDE/CALL × L0/L1，即组件列表完整来源)为准，
    目录为空(降级/无基线)时回退架构模型兜底(与 `_comm_files` 解析口径一致)。
    结果按 (root, project) 短 TTL 缓存。失败返回空。"""
    key = (root or "", project or "")
    now = time.time()
    hit = _comp_file_map_cache.get(key)
    if hit and now - hit[0] < _COMP_FILE_MAP_TTL:
        return {k: set(v) for k, v in hit[1].items()}
    comp_files: Dict[str, set] = {}
    try:
        from ..common import build_component_catalog
        catalog = build_component_catalog(root, project)
        for c in catalog.get("components") or []:
            cid = c.get("id")
            if not cid:
                continue
            for f in (c.get("owns") or []):
                if f:
                    comp_files.setdefault(cid, set()).add(_norm_path(f))
    except Exception as e:
        logger.warning("[semantic] component file map(catalog) failed: %s", e)
    if not comp_files:
        try:
            from ..common import build_architecture_model
            model = build_architecture_model(root, project)
            for c in model.get("components") or []:
                cid = c.get("id")
                if not cid:
                    continue
                for f in (c.get("owns") or []):
                    if f:
                        comp_files.setdefault(cid, set()).add(_norm_path(f))
        except Exception as e:
            logger.warning("[semantic] component file map(model fallback) failed: %s", e)
    _comp_file_map_cache[key] = (now, {k: frozenset(v) for k, v in comp_files.items()})
    return {k: set(v) for k, v in comp_files.items()}


def _component_asset_ids(pid: str, comp_files: Dict[str, set],
                         scopes: Optional[List[str]]) -> List[str]:
    """选定组件范围 → 资产 id 集合(与 search 的 scope 语义一致)。

    - None / 空        : 全部资产(含无锚点 H 级聚合资产)。
    - ['__other__']    : 仅「其它」(非组件文件 + 无锚点资产)。
    - ['c1','c2']      : 指定组件的资产(scope_key 命中 或 meta.scopes 多归属命中)。
    - ['c1','__other__']: 指定组件 + 「其它」。
    """
    if not scopes:
        return sorted(
            i for i in {
                a.get("id") for a in store.SemanticAssetsStore.all_status(pid, limit=4000)
            } if i)
    keys = [s for s in scopes if s != "__other__"]
    include_other = "__other__" in scopes
    comp_set = set(keys)
    sel_files: set = set()
    all_files: set = set()
    for cid, files in comp_files.items():
        all_files |= files
        if cid in comp_set:
            sel_files |= files
    ids: set = set()
    for a in store.SemanticAssetsStore.all_status(pid, limit=4000):
        aid = a.get("id")
        if not aid:
            continue
        scopes_of = a.get("meta") or {}
        scopes_of = scopes_of.get("scopes") if isinstance(scopes_of, dict) else []
        if isinstance(scopes_of, list) and any(s in comp_set for s in scopes_of):
            ids.add(aid)
            continue
        if a.get("scopeType") == "comm" and (a.get("scopeKey") or "") in comp_set:
            ids.add(aid)
            continue
        f = _norm_path((a.get("astRefs") or [{}])[0].get("file") or "")
        if not f:
            # 无锚点资产(如 H 级聚合)不属任何组件文件 → 「其它」桶命中。
            if include_other:
                ids.add(aid)
            continue
        if f in sel_files or (include_other and f not in all_files):
            ids.add(aid)
    return sorted(i for i in ids if i)


def batch_manage(root: Optional[str], project: Optional[str],
                 action: str, comp_ids: Optional[List[str]] = None,
                 include_other: bool = False,
                 kinds: Optional[List[str]] = None,
                 model_id: Optional[str] = None,
                 level: str = "implementation",
                 scopes: Optional[List[str]] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
    """批量管理组件范围语义资产。

    仅支持 action="clear"：物理删除选定组件范围内的语义资产(不做软删保留)，
    dry_run=True 仅返回影响范围供确认。批量全量提取已退役——提取统一为
    组件 ID 指令化单管线(asset.semantic.extract / 单组件范围 /extract)。

    兼容保留 kinds/model_id/level 参数(clear 不使用)。scopes: 与 search 一致的
    组件范围语义(None=全部 / ['__other__']=仅其它 / 组件 id 列表)。
    返回 {action, count, cleared?, impact?}。
    """
    root = resolve_root(root, project)
    comp_ids = [c for c in (comp_ids or []) if c]
    if action != "clear":
        return {"action": action, "count": 0, "cleared": [], "updated": []}
    pid = project_id_for(root, project)
    comp_files = _component_file_map(root, project)
    # 归一化范围语义：优先 scopes；否则回退旧参数(空 comp_ids + include_other = 全部)。
    if scopes is None:
        scopes = list(comp_ids)
        if include_other and not comp_ids:
            scopes = None   # 空选 + 其它 = 全部
        elif include_other:
            scopes.append("__other__")
    ids = _component_asset_ids(pid, comp_files, scopes)
    cleared, updated = [], []
    if action == "clear":
        # 清除 = 物理删除(不做软删保留)：连同引用登记一并删除。
        targets = []
        for aid in ids:
            a = store.SemanticAssetsStore.get(aid)
            if not a or a.get("status") == "deleted":
                continue
            targets.append(aid)
        impact = _impact_of_purge(root, project, targets) if targets else {
            "reqCount": 0, "taskCount": 0, "requirements": [], "tasks": [],
            "assetCount": 0}
        if dry_run:
            # 预览：仅返回影响范围，不删除(供前端确认提示)。
            return {"action": action, "count": len(targets), "cleared": [],
                    "updated": [], "dryRun": True, "impact": impact}
        if targets:
            try:
                for i in range(0, len(targets), 500):
                    store.SemanticAssetsStore.purge(pid, targets[i:i + 500])
                try:
                    store.SemanticRefsStore.delete_for_assets(targets)
                except Exception:
                    pass
                cleared = targets
            except Exception as e:
                logger.warning("[semantic] batch clear %s failed: %s", targets[:5], e)
        return {"action": action, "count": len(targets), "cleared": cleared,
                "updated": [], "impact": impact}
    # 其它 action 已在上方返回；clear 之外(如 update)不再提供独立的更新概念。
    return {"action": action, "count": 0, "cleared": [], "updated": []}


# ── 语义资产清理(物理删除 + 影响识别) ─────────────────────────

_PURGE_REQ_REF_TYPES = ("req", "plan", "task", "test")


def _req_asset_ids(req: dict) -> List[str]:
    """需求 analysis.assetScope 中引用的 sa-* 资产 id。"""
    scope = ((req.get("analysis") or {}).get("assetScope") or [])
    return [str(a.get("assetId") or "") for a in scope
            if str(a.get("assetId") or "").startswith("sa-")]


def _task_asset_ids(task: dict) -> List[str]:
    """未完成任务引用的 sa-* 资产 id(exec.reqIds 回查需求 + 单测 refs + plan/impact)。"""
    ids: List[str] = []
    for rid in (task.get("reqIds") or []):
        req = store.RequirementsStore.get(rid)
        if req:
            ids += _req_asset_ids(req)
    return list(dict.fromkeys(ids))


def _impact_of_purge(root: Optional[str], project: Optional[str],
                     candidates: List[str]) -> Dict[str, Any]:
    """计算清理候选资产对需求池与未完成任务的影响范围。

    识别规则：
      - 受影响需求: 需求 analysis.assetScope 引用候选资产(id ∈ candidates)；
        限定「需求池/已分析」位置(pool) 或已绑定正式方案的需求。
      - 受影响任务: 未完成任务(arch_execution_tasks，status 非 done/cancelled/failed)
        且其 reqIds 关联的需求引用候选资产；或 arch_semantic_refs ref_type=task 命中。
      - 另按 arch_semantic_refs 兜底(需求/方案/任务/单测显式登记引用)。
    返回 {reqCount, taskCount, requirements:[...], tasks:[...]}。
    """
    cand = set(candidates)
    req_hits: List[dict] = []
    req_seen: set = set()
    for r in store.RequirementsStore.all():
        used = [a for a in _req_asset_ids(r) if a in cand]
        if not used:
            continue
        loc = r.get("location") or "proposal"
        status = r.get("status") or ""
        # 仅纳入需求池 / 已分析 / 已绑定方案的需求(未入池草稿不在影响范围)。
        if loc == "pool" or status in ("analyzed", "designed", "planned", "executing"):
            req_hits.append({"id": r.get("id") or "", "title": r.get("title") or "",
                             "location": loc, "status": status,
                             "assets": sorted(set(used))[:20]})
            req_seen.add(r.get("id") or "")
    # arch_semantic_refs 显式登记兜底(req/plan/task/test)。
    for a in candidates:
        try:
            for ref in store.SemanticRefsStore.refs_of(a):
                if ref.get("refType") == "req" and ref.get("refId") not in req_seen:
                    r = store.RequirementsStore.get(ref["refId"])
                    if r:
                        loc = r.get("location") or "proposal"
                        status = r.get("status") or ""
                        if loc == "pool" or status in ("analyzed", "designed", "planned", "executing"):
                            req_hits.append({"id": r.get("id") or "", "title": r.get("title") or "",
                                             "location": loc, "status": status,
                                             "assets": [a]})
                            req_seen.add(ref["refId"])
        except Exception:
            continue
    affected_req_ids = {h["id"] for h in req_hits}
    task_hits: List[dict] = []
    for t in store.ExecutionTasksStore.all():
        st = (t.get("status") or "").lower()
        if st in ("done", "cancelled", "failed", "stopped"):
            continue
        used = _task_asset_ids(t)
        # 需求池引用传播 + 显式 task ref 兜底。
        by_req = any(rid in affected_req_ids for rid in (t.get("reqIds") or []))
        direct = any(a in cand for a in used)
        if by_req or direct:
            task_hits.append({"id": t.get("id") or "", "title": t.get("title") or "",
                              "status": t.get("status") or "created",
                              "assets": sorted(set(a for a in used if a in cand))[:20]})
    return {
        "reqCount": len(req_hits), "taskCount": len(task_hits),
        "requirements": req_hits, "tasks": task_hits,
        "assetCount": len(candidates),
    }


def _mark_invalidated(impact: Dict[str, Any], now: int) -> Dict[str, Any]:
    """标记受影响需求/任务为「引用资产已清除，需重新生成方案」。返回统计。"""
    marked_req, marked_task = 0, 0
    for r in impact.get("requirements") or []:
        try:
            store.RequirementsStore.update(r["id"], {
                "assetInvalidated": 1, "assetInvalidatedAt": now,
                "updatedAt": now,
            })
            marked_req += 1
        except Exception as e:
            logger.warning("[semantic] mark req invalidated failed: %s", e)
    for t in impact.get("tasks") or []:
        try:
            store.ExecutionTasksStore.update(t["id"], {
                "assetInvalidated": 1, "updatedAt": now,
            })
            marked_task += 1
        except Exception as e:
            logger.warning("[semantic] mark task invalidated failed: %s", e)
    return {"req": marked_req, "task": marked_task}


def purge_semantic_assets(root: Optional[str], project: Optional[str],
                          stale_days: int = 7,
                          confirm: bool = False) -> Dict[str, Any]:
    """物理删除 stale/deleted 语义资产行(不再软删保留)，并识别对需求/任务的影响。

    流程：
      1) 候选 = 全部 stale + deleted 行(物理删除，不做软删保留)。
      2) 计算影响范围(需求池引用 + 未完成任务) —— 供前端确认提示。
      3) confirm=True 才真正删除；删除后把受影响需求/任务标记
         assetInvalidated=1(提示用户重新生成方案)。
    返回 {purged, impact, marked, dryRun}。
    """
    pid = project_id_for(root, project)
    rows = store.SemanticAssetsStore.all_status(pid, limit=20000)
    now = _ts()
    to_delete: List[str] = []
    by_status: Dict[str, int] = {}
    for a in rows:
        status = a.get("status") or ""
        by_status[status] = by_status.get(status, 0) + 1
        if status in ("deleted", "stale"):
            to_delete.append(a.get("id") or "")
    impact = _impact_of_purge(root, project, to_delete)
    if not confirm:
        return {"purged": 0, "dryRun": True, "confirmRequired": True,
                "candidates": len(to_delete), "byStatus": by_status,
                "impact": impact}
    purged = 0
    if to_delete:
        for i in range(0, len(to_delete), 500):
            purged += store.SemanticAssetsStore.purge(pid, to_delete[i:i + 500])
    marked = _mark_invalidated(impact, now)
    logger.info("[semantic] purge: project=%s purged=%d impact_req=%d impact_task=%d marked=%s by_status=%s",
                pid, purged, impact["reqCount"], impact["taskCount"], marked, by_status)
    return {"purged": purged, "dryRun": False, "confirmRequired": False,
            "candidates": len(to_delete), "byStatus": by_status,
            "impact": impact, "marked": marked}


# ── 文件变化检测 / 失效 / 反向探测(要求②③) ─────────────────────

def changed_files(root: str, project: Optional[str]) -> Dict[str, List[str]]:
    """文件级变更集合。

    主通道 git(`arch_git.diff_worktree` vs baseline)；非 git 仓库回退为
    按 `arch_ast_cache.content_hash` 与磁盘 md5 比对(新增/修改/删除)。
    """
    added, modified, deleted = [], [], []
    root = resolve_root(root, project)
    if not root or not os.path.isdir(root):
        return {"added": [], "modified": [], "deleted": []}
    try:
        from ..project import _resolve_project as _rp
        proj = _rp(root, project)
    except Exception:
        proj = None
    if proj:
        try:
            from ..arch_git import diff_worktree
            d = diff_worktree(proj)
            for f in d.get("files") or []:
                s = f.get("status", "")
                p = _norm_path(f.get("path") or "")
                if not p:
                    continue
                if s == "A":
                    added.append(p)
                elif s == "D":
                    deleted.append(p)
                else:
                    modified.append(p)
            if added or modified or deleted:
                return {"added": added, "modified": modified, "deleted": deleted}
        except Exception as e:
            logger.warning("[semantic] git diff failed: %s", e)
    # 非 git 回退: 以 ast 缓存 content_hash 为基线做哈希比对
    pid = project_id_for(root, project)
    for row in store.AstCacheStore.for_project(pid, limit=4000):
        rel = _norm_path(row.get("filePath") or "")
        if not rel:
            continue
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            deleted.append(rel)
        h = _cache_content_hash(root, rel)
        if h and row.get("contentHash") and h != row.get("contentHash"):
            modified.append(rel)
    return {"added": added, "modified": modified, "deleted": deleted}


def _node_ids_for_files(conn: sqlite3.Connection, files: List[str]) -> List[str]:
    if not files:
        return []
    fs = [_norm_path(f) for f in files][:200]
    ph = ",".join("?" * len(fs))
    try:
        rows = conn.execute(
            f"SELECT id FROM nodes WHERE file_path IN ({ph}) AND kind NOT IN ('file','import')",
            tuple(fs)).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def probe_impact(root: str, project: Optional[str],
                 files: List[str]) -> Dict[str, Any]:
    """新文件反向探测(文件级依赖与调用影响范围)。

    codegraph 路径: 边(target ∈ 新文件符号) 的 source 文件 = 依赖新文件的下游；
    source ∈ 新文件 → 新文件自身依赖。KB/缓存兜底: 从 arch_ast_cache 反向索引解析。
    """
    files = [_norm_path(f) for f in files if f]
    if not files:
        return {"dependents": [], "deps": [], "affectedFiles": []}
    dependents, deps = set(), set()
    conn, _cg_src = open_symbol_conn(root, project)
    if conn is not None:
        try:
            new_ids = _node_ids_for_files(conn, files)
            if new_ids:
                ph = ",".join("?" * len(new_ids))
                rows = conn.execute(
                    f"SELECT e.source, e.target, s.file_path AS sf, t.file_path AS tf "
                    f"FROM edges e "
                    f"JOIN nodes s ON s.id = e.source "
                    f"JOIN nodes t ON t.id = e.target "
                    f"WHERE (e.target IN ({ph}) OR e.source IN ({ph})) "
                    f"AND e.kind IN ('calls','imports','references')",
                    tuple(new_ids + new_ids)).fetchall()
                new_set = set(files)
                for r in rows:
                    if r["target"] in new_ids and r["sf"] and r["sf"] not in new_set:
                        dependents.add(_norm_path(r["sf"]))
                    if r["source"] in new_ids and r["tf"] and r["tf"] not in new_set:
                        deps.add(_norm_path(r["tf"]))
        except Exception as e:
            logger.warning("[semantic] codegraph probe failed: %s", e)
        finally:
            conn.close()
    else:
        # 缓存反向索引兜底
        pid = project_id_for(root, project)
        rows = store.AstCacheStore.for_project(pid, limit=4000)
        file_set = set(files)
        for row in rows:
            rel = _norm_path(row.get("filePath") or "")
            if not rel or rel in file_set:
                continue
            for mod in row.get("imports") or []:
                target = _resolve_import(rel, str(mod))
                if target in file_set:
                    dependents.add(rel)
        for f in files:
            row = store.AstCacheStore.get(pid, f)
            for mod in (row or {}).get("imports") or []:
                t = _resolve_import(f, str(mod))
                if t:
                    deps.add(t)
    affected = set(files) | dependents
    return {"dependents": sorted(dependents), "deps": sorted(deps),
            "affectedFiles": sorted(affected)}


def _resolve_import(src_file: str, module: str) -> str:
    """朴素 import 模块 → 相对文件路径解析(cache 兜底用)。"""
    m = (module or "").strip().strip("'\"")
    if not m:
        return ""
    base = m.replace(".", "/")
    dir = os.path.dirname(src_file)
    for cand in (f"{base}.py", f"{base}.ts", f"{base}.tsx", f"{base}.js",
                 f"{base}/index.ts", f"{base}/index.js", base):
        if cand.startswith("."):
            cand = os.path.join(dir, cand)
        cand = _norm_path(cand)
        if cand and cand != src_file:
            return cand
    return ""


def invalidate_assets_for_files(pid: str, files: List[str], *,
                                change: str = "modified", reason: str = "",
                                root: Optional[str] = None,
                                force: bool = False) -> List[str]:
    """受变更文件影响的资产 → needs_update=1 + status=stale(需更新后使用)。

    force=True: 命中即失效(新文件影响范围)；force=False: 按 anchor 哈希比对，
    仅当文件当前 md5 与提取时签名不一致才失效(避免重复失效刚刷新的资产)。
    """
    files = set(_norm_path(f) for f in files if f)
    if not files:
        return []
    invalidated = []
    for a in store.SemanticAssetsStore.all_status(pid, limit=2000):
        if a.get("status") == "deleted":
            continue
        anchors = {_norm_path(f): h for f, h in (a.get("anchorHashes") or {}).items()}
        if not anchors:
            continue
        hit = files & set(anchors)
        if not hit:
            continue
        if not force:
            changed_hit = [f for f in hit if (not anchors[f])
                           or (_file_md5(root, f) and _file_md5(root, f) != anchors[f])]
            if not changed_hit:
                continue
        # 文件已删 → change=deleted；否则 modified(哈希变化或受新文件影响)
        c = "deleted" if change == "deleted" or any(not anchors[f] for f in hit) else change
        store.SemanticAssetsStore.set_needs_update(a["id"], True, change=c,
                                                   reason=reason or "文件变更")
        invalidated.append(a["id"])
    return invalidated




def handle_stale_asset(asset_id: str, root: Optional[str], project: Optional[str],
                       model_id: Optional[str] = None) -> Dict[str, Any]:
    """过期资产处理(要求①建议)：先增量更新 → 失败软删 + 重新生成。

    返回 {status, refreshed: bool, regenerated: bool, asset?}。
    """
    a = store.SemanticAssetsStore.get(asset_id)
    if not a:
        return {"status": "missing", "refreshed": False, "regenerated": False}
    scope_type = a.get("scopeType") or "project"
    scope_key = a.get("scopeKey") or ""
    _meta = a.get("meta") or {}
    scope_files = _meta.get("files") or []
    scope_symbols = _meta.get("symbols") or []
    res = refresh_scope(root, project, scope_type, scope_key,
                        files=scope_files, symbols=scope_symbols,
                        model_id=model_id)
    if res.get("assets"):
        fresh = next((x for x in res["assets"] if x.get("id") == asset_id), None)
        if fresh:
            return {"status": "refreshed", "refreshed": True, "regenerated": False,
                    "asset": fresh, "degraded": res.get("degraded", False)}
        # 原资产名未再出现 → 该资产已消失，视为软删后由新资产顶替
        store.SemanticAssetsStore.mark_deleted(asset_id)
        return {"status": "regenerated", "refreshed": False, "regenerated": True,
                "asset": res["assets"][0] if res["assets"] else None,
                "degraded": res.get("degraded", False)}
    # 刷新失败(LLM/解析均不可用) → 软删 + 启发式重新生成(离线兜底)。
    # 业务层+逻辑层暂停再生：仅按实现层主类别单趟重新生成。
    store.SemanticAssetsStore.mark_deleted(asset_id)
    try:
        ctx = collect_context(root, scope_type, scope_key,
                              files=scope_files, symbols=scope_symbols,
                              project=project)
        pid = project_id_for(root, project)
        heur = _heuristic_extract_primary(ctx, list(SEMANTIC_KINDS))
        if heur:
            saved = _save_assets(pid, scope_type, scope_key, heur, ctx)
            return {"status": "regenerated", "refreshed": False, "regenerated": True,
                    "asset": saved[0] if saved else None, "degraded": True}
    except Exception as e:
        logger.warning("[semantic] regenerate %s failed: %s", asset_id, e)
    return {"status": "deleted", "refreshed": False, "regenerated": False, "asset": None}


# ── 引用登记(arch_semantic_refs：删除/失效时精确波及引用方) ──

def register_scope_refs(items: Optional[list], ref_type: str, ref_id: str) -> None:
    """登记需求/设计/任务/单测对语义资产的引用(assetScope 项或 assetId 列表)。"""
    if not items:
        return
    for it in items:
        if isinstance(it, dict):
            aid = it.get("assetId") or ""
            role = it.get("role") or "related"
        else:
            aid = str(it or "")
            role = "related"
        if str(aid).startswith("sa-"):
            store.SemanticRefsStore.add(aid, ref_type, ref_id, role)


def referencing_assets(asset_id: str) -> list[dict]:
    """查询某资产被哪些位置引用(供前端给失效告警)。"""
    return store.SemanticRefsStore.refs_of(asset_id)


# ═══ impact（原第 impact 段，纯移动）═══

from . import router  # noqa: F401  (路由随逻辑就地注册)



# ── A6 影响分析：整体基线变更级追踪（跨组件扩散链 + 契约↔实现全局漂移） ──

def _impact_analysis(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    """变更追踪（stale/needsUpdate 资产 + 关系边扩散）+ 全局漂移（活跃契约条目 ↔ 实现锚点）。"""
    pid = project_id_for(root, project)
    empty = {"direct": [], "propagated": [], "drift": [],
             "coverage": {"verifiable": 0, "covered": 0, "pct": 0}, "patterns": []}
    if not pid:
        return empty
    rows = store.SemanticAssetsStore.all_status(pid, limit=4000)
    by_id = {a.get("id"): a for a in rows if a.get("id")}
    # 直接变更：reconcile 标记的 stale / needsUpdate（排除 deleted）
    direct = [a for a in rows
              if a.get("status") == "stale" or a.get("needsUpdate")]
    direct_ids = {a.get("id") for a in direct}
    # 扩散：经关系边，引用直接变更资产的活跃资产间接受影响
    g = semantic_graph(root, project, kind="", scopes=None, level="",
                       limit=2000, focus="", hops=1)
    active_ids = {n.get("id") for n in g.get("nodes") or []}
    via_map: Dict[str, str] = {}
    for e in g.get("edges") or []:
        to, frm = e.get("to"), e.get("from")
        if to in direct_ids and frm not in direct_ids \
                and frm in active_ids and frm not in via_map:
            via_map[frm] = to
    propagated = [{"id": bid,
                   "name": (by_id.get(bid) or {}).get("name") or bid,
                   "kind": (by_id.get(bid) or {}).get("kind") or "",
                   "via": v,
                   "viaName": (by_id.get(v) or {}).get("name") or v}
                  for bid, v in via_map.items()]
    # 全局漂移：活跃契约条目(confirmed/injected/verifying) ↔ 实现锚点
    anchors_by_asset: Dict[str, List[tuple]] = {}
    for a in rows:
        refs = a.get("astRefs") or []
        if refs:
            anchors_by_asset[a.get("id")] = [
                (r.get("file") or "", r.get("symbol") or "") for r in refs]
    items = store.ContractItemStore.list(pid, limit=500)
    drift: List[Dict[str, Any]] = []
    verifiable = covered = 0
    for it in items:
        if it.get("status") not in ("confirmed", "injected", "verifying"):
            continue
        tgt = it.get("target") or {}
        file = tgt.get("file") or ""
        symbol = tgt.get("symbol") or ""
        quote = (it.get("origin") or {}).get("quote") or ""
        base = {"itemId": it.get("id"), "kind": it.get("kind") or "", "quote": quote}
        if not file and not symbol:
            drift.append({**base, "reason": "intent"})
            continue
        verifiable += 1
        matched = None
        for aid, al in anchors_by_asset.items():
            if any((not file or f == file) and (not symbol or s == symbol)
                   for f, s in al):
                matched = aid
                break
        if not matched:
            drift.append({**base, "reason": "missing"})
            continue
        node = by_id.get(matched) or {}
        if node.get("status") == "stale" or node.get("needsUpdate"):
            drift.append({**base, "reason": "stale", "assetId": matched,
                          "assetName": node.get("name") or ""})
            continue
        covered += 1
    pct = round(covered / verifiable * 100) if verifiable else 0
    by_kind: Dict[str, int] = {}
    for x in drift:
        if x["reason"] == "intent":
            continue
        by_kind[x["kind"]] = by_kind.get(x["kind"], 0) + 1
    patterns = [{"kind": k, "count": c} for k, c in
                sorted(by_kind.items(), key=lambda kv: -kv[1])]
    return {
        "direct": [{"id": a.get("id"), "name": a.get("name") or "",
                    "kind": a.get("kind") or ""} for a in direct],
        "propagated": propagated,
        "drift": drift,
        "coverage": {"verifiable": verifiable, "covered": covered, "pct": pct},
        "patterns": patterns,
    }


@router.get("/kb/semantic/impact")
async def api_impact(root: Optional[str] = None, project: Optional[str] = None):
    """A6 影响分析：跨组件变更扩散链 + 契约↔实现全局漂移总览。"""
    _lazy_reconcile(root, project)
    return ok(_impact_analysis(root, project))


@router.get("/kb/semantic/source-snippet")
async def api_source_snippet(root: Optional[str] = None, project: Optional[str] = None,
                             file: str = "", line: int = 0, symbol: str = "",
                             before: int = 10, after: int = 10, limit: int = 60):
    """锚点前后源码窗口（实现层逻辑精确核对）。

    symbol 已知（AST 缓存可解析行段）→ 优先展开整个符号体（startLine..endLine + 尾部余量）；
    否则按 anchor±before/after 取窗口。总窗口上限 limit 行，防超长文件全量返回。
    """
    rpath = resolve_root(root, project)
    if not rpath or not file:
        return err(400, "缺少项目根或文件路径")
    full = os.path.realpath(os.path.join(rpath, file))
    base = os.path.realpath(rpath)
    if not full.startswith(base + os.sep):
        return err(400, f"路径越界: {file}")
    if not os.path.isfile(full):
        return err(400, f"文件不存在: {file}")
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except Exception as e:
        return err(500, f"读取失败: {e}")
    if not lines:
        return ok({"file": file, "symbol": symbol, "anchorLine": 0,
                   "highlight": [], "lines": []})
    n = len(lines)
    anchor = int(line or 0)
    start = end = anchor
    highlight: List[int] = []
    resolved = False
    if symbol and anchor:
        # AST 缓存里有该符号的行段 → 整段显示（更精确覆盖实现层逻辑）
        try:
            pid = project_id_for(root, project)
            cached = store.AstCacheStore.get(pid, file.replace("\\", "/"))
            for nd in (cached or {}).get("symbols") or []:
                if (nd.get("name") or "") == symbol:
                    s_, e_ = int(nd.get("startLine") or 0), int(nd.get("endLine") or 0)
                    if s_ and e_:
                        start, end = s_, e_
                        highlight = list(range(s_, min(e_ + 1, n + 1)))
                        resolved = True
                    break
        except Exception:
            logger.warning("[semantic] source-snippet 符号行段解析失败: %s", symbol)
        if not resolved:
            # AST 缓存缺行段(如 ts 符号未记录行号) → codegraph 符号表兜底：
            # 优先取包含锚点行的符号体，否则取同名首个有行段的符号。
            try:
                rows: List[tuple] = []
                conn, _cg_src = open_symbol_conn(root, project)
                if conn is not None:
                    rel = _norm_path(file)
                    rows = conn.execute(
                        "SELECT start_line, end_line FROM nodes "
                        "WHERE file_path = ? AND (name = ? OR qualified_name = ?) "
                        "AND start_line > 0 AND end_line > 0",
                        (rel, symbol, symbol)).fetchall()
                    conn.close()
                span = next(((s_, e_) for s_, e_ in rows if s_ <= anchor <= e_), None)
                if span is None and rows:
                    span = (rows[0][0], rows[0][1])
                if span:
                    start, end = span
                    highlight = list(range(start, min(end + 1, n + 1)))
            except Exception as e:
                logger.warning("[semantic] source-snippet codegraph 行段兜底失败: %s", e)
    if not anchor:
        anchor = start
    b = max(1, (anchor or 1) - before)
    e = min(n, max(end + after, (anchor or 1) + after))
    if e - b + 1 > limit:  # 上限裁剪（防超长）
        e = b + limit - 1
    out = [{"line": i, "code": lines[i - 1]} for i in range(b, e + 1)]
    highlight = [h for h in highlight if b <= h <= e]
    return ok({"file": file, "symbol": symbol, "anchorLine": anchor,
               "highlight": highlight, "lines": out})






@router.post("/kb/semantic/reconcile")
async def api_reconcile(request: Request):
    body = await request.json()
    force = bool(body.get("force"))
    res = reconcile_semantic(body.get("root"), body.get("project"), force=force)
    return ok(res)


@router.post("/kb/semantic/handle-stale")
async def api_handle_stale(request: Request):
    body = await request.json()
    asset_id = (body.get("assetId") or body.get("asset_id") or "").strip()
    if not asset_id:
        return err(400, "assetId 不能为空")
    # 提取/重提触及 tAgent asyncio.run，不能在事件循环线程直接调 → offload 到线程
    res = await asyncio.to_thread(
        handle_stale_asset, asset_id, body.get("root"), body.get("project"),
        body.get("modelId"))
    return ok(res)


@router.post("/kb/semantic/extract")
async def api_extract(request: Request):
    body = await request.json()
    st, sk, files, symbols = _scope(body)
    lvl = body.get("level") or "implementation"
    logger.info("[semantic] /kb/semantic/extract 请求: type=%s key=%s files=%d symbols=%d kinds=%s level=%s",
                st, sk or "-", len(files or []), len(symbols or []), body.get("kinds"), lvl)
    # offload 到线程：tAgent 提取用 asyncio.run，不能在事件循环线程直接调(否则静默落地板)
    res = await asyncio.to_thread(
        extract_scope, body.get("root"), body.get("project"), st, sk, files, symbols,
        kinds=body.get("kinds"), model_id=body.get("modelId"), level=lvl)
    if not (res.get("count") or 0):
        logger.warning("[semantic] /kb/semantic/extract 产出 0: type=%s key=%s source=%s degraded=%s",
                       st, sk or "-", res.get("source"), res.get("degraded"))
    return ok(res)


@router.post("/kb/semantic/asset-diagram")
async def api_asset_diagram(request: Request):
    """静态资产 → 图：entity → classDiagram(字段/方法)，state → stateDiagram。

    body: {assetIds?: [...], project?: str}  (assetIds 缺省 = 项目内 entity/state 资产)
    返回 {diagrams: [{assetId, name, type, mermaid}]}
    """
    body = await request.json()
    from .. import asset_diagram
    ids = body.get("assetIds") or []
    if ids:
        assets = [store.SemanticAssetsStore.get(i) for i in ids[:20]]
        assets = [a for a in assets if a]
    else:
        pid = project_id_for(body.get("root"), body.get("project"))
        assets = []
        if pid:
            for k in ("entity", "state"):
                assets += [a for a in store.SemanticAssetsStore.all(pid, k, limit=20)
                           if (a.get("level") or "implementation") == "implementation"
                           and (a.get("status") or "active") == "active"]
    return ok(asset_diagram.build_asset_diagrams(assets))


@router.post("/kb/semantic/refresh")
async def api_refresh(request: Request):
    body = await request.json()
    st = body.get("scopeType") or body.get("scope", {}).get("type", "project")
    sk = body.get("scopeKey") or body.get("scope", {}).get("key", "")
    # files/symbols 范围: 从该范围既有资产恢复文件/符号清单(避免退化为全项目)
    files, symbols = [], []
    if st in ("files", "symbols"):
        pid = project_id_for(body.get("root"), body.get("project"))
        rows = store.SemanticAssetsStore.find_by_scope(pid, st, sk)
        if rows:
            m = rows[0].get("meta") or {}
            files = m.get("files") or []
            symbols = m.get("symbols") or []
    # offload 到线程：refresh_scope 内部重提触及 tAgent asyncio.run
    res = await asyncio.to_thread(
        refresh_scope, body.get("root"), body.get("project"), st, sk,
        files=files, symbols=symbols, model_id=body.get("modelId"))
    return ok(res)


@router.post("/kb/semantic/aggregate")
async def api_aggregate_high(request: Request):
    """按需聚合 H 级(业务概念级)语义资产：从已提取 M/L 资产 + 组件依赖图合成。"""
    body = await request.json()
    res = _aggregate_high(body.get("root"), body.get("project"),
                          model_id=body.get("modelId"))
    return ok(res)


@router.post("/kb/semantic/batch")
async def api_batch(request: Request):
    """批量管理选定组件范围的语义资产(extract/clear/update)。

    body: {action, components?, includeOther?, kinds?, modelId?, level?, scope?, dryRun?}
    scope: 与 search 一致的组件范围(空/缺省=全部，['__other__']=仅其它)。
    clear 支持 dryRun=true 预览影响(需求池/任务)供前端确认。
    """
    body = await request.json()
    logger.info("[semantic] /kb/semantic/batch 请求: action=%s components=%d include_other=%s",
                body.get("action"), len(body.get("components") or []), body.get("includeOther"))
    res = batch_manage(body.get("root"), body.get("project"),
                       body.get("action") or "extract",
                       comp_ids=body.get("components") or [],
                       include_other=bool(body.get("includeOther")),
                       kinds=body.get("kinds"),
                       model_id=body.get("modelId"),
                       level=body.get("level") or "",
                       scopes=body.get("scope"),
                       dry_run=bool(body.get("dryRun")))
    logger.info("[semantic] /kb/semantic/batch 响应: action=%s count=%s components=%s",
                body.get("action"), res.get("count"), res.get("components"))
    return ok(res)


@router.post("/kb/semantic/purge")
async def api_purge_semantic(request: Request):
    """物理删除 stale/deleted 语义资产行，并识别对需求池/未完成任务的影响。

    body: {root?, project?, staleDays?, confirm?}
      - 首次调用(confirm 缺省 false) → 仅返回影响范围(dryRun)，前端弹确认提示。
      - 用户确认后带 confirm=true → 真正物理删除，并把受影响需求/任务标记
        assetInvalidated(提示重新生成方案)。
    返回 {purged, impact:{reqCount,taskCount,requirements,tasks}, marked, dryRun}。
    """
    body = await request.json()
    res = purge_semantic_assets(body.get("root"), body.get("project"),
                                stale_days=int(body.get("staleDays") or 7),
                                confirm=bool(body.get("confirm")))
    return ok(res)


# ── 动态路由置底注册（A1-T2：避免 {asset_id} 遮蔽静态路径）──
@router.get("/kb/semantic/codegraph")
async def api_codegraph_status(root: Optional[str] = None, project: Optional[str] = None):
    from .. import ctx
    from .codegraph import codegraph_status, effective_mode, kv_mode
    from .symbols import symbol_source_state, _resolve_core_pid, _open_core_conn
    mode = effective_mode()
    st = codegraph_status()
    # root 解析：显式参数 > 请求上下文(注册项目 rootPath)
    _root = (root or '').strip()
    if not _root:
        _pid_ctx = ctx.get_project()
        _root = (store.ProjectsStore.get(_pid_ctx) or {}).get('rootPath', '') if _pid_ctx else ''
    _root = _root or ''
    # native 统计（root 优先于 codegraph_status 内部上下文解析）
    _core_pid = _resolve_core_pid(_root)
    if _core_pid:
        _conn = _open_core_conn(_core_pid)
        if _conn is not None:
            try:
                st['corePid'] = _core_pid
                st['nativeNodes'] = _conn.execute("SELECT COUNT(*) FROM graph_node").fetchone()[0]
                st['nativeEdges'] = _conn.execute("SELECT COUNT(*) FROM graph_edge").fetchone()[0]
            except Exception:
                st['nativeNodes'] = st['nativeEdges'] = 0
        else:
            st['corePid'] = _core_pid
            st['nativeNodes'] = st['nativeEdges'] = 0
    ns = symbol_source_state(_root, project or ctx.get_project())
    return ok({"mode": mode, "env": os.environ.get("ARCH_CODEGRAPH", "").strip().lower(),
               "cli": st["cli"], "cliPath": st["cliPath"],
               "kv": kv_mode(), "source": "env" if os.environ.get("ARCH_CODEGRAPH") else ("kv" if kv_mode() else "default"),
               "corePid": st.get('corePid', ''),
               "native": {"nodes": st.get('nativeNodes', 0), "edges": st.get('nativeEdges', 0)},
               "state": {"head": ns['head'], "lastHead": ns['lastHead'],
                         "dirty": ns['dirty'], "stale": ns['stale'],
                         "staleCount": len(ns['staleFiles'])}})


@router.post("/kb/semantic/codegraph")
async def api_codegraph_set(body: dict = None):
    from .codegraph import set_kv_mode
    body = body or {}
    mode = str(body.get("mode") or "")
    if not set_kv_mode(mode):
        return err(400, "mode 必须为 on/off/auto")
    return ok({"mode": mode})


@router.post("/kb/semantic/symbol-sync")
async def api_symbol_sync(body: dict = None):
    """发起基线变更请求（职责划分：architect 仅发起，执行在 KB 知识库管理）。

    调 KB knowledge.pullRequest 写入待更新标记(pending)，由 KB 知识库管理界面
    确认后执行 updateConfirm(拉取/预览) + version.sync(增量分析+社区重划分) +
    cleanup(物理清除腐烂旧基线数据)。请求成功后记录跟踪状态 head。

    ⚠️ 双模式（勿"统一"，决策见 api_cold_start docstring）：仓库已有 core 项目
    → 走本端点（发起-确认-执行，防误同步）；仅冷启动(无项目、KB 管理无入口
    可承接确认流)才由 api_cold_start 直接编排执行。
    """
    from .. import ctx
    from ..kb_gateway import call_kb
    from .symbols import _resolve_core_pid, record_sync, _git
    body = body or {}
    proj = body.get('project') or ctx.get_project()
    root = resolve_root(body.get('root') or None, proj)
    if not root:
        return err(400, "项目 root 解析失败")
    pid = _resolve_core_pid(root)
    if not pid:
        return err(400, "KB 注册表无此仓库对应项目，请先在 KB 知识库管理中建项/建基线")
    head = (_git(root, ['rev-parse', 'HEAD'], timeout=15) or '').strip()
    if not head:
        return err(400, "无法获取仓库 HEAD commit")
    try:
        res = call_kb('knowledge.pullRequest', project_id=pid, head=head,
                      note='architect-manual-baseline-request')
    except Exception as e:
        return err(500, f"基线变更请求失败: {e}")
    if res is None:
        return err(503, "KB 服务不可达，请稍后重试")
    record_sync(pid, head)
    return ok({"requested": True, "requestId": (res or {}).get('requestId'),
                "corePid": pid, "head": head,
                "message": "已在 KB 知识库管理创建待确认的基线变更请求"})


@router.get("/kb/semantic/baseline-diff")
async def api_baseline_diff(root: Optional[str] = None, project: Optional[str] = None):
    """基线(lastHead) → 工作区 变更文件集（三视图 diff 数据源）。

    core 侧图谱/语义资产无版本快照，diff 以「变更文件集 × 当前资产/节点文件引用」
    叠加到三视图（概览文件清单 / 语义资产行级徽标 / 图谱节点着色）。
    """
    from .. import ctx
    from .symbols import baseline_diff
    _root = (root or '').strip()
    if not _root:
        _pid_ctx = project or ctx.get_project()
        _root = (store.ProjectsStore.get(_pid_ctx) or {}).get('rootPath', '') if _pid_ctx else ''
    return ok(baseline_diff(_root or None, project or ctx.get_project()))


@router.post("/kb/semantic/cold-start")
def api_cold_start(body: dict = None):
    """冷启动：未注册仓库 → core 建项(project.import，含初始基线) + 全量分析
    (analysis.createTask+runTask)。决策①「冷启动自动触发+全仓库」；职责划分：
    architect 发起，core 执行。完成后记录跟踪状态(lastHead=HEAD)使符号源对齐。

    ⚠️ 双模式决策依据（勿与 api_symbol_sync "统一"，两者刻意不同）：
    - 本端点「直接编排执行」仅适用于冷启动——仓库尚无 core 项目，KB 知识库
      管理界面没有可承接确认流的入口，走 pullRequest 会死锁（无项目可挂请求）。
      自举一次性操作，且 import 天然是"建基线"语义，无覆盖风险。
    - 仓库已有项目 → 必须走 api_symbol_sync 的「发起 knowledge.pullRequest →
      KB 管理确认 → version.sync 执行」确认流（决策④），防止未确认就重分析。
    同步 def：内含轮询 sleep(≤180s)，FastAPI 丢线程池执行，勿改回 async def
    （call_kb 为阻塞 urllib，async 下会卡事件循环）。
    """
    from .. import ctx
    from ..kb_gateway import call_kb
    from .symbols import _resolve_core_pid, record_sync, invalidate_native_cache, _git
    import time as _time
    body = body or {}
    proj = body.get('project') or ctx.get_project()
    root = resolve_root(body.get('root') or None, proj)
    root = (root or '').strip()
    if not root:
        return err(400, "项目 root 解析失败")
    if _resolve_core_pid(root):
        return err(400, "仓库已在 KB 注册，无需冷启动；如基线过期请用「发起基线变更」")
    head = (_git(root, ['rev-parse', 'HEAD']) or '').strip()
    if not head:
        return err(400, "非 git 仓库或无法获取 HEAD，无法冷启动")
    # ① 建项 + 初始基线（异步 → 轮询 importStatus）
    try:
        imp = call_kb('project.import', path=root, mode="static", timeout=60)
    except Exception as e:
        return err(500, f"建项请求失败: {e}")
    if not imp or not imp.get('requestId'):
        return err(503, "KB 服务不可达，冷启动失败")
    request_id = imp['requestId']
    pid = None
    deadline = _time.time() + 180
    while _time.time() < deadline:
        _time.sleep(2)
        st = call_kb('project.importStatus', requestId=request_id, timeout=30)
        if not st:
            return err(503, "KB 服务不可达，建项状态查询失败")
        if st.get('status') == 'done':
            pid = st.get('projectId') or ''
            break
        if st.get('status') in ('error', 'unknown'):
            return err(500, f"建项失败: {st.get('error') or st.get('status')}")
    if not pid:
        return ok({"started": False, "requestId": request_id,
                   "message": "建项进行中（文件扫描），请稍后在 KB 知识库管理查看/继续全量分析"})
    invalidate_native_cache()
    # ② 全量分析（异步，fire-and-forget；不阻塞等待，分析在 core 后台跑）
    task_id = ''
    try:
        task = call_kb('analysis.createTask', project_id=pid, type="full",
                       name="cold-start", timeout=30)
        if task and task.get('id'):
            task_id = task['id']
            call_kb('analysis.runTask', task_id=task_id, timeout=30)
    except Exception as e:
        logger.warning("[semantic] 冷启动全量分析发起失败: %s", e)
    # ③ 记录跟踪状态（符号源对齐 HEAD）
    record_sync(pid, head)
    return ok({"started": True, "projectId": pid, "taskId": task_id, "head": head,
               "message": "冷启动完成：项目已建项+初始基线，全量分析进行中（图谱/社区完成后符号源即生效）"})


@router.get("/kb/semantic/mappings")
async def api_mappings(root: Optional[str] = None, project: Optional[str] = None,
                       asset_ids: str = ""):
    ids = [x for x in (asset_ids or "").split(",") if x.strip()]
    out = []
    for i in ids:
        out += mappings(i.strip(), root, project)
    return ok(out)

@router.get("/kb/semantic/status")
async def api_status(root: Optional[str] = None, project: Optional[str] = None):
    """资产新鲜度状态(含 stale/deleted 统计 + 变更文件)。"""
    _lazy_reconcile(root, project, force=True)
    pid = project_id_for(root, project)
    rows = store.SemanticAssetsStore.all_status(pid, limit=4000)
    counts = {"active": 0, "stale": 0, "deleted": 0, "needsUpdate": 0}
    for a in rows:
        counts[a.get("status") or "active"] = counts.get(a.get("status") or "active", 0) + 1
        if a.get("needsUpdate"):
            counts["needsUpdate"] += 1
    changed = changed_files(resolve_root(root, project), project)
    return ok({"counts": counts, "total": len(rows),
               "changed": {k: v for k, v in changed.items()}})

@router.get("/kb/semantic/stats")
async def api_semantic_stats(root: Optional[str] = None, project: Optional[str] = None):
    """资产概览统计：总量 / 按类别(结构/行为/规则/契约) / 按粒度(高/中/低) / 状态。"""
    _lazy_reconcile(root, project)
    pid = project_id_for(root, project)
    by_kind: Dict[str, int] = {}
    for k in SEMANTIC_KINDS:
        by_kind[k] = store.SemanticAssetsStore.count(pid, kind=k)
    by_level: Dict[str, int] = {}
    for lv in SEMANTIC_LEVELS:
        by_level[lv] = store.SemanticAssetsStore.count(pid, level=lv)
    rows = store.SemanticAssetsStore.all_status(pid, limit=4000)
    status = {"active": 0, "stale": 0, "deleted": 0, "needsUpdate": 0}
    for a in rows:
        status[a.get("status") or "active"] = status.get(a.get("status") or "active", 0) + 1
        if a.get("needsUpdate"):
            status["needsUpdate"] += 1
    return ok({
        "total": sum(by_kind.values()),
        "byKind": by_kind,
        "byLevel": by_level,
        "status": status,
    })

@router.get("/kb/semantic/graph")
async def api_graph(root: Optional[str] = None, project: Optional[str] = None,
                    kind: str = "", scope: str = "", level: str = "", limit: int = 2000,
                    focus: str = "", hops: int = 1, include_indirect: bool = False):
    """语义层图谱：节点=语义资产，边=资产 relations，锚点=AST 引用。

    scope: 逗号分隔的组件范围(scope_key)；kind: 资产种类过滤；level: 抽象粒度过滤。
    focus: 单资产聚焦(仅返回其周围 hops 跳子图)；hops: 聚焦跳数，默认 1。
    include_indirect: 追加 1 跳中转间接边(虚线展示，默认关)。
    """
    scopes = [s.strip() for s in (scope or "").split(",") if s.strip()] or None
    lvl = level if level in SEMANTIC_LEVELS else ""
    return ok(semantic_graph(root, project, kind, scopes, level=lvl, limit=limit,
                             focus=focus, hops=hops,
                             include_indirect=include_indirect))

@router.get("/kb/semantic/{asset_id}")
async def api_detail(asset_id: str, root: Optional[str] = None, project: Optional[str] = None):
    a = detail(asset_id, root, project)
    if not a:
        return err(404, f"语义资产 {asset_id} 不存在")
    return ok(a)


@router.get("/kb/semantic/{asset_id}/pseudo")
async def api_pseudo(asset_id: str, root: Optional[str] = None,
                     project: Optional[str] = None, model_id: Optional[str] = None):
    """查询时生成/返回资产关联代码的伪码级说明(有效生命周期内缓存)。"""
    # LLM 同步调用 offload 到线程(P0：async 内禁阻塞事件循环)
    return ok(await asyncio.to_thread(generate_pseudo, asset_id, root, project, model_id))


@router.get("/kb/semantic/{asset_id}/node-brief")
async def api_node_brief(asset_id: str, root: Optional[str] = None, project: Optional[str] = None,
                         model_id: Optional[str] = None, force: bool = False):
    """资产节点简介(≤80 字代码级描述；fresh 命中缓存 / stale·force 重生成；失败降级原 desc)。"""
    def _run():
        a = store.SemanticAssetsStore.get(asset_id)
        if not a:
            return {"brief": "", "cached": False, "degraded": True, "error": "资产不存在"}
        return generate_node_brief(a, root, project, model_id, force)
    return ok(await asyncio.to_thread(_run))


@router.get("/kb/semantic/{asset_id}/line-notes")
async def api_line_notes(asset_id: str, file: str, start: int, end: int,
                         root: Optional[str] = None, project: Optional[str] = None,
                         model_id: Optional[str] = None, force: bool = False):
    """资产卡源码窗口关键行逐行用途说明(手动触发，落库缓存随资产生命周期)。
    force=True 跳过缓存读取，重新生成并覆盖原窗口缓存。"""
    return ok(await asyncio.to_thread(
        generate_line_notes, asset_id, file, start, end, root, project, model_id, force))


# ── 静态查询路由置底（A1-T2：在 {asset_id} 动态路由之后注册）──






