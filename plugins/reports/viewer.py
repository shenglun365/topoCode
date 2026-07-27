"""Viewer module — /doc + community/graph/file/heatmap/plantuml API"""

import hashlib
import json
import logging
import os
import re

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import common
import common

router = APIRouter()

import community_data as cd

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ── Static pages ──

@router.get("/doc", response_class=HTMLResponse)
async def view_doc(task_id: str = Query(None), doc_id: str = Query(None),
                   taskId: str = Query(None), docId: str = Query(None)):
    tid = task_id or taskId or ''
    did = doc_id or docId or ''
    legacy_path = os.path.join(STATIC_DIR, "legacy-viewer.html")
    viewer_path = os.path.join(STATIC_DIR, "viewer.html")
    logger.info(f"=== Document viewer URL: http://127.0.0.1:{common.http_port}/doc?docId={did}&taskId={tid} ===")
    if os.path.isfile(legacy_path):
        return FileResponse(legacy_path)
    if os.path.isfile(viewer_path):
        return FileResponse(viewer_path)
    return HTMLResponse("viewer.html not found", status_code=404)


@router.get("/code", response_class=HTMLResponse)
async def view_code():
    code_path = os.path.join(STATIC_DIR, "code.html")
    if os.path.isfile(code_path):
        return FileResponse(code_path)
    return HTMLResponse("code.html not found", status_code=404)


# ── Community Document API ──

