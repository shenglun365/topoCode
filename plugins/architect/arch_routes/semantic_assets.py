"""Semantic Data Assets — architect 自持语义数据资产提取/检索服务。

语义资产按「类别(关切维度) × 抽象粒度(离代码远近)」二维正交分类：
  类别 kind:
    - structure : 结构(数据/状态)      - behavior : 行为(流程)
    - rule      : 规则(决策/约束)      - contract : 契约(接口/交互)
  粒度 level(越低越贴近代码实现):
    - high   : 概念/业务级(domain_entity / business_process / business_rule / business_contract)
    - medium : 逻辑/设计级(data_structure / processing_flow / control_logic / service_contract)
    - low    : 实现/代码级(concrete_type / call_chain / branch_logic / message_contract)

设计要点(结合最新代码结构):
  - 符号数据源: codegraph `.codegraph/codegraph.db`(提取前 `codegraph sync` 保鲜)，
    缺失时降级为轻量文件扫描; KB `architecture.model` 仅作组件归属/baseline 上下文。
  - LLM 通道: 复用 req_agent.llm_sync(经 KbGateway 转主后端)。LLM 不可用 → 启发式降级
    (L 级确定性映射/名=符号名、描述=docstring/签名摘要)，AST 锚点始终取真实 codegraph 节点。
  - 粒度策略: L 级确定性提取(零 LLM 成本，代码事实层)；M 级 LLM 按组件归纳(逻辑组织层)；
    H 级按需聚合(业务功能模块层，从 M/L 资产 + 跨组件依赖图合成，锚定下级防漂移)。
  - AST 关联: LLM 以符号名引用 → 服务端按符号表解析为真实 AstNodeRef(file/symbol/
    kind/startLine/endLine)，杜绝臆造行号。
  - 增量: 同范围重提 → src_hash 比对，change ∈ same|added|modified，旧资产标 stale。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request

from .common import _ts, err, ok
from . import store

logger = logging.getLogger(__name__)
router = APIRouter()

SEMANTIC_KINDS = ("entity", "contract", "state", "rule", "process", "decision")
SEMANTIC_LEVELS = ("implementation", "logic", "business")

# 类别轴：静态·定义(是什么) / 动态·处理(发生什么)。
SEMANTIC_CATEGORY = {
    "entity": "static", "contract": "static", "state": "static", "rule": "static",
    "process": "dynamic", "decision": "dynamic",
}
STATIC_KINDS = ("entity", "contract", "state", "rule")
DYNAMIC_KINDS = ("process", "decision")

_KIND_LABEL = {
    "entity": "实体(数据对象/领域实体)",
    "contract": "契约(接口/消息/事件/端点)",
    "state": "状态(生命周期定义/状态集+迁移)",
    "rule": "规则(配置化的约束/策略定义)",
    "process": "过程(输入→处理→输出/流程)",
    "decision": "决策(运行时分支/策略执行)",
}

# 规范分类在各级粒度下的具体形态(供 prompt / 前端标注)。
_LEVEL_KIND_FORM = {
    ("business", "entity"): "business_entity 聚合根/业务概念",
    ("business", "contract"): "business_capability 对外业务能力",
    ("business", "state"): "lifecycle 业务生命周期",
    ("business", "rule"): "business_policy 业务政策/规章",
    ("business", "process"): "business_process 端到端业务过程",
    ("business", "decision"): "business_strategy 业务策略选择",
    ("logic", "entity"): "logical_data 领域实体/规范化关系",
    ("logic", "contract"): "service_contract 服务/接口契约",
    ("logic", "state"): "state_flow 状态机(迁移表)",
    ("logic", "rule"): "configured_rule 配置化规则定义",
    ("logic", "process"): "processing_flow 用例/流程",
    ("logic", "decision"): "control_logic 决策表/分支",
    ("implementation", "entity"): "concrete_type 具体类型(class/struct/enum)",
    ("implementation", "contract"): "message_contract 签名/路由/schema",
    ("implementation", "state"): "enum 枚举/状态字段",
    ("implementation", "rule"): "config_item 配置结构/阈值定义",
    ("implementation", "process"): "call_chain 函数执行序列",
    ("implementation", "decision"): "branch_logic if/switch 分支",
}

# 统一 id 编码规则：sa-{cat_code}-{gran_code}-{kind_code}-{seq}。每段 1 字母码。
_CAT_CODE = {"static": "s", "dynamic": "d"}
_GRAN_CODE = {"implementation": "i", "logic": "l", "business": "b"}
_KIND_CODE = {"entity": "e", "contract": "c", "state": "s", "rule": "r",
              "process": "p", "decision": "d"}


def _id_prefix(level: Optional[str], kind: Optional[str]) -> str:
    """语义资产 id 统一编码前缀: sa-{cat}-{gran}-{kind}。未知取值回落 sa-x-x-x。"""
    cat = _CAT_CODE.get(SEMANTIC_CATEGORY.get(kind or ""), "x")
    return f"sa-{cat}-{_GRAN_CODE.get(level or '', 'x')}-{_KIND_CODE.get(kind or '', 'x')}"

# codegraph node.kind → AstNodeKind
_AST_KIND_MAP = {
    "class": "class", "struct": "class", "interface": "class", "enum": "class",
    "component": "class", "type_alias": "class",
    "method": "method", "constructor": "method",
    "function": "func", "func": "func", "route": "func",
    "field": "field", "property": "field", "variable": "field",
    "constant": "field", "enum_member": "field",
}

_NODE_COLS = (
    "id, kind, name, qualified_name, file_path, start_line, end_line, "
    "start_column, end_column, signature, docstring, return_type"
)

_SCHEMA_KIND_TO_LLM = {k: k for k in SEMANTIC_KINDS}


# ── 项目/路径解析 ─────────────────────────────────────────────

def project_id_for(root: Optional[str], project: Optional[str]) -> str:
    """按 arch_projects 解析项目稳定 id(未登记路径 → 按 root 哈希合成)。"""
    from .project import _resolve_project as _rp
    try:
        proj = _rp(root, project)
    except Exception:
        proj = None
    if proj and proj.get("id"):
        return proj["id"]
    return _stable_id(root or "")


def _stable_id(root: str) -> str:
    h = hashlib.md5((root or "").encode("utf-8")).hexdigest()[:10]
    return f"proj-{h}"


def resolve_root(root: Optional[str], project: Optional[str]) -> Optional[str]:
    from .project import _resolve_project as _rp
    try:
        proj = _rp(root, project)
    except Exception:
        proj = None
    r = (proj or {}).get("rootPath") or (root or "").strip()
    return r or None


def _norm_path(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("/")


# ── codegraph 适配器 ──────────────────────────────────────────

def cg_dir(root: str) -> Optional[str]:
    """定位项目 codegraph 索引目录(.codegraph/)。"""
    if not root or not os.path.isdir(root):
        return None
    d = os.path.join(root, ".codegraph")
    if os.path.isdir(d) and os.path.isfile(os.path.join(d, "codegraph.db")):
        return d
    return None


def ensure_synced(root: str, timeout: int = 90) -> bool:
    """确保 codegraph 索引存在且保鲜。无索引/同步失败返回 False(调用方降级)。"""
    if not root or not os.path.isdir(root):
        return False
    try:
        r = subprocess.run(["codegraph", "status", "-j", root],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            data = json.loads(r.stdout or "{}") if (r.stdout or "").strip() else {}
            if not data.get("initialized"):
                return False
        else:
            return False
    except Exception:
        return False
    try:
        subprocess.run(["codegraph", "sync", "-q", root],
                       capture_output=True, text=True, timeout=timeout)
    except Exception:
        logger.warning("[semantic] codegraph sync failed (best-effort)")
    return True


def _open_cg(root: str) -> Optional[sqlite3.Connection]:
    d = cg_dir(root)
    if not d:
        return None
    try:
        conn = sqlite3.connect(f"file:{os.path.join(d, 'codegraph.db')}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.warning("[semantic] open codegraph.db failed: %s", e)
        return None


def _query_nodes(conn: sqlite3.Connection, files: Optional[List[str]] = None,
                 symbols: Optional[List[str]] = None, limit: int = 400) -> List[dict]:
    """查询符号节点。files 为相对路径(正斜杠)；symbols 按 name/qualified_name 匹配。"""
    conds, params = [], []
    if files:
        fs = [_norm_path(f) for f in files if f][:200]
        if fs:
            ph = ",".join("?" * len(fs))
            conds.append(f"file_path IN ({ph})")
            params += fs
    if symbols:
        sym_conds, sym_params = [], []
        for s in symbols[:60]:
            sym_conds.append("(name = ? OR qualified_name = ?)")
            sym_params += [s, s]
        conds.append("(" + " OR ".join(sym_conds) + ")")
        params += sym_params
    if not conds:
        conds.append("1=1")
    sql = (
        f"SELECT {_NODE_COLS} FROM nodes "
        f"WHERE ({' AND '.join(conds)}) AND kind NOT IN ('file','import') "
        f"ORDER BY file_path, start_line LIMIT ?"
    )
    params.append(int(limit))
    try:
        rows = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
        if files and fs and not rows:
            logger.warning("[semantic] codegraph 未匹配到任何节点: 请求文件 %d 个(如 %s)，"
                           "codegraph file_path 可能是绝对路径/格式不同。"
                           "样例 codegraph file_path: %s",
                           len(fs), fs[:3], _cg_sample_paths(conn))
        return rows
    except Exception as e:
        logger.warning("[semantic] query nodes failed: %s", e, exc_info=True)
        return []


def _cg_sample_paths(conn: sqlite3.Connection, limit: int = 5) -> list:
    """取 codegraph 里实际存储的 file_path 样例，辅助诊断相对/绝对路径差异。"""
    try:
        rows = conn.execute(
            "SELECT DISTINCT file_path FROM nodes WHERE file_path IS NOT NULL AND file_path != '' "
            "ORDER BY file_path LIMIT ?", (limit,)).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _query_edges(conn: sqlite3.Connection, node_ids: List[str], limit: int = 3000) -> List[dict]:
    ids = list(dict.fromkeys(node_ids))[:1500]
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    try:
        rows = conn.execute(
            f"SELECT source, target, kind FROM edges "
            f"WHERE (source IN ({ph}) OR target IN ({ph})) "
            f"AND kind IN ('calls','contains','extends','imports','references','instantiates') "
            f"LIMIT ?",
            tuple(ids + ids + [int(limit)]),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("[semantic] query edges failed: %s", e)
        return []


# ── 范围解析 ──────────────────────────────────────────────────

def _comm_files(root: str, comm_key: str, project: Optional[str] = None) -> List[str]:
    """组件范围 → 文件集合。

    组件 id 来自组件目录(architecture.catalog，跨 INCLUDE/CALL × L0/L1，即组件列表的
    完整来源)；architecture.model 仅为 INCLUDE·L1/L0 子集视图。以目录为主解析
    (目录 ⊇ 模型)，模型兜底兼容仅模型存在的场景。
    """
    from .common import build_component_catalog, build_architecture_model
    try:
        catalog = build_component_catalog(root, project)
        for c in catalog.get("components") or []:
            if c.get("id") == comm_key:
                files = [_norm_path(f) for f in (c.get("owns") or []) if f]
                logger.info("[semantic] comm %s 命中组件目录, 文件数=%d", comm_key, len(files))
                return files
    except Exception as e:
        logger.warning("[semantic] comm %s 组件目录解析失败: %s", comm_key, e, exc_info=True)
    try:
        model = build_architecture_model(root, project)
        for c in model.get("components") or []:
            if c.get("id") == comm_key:
                files = [_norm_path(f) for f in (c.get("owns") or []) if f]
                logger.info("[semantic] comm %s 命中架构模型, 文件数=%d", comm_key, len(files))
                return files
    except Exception as e:
        logger.warning("[semantic] comm %s 架构模型解析失败: %s", comm_key, e, exc_info=True)
    logger.warning("[semantic] comm %s 组件目录与模型均未命中, 返回空文件集合", comm_key)
    return []


def resolve_scope_files(root: str, scope_type: str, scope_key: str,
                        files: Optional[List[str]] = None,
                        symbols: Optional[List[str]] = None,
                        project: Optional[str] = None):
    """范围 → (files, symbols)。comm 解析为文件集合；symbols 保持符号名列表。"""
    st = scope_type or "project"
    if st == "files":
        return [_norm_path(f) for f in (files or []) if f], []
    if st == "symbols":
        return [], [s for s in (symbols or []) if s]
    if st == "comm":
        return _comm_files(root, scope_key, project), []
    return [], []  # project: 全量


# ── 符号表 / 上下文 ───────────────────────────────────────────

def build_symbol_table(nodes: List[dict]) -> Dict[str, dict]:
    """name/qualified_name → node 的解析表(供 LLM 符号引用→真实 AST 锚点)。"""
    table: Dict[str, dict] = {}
    for n in nodes:
        table.setdefault(n["name"], n)
        if n.get("qualified_name"):
            table.setdefault(n["qualified_name"], n)
            tail = n["qualified_name"].rsplit("::", 1)[-1]
            if tail and tail != n["name"]:
                table.setdefault(tail, n)
    return table


def _symbol_block(nodes: List[dict], limit: int = 220) -> str:
    """符号上下文块(供 LLM)。docstring 截断控制 token。"""
    lines = []
    for n in nodes[:limit]:
        kind = n.get("kind") or ""
        sig = n.get("signature") or ""
        doc = (n.get("docstring") or "").strip().replace("\n", " ")[:160]
        rt = n.get("return_type") or ""
        head = f"- [{kind}] {n['qualified_name'] or n['name']} @ {n['file_path']}:{n['start_line']}-{n['end_line']}"
        if sig:
            head += f" sig=({sig})"
        if rt:
            head += f" -> {rt}"
        if doc:
            head += f" // {doc}"
        lines.append(head)
    return "\n".join(lines) or "(无符号)"


def _edge_lines(edges: List[dict], table: Dict[str, dict]) -> str:
    """调用/包含边(源/目标符号名)，供流程/控制提取。"""
    name_of = {n["id"]: (n["qualified_name"] or n["name"]) for n in table.values()}
    seen, out = set(), []
    for e in edges:
        s = name_of.get(e["source"], e["source"])
        t = name_of.get(e["target"], e["target"])
        key = (e["kind"], s, t)
        if key in seen:
            continue
        seen.add(key)
        out.append(f"- {s} {e['kind']} {t}")
        if len(out) >= 180:
            break
    return "\n".join(out)


def _cross_file_edges_text(conn: sqlite3.Connection, node_ids: List[str],
                           cap: int = 40) -> str:
    """跨文件被调用符号索引：本范围符号在其它文件中调用/引用的目标符号(签名+docstring)。

    供 LLM 描述跨文件流程/契约时引用准确的外部符号，弥补逐文件提取的视野局限。
    """
    ids = list(dict.fromkeys(nid for nid in (node_ids or []) if nid))[:800]
    if not ids:
        return ""
    ph = ",".join("?" * len(ids))
    try:
        rows = conn.execute(
            f"SELECT e.kind AS k, t.qualified_name AS qn, t.name AS nm, "
            f"t.file_path AS f, t.signature AS sig, t.return_type AS rt, t.docstring AS doc "
            f"FROM edges e JOIN nodes t ON t.id = e.target "
            f"WHERE e.source IN ({ph}) AND e.kind IN ('calls','references') "
            f"AND t.file_path IS NOT NULL AND t.kind NOT IN ('file','import') "
            f"LIMIT ?",
            tuple(ids + [cap * 4])).fetchall()
    except Exception as e:
        logger.warning("[semantic] cross-file index failed: %s", e)
        return ""
    lines, seen = [], set()
    for r in rows:
        qn = r["qn"] or r["nm"]
        if not qn or qn in seen:
            continue
        seen.add(qn)
        doc = (r["doc"] or "").strip().replace("\n", " ")[:120]
        head = f"- {qn} @ {r['f']}"
        if r["sig"]:
            head += f" sig=({r['sig']})"
        if r["rt"]:
            head += f" -> {r['rt']}"
        if doc:
            head += f" // {doc}"
        lines.append(head)
        if len(lines) >= cap:
            break
    if not lines:
        return ""
    return "跨文件被调用符号(其它文件，供跨文件流程/契约描述):\n" + "\n".join(lines)


def _norm_cache_symbol(file: str, lang: str, s: dict) -> dict:
    """KB parseFileAst 返回的 camelCase 符号 → 与 codegraph 节点同构(snake_case)。

    透传 return_type/decorators/visibility 等与 codegraph 对齐的字段(缺失置空)，
    保证两条 AST 路径产出的统一符号模型一致(Rule 判定/签名信号不受路径影响)。

    兼容两种输入形状：KB 原始 camelCase(`startLine`/`qualifiedName`) 与
    本函数产出后落库的 snake_case(`start_line`/`qualified_name`)——因为
    `_collect_via_cache` 把归一化后的节点写回 `arch_ast_cache`，读回时再归一化一次。
    """
    name = (s.get("name") or "").strip()
    if not name:
        return None
    kind = s.get("kind") or "symbol"
    # 行号/列号/限定名同时兼容 camelCase 与 snake_case 输入。
    def _g(*keys, default=0):
        for k in keys:
            v = s.get(k)
            if v is not None:
                return v
        return default
    node = {
        "id": s.get("id") or f"cache:{file}::{name}::{int(_g('startLine', 'start_line') or 0)}",
        "kind": kind,
        "name": name,
        "qualified_name": s.get("qualifiedName") or s.get("qualified_name") or name,
        "file_path": file,
        "language": lang,
        "start_line": int(_g('startLine', 'start_line') or 0),
        "end_line": int(_g('endLine', 'end_line') or 0),
        "start_column": int(_g('startCol', 'start_column') or 0),
        "end_column": int(_g('endCol', 'end_column') or 0),
        "signature": s.get("signature") or "",
        "docstring": s.get("docstring") or "",
        "return_type": s.get("return_type") or s.get("returnType") or "",
    }
    if s.get("decorators"):
        node["decorators"] = s.get("decorators")
    if s.get("visibility"):
        node["visibility"] = s.get("visibility")
    return node


_REF_EDGE_KINDS = {"calls", "extends", "imports", "references", "instantiates", "implements"}
_CONTAINER_KINDS = {"class", "interface", "struct", "enum", "component", "trait", "protocol", "namespace"}


def _rebuild_edges_from_refs(symbols: List[dict], refs: List[dict]) -> List[dict]:
    """KB parseFileAst 路径：从文件级 refs 重建统一边(与 codegraph `_query_edges` 同构)。

    refs 为文件级数组 `{name, kind, line, col}`，无 source 符号 id，因此：
      1) 按「符号行区间归属」：ref 行落在某符号 start_line..end_line 内 → 该符号的出边；
      2) 目标解析：能命中符号 id/name/qualified_name → 存 id，否则存符号名(与 `_edge_lines`
         的 name_of 解析兼容)；
      3) contains：由「子符号行区间 ⊂ 父符号行区间」推导(类包含方法/字段)。
    调用方应保证 symbols/refs 属于**同一文件**，避免跨文件行区间误归属。
    返回 [{source, target, kind, line?, col?}]，供两路径统一消费。
    """
    out: List[dict] = []
    if not refs:
        return _contains_edges(out, symbols or [])
    name_to_id: Dict[str, str] = {}
    for n in symbols or []:
        name_to_id.setdefault((n.get("name") or "").strip(), n.get("id") or "")
        if n.get("qualified_name"):
            name_to_id.setdefault((n.get("qualified_name") or "").strip(), n.get("id") or "")
    seen: set = set()

    def _emit(sid: str, tgt: str, kind: str, line: Optional[int], col: Optional[int]) -> None:
        if not sid or not tgt or sid == tgt:
            return
        key = (sid, tgt, kind)
        if key in seen:
            return
        seen.add(key)
        e: Dict[str, Any] = {"source": sid, "target": tgt, "kind": kind}
        if line is not None:
            e["line"] = line
        if col is not None:
            e["col"] = col
        out.append(e)

    for n in symbols or []:
        sid = n.get("id") or ""
        s0 = int(n.get("start_line") or 0)
        s1 = int(n.get("end_line") or 0)
        if not sid or s0 <= 0:
            continue
        for r in refs or []:
            if r.get("kind") not in _REF_EDGE_KINDS:
                continue
            rl = int(r.get("line") or 0)
            if rl < s0 or rl > s1:
                continue
            nm = (r.get("name") or "").strip()
            if not nm:
                continue
            tgt = name_to_id.get(nm, nm)
            _emit(sid, tgt, r.get("kind"), rl, int(r.get("col") or 0))
    return _contains_edges(out, symbols or [], emit=_emit)


def _contains_edges(out: List[dict], symbols: List[dict],
                    emit: Optional[Any] = None) -> List[dict]:
    """contains 推导：最深的父容器包含子符号(子区间 ⊂ 父区间)。

    emit 为 None 时使用独立去重并 append 到 out；否则复用调用方 `_emit`。
    """
    children = [
        n for n in (symbols or [])
        if n.get("id") and (n.get("kind") or "") not in _CONTAINER_KINDS
        and (int(n.get("start_line") or 0) > 0)
    ]
    containers = [
        n for n in (symbols or [])
        if n.get("id") and (n.get("kind") or "") in _CONTAINER_KINDS
        and (int(n.get("start_line") or 0) > 0)
    ]
    seen: set = set()

    def _e(sid: str, tgt: str) -> None:
        key = (sid, tgt, "contains")
        if key in seen:
            return
        seen.add(key)
        if emit is not None:
            ch = next((c for c in children if c.get("id") == tgt), None)
            emit(sid, tgt, "contains", int(ch.get("start_line") or 0) if ch else None, None)
        else:
            out.append({"source": sid, "target": tgt, "kind": "contains"})

    for ch in children:
        cs0 = int(ch.get("start_line") or 0)
        cs1 = int(ch.get("end_line") or 0)
        best = None
        for p in containers:
            ps0 = int(p.get("start_line") or 0)
            ps1 = int(p.get("end_line") or 0)
            # 区间严格真包含(子区间 ⊂ 父区间)，排除相同区间(避免容器视为含自身)。
            if ps0 <= cs0 and ps1 >= cs1 and not (ps0 == cs0 and ps1 == cs1):
                if best is None or (ps1 - ps0) < (int(best.get("end_line") or 0) - int(best.get("start_line") or 0)):
                    best = p
        if best:
            _e(best.get("id") or "", ch.get("id") or "")
    return out


def _collect_via_cache(root: str, project: Optional[str],
                       files: List[str], syms: List[str]):
    """无 codegraph 时的 AST 缓存层取数(要求③)：缓存命中 → KB 解析 → live 扫描。

    返回 (nodes, edges, source)。KB 路径经 `_rebuild_edges_from_refs` 从文件级 refs
    重建统一边(与 codegraph `_query_edges` 同构)，保证下游(Rule 判定/流程/字段)效果一致。
    """
    pid = project_id_for(root, project)
    nodes: List[dict] = []
    # 每文件符号/refs 分组，供重建边(行区间归属必须限定单文件，防跨文件误归)。
    per_file: Dict[str, dict] = {}
    source = "live"
    if syms:
        # 符号范围无 codegraph 无法精确定位文件 → 退化为 live 全量扫描(有文件列表时)
        if files:
            nodes = _scan_live(root, files, syms)
        return nodes, [], source
    miss: List[str] = []
    for rel in (files or [])[:120]:
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            logger.info("[semantic] cache 文件不存在, 跳过: %s", rel)
            continue
        h = _file_md5(root, rel)
        pf: dict = {"symbols": [], "refs": []}
        cached = store.AstCacheStore.get(pid, rel)
        if cached and cached.get("contentHash") and cached.get("contentHash") == h:
            if cached.get("source") in ("codegraph", "kb"):
                source = cached.get("source")
            for s in cached.get("symbols") or []:
                n = _norm_cache_symbol(rel, cached.get("language") or "", s)
                if n:
                    nodes.append(n)
                    pf["symbols"].append(n)
            pf["refs"] = cached.get("refs") or []
            per_file[rel] = pf
            continue
        miss.append(rel)
        # 缓存未命中/已过期 → KB 只读解析(不落 KB，写入 architect 缓存)
        kb = _kb_parse_file(root, rel)
        if kb and kb.get("symbols"):
            source = "kb"
            src = None
            for s in kb["symbols"]:
                n = _norm_cache_symbol(rel, kb.get("language") or "", s)
                if not n:
                    continue
                if not n.get("docstring"):
                    # KB tree-sitter 只识别注释式 docstring，漏掉 Python """..."""。
                    # 用轻量源码回读补全(仅 KB 兜底路径)。
                    if src is None:
                        try:
                            with open(full, "r", encoding="utf-8", errors="replace") as _fh:
                                src = _fh.read()
                        except Exception:
                            src = ""
                    n["docstring"] = _peek_docstring_at_line(src, n["start_line"])
                nodes.append(n)
                pf["symbols"].append(n)
            pf["refs"] = kb.get("refs") or []
            per_file[rel] = pf
            store.AstCacheStore.upsert(pid, rel, {
                "contentHash": h, "language": kb.get("language") or "",
                "symbols": nodes[-len(kb["symbols"]):],
                "imports": kb.get("imports") or [],
                "refs": kb.get("refs") or [],
                "source": "kb",
            })
        else:
            # KB 不可达/不支持 → live 扫描(仅本文件)
            for n in _scan_live(root, [rel], []):
                nodes.append(n)
    edges: List[dict] = []
    for pf in per_file.values():
        edges += _rebuild_edges_from_refs(pf["symbols"], pf["refs"])
    logger.info("[semantic] cache 兜底: 文件数=%d 缓存未命中=%s source=%s 共取节点=%d 边=%d",
                len(files or []), miss or "-", source, len(nodes), len(edges))
    return nodes, edges, source


def _kb_parse_file(root: str, rel: str) -> Optional[dict]:
    """经 KbGateway 调 KB 只读 analysis.parseFileAst(内容不落 KB)。"""
    full = os.path.join(root, rel.replace("/", os.sep))
    try:
        from .kb_gateway import call_kb
        res = call_kb("analysis.parseFileAst", filePath=full, file_path=full)
        if isinstance(res, dict) and res.get("symbols") is not None:
            return res
        return None
    except Exception as e:
        logger.warning("[semantic] kb parseFileAst %s failed: %s", rel, e)
        return None


def collect_context(root: str, scope_type: str, scope_key: str,
                    files: Optional[List[str]] = None,
                    symbols: Optional[List[str]] = None,
                    project: Optional[str] = None) -> Dict[str, Any]:
    """收集范围符号上下文。返回 {files, symbols, nodes, table, edges, text, srcHash, source}。

    取数四层(要求③): 缓存命中 → codegraph → KB parseFileAst → live 扫描。
    """
    files, syms = resolve_scope_files(root, scope_type, scope_key, files, symbols, project)
    logger.info("[semantic] collect_context 范围 %s(%s): files=%d symbols=%d",
                scope_type, scope_key or "-", len(files), len(syms))
    # 组件范围未解析到任何文件(组件目录/模型均未命中) → 直接空上下文，避免退化为全项目扫描。
    if scope_type == "comm" and not files and not syms:
        logger.warning("[semantic] collect_context comm(%s) 未解析到文件, 返回空上下文", scope_key or "-")
        return {"root": root, "files": [], "symbols": [], "nodes": [], "table": {},
                "edges": [], "text": "", "srcHash": "", "source": "none"}
    source = "live"
    conn = _open_cg(root)
    cross = ""
    if conn is not None:
        source = "codegraph"
        nodes = _query_nodes(conn, files=files, symbols=syms)
        edges = _query_edges(conn, [n["id"] for n in nodes]) if nodes else []
        cross = _cross_file_edges_text(conn, [n["id"] for n in nodes])
        conn.close()
    else:
        # 无 codegraph → AST 缓存层(KB 解析优先，live 扫描兜底)
        nodes, edges, source = _collect_via_cache(root, project, files, syms)
    logger.info("[semantic] collect_context source=%s nodes=%d edges=%d",
                source, len(nodes), len(edges))
    table = build_symbol_table(nodes)
    cross_suffix = ("\n" + cross) if cross else ""
    text = (
        f"文件集合({len(files)} 个): {', '.join(files[:40]) or '(全量)'}\n"
        f"符号清单:\n{_symbol_block(nodes)}\n"
        f"关系边:\n{_edge_lines(edges, table) or '(无)'}"
        f"{cross_suffix}"
    )
    src_hash = hashlib.md5(json.dumps(
        [{"f": n["file_path"], "n": n["name"], "k": n["kind"],
          "s": n["start_line"], "e": n["end_line"], "sig": n.get("signature")}
         for n in nodes], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return {"root": root, "project": project, "files": files, "symbols": syms, "nodes": nodes, "table": table,
            "edges": edges, "text": text, "srcHash": src_hash, "source": source}


def _scan_live(root: str, files: Optional[List[str]],
               symbols: Optional[List[str]]) -> List[dict]:
    """轻量降级收集: 无 codegraph 索引时扫描源码(类/函数/方法行号粗定位)。"""
    if not root or not os.path.isdir(root):
        return []
    rel_files = files or []
    out: List[dict] = []
    for rel in rel_files[:120]:
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except Exception:
            continue
        for m in re.finditer(r"^\s*(?:export\s+)?(?:class|interface|enum|struct)\s+(\w+)", src, re.M):
            line = src[:m.start()].count("\n") + 1
            out.append({"id": f"live-{len(out)}", "kind": "class", "name": m.group(1),
                        "qualified_name": m.group(1), "file_path": rel,
                        "start_line": line, "end_line": line,
                        "start_column": 0, "end_column": 0,
                        "signature": "", "docstring": _peek_docstring(src, m.end()),
                        "return_type": ""})
        for m in re.finditer(r"^\s*(?:def|function|async def|async function)\s+(\w+)", src, re.M):
            line = src[:m.start()].count("\n") + 1
            out.append({"id": f"live-{len(out)}", "kind": "function", "name": m.group(1),
                        "qualified_name": m.group(1), "file_path": rel,
                        "start_line": line, "end_line": line,
                        "start_column": 0, "end_column": 0,
                        "signature": "", "docstring": _peek_docstring(src, m.end()),
                        "return_type": ""})
        if len(out) >= 260:
            break
    return out


def _peek_docstring(src: str, pos: int, max_lines: int = 4) -> str:
    """粗略抓取声明后的第一个引号字符串(作为启发式 docstring)。"""
    tail = src[pos:pos + 1200]
    lines = tail.split("\n")[:max_lines]
    for ln in lines:
        s = ln.strip()
        m = re.match(r'^([""\'\']{3}|["\'])(.*?)\1', s)
        if m and m.group(2).strip():
            return m.group(2).strip()
    return ""


def _peek_docstring_at_line(src: str, line_no: int, max_lines: int = 4) -> str:
    """按起始行号抓取声明后的引号字符串(供 KB 兜底路径补全 docstring)。"""
    if not src or line_no <= 0:
        return ""
    pos = 0
    for _ in range(line_no - 1):
        pos = src.find("\n", pos)
        if pos < 0:
            return ""
        pos += 1
    return _peek_docstring(src, pos, max_lines)


# ── AST 解析: LLM 符号引用 → 真实节点 ─────────────────────────

def resolve_ast_refs(symbols_in: Optional[List[str]], table: Dict[str, dict],
                     llm_refs: Optional[List[dict]] = None) -> List[dict]:
    """把符号引用解析为 AstNodeRef 列表(去重；优先真实节点行号)。"""
    refs: Dict[str, dict] = {}
    keys = set(symbols_in or [])
    for s in keys:
        node = table.get(s)
        if not node:
            continue
        refs[s] = _node_to_ref(node)
    for r in (llm_refs or []):
        if not isinstance(r, dict):
            continue
        file = _norm_path(r.get("file") or "")
        symbol = (r.get("symbol") or "").strip()
        if not symbol or not file:
            continue
        node = table.get(symbol)
        if node and node["file_path"] == file:
            refs[symbol] = _node_to_ref(node)
        elif symbol in refs:
            continue
        else:
            refs[symbol] = {"file": file, "symbol": symbol,
                            "kind": r.get("kind") or "func",
                            "startLine": int(r.get("startLine") or 0),
                            "endLine": int(r.get("endLine") or 0)}
    return list(refs.values())


def _node_to_ref(n: dict) -> dict:
    return {
        "file": n["file_path"],
        "symbol": n["qualified_name"] or n["name"],
        "kind": _AST_KIND_MAP.get(n.get("kind"), "func"),
        "startLine": int(n.get("start_line") or 0),
        "endLine": int(n.get("end_line") or 0),
    }


def _symbol_tail(sym: str) -> str:
    """提取符号尾段(处理 file::sym / Class::method / obj.method 形式)。"""
    s = (sym or "").strip()
    for sep in ("::", "."):
        if sep in s:
            s = s.split(sep)[-1]
    return s


def _node_index(table: Dict[str, dict]) -> Dict[str, list]:
    """节点表 → (尾段符号名, 归一化文件) → 节点列表 索引(宽容锚点解析用)。"""
    idx: Dict[str, list] = {}
    for node in table.values():
        key = _symbol_tail(node.get("qualified_name") or node.get("name") or "")
        f = _norm_path(node.get("file_path") or "")
        if key:
            idx.setdefault(key, []).append(node)
        if f:
            idx.setdefault(f"@{f}", []).append(node)
    return idx


def _resolve_symbol_node(sym: str, file: str, line: int,
                         table: Dict[str, dict],
                         idx: Optional[Dict[str, list]] = None) -> Optional[dict]:
    """宽容符号→AST 节点解析(供 LLM 锚点/启发式兜底)。

    命中策略(依次):
      1) table 精确匹配(原有行为)；
      2) 尾段符号名匹配(Class::method / obj.method → method)；
      3) 行号回退: 在指定文件内找 start_line<=line<=end_line 或最近的节点，
         优先函数/方法/路由(路由字符串 GET:/path 的 startLine 指向装饰器行时，
         取其后的函数定义节点)。
    """
    if sym:
        node = table.get(sym)
        if node:
            return node
        tail = _symbol_tail(sym)
        if tail and tail != sym:
            node = table.get(tail)
            if node:
                return node
        if idx and tail:
            for n in idx.get(tail, []):
                f = _norm_path(n.get("file_path") or "")
                if f and file and _norm_path(file) == f:
                    return n
            if len(idx.get(tail, [])) == 1:
                return idx[tail][0]
    # 行号回退: 同文件内找覆盖/最近的函数/方法/路由节点
    if file and idx:
        fnodes = sorted(
            (n for n in idx.get(f"@{_norm_path(file)}", [])
             if n.get("kind") in ("function", "method", "route")),
            key=lambda n: int(n.get("start_line") or 0),
        )
        if line > 0 and fnodes:
            # 装饰器行(@router.get)落在函数定义之前: 取 start_line>=line 的第一个
            nxt = next((n for n in fnodes if int(n.get("start_line") or 0) >= line), None)
            if nxt:
                return nxt
            for n in reversed(fnodes):
                if int(n.get("start_line") or 0) <= line:
                    return n
        elif fnodes:
            return fnodes[0]
    return None


def _attach_step_refs(detail: dict, table: Dict[str, dict]) -> None:
    """把步骤/分支里的 symbols[] 解析进对应 astRefs。"""
    for i, s in enumerate(detail.get("steps") or []):
        if isinstance(s, dict):
            s["astRefs"] = resolve_ast_refs(s.get("symbols"), table)
    for i, b in enumerate(detail.get("branches") or []):
        if isinstance(b, dict):
            b["astRefs"] = resolve_ast_refs(b.get("symbols"), table)


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


def _flat_str(v: Any) -> str:
    """then/else 等字段可能是 str / list / dict → 扁平化为字符串。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (list, tuple)):
        parts = []
        for x in v:
            if isinstance(x, str):
                parts.append(x.strip())
            elif isinstance(x, dict):
                parts.append(str(x.get("action") or x.get("semantic") or "").strip() or json.dumps(x, ensure_ascii=False))
            else:
                parts.append(str(x))
        return "；".join(p for p in parts if p)
    if isinstance(v, dict):
        return str(v.get("action") or v.get("semantic") or "").strip() or json.dumps(v, ensure_ascii=False)
    return str(v)


