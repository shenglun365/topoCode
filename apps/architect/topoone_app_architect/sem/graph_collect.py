"""architect 自有图谱基线采集（数据主权批A）。

职责：把「KB parseFileAst 算力 → architect 持久图谱」批量作业化——
- 文件集 = git ls-files 代码文件（scope.files 可显式收窄）；
- 逐文件走 AstCacheStore（content_hash 命中免解析；miss → KB 只读解析 →
  归一化落缓存——与 sem/context 按需链路同源，复用其归一化与边重建）；
- 节点 + 边（refs 重建含 contains 推导 + imports 文件级边 + file 虚拟节点）
  整 rev 重灌 GraphStore（arch_graph_node / arch_graph_edge）；
- 完成自记基线 KV（arch.graphBaseline.<pid> = {head, at}）——resolve_base_commit
  的自管基准来源，KB 缺席照常工作。

快照语义：采集=工作区现状 + 采集时 HEAD 锚定（与 codegraph sync 同语义）；
历史版本按需走 structural_parse.parse_rev_file 通道，不做批量历史快照。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import List, Optional, Tuple

from ..store import AstCacheStore
from ..store.graph import ComponentStore, GraphStore
from . import job_runner
from .job_runner import JobCtx
from .structural_parse import parse_file

logger = logging.getLogger(__name__)

# 代码文件扩展名（采集文件集过滤；与 KB EXT_LANG 口径对齐的超集，含前端）
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".mjs", ".cjs",
    ".go", ".java", ".rs", ".c", ".h", ".cpp", ".cc", ".hpp", ".hh",
    ".cs", ".php", ".rb", ".kt", ".kts", ".swift", ".scala", ".lua",
    ".m", ".mm", ".dart", ".sql",
}

# 采集跳过的目录（依赖/构建产物——git ls-files 已排除 ignored，这里兜非 git 目录场景）
SKIP_DIRS = {"node_modules", "dist", "build", "__pycache__", ".codegraph", "vendor"}


def _now_ms() -> int:
    return int(time.time() * 1000)


def list_code_files(root: str, *, limit: int = 3000) -> List[str]:
    """git ls-files → 代码文件相对路径（正斜杠，cap limit）。非 git 目录降级 os.walk。"""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z"],
                             capture_output=True, timeout=60)
        if out.returncode == 0 and out.stdout:
            names = [n.replace("\\", "/") for n in
                     out.stdout.decode("utf-8", errors="replace").split("\x00") if n]
        else:
            names = []
    except Exception as e:  # noqa: BLE001
        logger.warning("[graph-collect] git ls-files 失败, 降级 os.walk: %s", e)
        names = []
    if not names:
        names = _walk_files(root)
    files = [n for n in names
             if os.path.splitext(n)[1].lower() in CODE_EXTS
             and not any(p in SKIP_DIRS for p in n.split("/"))]
    return files[:limit]


def _walk_files(root: str) -> List[str]:
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")
            out.append(rel)
    return out


def _cache_content_hash(root: str, rel: str) -> str:
    import hashlib
    try:
        full = os.path.join(root, rel.replace("/", os.sep))
        with open(full, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return ""


def _parse_one(root: str, rel: str) -> Optional[dict]:
    """单文件 → KB 解析结果（symbols/imports/refs/implDetails）。失败返回 None。"""
    return parse_file(root, rel, impl=False)


def collect_snapshot(root: str, project: str, files: List[str], rev: str, *,
                     progress=None) -> Tuple[List[dict], List[dict], dict]:
    """采集核心：文件集 → (nodes, edges, stats)。

    主路径: KB analysis.buildGraph(与 KB 分析管线同构全图, 划分一致);
    降级路径: 逐文件 parseFileAst + refs 重建 + D1 imports 解析。"""
    from .context import _norm_cache_symbol, _peek_docstring_at_line, _rebuild_edges_from_refs
    from .import_resolver import AliasRegistry, build_alias_registry

    nodes: List[dict] = []
    edges: List[dict] = []
    stats = {"parsed": 0, "cached": 0, "failed": 0, "source": ""}
    file_set = set(files or [])

    # ── 主路径: KB buildGraph(全层级同构图) ──
    from .buildgraph_client import _prune_old_snapshots, collect_via_buildgraph
    bg = collect_via_buildgraph(root, files or [])
    if bg is not None:
        if progress is not None:
            progress(len(files or []), "buildGraph 完成")
        return bg

    registry = build_alias_registry(root, file_set)
    for i, rel in enumerate(files or []):
        if progress is not None and i % 20 == 0:
            progress(i, rel)
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            stats["failed"] += 1
            continue
        h = _cache_content_hash(root, rel)
        file_node_id = f"file:{rel}"
        file_syms: List[dict] = []
        file_refs: List[dict] = []
        file_imports: List[str] = []
        cached = AstCacheStore.get(project, rel)
        if cached and cached.get("contentHash") == h and cached.get("symbols"):
            stats["cached"] += 1
            lang = cached.get("language") or ""
            for s in cached.get("symbols") or []:
                n = _norm_cache_symbol(rel, lang, s)
                if n:
                    file_syms.append(n)
            file_refs = cached.get("refs") or []
            file_imports = cached.get("imports") or []
            stats["source"] = stats["source"] or (cached.get("source") or "")
        else:
            kb = _parse_one(root, rel)
            if not (kb and kb.get("symbols")):
                stats["failed"] += 1
                continue
            stats["parsed"] += 1
            stats["source"] = stats["source"] or "kb"
            lang = kb.get("language") or ""
            src = None
            for s in kb["symbols"]:
                n = _norm_cache_symbol(rel, lang, s)
                if not n:
                    continue
                if not n.get("docstring"):
                    if src is None:
                        try:
                            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                                src = fh.read()
                        except Exception:  # noqa: BLE001
                            src = ""
                    n["docstring"] = _peek_docstring_at_line(src or "", n["start_line"])
                file_syms.append(n)
            file_refs = kb.get("refs") or []
            file_imports = kb.get("imports") or []
            try:
                AstCacheStore.upsert(project, rel, {
                    "contentHash": h, "language": lang,
                    "symbols": file_syms, "imports": file_imports,
                    "refs": file_refs, "source": "kb",
                })
            except Exception as e:  # noqa: BLE001
                logger.warning("[graph-collect] ast cache 写入失败 %s: %s", rel, e)
        if not file_syms:
            continue
        nodes.extend(file_syms)
        nodes.append({
            "id": file_node_id, "kind": "file", "name": os.path.basename(rel),
            "qualified_name": rel, "file_path": rel, "language": "",
            "start_line": 0, "end_line": 0, "start_column": 0, "end_column": 0,
            "signature": "", "docstring": "", "return_type": "", "is_exported": False,
        })
        edges.extend(_rebuild_edges_from_refs(file_syms, file_refs))
        for mod in file_imports or []:
            if isinstance(mod, str) and mod.strip():
                edges.append({"source": file_node_id, "target": mod.strip(),
                              "kind": "imports"})
    # imports 边批量改写(D1): 模块说明符 → file:<rel> 真实边; external 丢弃
    from .import_resolver import resolve_imports_batch
    jvm_roots = _jvm_package_roots(root, file_set)
    edges, imp_stats = resolve_imports_batch(edges, file_set, registry,
                                             jvm_package_dirs=jvm_roots)
    stats["importsResolved"] = imp_stats["resolved"]
    stats["importsExternal"] = imp_stats["external"]

    # D2: 符号级跨文件边(import 感知)——refs 未命中本文件的裸符号名 target,
    # 在「本文件 import 的目标文件」符号表中找同名; 唯一命中改写为符号 id,
    # 多命中(歧义)丢弃保守。
    sym_by_file: dict = {}
    for n in nodes:
        nm = n.get("name")
        if nm and n.get("kind") != "file":
            sym_by_file.setdefault(n.get("file_path") or "", {})[nm] = n["id"]
    file_imports: dict = {}
    for e in edges:
        if e.get("kind") == "imports":
            src, tgt = e.get("source") or "", e.get("target") or ""
            if src.startswith("file:") and tgt.startswith("file:"):
                file_imports.setdefault(src[5:], set()).add(tgt[5:])
    cross_resolved = 0
    for e in edges:
        if e.get("kind") == "imports":
            continue
        tgt = e.get("target") or ""
        if not tgt or tgt.startswith(("cache:", "file:")):
            continue
        src = e.get("source") or ""
        src_file = src[6:].split("::", 1)[0] if src.startswith("cache:") else ""
        hit = None
        for tf in file_imports.get(src_file, ()):  # 直接 import 的目标文件
            cand = sym_by_file.get(tf, {}).get(tgt)
            if cand:
                if hit and hit != cand:   # 歧义 → 丢弃
                    hit = None
                    break
                hit = cand
        if hit:
            e["target"] = hit
            cross_resolved += 1
    stats["crossFileRefs"] = cross_resolved
    return nodes, edges, stats


def _jvm_package_roots(root: str, file_set: set) -> dict:
    """JVM 族 FQCN → 目录索引: 扫 package/use 声明(每文件一次, 上限 512 文件)。

    import com.x.y.Z → 前缀 com.x.y 命中 → 目录 + Z + 扩展序探测。
    """
    import re as _re
    out: dict = {}
    jvm_files = [f for f in file_set
                 if os.path.splitext(f)[1].lower() in (".java", ".kt", ".kts", ".scala")][:512]
    for rel in jvm_files:
        try:
            with open(os.path.join(root, rel.replace("/", os.sep)), "rb") as fh:
                head = fh.read(4096).decode("utf-8", "replace")
        except OSError:
            continue
        m = _re.search(r"^\s*package\s+([\w.]+)", head, _re.M)
        if m:
            out[m.group(1)] = os.path.dirname(rel)
    return out


def _graph_kv_key(pid: str) -> str:
    return f"arch.graphBaseline.{pid}"


def record_graph_baseline(pid: str, head: str) -> None:
    """采集完成自记基线锚（自管 KV；resolve_base_commit 的数据主权来源）。"""
    try:
        from .. import ctx
        from .codegraph import ensure_arch_settings_table
        ensure_arch_settings_table()
        val = json.dumps({"head": head, "at": _now_ms()}, ensure_ascii=False)
        ctx.db().execute(
            "INSERT INTO arch_settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_graph_kv_key(pid), val))
    except Exception as e:  # noqa: BLE001
        logger.warning("[graph-collect] 基线锚写入失败: %s", e)


def read_graph_baseline(project: str) -> dict:
    """读自管基线锚 {head, at}（无则 {}）。"""
    try:
        from .. import ctx
        row = ctx.db().fetchone(
            "SELECT value FROM arch_settings WHERE key = ?", (_graph_kv_key(project),))
        return json.loads(row["value"]) if row and row.get("value") else {}
    except Exception:  # noqa: BLE001
        return {}


def _git_head(root: str) -> str:
    try:
        out = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                             capture_output=True, timeout=15)
        return out.stdout.decode().strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def _job_collect_graph(ctx: JobCtx) -> dict:
    """作业体：kind=collect_graph。scope: {files?: [], rev?: str,
    partition?: {head, idx}}(分区模式, D3——单分区落库 + 完成后自链下一分区)。"""
    from .. import ctx as app_ctx
    from ..arch_routes.project import resolve_project
    from .paths import resolve_root

    scope = ctx.scope
    job = ctx.job
    pid = ctx.pid
    proj_row = resolve_project(None, pid) or {}
    root = resolve_root(proj_row.get("rootPath") or None, pid)
    if not root:
        return {"error": "root 解析失败"}

    part = scope.get("partition") or None
    from ..store.partition import PartitionStore
    if part:
        prow = PartitionStore.get(pid, part.get("head") or "", int(part.get("idx") or 0))
        if not prow:
            return {"error": "分区不存在(重新提案)"}
        PartitionStore.set_state(pid, part["head"], prow["idx"], "running")
        files = prow.get("files") or []
    else:
        files = scope.get("files") or list_code_files(root)
    if not files:
        if part:
            PartitionStore.set_state(pid, part["head"], prow["idx"], "done")
        return {"nodes": 0, "edges": 0, "files": 0, "note": "无代码文件"}
    rev = scope.get("rev") or ""
    anchor_head = (scope.get("anchorHead") or "").strip()
    if not rev:
        head = anchor_head or _git_head(root)
        rev = f"baseline:{head}" if head else "workspace"

    def _prog(done: int, current: str) -> None:
        ctx.progress(total=len(files), done=done, current=current[-80:])

    nodes, edges, stats = collect_snapshot(root, pid, files, rev, progress=_prog)
    if part:
        written = GraphStore.merge_partition(pid, rev, nodes, edges, files)
    else:
        written = GraphStore.replace_rev(pid, rev, nodes, edges)
    head = anchor_head or _git_head(root)
    baseline_recorded = False
    if head:
        if part:
            # 分区模式: 全部 done 才记基线锚; 并自链下一个待跑分区
            PartitionStore.set_state(pid, part["head"], prow["idx"], "done")
            states = PartitionStore.counts_by_state(pid, part["head"])
            next_idx = _next_partition(pid, part["head"])
            if next_idx is not None:
                from . import job_runner
                job_runner.start_job(pid, "collect_graph", scope={
                    "rev": rev, "partition": {"head": part["head"], "idx": next_idx},
                })
            elif not states.get("confirmed") and not states.get("running"):
                record_graph_baseline(pid, head)
                baseline_recorded = True
                _prune_old_snapshots(pid)
        else:
            record_graph_baseline(pid, head)
            baseline_recorded = True
            _prune_old_snapshots(pid)
            try:
                from .symbols import _resolve_core_pid, record_sync
                core_pid = _resolve_core_pid(root)
                if core_pid:
                    record_sync(core_pid, head)
            except Exception as e:  # noqa: BLE001
                logger.info("[graph-collect] 兼容 record_sync 跳过: %s", e)
    result = {
        "rev": rev, "head": head,
        "files": len(files), "nodes": written["nodes"], "edges": written["edges"],
        "parsed": stats["parsed"], "cached": stats["cached"], "failed": stats["failed"],
        "source": stats["source"], "baselineRecorded": baseline_recorded,
    }
    if part:
        result["partition"] = prow["idx"]
        result["importsResolved"] = stats.get("importsResolved", 0)
    logger.info("[graph-collect] 完成: %s", json.dumps(result, ensure_ascii=False))
    return result


def _next_partition(pid: str, head: str):
    """自链: 下一个 confirmed 分区 idx; 无返回 None。"""
    from ..store.partition import PartitionStore
    for p in PartitionStore.list_rev(pid, head):
        if p.get("state") == "confirmed":
            return p["idx"]
    return None


# 组件三表的写入入口也在此暴露（批B 社区接线直接调；A1 落位）
def save_components(project: str, rev: str, components: List[dict],
                    hierarchy: List[dict]) -> dict:
    return ComponentStore.replace_rev(project, rev, components, hierarchy)


job_runner.register("collect_graph", _job_collect_graph)  # noqa: E305
