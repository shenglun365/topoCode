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
    H 级按需聚合(业务意图层，从 M/L 资产 + 跨组件依赖图合成，锚定下级防漂移)。
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
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request

from .common import _ts, err, ok
from . import store

logger = logging.getLogger(__name__)
router = APIRouter()

SEMANTIC_KINDS = ("structure", "behavior", "rule", "contract")
SEMANTIC_LEVELS = ("high", "medium", "low")

_KIND_LABEL = {
    "structure": "结构(数据/状态)",
    "behavior": "行为(流程)",
    "rule": "规则(决策/约束)",
    "contract": "契约(接口/交互)",
}

# 规范分类在各级粒度下的具体形态(供 prompt / 前端标注)。
_LEVEL_KIND_FORM = {
    ("high", "structure"): "domain_entity 领域实体/聚合",
    ("high", "behavior"): "business_process 端到端业务过程",
    ("high", "rule"): "business_rule 业务规则/策略",
    ("high", "contract"): "business_contract 业务能力契约",
    ("medium", "structure"): "data_structure 逻辑数据结构",
    ("medium", "behavior"): "processing_flow 处理流程",
    ("medium", "rule"): "control_logic 决策逻辑",
    ("medium", "contract"): "service_contract 服务/接口契约",
    ("low", "structure"): "concrete_type 具体类型(class/struct/enum)",
    ("low", "behavior"): "call_chain 函数/调用链",
    ("low", "rule"): "branch_logic 分支/条件逻辑单元",
    ("low", "contract"): "message_contract 消息/事件/签名约定",
}

# id 前缀: 按 level+kind。medium 沿用旧前缀保证历史 id 不断链。
_ID_PREFIX = {
    ("medium", "structure"): "sa-d",
    ("medium", "behavior"): "sa-f",
    ("medium", "rule"): "sa-c",
    ("medium", "contract"): "sa-mx",
    ("high", "structure"): "sa-hs",
    ("high", "behavior"): "sa-hb",
    ("high", "rule"): "sa-hr",
    ("high", "contract"): "sa-hx",
    ("low", "structure"): "sa-ls",
    ("low", "behavior"): "sa-lb",
    ("low", "rule"): "sa-lr",
    ("low", "contract"): "sa-lx",
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
    "structure": "structure",
    "结构": "structure",
    "data_structure": "structure",
    "数据结构": "structure",
    "datastructure": "structure",
    "data structure": "structure",
    "data-structure": "structure",
    "data_structure类": "structure",
    "entity": "structure",
    "实体": "structure",
    "domain_entity": "structure",
    "concrete_type": "structure",
    "behavior": "behavior",
    "行为": "behavior",
    "processing_flow": "behavior",
    "处理流程": "behavior",
    "processingflow": "behavior",
    "process flow": "behavior",
    "process-flow": "behavior",
    "process": "behavior",
    "processing": "behavior",
    "流程": "behavior",
    "flow": "behavior",
    "call_chain": "behavior",
    "business_process": "behavior",
    "rule": "rule",
    "规则": "rule",
    "control_logic": "rule",
    "控制逻辑": "rule",
    "controllogic": "rule",
    "control logic": "rule",
    "control-logic": "rule",
    "logic": "rule",
    "逻辑": "rule",
    "决策": "rule",
    "business_rule": "rule",
    "branch_logic": "rule",
    "contract": "contract",
    "契约": "contract",
    "interface": "contract",
    "接口": "contract",
    "api": "contract",
    "service_contract": "contract",
    "message_contract": "contract",
    "business_contract": "contract",
}

