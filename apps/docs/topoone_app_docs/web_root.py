"""Web Root 业务 API — project/task/doc + export/import/verify（M11 迁 docs 服务）。

门户 HTML（/ 与 /projects）由 gateway vue_routes serve，本模块只含 API 路由。
"""

import json
import os
import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse

from topoone import service_common as common

router = APIRouter()

import topoone.engine.community_data as cd

# 门户 HTML（/ 与 /projects）由 gateway vue_routes 统一 serve（docs static_dir），
# 本模块只承载 web_root 业务 API（/api/projects · /api/tasks · /api/docs ·
# /api/import* · /api/export* · /api/verify*）。

# ── Projects API ──

@router.get("/api/projects")
async def list_projects():
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        # MS7-W5 排序归一：与主源 RPC project.list 同序（置顶→sort_order→最近更新）
        projects = common.multi_db.main_db.fetchall(
            "SELECT id, name, root_path, pinned, sort_order, updated_at FROM projects "
            "ORDER BY pinned DESC, sort_order ASC, updated_at DESC"
        )
        return [{
            "id": p["id"],
            "name": p["name"],
            "rootPath": p["root_path"],
            "isResource": p["id"].startswith("TOPORES_ID:"),
        } for p in projects]
    except Exception as e:
        return []


@router.get("/api/tasks")
async def list_tasks(project_id: str = Query(...)):
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        tasks = common.multi_db.main_db.fetchall(
            "SELECT id, name, type, status, project_id FROM analysis_tasks WHERE project_id = ?",
            (project_id,),
        )
        # Check which tasks have generated documents
        pdb = common.multi_db.get_project_db(project_id)
        overall_ids = [f"overall-{t['id']}" for t in tasks]
        has_doc_set = set()
        if overall_ids:
            try:
                ph = ",".join("?" * len(overall_ids))
                rows = pdb.fetchall(
                    f"SELECT id FROM report_subdocs WHERE id IN ({ph})", overall_ids
                )
                has_doc_set = {r["id"].replace("overall-", "") for r in rows}
            except Exception:
                pass
        return [{
            "id": t["id"], "name": t["name"], "type": t["type"],
            "status": t["status"], "projectId": t["project_id"],
            "hasDoc": t["id"] in has_doc_set,
        } for t in tasks]
    except Exception as e:
        return []


# ── Docs API ──

@router.get("/api/docs/{doc_id}")
async def get_doc(doc_id: str):
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid = common._resolve_project_by_doc_id(doc_id)
        if not pid:
            raise HTTPException(404, f"Document {doc_id} not found")
        pdb = common.multi_db.get_project_db(pid)
        doc = pdb.fetchone(
            "SELECT id, task_id, title, content, created_at, updated_at FROM report_subdocs WHERE id = ?",
            (doc_id,),
        )
        if not doc:
            raise HTTPException(404, f"Document {doc_id} not found")
        proj_row = common.multi_db.main_db.fetchone("SELECT name FROM projects WHERE id = ?", (pid,))
        project_name = proj_row["name"] if proj_row else ""
        return {
            "id": doc["id"], "taskId": doc["task_id"], "projectId": pid,
            "projectName": project_name, "title": doc["title"],
            "content": doc["content"], "createdAt": doc["created_at"],
            "updatedAt": doc["updated_at"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Export / Import / Verify ──

import topoone.engine.export_service as _export_svc
import topoone.engine.import_service as _import_svc
import topoone.engine.verify_service as _verify_svc


@router.post("/api/export")
async def start_export(request: Request):
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        body = await request.json()
        project_id = body.get("projectId") or body.get("project_id")
        task_ids = body.get("taskIds")
        if not project_id:
            raise HTTPException(422, "projectId is required")
        export_id = _export_svc.start_export(common.multi_db, project_id, task_ids, common._publish)
        return {"exportId": export_id, "status": "running"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/export/{export_id}/status")
async def get_export_status(export_id: str):
    status = _export_svc.get_export_status(export_id)
    if not status:
        raise HTTPException(404, "Export task not found")
    return status


@router.get("/api/export/{export_id}/download")
async def download_export(export_id: str):
    status = _export_svc.get_export_status(export_id)
    if not status:
        raise HTTPException(404, "Export task not found")
    if status["status"] != "done":
        raise HTTPException(400, "Export not yet complete")
    archive_path = status.get("result", {}).get("archivePath")
    if not archive_path or not os.path.exists(archive_path):
        raise HTTPException(404, "Export file not found")
    return FileResponse(archive_path, media_type="application/zip",
                        filename=os.path.basename(archive_path))


@router.post("/api/import")
async def start_import(request: Request):
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(422, "file is required")
        mode = form.get("mode", "share")
        import_path = os.path.join(common.multi_db.data_dir, "imports")
        os.makedirs(import_path, exist_ok=True)
        local_path = os.path.join(import_path, f"upload-{uuid.uuid4().hex[:12]}.zip")
        content = await file.read()
        with open(local_path, "wb") as f:
            f.write(content)
        import_id = _import_svc.start_import(common.multi_db, local_path, common._publish,
                                              import_mode=mode, cleanup_archive=True)
        return {"importId": import_id, "status": "running"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/import/{import_id}/status")
async def get_import_status(import_id: str):
    status = _import_svc.get_import_status(import_id)
    if not status:
        raise HTTPException(404, "Import task not found")
    return status


@router.post("/api/projects/{project_id}/verify-files")
async def start_verify(project_id: str):
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        verify_id = _verify_svc.start_verify(common.multi_db, project_id, common._publish)
        return {"verifyId": verify_id, "status": "running"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/verify/{verify_id}/status")
async def get_verify_status(verify_id: str):
    status = _verify_svc.get_verify_status(verify_id)
    if not status:
        raise HTTPException(404, "Verify task not found")
    return status
