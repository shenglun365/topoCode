"""基线视图(Baseline View) —— KB 项目对外唯一生效视图。

设计契约(kb-view-plan)：
- 外部调用方(architect 等)只按 projectId 请求，**零任务感知**；
- 项目内任务轴保持自由(允许重复/交叉任务，任务管理 analysis.* 仅 KB 内部使用)；
- 任务必须显式挂载(view.mount)才进入基线视图；挂载时做**严格重合检测**
  (与已挂载任务的实际覆盖文件交集非空即拒绝，force=true 强制并标记 overlapWarned)；
- architecture.catalog/model 等对外读取经视图解析任务，多个挂载任务分区拼凑项目全貌
  (大项目受 5000 源码文件分析上限拆成多个平行任务的场景)；
- 视图带覆盖率统计(挂载任务覆盖文件并集 / source_files 总数)与 stale 标记
  (存在未挂载的更新 done 任务)。
"""
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── 内部工具 ─────────────────────────────────────────────────────

def _ensure_view(main_db, project_id: str) -> dict:
    """取视图行，不存在则创建(视图随项目唯一，惰性创建)。"""
    row = main_db.fetchone("SELECT * FROM project_views WHERE project_id = ?", (project_id,))
    if row:
        return dict(row)
    main_db.execute(
        "INSERT OR IGNORE INTO project_views (project_id, version, published_at, updated_at) "
        "VALUES (?, 1, ?, ?)", (project_id, _now(), _now()))
    main_db.commit()
    row = main_db.fetchone("SELECT * FROM project_views WHERE project_id = ?", (project_id,))
    return dict(row) if row else {}


def _bump(main_db, project_id: str, overlap_warned: bool = None):
    """视图变更：版本号自增 + 时间戳刷新。"""
    if overlap_warned is None:
        main_db.execute(
            "UPDATE project_views SET version = version + 1, published_at = ?, updated_at = ? "
            "WHERE project_id = ?", (_now(), _now(), project_id))
    else:
        main_db.execute(
            "UPDATE project_views SET version = version + 1, published_at = ?, updated_at = ?, "
            "overlap_warned = ? WHERE project_id = ?",
            (_now(), _now(), 1 if overlap_warned else 0, project_id))
    main_db.commit()


def _mounts(main_db, project_id: str) -> list:
    return [dict(r) for r in main_db.fetchall(
        "SELECT task_id, mounted_files, mounted_at FROM view_mounts "
        "WHERE project_id = ? ORDER BY mounted_at", (project_id,))]


def _task_row(main_db, task_id: str) -> dict:
    row = main_db.fetchone(
        "SELECT id, project_id, name, status, scopes, extensions, exclude_dirs, created_at "
        "FROM analysis_tasks WHERE id = ?", (task_id,))
    return dict(row) if row else {}


def _task_selected_files(project_db, task_row: dict) -> set:
    """任务「选择」的源码文件集：按任务声明的 scopes/extensions/exclude_dirs
    过滤 source_files(与 analyst_runner 解析入口同口径)。"""
    if not task_row:
        return set()
    try:
        from .store.analysis_store import AnalysisStore
        scopes = _json_list(task_row.get("scopes")) or (
            [task_row.get("scope")] if task_row.get("scope") else [])
        a_store = AnalysisStore(project_db)
        rows = a_store.list_source_files(
            scopes=scopes,
            extensions=_json_list(task_row.get("extensions")),
            exclude_dirs=_json_list(task_row.get("exclude_dirs")),
        )
        return {r["file_path"] for r in rows if r.get("file_path")}
    except Exception:
        return set()


def _task_files(project_db, task_id: str) -> set:
    """任务实际覆盖文件集：graph_node 出现过的全部 file_path(去重)。"""
    try:
        rows = project_db.fetchall(
            "SELECT DISTINCT file_path FROM graph_node WHERE task_id = ? AND file_path != ''",
            (task_id,))
        return {r["file_path"] for r in rows}
    except Exception:
        return set()


def _total_source_files(project_db) -> int:
    try:
        row = project_db.fetchone("SELECT COUNT(*) AS c FROM source_files")
        return int(row["c"]) if row else 0
    except Exception:
        return 0


