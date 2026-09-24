"""graph 节点位置持久化族（MS5-V1 自 task_manager.py 切分；RPC 面经 service/project.py 二次包装暴露）。"""
import logging

from topoone.db.manager import MultiDBManager
from .common import _ensure_table

logger = logging.getLogger(__name__)


_POSITIONS_DDL = """CREATE TABLE IF NOT EXISTS graph_node_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    edge_type TEXT NOT NULL CHECK(edge_type IN ('INCLUDE','CALL','EXTERNAL_INCLUDE','EXTERNAL_CALL')),
    drill_key TEXT NOT NULL,
    snapshot_id TEXT,
    layout_type TEXT NOT NULL CHECK(layout_type IN ('dagre','force')),
    node_id TEXT NOT NULL,
    pos_x REAL NOT NULL,
    pos_y REAL NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_gp_active_unique
    ON graph_node_positions(task_id, edge_type, drill_key, layout_type, node_id)
    WHERE snapshot_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_gp_snap_unique
    ON graph_node_positions(task_id, edge_type, drill_key, snapshot_id, layout_type, node_id)
    WHERE snapshot_id IS NOT NULL;
"""


def save_positions(multi_db: MultiDBManager, task_id: str, edge_type: str, drill_key: str,
                   layout_type: str, positions: list, snapshot_id=None) -> dict:
    """Batch save node positions (UPSERT per node)."""
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"saved": 0, "error": "project_db_not_found"}
    _ensure_table(project_db, "graph_node_positions", _POSITIONS_DDL)
    saved = 0
    for p in positions:
        project_db.execute("""
            INSERT OR REPLACE INTO graph_node_positions
                (task_id, edge_type, drill_key, snapshot_id, layout_type, node_id, pos_x, pos_y)
            VALUES (?,?,?,?,?,?,?,?)
        """, (task_id, edge_type, drill_key, snapshot_id, layout_type,
              p.get("nodeId", p.get("node_id", "")), p.get("x", 0), p.get("y", 0)))
        saved += 1
    project_db.commit()
    return {"saved": saved}


def load_positions(multi_db: MultiDBManager, task_id: str, edge_type: str, drill_key: str,
                   layout_type: str, snapshot_id=None) -> dict:
    """Load saved node positions."""
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"positions": {}}
    _ensure_table(project_db, "graph_node_positions", _POSITIONS_DDL)
    rows = project_db.fetchall(
        """SELECT node_id, pos_x, pos_y FROM graph_node_positions
           WHERE task_id=? AND edge_type=? AND drill_key=? AND layout_type=?
             AND snapshot_id IS ?""",
        (task_id, edge_type, drill_key, layout_type, snapshot_id))
    result = {}
    for r in rows:
        result[r["node_id"]] = {"x": r["pos_x"], "y": r["pos_y"]}
    logger.info(
        f"[loadPositions] task={task_id[:8]} edge={edge_type} drill={drill_key}"
        f" layout={layout_type} snap={snapshot_id!r} → rows={len(rows)}"
    )
    return {"positions": result}


def list_position_keys(multi_db: MultiDBManager, project_id: str) -> dict:
    """List all saved position key summaries for a project."""
    main_db = multi_db.main_db
    task_rows = main_db.fetchall(
        "SELECT id FROM analysis_tasks WHERE project_id = ?", (project_id,))
    task_ids = [r["id"] for r in task_rows]
    if not task_ids:
        return {"keys": []}
    project_db = multi_db.get_project_db(project_id)
    if not project_db:
        return {"keys": []}
    _ensure_table(project_db, "graph_node_positions", _POSITIONS_DDL)
    result = []
    for tid in task_ids:
        rows = project_db.fetchall(
            """SELECT edge_type, drill_key, layout_type, COUNT(*) AS cnt
               FROM graph_node_positions
               WHERE task_id = ? AND snapshot_id IS NULL
               GROUP BY edge_type, drill_key, layout_type""",
            (tid,))
        for r in rows:
            result.append({
                "taskId": tid,
                "edgeType": r["edge_type"],
                "drillKey": r["drill_key"],
                "layoutType": r["layout_type"],
                "count": r["cnt"],
            })
    return {"keys": result}


def clear_positions(multi_db: MultiDBManager, task_id: str, edge_type: str, drill_key: str,
                    layout_type: str) -> dict:
    """Clear all saved positions for a given key."""
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"deleted": 0}
    _ensure_table(project_db, "graph_node_positions", _POSITIONS_DDL)
    cursor = project_db.execute(
        """DELETE FROM graph_node_positions
           WHERE task_id=? AND edge_type=? AND drill_key=? AND layout_type=?""",
        (task_id, edge_type, drill_key, layout_type))
    deleted = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
    project_db.commit()
    return {"deleted": deleted}
