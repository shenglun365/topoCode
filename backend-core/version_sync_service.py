"""version_sync_service.py — KB 版本基线 + 增量更新服务（P0 地基）。

职责：
  - 计算当前磁盘文件清单 (manifest, content_hash)
  - 对比上一 KB 基线 manifest，产出文件级 delta (A/M/D)
  - 注册新版本基线 project_versions + 记录 delta project_version_files
  - 活表/历史表 δ 归档：source_files → source_files_history
  - 逐环节影响评估（变更幅度/影响范围），供用户选择更新环节
  - 更新请求状态机（architect 待更新标记 → KB 确认 → 拉代码）
  - VersionViewer：快速重建任意基线 head 的完整文件清单

设计原则（KB 语义）：
  - 只向前，不向后；对比仅在 KB 基线之间，不依赖 git 祖先。
  - delta 一律 = content-hash 文件级 diff，对切分支/force-push 鲁棒。
  - 分析环节的增量执行（AST/图/组件/LLM）属 P1-P3，本模块提供 stage plan 钩子。
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime

from sqlite_ctx import MultiDBManager, SQLiteContext
from core_service import (
    MultiIgnoreParser,
    should_ignore_file,
    build_effective_ignore_patterns,
    _load_import_config,
    IGNORE_FILE_PRIORITY,
    _simple_hash,
)

logger = logging.getLogger(__name__)

# 文件扩展名 → 语言 key（与 core_service._scan_and_import 的 LANG_MAP_FILE 一致）
EXT_LANG = {
    ".ts": "typescript", ".js": "javascript", ".jsx": "javascript", ".tsx": "typescript",
    ".mts": "typescript", ".cts": "typescript", ".mjs": "javascript", ".cjs": "javascript",
    ".py": "python", ".pyw": "python", ".go": "go", ".rs": "rust", ".java": "java",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".hh": "cpp", ".hxx": "cpp", ".cs": "c_sharp", ".vue": "vue", ".html": "html",
    ".css": "css", ".scss": "scss", ".json": "json", ".md": "markdown",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".rb": "ruby", ".rake": "ruby",
    ".php": "php", ".inc": "php", ".swift": "swift", ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala", ".sc": "scala", ".r": "r", ".sql": "sql", ".sh": "bash",
    ".dart": "dart", ".lua": "lua", ".luau": "luau", ".m": "objc", ".mm": "objc",
    ".perl": "perl", ".pl": "perl", ".elixir": "elixir", ".ex": "elixir",
    ".exs": "elixir", ".erl": "erlang", ".hs": "haskell", ".ml": "ocaml",
    ".zig": "zig", ".nim": "nim", ".v": "verilog",
}

# P0 可识别的分析环节（P1-P3 逐步实现增量执行）
STAGE_KEYS = ["ast", "graph", "presummary", "community", "llm"]
# 默认建议环节（文件级联动必更）
DEFAULT_STAGES = {"ast": True, "graph": True, "presummary": True,
                  "community": False, "llm": False}
# 默认执行环节（version.sync 未传 stages 时的兜底：仅已实现的必更环节）
DEFAULT_SYNC_STAGES = {"ast": True, "graph": True, "presummary": False,
                       "community": False, "llm": False}

# 版本 id 单调递增（词法序 = 创建序），供 version_from/version_to 区间比较
_version_seq = 0


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _new_version_id() -> str:
    global _version_seq
    _version_seq += 1
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"ver-{ts}-{_version_seq:06d}-{uuid.uuid4().hex[:4]}"


def _ts() -> str:
    return datetime.now().isoformat()


def _to_camel(key: str) -> str:
    parts = key.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _camel_row(row: dict) -> dict:
    """snake_case DB 行 → camelCase（对外契约形状）。"""
    if not row:
        return row
    return {_to_camel(k): v for k, v in row.items()}


def _md5_file(path: str) -> str:
    import hashlib
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (PermissionError, OSError):
        return ""


def _rel_name(rel_path: str) -> str:
    base = rel_path.rsplit('/', 1)[-1]
    if '.' in base:
        return base.rsplit('.', 1)[0]
    return base


def compute_manifest(root: str, main_db) -> dict:
    """扫描磁盘根目录，返回 {rel_path: {content_hash, size, language, file_name, mtime}}。

    应用系统导入配置 + 多 ignore 文件（.gitignore 等）。
    """
    manifest: dict = {}
    if not root or not os.path.isdir(root):
        return manifest

    import_config = _load_import_config(main_db)
    extra_patterns = build_effective_ignore_patterns(import_config)
    parser = MultiIgnoreParser()
    try:
        ignore_filenames = IGNORE_FILE_PRIORITY + import_config.get("extra_ignore_files", [])
        parser.load_files(root, ignore_filenames)
    except Exception as e:
        logger.warning(f"[manifest] ignore file load failed: {e}")

    try:
        for dirpath, dirnames, filenames in os.walk(root):
            rel_root = os.path.relpath(dirpath, root)
            # KB 元数据目录永不索引；.git 为仓库元数据
            if rel_root == ".topocode" or rel_root == ".git":
                dirnames[:] = []
                continue
            dirnames[:] = [
                d for d in dirnames
                if not should_ignore_file(os.path.join(rel_root, d) if rel_root != '.' else d,
                                          parser, is_dir=True, extra_patterns=extra_patterns)
            ]
            for filename in filenames:
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, root).replace('\\', '/')
                if rel.startswith(".topocode/") or rel.startswith(".git/"):
                    continue
                if should_ignore_file(rel, parser, extra_patterns=extra_patterns):
                    continue
                try:
                    st = os.stat(full)
                    size = int(st.st_size)
                    mtime = float(st.st_mtime)
                except OSError:
                    size = 0
                    mtime = 0.0
                ext = os.path.splitext(filename)[1].lower()
                manifest[rel] = {
                    "content_hash": _md5_file(full),
                    "size": size,
                    "language": EXT_LANG.get(ext, ""),
                    "file_name": _rel_name(rel),
                    "mtime": mtime,
                }
    except PermissionError:
        pass
    return manifest


def read_latest_manifest(project_db: SQLiteContext) -> dict:
    """读取活表 source_files 作为上一基线 manifest（含 version_from）。

    仅取文件行（排除 language='directory' 的目录节点），与 compute_manifest 一致。
    """
    rows = project_db.fetchall(
        "SELECT file_path, content_hash, size, language, file_name, mtime, version_from "
        "FROM source_files WHERE language != 'directory'"
    )
    out = {}
    for r in rows:
        out[r["file_path"]] = {
            "content_hash": r["content_hash"] or "",
            "size": r["size"] or 0,
            "language": r["language"] or "",
            "file_name": r["file_name"] or "",
            "mtime": r["mtime"] or 0,
            "vfrom": r["version_from"],
        }
    return out


def diff_manifests(old: dict, new: dict) -> dict:
    """content-hash 文件级 diff → {'added': [], 'modified': [], 'deleted': []}"""
    added, modified, deleted = [], [], []
    for path, meta in new.items():
        if path not in old:
            added.append(path)
        elif old[path].get("content_hash") != meta.get("content_hash"):
            modified.append(path)
    for path in old:
        if path not in new:
            deleted.append(path)
    return {"added": added, "modified": modified, "deleted": deleted}


def _latest_done_task(main_db, project_id: str) -> dict | None:
    row = main_db.fetchone(
        """SELECT * FROM analysis_tasks
           WHERE project_id = ? AND status = 'done'
           ORDER BY updated_at DESC LIMIT 1""",
        (project_id,),
    )
    return row


def _changed_node_ids(project_db, task_id: str, paths: set) -> set:
    if not task_id:
        return set()
    ids = set()
    for p in paths:
        rows = project_db.fetchall(
            "SELECT id FROM graph_node WHERE task_id = ? AND file_path = ?",
            (task_id, p),
        )
        ids.update(r["id"] for r in rows)
    return ids


def build_stage_plan(project_id: str, project_db: SQLiteContext, main_db,
                     delta: dict, branch_switched: bool) -> dict:
    """逐环节影响评估（变更幅度/影响范围）。"""
    changed = set(delta["added"]) | set(delta["modified"])
    removed = set(delta["deleted"])

    task = _latest_done_task(main_db, project_id)
    task_id = task["id"] if task else ""
    node_ids = _changed_node_ids(project_db, task_id, changed | removed)

    # 社区影响：最新任务的社区中，node_list 触及变更符号的社区
    affected_comms = []
    if task_id and node_ids:
        try:
            rows = project_db.fetchall(
                """SELECT task_id, edge_type, comm_lv, comm_id, node_list
                   FROM graph_doc WHERE task_id = ?""",
                (task_id,),
            )
            for r in rows:
                try:
                    nodes = json.loads(r["node_list"] or "[]")
                except (TypeError, ValueError):
                    nodes = []
                inter = set(nodes) & node_ids
                if inter:
                    affected_comms.append({
                        "edgeType": r["edge_type"],
                        "commLv": r["comm_lv"],
                        "commId": r["comm_id"],
                        "touchedNodes": len(inter),
                    })
        except Exception as e:
            logger.warning(f"[stage_plan] community impact failed: {e}")

    parseable = [p for p in changed if os.path.splitext(p)[1].lower() in EXT_LANG]
    changed_count = len(changed)
    removed_count = len(removed)
    magnitude = changed_count + removed_count

    # 风险等级：按变化量 + 社区波及面
    risk = "low"
    if magnitude >= 200 or (len(affected_comms) >= 20 and changed_count >= 100):
        risk = "high"
    elif magnitude >= 50 or len(affected_comms) >= 5:
        risk = "medium"

    return {
        "delta": {
            "added": delta["added"],
            "modified": delta["modified"],
            "deleted": delta["deleted"],
            "addedCount": len(delta["added"]),
            "modifiedCount": len(delta["modified"]),
            "deletedCount": len(delta["deleted"]),
            "total": magnitude,
        },
        "branchSwitched": branch_switched,
        "changeType": "major" if branch_switched else "minor",
        "risk": risk,
        "impact": {
            "ast": {"filesToParse": len(parseable), "removedFiles": removed_count},
            "graph": {"nodeIdsAffected": len(node_ids)},
            "presummary": {"filesToSummarize": len(parseable)},
            "community": {
                "affectedCommunities": len(affected_comms),
                "communities": affected_comms[:50],
                "reclusterSuggested": risk in ("high", "medium"),
            },
            "llm": {"filesToResummarize": len(parseable),
                    "communitiesToReanalyze": len(affected_comms)},
        },
        "stages": {
            "ast": {"suggested": True, "implemented": True},
            "graph": {"suggested": True, "implemented": True},
            "presummary": {"suggested": True, "implemented": False},
            "community": {"suggested": risk in ("high", "medium"),
                          "implemented": False},
            "llm": {"suggested": False, "implemented": False},
        },
    }


def _archive_and_apply(project_db: SQLiteContext, old: dict, new: dict,
                       new_version_id: str) -> int:
    """δ 归档 + 活表更新 source_files。

    返回归档行数。
    """
    delta = diff_manifests(old, new)
    hist = "source_files_history"
    archived = 0

    def _copy_to_hist(row_meta, vfrom, vto):
        nonlocal archived
        path = row_meta["file_path"]
        project_db.execute(
            f"""INSERT OR REPLACE INTO {hist}
                (id, file_path, file_name, language, size, content_hash,
                 hashcode, parent_path, mtime, version_from, version_to)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_new_id("sfh"), path,
             row_meta.get("file_name") or _rel_name(path),
             row_meta.get("language") or "",
             row_meta.get("size") or 0,
             row_meta.get("content_hash") or "",
             "",
             "",
             row_meta.get("mtime") or 0,
             vfrom, vto),
        )
        archived += 1

    # 删除的旧文件 → 历史 (version_to = new)
    for path in delta["deleted"]:
        row = old[path]
        _copy_to_hist({"file_path": path, **row}, row.get("vfrom"), new_version_id)
        project_db.execute("DELETE FROM source_files WHERE file_path = ?", (path,))

    # 修改的旧文件 → 历史，然后写新行
    for path in delta["modified"]:
        row = old[path]
        _copy_to_hist({"file_path": path, **row}, row.get("vfrom"), new_version_id)
        project_db.execute("DELETE FROM source_files WHERE file_path = ?", (path,))
        _upsert_file(project_db, path, new[path], new_version_id)

    # 新增文件
    for path in delta["added"]:
        _upsert_file(project_db, path, new[path], new_version_id)

    return archived