@router.get("/api/community-doc")
async def get_community_doc(task_id: str = Query(None), taskId: str = Query(None),
                            community_id: str = Query(None), communityId: str = Query(None),
                            edge_type: str = Query(None), edgeType: str = Query(None)):
    tid = task_id or taskId
    cid = community_id or communityId
    et = edge_type or edgeType or 'CALL'
    if not tid or not cid:
        raise HTTPException(422, "task_id/taskId and community_id/communityId are required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        task = common.multi_db.main_db.fetchone(
            "SELECT t.project_id, p.name AS project_name FROM analysis_tasks t JOIN projects p ON t.project_id = p.id WHERE t.id = ?", (tid,)
        )
        if not task:
            raise HTTPException(404, "Task not found")
        pid = task["project_id"]
        project_name = task["project_name"]
        pdb = common.multi_db.get_project_db(pid)
        row = pdb.fetchone(
            "SELECT name, summary, comm_lv FROM community_llm_results WHERE task_id=? AND edge_type=? AND comm_id=?",
            (tid, et, cid)
        )
        if not row:
            name = cid
            parts = [f"# {name}", "", f"**ID**: {cid}  **\u7c7b\u578b**: {et}", "",
                     "\u8be5\u7ec4\u4ef6\u6682\u65e0 LLM \u5206\u6790\u7ed3\u679c\uff0c\u8bf7\u5148\u901a\u8fc7 AI \u52a9\u624b\u8fd0\u884c\u7ec4\u4ef6\u5206\u6790\u3002"]
        else:
            name = row.get("name") or cid
            parts = [f"# {name}", "", f"**ID**: {cid}  **\u7c7b\u578b**: {et}", "", row.get("summary") or ""]
        return {
            "id": f"community-{tid}-{et}-{cid}",
            "taskId": tid, "projectId": pid, "projectName": project_name,
            "title": name, "content": "\n".join(parts), "createdAt": "", "updatedAt": "",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/community-files")
async def get_community_files(task_id: str = Query(None), taskId: str = Query(None),
                               community_id: str = Query(None), communityId: str = Query(None),
                               edge_type: str = Query(None), edgeType: str = Query(None)):
    tid = task_id or taskId
    cid = community_id or communityId
    et = edge_type or edgeType or 'CALL'
    if not tid or not cid:
        raise HTTPException(422, "task_id/taskId and community_id/communityId are required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        task = common.multi_db.main_db.fetchone("SELECT project_id FROM analysis_tasks WHERE id = ?", (tid,))
        if not task:
            raise HTTPException(404, "Task not found")
        pid = task["project_id"]
        pdb = common.multi_db.get_project_db(pid)
        proj_row = common.multi_db.main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (pid,))
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""
        _rel = cd._make_rel(project_root)

        rows = pdb.fetchall(
            "SELECT comm_id, comm_lv, node_list FROM graph_doc "
            "WHERE task_id=? AND edge_type=? AND comm_id=? "
            "ORDER BY comm_lv, comm_id",
            (tid, et, cid)
        )
        if not rows:
            l0_cid = cd.l0_ancestor(cid)
            if l0_cid and l0_cid != cid:
                rows = pdb.fetchall(
                    "SELECT comm_id, comm_lv, node_list FROM graph_doc "
                    "WHERE task_id=? AND edge_type=? AND comm_id=? "
                    "ORDER BY comm_lv, comm_id",
                    (tid, et, l0_cid)
                )
        files = []
        seen = set()
        for r in rows:
            try:
                raw = json.loads(r["node_list"]) if isinstance(r["node_list"], str) else r["node_list"] or []
            except Exception:
                raw = []
            if not isinstance(raw, list):
                raw = [raw]
            for node_id in raw:
                if isinstance(node_id, dict):
                    nid = str(node_id.get("id", ""))
                else:
                    nid = str(node_id)
                if cd._bad_id(nid):
                    continue
                clean = nid.split(':')[0] if ':' in nid else nid
                clean = _rel(clean)
                if clean and clean not in seen:
                    seen.add(clean)
                    parts = clean.split("/")
                    files.append({
                        "path": clean, "name": parts[-1] if parts else clean,
                        "parentDir": parts[-2] if len(parts) >= 2 else "",
                        "commId": r["comm_id"], "commLv": r["comm_lv"]
                    })
        return {"files": files, "total": len(files), "projectId": pid}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/community-children")
async def get_community_children(task_id: str = Query(None), taskId: str = Query(None),
                                  parent_comm_id: str = Query(None), parentCommId: str = Query(None),
                                  edge_type: str = Query(None), edgeType: str = Query(None)):
    tid = task_id or taskId
    pid = parent_comm_id or parentCommId
    et = (edge_type or edgeType or 'CALL').upper()
    if not tid:
        raise HTTPException(422, "task_id/taskId is required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        _, pdb = common._resolve_project_db(tid)
        return cd.get_community_children(pdb, tid, et, pid or None)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/community-graph")
async def get_community_graph(task_id: str = Query(None), taskId: str = Query(None),
                              edge_type: str = Query(None), edgeType: str = Query(None),
                              comm_lv: str = Query(None), commLv: str = Query(None),
                              comm_id: str = Query(None), commId: str = Query(None),
                              gran: str = Query(None), gran_: str = Query(None),
                              depth: int = Query(1)):
    task_id = task_id or taskId
    edge_type = edge_type or edgeType or "CALL"
    comm_lv_raw = comm_lv or commLv
    comm_lv = comm_lv_raw or "L0"
    comm_id = comm_id or commId or ""
    if not comm_lv_raw and comm_id:
        m = re.search(r"-L(\d+)-", comm_id)
        if m:
            comm_lv = f"L{m.group(1)}"
    gn = (gran or gran_ or "component").lower()
    if not task_id:
        raise HTTPException(422, "task_id is required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = common._resolve_project_db(task_id)
        et = (edge_type or edgeType or "CALL").upper()
        proj_row = common.multi_db.main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (pid,))
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""

        if gn == "component":
            return cd.get_community_graph_component(
                pdb, task_id, et, comm_lv, comm_id, project_root, depth=int(depth) if depth else 1)
        else:
            return cd.get_community_graph_file(pdb, task_id, et, comm_lv, comm_id, project_root)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[community-graph] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, str(e))


@router.get("/api/file-graph")
async def get_file_graph(task_id: str = Query(None), taskId: str = Query(None),
                          edge_type: str = Query(None), edgeType: str = Query(None),
                          comm_id: str = Query(None), commId: str = Query(None),
                          scope: str = Query(None), scope_: str = Query(None)):
    task_id = task_id or taskId
    edge_type = edge_type or edgeType or "CALL"
    comm_id = comm_id or commId or ""
    sc = (scope or scope_ or "both").lower()
    if not task_id:
        raise HTTPException(422, "task_id is required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = common._resolve_project_db(task_id)
        et = (edge_type or edgeType or "CALL").upper()
        proj_row = common.multi_db.main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (pid,))
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""
        _proot = project_root.replace('\\', '/') if project_root else ''

        def _rel(p):
            if not p: return p
            if p.startswith('file:'): p = p[5:]
            p = p.replace('\\', '/')
            if _proot and p.lower().startswith(_proot.lower()): p = p[len(_proot):]
            return p.lstrip('/')

        file_comm = {}
        all_doc_rows = pdb.fetchall(
            "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=?", (task_id, et)
        )
        for dr in all_doc_rows:
            cid = dr["comm_id"]
            try:
                nlist = json.loads(dr["node_list"]) if isinstance(dr["node_list"], str) else dr["node_list"] or []
            except Exception:
                nlist = []
            for n in (nlist if isinstance(nlist, list) else [nlist]):
                if isinstance(n, dict):
                    key = str(n.get("id", ""))
                elif isinstance(n, str):
                    key = n
                else:
                    continue
                fp = _rel(key)
                if fp and fp not in file_comm:
                    file_comm[fp] = cid

        target_files = set()
        if comm_id == "__all__":
            for dr in all_doc_rows:
                try:
                    nlist = json.loads(dr["node_list"]) if isinstance(dr["node_list"], str) else dr["node_list"] or []
                except Exception:
                    nlist = []
                for n in (nlist if isinstance(nlist, list) else [nlist]):
                    if isinstance(n, dict):
                        key = str(n.get("id", ""))
                    elif isinstance(n, str):
                        key = n
                    else:
                        continue
                    fp = _rel(key)
                    if fp:
                        target_files.add(fp)
        elif comm_id:
            doc_rows = pdb.fetchall(
                "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id=?", (task_id, et, comm_id)
            )
            for dr in doc_rows:
                try:
                    nlist = json.loads(dr["node_list"]) if isinstance(dr["node_list"], str) else dr["node_list"] or []
                except Exception:
                    nlist = []
                for n in (nlist if isinstance(nlist, list) else [nlist]):
                    if isinstance(n, dict):
                        key = str(n.get("id", ""))
                    elif isinstance(n, str):
                        key = n
                    else:
                        continue
                    fp = _rel(key)
                    if fp:
                        target_files.add(fp)
        else:
            doc_rows = pdb.fetchall(
                "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv='L0' LIMIT 1", (task_id, et)
            )
            for dr in doc_rows:
                try:
                    nlist = json.loads(dr["node_list"]) if isinstance(dr["node_list"], str) else dr["node_list"] or []
                except Exception:
                    nlist = []
                for n in (nlist if isinstance(nlist, list) else [nlist]):
                    if isinstance(n, dict):
                        key = str(n.get("id", ""))
                    elif isinstance(n, str):
                        key = n
                    else:
                        continue
                    fp = _rel(key)
                    if fp:
                        target_files.add(fp)

        if not target_files:
            return {"nodes": [], "edges": []}

        all_nodes = pdb.fetchall("SELECT id, file_path FROM graph_node WHERE task_id=?", (task_id,))
        node_map = {}
        fp_to_id = {}
        for n in all_nodes:
            fp = _rel(n["file_path"] or "")
            if fp and fp in target_files:
                node_map[fp] = {"id": fp, "label": fp}
                if n["id"]:
                    fp_to_id[fp] = n["id"]

        kind = "imports" if et == "INCLUDE" else "calls"
        all_edges = pdb.fetchall(
            "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?", (task_id, kind)
        )
        edge_set = set()
        for e in all_edges:
            src = _rel(e["source_id"] or "")
            tgt = _rel(e["target_id"] or "")
            if not src or not tgt or src not in node_map or tgt not in node_map:
                continue
            if sc == "internal":
                if file_comm.get(src) == file_comm.get(tgt):
                    edge_set.add(f"{src}→{tgt}")
            elif sc == "external":
                if file_comm.get(src) and file_comm.get(tgt) and file_comm[src] != file_comm[tgt]:
                    edge_set.add(f"{src}→{tgt}")
            else:
                edge_set.add(f"{src}→{tgt}")

        return {
            "nodes": list(node_map.values()),
            "edges": [{"id": e, "source": e.split("→")[0], "target": e.split("→")[1]} for e in edge_set]
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[file-graph] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, str(e))


@router.get("/api/file-summary")
async def get_file_summary(task_id: str = Query(None), taskId: str = Query(None),
                            file_path: str = Query(None), filePath: str = Query(None)):
    tid = task_id or taskId
    fp = file_path or filePath
    if not tid or not fp:
        raise HTTPException(422, "task_id/taskId and file_path/filePath are required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        task = common.multi_db.main_db.fetchone("SELECT project_id FROM analysis_tasks WHERE id = ?", (tid,))
        if not task:
            raise HTTPException(404, "Task not found")
        pid = task["project_id"]
        pdb = common.multi_db.get_project_db(pid)
        row = pdb.fetchone(
            "SELECT summary, summary_len, created_at, source, task_id FROM file_summaries "
            "WHERE project_id=? AND file_path=? ORDER BY created_at DESC LIMIT 1", (pid, fp)
        )
        if row:
            return {"found": True, "summary": row["summary"], "summary_len": row["summary_len"],
                    "created_at": row["created_at"], "source": row["source"], "task_id": row["task_id"]}
        return {"found": False}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/file")
async def get_file(project_id: str = Query(...), path: str = Query(...)):
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        project = common.multi_db.main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (project_id,))
        if not project:
            raise HTTPException(404, "Project not found")
        root_path = project["root_path"]
        full_path = os.path.normpath(os.path.join(root_path, path))
        if not full_path.startswith(os.path.normpath(root_path)):
            raise HTTPException(403, "Path outside project root")
        if not os.path.isfile(full_path):
            alt = common._find_file_alternatives(project_id, path)
            raise HTTPException(status_code=404, detail={"message": "File not found", "alternatives": alt})
        size = os.path.getsize(full_path)
        max_bytes = 500 * 1024
        max_lines = 1000
        content = ""
        truncated = False
        if size > max_bytes:
            truncated = True
            with open(full_path, "rb") as f:
                raw = f.read(max_bytes)
        else:
            with open(full_path, "rb") as f:
                raw = f.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gbk")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            text = "\n".join(lines)
            truncated = True
        _, ext = os.path.splitext(path)
        lang_map = {
            ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
            ".cc": "cpp", ".cxx": "cpp", ".hh": "cpp",
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".java": "java", ".go": "go", ".rs": "rust",
            ".sh": "bash", ".bash": "bash", ".zsh": "bash",
            ".yaml": "yaml", ".yml": "yaml", ".json": "json",
            ".xml": "xml", ".md": "markdown", ".txt": "text",
            ".css": "css", ".html": "html", ".vue": "html",
            ".jsx": "javascript", ".tsx": "typescript",
        }
        return {"content": text, "language": lang_map.get(ext.lower(), ""),
                "path": path, "truncated": truncated, "size": size}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/cascade-levels")
async def get_cascade_levels(task_id: str = Query(None), taskId: str = Query(None),
                              edge_type: str = Query(None), edgeType: str = Query(None)):
    task_id = task_id or taskId
    edge_type = edge_type or edgeType or "CALL"
    if not task_id:
        raise HTTPException(422, "task_id is required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        _, pdb = common._resolve_project_db(task_id)
        et = (edge_type or edgeType or "CALL").upper()
        return cd.get_cascade_levels(pdb, task_id, et)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/heatmap")
async def get_heatmap(task_id: str = Query(None), taskId: str = Query(None),
                       edge_type: str = Query(None), edgeType: str = Query(None),
                       size: int = Query(10),
                       comm_id: str = Query(None), commId: str = Query(None),
                       comm_lv: str = Query(None), commLv: str = Query(None)):
    task_id = task_id or taskId
    edge_type = edge_type or edgeType or "CALL"
    if not task_id:
        raise HTTPException(422, "task_id is required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    size = max(5, min(50, size))
    try:
        pid, pdb = common._resolve_project_db(task_id)
        et = (edge_type or edgeType or "CALL").upper()
        cid = comm_id or commId or ""
        clv = comm_lv or commLv or "L0"
        proj_row = common.multi_db.main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (pid,))
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""

        if cid:
            return common._drill_heatmap(pdb, task_id, et, clv, cid, size, project_root)
        return cd.get_heatmap(pdb, task_id, et, project_root, "L0", size)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[heatmap] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, str(e))


@router.get("/api/external-graph")
async def get_external_graph(task_id: str = Query(None), taskId: str = Query(None),
                              edge_type: str = Query(None), edgeType: str = Query(None),
                              depth: int = Query(1), comm_id: str = Query(None), commId: str = Query(None)):
    tid = task_id or taskId
    et = edge_type or edgeType or 'EXTERNAL_INCLUDE'
    cid = comm_id or commId or ''
    if not tid:
        raise HTTPException(422, "taskId is required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = common._resolve_project_db(tid)
        proj_row = common.multi_db.main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (pid,))
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""
        return cd.get_external_graph(pdb, tid, et, depth, cid, project_root)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[external-graph] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, str(e))


