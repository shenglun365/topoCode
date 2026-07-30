"""Viewer module — /doc + community/graph/file/heatmap/plantuml API"""

import hashlib
import json
import logging
import logging.handlers
import os
import re

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import common

router = APIRouter()

import community_data as cd

logger = logging.getLogger(__name__)

# ── File logger for diagram editor (not to console) ──
_diag_log = logging.getLogger(f"{__name__}.diagram_editor")
_diag_log.setLevel(logging.DEBUG)
_diag_log.propagate = False
_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_path = os.path.join(_log_dir, "diagram-editor.log")
_fh = logging.handlers.RotatingFileHandler(_log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_diag_log.addHandler(_fh)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ── Static pages ──

@router.get("/doc", response_class=HTMLResponse)
async def view_doc(task_id: str = Query(None), doc_id: str = Query(None),
                   taskId: str = Query(None), docId: str = Query(None)):
    tid = task_id or taskId or ''
    did = doc_id or docId or ''
    viewer_path = os.path.join(STATIC_DIR, "viewer.html")
    logger.info(f"=== Document viewer URL: http://127.0.0.1:{common.http_port}/doc?docId={did}&taskId={tid} ===")
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


# ── Diagram Rebuild API (Parser + Template) ──

@router.post("/api/plantuml/rebuild")
async def rebuild_plantuml(request: Request):
    try:
        body = await request.json()
        code: str = body.get("code", "")
        diag_type: str = body.get("type", "auto")
        if not code or not code.strip():
            raise HTTPException(400, "Empty code")
        from diagram import rebuild_plantuml as _rebuild
        try:
            result = _rebuild(code, diag_type if diag_type != "auto" else None)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("POST /api/plantuml/rebuild failed")
        raise HTTPException(500, f"Rebuild failed: {e}")


@router.post("/api/mermaid/rebuild")
async def rebuild_mermaid(request: Request):
    try:
        body = await request.json()
        code: str = body.get("code", "")
        diag_type: str = body.get("type", "auto")
        if not code or not code.strip():
            raise HTTPException(400, "Empty code")
        from diagram import rebuild_mermaid as _rebuild
        try:
            result = _rebuild(code, diag_type if diag_type != "auto" else None)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("POST /api/mermaid/rebuild failed")
        raise HTTPException(500, f"Rebuild failed: {e}")


# ── Diagram Editing Agent (Scheme B) ──

import time as _time


def _make_message_id() -> str:
    return "msg_" + hashlib.md5(str(_time.time_ns()).encode()).hexdigest()[:16]


def _summarize_tool_result(t_name: str, result: dict) -> str:
    if "code" in result:
        v = result.get("validation", {})
        return f"code_len={len(result['code'])} valid={v.get('valid')} errors={v.get('errors', [])[:2]}"
    if "ir" in result:
        ir = result.get("ir", {})
        ns = len(ir.get("nodes", []) or ir.get("participants", []) or ir.get("classes", []))
        es = len(ir.get("edges", []) or ir.get("messages", []) or ir.get("relations", []))
        sg = len(ir.get("subgraphs", []) or [])
        return f"nodes={ns} edges={es} subgraphs={sg}"
    if result.get("stats"):
        s = result["stats"]
        return f"nodes={s.get('node_count')} edges={s.get('edge_count')} chars={s.get('char_count')}"
    if "errors" in result:
        return f"errors={result['errors'][:3]}"
    if "error" in result:
        return f"error={result['error'][:120]}"
    return f"keys={list(result.keys())[:4]}"


@router.post("/api/diagram-editor/process")
async def diagram_editor_process(request: Request):
    _t0 = _time.time()
    try:
        body = await request.json()
        code: str = body.get("code", "")
        lang: str = body.get("lang", "mermaid")
        instruction: str = body.get("instruction", "")
        history: list = body.get("history", [])
        context_limit: int = body.get("context_limit", 0)

        if not code or not instruction:
            _diag_log.warning("missing code or instruction")
            raise HTTPException(400, "code and instruction are required")

        model_id = body.get("model_id", "")
        if not model_id:
            default_row = common.multi_db.main_db.fetchone(
                "SELECT value FROM app_config WHERE key='web_chat_default_model_id'"
            ) if common.multi_db else None
            if default_row and default_row["value"]:
                model_id = default_row["value"]
            else:
                default_model = common.multi_db.main_db.fetchone(
                    "SELECT id FROM model_configs WHERE is_default = 1 AND status = 'connected'"
                ) if common.multi_db else None
                if default_model:
                    model_id = default_model["id"]

        if not model_id:
            _diag_log.warning("no available model")
            raise HTTPException(400, "No available model")

        _diag_log.info("=== diagram-editor process start ===")
        _diag_log.info("model=%s lang=%s code_len=%d instr_len=%d history_entries=%d",
                       model_id, lang, len(code), len(instruction), len(history))
        _diag_log.info("code_preview=%s ...", code[:200].replace("\n", "\\n"))
        _diag_log.info("instruction=%s", instruction[:300])

        from web_tools import get_web_tool_definitions

        diagram_tool_names = [
            "web_diagram_parse",
            "web_diagram_build",
            "web_diagram_validate",
        ]
        tool_defs = get_web_tool_definitions(diagram_tool_names)

        system_prompt = (
            "## 图编辑能力\n"
            "你是图编辑专家。通过三个工具操作 Mermaid/PlantUML 图：\n\n"
            "### 可用工具\n"
            "1. web_diagram_parse —— 将现有图代码解析为结构化中间表示(IR)\n"
            "2. web_diagram_build —— 从 IR 生成语法正确的图代码（唯一能产生代码的工具）\n"
            "3. web_diagram_validate —— 校验图代码语法\n\n"
            "### 工作流程\n"
            "修改现有图：\n"
            "  1. 调用 web_diagram_parse 获取 IR\n"
            "  2. 分析 IR，规划变化\n"
            "  3. 修改 IR 中的字段（在改动的元素上标注 _is_modified: true）\n"
            "  4. 调用 web_diagram_build 生成新代码\n"
            "  5. 调用 web_diagram_validate 确保语法正确\n"
            "  6. 向用户展示修改摘要\n\n"
            "创建新图：\n"
            "  1. 直接构造 IR（含所有节点/边/分组/样式）\n"
            "  2. 调用 web_diagram_build 生成代码\n"
            "  3. 调用 web_diagram_validate 校验\n\n"
            "### 强制约束\n"
            "- 禁止直接输出 mermaid/plantuml 代码。直接输出的代码将被系统自动丢弃。\n"
            "- 所有图代码必须通过 web_diagram_build 工具生成。\n"
            "- LLM 只描述图的结构（在 IR 中表达），不写具体的语法代码。\n"
            "- 每次修改后必须调用 web_diagram_validate。\n"
            "- 对于超大图（char_count > 8000），分区域依次修改。\n\n"
            "### 示例\n"
            "用户：「把用户模块改成蓝色，加一个缓存节点」\n"
            "正确：\n"
            "  1. web_diagram_parse → 获取 IR\n"
            "  2. 修改 IR：user.styles.fill = '#42b883'（标注 _is_modified: true），\n"
            "     添加节点 {id: 'cache', text: 'Redis缓存', shape: 'stadium'}\n"
            "  3. web_diagram_build → 新代码\n"
            "  4. web_diagram_validate → 确认语法正确\n"
            "  5. 输出修改摘要\n\n"
            "错误（将被丢弃）：\n"
            "  直接在回复中写 ```mermaid\\ngraph LR\\n    A[用户模块] --> B[Redis]\\n```\n\n"
            "### IR 格式\n"
            "- nodes: [{id, text, shape, styles, classes, _is_modified}]\n"
            "- edges: [{from, to, label, style, _is_modified}]\n"
            "- subgraphs: [{id, title, nodes, _is_modified}]\n"
            "- direction: TB|LR|RL|BT\n"
            "- init_config: {theme, themeVariables}\n"
            "- 所有 _is_modified: true 的元素会在编辑摘要中展示给用户"
        )

        user_content = f"当前图代码（{lang}）：\n```\n{code}\n```\n\n用户要求：{instruction}"

        model_cfg = common.multi_db.main_db.fetchone(
            "SELECT * FROM model_configs WHERE id = ?", (model_id,)
        ) if common.multi_db else None
        if not model_cfg:
            _diag_log.warning("model config not found: %s", model_id)
            raise HTTPException(400, f"Model {model_id} not found")

        md = dict(model_cfg)
        import requests as _req

        base_url = md.get("url", "").rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]

        _diag_log.info("model_info: name=%s url=%s timeout=%d max_tokens=%d",
                       md.get("model_name"), base_url, md.get("timeout", 300), md.get("max_tokens", 8192))

        messages = [{"role": "system", "content": system_prompt}]
        for h in history:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": user_content})

        executor = common.web_tool_executor
        max_rounds = 8
        final_response = ""
        updated_code = code
        code_changed = False

        max_tokens = md.get("max_tokens", 8192)
        if context_limit and context_limit < max_tokens:
            max_tokens = min(context_limit, max_tokens)

        for _round in range(max_rounds):
            _tr0 = _time.time()
            payload = {
                "model": md.get("model_name", ""),
                "messages": messages,
                "tools": tool_defs,
                "tool_choice": "auto",
                "max_tokens": max_tokens,
                "temperature": 0.3,
            }

            extra_raw = md.get("extra_config")
            if extra_raw and isinstance(extra_raw, str):
                try:
                    extra = json.loads(extra_raw)
                    if isinstance(extra, dict):
                        payload.update(extra)
                except Exception:
                    pass

            api_key = md.get("api_key", "")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}" if api_key else "",
            }

            timeout = md.get('timeout', 300)
            try:
                resp = _req.post(
                    f"{base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
            except _req.exceptions.ConnectionError as e:
                _diag_log.error("round=%d connection_error url=%s: %s", _round + 1, base_url, e)
                raise HTTPException(502,
                    f"无法连接到模型服务 ({base_url})。当前模型 ID: {model_id}")
            except _req.exceptions.Timeout:
                _diag_log.error("round=%d timeout url=%s timeout=%d", _round + 1, base_url, timeout)
                raise HTTPException(504, f"模型服务 ({base_url}) 响应超时 (>{timeout}s)")
            except _req.exceptions.RequestException as e:
                _diag_log.error("round=%d request_error: %s", _round + 1, e)
                raise HTTPException(502, f"模型请求失败: {e}")

            if resp.status_code != 200:
                _diag_log.error("round=%d llm_api_error status=%d body=%s",
                                _round + 1, resp.status_code, resp.text[:200])
                raise HTTPException(502, f"LLM API error: {resp.status_code} {resp.text[:200]}")

            data = resp.json()
            usage = data.get("usage", {})
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content", "") or ""
            tool_calls = msg.get("tool_calls", [])
            _tr1 = _time.time()
            _round_ms = int((_tr1 - _tr0) * 1000)

            _diag_log.info("[round=%d/%d] llm_time=%dms prompt_tokens=%s completion_tokens=%s content_len=%d tool_calls=%d",
                           _round + 1, max_rounds, _round_ms,
                           usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?"),
                           len(content), len(tool_calls))

            if content:
                _diag_log.info("[round=%d] llm_reasoning: %s", _round + 1, content[:500])
                final_response = content

            if not tool_calls:
                _diag_log.info("[round=%d] no tool calls — LLM produced final response", _round + 1)
                break

            _tool_t0 = _time.time()
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

            for tc in tool_calls:
                tc_id = tc.get("id", "")
                t_name = tc.get("function", {}).get("name", "")
                try:
                    t_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                except json.JSONDecodeError:
                    t_args = {}

                _args_preview = json.dumps(t_args, ensure_ascii=False)[:600]
                _diag_log.info("[round=%d] tool_call name=%s args=%s", _round + 1, t_name, _args_preview)

                result = executor.execute(t_name, t_args)
                result_str = json.dumps(result, ensure_ascii=False)
                messages.append({
                    "role": "tool",
                    "content": result_str,
                    "tool_call_id": tc_id,
                    "name": t_name,
                })

                _result_summary = _summarize_tool_result(t_name, result)
                _diag_log.info("[round=%d] tool_result name=%s summary=%s", _round + 1, t_name, _result_summary)

                if t_name == "web_diagram_build" and "code" in result:
                    updated_code = result["code"]
                    code_changed = True
                    _diag_log.info("[round=%d] code UPDATED old_len=%d new_len=%d",
                                   _round + 1, len(code), len(updated_code))

            _tool_t1 = _time.time()
            _diag_log.info("[round=%d] tool_exec_time=%dms", _round + 1, int((_tool_t1 - _tool_t0) * 1000))

        # 从 LLM 响应中剥离图代码块（不再展示给用户）
        if final_response:
            _cleaned = re.sub(r'```(?:mermaid|plantuml)\s*\n.*?\n```', '', final_response, flags=re.DOTALL | re.IGNORECASE).strip()
            if _cleaned != final_response:
                _diag_log.info("stripped code block from LLM response (was %d chars, now %d)", len(final_response), len(_cleaned))
                final_response = _cleaned
            # 兜底：如果没有通过工具生成代码，从响应中提取
            if not code_changed:
                _m = re.search(r'```(mermaid|plantuml)\s*\n(.*?)\n```', final_response, re.DOTALL | re.IGNORECASE)
                if _m:
                    _extracted = _m.group(2).strip()
                    if _extracted:
                        from diagram_tools._validator import validate_diagram_syntax
                        _val = validate_diagram_syntax(_extracted, _m.group(1).lower())
                        if _val['valid']:
                            _diag_log.info("code extracted from LLM response (fallback) old_len=%d new_len=%d",
                                           len(code), len(_extracted))
                            updated_code = _extracted
                            code_changed = True

        _total_ms = int((_time.time() - _t0) * 1000)
        _diag_log.info("=== diagram-editor done rounds=%d total=%dms code_changed=%s ===",
                       min(_round + 1, max_rounds), _total_ms, code_changed)

        return {
            "response": final_response,
            "updated_code": updated_code if code_changed else None,
            "code_changed": code_changed,
            "rounds": min(_round + 1, max_rounds),
            "history": messages[-4:],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("POST /api/diagram-editor/process failed")
        raise HTTPException(500, f"Diagram editor failed: {e}")


@router.post("/api/diagram-tools/apply")
async def diagram_tools_apply(request: Request):
    try:
        body = await request.json()
        sub_session_id = body.get("sub_session_id", "")
        main_session_id = body.get("main_session_id", "")
        msg_id = body.get("msg_id", "")
        diag_id = body.get("diag_id", "")
        lang = body.get("lang", "mermaid")

        from diagram_tools._subagent import apply_change, commit_to_main
        if sub_session_id:
            commit_result = commit_to_main(sub_session_id)
        else:
            code = body.get("code", "")
            if not code:
                raise HTTPException(400, "code required")
            commit_result = {"code": code, "modified": True, "diag_id": diag_id}

        return {
            "code": commit_result.get("code", ""),
            "msg_id": commit_result.get("msg_id", msg_id),
            "diag_id": diag_id,
            "modified": commit_result.get("modified", False),
            "lang": lang,
            "_writeback": {
                "msg_id": msg_id,
                "new_code": commit_result.get("code", ""),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Apply failed: {e}")


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
