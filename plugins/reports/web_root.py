"""Web Root module — index page + project/task/doc API + export/import/verify"""

import json
import os
import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, FileResponse

import common
import common

router = APIRouter()

import community_data as cd


# ── Index page ──

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, search: str = Query(None), page: int = Query(1), page_size: int = Query(50)):
    lang = request.headers.get('Accept-Language', 'zh-CN')
    locale = 'zh-CN' if lang.startswith('zh') else 'en-US'
    _ = common._INDEX_I18N.get(locale, common._INDEX_I18N['zh-CN'])
    if not common.multi_db:
        return HTMLResponse(f'<html><body><h1>TopoCode</h1><p>Backend not ready</p></body></html>')
    try:
        ps = max(10, min(200, page_size))
        offset = (max(1, page) - 1) * ps
        q = search or ''

        all_projects = common.multi_db.main_db.fetchall(
            "SELECT id, name FROM projects "
            "WHERE (? = '' OR name LIKE ?) "
            "ORDER BY name",
            (q, f'%{q}%')
        )
        all_tasks = common.multi_db.main_db.fetchall(
            "SELECT t.id, t.name, t.status, t.project_id, p.name AS project_name "
            "FROM analysis_tasks t JOIN projects p ON t.project_id = p.id "
            "WHERE (? = '' OR t.name LIKE ? OR p.name LIKE ?) "
            "ORDER BY t.project_id, t.created_at DESC",
            (q, f'%{q}%', f'%{q}%')
        )

        tasks_by_pid = defaultdict(list)
        for t in all_tasks:
            tasks_by_pid[t["project_id"]].append(t)

        projects_map = {}
        for proj in all_projects:
            pid = proj["id"]
            tasks = tasks_by_pid.get(pid, [])
            overall_ids = [f"overall-{t['id']}" for t in tasks]
            has_doc_set = set()
            try:
                if tasks:
                    pdb = common.multi_db.get_project_db(pid)
                    ph = ",".join("?" * len(overall_ids))
                    rows = pdb.fetchall(
                        f"SELECT id FROM report_subdocs WHERE id IN ({ph})", overall_ids
                    )
                    has_doc_set = {r["id"].replace("overall-", "") for r in rows}
            except Exception:
                pass
            proj_tasks = []
            for t in tasks:
                has_ov = t["id"] in has_doc_set
                proj_tasks.append({"id": t["id"], "name": t["name"], "status": t["status"], "hasDoc": has_ov})
            is_resource = pid.startswith("TOPORES_ID:")
            projects_map[pid] = {
                "id": pid,
                "name": proj["name"],
                "tasks": proj_tasks,
                "has_doc": len(has_doc_set) > 0,
                "is_resource": is_resource,
            }

        proj_list = sorted(projects_map.values(), key=lambda x: (not x["has_doc"], x["name"]))

        flat_tasks = []
        for proj in proj_list:
            if proj["tasks"]:
                for t in proj["tasks"]:
                    flat_tasks.append((proj, t))
            else:
                flat_tasks.append((proj, None))
        total = len(flat_tasks)
        page_tasks = flat_tasks[offset:offset + ps]
        total_pages = max(1, (total + ps - 1) // ps)

        def esc(s):
            return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

        q_esc = esc(q)
        total_str = str(total)
        ps_sel_50 = ' selected' if ps == 50 else ''
        ps_sel_100 = ' selected' if ps == 100 else ''
        ps_sel_200 = ' selected' if ps == 200 else ''

        html = """<!DOCTYPE html><html lang="zh-CN"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TopoCode - Documents</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz@14..32&display=swap" rel="stylesheet">
<style>
  :root{--bg:#ffffff;--bg-secondary:#f7f7f8;--bg-hover:#f0f0f2;--text:#1a1a1a;--text-secondary:#6b6b76;--text-muted:#8e8e98;--border:#e4e4e7;--accent:#4d6bfe;--accent-hover:#3a56d4;--shadow-sm:0 1px 2px rgba(0,0,0,0.04);--shadow-md:0 4px 16px rgba(0,0,0,0.06);--radius-sm:6px;--radius-md:8px;--radius-lg:12px;--font:'Inter',-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;--transition:0.2s ease}
  @media(prefers-color-scheme:dark){:root{--bg:#212121;--bg-secondary:#2d2d2d;--bg-hover:#3d3d3d;--text:#e8e8e8;--text-secondary:#a0a0a0;--text-muted:#6b6b6b;--border:#3d3d3d;--accent:#60a5fa;--accent-hover:#3b82f6;--shadow-sm:0 1px 2px rgba(0,0,0,0.2);--shadow-md:0 4px 16px rgba(0,0,0,0.3)}}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:var(--font);background:var(--bg-secondary);color:var(--text);font-size:14px;line-height:1.6;padding:24px}
  .container{max-width:760px;margin:0 auto}
  h1{font-size:18px;font-weight:600;margin-bottom:16px}
  .toolbar{display:flex;gap:8px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
  .toolbar input{padding:7px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;flex:1;min-width:160px;outline:none;background:var(--bg);color:var(--text)}
  .toolbar input:focus{border-color:var(--accent)}
  .toolbar button{padding:7px 16px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);cursor:pointer;font-size:12px}
  .toolbar button:hover{border-color:var(--accent);color:var(--accent)}
  .toolbar select{padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg);color:var(--text);outline:none}
  .toolbar .info{font-size:12px;color:var(--text-muted)}
  .project{background:var(--bg);border-radius:var(--radius-lg);border:1px solid var(--border);margin-bottom:10px;overflow:hidden}
  .project-header{padding:10px 14px;font-weight:600;font-size:13px;background:var(--bg-secondary);border-bottom:1px solid var(--border);cursor:pointer;display:flex;align-items:center;gap:8px}
  .project-header:hover{background:var(--bg-hover)}
  .project-header .arrow{transition:transform .2s;font-size:10px;color:var(--text-muted)}
  .project-header .arrow.open{transform:rotate(90deg)}
  .project-tasks.open{display:block}
  .project-tasks{display:none}
  .task-item{padding:8px 14px 8px 32px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}
  .task-item:last-child{border-bottom:none}
  .task-item a{color:var(--accent);text-decoration:none;font-size:13px}
  .task-item a:hover{text-decoration:underline}
  .task-name-pending{color:var(--text-muted);font-size:13px}
  .status-dot{width:6px;height:6px;border-radius:50%;display:inline-block;flex-shrink:0}
  .status-dot.done{background:#10b981}
  .status-dot.pending{background:#f59e0b}
  .status-label{font-size:11px;font-weight:500}
  .status-label.done{color:#10b981}
  .status-label.pending{color:#f59e0b}
  .empty{padding:20px;color:var(--text-muted);font-size:13px;text-align:center}
  .badge{display:inline-block;padding:1px 6px;font-size:10px;font-weight:600;border-radius:4px;vertical-align:middle}
  .badge-resource{background:#e8f4fd;color:#2563eb;border:1px solid #93c5fd}
  .pagination{display:flex;gap:6px;justify-content:center;margin-top:16px;flex-wrap:wrap}
  .pagination a,.pagination span{padding:5px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;text-decoration:none;color:var(--text);background:var(--bg)}
  .pagination a:hover{background:var(--bg-hover);border-color:var(--accent)}
  .pagination .active{background:var(--accent);color:#fff;border-color:var(--accent)}
</style></head><body>
<div class="container">
<h1>__TITLE__</h1>
<div class="toolbar">
  <form method="get" action="/" style="display:flex;gap:8px;flex:1;align-items:center">
    <input type="text" name="search" placeholder="__SEARCH_PLACEHOLDER__" value="__Q_ESC__">
    <button type="submit">__SEARCH__</button>
  </form>
  <select onchange="location.href='/?search='+encodeURIComponent('__Q_ESC__')+'&page=1&page_size='+this.value">
    <option value="50"__PS_50__>__P50__</option>
    <option value="100"__PS_100__>__P100__</option>
    <option value="200"__PS_200__>__P200__</option>
  </select>
  <span class="info">__TOTAL_LABEL__</span>
  <a href="/chat" target="_blank" style="font-size:12px;color:var(--accent);text-decoration:none;display:inline-flex;align-items:center;gap:3px;padding:4px 8px;border-radius:4px;transition:background .15s;" onmouseover="this.style.background='var(--bg-hover)'" onmouseout="this.style.background='transparent'"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>__AI__</a>
</div>"""
        html = html.replace('__Q_ESC__', q_esc)
        html = html.replace('__TITLE__', _['title'])
        html = html.replace('__SEARCH_PLACEHOLDER__', _['search_placeholder'])
        html = html.replace('__SEARCH__', _['search'])
        html = html.replace('__P50__', _['per_page_50'])
        html = html.replace('__P100__', _['per_page_100'])
        html = html.replace('__P200__', _['per_page_200'])
        html = html.replace('__TOTAL_LABEL__', _['total'].replace('{n}', total_str))
        html = html.replace('__AI__', _['ai'])
        html = html.replace('__PS_50__', ps_sel_50).replace('__PS_100__', ps_sel_100).replace('__PS_200__', ps_sel_200)

        last_pid = None
        for proj, t in page_tasks:
            pid = proj["id"]
            if pid != last_pid:
                if last_pid is not None:
                    html += '</div></div>'
                resource_badge = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="#22c55e" style="width:14px;height:14px;vertical-align:middle;margin-right:3px"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25"/></svg><span class="badge badge-resource">资源中心导入</span>' if proj["is_resource"] else ''
                html += f'<div class="project"><div class="project-header" onclick="this.nextElementSibling.classList.toggle(\'open\');this.querySelector(\'.arrow\').classList.toggle(\'open\')"><span class="arrow">▶</span> {esc(proj["name"])} {resource_badge}</div><div class="project-tasks open">'
                last_pid = pid
            if t is None:
                html += f'<div class="task-item" style="color:var(--text-muted);font-size:12px;">{_["no_task"]}</div>'
            else:
                dot_class = 'done' if t["hasDoc"] else 'pending'
                if t["hasDoc"]:
                    html += f'<div class="task-item"><span class="status-dot {dot_class}"></span><a href="/doc?taskId={esc(t["id"])}&docId=overall-{esc(t["id"])}">{esc(t["name"])}</a><span class="status-label {dot_class}">{_["generated"]}</span></div>'
                else:
                    html += f'<div class="task-item"><span class="status-dot {dot_class}"></span><span class="task-name-pending">{esc(t["name"])}</span><span class="status-label {dot_class}">{_["not_generated"]}</span></div>'
        if last_pid is not None:
            html += '</div></div>'
        if total == 0:
            html += f'<div class="empty">{_["no_matches"]}</div>'

        if total_pages > 1:
            html += '<div class="pagination">'
            base_q = f'search={esc(q)}&page_size={ps}' if q else f'page_size={ps}'
            if page > 1:
                html += f'<a href="/?{base_q}&page={page-1}">‹</a>'
            for pn in range(max(1, page - 3), min(total_pages, page + 3) + 1):
                cls = 'active' if pn == page else ''
                html += f'<a class="{cls}" href="/?{base_q}&page={pn}">{pn}</a>'
            if page < total_pages:
                html += f'<a href="/?{base_q}&page={page+1}">›</a>'
            html += '</div>'

        html += '</div></body></html>'
        return HTMLResponse(html)
    except Exception as e:
        return HTMLResponse(f"<html><body><h1>Error</h1><p>{e}</p></body></html>")


# ── Projects API ──

@router.get("/api/projects")
async def list_projects():
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        projects = common.multi_db.main_db.fetchall("SELECT id, name, root_path FROM projects")
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

@router.get("/api/docs", response_class=HTMLResponse)
async def list_docs_html():
    if not common.multi_db:
        return HTMLResponse("Backend not ready", status_code=503)
    try:
        projects = common.multi_db.main_db.fetchall("SELECT id, name FROM projects")
        html = "<html><body><h1>Documents</h1>"
        for p in projects:
            html += f"<h2>{p['name']}</h2><ul>"
            tasks = common.multi_db.main_db.fetchall(
                "SELECT id, name FROM analysis_tasks WHERE project_id = ?", (p["id"],)
            )
            for t in tasks:
                html += f"<li><a href='/doc?taskId={t['id']}'>{t['name']}</a></li>"
            html += "</ul>"
        html += "</body></html>"
        return html
    except Exception as e:
        return HTMLResponse(f"Error: {e}", status_code=500)


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


@router.get("/api/task-docs")
async def list_task_docs(task_id: str = Query(None), taskId: str = Query(None)):
    tid = task_id or taskId
    if not tid:
        raise HTTPException(422, "task_id or taskId is required")
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        task = common.multi_db.main_db.fetchone("SELECT project_id FROM analysis_tasks WHERE id = ?", (tid,))
        if not task:
            return {"docs": [], "error": "Task not found"}
        pdb = common.multi_db.get_project_db(task["project_id"])
        docs = pdb.fetchall(
            "SELECT id, task_id, title, created_at FROM report_subdocs WHERE task_id = ? ORDER BY created_at",
            (tid,),
        )
        return [{"id": d["id"], "taskId": d["task_id"], "title": d["title"], "createdAt": d["created_at"]} for d in docs]
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Export / Import / Verify ──

import export_service as _export_svc
import import_service as _import_svc
import verify_service as _verify_svc


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