@router.get("/api/external-stats")
async def get_external_stats(task_id: str = Query(None), taskId: str = Query(None)):
    tid = task_id or taskId
    if not tid:
        raise HTTPException(422, "task_id is required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = common._resolve_project_db(tid)
        proj_row = common.multi_db.main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (pid,))
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""
        return cd.get_external_stats(pdb, tid, project_root)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[external-stats] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, str(e))


# ── PlantUML ──

@router.get("/api/plantuml")
async def render_plantuml(code: str = Query(...)):
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        code_hash = hashlib.md5(code.encode("utf-8")).hexdigest()
        cached = common._get_cached_plantuml(code_hash)
        if cached:
            return Response(content=cached, media_type="image/svg+xml")
        from plantuml_service import render_plantuml as render_pu
        svg_bytes = render_pu(code, format="svg", use_remote=True)
        svg_text = svg_bytes.decode("utf-8", errors="replace")
        common._set_cached_plantuml(code_hash, code, svg_text)
        return Response(content=svg_text, media_type="image/svg+xml")
    except Exception as e:
        raise HTTPException(500, f"PlantUML render failed: {e}")

@router.post("/api/plantuml")
async def render_plantuml_post(request: Request):
    import logging
    logger = logging.getLogger(__name__)
    try:
        body = await request.body()
        code = body.decode("utf-8", errors="replace")
        if not code or not code.strip():
            raise HTTPException(400, "Empty PlantUML code")
        if not common.multi_db:
            raise HTTPException(503, "Backend not ready")
        code_hash = hashlib.md5(code.encode("utf-8")).hexdigest()
        cached = common._get_cached_plantuml(code_hash)
        if cached:
            return Response(content=cached, media_type="image/svg+xml")
        from plantuml_service import render_plantuml as render_pu
        from plantuml_service import PLANTUML_SERVER as _pu_srv
        logger.info(f"POST /api/plantuml: PLANTUML_SERVER={_pu_srv} code_len={len(code)}")
        svg_bytes = render_pu(code, format="svg", use_remote=True)
        svg_text = svg_bytes.decode("utf-8", errors="replace")
        common._set_cached_plantuml(code_hash, code, svg_text)
        return Response(content=svg_text, media_type="image/svg+xml")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("POST /api/plantuml failed")
        raise HTTPException(500, f"PlantUML render failed: {e}")


@router.get("/api/plantuml/clear-cache")
async def clear_plantuml_cache():
    common._clear_plantuml_cache()
    return {"status": "ok"}


# ── Graph Layout Persistence ──

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