def _json_list(raw) -> list:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return raw
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


# ── 对外解析入口(catalog/model 消费) ─────────────────────────────

def resolve_view_task_ids(multi_db, project_id: str) -> list:
    """基线视图挂载任务列表(挂载顺序)。空 = 视图未挂载，外部读取应为空。"""
    if not project_id:
        return []
    try:
        main_db = multi_db.main_db
        return [m["task_id"] for m in _mounts(main_db, project_id)]
    except Exception as e:
        logger.warning("[view] resolve_mounted failed for %s: %s", project_id, e)
        return []


def view_summary(multi_db, project_id: str) -> dict:
    """视图元数据摘要(嵌入 architecture.catalog/model 响应，调用方可感知代际)。"""
    out = {"mountedTaskIds": [], "viewVersion": 0, "publishedAt": "",
           "stale": False, "coveragePct": None}
    if not project_id:
        return out
    try:
        st = view_status(multi_db, project_id)
    except Exception as e:
        logger.warning("[view] summary failed for %s: %s", project_id, e)
        return out
    out.update({
        "mountedTaskIds": [m["taskId"] for m in st.get("mounted") or []],
        "viewVersion": st.get("viewVersion") or 0,
        "publishedAt": st.get("publishedAt") or "",
        "stale": bool(st.get("stale")),
        "coveragePct": (st.get("coverage") or {}).get("coveragePct"),
    })
    return out


# ── RPC: view.mount / view.unmount / view.status ─────────────────

def mount_task(multi_db, project_id: str, task_id: str, force: bool = False) -> dict:
    """挂载任务到基线视图(严格重合检测)。"""
    if not project_id or not task_id:
        raise ValueError("project_id and task_id are required")
    main_db = multi_db.main_db
    task = _task_row(main_db, task_id)
    if not task or task.get("project_id") != project_id:
        raise ValueError(f"Task {task_id} not found in project {project_id}")
    if task.get("status") != "done":
        raise ValueError(f"Task {task_id} status is '{task.get('status')}', only done tasks can be mounted")

    try:
        project_db = multi_db.get_project_db(project_id)
    except Exception as e:
        raise ValueError(f"project db unavailable: {e}")

    cand = _task_files(project_db, task_id)
    _ensure_view(main_db, project_id)

    # 严格重合检测：与任一已挂载任务交集非空即拒绝
    for m in _mounts(main_db, project_id):
        if m["task_id"] == task_id:
            continue
        exist = _task_files(project_db, m["task_id"])
        inter = cand & exist
        if inter and not force:
            samples = sorted(inter)[:8]
            raise ValueError(
                f"任务 {task_id} 与已挂载任务 {m['task_id']} 覆盖交叉 {len(inter)} 个文件"
                f"(如 {samples})；基线视图不允许交叉覆盖的任务同时挂载，"
                f"请先卸载冲突任务或使用 force=true 强制挂载")

    main_db.execute(
        "INSERT OR REPLACE INTO view_mounts (project_id, task_id, mounted_files, mounted_at) "
        "VALUES (?, ?, ?, ?)", (project_id, task_id, len(cand), _now()))
    _bump(main_db, project_id, overlap_warned=bool(force))
    logger.info("[view.mount] project=%s task=%s files=%d force=%s",
                project_id, task_id, len(cand), force)
    return view_status(multi_db, project_id)


def unmount_task(multi_db, project_id: str, task_id: str) -> dict:
    if not project_id or not task_id:
        raise ValueError("project_id and task_id are required")
    main_db = multi_db.main_db
    _ensure_view(main_db, project_id)
    main_db.execute("DELETE FROM view_mounts WHERE project_id = ? AND task_id = ?",
                    (project_id, task_id))
    _bump(main_db, project_id)
    logger.info("[view.unmount] project=%s task=%s", project_id, task_id)
    return view_status(multi_db, project_id)


