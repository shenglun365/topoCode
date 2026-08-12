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


def _norm_cache_symbol(file: str, lang: str, s: dict) -> dict:
    """KB parseFileAst 返回的 camelCase 符号 → 与 codegraph 节点同构(snake_case)。"""
    name = (s.get("name") or "").strip()
    if not name:
        return None
    return {
        "id": f"cache:{file}::{name}::{int(s.get('startLine') or 0)}",
        "kind": s.get("kind") or "symbol",
        "name": name,
        "qualified_name": s.get("qualifiedName") or name,
        "file_path": file,
        "language": lang,
        "start_line": int(s.get("startLine") or 0),
        "end_line": int(s.get("endLine") or 0),
        "start_column": int(s.get("startCol") or 0),
        "end_column": int(s.get("endCol") or 0),
        "signature": s.get("signature") or "",
        "docstring": s.get("docstring") or "",
        "return_type": "",
    }


def _collect_via_cache(root: str, project: Optional[str],
                       files: List[str], syms: List[str]):
    """无 codegraph 时的 AST 缓存层取数(要求③)：缓存命中 → KB 解析 → live 扫描。"""
    pid = project_id_for(root, project)
    nodes: List[dict] = []
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
        cached = store.AstCacheStore.get(pid, rel)
        if cached and cached.get("contentHash") and cached.get("contentHash") == h:
            if cached.get("source") in ("codegraph", "kb"):
                source = cached.get("source")
            for s in cached.get("symbols") or []:
                n = _norm_cache_symbol(rel, cached.get("language") or "", s)
                if n:
                    nodes.append(n)
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
    logger.info("[semantic] cache 兜底: 文件数=%d 缓存未命中=%s source=%s 共取节点=%d",
                len(files or []), miss or "-", source, len(nodes))
    return nodes, [], source


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
    if conn is not None:
        source = "codegraph"
        nodes = _query_nodes(conn, files=files, symbols=syms)
        edges = _query_edges(conn, [n["id"] for n in nodes]) if nodes else []
        conn.close()
    else:
        # 无 codegraph → AST 缓存层(KB 解析优先，live 扫描兜底)
        nodes, edges, source = _collect_via_cache(root, project, files, syms)
    logger.info("[semantic] collect_context source=%s nodes=%d edges=%d",
                source, len(nodes), len(edges))
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
    return {"root": root, "files": files, "symbols": syms, "nodes": nodes, "table": table,
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
    "data_structure": "data_structure",
    "数据结构": "data_structure",
    "datastructure": "data_structure",
    "data structure": "data_structure",
    "data-structure": "data_structure",
    "data_structure类": "data_structure",
    "processing_flow": "processing_flow",
    "处理流程": "processing_flow",
    "processingflow": "processing_flow",
    "process flow": "processing_flow",
    "process-flow": "processing_flow",
    "process": "processing_flow",
    "processing": "processing_flow",
    "流程": "processing_flow",
    "控制逻辑": "control_logic",
    "control_logic": "control_logic",
    "controllogic": "control_logic",
    "control logic": "control_logic",
    "control-logic": "control_logic",
    "logic": "control_logic",
    "逻辑": "control_logic",
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
      - 锚点: source_symbols[] + anchor_symbol → astRefs(可解析则真实节点，否则记录警告)
    无法归一化(缺 kind/name)返回 None。
    """
    if not isinstance(a, dict):
        return None
    kind = _normalize_kind(a.get("kind") or a.get("type"))
    name = (a.get("name") or "").strip()
    if not kind or not name:
        return None
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

    # 锚点：source_symbols[] + anchor_symbol → astRefs
    ast_refs: List[dict] = []
    src_syms = a.get("source_symbols") or []
    if not isinstance(src_syms, list):
        src_syms = [src_syms] if isinstance(src_syms, str) else []
    for sym in src_syms:
        if not sym:
            continue
        node = table.get(str(sym).strip())
        if node:
            ast_refs.append(_node_to_ref(node))
        else:
            logger.warning("[semantic] LLM 资产符号无法解析(锚点忽略): %s", sym)
    anchor = a.get("anchor_symbol") or a.get("anchor") or ""
    if anchor:
        _file, _, _sym = str(anchor).partition("::")
        _file = (_file or "").strip()
        _sym = (_sym or "").strip()
        node = table.get(_sym) if _sym else None
        if node:
            ast_refs.append(_node_to_ref(node))
        elif _sym:
            logger.warning("[semantic] LLM 资产锚点符号无法解析(忽略): %s", anchor)
        elif _file:
            logger.warning("[semantic] LLM 资产锚点仅文件名无符号(忽略): %s", anchor)
    ast_refs = list({json.dumps(r, ensure_ascii=False, sort_keys=True): r for r in ast_refs}.values())

    return {"kind": kind, "name": name, "desc": (a.get("desc") or "").strip(),
            "detail": detail, "astRefs": ast_refs}


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
                    "source_symbols": {"type": "array", "items": {"type": "string"},
                                       "description": "锚定本资产的清单符号名列表(必须来自符号清单，用于定位真实代码)"},
                    "anchor_symbol": {"type": "string",
                                      "description": "主要锚定符号(可选，格式: 符号名 或 文件::符号名)"},
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
    "三类资产(字段名必须严格用 kind，值只能是 data_structure / processing_flow / control_logic，"
    "禁止翻译成中文或使用 type 等其他字段名):\n"
    "- data_structure: 语义化数据结构 —— 字段(fields)/关系(relations)/不变量(invariants)，锚定 class/interface/enum 节点\n"
    "- processing_flow: 语义化处理流程 —— 触发(trigger)/步骤序列(steps)/不变量，锚定跨函数调用链\n"
    "- control_logic: 语义化控制逻辑 —— 分支(branches: condition/then/else)/不变量，锚定决策函数\n\n"
    "约束(重要):\n"
    "1. 只输出 JSON 对象 {\"assets\": [...]}，不要 Markdown 代码块、不要解释。\n"
    "2. 每个资产必须真实来源于清单中的符号; steps/branches 的 symbols 必须是清单中的符号名，不得臆造。\n"
    "3. name 用业务语义命名(如「支付结算聚合」「鉴权校验链」)，不是符号名。\n"
    "4. desc 概括其逻辑作用与边界，比伪代码抽象。\n"
    "5. 建议提取 2~6 个资产；无匹配数据时返回空数组。\n"
    "6. 每个资产建议填写 source_symbols(清单中真实符号名数组)或 anchor_symbol(主要符号名)，"
    "帮助定位其真实代码位置。"
)


def _llm_extract(root: Optional[str], project: Optional[str],
                 context_text: str, model_id: Optional[str],
                 table: Optional[Dict[str, dict]] = None,
                 max_assets: int = 6) -> List[dict]:
    """LLM 结构化提取。LLM 不可用/解析失败返回空列表(调用方启发式兜底)。

    LLM 输出经 `_norm_llm_asset` 宽容归一化(兼容 type/kind、单复数字段、中文变体)。
    """
    from .req_agent import llm_sync
    table = table or {}
    logger.info("[semantic] llm 提取: model=%s text_len=%d", model_id or "(默认)", len(context_text or ""))
    res = llm_sync(
        [{"role": "system", "content": _SYSTEM_PROMPT},
         {"role": "user", "content": context_text}],
        mode="structured", output_schema=_ASSET_OUTPUT_SCHEMA,
        max_tokens=2000, model_id=model_id,
    )
    if not res:
        logger.warning("[semantic] llm 提取返回空/失败(将走启发式兜底)")
        return []
    output = res.get("output")
    if not isinstance(output, dict):
        logger.warning("[semantic] llm 提取输出非 dict: %r(将走启发式兜底)", type(output).__name__)
        return []
    assets = output.get("assets") or []
    valid: List[dict] = []
    dropped = 0
    for a in assets:
        norm = _norm_llm_asset(a, table)
        if norm:
            valid.append(norm)
        else:
            dropped += 1
        if len(valid) >= max_assets:
            break
    logger.info("[semantic] llm 提取输出: 原始=%d 有效=%d 丢弃=%d",
                len(assets or []), len(valid), dropped)
    if assets and not valid:
        logger.warning("[semantic] llm 提取资产全部未通过归一化: 首个键=%s 首个type=%r",
                       list((assets[0] or {}).keys()) if isinstance(assets[0], dict) else "-",
                       (assets[0] or {}).get("type") if isinstance(assets[0], dict) else None)
    return valid


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


def _save_assets(project_id: str, scope_type: str, scope_key: str,
                 assets: List[dict], ctx: Dict[str, Any]) -> List[dict]:
    now = _ts()
    root = ctx.get("root") or ""
    existing = {a["name"]: a for a in store.SemanticAssetsStore.find_by_scope(
        project_id, scope_type, scope_key, include_deleted=True)}
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
        meta = {"componentId": scope_key if scope_type == "comm" else ""}
        if scope_type == "files":
            meta["files"] = (ctx.get("files") or [])[:200]
        if scope_type == "symbols":
            meta["symbols"] = (ctx.get("symbols") or [])[:200]
        payload = {
            "projectId": project_id, "kind": a["kind"],
            "name": a["name"], "desc": a.get("desc") or "",
            "detail": detail, "astRefs": ast_refs[:40],
            "scopeType": scope_type, "scopeKey": scope_key,
            "source": ctx.get("source") or "live",
            "srcHash": ctx.get("srcHash") or "",
            "meta": meta,
            "anchorHashes": _anchor_hashes(root, ast_refs[:40]),
            "needsUpdate": 0,
            "lastCheckedAt": now,
            "updatedAt": now,
        }
        old = existing.pop(a["name"], None)
        if old:
            payload["id"] = old["id"]
            payload["change"] = "modified" if (ctx.get("srcHash") and ctx.get("srcHash") != old.get("srcHash")) else "same"
            if old.get("status") == "deleted":
                payload["status"] = "active"   # 软删后重新生成 → 恢复
            store.SemanticAssetsStore.update(old["id"], payload)
        else:
            payload["id"] = store.next_id(_ID_PREFIX.get(a["kind"], "sa-a"))
            payload["change"] = "added"
            payload["status"] = "active"
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
        "[semantic] extract_scope 范围 %s(%s) kinds=%s files=%d symbols=%d "
        "source=%s nodes=%d codegraph_synced=%s",
        scope_type, scope_key or "-", kinds, len(ctx.get("files") or []),
        len(ctx.get("symbols") or []), ctx.get("source"), len(ctx.get("nodes") or []), synced)
    all_assets: List[dict] = []
    llm_count = 0
    if use_llm:
        try:
            llm_assets = _llm_extract(root, project, ctx.get("text") or "", model_id,
                                      table=ctx.get("table") or {})
            llm_count = len(llm_assets or [])
        except Exception as e:
            logger.warning("[semantic] llm extract failed: %s", e, exc_info=True)
            llm_assets = []
        if llm_assets:
            degraded = degraded or False
            all_assets = llm_assets
    heur_counts: Dict[str, int] = {}
    if not all_assets:
        degraded = True
        for k in kinds:
            _before = len(all_assets)
            all_assets += _heuristic_extract(k, ctx)
            heur_counts[k] = len(all_assets) - _before
    logger.info(
        "[semantic] extract_scope 结果: scope=%s(%s) llm=%d heuristic=%s "
        "degraded=%s saved=%d text_len=%d",
        scope_type, scope_key or "-", llm_count, heur_counts or "-",
        degraded, len(all_assets), len(ctx.get("text") or ""))
    saved = _save_assets(pid, scope_type or "project", scope_key or "_", all_assets, ctx)
    return {"assets": saved, "source": ctx.get("source"), "degraded": degraded,
            "count": len(saved)}


def extract_all(root: Optional[str], project: Optional[str],
                kinds: Optional[List[str]] = None,
                model_id: Optional[str] = None,
                use_llm: bool = True,
                max_components: int = 12) -> Dict[str, Any]:
    """批处理: 对组件目录(跨 INCLUDE/CALL × L0/L1，与组件列表一致)逐一提取。
    并发受限，简单串行 + 累计。无组件时按全项目提取一次。"""
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
    logger.info("[semantic] extract_all 组件目录: 组件总数=%d 实际提取=%d", len(comps), min(len(comps), max_components))
    assets: List[dict] = []
    done = 0
    for c in comps[:max_components]:
        try:
            res = extract_scope(root, project, "comm", c.get("id") or "",
                                kinds=kinds, model_id=model_id, use_llm=use_llm)
            assets += res.get("assets") or []
            done += 1
        except Exception as e:
            logger.warning("[semantic] extract component %s failed: %s", c.get("id"), e, exc_info=True)
    # 无 KB 组件时按全项目提取一次
    if not comps:
        logger.info("[semantic] extract_all 无组件, 按全项目提取一次")
        res = extract_scope(root, project, "project", kinds=kinds,
                            model_id=model_id, use_llm=use_llm)
        assets += res.get("assets") or []
    logger.info("[semantic] extract_all 完成: 组件=%d 资产=%d", done, len(assets))
    return {"assets": assets, "count": len(assets), "components": done}


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


def _component_asset_ids(pid: str, comp_files: Dict[str, set],
                         comp_ids: List[str], include_other: bool) -> List[str]:
    """选定组件范围 → 资产 id 集合(comm 范围 + 文件归属双重匹配)。

    - 资产 scope_type='comm' 且 scope_key ∈ comp_ids → 命中
    - 资产首锚定文件属于任一选定组件的文件集 → 命中
    - include_other 且文件不属任何组件(「其它」桶) → 命中
    comp_ids 为空 = 全部组件(此时 include_other 决定是否含未列组件的文件)。
    """
    ids: set = set()
    comp_set = set(comp_ids)
    sel_files: set = set()
    all_files: set = set()
    for cid, files in comp_files.items():
        all_files |= files
        if not comp_set or cid in comp_set:
            sel_files |= files
    for a in store.SemanticAssetsStore.all_status(pid, limit=4000):
        aid = a.get("id")
        if not aid:
            continue
        if a.get("scopeType") == "comm" and (a.get("scopeKey") or "") in comp_set:
            ids.add(aid)
            continue
        f = _norm_path((a.get("astRefs") or [{}])[0].get("file") or "")
        if not f:
            continue
        if f in sel_files or (include_other and f not in all_files):
            ids.add(aid)
    return sorted(i for i in ids if i)


def batch_manage(root: Optional[str], project: Optional[str],
                 action: str, comp_ids: Optional[List[str]] = None,
                 include_other: bool = False,
                 kinds: Optional[List[str]] = None,
                 model_id: Optional[str] = None) -> Dict[str, Any]:
    """批量管理组件范围语义资产。

    - extract: 对每个组件(未指定则全部)按 comm 范围提取并落库。
    - clear:   软删选定组件范围内的语义资产。
    - update:  增量更新选定组件范围内的过期(stale/needsUpdate)资产。

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
        logger.info("[semantic] batch extract 开始: comp_ids=%d kinds=%s", len(comp_ids), kinds)
        done, total = 0, 0
        for cid in comp_ids:
            try:
                res = extract_scope(root, project, "comm", cid, kinds=kinds,
                                    model_id=model_id, use_llm=True)
                total += res.get("count") or 0
                done += 1
                if not (res.get("count") or 0):
                    logger.warning("[semantic] batch extract %s 产出 0 个资产 (source=%s)",
                                   cid, res.get("source"))
            except Exception as e:
                logger.warning("[semantic] batch extract %s failed: %s", cid, e, exc_info=True)
        logger.info("[semantic] batch extract 完成: 组件=%d 资产=%d", done, total)
        return {"action": action, "count": total, "components": done,
                "cleared": [], "updated": []}
    if action not in ("clear", "update"):
        return {"action": action, "count": 0, "cleared": [], "updated": []}
    pid = project_id_for(root, project)
    comp_files = _component_file_map(root, project)
    ids = _component_asset_ids(pid, comp_files, comp_ids, include_other)
    cleared, updated = [], []
    if action == "clear":
        for aid in ids:
            a = store.SemanticAssetsStore.get(aid)
            if not a or a.get("status") == "deleted":
                continue
            try:
                store.SemanticAssetsStore.mark_deleted(aid, change="removed")
                cleared.append(aid)
            except Exception as e:
                logger.warning("[semantic] batch clear %s failed: %s", aid, e)
    else:  # update
        for aid in ids:
            a = store.SemanticAssetsStore.get(aid)
            if not a or (a.get("status") == "active" and not a.get("needsUpdate")):
                continue
            try:
                handle_stale_asset(aid, root, project, model_id=model_id)
                updated.append(aid)
            except Exception as e:
                logger.warning("[semantic] batch update %s failed: %s", aid, e)
    return {"action": action, "count": len(ids), "components": len(comp_ids) or None,
            "cleared": cleared, "updated": updated}


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
    # 刷新失败(LLM/解析均不可用) → 软删 + 启发式重新生成(离线兜底)
    store.SemanticAssetsStore.mark_deleted(asset_id)
    try:
        ctx = collect_context(root, scope_type, scope_key,
                              files=scope_files, symbols=scope_symbols,
                              project=project)
        pid = project_id_for(root, project)
        heur = []
        for k in SEMANTIC_KINDS:
            heur += _heuristic_extract(k, ctx)
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

_SA_ID_RE = re.compile(r"\bsa-[dcf]-\d+\b")


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
           text: str = "", kind: str = "", limit: int = 20, offset: int = 0,
           scopes: Optional[List[str]] = None) -> List[dict]:
    _lazy_reconcile(root, project)
    pid = project_id_for(root, project)
    return store.SemanticAssetsStore.search(pid, text, kind, limit, offset, scopes=scopes)


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
                     limit: int = 100, offset: int = 0, scope: str = ""):
    """分页检索：返回 items + total(超出 limit 翻页用)。

    scope: 逗号分隔的组件范围(scope_key 精确匹配)；空=全部。
    """
    _lazy_reconcile(root, project)
    pid = project_id_for(root, project)
    scopes = [s.strip() for s in (scope or "").split(",") if s.strip()] or None
    items = store.SemanticAssetsStore.search(pid, q, kind, limit, offset, scopes=scopes)
    total = store.SemanticAssetsStore.count(pid, q, kind, scopes=scopes)
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
    logger.info("[semantic] /kb/semantic/extract 请求: type=%s key=%s files=%d symbols=%d kinds=%s",
                st, sk or "-", len(files or []), len(symbols or []), body.get("kinds"))
    res = extract_scope(body.get("root"), body.get("project"),
                        st, sk, files, symbols,
                        kinds=body.get("kinds"),
                        model_id=body.get("modelId"))
    if not (res.get("count") or 0):
        logger.warning("[semantic] /kb/semantic/extract 产出 0: type=%s key=%s source=%s degraded=%s",
                       st, sk or "-", res.get("source"), res.get("degraded"))
    return ok(res)


