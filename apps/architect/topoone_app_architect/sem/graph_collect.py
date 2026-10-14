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

    公共服务直调(用户裁决: 与 KB 同一套代码, 不复刻不分叉)——
    topoone.engine.semantic_service.run_pipeline = analyst_runner 原函数
    _step1.._step5 薄编排, 图+UNIFIED 组件树(L0~L5)一次产出, 内存即抛。"""
    from topoone.engine.semantic_service import run_pipeline
    res = run_pipeline(root, files or [])
    if res.get("error"):
        raise RuntimeError(f"semantic pipeline failed: {res['error']}")
    nodes = res.get("nodes") or []
    edges = []
    for e in res.get("edges") or []:
        edges.append({
            "source": e.get("source_id") or e.get("source") or "",
            "target": e.get("target_id") or e.get("target") or "",
            "kind": e.get("kind") or "", "line": int(e.get("line") or 0),
            "col": int(e.get("col") or 0),
        })
    stats = {
        "parsed": int((res.get("counts") or {}).get("parsed") or 0),
        "cached": 0,
        "failed": int((res.get("counts") or {}).get("skipped") or 0),
        "source": "pipeline",
        "components": res.get("components") or [],
        "levels": res.get("levels") or 0,
    }
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


def _prune_old_snapshots(pid: str, keep: int = 2) -> None:
    """采集完成即修剪旧快照: 组件三表+图节点/边只留最近 keep 个 rev
    (当前+上一版 DIFF 基准), 更旧快照清理(用户裁决: 刷新后不留陈旧组件信息)。"""
    try:
        from ..store.graph import ComponentStore, GraphStore
        n1 = ComponentStore.prune_old_revs(pid, keep=keep)
        n2 = GraphStore.prune_old_revs(pid, keep=keep)
        if n1 or n2:
            logger.info("[graph-collect] 修剪旧快照: 组件行 -%s, 图 rev -%s", n1, n2)
    except Exception as e:  # noqa: BLE001
        logger.warning("[graph-collect] 快照修剪失败(不阻塞): %s", e)


def _job_collect_graph(ctx: JobCtx) -> dict:
    """作业体：kind=collect_graph(采集+分组合一)。

    scope: {files?: [], rev?: str, anchorHead?: str}。语义管线(与 KB 同一套
    代码)产出图+组件树 → 图快照落 arch_graph_node/edge, 组件树全层级落
    arch_components/hierarchy, 记基线锚 + 修剪旧快照。"""
    from ..arch_routes.project import resolve_project
    from .paths import resolve_root

    scope = ctx.scope
    pid = ctx.pid
    proj_row = resolve_project(None, pid) or {}
    root = resolve_root(proj_row.get("rootPath") or None, pid)
    if not root:
        return {"error": "root 解析失败"}

    files = scope.get("files") or list_code_files(root)
    if not files:
        return {"nodes": 0, "edges": 0, "files": 0, "note": "无代码文件"}
    incremental = bool(scope.get("incremental")) and bool(scope.get("files"))
    rev = scope.get("rev") or ""
    anchor_head = (scope.get("anchorHead") or "").strip()
    if incremental:
        # 遗留#3 增量: 在当前基线快照上按文件合入(无基线→回落全量语义)
        try:
            from .graph_context import baseline_rev as _br
            rev = _br(pid).get("rev") or ""
        except Exception:  # noqa: BLE001
            rev = ""
        if not rev:
            incremental = False
    if not rev:
        head = anchor_head or _git_head(root)
        rev = f"baseline:{head}" if head else "workspace"

    ctx.progress(total=3, done=0, current="语义管线(解析→符号→关系→社区)")

    nodes, edges, stats = collect_snapshot(root, pid, files, rev)
    written = (GraphStore.merge_files(pid, rev, files, nodes, edges)
               if incremental else GraphStore.replace_rev(pid, rev, nodes, edges))

    if incremental:
        # 增量收敛: 组件树/基线锚不动(全量刷新时重建)——受影响资产清单
        # (assets_of_files)独立于组件树可用
        return {"rev": rev, "files": len(files), "nodes": written["nodes"],
                "edges": written["edges"], "incremental": True,
                "removedNodes": written.get("removedNodes", 0),
                "removedEdges": written.get("removedEdges", 0),
                "parsed": stats["parsed"], "cached": stats["cached"],
                "failed": stats["failed"], "source": stats["source"]}
    ctx.progress(total=3, done=2, current="组件树落库")
    comps, hier = [], []
    for c in stats.get("components") or []:
        cid = c.get("commId")
        if not cid:
            continue
        lvl = str(c.get("level") or "L0")
        comps.append({
            "id": cid, "name": cid, "summary": "",
            "owns": c.get("files") or [], "source": "community",
        })
        hier.append({
            "childId": cid, "parentId": c.get("parentId") or "",
            "level": int(lvl[1:]) if lvl[1:].isdigit() else 0,
        })
    comp_written = ComponentStore.replace_rev(pid, rev, comps, hier)

    head = anchor_head or _git_head(root)
    baseline_recorded = False
    if head:
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
        "group": {"components": comp_written["components"],
                  "hierarchy": comp_written["hierarchy"],
                  "levels": stats.get("levels") or 0},
    }
    logger.info("[graph-collect] 完成: %s", json.dumps(result, ensure_ascii=False)[:300])
    return result






# 组件三表的写入入口也在此暴露（批B 社区接线直接调；A1 落位）
def save_components(project: str, rev: str, components: List[dict],
                    hierarchy: List[dict]) -> dict:
    return ComponentStore.replace_rev(project, rev, components, hierarchy)


job_runner.register("collect_graph", _job_collect_graph)  # noqa: E305