def view_status(multi_db, project_id: str) -> dict:
    """视图全景：挂载明细 + 覆盖率统计 + stale 标记。"""
    if not project_id:
        raise ValueError("project_id is required")
    main_db = multi_db.main_db
    view = _ensure_view(main_db, project_id)
    mounts = _mounts(main_db, project_id)

    try:
        project_db = multi_db.get_project_db(project_id)
    except Exception as e:
        raise ValueError(f"project db unavailable: {e}")

    # 覆盖率 = 任务口径汇总：分母=各任务「选择」的源码文件并集，
    # 分子=各任务「已分析∩已选择」并集(挂载时拒绝重叠，force 挂载的交叠由并集去重)
    selected_all: set = set()
    covered: set = set()
    per_task: list = []
    mounted = []
    for m in mounts:
        tid = m["task_id"]
        t = _task_row(main_db, tid)
        analyzed = _task_files(project_db, tid)
        selected = _task_selected_files(project_db, t)
        covered_task = analyzed & selected
        selected_all |= selected
        covered |= covered_task
        per_task.append({
            "taskId": tid,
            "selectedFiles": len(selected),
            "coveredFiles": len(covered_task),
            "coveragePct": round(len(covered_task) / len(selected) * 100, 1) if selected else None,
        })
        mounted.append({
            "taskId": tid,
            "taskName": t.get("name") or tid,
            "status": t.get("status") or "",
            "files": len(analyzed),
            "selectedFiles": len(selected),
            "declared": {
                "scopes": _json_list(t.get("scopes")) or ([t.get("scope")] if t.get("scope") else []),
                "extensions": _json_list(t.get("extensions")),
                "excludeDirs": _json_list(t.get("exclude_dirs")),
            },
            "mountedAt": m["mounted_at"],
        })

    # 任务行缺失/选择集为空 → 回退全量源文件口径(旧行为，保持健壮)
    total_files = len(selected_all) or _total_source_files(project_db)

    # stale：存在未挂载的更新 done 任务(信息性标记，切换一律显式挂载)
    stale, unmounted_latest = False, None
    try:
        for r in main_db.fetchall(
                "SELECT id, name, created_at FROM analysis_tasks "
                "WHERE project_id = ? AND status = 'done' ORDER BY created_at DESC LIMIT 5",
                (project_id,)):
            if r["id"] not in {m["taskId"] for m in mounted}:
                stale = True
                unmounted_latest = {"taskId": r["id"], "taskName": r["name"],
                                    "createdAt": r["created_at"]}
                break
    except Exception:
        pass

    coverage_pct = round(len(covered) / total_files * 100, 1) if total_files else None
    return {
        "projectId": project_id,
        "viewVersion": int(view.get("version") or 1),
        "baselineVersionId": view.get("baseline_version_id") or "",
        "overlapWarned": bool(view.get("overlap_warned")),
        "publishedAt": view.get("published_at") or "",
        "mounted": mounted,
        "coverage": {
            "totalFiles": total_files,
            "coveredFiles": len(covered),
            "coveragePct": coverage_pct,
            "perTask": per_task,
        },
        "stale": stale,
        "unmountedLatest": unmounted_latest,
    }


def remove_project_view(main_db, project_id: str):
    """项目删除时清理视图数据。"""
    main_db.execute("DELETE FROM view_mounts WHERE project_id = ?", (project_id,))
    main_db.execute("DELETE FROM project_views WHERE project_id = ?", (project_id,))
    main_db.commit()


def register_view_methods(server, multi_db) -> None:
    """对外视图方法(外部白名单内)：挂载管理 + 状态查询。"""

    @server.register("view.mount")
    def view_mount(project_id=None, projectId=None, task_id=None, taskId=None, force=False):
        pid = project_id or projectId
        tid = task_id or taskId
        return mount_task(multi_db, pid, tid, force=bool(force))

    @server.register("view.unmount")
    def view_unmount(project_id=None, projectId=None, task_id=None, taskId=None):
        return unmount_task(multi_db, project_id or projectId, task_id or taskId)

    @server.register("view.status")
    def view_status_rpc(project_id=None, projectId=None):
        return view_status(multi_db, project_id or projectId)

    @server.register("view.summary")
    def view_summary_rpc(project_id=None, projectId=None):
        return view_summary(multi_db, project_id or projectId)
