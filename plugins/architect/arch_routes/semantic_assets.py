"""Semantic Data Assets — architect 自持语义数据资产提取/检索服务。

语义资产 = 介于「组件(社区级)」与「原始 AST 符号」之间的逻辑级抽象：
  - data_structure  : 语义化数据结构(字段/关系/不变量)，锚定 class/interface/enum/struct 节点
  - processing_flow : 语义化处理流程(触发/步骤序列/前置后置)，锚定跨函数调用链
  - control_logic   : 语义化控制逻辑(分支/条件/策略/校验)，锚定决策函数与分支

设计要点(结合最新代码结构):
  - 符号数据源: codegraph `.codegraph/codegraph.db`(提取前 `codegraph sync` 保鲜)，
    缺失时降级为轻量文件扫描; KB `architecture.model` 仅作组件归属/baseline 上下文。
  - LLM 通道: 复用 req_agent.llm_sync(经 KbGateway 转主后端)。LLM 不可用 → 启发式降级
    (名=符号名、描述=docstring/签名摘要)，AST 锚点始终取真实 codegraph 节点。
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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from .common import _ts, err, ok
from . import store

logger = logging.getLogger(__name__)
router = APIRouter()

SEMANTIC_KINDS = ("data_structure", "processing_flow", "control_logic")

_KIND_LABEL = {
    "data_structure": "语义化数据结构(字段/关系/不变量)",
    "processing_flow": "语义化处理流程(触发/步骤序列)",
    "control_logic": "语义化控制逻辑(分支/条件/策略)",
}

_ID_PREFIX = {
    "data_structure": "sa-d",
    "processing_flow": "sa-f",
    "control_logic": "sa-c",
}

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
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
    except Exception as e:
        logger.warning("[semantic] query nodes failed: %s", e)
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

def _comm_files(root: str, comm_key: str) -> List[str]:
    """组件范围 → 文件集合：经 KB architecture.model 取组件 owns。"""
    from .common import build_architecture_model
    try:
        model = build_architecture_model(root, None)
        for c in model.get("components") or []:
            if c.get("id") == comm_key:
                return [_norm_path(f) for f in (c.get("owns") or []) if f]
    except Exception:
        pass
    return []


def resolve_scope_files(root: str, scope_type: str, scope_key: str,
                       files: Optional[List[str]] = None,
                       symbols: Optional[List[str]] = None):
    """范围 → (files, symbols)。comm 解析为文件集合；symbols 保持符号名列表。"""
    st = scope_type or "project"
    if st == "files":
        return [_norm_path(f) for f in (files or []) if f], []
    if st == "symbols":
        return [], [s for s in (symbols or []) if s]
    if st == "comm":
        return _comm_files(root, scope_key), []
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


def collect_context(root: str, scope_type: str, scope_key: str,
                    files: Optional[List[str]] = None,
                    symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """收集范围符号上下文。返回 {files, symbols, nodes, table, edges, text, srcHash, source}。"""
    files, syms = resolve_scope_files(root, scope_type, scope_key, files, symbols)
    source = "live"
    conn = _open_cg(root)
    if conn is not None:
        source = "codegraph"
        nodes = _query_nodes(conn, files=files, symbols=syms)
        edges = _query_edges(conn, [n["id"] for n in nodes]) if nodes else []
        conn.close()
    else:
        nodes = _scan_live(root, files, syms)
        edges = []
    table = build_symbol_table(nodes)
    text = (
        f"文件集合({len(files)} 个): {', '.join(files[:40]) or '(全量)'}\n"
        f"符号清单:\n{_symbol_block(nodes)}\n"
        f"关系边:\n{_edge_lines(edges, table) or '(无)'}"
    )
    src_hash = hashlib.md5(json.dumps(
        [{"f": n["file_path"], "n": n["name"], "k": n["kind"],
          "s": n["start_line"], "e": n["end_line"], "sig": n.get("signature")}
         for n in nodes], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return {"files": files, "symbols": syms, "nodes": nodes, "table": table,
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


def _attach_step_refs(detail: dict, table: Dict[str, dict]) -> None:
    """把步骤/分支里的 symbols[] 解析进对应 astRefs。"""
    for i, s in enumerate(detail.get("steps") or []):
        if isinstance(s, dict):
            s["astRefs"] = resolve_ast_refs(s.get("symbols"), table)
    for i, b in enumerate(detail.get("branches") or []):
        if isinstance(b, dict):
            b["astRefs"] = resolve_ast_refs(b.get("symbols"), table)


# ── LLM 提取 ──────────────────────────────────────────────────

_ASSET_OUTPUT_SCHEMA = {
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
                    "name": {"type": "string", "description": "语义化名称(业务命名, 非符号名)"},
                    "desc": {"type": "string", "description": "语义描述(逻辑层级, 比伪代码更概括)"},
                    "fields": {"type": "array", "items": {"type": "object",
                                 "properties": {"name": {"type": "string"}, "type": {"type": "string"},
                                                "semantic": {"type": "string"}}}},
                    "relations": {"type": "array", "items": {"type": "object",
                                  "properties": {"target": {"type": "string"}, "type": {"type": "string"},
                                                 "semantic": {"type": "string"}}}},
                    "invariants": {"type": "array", "items": {"type": "string"}},
                    "trigger": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "object",
                              "properties": {"order": {"type": "integer"}, "semantic": {"type": "string"},
                                             "symbols": {"type": "array", "items": {"type": "string"}}}}},
                    "branches": {"type": "array", "items": {"type": "object",
                                "properties": {"condition": {"type": "string"}, "then": {"type": "string"},
                                               "else": {"type": "string"}, "semantic": {"type": "string"},
                                               "symbols": {"type": "array", "items": {"type": "string"}}}}},
                },
            },
        }
    },
}

_SYSTEM_PROMPT = (
    "你是代码语义化建模专家。基于给定的最新代码符号清单(文件/符号/行号/签名/docstring/关系边)，"
    "提取语义化的数据资产。\n"
    "语义资产比「组件/社区」粒度更细、贴近具体源码实现，比伪代码更概括抽象(逻辑层级)。\n"
    "三类资产:\n"
    "- data_structure: 语义化数据结构 —— 字段(fields)/关系(relations)/不变量(invariants)，锚定 class/interface/enum 节点\n"
    "- processing_flow: 语义化处理流程 —— 触发(trigger)/步骤序列(steps，每步引用 symbol)/不变量，锚定跨函数调用链\n"
    "- control_logic: 语义化控制逻辑 —— 分支(branches: condition/then/else，每分支引用 symbol)/不变量，锚定决策函数\n\n"
    "约束(重要):\n"
    "1. 只输出 JSON 对象 {\"assets\": [...]}，不要 Markdown 代码块、不要解释。\n"
    "2. 每个资产必须真实来源于清单中的符号; steps/branches 的 symbols 必须是清单中的符号名，不得臆造。\n"
    "3. name 用业务语义命名(如「支付结算聚合」「鉴权校验链」)，不是符号名。\n"
    "4. desc 概括其逻辑作用与边界，比伪代码抽象。\n"
    "5. 建议提取 2~6 个资产；无匹配数据时返回空数组。"
)


def _llm_extract(root: Optional[str], project: Optional[str],
                 context_text: str, model_id: Optional[str],
                 max_assets: int = 6) -> List[dict]:
    """LLM 结构化提取。LLM 不可用/解析失败返回空列表(调用方启发式兜底)。"""
    from .req_agent import llm_sync
    res = llm_sync(
        [{"role": "system", "content": _SYSTEM_PROMPT},
         {"role": "user", "content": context_text}],
        mode="structured", output_schema=_ASSET_OUTPUT_SCHEMA,
        max_tokens=2000, model_id=model_id,
    )
    if not res:
        return []
    output = res.get("output")
    if not isinstance(output, dict):
        return []
    assets = output.get("assets") or []
    return [a for a in assets if isinstance(a, dict) and a.get("name") and a.get("kind") in SEMANTIC_KINDS][:max_assets]


# ── 启发式降级 ────────────────────────────────────────────────

def _heuristic_extract(kind: str, ctx: Dict[str, Any]) -> List[dict]:
    nodes = ctx.get("nodes") or []
    out: List[dict] = []
    if kind == "data_structure":
        for n in nodes:
            if n.get("kind") not in ("class", "interface", "enum", "struct", "component"):
                continue
            doc = (n.get("docstring") or "").strip()
            desc = doc or f"「{n['name']}」逻辑数据结构，位于 {n['file_path']}:{n['start_line']}。"
            out.append({"kind": kind, "name": n["name"], "desc": desc,
                        "detail": {"fields": [], "relations": [], "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
    elif kind == "processing_flow":
        for n in nodes:
            if n.get("kind") not in ("function", "method", "route"):
                continue
            sig = n.get("signature") or ""
            doc = (n.get("docstring") or "").strip()
            desc = doc or f"处理流程「{n['name']}」，签名 ({sig})，位于 {n['file_path']}:{n['start_line']}。"
            out.append({"kind": kind, "name": n["name"], "desc": desc,
                        "detail": {"trigger": "", "steps": [], "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
    elif kind == "control_logic":
        for n in nodes:
            if n.get("kind") not in ("function", "method", "route"):
                continue
            doc = (n.get("docstring") or "").strip()
            desc = doc or f"控制逻辑「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。"
            out.append({"kind": kind, "name": n["name"], "desc": desc,
                        "detail": {"branches": [], "invariants": []},
                        "astRefs": [_node_to_ref(n)]})
    return out[:12]


# ── 持久化(增量 change) ───────────────────────────────────────

def _save_assets(project_id: str, scope_type: str, scope_key: str,
                 assets: List[dict], ctx: Dict[str, Any]) -> List[dict]:
    now = _ts()
    existing = {a["name"]: a for a in store.SemanticAssetsStore.find_by_scope(
        project_id, scope_type, scope_key)}
    saved: List[dict] = []
    for a in assets:
        detail = a.get("detail") or {}
        for k in ("fields", "relations", "invariants", "trigger",
                  "steps", "branches"):
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
        payload = {
            "projectId": project_id, "kind": a["kind"],
            "name": a["name"], "desc": a.get("desc") or "",
            "detail": detail, "astRefs": ast_refs[:40],
            "scopeType": scope_type, "scopeKey": scope_key,
            "source": ctx.get("source") or "live",
            "srcHash": ctx.get("srcHash") or "",
            "meta": {"componentId": scope_key if scope_type == "comm" else ""},
            "updatedAt": now,
        }
        old = existing.pop(a["name"], None)
        if old:
            payload["id"] = old["id"]
            payload["change"] = "modified" if (ctx.get("srcHash") and ctx.get("srcHash") != old.get("srcHash")) else "same"
            store.SemanticAssetsStore.update(old["id"], payload)
        else:
            payload["id"] = store.next_id(_ID_PREFIX.get(a["kind"], "sa-a"))
            payload["change"] = "added"
            payload["createdAt"] = now
            store.SemanticAssetsStore.create(payload)
        saved.append(store.SemanticAssetsStore.get(payload["id"]) or payload)
    for name, old in existing.items():
        store.SemanticAssetsStore.update(old["id"], {"status": "stale", "updatedAt": now})
    return saved


# ── 顶层提取入口 ──────────────────────────────────────────────

def extract_scope(root: Optional[str], project: Optional[str],
                  scope_type: str = "project", scope_key: str = "",
                  files: Optional[List[str]] = None,
                  symbols: Optional[List[str]] = None,
                  kinds: Optional[List[str]] = None,
                  model_id: Optional[str] = None,
                  use_llm: bool = True) -> Dict[str, Any]:
    """按范围提取语义资产并落库。返回 {assets, source, degraded, count}。

    degraded=True 表示 LLM 不可用(启发式兜底) 或 codegraph 缺失(轻量扫描)。
    """
    root = resolve_root(root, project)
    if not root:
        return {"assets": [], "source": "none", "degraded": True, "count": 0}
    kinds = [k for k in (kinds or []) if k in SEMANTIC_KINDS] or list(SEMANTIC_KINDS)
    ensure_synced(root)
    ctx = collect_context(root, scope_type, scope_key, files, symbols)
    pid = project_id_for(root, project)
    degraded = ctx.get("source") != "codegraph"
    all_assets: List[dict] = []
    if use_llm:
        try:
            llm_assets = _llm_extract(root, project, ctx.get("text") or "", model_id)
        except Exception as e:
            logger.warning("[semantic] llm extract failed: %s", e)
            llm_assets = []
        if llm_assets:
            degraded = degraded or False
            all_assets = llm_assets
    if not all_assets:
        degraded = True
        for k in kinds:
            all_assets += _heuristic_extract(k, ctx)
    saved = _save_assets(pid, scope_type or "project", scope_key or "_", all_assets, ctx)
    return {"assets": saved, "source": ctx.get("source"), "degraded": degraded,
            "count": len(saved)}


def extract_all(root: Optional[str], project: Optional[str],
                kinds: Optional[List[str]] = None,
                model_id: Optional[str] = None,
                use_llm: bool = True,
                max_components: int = 12) -> Dict[str, Any]:
    """批处理: 对 KB 组件(或全项目)逐一提取。并发受限，简单串行 + 累计。"""
    root = resolve_root(root, project)
    if not root:
        return {"assets": [], "count": 0, "components": 0}
    from .common import build_architecture_model
    comps = []
    try:
        comps = (build_architecture_model(root, None) or {}).get("components") or []
    except Exception:
        comps = []
    assets: List[dict] = []
    done = 0
    for c in comps[:max_components]:
        try:
            res = extract_scope(root, project, "comm", c.get("id") or "",
                                kinds=kinds, model_id=model_id, use_llm=use_llm)
            assets += res.get("assets") or []
            done += 1
        except Exception as e:
            logger.warning("[semantic] extract component %s failed: %s", c.get("id"), e)
    # 无 KB 组件时按全项目提取一次
    if not comps:
        res = extract_scope(root, project, "project", kinds=kinds,
                            model_id=model_id, use_llm=use_llm)
        assets += res.get("assets") or []
    return {"assets": assets, "count": len(assets), "components": done}


def refresh_scope(root: Optional[str], project: Optional[str],
                  scope_type: str, scope_key: str,
                  model_id: Optional[str] = None) -> Dict[str, Any]:
    """增量刷新: 对已提取范围重跑提取，按 src_hash 判定 change。"""
    return extract_scope(root, project, scope_type, scope_key,
                         model_id=model_id, use_llm=True)


# ── 上下文展开(任务执行/需求设计注入) ─────────────────────────

_SA_ID_RE = re.compile(r"\bsa-[dcf]-\d+\b")


def context_block_for(root: Optional[str], project: Optional[str],
                      context: Optional[List[str]] = None,
                      max_assets: int = 6) -> str:
    """从上下文条目中识别 `sa-*` 语义资产 id → 展开为语义块(供 coding-agent 注入)。

    返回追加文本(无资产则空串)。语义块含 名/kind/描述/AST 锚点，锁定「改哪里」。
    """
    if not context:
        return ""
    ids = []
    for c in context:
        ids += _SA_ID_RE.findall(c or "")
    ids = list(dict.fromkeys(ids))
    if not ids:
        return ""
    block = ["\n## 语义数据资产上下文(改动锚点)"]
    for i in ids[:max_assets]:
        a = store.SemanticAssetsStore.get(i)
        if not a or a.get("status") != "active":
            continue
        detail = a.get("detail") or {}
        line = f"- {a.get('name')}({a.get('kind')}): {a.get('desc') or ''}"
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
           text: str = "", kind: str = "", limit: int = 20) -> List[dict]:
    pid = project_id_for(root, project)
    return store.SemanticAssetsStore.search(pid, text, kind, limit)


def detail(asset_id: str) -> Optional[dict]:
    return store.SemanticAssetsStore.get(asset_id)


def mappings(asset_id: str) -> List[dict]:
    a = store.SemanticAssetsStore.get(asset_id)
    if not a:
        return []
    refs = a.get("astRefs") or []
    return [{"id": f"sa-{asset_id}-{i}", "targetType": "semantic",
             "targetId": asset_id, "targetName": a.get("name") or "",
             "file": r.get("file", ""), "line": f"L{r.get('startLine') or 0}",
             "level": "logical", "note": r.get("symbol", "")}
            for i, r in enumerate(refs)]


# ── REST ──────────────────────────────────────────────────────

def _scope(body: dict) -> tuple:
    scope = body.get("scope") or {}
    return (scope.get("type") or body.get("scopeType") or "project",
            scope.get("key") or body.get("scopeKey") or "",
            scope.get("files") or body.get("files") or [],
            scope.get("symbols") or body.get("symbols") or [])


@router.get("/kb/semantic/search")
async def api_search(q: str = "", kind: str = "",
                     root: Optional[str] = None, project: Optional[str] = None,
                     limit: int = 20):
    items = search(root, project, q, kind, limit)
    return ok(items)


@router.get("/kb/semantic/mappings")
async def api_mappings(root: Optional[str] = None, project: Optional[str] = None,
                       asset_ids: str = ""):
    ids = [x for x in (asset_ids or "").split(",") if x.strip()]
    out = []
    for i in ids:
        out += mappings(i.strip())
    return ok(out)


@router.get("/kb/semantic/{asset_id}")
async def api_detail(asset_id: str, root: Optional[str] = None, project: Optional[str] = None):
    a = detail(asset_id)
    if not a:
        return err(404, f"语义资产 {asset_id} 不存在")
    return ok(a)


@router.post("/kb/semantic/extract")
async def api_extract(request: Request):
    body = await request.json()
    st, sk, files, symbols = _scope(body)
    res = extract_scope(body.get("root"), body.get("project"),
                        st, sk, files, symbols,
                        kinds=body.get("kinds"),
                        model_id=body.get("modelId"))
    return ok(res)


@router.post("/kb/semantic/extractAll")
async def api_extract_all(request: Request):
    body = await request.json()
    res = extract_all(body.get("root"), body.get("project"),
                      kinds=body.get("kinds"),
                      model_id=body.get("modelId"),
                      use_llm=body.get("useLlm", True),
                      max_components=int(body.get("maxComponents") or 12))
    return ok(res)


@router.post("/kb/semantic/refresh")
async def api_refresh(request: Request):
    body = await request.json()
    res = refresh_scope(body.get("root"), body.get("project"),
                        body.get("scopeType") or body.get("scope", {}).get("type", "project"),
                        body.get("scopeKey") or body.get("scope", {}).get("key", ""),
                        model_id=body.get("modelId"))
    return ok(res)
