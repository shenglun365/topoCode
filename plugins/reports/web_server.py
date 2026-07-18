"""Web Server - FastAPI 提供本地 HTTP 文档浏览服务"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import uuid
from collections import defaultdict
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# 在 start_http_server 中注入
multi_db = None
zmq_server = None  # ZMQ server for pub events
plantuml_cache_db: Optional[sqlite3.Connection] = None
http_port = 3456

# 管理活动中止状态（keyed by session_id）
import threading as _threading
_active_streams: dict = {}
_active_streams_lock = _threading.Lock()
web_tool_executor = None

# 统一数据模块
import sys as _sys
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_backend_dir = os.path.join(_project_root, "backend-core")
if _backend_dir not in _sys.path:
    _sys.path.insert(0, _backend_dir)
import community_data as cd
from web_tools import WebToolExecutor, resolve_refs_to_context
from skills import get_skill_registry

app = FastAPI(title="TopoOne Web Viewer")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
import mimetypes
mimetypes.add_type("application/javascript", ".mjs")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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
        projects = multi_db.main_db.fetchall("SELECT id, name, root_path FROM projects")
        return [{
            "id": p["id"],
            "name": p["name"],
            "rootPath": p["root_path"],
            "isResource": p["id"].startswith("TOPORES_ID:"),
        } for p in projects]
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
        pid = resolve_project_by_doc_id(doc_id)
        if not pid:
            raise HTTPException(404, f"Document {doc_id} not found")
        pdb = multi_db.get_project_db(pid)
        doc = pdb.fetchone(
            "SELECT id, task_id, title, content, created_at, updated_at FROM report_subdocs WHERE id = ?",
            (doc_id,),
        )
        if not doc:
            raise HTTPException(404, f"Document {doc_id} not found")
        proj_row = multi_db.main_db.fetchone(
            "SELECT name FROM projects WHERE id = ?", (pid,)
        )
        project_name = proj_row["name"] if proj_row else ""
        logger.info(f"=== Document URL: http://127.0.0.1:{http_port}/doc?docId={doc_id} ===")
        return {
            "id": doc["id"],
            "taskId": doc["task_id"],
            "projectId": pid,
            "projectName": project_name,
            "title": doc["title"],
            "content": doc["content"],
            "createdAt": doc["created_at"],
            "updatedAt": doc["updated_at"],
        }
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
            "SELECT t.project_id, p.name AS project_name FROM analysis_tasks t JOIN projects p ON t.project_id = p.id WHERE t.id = ?", (tid,)
        )
        if not task:
            raise HTTPException(404, "Task not found")
        pid = task["project_id"]
        project_name = task["project_name"]
        pdb = multi_db.get_project_db(pid)
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
            "taskId": tid,
            "projectId": pid,
            "projectName": project_name,
            "title": name,
            "content": "\n".join(parts),
            "createdAt": "",
            "updatedAt": "",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/community-files")
async def get_community_files(task_id: str = Query(None), taskId: str = Query(None),
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
        proj_row = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""
        _rel = cd._make_rel(project_root)

        rows = pdb.fetchall(
            "SELECT comm_id, comm_lv, node_list FROM graph_doc "
            "WHERE task_id=? AND edge_type=? AND comm_id=? "
            "ORDER BY comm_lv, comm_id",
            (tid, et, cid)
        )
        # 嵌套社区（L1+）在 graph_doc 中无记录，回退到 L0 祖先
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
                        "path": clean,
                        "name": parts[-1] if parts else clean,
                        "parentDir": parts[-2] if len(parts) >= 2 else "",
                        "commId": r["comm_id"],
                        "commLv": r["comm_lv"]
                    })
        return {"files": files, "total": len(files), "projectId": pid}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/file-summary")
async def get_file_summary(task_id: str = Query(None), taskId: str = Query(None),
                            file_path: str = Query(None), filePath: str = Query(None)):
    tid = task_id or taskId
    fp = file_path or filePath
    if not tid or not fp:
        raise HTTPException(422, "task_id/taskId and file_path/filePath are required")
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
            "SELECT summary, summary_len, created_at, source, task_id FROM file_summaries "
            "WHERE project_id=? AND file_path=? ORDER BY created_at DESC LIMIT 1",
            (pid, fp)
        )
        if row:
            return {"found": True, "summary": row["summary"], "summary_len": row["summary_len"],
                    "created_at": row["created_at"], "source": row["source"], "task_id": row["task_id"]}
        return {"found": False}
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
        task = multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (tid,)
        )
        if not task:
            return {"docs": [], "error": "Task not found"}
        pdb = multi_db.get_project_db(task["project_id"])
        docs = pdb.fetchall(
            "SELECT id, task_id, title, created_at FROM report_subdocs WHERE task_id = ? ORDER BY created_at",
            (tid,),
        )
        result = [
            {
                "id": d["id"],
                "taskId": d["task_id"],
                "title": d["title"],
                "createdAt": d["created_at"],
            }
            for d in docs
        ]
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/community-children")
async def get_community_children(task_id: str = Query(None), taskId: str = Query(None),
                                  parent_comm_id: str = Query(None), parentCommId: str = Query(None),
                                  edge_type: str = Query(None), edgeType: str = Query(None)):
    tid = task_id or taskId
    pid = parent_comm_id or parentCommId
    et = (edge_type or edgeType or 'CALL').upper()
    if not tid:
        raise HTTPException(422, "task_id/taskId is required")
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        _, pdb = _resolve_project_db(tid)
        return cd.get_community_children(pdb, tid, et, pid or None)
    except HTTPException:
        raise
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
            # 文件不存在时，在 source_files 中查找同名文件作为备选
            alt = _find_file_alternatives(project_id, path)
            raise HTTPException(status_code=404, detail={
                "message": "File not found",
                "alternatives": alt,
            })
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


@app.get("/api/template-locale")
async def get_template_locale():
    """获取默认模板语言"""
    if not multi_db:
        return {"locale": "zh-CN"}
    try:
        row = multi_db.main_db.fetchone(
            "SELECT value FROM context_store WHERE key='default_template_locale'"
        )
        return {"locale": row["value"] if row else "zh-CN"}
    except Exception:
        return {"locale": "zh-CN"}


@app.get("/api/plantuml/clear-cache")
async def clear_plantuml_cache():
    _clear_plantuml_cache()
    return {"status": "ok"}


def _find_file_alternatives(project_id: str, path: str) -> list:
    """在项目 source_files 中查找匹配文件，返回备选路径列表（模糊匹配文件名）"""
    basename = os.path.basename(path)
    if not basename:
        return []
    try:
        project_db = multi_db.get_project_db(project_id)
        seen = set()
        results = []
        def add(row):
            fp = row[0]
            if fp not in seen:
                seen.add(fp)
                results.append({"file_path": fp, "file_name": row[1], "language": row[2]})

        # 1. 精确文件名匹配 file_path LIKE %/ioport.h
        for row in project_db.execute(
            "SELECT file_path, file_name, language FROM source_files WHERE file_path LIKE ?",
            (f"%/{basename}",),
        ).fetchall():
            add(row)

        if not results:
            # 2. 去掉扩展名匹配 file_name（如 ioport.h → ioport）
            name_no_ext = os.path.splitext(basename)[0]
            if name_no_ext:
                for row in project_db.execute(
                    "SELECT file_path, file_name, language FROM source_files WHERE file_name = ?",
                    (name_no_ext,),
                ).fetchall():
                    add(row)

        if not results:
            # 3. 最宽松：file_name 模糊 LIKE（basename 截断前 8 字符）
            short = basename[:8].replace(".", "_")
            for row in project_db.execute(
                "SELECT file_path, file_name, language FROM source_files WHERE file_name LIKE ?",
                (f"%{short}%",),
            ).fetchall():
                add(row)

        return results
    except Exception:
        return []

# ==================== 静态页面 ====================


# i18n for index page
_INDEX_I18N = {
    'zh-CN': {
        'title': 'TopoCode 文档', 'search_placeholder': '搜索项目/任务...', 'search': '搜索',
        'per_page_50': '50条/页', 'per_page_100': '100条/页', 'per_page_200': '200条/页',
        'total': '共 {n} 条', 'ai': 'AI助手',
        'no_task': '资源项目 — 无需分析任务',
        'generated': '已生成', 'not_generated': '未生成', 'no_matches': '暂无匹配结果',
    },
    'en-US': {
        'title': 'TopoCode Documents', 'search_placeholder': 'Search projects/tasks...', 'search': 'Search',
        'per_page_50': '50/page', 'per_page_100': '100/page', 'per_page_200': '200/page',
        'total': 'Total {n}', 'ai': 'AI Assistant',
        'no_task': 'Resource — no analysis',
        'generated': 'Done', 'not_generated': 'Pending', 'no_matches': 'No matches',
    },
}

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, search: str = Query(None), page: int = Query(1), page_size: int = Query(50)):
    # Detect locale
    lang = request.headers.get('Accept-Language', 'zh-CN')
    locale = 'zh-CN' if lang.startswith('zh') else 'en-US'
    _ = _INDEX_I18N.get(locale, _INDEX_I18N['zh-CN'])
    if not multi_db:
        return HTMLResponse(f'<html><body><h1>TopoCode</h1><p>Backend not ready</p></body></html>')
    try:
        ps = max(10, min(200, page_size))
        offset = (max(1, page) - 1) * ps
        q = search or ''

        # 查所有项目（含无任务项目），附加任务列表
        all_projects = multi_db.main_db.fetchall(
            "SELECT id, name FROM projects "
            "WHERE (? = '' OR name LIKE ?) "
            "ORDER BY name",
            (q, f'%{q}%')
        )
        all_tasks = multi_db.main_db.fetchall(
            "SELECT t.id, t.name, t.status, t.project_id, p.name AS project_name "
            "FROM analysis_tasks t JOIN projects p ON t.project_id = p.id "
            "WHERE (? = '' OR t.name LIKE ? OR p.name LIKE ?) "
            "ORDER BY t.project_id, t.created_at DESC",
            (q, f'%{q}%', f'%{q}%')
        )

        # 按项目分组任务
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
                    pdb = multi_db.get_project_db(pid)
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

        # 排序：有文档的靠前，其余按项目名
        proj_list = sorted(projects_map.values(), key=lambda x: (not x["has_doc"], x["name"]))

        # 分页：所有任务扁平化后分页
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
  body{font-family:var(--font);background:var(--bg-secondary);color:var(--text);font-size:14px;line-height:1.6;padding:24px;-webkit-font-smoothing:antialiased}
  .container{max-width:760px;margin:0 auto}
  h1{font-size:18px;font-weight:600;margin-bottom:16px;color:var(--text)}
  .toolbar{display:flex;gap:8px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
  .toolbar input{padding:7px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;flex:1;min-width:160px;outline:none;background:var(--bg);color:var(--text);transition:border-color var(--transition)}
  .toolbar input:focus{border-color:var(--accent)}
  .toolbar button{padding:7px 16px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);cursor:pointer;font-size:12px;transition:all var(--transition)}
  .toolbar button:hover{border-color:var(--accent);color:var(--accent)}
  .toolbar select{padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg);color:var(--text);outline:none}
  .toolbar .info{font-size:12px;color:var(--text-muted)}
  .project{background:var(--bg);border-radius:var(--radius-lg);border:1px solid var(--border);margin-bottom:10px;overflow:hidden;box-shadow:var(--shadow-sm)}
  .project-header{padding:10px 14px;font-weight:600;font-size:13px;background:var(--bg-secondary);border-bottom:1px solid var(--border);cursor:pointer;display:flex;align-items:center;gap:8px;transition:background var(--transition)}
  .project-header:hover{background:var(--bg-hover)}
  .project-header .arrow{transition:transform .2s;font-size:10px;color:var(--text-muted)}
  .project-header .arrow.open{transform:rotate(90deg)}
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
  .pagination a,.pagination span{padding:5px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;text-decoration:none;color:var(--text);background:var(--bg);transition:all var(--transition)}
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

        # 分页
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


# ==================== 可视化 API ====================

def _resolve_project_db(task_id: str):
    """Helper: 根据 task_id 获取 project_db"""
    task_row = multi_db.main_db.fetchone(
        "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
    )
    if not task_row:
        raise HTTPException(404, f"Task {task_id} not found")
    return task_row["project_id"], multi_db.get_project_db(task_row["project_id"])


def resolve_project_by_doc_id(doc_id: str) -> str | None:
    """根据 doc_id 定位 project_id。三步：快速路径 → 映射表 → 兜底遍历。"""
    if not multi_db:
        return None
    # 1. 快速路径：doc_id 前缀解析
    task_id = _extract_task_id_from_doc_id(doc_id)
    if task_id:
        row = multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
        )
        if row:
            return row["project_id"]
    # 2. 查映射表
    row = multi_db.main_db.fetchone(
        "SELECT project_id FROM doc_project_map WHERE doc_id = ?", (doc_id,)
    )
    if row:
        return row["project_id"]
    # 3. 兜底：遍历项目库（首次后写入缓存，后续瞬回）
    projects = multi_db.main_db.fetchall("SELECT id FROM projects")
    for proj in projects:
        pid = proj["id"]
        try:
            pdb = multi_db.get_project_db(pid)
            if pdb.fetchone("SELECT 1 FROM report_subdocs WHERE id=?", (doc_id,)):
                multi_db.main_db.execute(
                    "INSERT OR IGNORE INTO doc_project_map (doc_id, project_id, task_id) VALUES (?, ?, ?)",
                    (doc_id, pid, task_id or ""),
                )
                return pid
        except Exception:
            continue
    return None


def _extract_task_id_from_doc_id(doc_id: str) -> str | None:
    """从 doc_id 提取 task_id。overall-{taskId} / subdoc-{taskId}-*"""
    if doc_id.startswith("overall-"):
        return doc_id[len("overall-"):]
    if doc_id.startswith("subdoc-"):
        rest = doc_id[len("subdoc-"):]
        idx = rest.find("-")
        return rest[:idx] if idx > 0 else rest
    return None


@app.get("/api/community-graph")
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
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = _resolve_project_db(task_id)
        et = (edge_type or edgeType or "CALL").upper()
        proj_row = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""

        if gn == "component":
            return cd.get_community_graph_component(
                pdb, task_id, et, comm_lv, comm_id, project_root,
                depth=int(depth) if depth else 1)
        else:
            return cd.get_community_graph_file(
                pdb, task_id, et, comm_lv, comm_id, project_root)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[community-graph] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, str(e))


@app.get("/api/file-graph")
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
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = _resolve_project_db(task_id)
        et = (edge_type or edgeType or "CALL").upper()
        proj_row = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""

        _proot = project_root.replace('\\', '/') if project_root else ''
        def _rel(p):
            if not p: return p
            if p.startswith('file:'): p = p[5:]
            p = p.replace('\\', '/')
            if _proot and p.lower().startswith(_proot.lower()): p = p[len(_proot):]
            return p.lstrip('/')

        # 构建 file_path → comm_id 映射（用于 scope 过滤）
        file_comm = {}
        all_doc_rows = pdb.fetchall(
            "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=?",
            (task_id, et)
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

        # 收集目标文件列表
        target_files = set()
        if comm_id == "__all__":
            # 全局模式：取所有社区的全部文件
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
            # 指定社区：从 graph_doc.node_list 获取该社区内的文件
            doc_rows = pdb.fetchall(
                "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id=?",
                (task_id, et, comm_id)
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
            # 未指定社区：取第一个 L0 社区文件
            doc_rows = pdb.fetchall(
                "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv='L0' LIMIT 1",
                (task_id, et)
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

        # 获取节点数据
        all_nodes = pdb.fetchall(
            "SELECT id, file_path FROM graph_node WHERE task_id=?",
            (task_id,)
        )
        node_map = {}
        fp_to_id = {}
        for n in all_nodes:
            fp = _rel(n["file_path"] or "")
            if fp and fp in target_files:
                node_map[fp] = {"id": fp, "label": fp}
                if n["id"]:
                    fp_to_id[fp] = n["id"]

        # 获取边数据，按 scope 过滤
        kind = "imports" if et == "INCLUDE" else "calls"
        all_edges = pdb.fetchall(
            "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
            (task_id, kind)
        )
        edge_set = set()
        for e in all_edges:
            src = _rel(e["source_id"] or "")
            tgt = _rel(e["target_id"] or "")
            if not src or not tgt or src not in node_map or tgt not in node_map:
                continue
            if sc == "internal":
                # 内部：边两端在同一社区
                if file_comm.get(src) == file_comm.get(tgt):
                    eid = f"{src}→{tgt}"
                    edge_set.add(eid)
            elif sc == "external":
                # 外部：边两端在不同社区
                if file_comm.get(src) and file_comm.get(tgt) and file_comm[src] != file_comm[tgt]:
                    eid = f"{src}→{tgt}"
                    edge_set.add(eid)
            else:
                # 'both' or default: 不过滤
                eid = f"{src}→{tgt}"
                edge_set.add(eid)

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


@app.get("/api/cascade-levels")
async def get_cascade_levels(task_id: str = Query(None), taskId: str = Query(None),
                              edge_type: str = Query(None), edgeType: str = Query(None)):
    task_id = task_id or taskId
    edge_type = edge_type or edgeType or "CALL"
    if not task_id:
        raise HTTPException(422, "task_id is required")
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        _, pdb = _resolve_project_db(task_id)
        et = (edge_type or edgeType or "CALL").upper()
        return cd.get_cascade_levels(pdb, task_id, et)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


def _drill_heatmap(pdb, task_id, et, comm_lv, comm_id, size, project_root):
    """下钻热力图：子社区间跨社区边矩阵（文件级数据聚合到子社区）"""
    children = cd.get_community_children(pdb, task_id, et, comm_id)
    if not children:
        return {"rows": [], "cols": [], "matrix": [], "maxCount": 0}

    child_ids = [c["commId"] for c in children]
    child_names = {c["commId"]: c.get("name") or c["commId"] for c in children}

    _rel = cd._make_rel(project_root)

    # 文件级数据：当前 drill 社区的 node_list（文件→子社区映射）
    file_child = {}
    for child_cid in child_ids:
        doc_rows = pdb.fetchall(
            "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id=?",
            (task_id, et, child_cid)
        )
        for dr in doc_rows:
            try:
                nodes = json.loads(dr["node_list"]) if isinstance(dr["node_list"], str) else dr["node_list"] or []
            except Exception:
                nodes = []
            for n in (nodes if isinstance(nodes, list) else [nodes]):
                key = str(n) if isinstance(n, str) else str(n.get("id", ""))
                fp = _rel(key)
                if fp:
                    clean = fp.split(':')[0] if ':' in fp else fp
                    if clean and clean not in file_child:
                        file_child[clean] = child_cid

    if not file_child:
        return {"rows": [], "cols": [], "matrix": [], "maxCount": 0}

    # 从 graph_edge 获取跨社区边
    kind = "imports" if et == "INCLUDE" else "calls"
    all_ge = pdb.fetchall(
        "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
        (task_id, kind)
    )
    hash_to_path = cd.resolve_call_symbols(pdb, task_id, all_ge, _rel) if et == "CALL" else {}

    # 统计子社区间边
    edge_counts = {}
    for e in all_ge:
        src = _rel(e["source_id"] or "")
        tgt = _rel(e["target_id"] or "")
        if not src or not tgt:
            continue
        if ':' in src: src = src.split(':')[0]
        if ':' in tgt: tgt = tgt.split(':')[0]
        src = hash_to_path.get(src, src)
        tgt = hash_to_path.get(tgt, tgt)
        src_child = file_child.get(src)
        tgt_child = file_child.get(tgt)
        if not src_child or not tgt_child or src_child == tgt_child:
            continue
        pair = (src_child, tgt_child)
        edge_counts[pair] = edge_counts.get(pair, 0) + 1

    n = len(child_ids)
    comm_index = {cid: i for i, cid in enumerate(child_ids)}
    matrix = [[0] * n for _ in range(n)]
    for (src_c, tgt_c), cnt in edge_counts.items():
        si = comm_index.get(src_c)
        ti = comm_index.get(tgt_c)
        if si is not None and ti is not None:
            matrix[si][ti] = cnt

    max_count = max(max(row) for row in matrix) if n > 0 else 0
    return {
        "rows": [child_names[cid] for cid in child_ids],
        "cols": [child_names[cid] for cid in child_ids],
        "matrix": matrix, "maxCount": max_count,
        "commIds": child_ids
    }


@app.get("/api/heatmap")
async def get_heatmap(task_id: str = Query(None), taskId: str = Query(None),
                       edge_type: str = Query(None), edgeType: str = Query(None),
                       size: int = Query(10),
                       comm_id: str = Query(None), commId: str = Query(None),
                       comm_lv: str = Query(None), commLv: str = Query(None)):
    task_id = task_id or taskId
    edge_type = edge_type or edgeType or "CALL"
    if not task_id:
        raise HTTPException(422, "task_id is required")
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    size = max(5, min(50, size))
    try:
        pid, pdb = _resolve_project_db(task_id)
        et = (edge_type or edgeType or "CALL").upper()
        cid = comm_id or commId or ""
        clv = comm_lv or commLv or "L0"
        proj_row = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""

        if cid:
            # 有 drill → 构建该社区的子社区间跨社区矩阵
            return _drill_heatmap(pdb, task_id, et, clv, cid, size, project_root)
        return cd.get_heatmap(pdb, task_id, et, project_root, "L0", size)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[heatmap] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, str(e))


@app.get("/api/external-graph")
async def get_external_graph(task_id: str = Query(None), taskId: str = Query(None),
                              edge_type: str = Query(None), edgeType: str = Query(None),
                              depth: int = Query(1), comm_id: str = Query(None), commId: str = Query(None)):
    tid = task_id or taskId
    et = edge_type or edgeType or 'EXTERNAL_INCLUDE'
    cid = comm_id or commId or ''
    if not tid:
        raise HTTPException(422, "taskId is required")
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = _resolve_project_db(tid)
        proj_row = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""
        return cd.get_external_graph(pdb, tid, et, depth, cid, project_root)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[external-graph] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, str(e))


@app.get("/api/external-stats")
async def get_external_stats(task_id: str = Query(None), taskId: str = Query(None)):
    tid = task_id or taskId
    if not tid:
        raise HTTPException(422, "task_id is required")
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = _resolve_project_db(tid)
        proj_row = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""
        return cd.get_external_stats(pdb, tid, project_root)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[external-stats] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, str(e))


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


@app.get("/chat", response_class=HTMLResponse)
async def view_chat():
    chat_path = os.path.join(STATIC_DIR, "chat.html")
    if os.path.isfile(chat_path):
        return FileResponse(chat_path)
    return HTMLResponse("chat.html not found.")


# ==================== Graph Layout Persistence ====================

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

@app.post("/api/graph-layout")
async def save_graph_layout(request: Request):
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        body = await request.json()
        tid = body.get("taskId") or body.get("task_id", "")
        comm_id = body.get("commId") or body.get("comm_id", "")
        et = body.get("edgeType") or body.get("edge_type", "")
        gran = body.get("gran", "component")
        depth = body.get("depth", 1)
        nodes = body.get("nodes", {})  # {nodeId: {x, y}}
        if not tid:
            raise HTTPException(422, "taskId is required")
        pid, pdb = _resolve_project_db(tid)
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

@app.get("/api/graph-layout")
async def load_graph_layout(task_id: str = Query(None), taskId: str = Query(None),
                             comm_id: str = Query(None), commId: str = Query(None),
                             edge_type: str = Query(None), edgeType: str = Query(None),
                             gran: str = Query("component"), depth: int = Query(1)):
    tid = task_id or taskId
    cid = comm_id or commId or ""
    et = edge_type or edgeType or ""
    if not tid:
        raise HTTPException(422, "taskId is required")
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = _resolve_project_db(tid)
        _ensure_graph_layout_table(pdb)
        row = pdb.fetchone(
            "SELECT layout_data FROM web_graph_layout "
            "WHERE project_id=? AND task_id=? AND comm_id=? AND edge_type=? AND gran=? AND depth=?",
            (pid, tid, cid, et, gran, depth)
        )
        if row:
            return {"found": True, "nodes": json.loads(row["layout_data"])}
        return {"found": False}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.delete("/api/graph-layout")
async def delete_graph_layout(task_id: str = Query(None), taskId: str = Query(None),
                               comm_id: str = Query(None), commId: str = Query(None),
                               edge_type: str = Query(None), edgeType: str = Query(None),
                               gran: str = Query("component"), depth: int = Query(1)):
    tid = task_id or taskId
    cid = comm_id or commId or ""
    et = edge_type or edgeType or ""
    if not tid:
        raise HTTPException(422, "taskId is required")
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        pid, pdb = _resolve_project_db(tid)
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


# ==================== Web AI 对话 ====================


def _require_chat_ready():
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    if not web_tool_executor:
        raise HTTPException(503, "Chat tools not initialized")


def _sdb():
    return multi_db.sessions_db


@app.get("/api/models")
async def list_models():
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        rows = multi_db.main_db.fetchall(
            "SELECT id, name, provider, model, is_default, type FROM model_configs ORDER BY is_default DESC, name"
        )
        result = []
        for r in rows:
            badge = "本地" if r["type"] == "local" else "API"
            result.append({
                "id": r["id"],
                "name": r["name"] or r["model"],
                "provider": r["provider"],
                "model": r["model"],
                "isDefault": bool(r["is_default"]),
                "badge": badge,
            })
        default_row = multi_db.main_db.fetchone(
            "SELECT value FROM app_config WHERE key='web_chat_default_model_id'"
        )
        default_model = default_row["value"] if default_row else None
        return {"models": result, "webChatDefaultModelId": default_model}
    except Exception as e:
        logger.error(f"list_models error: {e}")
        return {"models": [], "webChatDefaultModelId": None}


@app.get("/api/skills")
async def list_skills():
    registry = get_skill_registry()
    return {"skills": registry.to_frontend_list(), "defaults": registry.list_defaults()}


def _make_session_id():
    return f"chat_{uuid.uuid4().hex[:12]}"


def _create_chat_session(title: str, project_id: str = "") -> str:
    """创建新会话并插入 system 消息，返回 session_id。"""
    sid = _make_session_id()
    now = __import__("datetime").datetime.now().isoformat()
    metadata = json.dumps({"module": "web_chat", "model_id": ""}, ensure_ascii=False)
    _sdb().execute(
        "INSERT INTO llm_sessions (id, module_type, project_id, title, metadata, created_at, updated_at) "
        "VALUES (?, 'ai_assistant', ?, ?, ?, ?, ?)",
        (sid, project_id or None, title, metadata, now, now),
    )
    # 插入基础 system 消息
    sys_content = "你是 TopoCode 架构分析助手，帮助用户理解和分析项目代码架构。"
    _sdb().execute(
        "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
        "VALUES (?, ?, 'system', ?, '{}', ?)",
        (_make_message_id(), sid, sys_content, now),
    )
    return sid


def _make_message_id():
    return f"msg_{uuid.uuid4().hex[:12]}"


@app.post("/api/chat/sessions")
async def create_chat_session(request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        title = body.get("title", "新对话")
        project_id = body.get("projectId") or body.get("project_id", "")
        model_id = body.get("modelId") or body.get("model_id", "")
        active_skills = body.get("skills") or body.get("active_skills", [])
        refs = body.get("refs", [])

        if not model_id:
            default_row = multi_db.main_db.fetchone(
                "SELECT value FROM app_config WHERE key='web_chat_default_model_id'"
            )
            if default_row and default_row["value"]:
                model_id = default_row["value"]
            else:
                default_model = multi_db.main_db.fetchone(
                    "SELECT id FROM model_configs WHERE is_default = 1 AND status = 'connected'"
                )
                if default_model:
                    model_id = default_model["id"]

        registry = get_skill_registry()
        if not active_skills:
            active_skills = registry.list_defaults()

        sid = _make_session_id()
        metadata = json.dumps({
            "module": "web_chat",
            "model_id": model_id,
            "active_skills": active_skills,
            "refs": refs,
        }, ensure_ascii=False)
        now = __import__("datetime").datetime.now().isoformat()
        _sdb().execute(
            "INSERT INTO llm_sessions (id, module_type, project_id, title, metadata, created_at, updated_at) "
            "VALUES (?, 'ai_assistant', ?, ?, ?, ?, ?)",
            (sid, project_id or None, title, metadata, now, now),
        )

        system_parts = [
            "你是 TopoCode 架构分析助手，帮助用户理解和分析项目代码架构。",
            "你可以使用工具查询项目数据，回答用户关于架构、代码、设计的问题。",
            "可用命令: /overview (生成架构概览), /analyze_components (组件分析), "
            "/presummary (文件预摘要), /pipeline (完整流水线). 支持参数: "
            "--force (重新生成), -L zh/en (输出语言), "
            "-j N (并发数, 1-5, 默认1, 如 /pipeline -j 2). "
            "overview 命令不支持 -j 参数, 只有一个并发.",
            "注意：每次消息最多可以进行 50 次工具调用。请在此限制内规划分析路径。"
            "工具的调用必须使用可用工具列表中提供的精确名称，禁止猜测或编造工具名。"
            "如果无合适工具可用，直接告知用户无法处理，不要循环尝试不存在的工具。"
            "如果某个工具返回空结果或无有效数据，说明该路径不可行，请跳过并尝试其他方法。"
            "不要重复调用返回相同结果的工具。如果已获取足够信息，直接输出结论。"
            "如果多次尝试后仍无法获取需要的信息，直接告知用户当前的能力限制。",
        ]
        if refs:
            ref_context = resolve_refs_to_context(refs, multi_db)
            if ref_context:
                system_parts.append(ref_context)
        skill_context = registry.collect_context(active_skills)
        if skill_context:
            system_parts.append(skill_context)

        system_content = "\n\n".join(system_parts)
        if system_content.strip():
            _sdb().execute(
                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, 'system', ?, '{}', ?)",
                (_make_message_id(), sid, system_content, now),
            )

        return {
            "id": sid,
            "title": title,
            "projectId": project_id,
            "modelId": model_id,
            "activeSkills": active_skills,
            "createdAt": now,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/chat/sessions")
async def list_chat_sessions(project_id: str = Query(None), status: str = Query(None)):
    _require_chat_ready()
    try:
        wheres = ["json_extract(metadata, '$.module') = 'web_chat'"]
        params = []
        if project_id:
            wheres.append("project_id = ?")
            params.append(project_id)
        if status:
            wheres.append("status = ?")
            params.append(status)
        sql = (
            "SELECT id, project_id, title, status, metadata, created_at, updated_at "
            f"FROM llm_sessions WHERE {' AND '.join(wheres)} ORDER BY updated_at DESC"
        )
        rows = _sdb().fetchall(sql, tuple(params))
        result = []
        for r in rows:
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
            result.append({
                "id": r["id"],
                "projectId": r["project_id"],
                "title": r["title"],
                "status": r["status"],
                "modelId": meta.get("model_id", ""),
                "activeSkills": meta.get("active_skills", []),
                "messageCount": meta.get("message_count", 0),
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
            })
        return {"sessions": result, "total": len(result)}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/chat/sessions/{session_id}")
async def get_chat_session(session_id: str):
    _require_chat_ready()
    try:
        row = _sdb().fetchone(
            "SELECT id, project_id, title, status, metadata, created_at, updated_at "
            "FROM llm_sessions WHERE id = ?",
            (session_id,),
        )
        if not row:
            raise HTTPException(404, "Session not found")
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        messages = _sdb().fetchall(
            "SELECT id, role, content, metadata, created_at FROM llm_messages "
            "WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        )
        return {
            "id": row["id"],
            "projectId": row["project_id"],
            "title": row["title"],
            "status": row["status"],
            "modelId": meta.get("model_id", ""),
            "activeSkills": meta.get("active_skills", []),
            "refs": meta.get("refs", []),
            "messages": [
                {
                    "id": m["id"],
                    "role": m["role"],
                    "content": m["content"],
                    "refs": json.loads(m["metadata"]).get("refs", []) if m["metadata"] else [],
                    "reasoning": json.loads(m["metadata"]).get("reasoning", "") if m["metadata"] else "",
                    "toolCalls": json.loads(m["metadata"]).get("tool_calls", []) if m["metadata"] else [],
                    "createdAt": m["created_at"],
                }
                for m in messages
            ],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.put("/api/chat/sessions/{session_id}")
async def update_chat_session(session_id: str, request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        row = _sdb().fetchone(
            "SELECT metadata FROM llm_sessions WHERE id = ?", (session_id,)
        )
        if not row:
            raise HTTPException(404, "Session not found")
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        updates = []

        if "title" in body:
            updates.append(("title", body["title"]))
        if "status" in body:
            updates.append(("status", body["status"]))
        if "modelId" in body or "model_id" in body:
            mid = body.get("modelId") or body.get("model_id", "")
            meta["model_id"] = mid
        if "skills" in body:
            meta["active_skills"] = body["skills"]
        if "refs" in body:
            meta["refs"] = body["refs"]

        now = __import__("datetime").datetime.now().isoformat()
        updates.append(("metadata", json.dumps(meta, ensure_ascii=False)))
        updates.append(("updated_at", now))

        set_clause = ", ".join(f"{k} = ?" for k, _ in updates)
        vals = [v for _, v in updates] + [session_id]
        _sdb().execute(
            f"UPDATE llm_sessions SET {set_clause} WHERE id = ?", tuple(vals)
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/chat/sessions/{session_id}/auto-title")
async def auto_title_session(session_id: str):
    """手动触发 AI 生成会话标题，返回生成的标题"""
    _require_chat_ready()
    try:
        row = _sdb().fetchone(
            "SELECT title FROM llm_sessions WHERE id = ?", (session_id,)
        )
        if not row:
            raise HTTPException(404, "Session not found")
        msgs = _sdb().fetchall(
            "SELECT role, content FROM llm_messages WHERE session_id = ? AND role IN ('user', 'assistant') ORDER BY created_at",
            (session_id,),
        )
        if len(msgs) < 2:
            return {"title": row["title"] or "新对话", "generated": False}
        context = "\n".join([f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:500]}" for m in msgs[-4:]])
        _do_auto_title(session_id, context)
        updated = _sdb().fetchone(
            "SELECT title FROM llm_sessions WHERE id = ?", (session_id,)
        )
        new_title = updated["title"] if updated else (row["title"] or "新对话")
        return {"title": new_title, "generated": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    _require_chat_ready()
    try:
        _sdb().execute("DELETE FROM llm_sessions WHERE id = ?", (session_id,))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/chat/sessions/{session_id}/stream/abort")
async def abort_chat_stream(session_id: str):
    """中止正在进行的 LLM 流"""
    _require_chat_ready()
    with _active_streams_lock:
        resp = _active_streams.pop(session_id, None)
    if resp:
        resp.close()
        logger.info(f"[abort] closed HTTP connection for session {session_id[:16]}")
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# 统一上下文管理
# ═══════════════════════════════════════════════════════════════

import re as _re

class ReferenceParser:
    """解析 @type:id 引用、隐式 ID、便签 refs"""

    ID_PATTERNS = [
        (r'\b(comm-\w+)\b', 'community'),
        (r'\b(proj-\w+)\b', 'project'),
        (r'\b(task-\w+)\b', 'task'),
        (r'\b(chat_\w+)\b', 'session'),
        (r'\b(arch_\w+)\b', 'archive'),
    ]

    @staticmethod
    def parse(user_content: str, body_refs: list = None) -> list:
        parsed = []
        for match in _re.finditer(r'@(\w+):([^\s,;，。！？\n]+)', user_content):
            parsed.append({"type": match.group(1), "id": match.group(2), "source": "explicit"})
        for pattern, ref_type in ReferenceParser.ID_PATTERNS:
            for match in _re.finditer(pattern, user_content):
                id_val = match.group(1)
                if not any(r.get("type") == ref_type and r.get("id") == id_val for r in parsed):
                    parsed.append({"type": ref_type, "id": id_val, "source": "implicit"})
        if body_refs:
            for br in body_refs:
                pr = ReferenceParser._infer_ref_type(br)
                if pr:
                    key = (pr["type"], pr["id"])
                    if not any((r.get("type"), r.get("id")) == key for r in parsed):
                        parsed.append({**pr, "source": "refs"})
        return parsed

    @staticmethod
    def _infer_ref_type(ref: dict) -> dict | None:
        if ref.get("type"):
            return {"type": ref["type"], "id": ref.get("id", "")}
        if ref.get("componentId"):
            return {"type": "community", "id": ref["componentId"]}
        if ref.get("projectId"):
            return {"type": "project", "id": ref["projectId"]}
        if ref.get("taskId"):
            return {"type": "task", "id": ref["taskId"]}
        return None


class TokenBudget:
    """上下文 Token 预算管理"""

    CHARS_PER_TOKEN = 2

    @classmethod
    def estimate(cls, text: str) -> int:
        return max(1, len(text) // cls.CHARS_PER_TOKEN)

    @classmethod
    def estimate_msgs(cls, messages: list[dict]) -> int:
        return sum(cls.estimate(m.get("content", "")) for m in messages)

    @classmethod
    def trim(cls, messages: list[dict], max_context: int = 16000, reserve: int = 4000) -> list[dict]:
        """在预算内保留高优先级消息"""
        budget = max_context - reserve
        if budget <= 0:
            return messages[-8:] if len(messages) > 8 else messages
        system_msgs = [m for m in messages if m["role"] == "system"]
        dialog_msgs = [m for m in messages if m["role"] != "system"]
        base_tokens = cls.estimate_msgs(system_msgs)
        if base_tokens > budget:
            return system_msgs
        remaining = budget - base_tokens
        keep = []
        for m in reversed(dialog_msgs):
            if remaining <= 0:
                break
            tok = cls.estimate(m.get("content", ""))
            if tok <= remaining:
                keep.insert(0, m)
                remaining -= tok
        return system_msgs + keep


class ContextAssembler:
    """构建三层上下文"""

    def __init__(self, session_id: str, sdb):
        self.session_id = session_id
        self.sdb = sdb

    def build(self, db_messages: list[dict], parsed_refs: list = None,
              context_limit: int = 32000) -> list[dict]:
        l1 = self._build_l1(parsed_refs)
        merged = self._merge(db_messages, l1)
        return TokenBudget.trim(merged, context_limit)

    def _build_l1(self, parsed_refs: list = None) -> list[dict]:
        msgs = []
        if parsed_refs:
            context = resolve_refs_to_context(parsed_refs, multi_db)
            if context:
                msgs.append({"role": "system", "content": context})
        session = self.sdb.fetchone(
            "SELECT metadata FROM llm_sessions WHERE id = ?", (self.session_id,)
        )
        if session:
            meta = json.loads(session["metadata"]) if session["metadata"] else {}
            summary = meta.get("compressed_summary", "")
            if summary:
                msgs.append({"role": "system", "content":
                    f"以下是对本对话早期内容的结构化摘要：\n{summary}"})
        return msgs

    def _merge(self, db_msgs: list[dict], l1_msgs: list[dict]) -> list[dict]:
        if not l1_msgs:
            return db_msgs
        system_msgs = [m for m in db_msgs if m["role"] == "system"]
        dialog_msgs = [m for m in db_msgs if m["role"] != "system"]
        return system_msgs + l1_msgs + dialog_msgs


class SessionCompressor:
    """处理 /compress 指令"""

    PROMPT_TEMPLATE = """请将以下对话压缩为结构化摘要：