def _norm_llm_asset(a: dict, table: Dict[str, dict]) -> Optional[dict]:
    """把 LLM 返回的资产归一化为内部规范结构。

    LLM(尤其本地中文模型)常输出 `type` 而非 `kind`、`steps.symbol` 单数而非
    `symbols` 列表、`source_symbols`/`anchor_symbol` 作锚点。此处做宽容归一化：
      - type → kind(含中文/驼峰变体)
      - steps: {step,symbol,action} → {order,semantic,symbols[]}
      - branches: {condition,then,else,result_symbol} → {condition,then,else,semantic,symbols[]}
      - relations: {from,to,via} → {target,type,semantic}
      - states: {state,description} → {name,desc,initial,final}
      - transitions: {source,target,event,guard} → {from,to,event,condition,action}
      - 锚点: source_symbols[] + anchor_symbol → astRefs(可解析则真实节点，否则记录警告)
    无法归一化(缺 kind/name)返回 None。
    """
    if not isinstance(a, dict):
        return None
    kind = _normalize_kind(a.get("kind") or a.get("type"))
    name = (a.get("name") or "").strip()
    if not kind or not name:
        return None
    level = _normalize_level(a.get("level")) or "logic"
    detail: Dict[str, Any] = {}
    if isinstance(a.get("fields"), list):
        detail["fields"] = a["fields"]
    rels = []
    for r in a.get("relations") or []:
        if not isinstance(r, dict):
            continue
        rels.append({
            "target": (r.get("target") or r.get("to") or "").strip(),
            "type": (r.get("type") or r.get("via") or "").strip(),
            "semantic": (r.get("semantic") or "").strip(),
        })
    if rels:
        detail["relations"] = rels
    if isinstance(a.get("invariants"), list):
        detail["invariants"] = [str(x) for x in a["invariants"]]
    if a.get("trigger"):
        detail["trigger"] = str(a["trigger"])
    if isinstance(a.get("steps"), list):
        steps = []
        for s in a["steps"]:
            if not isinstance(s, dict):
                continue
            syms = s.get("symbols")
            if not isinstance(syms, list):
                syms = [s.get("symbol")] if s.get("symbol") else []
            steps.append({
                "order": s.get("order") if s.get("order") is not None else s.get("step"),
                "semantic": (s.get("semantic") or s.get("action") or "").strip(),
                "condition": (s.get("condition") or "").strip(),
                "symbols": [x for x in syms if x],
            })
        detail["steps"] = steps
    if isinstance(a.get("branches"), list):
        branches = []
        for b in a["branches"]:
            if not isinstance(b, dict):
                continue
            syms = b.get("symbols")
            if not isinstance(syms, list):
                syms = [b.get("symbol")] if b.get("symbol") else []
            branches.append({
                "condition": (b.get("condition") or "").strip(),
                "then": _flat_str(b.get("then")),
                "else": _flat_str(b.get("else")),
                "semantic": (b.get("semantic") or b.get("result_symbol") or "").strip(),
                "symbols": [x for x in syms if x],
            })
        detail["branches"] = branches
    if isinstance(a.get("states"), list):
        states = []
        for st in a["states"]:
            if isinstance(st, str) and st.strip():
                states.append({"name": st.strip(), "desc": "", "initial": False, "final": False})
            elif isinstance(st, dict) and (st.get("name") or "").strip():
                states.append({
                    "name": (st.get("name") or "").strip(),
                    "desc": (st.get("desc") or "").strip(),
                    "initial": bool(st.get("initial")),
                    "final": bool(st.get("final")),
                })
        if states:
            detail["states"] = states
    if isinstance(a.get("transitions"), list):
        transitions = []
        for tr in a["transitions"]:
            if isinstance(tr, dict) and (tr.get("from") or tr.get("to")):
                transitions.append({
                    "from": (tr.get("from") or tr.get("source") or "").strip(),
                    "to": (tr.get("to") or tr.get("target") or "").strip(),
                    "event": (tr.get("event") or "").strip(),
                    "condition": (tr.get("condition") or tr.get("guard") or "").strip(),
                    "action": (tr.get("action") or "").strip(),
                })
        if transitions:
            detail["transitions"] = transitions
    if isinstance(a.get("tags"), list):
        tags = [str(x).strip() for x in a["tags"] if str(x).strip()]
        if tags:
            detail["tags"] = tags
    # H 级聚合：aggress 字段 → detail.aggregates(子资产组合链)。
    agg = a.get("aggregates")
    if isinstance(agg, list):
        agg_norm = []
        for x in agg:
            if isinstance(x, str) and x.strip():
                agg_norm.append({"assetId": x.strip()})
            elif isinstance(x, dict) and x.get("assetId"):
                agg_norm.append({"assetId": str(x.get("assetId")),
                                 "name": (x.get("name") or "").strip(),
                                 "role": (x.get("role") or "").strip()})
        if agg_norm:
            detail["aggregates"] = agg_norm

    # 锚点：source_symbols[] + anchor_symbol → astRefs
    # 宽容解析：LLM 常输出 file::GET:/path / Class::method 等形式，需解析到真实 AST 节点。
    node_idx = _node_index(table)
    ast_refs: List[dict] = []
    src_syms = a.get("source_symbols") or []
    if not isinstance(src_syms, list):
        src_syms = [src_syms] if isinstance(src_syms, str) else []
    for sym in src_syms:
        if not sym:
            continue
        sym_s = str(sym).strip()
        _f, _, _s = sym_s.partition("::")
        file_hint = (_f or "").strip()
        node = _resolve_symbol_node(_s or sym_s, file_hint, 0, table, node_idx)
        if node:
            ast_refs.append(_node_to_ref(node))
        else:
            logger.warning("[semantic] LLM 资产符号无法解析(锚点忽略): %s", sym_s)
    anchor = a.get("anchor_symbol") or a.get("anchor") or ""
    if anchor:
        _file, _, _sym = str(anchor).partition("::")
        _file = (_file or "").strip()
        _sym = (_sym or "").strip()
        line = int(a.get("anchor_line") or 0)
        node = _resolve_symbol_node(_sym, _file, line, table, node_idx)
        if node:
            ast_refs.append(_node_to_ref(node))
        else:
            logger.warning("[semantic] LLM 资产锚点符号无法解析(忽略): %s", anchor)
    ast_refs = list({json.dumps(r, ensure_ascii=False, sort_keys=True): r for r in ast_refs}.values())

    return {"kind": kind, "level": level, "name": name, "desc": (a.get("desc") or "").strip(),
            "detail": detail, "astRefs": ast_refs}


