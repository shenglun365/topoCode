"""semantic_assets 拆分模块（A1 修正：纯移动，逻辑零改动）。

原 semantic_assets.py 5555 行 god-file 按段拆出；本模块由构建脚本生成段内容，
跨模块引用为显式 import。每步拆分均跑 28 个后端测试文件保护。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import store
from ..common import _ts, err, ok  # noqa: F401

logger = logging.getLogger(__name__)

from .paths import project_id_for
from .codegraph import _query_edges, _query_nodes
from .symbols import open_symbol_conn, close_symbol_conn
from .scope import resolve_scope_files
from .incremental import _cache_content_hash


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
    """调用/包含边(源/目标符号名)，供流程/控制提取。

    180 行额度内 calls/contains/imports 优先(流程提取主证据)，
    references/assigns/passes 等补充类别填剩余额度。
    """
    name_of = {n["id"]: (n["qualified_name"] or n["name"]) for n in table.values()}
    seen, out = set(), []
    prim, sec = [], []
    for e in edges:
        s = name_of.get(e["source"], e["source"])
        t = name_of.get(e["target"], e["target"])
        key = (e["kind"], s, t)
        if key in seen:
            continue
        seen.add(key)
        line = f"- {s} {e['kind']} {t}"
        (prim if e["kind"] in ("calls", "contains", "imports") else sec).append(line)
    out = prim + sec
    return "\n".join(out[:180])


def _ordered_call_lines(nodes: List[dict], edges: List[dict],
                        table: Dict[str, dict], limit_funcs: int = 60,
                        limit_calls: int = 12) -> str:
    """按函数分组的有序调用序列(边 line 升序)，供实现层 process/decision 提取。

    仅覆盖带 line 信息的 calls 边；无 line 时输出为空(调用方回退普通边清单)。
    """
    name_of = {n["id"]: (n.get("qualified_name") or n.get("name")) for n in table.values()}
    calls_by_src: Dict[str, List[tuple]] = {}
    has_line = False
    for e in edges or []:
        if e.get("kind") != "calls" or not e.get("target"):
            continue
        ln = e.get("line")
        if isinstance(ln, int) and ln > 0:
            has_line = True
        calls_by_src.setdefault(e.get("source") or "", []).append(
            (ln if isinstance(ln, int) else 0, e["target"]))
    if not has_line:
        return ""
    fn_ids = [n.get("id") for n in nodes or []
              if (n.get("kind") or "") in ("function", "method", "route")]
    lines: List[str] = []
    for fid in fn_ids:
        seq = calls_by_src.get(fid)
        if not seq:
            continue
        seq.sort()
        name = name_of.get(fid, fid)
        calls = []
        seen_t: set = set()
        for ln, t in seq:
            tn = name_of.get(t, t)
            if tn in seen_t:
                continue
            seen_t.add(tn)
            calls.append(f"L{ln} {tn}" if ln else tn)
            if len(calls) >= limit_calls:
                break
        lines.append(f"- {name}: " + " → ".join(calls))
        if len(lines) >= limit_funcs:
            break
    return "\n".join(lines)


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


_REF_EDGE_KINDS = {"calls", "extends", "imports", "references", "instantiates", "implements",
                   "assigns", "passes"}
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


_SKIP_DIRS = {".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__",
              ".DS_Store", "node_modules", "dist", "build", ".venv", "venv"}


def _project_source_files(root: str, cap: int = 500) -> List[str]:
    """降级 project 范围的本地源码文件枚举(无 codegraph/KB 清单可依时)。

    口径单源：可提取判定复用 compare._extractable(与 KB 扫描 walker 同一
    _CODE_EXTS)；忽略目录与 dirs._SKIP 同口径。路径相对 root、稳定排序。
    上限 cap(默认 500，与 compare._CAP_PENDING 同量级；下游循环另有 120/趟截断)。
    """
    from .compare import _extractable
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS
                       and not d.startswith(".")]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            rel = rel.replace(os.sep, "/")
            if _extractable(rel):
                out.append(rel)
                if len(out) >= cap:
                    out.sort()
                    return out
    out.sort()
    return out


def _collect_via_cache(root: str, project: Optional[str],
                       files: List[str], syms: List[str]):
    """无 codegraph 时的 AST 缓存层取数(要求③)：缓存命中 → KB 解析 → live 扫描。

    返回 (nodes, edges, source, impl_by_file)。KB 路径经 `_rebuild_edges_from_refs`
    从文件级 refs 重建统一边(与 codegraph `_query_edges` 同构)，保证下游
    (Rule 判定/流程/字段)效果一致；impl_by_file 为实现细节(语句/路由/常量)。
    """
    if not root:
        # root 不可解析(缺 root/project 参数) → 无法读文件/扫描，返回空上下文防 TypeError。
        logger.warning("[semantic] _collect_via_cache: root 未解析, 返回空上下文")
        return [], [], "none", {}
    if not files:
        # 重定位 P-A(能力对齐修复): project 范围在 resolve_scope_files 恒返回空清单
        # (全量语义由 codegraph 路径承载)，降级路径此前零文件 → 分析全空(cv-258 实测)。
        # 本地枚举补上(非新建能力: 只补清单，解析/提取全走既有三级源)。
        files = _project_source_files(root)
        if files:
            logger.info("[semantic] 降级 project 范围本地枚举源码文件: %d", len(files))
    pid = project_id_for(root, project)
    nodes: List[dict] = []
    # 每文件符号/refs 分组，供重建边(行区间归属必须限定单文件，防跨文件误归)。
    per_file: Dict[str, dict] = {}
    source = "live"
    if syms:
        # 符号范围无 codegraph 无法精确定位文件 → 退化为 live 全量扫描(有文件列表时)
        if files:
            nodes = _scan_live(root, files, syms)
        return nodes, [], source, {}
    miss: List[str] = []
    for rel in (files or [])[:120]:
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            logger.info("[semantic] cache 文件不存在, 跳过: %s", rel)
            continue
        h = _cache_content_hash(root, rel)
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
            impl = _impl_from_row(cached)
            if impl is None:
                impl = _fetch_impl_for_file(root, project, rel)  # 旧行补取
            if impl and any(impl.values()):
                pf["impl"] = impl
            per_file[rel] = pf
            continue
        miss.append(rel)
        # 缓存未命中/已过期 → KB 只读解析(不落 KB，写入 architect 缓存)
        kb = _kb_parse_file(root, rel, impl=True)
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
            impl = _impl_from_kb(kb)
            if impl and any(impl.values()):
                pf["impl"] = impl
            per_file[rel] = pf
            store.AstCacheStore.upsert(pid, rel, {
                "contentHash": h, "language": kb.get("language") or "",
                "symbols": nodes[-len(kb["symbols"]):],
                "imports": kb.get("imports") or [],
                "refs": kb.get("refs") or [],
                "statements": (impl or {}).get("statements") or [],
                "routes": (impl or {}).get("routes") or [],
                "constants": (impl or {}).get("constants") or [],
                "source": "kb",
            })
        else:
            # KB 不可达/不支持 → live 扫描(仅本文件)
            for n in _scan_live(root, [rel], []):
                nodes.append(n)
    edges: List[dict] = []
    for pf in per_file.values():
        edges += _rebuild_edges_from_refs(pf["symbols"], pf["refs"])
    impl_by_file = {rel: pf["impl"] for rel, pf in per_file.items() if pf.get("impl")}
    logger.info("[semantic] cache 兜底: 文件数=%d 缓存未命中=%s source=%s 共取节点=%d 边=%d impl文件=%d",
                len(files or []), miss or "-", source, len(nodes), len(edges), len(impl_by_file))
    return nodes, edges, source, impl_by_file


def _kb_parse_file(root: str, rel: str, impl: bool = False) -> Optional[dict]:
    """经 KbGateway 调 KB 只读 analysis.parseFileAst(内容不落 KB)。

    impl=True 时请求 implDetails(语句条件/框架路由/常量值)；
    旧版 KB 后端无此参数(HTTP 500) → 自动重试无参调用，降级为仅符号。
    """
    full = os.path.join(root, rel.replace("/", os.sep))
    try:
        from ..kb_gateway import call_kb
        res = None
        if impl:
            res = call_kb("analysis.parseFileAst", filePath=full, file_path=full,
                          implDetails=True)
            if not (isinstance(res, dict) and res.get("symbols") is not None):
                # 旧 KB 后端不支持 implDetails → 无参重试(降级为仅符号)
                res = call_kb("analysis.parseFileAst", filePath=full, file_path=full)
        else:
            res = call_kb("analysis.parseFileAst", filePath=full, file_path=full)
        if isinstance(res, dict) and res.get("symbols") is not None:
            return res
        return None
    except Exception as e:
        logger.warning("[semantic] kb parseFileAst %s failed: %s", rel, e)
        return None


def _impl_from_kb(kb: Optional[dict]) -> Optional[dict]:
    """KB 响应 → impl details；无 implDetails 字段(旧后端)返回 None。"""
    if not isinstance(kb, dict) or "implDetails" not in kb:
        return None
    det = kb.get("implDetails") or {}
    return {"statements": det.get("statements") or [],
            "routes": det.get("routes") or [],
            "constants": det.get("constants") or []}


def _impl_from_row(row: Optional[dict]) -> Optional[dict]:
    """缓存行 → impl details；行无 impl 数据(旧行/未填充)返回 None。"""
    if not isinstance(row, dict):
        return None
    if all(row.get(k) is None for k in ("statements", "routes", "constants")):
        return None
    return {"statements": row.get("statements") or [],
            "routes": row.get("routes") or [],
            "constants": row.get("constants") or []}


def _local_parse_impl(root: str, rel: str) -> Optional[dict]:
    """本地解析器兜底(KB 不可用时)：与 parseFileAst 同一 TreeSitterWalker + extract_impl_details。

    返回 {statements, routes, constants, language}；不支持的语言/失败返回 None。
    """
    full = os.path.join(root, rel.replace("/", os.sep))
    try:
        with open(full, "rb") as fh:
            raw = fh.read()
    except Exception:
        return None
    if len(raw) > 512 * 1024:
        return None
    try:
        from parsers.core.walker import TreeSitterWalker, _detect_language
        from parsers.core.impl_detail import extract_impl_details
        from parsers.languages import EXTRACTORS
        from parsers.language_loader import get_parser
    except Exception:
        return None
    lang = _detect_language(full) or ""
    if not lang or EXTRACTORS.get(lang) is None or get_parser(lang) is None:
        return None
    try:
        table = TreeSitterWalker(full, raw, lang, EXTRACTORS[lang]).extract()
    except Exception as e:
        logger.warning("[semantic] local walk %s failed: %s", rel, e)
        return None
    try:
        r = extract_impl_details(rel, raw, lang, table)
    except Exception as e:
        logger.warning("[semantic] local impl %s failed: %s", rel, e)
        return None
    impl = {"statements": r.get("statements") or [], "routes": r.get("routes") or [],
            "constants": r.get("constants") or [], "language": lang}
    return impl if any(impl[k] for k in ("statements", "routes", "constants")) else None


def _fetch_impl_for_file(root: str, project: Optional[str], rel: str) -> Optional[dict]:
    """单文件实现细节: 缓存命中 → KB parseFileAst(implDetails) → 本地解析器 → 回写 architect 缓存。"""
    pid = project_id_for(root, project)
    full = os.path.join(root, rel.replace("/", os.sep))
    if not os.path.isfile(full):
        return None
    h = _cache_content_hash(root, rel)
    row = store.AstCacheStore.get(pid, rel)
    if row and row.get("contentHash") == h:
        impl = _impl_from_row(row)
        if impl is not None:
            return impl
    kb = _kb_parse_file(root, rel, impl=True)
    if kb:
        impl = _impl_from_kb(kb)
        if impl is None:
            return None  # 旧 KB 后端不支持 → 降级为空
        store.AstCacheStore.upsert(pid, rel, {
            "contentHash": h, "language": kb.get("language") or "",
            "symbols": kb.get("symbols") or [],
            "imports": kb.get("imports") or [],
            "refs": kb.get("refs") or [],
            "statements": impl["statements"], "routes": impl["routes"],
            "constants": impl["constants"],
            "source": "kb",
        })
        return impl
    # KB 不可用 → 本地解析器兜底(与 parseFileAst 同一提取逻辑，source=local)
    local = _local_parse_impl(root, rel)
    if local is None:
        return None
    store.AstCacheStore.upsert(pid, rel, {
        "contentHash": h, "language": local.get("language") or "",
        "statements": local["statements"], "routes": local["routes"],
        "constants": local["constants"],
        "source": "local",
    })
    return {k: local[k] for k in ("statements", "routes", "constants")}


def _collect_impl_details(root: str, project: Optional[str],
                          files: Optional[List[str]]) -> Dict[str, dict]:
    """逐文件收集实现细节(rel → {statements, routes, constants})，全部 best-effort。"""
    out: Dict[str, dict] = {}
    for rel in (files or [])[:120]:
        try:
            impl = _fetch_impl_for_file(root, project, rel)
        except Exception as e:
            logger.warning("[semantic] impl details %s failed: %s", rel, e)
            continue
        if impl and any(impl.values()):
            out[rel] = impl
    return out


def _impl_block(impl_by_file: Dict[str, dict]) -> str:
    """实现细节结构化块: API 路由清单 / 常量值 / 控制流语句清单(供 LLM/启发式)。"""
    if not impl_by_file:
        return ""
    rl: List[str] = []
    cl: List[str] = []
    sl: List[str] = []
    for rel, impl in impl_by_file.items():
        for r in (impl.get("routes") or [])[:50]:
            methods = "/".join(r.get("methods") or ["GET"])
            handler = r.get("handler") or "?"
            rl.append(f"- [{methods}] {r.get('path', '')} -> {handler} "
                      f"({rel}:{r.get('line', 0)}, {r.get('framework', '')})")
        for c in (impl.get("constants") or [])[:80]:
            cl.append(f"- {c.get('name', '')} = {c.get('value', '')} ({rel}:{c.get('line', 0)})")
        for s in (impl.get("statements") or [])[:200]:
            enc = f"{s['enclosing']}:" if s.get("enclosing") else ""
            sl.append((f"- {enc}{s.get('startLine', 0)} [{s.get('type', '')}] "
                       f"{(s.get('condition') or '').strip()}").rstrip())
    parts: List[str] = []
    if rl:
        parts.append("API 路由清单:\n" + "\n".join(rl))
    if cl:
        parts.append("常量值清单:\n" + "\n".join(cl))
    if sl:
        parts.append("控制流语句清单(函数:行 [类型] 条件原文):\n" + "\n".join(sl))
    if not parts:
        return ""
    return "\n" + "\n".join(parts) + "\n"


def collect_context(root: str, scope_type: str, scope_key: str,
                    files: Optional[List[str]] = None,
                    symbols: Optional[List[str]] = None,
                    project: Optional[str] = None) -> Dict[str, Any]:
    """收集范围符号上下文。返回 {files, symbols, nodes, table, edges, text, srcHash, source}。

    取数四层(要求③): 缓存命中 → codegraph → KB parseFileAst → live 扫描。
    """
    _scope_out: Dict[str, Any] = {}
    files, syms = resolve_scope_files(root, scope_type, scope_key, files, symbols, project,
                                      out=_scope_out)
    scope_error = _scope_out.get("scopeError")
    logger.info("[semantic] collect_context 范围 %s(%s): files=%d symbols=%d",
                scope_type, scope_key or "-", len(files), len(syms))
    # 组件范围未解析到任何文件(组件目录/模型均未命中) → 直接空上下文，避免退化为全项目扫描。
    if scope_type == "comm" and not files and not syms:
        logger.warning("[semantic] collect_context comm(%s) 未解析到文件, 返回空上下文", scope_key or "-")
        return {"root": root, "files": [], "symbols": [], "nodes": [], "table": {},
                "edges": [], "text": "", "srcHash": "", "source": "none",
                "scopeError": scope_error}
    source = "live"
    impl_by_file: Dict[str, dict] = {}
    callee_names: Dict[str, str] = {}
    conn, _cg_src = open_symbol_conn(root, project)
    cross = ""
    if conn is not None:
        source = _cg_src if _cg_src in ('codegraph', 'merged') else 'native'
        nodes = _query_nodes(conn, files=files, symbols=syms)
        edges = _query_edges(conn, [n["id"] for n in nodes]) if nodes else []
        cross = _cross_file_edges_text(conn, [n["id"] for n in nodes])
        # 范围外调用目标 → 批量补名(steps/流程展示，避免裸节点 id)
        known = {n.get("id") for n in nodes}
        missing = {e.get("target") for e in edges
                   if e.get("kind") == "calls" and e.get("target")
                   and e.get("target") not in known}
        if missing:
            try:
                ph = ",".join("?" * len(missing))
                for r in conn.execute(
                        f"SELECT id, name FROM nodes WHERE id IN ({ph})",
                        tuple(missing)).fetchall():
                    callee_names[r["id"]] = r["name"] or ""
            except Exception as e:
                logger.warning("[semantic] callee 名称补全失败: %s", e)
        close_symbol_conn(conn)  # 缓存(native)连接不关，勿直接 conn.close()
        # codegraph 无实现级数据 → KB parseFileAst(implDetails) 补取(缓存 arch_ast_cache)
        if files:
            impl_by_file = _collect_impl_details(root, project, files)
    else:
        # 无 codegraph → AST 缓存层(KB 解析优先，live 扫描兜底)
        nodes, edges, source, impl_by_file = _collect_via_cache(root, project, files, syms)
    logger.info("[semantic] collect_context source=%s nodes=%d edges=%d implFiles=%d",
                source, len(nodes), len(edges), len(impl_by_file))
    table = build_symbol_table(nodes)
    cross_suffix = ("\n" + cross) if cross else ""
    ordered = _ordered_call_lines(nodes, edges, table)
    ordered_block = ("\n有序调用序列(按行号):\n" + ordered + "\n") if ordered else ""
    impl_block = _impl_block(impl_by_file)
    text = (
        f"文件集合({len(files)} 个): {', '.join(files[:40]) or '(全量)'}\n"
        f"符号清单:\n{_symbol_block(nodes)}\n"
        f"关系边:\n{_edge_lines(edges, table) or '(无)'}"
        f"{ordered_block}"
        f"{impl_block}"
        f"{cross_suffix}"
    )
    src_hash = hashlib.md5(json.dumps(
        [{"f": n["file_path"], "n": n["name"], "k": n["kind"],
          "s": n["start_line"], "e": n["end_line"], "sig": n.get("signature")}
         for n in nodes], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return {"root": root, "project": project, "files": files, "symbols": syms, "nodes": nodes, "table": table,
            "edges": edges, "text": text, "srcHash": src_hash, "source": source,
            "implDetails": impl_by_file, "calleeNames": callee_names}


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