@router.post("/kb/semantic/extractAll")
async def api_extract_all(request: Request):
    body = await request.json()
    logger.info("[semantic] /kb/semantic/extractAll 请求: kinds=%s model=%s max_components=%s",
                body.get("kinds"), body.get("modelId"), body.get("maxComponents"))
    res = extract_all(body.get("root"), body.get("project"),
                      kinds=body.get("kinds"),
                      model_id=body.get("modelId"),
                      use_llm=body.get("useLlm", True),
                      max_components=int(body.get("maxComponents") or 12))
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


@router.post("/kb/semantic/batch")
async def api_batch(request: Request):
    """批量管理选定组件范围的语义资产(extract/clear/update)。"""
    body = await request.json()
    logger.info("[semantic] /kb/semantic/batch 请求: action=%s components=%d include_other=%s",
                body.get("action"), len(body.get("components") or []), body.get("includeOther"))
    res = batch_manage(body.get("root"), body.get("project"),
                       body.get("action") or "extract",
                       comp_ids=body.get("components") or [],
                       include_other=bool(body.get("includeOther")),
                       kinds=body.get("kinds"),
                       model_id=body.get("modelId"))
    logger.info("[semantic] /kb/semantic/batch 响应: action=%s count=%s components=%s",
                body.get("action"), res.get("count"), res.get("components"))
    return ok(res)