def _normalize_llm_assets(output: dict, level: str, table: Dict[str, dict],
                          max_assets: int) -> Tuple[List[dict], int]:
    """LLM 输出 → 归一化资产列表。返回 (valid, dropped)。"""
    assets = output.get("assets") or []
    valid: List[dict] = []
    dropped = 0
    for a in assets:
        norm = _norm_llm_asset(a, table)
        if norm:
            # 请求粒度权威：一次提取只产出一级，避免 LLM 混级(否则按粒度展示会不稳定)。
            norm["level"] = level
            valid.append(norm)
        else:
            dropped += 1
        if len(valid) >= max_assets:
            break
    # 空锚点兜底：LLM 未给出可解析的 source_symbols/anchor_symbol 时，
    # 从 name/desc 反查符号表补真实 AST 锚点(保证资产可定位到源码)。
    if table:
        _backfill_anchors(valid, table)
    # 类别-锚点一致性后置校验：kind 与锚点节点类别冲突的资产丢弃(仅实现层)。
    # entity 锚到函数、contract 锚到变量等 —— LLM 常见误标，此处确定性纠正。
    if level == "implementation":
        valid = [a for a in valid if _asset_anchor_kind_ok(a.get("kind") or "", a.get("astRefs") or [])]
    return valid, dropped