_LEVEL_ALIASES = {
    "high": "high",
    "高": "high",
    "概念": "high",
    "conceptual": "high",
    "business": "high",
    "业务": "high",
    "medium": "medium",
    "中": "medium",
    "逻辑": "medium",
    "logical": "medium",
    "design": "medium",
    "设计": "medium",
    "low": "low",
    "低": "low",
    "实现": "low",
    "implementation": "low",
    "code": "low",
    "代码": "low",
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
      - 锚点: source_symbols[] + anchor_symbol → astRefs(可解析则真实节点，否则记录警告)
    无法归一化(缺 kind/name)返回 None。
    """
    if not isinstance(a, dict):
        return None
    kind = _normalize_kind(a.get("kind") or a.get("type"))
    name = (a.get("name") or "").strip()
    if not kind or not name:
        return None
    level = _normalize_level(a.get("level")) or "medium"
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

    return {"kind": kind, "level": level, "name": name, "desc": (a.get("desc") or "").strip(),
            "detail": detail, "astRefs": ast_refs}


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
                                             "symbols": {"type": "array", "items": {"type": "string"}}}}},
                    "branches": {"type": "array", "items": {"type": "object",
                                "properties": {"condition": {"type": "string"}, "then": {"type": "string"},
                                               "else": {"type": "string"}, "semantic": {"type": "string"},
                                               "symbols": {"type": "array", "items": {"type": "string"}}}}},
                    "aggregates": {"type": "array", "items": {"type": "object",
                                   "properties": {"assetId": {"type": "string"}, "name": {"type": "string"},
                                                  "role": {"type": "string"}}}},
                },
            },
        }
    },
}

_SYSTEM_PROMPT = (
    "你是代码语义化建模专家。基于给定的最新代码符号清单(文件/符号/行号/签名/docstring/关系边)，"
    "提取语义化的数据资产。\n"
    "语义资产按「类别(关切维度) × 抽象粒度(离代码远近)」二维分类：\n"
    "类别 kind(值只能是 structure / behavior / rule / contract，禁止翻译成中文):\n"
    "  - structure : 结构(数据/状态)\n"
    "  - behavior  : 行为(流程)\n"
    "  - rule      : 规则(决策/约束)\n"
    "  - contract  : 契约(接口/交互)\n"
    "粒度 level(越低越贴近代码实现；值只能是 high / medium / low):\n"
    "  - high   : 概念/业务级 —— 业务命名(如「订单创建与结算」)，不直接耦合单个符号，"
    "    锚定一组下级资产/符号；detail 用 aggregates 列出组成资产\n"
    "  - medium : 逻辑/设计级 —— 业务语义命名(如「支付结算聚合」)，锚定符号集合；"
    "    structure→fields/relations/invariants；behavior→trigger/steps；rule→branches；"
    "    contract→relations(端点/事件/消息)\n"
    "  - low    : 实现/代码级 —— 名称贴近符号(如 `Order.calcTotal`)，锚定单符号/1-hop 调用链；"
    "    detail 以签名/字段/分支为事实层\n"
    "约束(重要):\n"
    "1. 只输出 JSON 对象 {\"assets\": [...]}，不要 Markdown 代码块、不要解释。\n"
    "2. 每个资产必须真实来源于清单中的符号; steps/branches 的 symbols 必须是清单中的符号名，不得臆造。\n"
    "3. name 用业务语义命名(如「支付结算聚合」「鉴权校验链」)，不是符号名。\n"
    "4. desc 概括其逻辑作用与边界，比伪代码抽象。\n"
    "5. 建议提取 2~6 个资产；无匹配数据时返回空数组。\n"
    "6. 每个资产建议填写 source_symbols(清单中真实符号名数组)或 anchor_symbol(主要符号名)，"
    "帮助定位其真实代码位置。\n"
    "7. 高(high)粒度资产应聚合多个逻辑单元并填写 aggregates 字段，避免与 medium 资产重复表述。\n"
    "8. relations 用于表达资产之间的依赖/关联，强烈建议为每个资产填写(可空) 1~3 条："
    "target 填**其它资产业务名**或清单中的符号名(如「支付结算聚合」依赖「订单实体」、"
    "「鉴权校验链」被「下单流程」调用)，type 填关系类型(calls/contains/extends/implements/1:N/读写等)，"
    "semantic 一句话说明关系含义。relations 是图谱连边的数据来源，务必填写。"
)


def _llm_extract(root: Optional[str], project: Optional[str],
                 context_text: str, model_id: Optional[str],
                 table: Optional[Dict[str, dict]] = None,
                 max_assets: int = 6,
                 level: str = "medium") -> List[dict]:
    """LLM 结构化提取。LLM 不可用/解析失败返回空列表(调用方启发式兜底)。

    LLM 输出经 `_norm_llm_asset` 宽容归一化(兼容 type/kind、单复数字段、中文变体)。
    level: 请求粒度(medium 默认)；提示词据此要求产出对应抽象层的资产。
    """
    from .req_agent import llm_sync
    table = table or {}
    sys_prompt = _SYSTEM_PROMPT
    if level == "low":
        sys_prompt = _SYSTEM_PROMPT + (
            "\n\n本批只提取 low 实现/代码级资产：名称贴近符号(如 `Order.calcTotal`)，"
            "锚定单符号/1-hop 调用链，detail 以签名/字段/分支为事实层。不要输出 high/medium 级归纳。"
        )
    elif level == "high":
        sys_prompt = _SYSTEM_PROMPT + (
            "\n\n本批只提取 high 概念/业务级资产：业务命名(如「订单创建与结算」)，"
            "不直接耦合单个符号，detail 用 aggregates 列出组成资产。不要输出 medium/low 级细节。"
        )
    logger.info("[semantic] llm 提取: model=%s level=%s text_len=%d",
                model_id or "(默认)", level, len(context_text or ""))
    res = llm_sync(
        [{"role": "system", "content": sys_prompt},
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
            # 请求粒度优先：LLM 未标注时按请求粒度落库。
            norm["level"] = norm.get("level") or level
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

def _heuristic_extract(kind: str, ctx: Dict[str, Any],
                       level: str = "medium") -> List[dict]:
    """无 LLM 时的确定性提取。

    - level='low' : 代码事实层。concrete_type/call_chain/branch_logic/message_contract
                    一一对应 codegraph 符号节点(名称=符号名，锚定真实节点)，零臆造。
    - level='medium': 逻辑级降级。以符号名+签名/docstring 兜底(名称=符号名，粒度近 low，
                    供 LLM 不可用时仍能消费)。
    """
    nodes = ctx.get("nodes") or []
    edges = ctx.get("edges") or []
    out: List[dict] = []
    low = level == "low"
    if kind == "structure":
        for n in nodes:
            if n.get("kind") not in ("class", "interface", "enum", "struct", "component"):
                continue
            doc = (n.get("docstring") or "").strip()
            desc = doc or (f"数据结构「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。"
                           if not low else
                           f"具体类型「{n['name']}」，位于 {n['file_path']}:{n['start_line']}。")
            detail = {"fields": [], "relations": [], "invariants": []}
            if low:
                detail = {"kind": "type", "signature": n.get("signature") or "",
                          "fields": _fields_from_node(n), "invariants": []}
            out.append({"kind": kind, "level": level, "name": n["name"], "desc": desc,
                        "detail": detail, "astRefs": [_node_to_ref(n)]})
    elif kind == "behavior":
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
                callees = _callee_names(n.get("id"), edges)
                detail = {"trigger": "", "kind": "call_chain",
                          "steps": [{"order": 1, "semantic": "调用 " + c, "symbols": [c]}
                                    for c in callees],
                          "invariants": []}
            out.append({"kind": kind, "level": level, "name": n["name"], "desc": desc,
                        "detail": detail, "astRefs": [_node_to_ref(n)]})
    elif kind == "rule":
        for n in nodes:
            if n.get("kind") not in ("function", "method", "route"):
                continue
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
    return out[:12]


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


def _callee_names(node_id: str, edges: List[dict]) -> List[str]:
    """低粒度调用链：取 1-hop 直接调用目标名(去重、截断)。"""
    out: List[str] = []
    for e in edges or []:
        if e.get("kind") == "calls" and e.get("source") == node_id and e.get("target"):
            out.append(str(e["target"]))
    return list(dict.fromkeys(out))[:8]


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
        membership = _asset_scope_membership(ast_refs, file_to_comps)
        meta = {"componentId": scope_key if scope_type == "comm" else "",
                "scopes": membership}
        if scope_type == "files":
            meta["files"] = (ctx.get("files") or [])[:200]
        if scope_type == "symbols":
            meta["symbols"] = (ctx.get("symbols") or [])[:200]
        canonical_key = _canonical_key(a["kind"], a.get("level") or "medium", ast_refs,
                                       name=a.get("name") or "",
                                       scope_type=scope_type, scope_key=scope_key)
        payload = {
            "projectId": project_id, "kind": a["kind"],
            "level": a.get("level") or "medium",
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
            lvl = a.get("level") or "medium"
            payload["id"] = store.next_id(_ID_PREFIX.get((lvl, a["kind"]), "sa-a"))
            payload["change"] = "added"
            payload["status"] = "active"
            payload["createdAt"] = now
            store.SemanticAssetsStore.create(payload)
        saved.append(store.SemanticAssetsStore.get(payload["id"]) or payload)
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
                  level: str = "medium") -> Dict[str, Any]:
    """按范围提取语义资产并落库。返回 {assets, source, degraded, count}。

    level: 抽象粒度 high|medium|low。
      - low    : 确定性启发式映射(零 LLM，代码事实层)；
      - medium : LLM 归纳(逻辑组织层)，LLM 不可用降级启发式；
      - high   : 由 _aggregate_high 负责(按需，从已提取 M/L 资产聚合)，本入口不直接生成。
    degraded=True 表示 LLM 不可用(启发式兜底) 或 codegraph 缺失(轻量扫描)。
    """
    if level == "high":
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
    if level == "low":
        # 低粒度确定性映射(代码事实层)：不依赖 LLM，海量可跑。
        for k in kinds:
            all_assets += _heuristic_extract(k, ctx, level="low")
    else:
        if use_llm:
            try:
                llm_assets = _llm_extract(root, project, ctx.get("text") or "", model_id,
                                          table=ctx.get("table") or {}, level="medium")
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
                all_assets += _heuristic_extract(k, ctx, level="medium")
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
                      level: str = "medium") -> Tuple[List[dict], int, List[str]]:
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


def extract_all(root: Optional[str], project: Optional[str],
                kinds: Optional[List[str]] = None,
                model_id: Optional[str] = None,
                use_llm: bool = True,
                max_components: int = 12,
                level: str = "medium") -> Dict[str, Any]:
    """批处理: 组件目录(跨 INCLUDE/CALL × L0/L1)文件并集 → 逐文件单次提取。

    组件是下游投影(资产身份=代码锚点)，两套组件重叠文件不重复提取。
    无组件时按全项目提取一次。"""
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
    if not files:
        logger.info("[semantic] extract_all 无组件文件, 按全项目提取一次")
        res = extract_scope(root, project, "project", kinds=kinds,
                            model_id=model_id, use_llm=use_llm, level=level)
        return {"assets": res.get("assets") or [], "count": res.get("count") or 0,
                "components": 0}
    assets, done, _failed = _extract_file_set(root, project, files, kinds,
                                              model_id=model_id, use_llm=use_llm, level=level)
    logger.info("[semantic] extract_all 完成: 文件=%d 资产=%d", done, len(assets))
    return {"assets": assets, "count": len(assets), "components": len(comps)}


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
        lvl = a.get("level") or "medium"
        if lvl == "high":
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
                    "invariants": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


def _aggregate_high(root: Optional[str], project: Optional[str],
                    model_id: Optional[str] = None,
                    max_assets: int = 8) -> Dict[str, Any]:
    """按需聚合 H 级(业务概念级)资产：从已提取 M/L 资产 + 跨组件依赖图合成。

    只消费已落库的 active 中/低资产(锚定真实代码)，LLM 仅作归纳并填写 aggregates
    (组成资产 id)，防止业务级表述漂移。落库后为下级资产回填 parentId(组合链)。
    """
    root = resolve_root(root, project)
    if not root:
        return {"assets": [], "count": 0, "degraded": True, "reason": "root"}
    from .req_agent import llm_sync
    pid = project_id_for(root, project)
    asset_text = _high_asset_text(pid)
    # 跨组件依赖图上下文(业务过程常横跨组件)。
    comp_context = ""
    try:
        from .common import build_architecture_model
        model = build_architecture_model(root, project)
        comps = model.get("components") or []
        lines = []
        for c in comps:
            lines.append(f"- {c.get('id')} ({c.get('name')})"
                         f"{(' — ' + (c.get('desc') or '')) if c.get('desc') else ''}"
                         f"{(' owns: ' + ','.join((c.get('owns') or [])[:4])) if c.get('owns') else ''}")
        if lines:
            comp_context = "组件目录:\n" + "\n".join(lines)
    except Exception as e:
        logger.warning("[semantic] aggregate high 组件上下文失败: %s", e)
    sys_prompt = (
        "你是资深架构师。基于已提取的逻辑/代码级语义资产清单与组件目录，"
        "归纳出 high 概念/业务级的语义资产。\n"
        "类别 kind ∈ structure(领域实体/聚合)/behavior(端到端业务过程)/"
        "rule(业务规则/策略)/contract(业务能力契约)。\n"
        "规则：\n"
        "1. 每个 high 资产必须是多个逻辑单元的业务归纳(如「订单创建与结算」聚合"
        " createOrder/支付 等资产)，不得与 medium 资产重复表述；\n"
        "2. aggregates 只引用清单中真实存在的资产 id(至少一个)，不得臆造；\n"
        "3. name 用业务命名，desc 概括业务意图与边界；\n"
        "4. 只输出 JSON 对象 {\"assets\": [...]}，不要代码块。"
    )
    user_prompt = (
        f"{comp_context or '(无组件)'}\n\n"
        f"候选逻辑/代码级资产:\n{asset_text}\n\n请归纳 high 级业务概念资产。"
    )
    try:
        res = llm_sync([{"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt}],
                       mode="structured", output_schema=_HIGH_SCHEMA,
                       max_tokens=1600, model_id=model_id)
    except Exception as e:
        logger.warning("[semantic] aggregate high LLM 失败: %s", e, exc_info=True)
        return {"assets": [], "count": 0, "degraded": True, "reason": "llm"}
    output = res.get("output") if isinstance(res, dict) else None
    if not isinstance(output, dict):
        return {"assets": [], "count": 0, "degraded": True, "reason": "parse"}
    raw = output.get("assets") or []
    assets: List[dict] = []
    for a in raw:
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
        detail = {"aggregates": agg,
                  "invariants": [str(v) for v in (a.get("invariants") or [])]}
        assets.append({"kind": kind, "level": "high", "name": name,
                       "desc": (a.get("desc") or "").strip(),
                       "detail": detail, "astRefs": [],
                       "parentId": ""})
        if len(assets) >= max_assets:
            break
    if not assets:
        return {"assets": [], "count": 0, "degraded": False, "reason": "empty"}
    saved = _save_assets(pid, "project", "high", assets, {"root": root, "project": project,
                                                          "table": {},
                                                          "source": "codegraph",
                                                          "srcHash": ""})
    # 回填组合链: 下级资产 parentId → 上级 high 资产。
    _link_parent(pid, saved)
    return {"assets": saved, "count": len(saved), "degraded": False, "reason": "ok"}


def _link_parent(pid: str, high_assets: List[dict]) -> None:
    """为 high 资产 aggregates 引用的下级资产回填 parentId(组合链)。"""
    for h in high_assets:
        hid = h.get("id") or ""
        detail = h.get("detail") or {}
        for agg in detail.get("aggregates") or []:
            aid = (agg.get("assetId") or "").strip()
            if not aid or not str(aid).startswith("sa-"):
                continue
            try:
                store.SemanticAssetsStore.update(aid, {"parentId": hid, "updatedAt": _ts()})
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
                 level: str = "medium",
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
        assets, done, _failed = _extract_file_set(root, project, files, kinds,
                                                  model_id=model_id, use_llm=True, level=level)
        logger.info("[semantic] batch extract 完成: 文件=%d 资产=%d", done, len(assets))
        return {"action": action, "count": len(assets), "components": len(comp_ids),
                "cleared": [], "updated": []}
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
        assets, _, failed = _extract_file_set(root, project, files, kinds,
                                              model_id=model_id, use_llm=True)
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


def extract_task_status(task_id: str) -> Dict[str, Any]:
    """任务状态快照(供前端轮询)：status/progress/messages + 概要。"""
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
    # 刷新失败(LLM/解析均不可用) → 软删 + 启发式重新生成(离线兜底)
    store.SemanticAssetsStore.mark_deleted(asset_id)
    try:
        ctx = collect_context(root, scope_type, scope_key,
                              files=scope_files, symbols=scope_symbols,
                              project=project)
        pid = project_id_for(root, project)
        heur = []
        for k in SEMANTIC_KINDS:
            heur += _heuristic_extract(k, ctx, level="medium")
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

_SA_ID_RE = re.compile(r"\bsa-(?:d|f|c|dcf|hs|hb|hr|hx|ms|mb|mr|mx|ls|lb|lr|lx)-\d+\b")


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
        line = (f"- {a.get('name')}({a.get('kind')}/{a.get('level') or 'medium'}): "
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


def semantic_graph(root: Optional[str], project: Optional[str],
                   kind: str = "", scopes: Optional[List[str]] = None,
                   level: str = "", limit: int = 2000) -> Dict[str, Any]:
    """语义层图谱：节点=语义资产，边=资产间 relations，锚点=AST 引用。

    确定性派生自既有资产(不新增提取)；relations.target 若命中本图资产名则解析为 id。
    """
    _lazy_reconcile(root, project)
    pid = project_id_for(root, project)
    rows = store.SemanticAssetsStore.search(pid, text="", kind=kind,
                                            limit=limit, scopes=scopes, level=level)
    nodes: List[dict] = []
    edges: List[dict] = []
    anchors: List[dict] = []
    name_to_id = {a.get("name") or "": a.get("id") or "" for a in rows}
    for a in rows:
        aid = a.get("id") or ""
        nodes.append({
            "id": aid, "kind": a.get("kind") or "structure",
            "level": a.get("level") or "medium",
            "name": a.get("name") or "", "desc": a.get("desc") or "",
            "change": a.get("change") or "same", "status": a.get("status") or "active",
            "scopeType": a.get("scopeType") or "", "scopeKey": a.get("scopeKey") or "",
            "needsUpdate": a.get("needsUpdate") or 0,
            "canonicalKey": a.get("canonicalKey") or "",
        })
        detail = a.get("detail") or {}
        for rel in detail.get("relations") or []:
            tgt = (rel.get("target") or "").strip()
            if not tgt:
                continue
            tgt_id = name_to_id.get(tgt, tgt)
            edges.append({"from": aid, "to": tgt_id,
                          "resolved": tgt in name_to_id,
                          "type": rel.get("type") or "",
                          "semantic": rel.get("semantic") or ""})
        for r in a.get("astRefs") or []:
            if r.get("file"):
                anchors.append({"assetId": aid, "file": r.get("file"),
                                "line": r.get("startLine") or 0,
                                "symbol": r.get("symbol") or "",
                                "kind": r.get("kind") or ""})
    return {"nodes": nodes, "edges": edges, "anchors": anchors,
            "count": len(nodes)}


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
                     limit: int = 100, offset: int = 0, scope: str = "",
                     level: str = ""):
    """分页检索：返回 items + total(超出 limit 翻页用)。

    scope: 逗号分隔的组件范围(scope_key 精确匹配)；空=全部。
    level: 抽象粒度过滤(high|medium|low)；空=全部。
    """
    _lazy_reconcile(root, project)
    pid = project_id_for(root, project)
    scopes = [s.strip() for s in (scope or "").split(",") if s.strip()] or None
    lvl = level if level in SEMANTIC_LEVELS else ""
    items = store.SemanticAssetsStore.search(pid, q, kind, limit, offset, scopes=scopes, level=lvl)
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
                    kind: str = "", scope: str = "", level: str = "", limit: int = 2000):
    """语义层图谱：节点=语义资产，边=资产 relations，锚点=AST 引用。

    scope: 逗号分隔的组件范围(scope_key)；kind: 资产种类过滤；level: 抽象粒度过滤。
    """
    scopes = [s.strip() for s in (scope or "").split(",") if s.strip()] or None
    lvl = level if level in SEMANTIC_LEVELS else ""
    return ok(semantic_graph(root, project, kind, scopes, level=lvl, limit=limit))


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
    lvl = body.get("level") or "medium"
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
    lvl = body.get("level") or "medium"
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
                       level=body.get("level") or "medium",
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