def _upsert_file(project_db, path: str, meta: dict, version_id: str) -> None:
    project_db.execute(
        """INSERT OR REPLACE INTO source_files
           (id, file_path, file_name, language, size, content_hash, parent_path, mtime, version_from)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (f"file-{_simple_hash(path)}", path,
         meta.get("file_name") or _rel_name(path),
         meta.get("language") or "",
         meta.get("size") or 0,
         meta.get("content_hash") or "",
         path.rsplit('/', 1)[0] if '/' in path else None,
         meta.get("mtime") or 0,
         version_id),
    )


def register_version(multi_db: MultiDBManager, project_id: str, *,
                     branch: str = "", head: str = "", label: str = "",
                     change_type: str = "minor", parent_version_id: str | None = None,
                     delta: dict | None = None, is_baseline: bool = False) -> dict:
    """注册新版本基线，记录 delta 文件列表，更新 projects.current_version_id。"""
    main_db = multi_db.main_db
    vid = _new_version_id()
    now = _ts()
    main_db.insert("project_versions", {
        "id": vid,
        "project_id": project_id,
        "parent_version_id": parent_version_id,
        "label": label,
        "branch": branch,
        "head": head,
        "change_type": change_type,
        "file_count": len(delta["added"]) + len(delta["modified"]) if delta else 0,
        "added_count": len(delta["added"]) if delta else 0,
        "modified_count": len(delta["modified"]) if delta else 0,
        "deleted_count": len(delta["deleted"]) if delta else 0,
        "is_baseline": 1 if is_baseline else 0,
        "metadata": json.dumps({"synced_at": now}),
        "created_at": now,
    })

    if delta:
        records = []
        for change_type_, path in (
            [("A", p) for p in delta["added"]] +
            [("M", p) for p in delta["modified"]] +
            [("D", p) for p in delta["deleted"]]
        ):
            records.append((_new_id("pvf"), vid, project_id, change_type_, path))
        if records:
            main_db.executemany(
                """INSERT INTO project_version_files (id, version_id, project_id, change_type, file_path)
                   VALUES (?, ?, ?, ?, ?)""",
                records,
            )

    main_db.update("projects", {"current_version_id": vid}, "id = ?", (project_id,))
    return {
        "id": vid,
        "projectId": project_id,
        "branch": branch,
        "head": head,
        "changeType": change_type,
        "parentVersionId": parent_version_id,
        "createdAt": now,
    }


def sync(multi_db: MultiDBManager, project_id: str, *,
         branch: str = "", head: str = "", label: str = "",
         stages: dict | None = None, force: bool = False,
         request_id: str | None = None, task_id: str | None = None) -> dict:
    """执行一次 KB 基线更新（增量 δ 归档）。

    1. 读上一基线 manifest（source_files 活表）
    2. 扫描当前磁盘 manifest
    3. content-hash diff → delta
    4. 归档过期行到 source_files_history + 更新活表
    5. 注册新版本 + 记录 delta
    6. 返回 stage plan（P1-P3 将据此执行增量分析）
    """
    main_db = multi_db.main_db
    project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise ValueError(f"Project not found: {project_id}")

    project_db = multi_db.get_project_db(project_id)
    root = project["root_path"]
    if not root or not os.path.isdir(root):
        raise ValueError(f"Project root not a directory: {root}")

    old_manifest = read_latest_manifest(project_db)
    new_manifest = compute_manifest(root, main_db)

    delta = diff_manifests(old_manifest, new_manifest)

    # 分支切换判定（major）
    latest = main_db.fetchone(
        "SELECT * FROM project_versions WHERE project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (project_id,),
    )
    branch_switched = False
    if latest and branch and latest["branch"] and latest["branch"] != branch:
        branch_switched = True
    total_changed = len(delta["added"]) + len(delta["modified"]) + len(delta["deleted"])
    change_type = "major" if branch_switched else "minor"

    # 无内容变化且无分支/基线切换 → 直接返回（不产生新版本）
    if total_changed == 0 and not branch_switched and not force:
        if request_id:
            main_db.execute(
                "UPDATE project_update_requests SET status = 'done', updated_at = ? WHERE id = ?",
                (_ts(), request_id),
            )
            main_db.conn.commit()
        return {
            "changed": False,
            "projectId": project_id,
            "message": "no code changes detected",
            "versionId": project.get("current_version_id"),
        }

    new_version_id = _new_version_id()
    archived = _archive_and_apply(project_db, old_manifest, new_manifest, new_version_id)
    project_db.conn.commit()

    version = register_version(
        multi_db, project_id,
        branch=branch or (latest["branch"] if latest else ""),
        head=head or (latest["head"] if latest else ""),
        label=label,
        change_type=change_type,
        parent_version_id=latest["id"] if latest else None,
        delta=delta,
    )

    stage_plan = build_stage_plan(project_id, project_db, main_db, delta, branch_switched)
    stage_plan["delta"] = delta

    # 逐环节增量执行（P1: ast/graph 已实现；presummary/community/llm 为 planned 占位）
    incremental_results = {}
    if total_changed > 0:
        selected = stages or dict(DEFAULT_SYNC_STAGES)
        if any(v for k, v in selected.items() if k in ("ast", "graph", "presummary", "community", "llm")):
            target_task = task_id or _latest_done_task(main_db, project_id)
            if target_task:
                try:
                    import incremental_runner
                    incremental_results = incremental_runner.apply_incremental(
                        multi_db, project_id,
                        target_task["id"] if isinstance(target_task, dict) else target_task,
                        delta, selected, proj_path=root)
                except Exception as e:
                    logger.warning(f"[version.sync] incremental stages failed: {e}")

    logger.info(
        f"[version.sync] {project_id} -> {version['id']} "
        f"({len(delta['added'])}A/{len(delta['modified'])}M/{len(delta['deleted'])}D) "
        f"change_type={change_type} archived={archived} stages={list(incremental_results)}"
    )

    if request_id:
        main_db.execute(
            "UPDATE project_update_requests SET status = 'done', result_version_id = ?, updated_at = ? WHERE id = ?",
            (version["id"], _ts(), request_id),
        )
        main_db.conn.commit()

    return {
        "changed": True,
        "projectId": project_id,
        "version": version,
        "delta": delta,
        "archivedRows": archived,
        "stagePlan": stage_plan,
        "stagesRequested": stages or DEFAULT_STAGES,
        "incrementalResults": incremental_results,
        "requestId": request_id,
    }


def preview(multi_db: MultiDBManager, project_id: str, *,
            branch: str = "", head: str = "") -> dict:
    """预览变更幅度/影响范围，不写入任何数据。"""
    main_db = multi_db.main_db
    project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise ValueError(f"Project not found: {project_id}")
    project_db = multi_db.get_project_db(project_id)
    root = project["root_path"]
    old_manifest = read_latest_manifest(project_db)
    new_manifest = compute_manifest(root, main_db) if os.path.isdir(root) else {}
    delta = diff_manifests(old_manifest, new_manifest)

    latest = main_db.fetchone(
        "SELECT * FROM project_versions WHERE project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (project_id,),
    )
    branch_switched = bool(latest and branch and latest["branch"] and latest["branch"] != branch)
    plan = build_stage_plan(project_id, project_db, main_db, delta, branch_switched)
    plan["delta"] = delta
    plan["latest"] = {
        "versionId": latest["id"] if latest else None,
        "branch": latest["branch"] if latest else "",
        "head": latest["head"] if latest else "",
    }
    return plan


def list_versions(multi_db: MultiDBManager, project_id: str) -> list:
    main_db = multi_db.main_db
    rows = main_db.fetchall(
        "SELECT * FROM project_versions WHERE project_id = ? ORDER BY created_at DESC, rowid DESC",
        (project_id,),
    )
    return [_camel_row(dict(r)) for r in rows]


def get_version(multi_db: MultiDBManager, project_id: str, version_id: str) -> dict:
    main_db = multi_db.main_db
    version = main_db.fetchone(
        "SELECT * FROM project_versions WHERE id = ? AND project_id = ?",
        (version_id, project_id),
    )
    if not version:
        raise ValueError(f"Version not found: {version_id}")
    files = main_db.fetchall(
        "SELECT change_type, file_path FROM project_version_files WHERE version_id = ?",
        (version_id,),
    )
    version = _camel_row(dict(version))
    version["files"] = [{"changeType": f["change_type"], "filePath": f["file_path"]} for f in files]
    return version


def materialize(multi_db: MultiDBManager, project_id: str, version_id: str) -> list:
    """重建任意基线 head 的完整文件清单。

    活表(version_from<=V) UNION 历史(version_from<=V AND version_to>V)。
    """
    project_db = multi_db.get_project_db(project_id)
    live = project_db.fetchall(
        "SELECT file_path, content_hash, language, size, file_name FROM source_files "
        "WHERE version_from IS NULL OR version_from <= ?",
        (version_id,),
    )
    hist = project_db.fetchall(
        "SELECT file_path, content_hash, language, size, file_name FROM source_files_history "
        "WHERE (version_from IS NULL OR version_from <= ?) AND (version_to IS NULL OR version_to > ?)",
        (version_id, version_id),
    )
    merged: dict = {}
    for r in live:
        merged[r["file_path"]] = r
    for r in hist:
        merged[r["file_path"]] = r
    # 活表优先（同路径取活表 = 较新且仍在用的行）
    files = list(merged.values())
    files.sort(key=lambda r: r["file_path"])
    return files


def diff_versions(multi_db: MultiDBManager, project_id: str,
                  from_id: str, to_id: str) -> dict:
    """对比两个 KB 基线的文件级差异（P0 为 manifest 级；P1+ 扩展分析差异）。"""
    from_files = {r["file_path"]: r for r in materialize(multi_db, project_id, from_id)}
    to_files = {r["file_path"]: r for r in materialize(multi_db, project_id, to_id)}
    d = diff_manifests(from_files, to_files)
    return {
        "fromVersion": from_id,
        "toVersion": to_id,
        "added": d["added"],
        "modified": d["modified"],
        "deleted": d["deleted"],
        "addedCount": len(d["added"]),
        "modifiedCount": len(d["modified"]),
        "deletedCount": len(d["deleted"]),
    }


# ── 更新请求状态机（architect → KB 待更新标记）──────────────

def pull_request(multi_db: MultiDBManager, project_id: str, *,
                 repo_url: str = "", local_repo_path: str = "",
                 branch: str = "", head: str = "", note: str = "",
                 source: str = "architect") -> dict:
    """architect 发起基线更新请求（仅写待更新标记，不执行）。"""
    main_db = multi_db.main_db
    project = main_db.fetchone("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise ValueError(f"Project not found: {project_id}")
    rid = _new_id("pur")
    main_db.insert("project_update_requests", {
        "id": rid,
        "project_id": project_id,
        "source": source,
        "repo_url": repo_url,
        "local_repo_path": local_repo_path,
        "branch": branch,
        "head": head,
        "status": "pending",
        "note": note,
        "created_at": _ts(),
        "updated_at": _ts(),
    })
    return {"requestId": rid, "projectId": project_id, "status": "pending"}


def pending_updates(multi_db: MultiDBManager, project_id: str | None = None) -> list:
    main_db = multi_db.main_db
    if project_id:
        rows = main_db.fetchall(
            "SELECT * FROM project_update_requests WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
    else:
        rows = main_db.fetchall(
            "SELECT * FROM project_update_requests WHERE status = 'pending' ORDER BY created_at DESC"
        )
    return [_camel_row(dict(r)) for r in rows]


def cancel_update(multi_db: MultiDBManager, request_id: str) -> bool:
    main_db = multi_db.main_db
    cur = main_db.execute(
        "UPDATE project_update_requests SET status = 'cancelled', updated_at = ? WHERE id = ? AND status = 'pending'",
        (_ts(), request_id),
    )
    main_db.conn.commit()
    return cur.rowcount > 0


def confirm_update(multi_db: MultiDBManager, request_id: str, method: str = "pull") -> dict:
    """KB 界面确认更新请求第一步：拉取新代码（pull/worktree），不执行分析。

    返回预览（变更幅度/影响范围），由用户选择更新环节后再调 version.sync 执行。
    """
    import git_service

    main_db = multi_db.main_db
    req = main_db.fetchone("SELECT * FROM project_update_requests WHERE id = ?", (request_id,))
    if not req:
        raise ValueError(f"Update request not found: {request_id}")
    if req["status"] != "pending":
        raise ValueError(f"Update request already {req['status']}")

    project_id = req["project_id"]
    project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise ValueError(f"Project not found: {project_id}")

    branch = req["branch"] or ""
    head = req["head"] or ""
    root = project["root_path"]
    resolved_head = head

    if project["import_mode"] in ("git-local", "git-remote") and os.path.isdir(root):
        if method == "worktree":
            cache_dir = multi_db.source_cache_dir_for(project_id)
            wt_dir = os.path.join(cache_dir, "worktrees", (branch or "default"))
            resolved_head = git_service.worktree(root, branch or "main", wt_dir, head=head)
            main_db.update("projects", {"root_path": wt_dir}, "id = ?", (project_id,))
            root = wt_dir
        else:
            resolved_head = git_service.checkout_ref(root, branch or None, head or None, method="pull")
    else:
        # static 项目：无 git 拉取，直接重扫（branch/head 仅作标签）
        resolved_head = head

    main_db.execute(
        "UPDATE project_update_requests SET status = 'confirmed', method = ?, updated_at = ? WHERE id = ?",
        (method, _ts(), request_id),
    )
    main_db.conn.commit()

    plan = preview(multi_db, project_id, branch=branch or None, head=resolved_head or None)
    plan["projectId"] = project_id
    plan["requestId"] = request_id
    plan["branch"] = branch
    plan["head"] = resolved_head or ""
    return plan