def _backfill_anchors(valid: List[dict], table: Dict[str, dict]) -> None:
    """为无 astRefs 的资产补启发式锚点。

    候选符号来源(依次)：
      1) name/desc 中的反引号符号 `sym`(含 file::sym)；
      2) detail.relations[].target(关系目标常为同文件真实符号名)；
      3) steps/branches 中的 symbols[]。
    在符号表中反查真实节点。找不到明确符号时**不补**(宁缺毋滥，避免锚到无关节点)——
    跨文件引用(如 infra 资产描述中提到的其它模块函数)不在此表内，属正常。
    """
    idx = _node_index(table)
    import re as _re
    token_re = _re.compile(r"`([A-Za-z_][\w.:]*)`")
    for a in valid:
        if a.get("astRefs"):
            continue
        detail = a.get("detail") or {}
        candidates: List[str] = []
        text = f"{a.get('name') or ''} {a.get('desc') or ''}"
        candidates += [m.group(1) for m in token_re.finditer(text)]
        for r in (detail.get("relations") or []):
            if isinstance(r, dict) and (r.get("target") or "").strip():
                candidates.append(str(r["target"]).strip())
        for s in (detail.get("steps") or []):
            if isinstance(s, dict) and s.get("symbols"):
                candidates += [str(x) for x in s["symbols"] if x]
        for b in (detail.get("branches") or []):
            if isinstance(b, dict) and b.get("symbols"):
                candidates += [str(x) for x in b["symbols"] if x]
        found: Optional[dict] = None
        seen: set = set()
        for tok in candidates:
            tok = tok.strip()
            if not tok or tok in seen:
                continue
            seen.add(tok)
            _f, _, _s = tok.partition("::")
            node = _resolve_symbol_node(_s or tok, (_f or "").strip(), 0, table, idx)
            if node:
                found = node
                break
        if found:
            a["astRefs"] = [_node_to_ref(found)]


def _llm_asset_detail_ok(a: dict) -> bool:
    """资产 detail 是否满足类别完整性要求：process 需 steps 或 trigger；decision 需 branches；
    state 需 states+transitions。

    schema 中 steps/branches 均为可选，模型预算紧张时常跳过 → 产出「业务命名但空 detail」
    的资产，污染活动图/状态图(直线流程)。此处做类别强制校验，防止空 detail 落库。
    """
    kind = a.get("kind") or ""
    detail = a.get("detail") or {}
    if not isinstance(detail, dict):
        return False
    if kind == "process":
        steps = detail.get("steps")
        if isinstance(steps, list) and steps:
            return True
        return bool((detail.get("trigger") or "").strip())
    if kind == "decision":
        branches = detail.get("branches")
        return isinstance(branches, list) and bool(branches)
    if kind == "state":
        states = detail.get("states")
        transitions = detail.get("transitions")
        return isinstance(states, list) and bool(states) \
            and isinstance(transitions, list) and bool(transitions)
    return True


def _detail_retry_hint(incomplete: List[dict]) -> str:
    """针对缺 detail 资产的定向补全提示(回喂给模型)。"""
    lines = ["以下资产未按要求填写 detail，请仅针对这些资产重新输出修正后的完整资产列表："]
    for a in incomplete:
        kind = a.get("kind") or ""
        name = a.get("name") or ""
        detail = a.get("detail") or {}
        missing = []
        if kind == "process" and not (isinstance(detail.get("steps"), list) and detail.get("steps")) \
                and not (detail.get("trigger") or "").strip():
            missing.append("steps(按执行顺序逐条，含 semantic/symbols；有分支时在 condition 字段写前置判定条件)")
        if kind == "decision" and not (isinstance(detail.get("branches"), list) and detail.get("branches")):
            missing.append("branches(condition/then/else 逐条，condition 不得留空)")
        if kind == "state":
            if not (isinstance(detail.get("states"), list) and detail.get("states")):
                missing.append("states(状态集合，标注 initial/final)")
            if not (isinstance(detail.get("transitions"), list) and detail.get("transitions")):
                missing.append("transitions(迁移 from/to/event/condition)")
        lines.append(f"- [{kind}] {name}: 缺少 {', '.join(missing)}")
    lines.append("重新输出完整 JSON 对象 {\"assets\": [...]}，包含全部资产(不要省略已完整的资产)，"
                 "不要 Markdown 代码块。")
    return "\n".join(lines)


_ASSET_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["assets"],
    "properties": {
        "assets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "level", "name", "desc"],
                "properties": {
                    "kind": {"type": "string", "enum": list(SEMANTIC_KINDS)},
                    "level": {"type": "string", "enum": list(SEMANTIC_LEVELS)},
                    "name": {"type": "string", "description": "语义化名称(业务命名, 非符号名)"},
                    "desc": {"type": "string", "description": "语义描述(逻辑层级, 比伪代码更概括)"},
                    "source_symbols": {"type": "array", "items": {"type": "string"},
                                       "description": "锚定本资产的清单符号名列表(必须来自符号清单，用于定位真实代码)"},
                    "anchor_symbol": {"type": "string",
                                      "description": "主要锚定符号(可选，格式: 符号名 或 文件::符号名)"},
                    "fields": {"type": "array", "items": {"type": "object",
                                 "properties": {"name": {"type": "string"}, "type": {"type": "string"},
                                                "semantic": {"type": "string"}}}},
                    "relations": {"type": "array", "items": {"type": "object",
                                  "properties": {"target": {"type": "string",
                                                             "description": "关联目标: 其它资产业务名或清单中符号名"},
                                                 "type": {"type": "string",
                                                          "description": "关系类型: calls/contains/extends/implements/1:N/读写 等"},
                                                 "semantic": {"type": "string",
                                                              "description": "关系语义一句话说明"}}}},
                    "invariants": {"type": "array", "items": {"type": "string"}},
                    "trigger": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "object",
                              "properties": {"order": {"type": "integer"}, "semantic": {"type": "string"},
                                             "condition": {"type": "string",
                                                           "description": "该步骤的前置判断条件(有分支时必填，如「验证码有效」)"},
                                             "symbols": {"type": "array", "items": {"type": "string"}}}}},
                     "branches": {"type": "array", "items": {"type": "object",
                                 "properties": {"condition": {"type": "string"}, "then": {"type": "string"},
                                                "else": {"type": "string"}, "semantic": {"type": "string"},
                                                "symbols": {"type": "array", "items": {"type": "string"}}}}},
                     "states": {"type": "array", "items": {"type": "object",
                                "properties": {"name": {"type": "string"},
                                               "desc": {"type": "string"},
                                               "initial": {"type": "boolean", "description": "是否初始状态"},
                                               "final": {"type": "boolean", "description": "是否终态"}}},
                                "description": "state 类别: 状态集合(实体生命周期状态)"},
                     "transitions": {"type": "array", "items": {"type": "object",
                                     "properties": {"from": {"type": "string"},
                                                    "to": {"type": "string"},
                                                    "event": {"type": "string", "description": "触发事件"},
                                                    "condition": {"type": "string", "description": "迁移守卫条件"},
                                                    "action": {"type": "string"}}},
                                     "description": "state 类别: 允许的状态迁移(事件驱动)"},
                     "aggregates": {"type": "array", "items": {"type": "object",
                                    "properties": {"assetId": {"type": "string"}, "name": {"type": "string"},
                                                   "role": {"type": "string"}}}},
                     "tags": {"type": "array", "items": {"type": "string"},
                              "description": "横向切面标签(可多选): transactional/caching/security/observability/async/middleware/resilience 等"},
                 },
            },
        }
    },
}

