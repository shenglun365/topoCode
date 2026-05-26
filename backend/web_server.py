"""Web Server - FastAPI 提供本地 HTTP 文档浏览服务"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# 在 start_http_server 中注入
multi_db = None
plantuml_cache_db: Optional[sqlite3.Connection] = None
http_port = 3456

app = FastAPI(title="TopoOne Web Viewer")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ==================== PlantUML 缓存 ====================

def _init_cache_db(cache_path: str):
    global plantuml_cache_db
    plantuml_cache_db = sqlite3.connect(cache_path, check_same_thread=False)
    plantuml_cache_db.execute(
        "CREATE TABLE IF NOT EXISTS plantuml_cache ("
        "  code_hash TEXT PRIMARY KEY,"
        "  code TEXT NOT NULL,"
        "  svg TEXT NOT NULL,"
        "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    plantuml_cache_db.commit()


def _get_cached_plantuml(code_hash: str) -> Optional[str]:
    if not plantuml_cache_db:
        return None
    cursor = plantuml_cache_db.execute(
        "SELECT svg FROM plantuml_cache WHERE code_hash = ?", (code_hash,)
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _set_cached_plantuml(code_hash: str, code: str, svg: str):
    if not plantuml_cache_db:
        return
    plantuml_cache_db.execute(
        "INSERT OR REPLACE INTO plantuml_cache (code_hash, code, svg) VALUES (?, ?, ?)",
        (code_hash, code, svg),
    )
    plantuml_cache_db.commit()


def _clear_plantuml_cache():
    if plantuml_cache_db:
        plantuml_cache_db.execute("DELETE FROM plantuml_cache")
        plantuml_cache_db.commit()


# ==================== API 路由 ====================


@app.get("/api/projects")
async def list_projects():
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        from core_service import register_project_methods
        projects = multi_db.main_db.fetchall("SELECT id, name, root_path FROM projects")
        return [{"id": p["id"], "name": p["name"], "rootPath": p["root_path"]} for p in projects]
    except Exception as e:
        logger.error(f"list_projects error: {e}")
        return []


@app.get("/api/tasks")
async def list_tasks(project_id: str = Query(...)):
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        tasks = multi_db.main_db.fetchall(
            "SELECT id, name, type, status, project_id FROM tasks WHERE project_id = ?",
            (project_id,),
        )
        return [
            {
                "id": t["id"],
                "name": t["name"],
                "type": t["type"],
                "status": t["status"],
                "projectId": t["project_id"],
            }
            for t in tasks
        ]
    except Exception as e:
        logger.error(f"list_tasks error: {e}")
        return []


@app.get("/api/docs", response_class=HTMLResponse)
async def list_docs_html():
    if not multi_db:
        raise HTMLResponse("Backend not ready", status_code=503)
    try:
        projects = multi_db.main_db.fetchall("SELECT id, name FROM projects")
        html = "<html><body><h1>Documents</h1>"
        for p in projects:
            html += f"<h2>{p['name']}</h2><ul>"
            tasks = multi_db.main_db.fetchall(
                "SELECT id, name FROM tasks WHERE project_id = ?", (p["id"],)
            )
            for t in tasks:
                html += f"<li><a href='/doc?taskId={t['id']}'>{t['name']}</a></li>"
            html += "</ul>"
        html += "</body></html>"
        return html
    except Exception as e:
        return HTMLResponse(f"Error: {e}", status_code=500)


@app.get("/api/docs/{doc_id}")
async def get_doc(doc_id: str):
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        # 遍历项目库查找 report_subdocs
        projects = multi_db.main_db.fetchall("SELECT id FROM projects")
        for proj in projects:
            pid = proj["id"]
            try:
                pdb = multi_db.get_project_db(pid)
                doc = pdb.fetchone(
                    "SELECT id, task_id, title, content, created_at, updated_at FROM report_subdocs WHERE id = ?",
                    (doc_id,),
                )
                if doc:
                    project_id = pid
                    logger.info(f"=== Document URL: http://127.0.0.1:{http_port}/doc?docId={doc_id} ===")
                    return {
                        "id": doc["id"],
                        "taskId": doc["task_id"],
                        "projectId": project_id,
                        "title": doc["title"],
                        "content": doc["content"],
                        "createdAt": doc["created_at"],
                        "updatedAt": doc["updated_at"],
                    }
            except Exception:
                continue

        raise HTTPException(404, "Document not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/community-doc")
async def get_community_doc(task_id: str = Query(None), taskId: str = Query(None),
                            community_id: str = Query(None), communityId: str = Query(None),
                            edge_type: str = Query(None), edgeType: str = Query(None)):
    tid = task_id or taskId
    cid = community_id or communityId
    et = edge_type or edgeType or 'CALL'
    if not tid or not cid:
        raise HTTPException(422, "task_id/taskId and community_id/communityId are required")
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        task = multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (tid,)
        )
        if not task:
            raise HTTPException(404, "Task not found")
        pid = task["project_id"]
        pdb = multi_db.get_project_db(pid)
        row = pdb.fetchone(
            "SELECT name, summary, mermaid, plantuml FROM community_llm_results WHERE task_id=? AND edge_type=? AND comm_lv='L0' AND comm_id=?",
            (tid, et, cid)
        )
        if not row:
            raise HTTPException(404, "Community result not found")
        name = row.get("name") or cid
        parts = [f"# {name}", "", f"**ID**: {cid}  **类型**: {et}", "", row.get("summary") or ""]
        if row.get("mermaid"):
            parts.extend(["", "```mermaid", row["mermaid"], "```"])
        if row.get("plantuml"):
            parts.extend(["", "```plantuml", row["plantuml"], "```"])
        return {
            "id": f"community-{tid}-{et}-{cid}",
            "taskId": tid,
            "projectId": pid,
            "title": name,
            "content": "\n".join(parts),
            "createdAt": "",
            "updatedAt": "",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/task-docs")
async def list_task_docs(task_id: str = Query(None), taskId: str = Query(None)):
    tid = task_id or taskId
    if not tid:
        raise HTTPException(422, "task_id or taskId is required")
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        result = []
        projects = multi_db.main_db.fetchall("SELECT id FROM projects")
        for proj in projects:
            try:
                pdb = multi_db.get_project_db(proj["id"])
                docs = pdb.fetchall(
                    "SELECT id, task_id, title, created_at FROM report_subdocs WHERE task_id = ? ORDER BY created_at",
                    (tid,),
                )
                for d in docs:
                    result.append({
                        "id": d["id"],
                        "taskId": d["task_id"],
                        "title": d["title"],
                        "createdAt": d["created_at"],
                    })
            except Exception:
                continue
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/file")
async def get_file(project_id: str = Query(...), path: str = Query(...)):
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        project = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (project_id,)
        )
        if not project:
            raise HTTPException(404, "Project not found")
        root_path = project["root_path"]
        full_path = os.path.normpath(os.path.join(root_path, path))
        if not full_path.startswith(os.path.normpath(root_path)):
            raise HTTPException(403, "Path outside project root")
        if not os.path.isfile(full_path):
            raise HTTPException(404, "File not found")
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
        return {
            "content": text,
            "language": lang_map.get(ext.lower(), ""),
            "path": path,
            "truncated": truncated,
            "size": size,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/plantuml")
async def render_plantuml(code: str = Query(...)):
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        code_hash = hashlib.md5(code.encode("utf-8")).hexdigest()
        cached = _get_cached_plantuml(code_hash)
        if cached:
            return Response(content=cached, media_type="image/svg+xml")
        from plantuml_service import render_plantuml as render_pu
        svg_bytes = render_pu(code, format="svg", use_remote=True)
        svg_text = svg_bytes.decode("utf-8", errors="replace")
        _set_cached_plantuml(code_hash, code, svg_text)
        return Response(content=svg_text, media_type="image/svg+xml")
    except Exception as e:
        raise HTTPException(500, f"PlantUML render failed: {e}")


@app.get("/api/plantuml/clear-cache")
async def clear_plantuml_cache():
    _clear_plantuml_cache()
    return {"status": "ok"}


# ==================== 静态页面 ====================


@app.get("/", response_class=HTMLResponse)
async def index():
    return await list_docs_html()


@app.get("/doc", response_class=HTMLResponse)
async def view_doc(task_id: str = Query(None), doc_id: str = Query(None),
                   taskId: str = Query(None), docId: str = Query(None)):
    tid = task_id or taskId or ''
    did = doc_id or docId or ''
    viewer_path = os.path.join(STATIC_DIR, "viewer.html")
    logger.info(f"=== Document viewer URL: http://127.0.0.1:{http_port}/doc?docId={did}&taskId={tid} ===")
    if os.path.isfile(viewer_path):
        return FileResponse(viewer_path)
    return HTMLResponse("viewer.html not found", status_code=404)


@app.get("/code", response_class=HTMLResponse)
async def view_code():
    code_path = os.path.join(STATIC_DIR, "code.html")
    if os.path.isfile(code_path):
        return FileResponse(code_path)
    return HTMLResponse("code.html not found", status_code=404)


def create_app(multi_db_instance) -> FastAPI:
    global multi_db
    multi_db = multi_db_instance
    return app


# ==================== 启动入口 ====================


async def start_http_server(multi_db_instance, port: int = 3456, cache_path: str = None):
    global multi_db, http_port
    http_port = port
    multi_db = multi_db_instance
    if cache_path:
        _init_cache_db(cache_path)
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Web server starting on http://0.0.0.0:{port}")
    await server.serve()