要求：
1. 提取关键信息：涉及的项目/社区/文件/符号，核心结论和分析结果
2. 格式：
## 主题
[一句话概括]
## 关键内容
- 要点1
- 要点2
## 涉及的资源
- 社区: @community:xxx
- 文件: @file:path/to/file

3. 控制在 300 字以内，保留引用标记

== 对话内容 ==
{text}"""

    def __init__(self, sdb, llm_service=None):
        self.sdb = sdb
        self.service = llm_service

    @classmethod
    def parse_args(cls, content: str) -> dict:
        args = {"target_ids": [], "save": False, "category": ""}
        m = _re.search(r'--session\s+(\S+)', content)
        if m:
            args["target_ids"] = [x.strip() for x in m.group(1).split(",")]
        if "--save" in content:
            args["save"] = True
        m = _re.search(r'--category\s+(\S+)', content)
        if m:
            args["category"] = m.group(1).strip()
        return args

    def _load_messages(self, session_ids: list[str]) -> str:
        parts = []
        for sid in session_ids:
            rows = self.sdb.fetchall(
                "SELECT role, content FROM llm_messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') "
                "ORDER BY created_at LIMIT 100",
                (sid,),
            )
            if rows:
                parts.append(f"--- 会话 {sid} ---")
                for r in rows:
                    role_label = "用户" if r["role"] == "user" else "AI"
                    content = (r["content"] or "")[:2000]
                    parts.append(f"[{role_label}] {content}")
        return "\n\n".join(parts) if parts else "（无对话内容）"

    def _save_summary(self, summary_text: str, current_id: str,
                      target_ids: list[str], to_archive: bool, category: str = ""):
        meta_key = "compressed_summary"
        session = self.sdb.fetchone(
            "SELECT metadata FROM llm_sessions WHERE id = ?", (current_id,)
        )
        if session:
            meta = json.loads(session["metadata"]) if session["metadata"] else {}
            meta[meta_key] = summary_text
            now = __import__("datetime").datetime.now().isoformat()
            self.sdb.execute(
                "UPDATE llm_sessions SET metadata = ?, updated_at = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), now, current_id),
            )
        if to_archive:
            archive_id = f"arch_{_make_message_id()}"
            project_row = self.sdb.fetchone(
                "SELECT project_id FROM llm_sessions WHERE id = ?",
                (target_ids[0] if target_ids else current_id,),
            )
            pid = project_row["project_id"] if project_row else ""
            self.sdb.execute(
                "INSERT INTO chat_archives (id, session_id, project_id, title, content, "
                "category, tags, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (archive_id, target_ids[0] if target_ids else current_id,
                 pid, "会话摘要", summary_text,
                 category or "compress", ",".join(target_ids or [current_id]),
                 "auto_compress", __import__("datetime").datetime.now().isoformat()),
            )

    async def execute(self, content: str, current_session_id: str) -> str:
        args = self.parse_args(content)
        target_ids = args["target_ids"] or [current_session_id]
        conversation_text = self._load_messages(target_ids)
        summary = await self._llm_compress(conversation_text)
        self._save_summary(summary, current_session_id, target_ids, args["save"], args["category"])
        return summary

    async def _llm_compress(self, text: str) -> str:
        try:
            import aiohttp
            model_id = _resolve_default_model_id()
            configs = _sdb().fetchall("SELECT model_id, api_base, api_key, model_name FROM model_configs")
            cfg = next((c for c in configs if c["model_id"] == model_id), None)
            if not cfg:
                cfg = configs[0] if configs else None
            if not cfg:
                return "（无可用模型）"
            base_url = (cfg["api_base"] or "").rstrip("/")
            api_key = cfg.get("api_key") or "sk-no-key"
            model_name = cfg.get("model_name") or model_id
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": self.PROMPT_TEMPLATE.format(text=text[:40000])}],
                "stream": False,
                "max_tokens": 1000,
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            async with aiohttp.ClientSession() as sess:
                async with sess.post(f"{base_url}/v1/chat/completions",
                                     json=payload, headers=headers, timeout=30) as resp:
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "")[:2000]
        except Exception as e:
            logger.info(f"[compress] LLM call failed: {e}")
        return "（压缩失败）"



@app.post("/api/chat/sessions/{session_id}/messages")
async def send_chat_message(session_id: str, request: Request):
    """发消息 + SSE 流式回复（核心端点）"""
    _require_chat_ready()
    try:
        body = await request.json()
        content = body.get("content", "")
        refs = body.get("refs", [])
        model_id = body.get("modelId") or body.get("model_id", "")
        streaming = body.get("stream", True)
        context_limit = body.get("contextLimit", 0)  # 0 = use model default

        # ── Phase 0: 指令检测 ──
        if content.startswith("/compress"):
            compressor = SessionCompressor(_sdb())
            summary = await compressor.execute(content, session_id)
            # 返回 SSE 流
            async def _compress_stream():
                yield f"data: {json.dumps({'type': 'chunk', 'text': summary[:100]})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'content': summary})}\n\n"
            return StreamingResponse(_compress_stream(), media_type="text/event-stream")

        # ── Phase 1: 引用解析 ──
        parsed_refs = ReferenceParser.parse(content, refs)
        logger.info(f"[context] parsed {len(parsed_refs)} refs: {parsed_refs[:3]}")

        session = _sdb().fetchone(
            "SELECT id, project_id, metadata FROM llm_sessions WHERE id = ?", (session_id,)
        )
        if not session:
            raise HTTPException(404, "Session not found")

        meta = json.loads(session["metadata"]) if session["metadata"] else {}
        if not model_id:
            model_id = meta.get("model_id", "")
        if not context_limit:
            context_limit = meta.get("context_limit", 32000)
        active_skills = meta.get("active_skills", [])

        now = __import__("datetime").datetime.now().isoformat()

        # 引用上下文持久化到 DB（插在 user 消息之前）
        if refs:
            ref_context = resolve_refs_to_context(refs, multi_db)
            if ref_context:
                _sdb().execute(
                    "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                    "VALUES (?, ?, 'system', ?, '{}', ?)",
                    (_make_message_id(), session_id, ref_context, now),
                )
            # 注入当前会话上下文（refs 中的项目/任务/组件信息）
            first = refs[0]
            ctx_parts = []
            if first.get("projectName") or first.get("projectId"):
                name = first.get("projectName", "")
                pid = first.get("projectId", "")
                ctx_parts.append(f"项目：{name}" + (f"（ID: {pid}）" if pid else ""))
            else:
                ctx_parts.append(f"项目ID：{session.get('project_id', '')}")
            if first.get("taskId"):
                ctx_parts.append(f"任务ID：{first['taskId']}")
            if first.get("componentId"):
                ctx_parts.append(f"组件ID：{first['componentId']}")
            ctx_parts.append(f"会话ID：{session_id}")
            ctx_parts.append("每轮消息最多 50 次工具调用。工具名必须使用可用工具列表中提供的精确名称，禁止猜测或编造工具名。如果无合适工具可用，直接告知用户无法处理，不要循环尝试不存在的工具。")
            ctx_msg = "；".join(ctx_parts)
            _sdb().execute(
                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, 'system', ?, '{}', ?)",
                (_make_message_id(), session_id, ctx_msg, now),
            )

        # 无 refs 时也注入会话上下文（sessionId 用于标题工具）
        if not refs:
            _sdb().execute(
                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, 'system', ?, '{}', ?)",
                (_make_message_id(), session_id, f"会话ID：{session_id}；每轮消息最多 50 次工具调用。工具名必须使用可用工具列表中提供的精确名称，禁止猜测或编造工具名。如果无合适工具可用，直接告知用户无法处理，不要循环尝试不存在的工具。", now),
            )

        msg_meta = json.dumps({"refs": refs} if refs else {})
        _sdb().execute(
            "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, 'user', ?, ?, ?)",
            (_make_message_id(), session_id, content, msg_meta, now),
        )

        count_row = _sdb().fetchone(
            "SELECT count(*) AS cnt FROM llm_messages WHERE session_id = ? AND role IN ('user', 'assistant')",
            (session_id,),
        )
        count = count_row["cnt"] if count_row else 0
        meta["message_count"] = count // 2
        _sdb().execute(
            "UPDATE llm_sessions SET metadata = ?, updated_at = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), now, session_id),
        )

        if not streaming:
            return {"ok": True, "messageId": _make_message_id()}

        # ── SSE 流式 ──
        from llm_service import LLMService
        registry = get_skill_registry()
        tool_names = registry.collect_tool_names(active_skills)
        has_tools = len(tool_names) > 0

        msgs = _sdb().fetchall(
            "SELECT role, content FROM llm_messages WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        )
        context_messages = [{"role": m["role"], "content": m["content"]} for m in msgs]

        # ── Phase 2: 上下文优化（注入 L1 + TokenBudget） ──
        assembler = ContextAssembler(session_id, _sdb())
        context_messages = assembler.build(context_messages, parsed_refs, context_limit)
        logger.info(f"[context] after assembly: {len(context_messages)} msgs, "
                    f"~{TokenBudget.estimate_msgs(context_messages)} tokens")

        # ── 工具名注入上下文（LLM 在 reasoning 阶段可见，避免猜测工具名） ──
        if has_tools:
            tool_descriptions = registry.collect_tool_descriptions(active_skills)
            if tool_descriptions:
                context_messages.append({
                    "role": "system",
                    "content": "可用工具列表：\n" + tool_descriptions
                })

        # ── 多轮工具调用 ──
        from web_tools import get_web_tool_definitions
        tool_defs = get_web_tool_definitions(tool_names) if has_tools else None
        import queue as _queue
        import threading

        def _llm_round(messages, tools, chunk_q, force_tool_choice=False):
            """单次 LLM 调用（在独立线程中运行）。统一走 direct HTTP。"""
            _log = logger.info
            try:
                model_cfg = multi_db.main_db.fetchone(
                    "SELECT * FROM model_configs WHERE id = ?", (model_id,)
                )
                if not model_cfg:
                    _log(f"[LLM-round] model not found: {model_id}")
                    chunk_q.put({"type": "error", "message": f"Model not found: {model_id}"})
                    chunk_q.put({"type": "done"})
                    return
                md = dict(model_cfg)
                has_t = bool(tools)
                _log(f"[LLM-round] model={md.get('model','')} provider={md.get('provider','')} has_tools={has_t} force_choice={force_tool_choice} msg_count={len(messages)}")

                import requests as _req
                base_url = md.get('url', '').rstrip('/')
                if base_url.endswith('/v1'):
                    base_url = base_url[:-3]
                payload = {
                    'model': md.get('model', ''),
                    'messages': messages,
                    'stream': True,
                }
                if tools:
                    payload['tools'] = tools
                    if force_tool_choice:
                        payload['tool_choice'] = 'auto'
                if md.get('temperature') is not None:
                    payload['temperature'] = md['temperature']
                if md.get('frequency_penalty') is not None:
                    payload['frequency_penalty'] = md['frequency_penalty']
                if md.get('presence_penalty') is not None:
                    payload['presence_penalty'] = md['presence_penalty']
                payload['max_tokens'] = md.get('max_tokens', 16384)
                headers = {'Content-Type': 'application/json'}
                api_key = md.get('api_key', '')
                if api_key:
                    headers['Authorization'] = f'Bearer {api_key}'
                timeout = md.get('timeout', 300)
                _log(f"[CHAT_TRACE] _llm_round payload: model={payload['model']} max_tokens={payload.get('max_tokens')} tools={bool(tools)} force_choice={force_tool_choice}")
                _log(f"[LLM-round] POST {base_url}/v1/chat/completions  timeout={timeout}s")
                resp = _req.post(
                    f'{base_url}/v1/chat/completions',
                    json=payload, headers=headers, stream=True, timeout=timeout,
                )
                _log(f"[LLM-round] HTTP status={resp.status_code}")
                if resp.status_code != 200:
                    err_body = resp.text[:300]
                    _log(f"[LLM-round] HTTP error: {err_body}")
                    chunk_q.put({'type': 'error', 'message': f'API error {resp.status_code}: {err_body}'})
                    chunk_q.put({'type': 'done'})
                    return
                with _active_streams_lock:
                    _active_streams[session_id] = resp
                line_count = 0
                reasoning_only_count = 0
                MAX_REASONING_LINES = 3000
                _chunk_total = 0
                _reasoning_total = 0
                _usage_data = {}
                try:
                    for line_bytes in resp.iter_lines():
                        if not line_bytes:
                            continue
                        line = line_bytes.decode('utf-8')
                        if not line.startswith('data: '):
                            continue
                        data_str = line[6:].strip()
                        if data_str == '[DONE]':
                            _log(f"[LLM-round] [DONE] after {line_count} lines usage={_usage_data}")
                            break
                        line_count += 1
                        try:
                            data = json.loads(data_str)
                            if data.get('usage'):
                                _usage_data = data['usage']
                            delta = data.get('choices', [{}])[0].get('delta', {})
                            chunk = delta.get('content', '')
                            reasoning = delta.get('reasoning_content', '')
                            if reasoning and line_count == 1:
                                _log(f"[LLM-round] first reasoning token: {reasoning[:60]}...")
                            if chunk and line_count == 1:
                                _log(f"[LLM-round] first content token: {chunk[:60]}...")
                            if reasoning and not chunk:
                                reasoning_only_count += 1
                                if reasoning_only_count > MAX_REASONING_LINES:
                                    _log(f"[LLM-round] reasoning-only lines exceed {MAX_REASONING_LINES}, force break")
                                    break
                            else:
                                reasoning_only_count = 0
                            if reasoning:
                                _reasoning_total += len(reasoning)
                                chunk_q.put({"type": "reasoning", "text": reasoning})
                            if chunk:
                                _chunk_total += len(chunk)
                                chunk_q.put(chunk)
                            tc = delta.get('tool_calls')
                            if tc:
                                _log(f"[LLM-round] tool_calls in delta: {json.dumps(tc)[:200]}")
                                chunk_q.put({'type': 'tool_calls', 'data': json.dumps(tc)})
                        except Exception as e:
                            _log(f"[LLM-round] parse error at line {line_count}: {e} | data={data_str[:100]}")
                            pass
                    _log(f"[LLM-round] complete ({line_count} data lines)")
                    _log(f"[CHAT_TRACE] _llm_round stats: lines={line_count} "
                         f"chunk_total={_chunk_total} reasoning_total={_reasoning_total} "
                         f"usage={_usage_data}")
                except Exception as e:
                    _log(f"[LLM-round] exception: {e}")
                    with _active_streams_lock:
                        _is_aborted = session_id not in _active_streams
                    if _is_aborted:
                        chunk_q.put({"type": "aborted"})
                    else:
                        import traceback
                        _log(traceback.format_exc())
                        chunk_q.put({"type": "error", "message": str(e)})
                finally:
                    with _active_streams_lock:
                        _active_streams.pop(session_id, None)
                    chunk_q.put({'type': 'done'})
            except Exception as e:
                _log(f"[LLM-round] outer exception: {e}")
                import traceback
                _log(traceback.format_exc())
                chunk_q.put({"type": "error", "message": str(e)})
                chunk_q.put({"type": "done"})

        async def event_stream():
            queue: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_event_loop()
            executor = web_tool_executor
            executor._current_session_id = session_id
            _log = logger.info

            TOOL_ROUND_LIMIT = 50

            async def _producer():
                ctx_msgs = list(context_messages)
                _acc_reasoning = ""  # 跨轮累积 reasoning，供 fallback 使用
                _acc_tool_calls = 0  # 跨轮累积 tool 调用次数，供质量判定使用
                for round_idx in range(TOOL_ROUND_LIMIT):
                    force_choice = round_idx == 0 and bool(tool_defs)
                    chunk_q = _queue.Queue()
                    full_content = ""
                    full_reasoning = ""
                    tc_raw = []

                    _log(f"[producer] === ROUND {round_idx} start === tools={bool(tool_defs)} force_choice={force_choice} ctx_msgs={len(ctx_msgs)}")
                    t = threading.Thread(target=_llm_round, args=(ctx_msgs, tool_defs, chunk_q, force_choice), daemon=True)
                    t.start()

                    drain_count = 0
                    # tool_calls 按 index 合并增量（OpenAI 流式格式）
                    tc_by_idx = {}
                    while True:
                        try:
                            item = await loop.run_in_executor(None, chunk_q.get, True, 0.15)
                        except _queue.Empty:
                            continue
                        drain_count += 1
                        if isinstance(item, dict):
                            if item.get("type") == "done":
                                _log(f"[producer] round {round_idx} drain done: {drain_count} items, full_content_len={len(full_content)}, tc_indexes={list(tc_by_idx.keys())}")
                                break
                            if item.get("type") == "error":
                                _log(f"[producer] round {round_idx} error: {item.get('message','')}")
                                await queue.put({"type": "error", "message": item.get("message", "")})
                                await queue.put({"type": "done"})
                                return
                            if item.get("type") == "aborted":
                                _log(f"[producer] round {round_idx} aborted by user")
                                await queue.put({"type": "done", "content": ""})
                                return
                            if item.get("type") == "tool_calls":
                                tc_delta_list = json.loads(item.get("data", "[]"))
                                for td in tc_delta_list:
                                    idx = td.get("index", 0)
                                    acc = tc_by_idx.setdefault(idx, {})
                                    if "id" in td:
                                        acc["id"] = td["id"]
                                    if "type" in td:
                                        acc["type"] = td["type"]
                                    fn = td.get("function", {})
                                    if fn:
                                        acc.setdefault("function", {})
                                        if "name" in fn:
                                            acc["function"]["name"] = fn["name"]
                                        if "arguments" in fn:
                                            acc["function"]["arguments"] = acc["function"].get("arguments", "") + fn["arguments"]
                            if item.get("type") == "reasoning":
                                full_reasoning += item.get("text", "")
                                await queue.put({"type": "reasoning", "text": item.get("text", "")})
                            if item.get("type") == "chunk" and not force_choice:
                                await queue.put({"type": "chunk", "text": item.get("text", "")})
                        elif isinstance(item, str):
                            full_content += item
                            if not force_choice:
                                await queue.put({"type": "chunk", "text": item})

                    t.join(timeout=5)
                    # 跨轮累积 reasoning（最终无 content 时 fallback 使用）
                    _acc_reasoning += full_reasoning
                    parsed = []
                    for v in tc_by_idx.values():
                        try:
                            args = json.loads(v.get("function", {}).get("arguments", "{}"))
                        except Exception:
                            args = {}
                        parsed.append({"id": v.get("id", ""), "name": v.get("function", {}).get("name", ""), "arguments": args})
                    _acc_tool_calls += len(parsed)
                    _log(f"[producer] round {round_idx} parsed: {len(parsed)} tool calls, full_content_len={len(full_content)}")

                    if not parsed:
                        _log(f"[producer] round {round_idx} no tool calls → finalize")
                        final_content = full_content.strip()
                        _reasoning_len = len(full_reasoning.strip())
                        _acc_reasoning_str = _acc_reasoning.strip()
                        # 质量判定：跑了多轮工具但模型未产出实质内容
                        quality = "ok"
                        if not final_content and _acc_reasoning_str:
                            # 没写 content，但有推理内容 → 够完整则当作 content
                            if len(_acc_reasoning_str) >= 500:
                                final_content = _acc_reasoning_str
                            elif _acc_tool_calls >= 2:
                                quality = "low"
                        elif not final_content and not _acc_reasoning_str and _acc_tool_calls >= 2:
                            quality = "low"
                        if quality == "low":
                            _log(f"[CHAT_TRACE] QUALITY_LOW: calls={_acc_tool_calls} "
                                 f"content_len={len(final_content)} acc_reasoning_len={len(_acc_reasoning_str)}")
                        _log(f"[CHAT_TRACE] FINALIZE round={round_idx} content_len={len(final_content)} "
                             f"reasoning_len={_reasoning_len} acc_reasoning_len={len(_acc_reasoning_str)} "
                             f"acc_calls={_acc_tool_calls} quality={quality} "
                             f"msgs_in_ctx={len(ctx_msgs)} tool_defs={bool(tool_defs)}")
                        if final_content:
                            _meta = {}
                            if _reasoning_len:
                                _meta["reasoning"] = full_reasoning.strip()
                            _sdb().execute(
                                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                                "VALUES (?, ?, 'assistant', ?, ?, ?)",
                                (_make_message_id(), session_id, final_content, json.dumps(_meta), now),
                            )
                        if round_idx == 0 and tool_defs and final_content:
                            _log(f"[producer] emit suppressed first-round chunks: {len(final_content)} chars")
                            await queue.put({"type": "chunk", "text": final_content})
                        await queue.put({
                            "type": "done",
                            "content": final_content if quality == "ok" else "",
                            "quality": quality,
                            "reasoning": _acc_reasoning_str if quality == "low" else "",
                        })
                        _log(f"[producer] done: content_len={len(final_content)} quality={quality}")
                        return

                    _log(f"[producer] executing {len(parsed)} tool(s): {[p.get('name','') for p in parsed]}")
                    tool_msgs = []
                    for tc_item in parsed:
                        t_name = tc_item.get("name", "")
                        t_args = tc_item.get("arguments", {})
                        tc_id = tc_item.get("id", "")
                        _log(f"[producer] tool_call: {t_name} id={tc_id} args={json.dumps(t_args)[:200]}")
                        await queue.put({"type": "tool_call", "name": t_name, "arguments": t_args})
                        try:
                            result = executor.execute(t_name, t_args)
                            _log(f"[producer] tool_result: {t_name} ok")
                        except Exception as e:
                            result = {"error": str(e)}
                            _log(f"[producer] tool_result: {t_name} error: {e}")
                        await queue.put({"type": "tool_result", "name": t_name, "result": result})

                        result_str = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
                        _sdb().execute(
                            "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                            "VALUES (?, ?, 'tool', ?, ?, ?)",
                            (_make_message_id(), session_id, result_str, json.dumps({"tool_call_id": tc_id}), now),
                        )
                        tool_msgs.append({"role": "tool", "content": result_str, "tool_call_id": tc_id})

                    asst_tc_payload = [{
                        "id": p.get("id", ""),
                        "type": "function",
                        "function": {"name": p.get("name",""), "arguments": json.dumps(p.get("arguments",{}), ensure_ascii=False)}
                    } for p in parsed]
                    _log(f"[producer] ctx_msgs extended: +1 assistant(tool_calls) + {len(tool_msgs)} tool(s)")
                    ctx_msgs.append({"role": "assistant", "content": full_content.strip() or "", "tool_calls": asst_tc_payload})
                    ctx_msgs.extend(tool_msgs)
                    # 也保存到 DB
                    asst_id = _make_message_id()
                    tc_meta_dict = {"tool_calls": [{"name": p.get("name",""), "arguments": p.get("arguments",{})} for p in parsed]}
                    if full_reasoning.strip():
                        tc_meta_dict["reasoning"] = full_reasoning.strip()
                    tc_meta = json.dumps(tc_meta_dict, ensure_ascii=False)
                    _sdb().execute(
                        "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                        "VALUES (?, ?, 'assistant', ?, ?, ?)",
                        (asst_id, session_id, full_content.strip() or "", tc_meta, now),
                    )

                _log(f"[producer] max rounds reached without final response")
                await queue.put({"type": "error", "message": "工具调用次数过多，请简化问题"})
                await queue.put({"type": "done"})

            asyncio.create_task(_producer())
            _log(f"[event_stream] producer task started, waiting for events...")
            event_count = 0
            try:
                while True:
                    event = await queue.get()
                    event_count += 1
                    if event["type"] in ("chunk", "reasoning") and event_count > 5 and event_count % 500 != 0:
                        pass
                    else:
                        _log(f"[event_stream] -> SSE event #{event_count}: type={event.get('type')} keys={list(event.keys())}")
                    if event["type"] == "done":
                        content_len = len(event.get("content", "") or "")
                        yield f"event: done\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        _log(f"[event_stream] done, total {event_count} events")
                        _log(f"[CHAT_TRACE] event_stream_done: events={event_count} content_len={content_len} session={session_id}")
                        break
                    elif event["type"] == "error":
                        yield f"event: error\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        _log(f"[event_stream] error, abort")
                        _log(f"[CHAT_TRACE] event_stream_error: session={session_id} msg={event.get('message','')}")
                        break
                    elif event["type"] == "chunk":
                        yield f"event: chunk\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    elif event["type"] == "reasoning":
                        yield f"event: reasoning\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    elif event["type"] == "tool_call":
                        yield f"event: tool_call\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    elif event["type"] == "tool_result":
                        yield f"event: tool_result\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                pass

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Chat error: {e}")


def _check_auto_title(session_id: str):
    """检查会话是否已有标题，若无则自动生成"""
    try:
        row = _sdb().fetchone(
            "SELECT title FROM llm_sessions WHERE id = ?", (session_id,)
        )
        if not row:
            logger.info(f"[auto-title] _check: session {session_id[:16]} not found")
            return
        title = row["title"] or ""
        logger.info(f"[auto-title] _check: session {session_id[:16]} title='{title[:30]}'")
        # 默认标题（新建会话、便签分析）→ 需要自动生成
        if title and not title.startswith("新对话") and not title.startswith("便签分析"):
            logger.info(f"[auto-title] _check: title already set, skip")
            return
        msgs = _sdb().fetchall(
            "SELECT role, content FROM llm_messages WHERE session_id = ? AND role IN ('user', 'assistant') ORDER BY created_at",
            (session_id,),
        )
        if len(msgs) < 2:
            logger.info(f"[auto-title] _check: only {len(msgs)} messages, need 2, skip")
            return
        logger.info(f"[auto-title] _check: calling _do_auto_title with {len(msgs)} messages")
        context = "\n".join([f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:500]}" for m in msgs[-4:]])
        _do_auto_title(session_id, context)
    except Exception as e:
        logger.warning(f"[auto-title] _check_auto_title error: {e}")


def _do_auto_title(session_id: str, context: str):
    """在后台线程中调用 LLM 生成标题"""
    try:
        model_id = ""
        default_row = multi_db.main_db.fetchone(
            "SELECT value FROM app_config WHERE key='web_chat_default_model_id'"
        )
        if default_row and default_row["value"]:
            model_id = default_row["value"]
        if not model_id:
            # 回退：找 is_default 模型
            default_model = multi_db.main_db.fetchone(
                "SELECT id FROM model_configs WHERE is_default = 1 AND status = 'connected' LIMIT 1"
            )
            if default_model:
                model_id = default_model["id"]
        if not model_id:
            logger.warning(f"[auto-title] _do: no default model found for session {session_id[:16]}")
            return
        logger.info(f"[auto-title] _do: using model_id={model_id[:16]}, context_len={len(context)}")
        model_cfg = multi_db.main_db.fetchone(
            "SELECT * FROM model_configs WHERE id = ?", (model_id,)
        )
        if not model_cfg:
            logger.warning(f"[auto-title] _do: model {model_id[:16]} not found in configs")
            return
        md = dict(model_cfg)
        base_url = md.get("url", "").rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        import requests as _req
        payload = {
            "model": md.get("model", ""),
            "messages": [
                {"role": "system", "content": "为对话生成一个简短标题（不要多于15个字）。列出3个候选，直接选一个输出。"},
                {"role": "user", "content": f"对话内容：{context}"},
            ],
            "stream": False,
            "max_tokens": md.get('max_tokens', 16384),
            "temperature": 0.1,
        }
        if md.get('frequency_penalty') is not None:
            payload['frequency_penalty'] = md['frequency_penalty']
        if md.get('presence_penalty') is not None:
            payload['presence_penalty'] = md['presence_penalty']
        _headers = {"Content-Type": "application/json"}
        api_key = md.get("api_key", "")
        if api_key:
            _headers["Authorization"] = f"Bearer {api_key}"
        logger.info(f"[auto-title] _do: POST {base_url}/v1/chat/completions")
        resp = _req.post(
            f"{base_url}/v1/chat/completions",
            json=payload, headers=_headers, timeout=30,
        )
        if resp.status_code != 200:
            logger.warning(f"[auto-title] _do: LLM returned status {resp.status_code}, body={resp.text[:200]}")
            return
        data = resp.json()
        choices = data.get("choices", [])
        raw = ""
        if choices:
            msg = choices[0].get("message", {})
            raw = (msg.get("content", "") or msg.get("reasoning_content", "") or "").strip()
        # 推理模型可能在 content 中输出大量思考过程，从中提取标题
        title = _extract_title_from_llm_output(raw)
        if title and 2 <= len(title) <= 16:
            from datetime import datetime as _dt
            now = _dt.now().isoformat()
            _sdb().execute(
                "UPDATE llm_sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, session_id),
            )
            logger.info(f"[auto-title] set title '{title}' for session {session_id[:16]}")
        else:
            # 回退：用用户首条消息截断为标题
            fallback = _fallback_title(session_id, raw[:80])
            if fallback:
                from datetime import datetime as _dt
                now = _dt.now().isoformat()
                _sdb().execute(
                    "UPDATE llm_sessions SET title = ?, updated_at = ? WHERE id = ?",
                    (fallback, now, session_id),
                )
                logger.info(f"[auto-title] fallback title '{fallback}' for session {session_id[:16]}")
            else:
                logger.warning(f"[auto-title] _do: no valid title, raw='{raw[:80]}'")
    except Exception as e:
        logger.warning(f"[auto-title] _do_auto_title error: {e}")


def _extract_title_from_llm_output(raw: str) -> str:
    """从 LLM 输出中提取标题"""
    if not raw:
        return ""
    lines = [l.strip().strip('"').strip("'").strip() for l in raw.split('\n') if l.strip()]
    for l in reversed(lines):
        if 2 <= len(l) <= 20 and not l.startswith('-') and not l.startswith('*') and not l.startswith('#'):
            return l
    if lines:
        last = lines[-1]
        if 2 <= len(last) <= 30:
            return last
    return ""


def _fallback_title(session_id: str, llm_hint: str) -> str:
    """LLM 标题生成失败时的回退：取用户首条消息前 16 字"""
    try:
        row = _sdb().fetchone(
            "SELECT content FROM llm_messages WHERE session_id = ? AND role = 'user' ORDER BY created_at LIMIT 1",
            (session_id,),
        )
        if row and row["content"]:
            text = row["content"].strip()
            if len(text) <= 16:
                return text
            return text[:16] + "…"
    except Exception:
        pass
    return ""


def _resolve_default_model_id() -> str:
    """获取默认模型 ID"""
    try:
        row = multi_db.main_db.fetchone(
            "SELECT id FROM model_configs WHERE is_default = 1 AND status = 'connected' LIMIT 1"
        )
        if row:
            return row["id"]
    except Exception:
        pass
    return ""


def _parse_tool_calls_simple(raw_parts: list) -> list:
    """简化的 tool_call JSON 解析"""
    try:
        raw = "".join(raw_parts)
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            result = []
            for tc in parsed:
                func = tc.get("function", {})
                args_raw = func.get("arguments", "{}")
                if isinstance(args_raw, str):
                    args = json.loads(args_raw)
                else:
                    args = args_raw
                result.append({"id": tc.get("id", ""), "name": func.get("name", ""), "arguments": args})
            return result
        elif isinstance(parsed, dict):
            func = parsed.get("function", {})
            args_raw = func.get("arguments", "{}")
            if isinstance(args_raw, str):
                args = json.loads(args_raw)
            else:
                args = args_raw
            return [{"id": parsed.get("id", ""), "name": func.get("name", ""), "arguments": args}]
    except (json.JSONDecodeError, AttributeError):
        pass
    return []


@app.get("/api/chat/sessions/{session_id}/messages")
async def get_chat_messages(session_id: str, limit: int = Query(50), offset: int = Query(0)):
    _require_chat_ready()
    try:
        rows = _sdb().fetchall(
            "SELECT id, role, content, metadata, created_at FROM llm_messages "
            "WHERE session_id = ? ORDER BY created_at LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        )
        return {
            "messages": [
                {
                    "id": m["id"],
                    "role": m["role"],
                    "content": m["content"],
                    "refs": json.loads(m["metadata"]).get("refs", []) if m["metadata"] else [],
                    "createdAt": m["created_at"],
                }
                for m in rows
            ],
            "total": len(rows),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/api/chat/sessions/{session_id}/messages")
async def delete_chat_messages(session_id: str, message_id: str = Query(None)):
    """删除会话中的一条或多条消息（支持逗号分隔的 message_id）"""
    _require_chat_ready()
    try:
        ids = [m.strip() for m in (message_id or "").split(",") if m.strip()]
        if not ids:
            raise HTTPException(422, "message_id is required")
        # 先记录被删除消息的时间戳，用于清理关联的 tool 消息
        timestamps = []
        for _id in ids:
            row = _sdb().fetchone(
                "SELECT created_at FROM llm_messages WHERE id = ? AND session_id = ?",
                (_id, session_id),
            )
            if row:
                timestamps.append(row["created_at"])
        placeholders = ",".join("?" * len(ids))
        _sdb().execute(
            f"DELETE FROM llm_messages WHERE session_id = ? AND id IN ({placeholders})",
            (session_id, *ids),
        )
        # 删除关联的 tool 消息（位于被删除消息与下一条非 tool 消息之间）
        for ts in timestamps:
            next_row = _sdb().fetchone(
                "SELECT MIN(created_at) AS next_ts FROM llm_messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') "
                "AND created_at > ?",
                (session_id, ts),
            )
            next_ts = next_row["next_ts"] if next_row and next_row["next_ts"] else "9999-12-31"
            _sdb().execute(
                "DELETE FROM llm_messages WHERE session_id = ? AND role = 'tool' "
                "AND created_at >= ? AND created_at < ?",
                (session_id, ts, next_ts),
            )
            prev_row = _sdb().fetchone(
                "SELECT MAX(created_at) AS prev_ts FROM llm_messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') "
                "AND created_at < ?",
                (session_id, ts),
            )
            if prev_row and prev_row["prev_ts"]:
                _sdb().execute(
                    "DELETE FROM llm_messages WHERE session_id = ? AND role = 'tool' "
                    "AND created_at > ? AND created_at < ?",
                    (session_id, prev_row["prev_ts"], ts),
                )
        # 更新 session 消息数
        cnt = _sdb().fetchone(
            "SELECT COUNT(*) AS c FROM llm_messages WHERE session_id = ? AND role IN ('user', 'assistant')",
            (session_id,),
        )
        count = cnt["c"] // 2 if cnt else 0
        row = _sdb().fetchone(
            "SELECT metadata FROM llm_sessions WHERE id = ?", (session_id,)
        )
        if row:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            meta["message_count"] = count
            _sdb().execute(
                "UPDATE llm_sessions SET metadata = ?, updated_at = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), __import__("datetime").datetime.now().isoformat(), session_id),
            )
        return {"ok": True, "deleted": len(ids)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# 自动补全

@app.get("/api/chat/autocomplete")
async def chat_autocomplete(
    type: str = Query(...), q: str = Query(...),
    taskId: str = Query(None), projectId: str = Query(None),
):
    """搜索联想：community / file / symbol / session"""
    _require_chat_ready()
    try:
        results = []
        if type == "community" and q:
            tid = taskId or ""
            rows = _sdb().fetchall(
                "SELECT DISTINCT comm_name, comm_id, comm_lv FROM community_llm_results "
                "WHERE task_id = ? AND comm_name LIKE ? LIMIT 10",
                (tid, f"%{q}%"),
            )
            for r in rows:
                results.append({
                    "label": f"{r['comm_name']} ({r['comm_lv']})",
                    "value": r["comm_id"],
                    "type": "community",
                })
        elif type == "file" and q:
            pid = projectId or ""
            rows = _sdb().fetchall(
                "SELECT DISTINCT file_path FROM file_summaries "
                "WHERE project_id = ? AND file_path LIKE ? LIMIT 10",
                (pid, f"%{q}%"),
            )
            for r in rows:
                results.append({
                    "label": r["file_path"],
                    "value": r["file_path"],
                    "type": "file",
                })
        elif type == "symbol" and q:
            rows = _sdb().fetchall(
                "SELECT name, kind FROM graph_node WHERE name LIKE ? LIMIT 10",
                (f"%{q}%",),
            )
            seen = set()
            for r in rows:
                if r["name"] not in seen:
                    seen.add(r["name"])
                    results.append({
                        "label": f"{r['name']} ({r['kind'] or 'symbol'})",
                        "value": r["name"],
                        "type": "symbol",
                    })
        elif type == "session" and q:
            rows = _sdb().fetchall(
                "SELECT id, title FROM llm_sessions WHERE id LIKE ? OR title LIKE ? LIMIT 10",
                (f"%{q}%", f"%{q}%"),
            )
            for r in rows:
                results.append({
                    "label": f"{r['title'] or '未命名'} ({r['id'][:12]}...)",
                    "value": r["id"],
                    "type": "session",
                })
        return {"results": results}
    except Exception as e:
        return {"results": [], "error": str(e)}


# 归档

@app.post("/api/chat/archives")
async def create_archive(request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        aid = f"arch_{uuid.uuid4().hex[:12]}"
        session_id = body.get("sessionId") or body.get("session_id", "")
        title = body.get("title", "")
        content = body.get("content", "")
        category = body.get("category", "note")
        tags = body.get("tags", "")
        pid = body.get("projectId") or body.get("project_id", "")
        if not pid and session_id:
            row = _sdb().fetchone(
                "SELECT project_id FROM llm_sessions WHERE id = ?", (session_id,)
            )
            if row:
                pid = row["project_id"]
        multi_db.main_db.execute(
            "INSERT INTO chat_archives (id, session_id, project_id, title, content, category, tags, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'manual')",
            (aid, session_id or None, pid or None, title, content, category, tags),
        )
        return {"id": aid, "ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/chat/archives")
async def list_archives(project_id: str = Query(None), category: str = Query(None), tag: str = Query(None)):
    _require_chat_ready()
    try:
        wheres = []
        params = []
        if project_id:
            wheres.append("project_id = ?")
            params.append(project_id)
        if category:
            wheres.append("category = ?")
            params.append(category)
        if tag:
            wheres.append("tags LIKE ?")
            params.append(f"%{tag}%")
        where = f"WHERE {' AND '.join(wheres)}" if wheres else ""
        rows = multi_db.main_db.fetchall(
            f"SELECT id, title, content, category, tags, source, created_at "
            f"FROM chat_archives {where} ORDER BY created_at DESC LIMIT 50"
        )
        return {
            "archives": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "content": r["content"][:500],
                    "category": r["category"],
                    "tags": r["tags"],
                    "source": r["source"],
                    "createdAt": r["created_at"],
                }
                for r in rows
            ],
            "total": len(rows),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/api/chat/archives/{archive_id}")
async def delete_archive(archive_id: str):
    _require_chat_ready()
    try:
        multi_db.main_db.execute("DELETE FROM chat_archives WHERE id = ?", (archive_id,))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


# ==================== 便签 (Notes) API ====================


def _make_note_id():
    return f"note_{uuid.uuid4().hex[:12]}"


@app.post("/api/notes")
async def create_note(request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        nid = _make_note_id()
        title = body.get("title", "")
        content = body.get("content", "")
        refs = json.dumps(body.get("refs", []), ensure_ascii=False)
        project_id = body.get("projectId") or body.get("project_id", "")
        now = __import__("datetime").datetime.now().isoformat()
        multi_db.main_db.execute(
            "INSERT INTO chat_notes (id, title, content, refs, status, project_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
            (nid, title, content, refs, project_id or None, now, now),
        )
        return {"id": nid, "title": title, "ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/notes")
async def list_notes(status: str = Query(None), project_id: str = Query(None)):
    _require_chat_ready()
    try:
        wheres = []
        params = []
        if status:
            wheres.append("status = ?")
            params.append(status)
        if project_id:
            wheres.append("project_id = ?")
            params.append(project_id)
        where = f"WHERE {' AND '.join(wheres)}" if wheres else ""
        rows = multi_db.main_db.fetchall(
            f"SELECT id, title, content, refs, status, session_id, project_id, created_at, updated_at "
            f"FROM chat_notes {where} ORDER BY updated_at DESC",
            tuple(params),
        )
        return {
            "notes": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "content": r["content"],
                    "refs": json.loads(r["refs"]) if r["refs"] else [],
                    "status": r["status"],
                    "sessionId": r["session_id"],
                    "projectId": r["project_id"],
                    "createdAt": r["created_at"],
                    "updatedAt": r["updated_at"],
                }
                for r in rows
            ],
            "total": len(rows),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/notes/{note_id}")
async def get_note(note_id: str):
    _require_chat_ready()
    try:
        row = multi_db.main_db.fetchone(
            "SELECT id, title, content, refs, status, session_id, project_id, created_at, updated_at "
            "FROM chat_notes WHERE id = ?",
            (note_id,),
        )
        if not row:
            raise HTTPException(404, "Note not found")
        return {
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "refs": json.loads(row["refs"]) if row["refs"] else [],
            "status": row["status"],
            "sessionId": row["session_id"],
            "projectId": row["project_id"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.put("/api/notes/{note_id}")
async def update_note(note_id: str, request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        row = multi_db.main_db.fetchone(
            "SELECT id, refs FROM chat_notes WHERE id = ?", (note_id,)
        )
        if not row:
            raise HTTPException(404, "Note not found")
        existing_refs = json.loads(row["refs"]) if row["refs"] else []
        updates = []
        if "title" in body:
            updates.append(("title", body["title"]))
        if "content" in body:
            updates.append(("content", body["content"]))
        if "refs" in body:
            seen = set()
            merged = []
            for r in existing_refs + body["refs"]:
                key = json.dumps(r, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    merged.append(r)
            updates.append(("refs", json.dumps(merged, ensure_ascii=False)))
        if not updates:
            return {"ok": True}
        now = __import__("datetime").datetime.now().isoformat()
        updates.append(("updated_at", now))
        set_clause = ", ".join(f"{k} = ?" for k, _ in updates)
        vals = [v for _, v in updates] + [note_id]
        multi_db.main_db.execute(
            f"UPDATE chat_notes SET {set_clause} WHERE id = ?", tuple(vals)
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/api/notes/{note_id}")
async def delete_note(note_id: str):
    _require_chat_ready()
    try:
        multi_db.main_db.execute("DELETE FROM chat_notes WHERE id = ?", (note_id,))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/notes/{note_id}/send")
async def send_note(note_id: str, request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        session_id = body.get("sessionId") or body.get("session_id", "")

        row = multi_db.main_db.fetchone(
            "SELECT id, title, content, refs, status, project_id FROM chat_notes WHERE id = ?",
            (note_id,),
        )
        if not row:
            raise HTTPException(404, "Note not found")
        if row["status"] == "sent":
            raise HTTPException(400, "Note already sent")

        refs = json.loads(row["refs"]) if row["refs"] else []
        title = row["title"] or "便签消息"
        note_content = row["content"] or ""
        project_id = row["project_id"]

        ref_context = resolve_refs_to_context(refs, multi_db)

        if not session_id:
            registry = get_skill_registry()
            default_skills = registry.list_defaults()
            sid = _make_session_id()
            now = __import__("datetime").datetime.now().isoformat()
            metadata = json.dumps({
                "module": "web_chat", "model_id": "",
                "active_skills": default_skills,
                "refs": refs, "note_id": note_id,
            }, ensure_ascii=False)
            _sdb().execute(
                "INSERT INTO llm_sessions (id, module_type, project_id, title, metadata, created_at, updated_at) "
                "VALUES (?, 'ai_assistant', ?, ?, ?, ?, ?)",
                (sid, project_id or None, title, metadata, now, now),
            )
            session_id = sid
        else:
            existing = _sdb().fetchone(
                "SELECT id, metadata FROM llm_sessions WHERE id = ?", (session_id,)
            )
            if not existing:
                raise HTTPException(404, "Session not found")
            meta = json.loads(existing["metadata"]) if existing["metadata"] else {}
            sent_notes = meta.get("sent_note_ids", [])
            if note_id in sent_notes:
                raise HTTPException(400, "Note already sent to this session")
            meta.setdefault("sent_note_ids", []).append(note_id)
            now = __import__("datetime").datetime.now().isoformat()
            _sdb().execute(
                "UPDATE llm_sessions SET metadata = ?, updated_at = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), now, session_id),
            )

        now = __import__("datetime").datetime.now().isoformat()
        sys_msg_id = _make_message_id()
        user_msg_id = _make_message_id()

        if ref_context:
            _sdb().execute(
                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, 'system', ?, ?, ?)",
                (sys_msg_id, session_id, ref_context,
                 json.dumps({"refs": refs, "note_id": note_id}, ensure_ascii=False), now),
            )

        user_text = note_content or f"分析这些内容：{title}"
        _sdb().execute(
            "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, 'user', ?, ?, ?)",
            (user_msg_id, session_id, user_text,
             json.dumps({"refs": refs, "note_id": note_id}, ensure_ascii=False), now),
        )

        multi_db.main_db.execute(
            "UPDATE chat_notes SET status = 'sent', session_id = ?, message_id = ?, updated_at = ? WHERE id = ?",
            (session_id, user_msg_id, now, note_id),
        )

        return {"sessionId": session_id, "messageId": user_msg_id, "ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/notes/batch-send")
async def batch_send_notes(request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        note_ids = body.get("noteIds", [])
        session_id = body.get("sessionId") or body.get("session_id", "")
        if not note_ids:
            raise HTTPException(422, "noteIds is required")
        first = None
        for nid in note_ids:
            try:
                result = await send_note(nid, request)
                if not first:
                    first = result
            except HTTPException as e:
                if e.status_code == 400 and "already sent" in str(e.detail):
                    continue
                raise
        return first or {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/notes/execute-draft")
async def execute_draft(request: Request):
    """从 viewer 草稿直接执行发送，不创建 DB note 记录。"""
    _require_chat_ready()
    try:
        body = await request.json()
        refs = body.get("refs", [])
        user_text = body.get("userText", "").strip()
        session_id = body.get("sessionId") or body.get("session_id")

        if not refs:
            raise HTTPException(422, "refs is required")

        project_id = refs[0].get("projectId", "")
        task_id = refs[0].get("taskId", "")

        # 直接构造上下文（draft refs 不含 type 字段，不走 resolve_refs_to_context）
        context_parts = []
        for ref in refs:
            label = ref.get("label", "")
            text = ref.get("text", "")
            pid = ref.get("projectId", "")
            tid = ref.get("taskId", "")
            cid = ref.get("componentId", "")
            meta = []
            if pid: meta.append(f"项目:{pid[:12]}")
            if tid: meta.append(f"任务:{tid[:10]}")
            if cid: meta.append(f"组件:{cid[:10]}")
            if label: meta.append(f"来源:{label}")
            s = " | ".join(meta)
            if text: s += "\n" + text
            context_parts.append(s)
        resolved = "\n\n".join(context_parts) if context_parts else "（引用材料为空）"

        if not session_id:
            title = "便签分析"
            if project_id:
                proj = multi_db.main_db.fetchone(
                    "SELECT name FROM projects WHERE id = ?", (project_id,)
                )
                if proj:
                    title = proj["name"] + " - 便签分析"
            session_id = _create_chat_session(title, task_id or project_id)

        # 插入 system 消息（引用上下文）
        sys_id = uuid.uuid4().hex[:16]
        from datetime import datetime as _dt
        now = _dt.now().isoformat()
        multi_db.sessions_db.execute(
            "INSERT INTO llm_messages (id, session_id, role, content, created_at) VALUES (?, ?, 'system', ?, ?)",
            (sys_id, session_id, resolved, now),
        )

        # 插入 user 消息
        user_msg_id = uuid.uuid4().hex[:16]
        content = user_text or "分析这些内容"
        multi_db.sessions_db.execute(
            "INSERT INTO llm_messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (user_msg_id, session_id, content, now),
        )

        # 更新 session 消息数（存到 metadata JSON 字段中）
        cnt = multi_db.sessions_db.fetchone(
            "SELECT COUNT(*) AS c FROM llm_messages WHERE session_id=?", (session_id,)
        )
        if cnt:
            row = multi_db.sessions_db.fetchone(
                "SELECT metadata FROM llm_sessions WHERE id=?", (session_id,)
            )
            if row:
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
                meta["message_count"] = cnt["c"]
                multi_db.sessions_db.execute(
                    "UPDATE llm_sessions SET metadata=?, updated_at=? WHERE id=?",
                    (json.dumps(meta, ensure_ascii=False), now, session_id),
                )


        return {"sessionId": session_id, "messageId": user_msg_id, "ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ==================== 上下文摘要 ====================
@app.get("/api/chat/context/project/{project_id}")
async def get_project_context(project_id: str):
    _require_chat_ready()
    try:
        proj = multi_db.main_db.fetchone(
            "SELECT id, name, root_path FROM projects WHERE id = ?", (project_id,)
        )
        if not proj:
            raise HTTPException(404, "Project not found")
        tasks = multi_db.main_db.fetchall(
            "SELECT id, name, status FROM analysis_tasks WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
        return {
            "project": {"id": proj["id"], "name": proj["name"], "rootPath": proj["root_path"]},
            "tasks": [
                {"id": t["id"], "name": t["name"], "status": t["status"]} for t in tasks
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/chat/context/task/{task_id}")
async def get_task_context(task_id: str):
    _require_chat_ready()
    try:
        task = multi_db.main_db.fetchone(
            "SELECT id, name, status, project_id FROM analysis_tasks WHERE id = ?", (task_id,)
        )
        if not task:
            raise HTTPException(404, "Task not found")
        pid = task["project_id"]
        pdb = multi_db.get_project_db(pid)
        communities = pdb.fetchall(
            "SELECT comm_id, comm_lv, name FROM community_llm_results WHERE task_id = ? LIMIT 20",
            (task_id,),
        )
        return {
            "task": {
                "id": task["id"],
                "name": task["name"],
                "status": task["status"],
                "projectId": task["project_id"],
            },
            "communities": [
                {"commId": c["comm_id"], "level": c["comm_lv"], "name": c["name"]}
                for c in communities
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))




# ==================== 结构分析导入/导出/校验 ====================

import export_service as _export_svc
import import_service as _import_svc
import verify_service as _verify_svc


def _publish(channel: str, event: str, data: dict):
    """如果 ZMQ server 可用则推送进度事件"""
    global zmq_server
    if zmq_server:
        try:
            zmq_server.publish(channel, event, data)
        except Exception:
            pass


@app.post("/api/export")
async def start_export(request: Request):
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        body = await request.json()
        project_id = body.get("projectId") or body.get("project_id")
        task_ids = body.get("taskIds")
        if not project_id:
            raise HTTPException(422, "projectId is required")
        export_id = _export_svc.start_export(multi_db, project_id, task_ids, _publish)
        return {"exportId": export_id, "status": "running"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/export/{export_id}/status")
async def get_export_status(export_id: str):
    status = _export_svc.get_export_status(export_id)
    if not status:
        raise HTTPException(404, "Export task not found")
    return status


@app.get("/api/export/{export_id}/download")
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


@app.post("/api/import")
async def start_import(request: Request):
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(422, "file is required")
        mode = form.get("mode", "share")
        import_path = os.path.join(multi_db.data_dir, "imports")
        os.makedirs(import_path, exist_ok=True)
        local_path = os.path.join(import_path, f"upload-{uuid.uuid4().hex[:12]}.zip")
        content = await file.read()
        with open(local_path, "wb") as f:
            f.write(content)
        import_id = _import_svc.start_import(multi_db, local_path, _publish,
                                              import_mode=mode, cleanup_archive=True)
        return {"importId": import_id, "status": "running"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/import/{import_id}/status")
async def get_import_status(import_id: str):
    status = _import_svc.get_import_status(import_id)
    if not status:
        raise HTTPException(404, "Import task not found")
    return status


@app.post("/api/projects/{project_id}/verify-files")
async def start_verify(project_id: str):
    if not multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        verify_id = _verify_svc.start_verify(multi_db, project_id, _publish)
        return {"verifyId": verify_id, "status": "running"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/verify/{verify_id}/status")
async def get_verify_status(verify_id: str):
    status = _verify_svc.get_verify_status(verify_id)
    if not status:
        raise HTTPException(404, "Verify task not found")
    return status


def _ensure_chat_tables():
    """确保聊天相关表存在"""
    if not multi_db:
        return
    multi_db.main_db.execute("""
        CREATE TABLE IF NOT EXISTS chat_archives (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            project_id TEXT,
            title TEXT,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'note',
            tags TEXT DEFAULT '',
            source TEXT DEFAULT 'manual',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    multi_db.main_db.execute("""
        CREATE TABLE IF NOT EXISTS chat_notes (
            id TEXT PRIMARY KEY,
            title TEXT DEFAULT '',
            content TEXT DEFAULT '',
            refs TEXT DEFAULT '[]',
            status TEXT DEFAULT 'draft',
            session_id TEXT,
            message_id TEXT,
            project_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)


def create_app(multi_db_instance, zmq_server_instance=None) -> FastAPI:
    global multi_db, zmq_server, web_tool_executor
    multi_db = multi_db_instance
    zmq_server = zmq_server_instance
    web_tool_executor = WebToolExecutor(multi_db)
    _ensure_chat_tables()
    return app


# ==================== 启动入口 ====================


async def start_http_server(multi_db_instance, port: int = 3456, host: str = '0.0.0.0',
                            cache_path: str = None, zmq_server_instance: object = None):
    global multi_db, http_port, zmq_server, web_tool_executor
    http_port = port
    multi_db = multi_db_instance
    zmq_server = zmq_server_instance
    web_tool_executor = WebToolExecutor(multi_db)
    _ensure_chat_tables()
    if cache_path:
        _init_cache_db(cache_path)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Web server starting on http://{host}:{port}")
    await server.serve()