_SYSTEM_PROMPT = (
    "你是代码语义化建模专家。基于给定的最新代码符号清单(文件/符号/行号/签名/docstring/关系边)，"
    "提取语义化的数据资产。\n"
    "语义资产按「类别轴(静态·定义 / 动态·处理) × 粒度轴(业务 / 逻辑 / 实现)」二维分类，"
    "并用 tags 标注横向切面。\n"
    "类别 kind(值只能是 entity / contract / state / rule / process / decision，禁止翻译成中文):\n"
    "  - entity   : 实体(静态) —— 数据对象、领域实体：字段/类型/关系(1:N/FK)/不变式\n"
    "  - contract : 契约(静态) —— 交换的形状：接口签名、API 端点、消息/事件 schema\n"
    "  - state    : 状态(静态) —— 生命周期定义：状态集合 + 允许迁移(仅定义面)\n"
    "  - rule     : 规则(静态，条件性) —— 配置化的约束/策略/阈值定义(仅当存在真实配置拆分时产出)\n"
    "  - process  : 过程(动态) —— 输入→有序步骤→输出：trigger + inputs/steps/outputs\n"
    "  - decision : 决策(动态) —— 运行时分支：condition→then/else(无配置化拆分的规则归此类)\n"
    "规则(重要): 规则 vs 决策 —— 硬编码在代码里的 if/分支是 decision(动态)；"
    "只有存在真实配置拆分(配置表/阈值存储/策略文件/env)时，配置侧才是 rule(静态)，执行侧仍是 decision/process。\n"
    "tags(横向切面，可多选，按代码特征自动打标):\n"
    "  - transactional 事务性(commit/rollback/atomic/事务装饰器)\n"
    "  - caching 缓存(redis/@lru_cache/cachetools)\n"
    "  - security 安全鉴权(auth/login/jwt/token/permission)\n"
    "  - observability 可观测性(logger/trace/metrics)\n"
    "  - async 并发异步(async def/await/thread/semaphore/pool)\n"
    "  - middleware 中间件(middleware/hook/interceptor)\n"
    "  - resilience 限流重试(rate_limit/retry/backoff)\n"
    "粒度 level(越低越贴近代码实现；值只能是 business / logic / implementation):\n"
    "  - business       : 业务级 —— 组件下的业务功能模块/共性目标(如「订单创建与支付结算」「用户统一认证」)，"
    "    聚合多条逻辑(detail 用 aggregates 列出组成资产)，回答「业务上是什么」；"
    "    一个叶子组件通常对应 1~2 个业务资产(允许跨一级同源组件的共性特征)\n"
    "  - logic          : 逻辑级 —— 伪码之上的概括简化：模块职责、用例/流程、决策表(谁负责 Who)；"
    "    锚定符号集合\n"
    "  - implementation : 实现级 —— 代码事实层，贴近伪码：具体计算、调用序、分支条件(具体步骤 How)；"
    "    锚定单符号或连续同类 AST\n"
    "约束(重要):\n"
    "1. 只输出 JSON 对象 {\"assets\": [...]}，不要 Markdown 代码块、不要解释。\n"
    "2. 每个资产必须真实来源于清单中的符号; steps/branches 的 symbols 必须是清单中的符号名，不得臆造。\n"
    "3. name 用业务语义命名(如「支付结算聚合」「鉴权校验链」)，不是符号名。\n"
    "4. desc 概括其逻辑作用与边界，比伪代码抽象。\n"
    "5. 建议提取 2~6 个资产；无匹配数据时返回空数组。\n"
    "6. 每个资产建议填写 source_symbols(清单中真实符号名数组)或 anchor_symbol(主要符号名)，"
    "帮助定位其真实代码位置。\n"
    "7. 高(business)粒度资产应聚合多个逻辑单元并填写 aggregates 字段，避免与 logic 资产重复表述。\n"
    "8. relations 用于表达资产之间的依赖/关联，强烈建议为每个资产填写(可空) 1~3 条："
    "target 填**其它资产业务名**或清单中的符号名(如「支付结算聚合」依赖「订单实体」、"
    "「鉴权校验链」被「下单流程」调用)，type 填关系类型(calls/uses/reads/writes/contains/"
    "extends/references/constrains/sends/triggers/1:N 等)，semantic 一句话说明关系含义。"
    "relations 是图谱连边的数据来源，务必填写。"
)


def _llm_extract(root: Optional[str], project: Optional[str],
                 context_text: str, model_id: Optional[str],
                 table: Optional[Dict[str, dict]] = None,
                 max_assets: int = 6,
                 level: str = "logic") -> List[dict]:
    """LLM 结构化提取。LLM 不可用/解析失败返回空列表(调用方启发式兜底)。

    LLM 输出经 `_norm_llm_asset` 宽容归一化(兼容 type/kind、单复数字段、中文变体)。
    level: 请求粒度(logic 默认)；提示词据此要求产出对应抽象层的资产。
    """
    from .req_agent import llm_sync
    table = table or {}
    sys_prompt = _SYSTEM_PROMPT
    if level == "implementation":
        sys_prompt = _SYSTEM_PROMPT + (
            "\n\n本批只提取 implementation 实现/代码事实层资产：名称贴近符号(如 `Order.calcTotal`)，"
            "锚定清单中的真实符号。detail 必须逐条完整填写：\n"
            "  - entity → fields(列出该类型/结构体的字段 name/type)\n"
            "  - process → steps(按真实调用顺序，每步 symbols 填被调符号名；"
            "若步骤前存在 if/分支判定，在 condition 字段写判定条件原文)\n"
            "  - decision → branches(逐条列出分支 condition 尽量按代码原文 + then/else，condition 不得留空)\n"
            "  - contract → relations(签名/消息约定)\n"
            "  - state → states(状态集合) + transitions(迁移 from/to/event/condition)\n"
            "  - rule → 仅当存在真实配置拆分(配置表/阈值存储/常量字典如 `_DEFAULT_*`/env)时才产出；"
            "detail 记录 configSource/约束/阈值。硬编码分支不是 rule。\n"
            "类别-锚点对应(重要):\n"
            "  - entity 只能锚 class/struct/enum/interface 类型节点；禁止把函数当实体。\n"
            "  - contract 只能锚 route 节点或 api_*/handle_* 路由处理函数；禁止把内部函数"
            "(get_config/send_sms_code 等)当契约。\n"
            "  - state 只能锚 enum 枚举。\n"
            "  - 每个符号只产一个资产(选最合适类别)，禁止同一函数同时输出 process+contract+decision。\n"
            "不得输出 business/logic 级归纳，不得臆造清单中不存在的符号。"
        )
    elif level == "business":
        sys_prompt = _SYSTEM_PROMPT + (
            "\n\n本批只提取 business 业务级资产：组件下的业务功能模块/共性目标(如「订单创建与支付结算」「用户统一认证」)，"
            "聚合多个逻辑/实现级资产，detail 用 aggregates 列出组成资产。不要输出 logic/implementation 级细节。"
        )
    elif level == "logic":
        sys_prompt = _SYSTEM_PROMPT + (
            "\n\n本批只提取 logic 逻辑级资产：伪码之上的概括简化(模块职责/用例/流程/决策表)。"
            "detail 必须按类别完整填写，不得留空：\n"
            "  - entity → fields(名称/类型/语义) + relations + invariants\n"
            "  - process → trigger + inputs/outputs(端点引用其它资产或符号) + steps(按执行顺序，"
            "每步 semantic + symbols；存在分支时在 condition 字段写前置判定条件) + invariants\n"
            "  - decision → branches(condition/then/else 逐条，condition 不得留空) + inputs + invariants\n"
            "  - contract → relations(端点/事件/消息，target 用符号名或其它资产业务名)\n"
            "  - state → states(状态集合，标注 initial/final) + transitions(from/to/event/condition)\n"
            "  - rule → 仅当存在真实配置拆分时才产出；否则相关逻辑归 decision/process。\n"
            "不要输出 business/implementation 级资产。"
        )
    logger.info("[semantic] llm 提取: model=%s level=%s text_len=%d",
                model_id or "(默认)", level, len(context_text or ""))
    # 输出预算取自 KB 配置(arch_collab_config.llm.maxTokens；空则透传 None，
    # 由主后端按 model_configs.max_tokens 兜底)。固定 4000 对大文件过紧，易致 JSON
    # 截断后整批落入启发式兜底(空 steps/branches)；KB 模型配置默认 16384 足够。
    from .req_agent import get_max_tokens_preference
    max_tokens = get_max_tokens_preference()
    messages = [{"role": "system", "content": sys_prompt},
                {"role": "user", "content": context_text}]
    res = llm_sync(messages, mode="structured", output_schema=_ASSET_OUTPUT_SCHEMA,
                   max_tokens=max_tokens, model_id=model_id)
    if not res:
        logger.warning("[semantic] llm 提取返回空/失败(将走启发式兜底)")
        return []
    output = res.get("output")
    if not isinstance(output, dict):
        logger.warning("[semantic] llm 提取输出非 dict: type=%s content_len=%d "
                       "structuredError=%r(将走启发式兜底)",
                       type(output).__name__, len(res.get("content") or ""),
                       str(res.get("structuredError"))[:300])
        return []
    valid, dropped = _normalize_llm_assets(output, level, table, max_assets)
    # detail 完整性定向重试：behavior 缺 steps/trigger、rule 缺 branches 时，回喂提示
    # 让模型补全(与 B1 的 JSON 解析重试互补，B1 只覆盖解析失败，不覆盖「可解析但空 detail」)。
    incomplete = [a for a in valid if not _llm_asset_detail_ok(a)]
    if incomplete:
        hint = _detail_retry_hint(incomplete)
        retry_msgs = messages + [
            {"role": "assistant", "content": res.get("content") or ""},
            {"role": "user", "content": hint},
        ]
        res2 = llm_sync(retry_msgs, mode="structured", output_schema=_ASSET_OUTPUT_SCHEMA,
                        max_tokens=max_tokens, model_id=model_id)
        if res2 and isinstance(res2.get("output"), dict):
            valid2, dropped2 = _normalize_llm_assets(res2["output"], level, table, max_assets)
            # 仅当重试结果比首轮有更多 detail 完整资产时采用(模型可能反而退化/省略已完整资产)。
            if valid2 and (sum(_llm_asset_detail_ok(a) for a in valid2)
                           > sum(_llm_asset_detail_ok(a) for a in valid)):
                valid, dropped = valid2, dropped + dropped2
    # 仍缺 detail 的资产：仅当存在其它完整资产时丢弃并告警(避免空 steps/branches 资产
    # 污染活动图/状态图)；若全部缺 detail，则保留(业务命名仍优于启发式符号名兜底，
    # 且丢弃整批会级联触发启发式，同样空 detail 且名称更差)。
    kept = [a for a in valid if _llm_asset_detail_ok(a)]
    dropped_empty = 0
    if kept:
        dropped_empty = len(valid) - len(kept)
        if dropped_empty:
            logger.warning("[semantic] llm 提取丢弃缺 detail 资产 %d 个: %s",
                           dropped_empty,
                           ", ".join((a.get("name") or "?") for a in valid if not _llm_asset_detail_ok(a))[:200])
        valid = kept
    elif valid:
        logger.warning("[semantic] llm 提取全部缺 detail(%d 个)，保留业务命名资产", len(valid))
    logger.info("[semantic] llm 提取输出: 原始=%d 有效=%d 丢弃=%d",
                len(output.get("assets") or []), len(valid), dropped + dropped_empty)
    raw_assets = output.get("assets") or []
    if raw_assets and not valid:
        logger.warning("[semantic] llm 提取资产全部未通过归一化: 首个键=%s 首个type=%r",
                       list((raw_assets[0] or {}).keys()) if isinstance(raw_assets[0], dict) else "-",
                       (raw_assets[0] or {}).get("type") if isinstance(raw_assets[0], dict) else None)
    return valid


# ── 启发式降级 ────────────────────────────────────────────────

# infra 量化信号：符号签名/文档命中任一类别即判基础设施级(首个命中类别写入 tags)。
_INFRA_SIGNALS: List[Tuple[str, Tuple[str, ...]]] = [
    ("async", ("async def", "await ", "asyncio", "thread", "semaphore", "queue", "pool")),
    ("transactional", ("@transaction", "transaction", "commit(", "rollback", "atomic", "begin(")),
    ("caching", ("@lru_cache", "cache", "redis", "memoiz", "@cache")),
    ("security", ("auth", "login", "jwt", "token", "permission", "require_")),
    ("observability", ("logger", "trace", "metric", "instrument", "@log")),
    ("middleware", ("middleware", "before_request", "after_request", "hook", "interceptor")),
    ("resilience", ("rate_limit", "throttl", "retry", "backoff")),
]


def _infra_tags(text: str) -> List[str]:
    """符号签名/文档 → 命中的 infra 切面标签(量化：≥1 信号即 infra)。"""
    t = (text or "").lower()
    hit = [tag for tag, sigs in _INFRA_SIGNALS if any(s in t for s in sigs)]
    return hit


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


def _config_consumer_signal(node: dict, edges: List[dict],
                            name_of: Optional[Dict[str, str]] = None) -> bool:
    """强信号②：符号 calls 配置读写符号(如 register_success calls get_config) → 是执行点，非 Rule。"""
    out_edges = [e for e in (edges or []) if e.get("source") == node.get("id")]
    for e in out_edges:
        if e.get("kind") != "calls":
            continue
        tgt = e.get("target") or ""
        if tgt.startswith("cache:") or "::" in tgt:
            tgt = tgt.rsplit("::", 1)[-1]
        t = tgt.lower()
        if any(k in t for k in ("get_config", "set_config", "get_threshold", "set_threshold",
                                "get_settings", "load_config", "get_all_config")):
            return True
    return False


