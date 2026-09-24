"""图布局持久化路由（MS5-V2 自 viewer.py 切分）。"""
import json

from fastapi import APIRouter, HTTPException, Query, Request

from topoone import service_common as common
import logging
logger = logging.getLogger(__name__)

router = APIRouter()

def _ensure_graph_layout_table(pdb):
    pdb.execute(
        "CREATE TABLE IF NOT EXISTS web_graph_layout ("
        "  project_id TEXT, task_id TEXT, comm_id TEXT,"
        "  edge_type TEXT, gran TEXT, depth INTEGER,"
        "  layout_data TEXT NOT NULL,"
        "  created_at TEXT DEFAULT (datetime('now')),"
        "  PRIMARY KEY (project_id, task_id, comm_id, edge_type, gran, depth)"
        ")"
    )


@router.post("/api/graph-layout")
async def save_graph_layout(request: Request):
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        body = await request.json()
        tid = body.get("taskId") or body.get("task_id", "")
        comm_id = body.get("commId") or body.get("comm_id", "")
        et = body.get("edgeType") or body.get("edge_type", "")
        gran = body.get("gran", "component")
        depth = body.get("depth", 1)
        nodes = body.get("nodes", {})
        if not tid:
            raise HTTPException(422, "taskId is required")
        pid, pdb = common._resolve_project_db(tid)
        _ensure_graph_layout_table(pdb)
        layout_json = json.dumps(nodes)
        pdb.execute(
            "INSERT OR REPLACE INTO web_graph_layout "
            "(project_id, task_id, comm_id, edge_type, gran, depth, layout_data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, tid, comm_id, et, gran, depth, layout_json)
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/graph-layout")
async def load_graph_layout(task_id: str = Query(None), taskId: str = Query(None),
                             comm_id: str = Query(None), commId: str = Query(None),
                             edge_type: str = Query(None), edgeType: str = Query(None),
                             gran: str = Query("component"), depth: int = Query(1)):
    tid = task_id or taskId
    cid = comm_id or commId or ""
    et = edge_type or edgeType or ""
    if not tid:
        raise HTTPException(422, "taskId is required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = common._resolve_project_db(tid)
        _ensure_graph_layout_table(pdb)
        row = pdb.fetchone(
            "SELECT layout_data FROM web_graph_layout "
            "WHERE project_id=? AND task_id=? AND comm_id=? AND edge_type=? AND gran=? AND depth=?",
            (pid, tid, cid, et, gran, depth)
        )
        if row:
            nodes = json.loads(row["layout_data"])
        else:
            nodes = {}
        return {"nodes": nodes}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/api/graph-layout")
async def delete_graph_layout(task_id: str = Query(None), taskId: str = Query(None),
                               comm_id: str = Query(None), commId: str = Query(None),
                               edge_type: str = Query(None), edgeType: str = Query(None),
                               gran: str = Query("component"), depth: int = Query(1)):
    tid = task_id or taskId
    cid = comm_id or commId or ""
    et = edge_type or edgeType or ""
    if not tid:
        raise HTTPException(422, "taskId is required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = common._resolve_project_db(tid)
        _ensure_graph_layout_table(pdb)
        pdb.execute(
            "DELETE FROM web_graph_layout "
            "WHERE project_id=? AND task_id=? AND comm_id=? AND edge_type=? AND gran=? AND depth=?",
            (pid, tid, cid, et, gran, depth)
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
