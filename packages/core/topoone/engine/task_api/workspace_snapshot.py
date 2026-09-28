"""workspace.snapshot — 工作区(非基线)符号快照 RPC(无状态, 只读)。

定位: architect 双通道(codegraph/KB)中 KB 侧的工作区实时认知源。
与基线分析的本质差异(勿合并):
- **零持久化**: 不建 analysis_task、不写 graph_node — 按需解析即返回,
  不污染任务列表与基线视图(分析任务表的幽灵任务是反例)。
- **锚点显式**: base..工作区 的变更口径由调用方/基线注册表显式给出,
  与 version.sync 的基线 delta 语义互不干涉。

复用 incremental_runner._parse_one_file(与增量同解析器);
节点 ID 由 A1 稳定契约保证 — 快照 ID 与基线图谱可直接对齐跟踪。
"""
from __future__ import annotations

import logging
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)

_MAX_SNAPSHOT_FILES = 2000   # 单次快照文件上限(防大 diff 雪崩)


def _git(root: str, args: list, timeout: float = 20.0) -> Optional[str]:
    try:
        p = subprocess.run(['git', '-C', root] + args,
                           capture_output=True, text=True, timeout=timeout)
        return p.stdout if p.returncode == 0 else None
    except Exception:
        return None


def _changed_files(root: str, base: str) -> List[str]:
    """base..HEAD 变更 ∪ 工作区未提交(含 untracked) — 工作区实时口径。"""
    out: List[str] = []
    if base:
        diff = _git(root, ['diff', '--name-only', f'{base}..HEAD', '--'])
        if diff:
            out.extend(l.strip() for l in diff.splitlines() if l.strip())
    status = _git(root, ['status', '--porcelain', '--untracked-files=all'])
    if status:
        for line in status.splitlines():
            line = line.strip()
            if not line:
                continue
            # XY path (XY 两位状态码; 重命名 "R  old -> new" 取新路径)
            path = line[3:] if len(line) > 3 else ''
            if ' -> ' in path:
                path = path.split(' -> ')[-1]
            path = path.strip('"')
            if path:
                out.append(path)
    # 去重保序
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _snapshot_nodes(root: str, files: List[str]) -> List[dict]:
    from topoone.engine.incremental_runner import _parse_one_file
    from topoone.engine.version_sync_service import EXT_LANG
    import os
    nodes: List[dict] = []
    for path in files[:_MAX_SNAPSHOT_FILES]:
        ext = os.path.splitext(path)[1].lower()
        lang = EXT_LANG.get(ext, "")
        if not lang:
            continue
        try:
            table = _parse_one_file(os.path.join(root, path), lang, root)
        except Exception as e:
            logger.warning("[workspace.snapshot] parse failed %s: %s", path, e)
            continue
        if not table:
            continue
        for n in table.nodes:
            nodes.append({
                "id": n.id, "kind": n.kind.value if hasattr(n.kind, 'value') else str(n.kind),
                "name": n.name, "qualifiedName": n.qualified_name,
                "file": table.file_path, "language": table.language or lang,
                "startLine": n.start_line, "endLine": n.end_line,
                "isExported": bool(n.is_exported),
            })
    return nodes


def workspace_snapshot(multi_db, project_id: str, files: Optional[List[str]] = None,
                       base: str = "") -> dict:
    """工作区符号快照。files 显式给出则只解析之; 否则按 base(缺省=当前基线
    commit)..工作区 的变更文件集解析。"""
    main_db = multi_db.main_db
    proj = main_db.fetchone(
        "SELECT id, root_path FROM projects WHERE id = ?", (project_id,))
    if not proj:
        raise ValueError(f"Project not found: {project_id}")
    root = proj["root_path"]
    if not root:
        raise ValueError("project root_path empty")

    resolved_base = (base or "").strip()
    if not resolved_base:
        row = main_db.fetchone(
            "SELECT baseline_commit FROM project_versions WHERE project_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1", (project_id,))
        resolved_base = ((row or {}).get("baseline_commit") or "").strip()

    explicit = [str(f) for f in (files or []) if f]
    if explicit:
        target, changed = explicit, None
    else:
        changed = _changed_files(root, resolved_base)
        target = changed

    nodes = _snapshot_nodes(root, target)
    return {
        "projectId": project_id,
        "base": resolved_base,
        "explicitFiles": bool(explicit),
        "filesRequested": len(target),
        "truncated": bool(changed is not None and len(changed) > _MAX_SNAPSHOT_FILES),
        "nodeCount": len(nodes),
        "nodes": nodes,
    }


def register_workspace_methods(server, multi_db) -> None:
    @server.register("workspace.snapshot")
    def ws_snapshot(project_id=None, projectId=None, files=None, base=""):
        return workspace_snapshot(multi_db, project_id or projectId,
                                  files=files, base=base or "")