def _classify_rule_role(node: dict, edges: List[dict],
                        name_of: Optional[Dict[str, str]] = None) -> str:
    """符号的规则角色判定(信号优先)：
    - 'rule'    : 配置载体(定义侧) → 静态 Rule 资产；
    - 'dynamic' : 配置消费者(执行侧) → 归 process/decision，由 detail 用 uses 关联规则；
    - ''        : 无信号，不参与规则判定。
    """
    if _config_carrier_signal(node):
        return "rule"
    if _config_consumer_signal(node, edges, name_of):
        return "dynamic"
    return ""


def _heuristic_extract(kind: str, ctx: Dict[str, Any],
                       level: str = "logic") -> List[dict]:
    """无 LLM 时的确定性提取。

    - level='implementation' : 代码事实层。concrete_type/call_chain/branch_logic/message_contract
                              一一对应 codegraph 符号节点(名称=符号名，锚定真实节点)，零臆造。
    - level='logic' : 逻辑级降级。以符号名+签名/docstring 兜底(名称=符号名，粒度近 implementation，
                     供 LLM 不可用时仍能消费)。
    - kind='rule'   : 配置载体强信号过滤 —— 仅当命中配置读写符号(Config 类 / _DEFAULT_* 常量 /
                      get_config(key,default) 类签名)时产出，硬编码分支归 decision。
    - kind='state'  : 从枚举/含状态字段的类型归纳状态机(独立于粒度信号)。
    """
    nodes = ctx.get("nodes") or []
    edges = ctx.get("edges") or []
    root = ctx.get("root") or ""
    out: List[dict] = []
    low = level == "implementation"
    node_by_id = {n.get("id"): n for n in nodes}
    name_of = {n.get("id"): (n.get("qualified_name") or n.get("name") or "") for n in nodes}
    if kind == "entity":
        for n in nodes:
            if n.get("kind") not in ("class", "interface", "enum", "struct", "component"):
                continue
            doc = (n.get("docstring") or "").strip()
            desc = doc or (f"数据结构「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。"
                           if not low else
                           f"具体类型「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。")
            fields = _fields_from_node(n) or _member_fields_from_edges(n.get("id"), edges, node_by_id)
            if not fields:
                # codegraph 对 Python 等语言常缺字段级节点 → 源码回读兜底(所有粒度都填属性)。
                fields = _fields_from_source(root, n)
            detail = {"fields": fields, "relations": [], "invariants": []}
            if low:
                detail = {"kind": "type", "signature": n.get("signature") or "",
                          "fields": fields, "invariants": []}
            out.append({"kind": kind, "level": level, "name": n["name"], "desc": desc,
                        "detail": detail, "astRefs": [_node_to_ref(n)]})
    elif kind == "process":
        for n in nodes:
            if n.get("kind") not in ("function", "method", "route"):
                continue
            sig = n.get("signature") or ""
            doc = (n.get("docstring") or "").strip()
            desc = doc or (f"处理流程「{n['name']}」，签名 ({sig})，位于 {n['file_path']}:{n['start_line']}。"
                           if not low else
                           f"调用链「{n['name']}」，签名 ({sig})，位于 {n['file_path']}:{n['start_line']}。")
            detail = {"trigger": "", "steps": [], "invariants": []}
            if low:
                callees = _callee_names(n.get("id"), edges, name_of)
                detail = {"trigger": "", "kind": "call_chain",
                          "steps": [{"order": 1, "semantic": "调用 " + c, "symbols": [c]}
                                    for c in callees],
                          "invariants": []}
            out.append({"kind": kind, "level": level, "name": n["name"], "desc": desc,
                        "detail": detail, "astRefs": [_node_to_ref(n)]})
    elif kind == "decision":
        for n in nodes:
            if n.get("kind") not in ("function", "method", "route"):
                continue
            sig = n.get("signature") or ""
            doc = (n.get("docstring") or "").strip()
            desc = doc or (f"控制逻辑「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。"
                           if not low else
                           f"分支逻辑「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。")
            detail = {"branches": [], "invariants": []}
            if low:
                detail = {"kind": "branch_logic",
                          "branches": [{"condition": "", "then": "", "else": "",
                                        "semantic": f"分支判定: {n['name']}", "symbols": [n["name"]]}],
                          "invariants": []}
            out.append({"kind": kind, "level": level, "name": n["name"], "desc": desc,
                        "detail": detail, "astRefs": [_node_to_ref(n)]})
    elif kind == "contract":
        for n in nodes:
            if n.get("kind") not in ("function", "method", "route"):
                continue
            sig = n.get("signature") or ""
            doc = (n.get("docstring") or "").strip()
            desc = doc or (f"服务契约「{n['name']}」，签名 ({sig})，位于 {n['file_path']}:{n['start_line']}。"
                           if not low else
                           f"消息/签名约定「{n['name']}」，签名 ({sig})，位于 {n['file_path']}:{n['start_line']}。")
            detail = {"relations": [], "invariants": []}
            if low:
                detail = {"kind": "message_contract",
                          "relations": [{"target": "", "type": "signature", "semantic": sig}],
                          "invariants": []}
            out.append({"kind": kind, "level": level, "name": n["name"], "desc": desc,
                        "detail": detail, "astRefs": [_node_to_ref(n)]})
    elif kind == "rule":
        # 配置载体强信号：仅产出命中配置读写信号的符号(定义侧)；配置消费者(执行侧)归 decision/process。
        for n in nodes:
            role = _classify_rule_role(n, edges, name_of)
            if role != "rule":
                continue
            doc = (n.get("docstring") or "").strip()
            desc = doc or f"配置/阈值「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。"
            detail = {"configSource": "", "constraints": [], "thresholds": []}
            if low:
                detail = {"kind": "config_item", "configSource": n.get("file_path") or "",
                          "constraints": [], "thresholds": []}
            out.append({"kind": kind, "level": level, "name": n["name"], "desc": desc,
                        "detail": detail, "astRefs": [_node_to_ref(n)]})
    elif kind == "state":
        # 从枚举(状态集合)或含 status/state 字段的类型归纳状态机；迁移为确定性推导(条件留空)。
        enum_nodes = [n for n in nodes if n.get("kind") == "enum"]
        for n in enum_nodes:
            members = _member_fields_from_edges(n.get("id"), edges, node_by_id)
            if not members:
                continue
            states = [{"name": m.get("name") or f"s{i}", "desc": "",
                       "initial": i == 0, "final": i == len(members) - 1}
                      for i, m in enumerate(members)]
            transitions = [{"from": states[i]["name"], "to": states[i + 1]["name"],
                            "event": "", "condition": "", "action": ""}
                           for i in range(len(states) - 1)]
            out.append({"kind": kind, "level": level,
                        "name": n["name"], "desc": f"实体生命周期「{n['name']}」的状态机(枚举推导)。",
                        "detail": {"states": states, "transitions": transitions, "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
    return out[:12]


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


def _primary_kind_for_node(node: dict, edges: List[dict],
                           name_of: Optional[Dict[str, str]] = None,
                           node_by_id: Optional[Dict[str, dict]] = None) -> str:
    """实现层每符号只产一个主类别(信号优先，避免跨类别重复)：

    rule(配置载体) > contract(路由/api 边界) > entity(类型) / state(枚举)
    > decision(分支密集) > process(普通函数)。
    """
    kind = (node.get("kind") or "").lower()
    if _config_carrier_signal(node):
        return "rule"
    if _is_contract_boundary_node(node, edges, name_of, node_by_id):
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
    out: List[dict] = []
    per_kind_cap: Dict[str, int] = {}
    for n in nodes:
        pk = _primary_kind_for_node(n, edges, name_of, node_by_id)
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
                                   "constraints": [], "thresholds": []},
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
            out.append({"kind": "contract", "level": level, "name": n["name"],
                        "desc": doc or f"服务契约「{n['name']}」，签名 ({sig})，位于 {n['file_path']}:{n['start_line']}。",
                        "detail": {"kind": "message_contract",
                                   "relations": [{"target": "", "type": "signature", "semantic": sig}],
                                   "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
        elif pk == "decision":
            sig = n.get("signature") or ""
            doc = (n.get("docstring") or "").strip()
            out.append({"kind": "decision", "level": level, "name": n["name"],
                        "desc": doc or f"分支逻辑「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。",
                        "detail": {"kind": "branch_logic",
                                   "branches": [{"condition": "", "then": "", "else": "",
                                                 "semantic": f"分支判定: {n['name']}", "symbols": [n["name"]]}],
                                   "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
        else:  # process
            callees = _callee_names(n.get("id"), edges, name_of)
            sig = n.get("signature") or ""
            doc = (n.get("docstring") or "").strip()
            out.append({"kind": "process", "level": level, "name": n["name"],
                        "desc": doc or f"调用链「{n['name']}」，签名 ({sig})，位于 {n['file_path']}:{n['start_line']}。",
                        "detail": {"trigger": "", "kind": "call_chain",
                                   "steps": [{"order": 1, "semantic": "调用 " + c, "symbols": [c]}
                                             for c in callees],
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
    """低粒度调用链：取 1-hop 直接调用目标符号名(经 name_of 把节点 id 解析为符号名)。"""
    out: List[str] = []
    for e in edges or []:
        if e.get("kind") == "calls" and e.get("source") == node_id and e.get("target"):
            t = e["target"]
            out.append(name_of.get(t, t) if name_of else t)
    return list(dict.fromkeys(out))[:8]


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


# ── 持久化(增量 change) ───────────────────────────────────────

def _file_md5(root: str, rel: str) -> str:
    """文件内容哈希签名(对应要求①：AST 节点 ↔ 文件哈希)。"""
    if not root or not rel:
        return ""
    full = os.path.join(root, rel.lstrip("/").replace("/", os.sep))
    try:
        with open(full, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()[:16]
    except Exception:
        return ""


def _anchor_hashes(root: str, ast_refs: List[dict]) -> Dict[str, str]:
    """资产锚定文件的哈希签名表(去重)。"""
    files = list(dict.fromkeys(r.get("file") or "" for r in ast_refs if r.get("file")))
    return {f: _file_md5(root, f) for f in files if f}


def _canonical_key(kind: str, level: str, ast_refs: List[dict],
                   name: str = "", scope_type: str = "", scope_key: str = "") -> str:
    """稳定规范标识 canonicalKey：逻辑类型 + 抽象粒度 + 代码锚点(文件:符号) 的确定性指纹。

    资产身份 = 代码(锚点)，**与提取它的组件口径(INCLUDE/CALL)无关**：
    同一段代码(同一组锚点)在任一组件下提取都得到同一个 canonicalKey，id 复用不重复。
    kind+level 纳入指纹，避免同一锚点在行为/规则与 high/medium/low 间误合并。
    无 AST 锚点的资产(纯语义/合成，如 H 级聚合)退化为名称派生 key(scope 仅作碰撞消解)。
    """
    anchors = sorted({
        f"{r.get('file', '')}:{r.get('symbol', '')}"
        for r in ast_refs if r.get("file")
    })
    if anchors:
        seed = f"{kind}|{level}|{'|'.join(anchors)}"
    else:
        seed = f"{kind}|{level}|{scope_type}|{scope_key}|name:{name}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]


_EDGE_SEMANTIC = {
    "calls": "调用依赖",
    "contains": "包含",
    "extends": "继承",
    "implements": "实现",
    "imports": "导入依赖",
    "references": "引用",
    "instantiates": "实例化",
}


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
_IMPL_KIND_CAP = 80


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
    pid = project_id_for(root, project)
    degraded = ctx.get("source") != "codegraph"
    logger.info(
        "[semantic] extract_scope 范围 %s(%s) level=%s kinds=%s files=%d symbols=%d "
        "source=%s nodes=%d codegraph_synced=%s",
        scope_type, scope_key or "-", level, kinds, len(ctx.get("files") or []),
        len(ctx.get("symbols") or []), ctx.get("source"), len(ctx.get("nodes") or []), synced)
    all_assets: List[dict] = []
    llm_count = 0
    if use_llm:
        try:
            llm_assets = _llm_extract(root, project, ctx.get("text") or "", model_id,
                                      table=ctx.get("table") or {}, level=level)
            llm_count = len(llm_assets or [])
        except Exception as e:
            logger.warning("[semantic] llm extract failed: %s", e, exc_info=True)
            llm_assets = []
        if llm_assets:
            all_assets = llm_assets
    heur_counts: Dict[str, int] = {}
    if not all_assets:
        degraded = True
        if level == "implementation":
            # 实现层单趟主类别分配：每符号只产一个资产(消除跨类别重复)。
            all_assets = _heuristic_extract_primary(ctx, kinds)
            for a in all_assets:
                heur_counts[a["kind"]] = heur_counts.get(a["kind"], 0) + 1
        else:
            for k in kinds:
                _before = len(all_assets)
                all_assets += _heuristic_extract(k, ctx, level=level)
                heur_counts[k] = len(all_assets) - _before
    logger.info(
        "[semantic] extract_scope 结果: scope=%s(%s) llm=%d heuristic=%s "
        "degraded=%s saved=%d text_len=%d",
        scope_type, scope_key or "-", llm_count, heur_counts or "-",
        degraded, len(all_assets), len(ctx.get("text") or ""))
    saved = _save_assets(pid, scope_type or "project", scope_key or "_", all_assets, ctx)
    return {"assets": saved, "source": ctx.get("source"), "degraded": degraded,
            "count": len(saved)}


def _extract_file_set(root: str, project: Optional[str],
                      files: Optional[List[str]],
                      kinds: Optional[List[str]] = None,
                      model_id: Optional[str] = None,
                      use_llm: bool = True,
                      level: str = "implementation") -> Tuple[List[dict], int, List[str]]:
    """对去重后的文件集合逐文件单次提取(每文件独立 LLM 上下文)。

    INCLUDE/CALL 两套组件重叠文件只提取一次；资产身份=代码锚点，
    归属(membership)由 `_save_assets` 按锚点文件推导，不重复建行。
    返回 (assets, extracted_files, failed_files)。
    """
    todo = sorted({_norm_path(f) for f in (files or []) if f})
    assets: List[dict] = []
    failed: List[str] = []
    done = 0
    for f in todo:
        try:
            res = extract_scope(root, project, "files", f, files=[f],
                                kinds=kinds, model_id=model_id,
                                use_llm=use_llm, level=level)
            assets += res.get("assets") or []
            done += 1
        except Exception as e:
            failed.append(f)
            logger.warning("[semantic] extract file %s failed: %s", f, e, exc_info=True)
    return assets, done, failed


def _extract_file_set_levels(root: str, project: Optional[str],
                             files: Optional[List[str]],
                             kinds: Optional[List[str]] = None,
                             model_id: Optional[str] = None,
                             use_llm: bool = True,
                             levels: Tuple[str, ...] = ("implementation",)) -> Tuple[List[dict], int, List[str]]:
    """对文件集合逐级提取(默认仅 implementation)，合并各层级资产。

    满足按粒度展示：业务级(business)由聚合层按需从 logic 资产聚合；
    逻辑级+业务级当前暂停再生，需要时显式传 levels。
    """
    assets: List[dict] = []
    done, failed = 0, []
    for lv in levels:
        a, d, f = _extract_file_set(root, project, files, kinds,
                                    model_id=model_id, use_llm=use_llm, level=lv)
        assets += a
        done += d
        failed += f
    return assets, done, failed


_AGG_HINT = {
    "llm": "LLM 服务不可达或调用失败，已重试仍失败",
    "parse": "LLM 返回内容未能解析为结构化资产，已重试仍失败",
    "empty": "当前无足够交互/算法级资产可聚合",
}

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


def _resolve_extract_levels(level: str) -> Tuple[str, ...]:
    """请求粒度 → 需提取的层级。显式层级只产该级；缺省/all 仅产 implementation。

    业务层+逻辑层当前暂停再生：默认只专注实现层。显式请求 logic/business
    (如单资产重提/按需聚合)仍可单独产出，不影响已落库资产的只读展示。
    """
    if level in SEMANTIC_LEVELS:
        return (level,)
    return ("implementation",)


def extract_all(root: Optional[str], project: Optional[str],
                kinds: Optional[List[str]] = None,
                model_id: Optional[str] = None,
                use_llm: bool = True,
                max_components: int = 12,
                level: str = "all") -> Dict[str, Any]:
    """批处理: 组件目录(跨 INCLUDE/CALL × L0/L1)文件并集 → 逐文件多级提取。

    组件是下游投影(资产身份=代码锚点)，两套组件重叠文件不重复提取。
    无组件时按全项目提取一次。缺省 level 产出 implementation+logic 并聚合 business，
    保证业务层/逻辑层/实现层三档按粒度展示都有数据。
    """
    root = resolve_root(root, project)
    if not root:
        logger.warning("[semantic] extract_all 中止: 项目 root 解析失败 (root=%r project=%r)", root, project)
        return {"assets": [], "count": 0, "components": 0}
    from .common import build_component_catalog
    comps = []
    try:
        comps = (build_component_catalog(root, project) or {}).get("components") or []
    except Exception as e:
        logger.warning("[semantic] extract_all 组件目录解析失败: %s", e, exc_info=True)
        comps = []
    files: List[str] = []
    for c in comps[:max_components]:
        files += (c.get("owns") or [])
    logger.info("[semantic] extract_all 组件目录: 组件=%d 文件(去重前)=%d level=%s",
                len(comps), len(files), level)
    levels = _resolve_extract_levels(level)
    file_levels = tuple(lv for lv in levels if lv in ("implementation", "logic"))
    # 业务级聚合暂停再生：仅当显式请求 level="business" 才触发聚合(默认不再自动产 business)。
    do_business = level == "business"
    business_count = 0
    if not files:
        logger.info("[semantic] extract_all 无组件文件, 按全项目提取一次")
        assets: List[dict] = []
        for lv in file_levels:
            res = extract_scope(root, project, "project", kinds=kinds,
                                model_id=model_id, use_llm=use_llm, level=lv)
            assets += res.get("assets") or []
    else:
        assets, done, _failed = _extract_file_set_levels(root, project, files, kinds,
                                                         model_id=model_id, use_llm=use_llm,
                                                         levels=file_levels)
    business_count = 0
    business_reason = "ok"
    if do_business:
        agg = _aggregate_high_best_effort(root, project, model_id) or {}
        business_count = agg.get("count") or 0
        business_reason = agg.get("reason") or "ok"
    logger.info("[semantic] extract_all 完成: 文件=%d 资产=%d business=%d business_reason=%s",
                len(files), len(assets), business_count, business_reason)
    return {"assets": assets, "count": len(assets), "components": len(comps),
            "business": business_count, "businessReason": business_reason}


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
    from .common import build_component_catalog
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
    from .common import build_component_catalog
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
    from .req_agent import llm_sync, get_max_tokens_preference
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


# ── 批量管理(选定组件范围: 提取/清除/更新) ──────────────────────

def _component_file_map(root: str, project: Optional[str]) -> Dict[str, set]:
    """组件 → 文件集合。以组件目录(跨 INCLUDE/CALL × L0/L1，即组件列表完整来源)为准，
    与 `_comm_files` 解析口径一致(不再用 INCLUDE 单视图 codeMappings)。失败返回空。"""
    comp_files: Dict[str, set] = {}
    try:
        from .common import build_component_catalog
        catalog = build_component_catalog(root, project)
        for c in catalog.get("components") or []:
            cid = c.get("id")
            if not cid:
                continue
            for f in (c.get("owns") or []):
                if f:
                    comp_files.setdefault(cid, set()).add(_norm_path(f))
    except Exception as e:
        logger.warning("[semantic] component file map failed: %s", e)
    return comp_files


def _file_to_components(root: str, project: Optional[str]) -> Dict[str, List[str]]:
    """文件 → 拥有它的组件 id 列表(跨 INCLUDE/CALL 两套口径)。
    供 `_save_assets` 把资产按锚点文件归属到所有组件(资产身份=代码，组件是下游投影)。"""
    out: Dict[str, List[str]] = {}
    for cid, files in _component_file_map(root, project).items():
        for f in files:
            if f not in out:
                out[f] = []
            if cid not in out[f]:
                out[f].append(cid)
    return out


def _asset_scope_membership(ast_refs: List[dict],
                            file_to_comps: Dict[str, List[str]]) -> List[str]:
    """资产锚点文件 → 归属组件 id 集合(去重排序)。无锚点/无归属 → 空。"""
    comps: List[str] = []
    for r in ast_refs or []:
        f = _norm_path(r.get("file") or "")
        for cid in file_to_comps.get(f) or []:
            if cid not in comps:
                comps.append(cid)
    return sorted(comps)



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

    - extract: 对每个组件(未指定则全部)按 comm 范围提取并落库。
               更新语义 = 重新提取(可先 clear 删除再提取，或直接重提覆盖)。
    - clear:   物理删除选定组件范围内的语义资产(不做软删保留)，
               dry_run=True 仅返回影响范围供确认。

    scopes: 与 search 一致的组件范围语义(None=全部 / ['__other__']=仅其它 /
            组件 id 列表)。兼容旧参数 comp_ids+include_other(空 comp_ids 且 include_other=True = 全部)。
    返回 {action, count, components?, cleared?, updated?}。
    """
    root = resolve_root(root, project)
    comp_ids = [c for c in (comp_ids or []) if c]
    if action == "extract":
        if not comp_ids:
            try:
                from .common import build_component_catalog
                comps = (build_component_catalog(root, project) or {}).get("components") or []
                seen: set = set()
                comp_ids = []
                for c in comps:
                    cid = c.get("id")
                    if cid and cid not in seen:
                        seen.add(cid)
                        comp_ids.append(cid)
            except Exception as e:
                logger.warning("[semantic] batch extract resolve components failed: %s", e)
                comp_ids = []
        # 组件文件并集 → 逐文件单次提取(INCLUDE/CALL 重叠不重复)。
        files: List[str] = []
        for cid in comp_ids:
            files += _comm_files(root, cid, project)
        logger.info("[semantic] batch extract 开始: comp_ids=%d 文件=%d kinds=%s level=%s",
                    len(comp_ids), len(files), kinds, level)
        if not files:
            return {"action": action, "count": 0, "components": len(comp_ids),
                    "cleared": [], "updated": []}
        levels = _resolve_extract_levels(level or "")
        assets, done, _failed = _extract_file_set_levels(root, project, files, kinds,
                                                         model_id=model_id, use_llm=True,
                                                         levels=levels)
        high_count = 0
        high_reason = "ok"
        # 业务层暂停再生：仅显式请求 level="business" 才聚合。
        if (level or "") == "business":
            agg = _aggregate_high_best_effort(root, project, model_id) or {}
            high_count = agg.get("count") or 0
            high_reason = agg.get("reason") or "ok"
        logger.info("[semantic] batch extract 完成: 文件=%d 资产=%d high=%d high_reason=%s",
                    done, len(assets), high_count, high_reason)
        return {"action": action, "count": len(assets), "components": len(comp_ids),
                "cleared": [], "updated": [], "high": high_count, "highReason": high_reason}
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


# ── 提取任务(状态保持：服务端后台执行，进度/消息持久化) ──────────

_EXTRACT_THREADS: Dict[str, threading.Thread] = {}
_EXTRACT_LOCK = threading.Lock()


def _task_append_message(task_id: str, role: str, content: str) -> dict:
    """向提取任务追加一条对话消息(持久化到 task.messages，供前端轮询同步)。"""
    now = _ts()
    msg = {"id": store.next_id("m"), "role": role, "content": content, "time": now}
    try:
        task = store.ExtractTaskStore.get(task_id)
        msgs = list(task.get("messages") or []) if task else []
        msgs.append(msg)
        store.ExtractTaskStore.update(task_id, {"messages": msgs, "updatedAt": now})
    except Exception as e:
        logger.warning("[semantic] extract task append message failed: %s", e)
    return msg


def _task_update_progress(task_id: str, progress: Optional[list] = None,
                          done: Optional[int] = None, total: Optional[int] = None,
                          status: Optional[str] = None) -> None:
    """更新任务进度(progress: 每组件状态 [{compId,status,count,error}])。"""
    payload: Dict[str, Any] = {"updatedAt": _ts()}
    if progress is not None:
        payload["progress"] = progress
    if done is not None:
        payload["done"] = done
    if total is not None:
        payload["total"] = total
    if status is not None:
        payload["status"] = status
    try:
        store.ExtractTaskStore.update(task_id, payload)
    except Exception as e:
        logger.warning("[semantic] extract task update failed: %s", e)


def _extract_one_comp(task_id: str, cid: str, name: str, kinds: Optional[List[str]],
                      root: Optional[str], project: Optional[str],
                      model_id: Optional[str], files: Optional[List[str]] = None) -> dict:
    """执行单个组件提取并同步消息/进度；返回该组件结果。

    files: 该组件内本次**尚未提取**的文件(任务级去重后)；为空表示已被其它组件覆盖。
    """
    _task_append_message(task_id, "assistant", f"▶ 开始提取组件「{name}」({cid})…")
    result: Dict[str, Any] = {"compId": cid, "status": "running", "count": 0, "error": ""}
    try:
        if not files:
            result["status"] = "done"
            _task_append_message(task_id, "assistant",
                                 f"✔ 组件「{name}」文件已被其它组件覆盖，跳过重复提取。")
            return result
        assets, _, failed = _extract_file_set_levels(root, project, files, kinds,
                                                     model_id=model_id, use_llm=True,
                                                     levels=("implementation",))
        result["count"] = len(assets)
        if failed:
            result["status"] = "failed"
            result["error"] = "文件提取失败: " + ", ".join(failed[:3])
            _task_append_message(task_id, "assistant",
                                 f"✘ 组件「{name}」部分文件提取失败：{', '.join(failed[:3])}")
        else:
            result["status"] = "done"
            _task_append_message(task_id, "assistant",
                                 f"✔ 组件「{name}」完成，产出 {len(assets)} 个语义资产。")
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        _task_append_message(task_id, "assistant",
                             f"✘ 组件「{name}」提取失败：{e}")
    return result


def _run_extract_task(task_id: str, comp_ids: List[str], names: Dict[str, str],
                      kinds: Optional[List[str]], root: Optional[str],
                      project: Optional[str], model_id: Optional[str]) -> None:
    """后台执行提取任务：跨组件去重后逐文件单次提取(INCLUDE/CALL 重叠不重复)，
    进度/消息按组件持久化，任务结束更新状态。"""
    # 先为每个组件解析其文件，任务级按文件去重：每文件只提取一次。
    seen_files: set = set()
    comp_files: Dict[str, List[str]] = {}
    for cid in comp_ids:
        own = []
        for f in _comm_files(root, cid, project):
            if f not in seen_files:
                seen_files.add(f)
                own.append(f)
        comp_files[cid] = own
    total = len(comp_ids)
    progress: List[dict] = []
    done = 0
    for i, cid in enumerate(comp_ids):
        name = names.get(cid) or cid
        result = _extract_one_comp(task_id, cid, name, kinds, root, project,
                                   model_id, files=comp_files.get(cid) or [])
        progress.append(result)
        if result["status"] == "done":
            done += 1
        _task_update_progress(task_id, progress=progress, done=done, total=total)
        if i < total - 1:
            _task_append_message(task_id, "assistant",
                                 f"…进度 {done}/{i + 1}·{total} 组件完成")
    if done == total:
        status = "done"
        tail = "全部组件提取完成。"
    elif done > 0:
        status = "partial"
        tail = f"部分完成：{done}/{total} 组件成功，其余失败。"
    else:
        status = "failed"
        tail = "全部组件提取失败，请检查 LLM/KB 后重试。"
    _task_append_message(task_id, "assistant", f"✅ {tail}")
    _task_update_progress(task_id, status=status)
    with _EXTRACT_LOCK:
        _EXTRACT_THREADS.pop(task_id, None)


def start_extract_task(root: Optional[str], project: Optional[str],
                       comp_ids: List[str], kinds: Optional[List[str]] = None,
                       model_id: Optional[str] = None,
                       title: str = "语义资产提取") -> Dict[str, Any]:
    """创建并后台启动提取任务。返回 {taskId, ...}；线程 daemon 运行，不阻塞 HTTP。"""
    comp_ids = [c for c in (comp_ids or []) if c]
    if not comp_ids:
        return {"taskId": "", "error": "未选择任何组件"}
    # 组件名解析(展示用；缺失退化为 id)
    names: Dict[str, str] = {}
    try:
        from .common import build_component_catalog
        catalog = build_component_catalog(root, project)
        for c in catalog.get("components") or []:
            if c.get("id"):
                names[c["id"]] = c.get("name") or c.get("id") or c["id"]
    except Exception:
        pass
    now = _ts()
    task_id = store.next_id("saxt")
    task = {
        "id": task_id, "projectId": project_id_for(root, project),
        "root": resolve_root(root, project) or "", "status": "running",
        "kind": "semantic", "compIds": comp_ids,
        "total": len(comp_ids), "done": 0,
        "progress": [], "messages": [], "meta": {"title": title},
        "createdAt": now, "updatedAt": now,
    }
    store.ExtractTaskStore.create(task)
    thread = threading.Thread(
        target=_run_extract_task,
        args=(task_id, comp_ids, names, kinds, root, project, model_id),
        daemon=True,
    )
    with _EXTRACT_LOCK:
        _EXTRACT_THREADS[task_id] = thread
    thread.start()
    return {"taskId": task_id}


def get_extract_task(task_id: str) -> Optional[dict]:
    return store.ExtractTaskStore.get(task_id)


def _task_thread_alive(task_id: str) -> bool:
    """任务对应的后台线程是否仍存活(模块内进程重启后均为 False → 孤儿任务)。"""
    with _EXTRACT_LOCK:
        t = _EXTRACT_THREADS.get(task_id)
        return bool(t and t.is_alive())


def _reap_orphan_extract_task(task_id: str) -> Optional[dict]:
    """回收孤儿任务：状态为 running 但后台线程已死(进程强杀/重启遗留)。
    标记 failed 并追加提示消息，返回回收后的任务；非孤儿返回 None。"""
    task = store.ExtractTaskStore.get(task_id)
    if not task:
        return None
    if (task.get("status") or "running") == "running" and not _task_thread_alive(task_id):
        _task_append_message(task_id, "assistant",
                             "⚠ 提取任务中断：服务进程已重启/关闭，后台线程被终止，无法继续。请重新发起提取。")
        store.ExtractTaskStore.update(task_id, {"status": "failed", "updatedAt": _ts()})
        logger.info("[semantic] reaped orphan extract task %s (process restarted)", task_id)
        return store.ExtractTaskStore.get(task_id)
    return None


def extract_task_status(task_id: str) -> Dict[str, Any]:
    """任务状态快照(供前端轮询)：status/progress/messages + 概要。
    进程重启遗留的 running 孤儿任务在此被标记为 failed，避免前端永久卡在"提取中"。"""
    task = _reap_orphan_extract_task(task_id)
    if task is None:
        task = store.ExtractTaskStore.get(task_id)
    if not task:
        return {"found": False}
    msgs = task.get("messages") or []
    progress = task.get("progress") or []
    return {
        "found": True,
        "id": task.get("id"),
        "status": task.get("status") or "running",
        "done": task.get("done") or 0,
        "total": task.get("total") or 0,
        "progress": progress,
        "messages": msgs,
        "title": (task.get("meta") or {}).get("title") or "语义资产提取",
        "updatedAt": task.get("updatedAt"),
        "running": (task.get("status") or "running") == "running",
    }


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
        from .project import _resolve_project as _rp
        proj = _rp(root, project)
    except Exception:
        proj = None
    if proj:
        try:
            from .arch_git import diff_worktree
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
            continue
        h = _file_md5(root, rel)
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
    conn = _open_cg(root)
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


def _derive_project_edges(root: Optional[str], project: Optional[str],
                          assets: List[dict]) -> List[dict]:
    """从 codegraph 边程序化合成资产间关系(不持久化)。

    把每个资产锚点符号解析到 codegraph 节点，再对 calls/contains/extends/
    imports/references/instantiates 边，两端各锚定不同资产 → 产出一条边。
    供 `semantic_graph` 按粒度合成稳定关系，避免 LLM 命名的漂移。
    """
    if not assets:
        return []
    root = resolve_root(root, project)
    conn = _open_cg(root) if root else None
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
        ids = list(node_to_assets)
        ph = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT source, target, kind FROM edges "
            f"WHERE source IN ({ph}) AND target IN ({ph}) "
            f"AND kind IN ('calls','contains','extends','imports','references','instantiates')",
            tuple(ids + ids)).fetchall()
        out: List[dict] = []
        seen: set = set()
        for s, t, k in rows:
            for a in node_to_assets.get(s, ()):
                for b in node_to_assets.get(t, ()):
                    if a == b:
                        continue
                    key = (a, b, k)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"from": a, "to": b, "type": k,
                                "semantic": _EDGE_SEMANTIC.get(k, k),
                                "derived": True})
        return out
    except Exception as e:
        logger.warning("[semantic] derive project edges failed: %s", e, exc_info=True)
        return []
    finally:
        conn.close()


def _cached_derived_edges(root: Optional[str], project: Optional[str],
                          assets: List[dict]) -> List[dict]:
    """派生边进程内缓存：键 = 项目 + 资产数 + 最新 updatedAt。"""
    if not assets:
        return []
    upd = [a.get("updatedAt") or 0 for a in assets]
    key = f"{project_id_for(root, project)}|{len(assets)}|{max(upd)}"
    hit = _DERIVED_EDGE_CACHE.get(key)
    now = time.time()
    if hit and (now - hit[0]) < _DERIVED_EDGE_TTL:
        return hit[1]
    edges = _derive_project_edges(root, project, assets)
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
                   focus: str = "", hops: int = 1) -> Dict[str, Any]:
    """语义层图谱：节点=语义资产，边=资产间 relations，锚点=AST 引用。

    边 = 存库基础 relations(按 id/name/nameAlias/符号解析) ∪ 程序化派生边
    (codegraph 边，_derive_project_edges)。派生边不持久化，随粒度筛选稳定合成。

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
            "detail": _graph_node_detail(a),
        })
        detail = a.get("detail") or {}
        for rel in detail.get("relations") or []:
            tgt, resolved = _resolve_relation_target((rel.get("target") or "").strip(), idx)
            if not tgt:
                continue
            edges.append({"from": aid, "to": tgt,
                          "resolved": resolved,
                          "type": rel.get("type") or "",
                          "semantic": rel.get("semantic") or ""})
        # 动态过程的三段端点(输入/输出) → 类型化边：inputs=uses/reads, outputs=writes/sends。
        for ep, etype in (("inputs", "uses"), ("outputs", "writes")):
            for rel in detail.get(ep) or []:
                tgt, resolved = _resolve_relation_target((rel.get("target") or "").strip(), idx)
                if not tgt:
                    continue
                edges.append({"from": aid, "to": tgt,
                              "resolved": resolved,
                              "type": rel.get("type") or etype,
                              "semantic": rel.get("semantic") or ""})
        for r in a.get("astRefs") or []:
            if r.get("file"):
                anchors.append({"assetId": aid, "file": r.get("file"),
                                "line": r.get("startLine") or 0,
                                "symbol": r.get("symbol") or "",
                                "kind": r.get("kind") or ""})
    # 程序化派生边(同层/跨层皆可，渲染与否由前端节点集决定)。
    derived = _cached_derived_edges(root, project, all_active)
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


# ── REST ──────────────────────────────────────────────────────

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
                    focus: str = "", hops: int = 1):
    """语义层图谱：节点=语义资产，边=资产 relations，锚点=AST 引用。

    scope: 逗号分隔的组件范围(scope_key)；kind: 资产种类过滤；level: 抽象粒度过滤。
    focus: 单资产聚焦(仅返回其周围 hops 跳子图)；hops: 聚焦跳数，默认 1。
    """
    scopes = [s.strip() for s in (scope or "").split(",") if s.strip()] or None
    lvl = level if level in SEMANTIC_LEVELS else ""
    return ok(semantic_graph(root, project, kind, scopes, level=lvl, limit=limit,
                             focus=focus, hops=hops))


@router.get("/kb/semantic/{asset_id}")
async def api_detail(asset_id: str, root: Optional[str] = None, project: Optional[str] = None):
    a = detail(asset_id, root, project)
    if not a:
        return err(404, f"语义资产 {asset_id} 不存在")
    return ok(a)


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
    res = handle_stale_asset(asset_id, body.get("root"), body.get("project"),
                             model_id=body.get("modelId"))
    return ok(res)


@router.post("/kb/semantic/extract")
async def api_extract(request: Request):
    body = await request.json()
    st, sk, files, symbols = _scope(body)
    lvl = body.get("level") or "implementation"
    logger.info("[semantic] /kb/semantic/extract 请求: type=%s key=%s files=%d symbols=%d kinds=%s level=%s",
                st, sk or "-", len(files or []), len(symbols or []), body.get("kinds"), lvl)
    res = extract_scope(body.get("root"), body.get("project"),
                        st, sk, files, symbols,
                        kinds=body.get("kinds"),
                        model_id=body.get("modelId"),
                        level=lvl)
    if not (res.get("count") or 0):
        logger.warning("[semantic] /kb/semantic/extract 产出 0: type=%s key=%s source=%s degraded=%s",
                       st, sk or "-", res.get("source"), res.get("degraded"))
    return ok(res)


@router.post("/kb/semantic/extractAll")
async def api_extract_all(request: Request):
    body = await request.json()
    lvl = body.get("level") or "all"
    logger.info("[semantic] /kb/semantic/extractAll 请求: kinds=%s model=%s max_components=%s level=%s",
                body.get("kinds"), body.get("modelId"), body.get("maxComponents"), lvl)
    res = extract_all(body.get("root"), body.get("project"),
                      kinds=body.get("kinds"),
                      model_id=body.get("modelId"),
                      use_llm=body.get("useLlm", True),
                      max_components=int(body.get("maxComponents") or 12),
                      level=lvl)
    return ok(res)


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
    res = refresh_scope(body.get("root"), body.get("project"), st, sk,
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


@router.post("/kb/semantic/extract-task")
async def api_start_extract_task(request: Request):
    """创建并后台启动组件语义资产提取任务(服务端执行，刷新不中断)。

    body: {root?, project?, components: string[], kinds?, modelId?}
    返回 {taskId}。前端轮询 GET /kb/semantic/extract-task/{id} 同步进度消息。
    """
    body = await request.json()
    res = start_extract_task(body.get("root"), body.get("project"),
                             comp_ids=body.get("components") or [],
                             kinds=body.get("kinds"),
                             model_id=body.get("modelId"))
    if not res.get("taskId"):
        return err(400, res.get("error") or "未选择任何组件")
    return ok({"taskId": res["taskId"]})


@router.get("/kb/semantic/extract-task/latest")
async def api_extract_task_latest(root: Optional[str] = None,
                                  project: Optional[str] = None):
    """最近一次提取任务(供刷新后恢复页面状态读取)。"""
    pid = project_id_for(root, project)
    task = store.ExtractTaskStore.latest(pid, kind="semantic")
    if not task:
        return ok(None)
    return ok(extract_task_status(task["id"]))


@router.get("/kb/semantic/extract-task/{task_id}")
async def api_extract_task_status(task_id: str):
    """轮询提取任务状态(含进度消息，供资产管理对话同步)。"""
    return ok(extract_task_status(task_id))


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
