"""Web Server - FastAPI 提供本地 HTTP 文档浏览服务"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# 在 start_http_server 中注入
multi_db = None
zmq_server = None  # ZMQ server for pub events
plantuml_cache_db: Optional[sqlite3.Connection] = None
http_port = 3456

# 统一数据模块
import sys as _sys
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_backend_dir = os.path.join(_project_root, "backend-core")
if _backend_dir not in _sys.path:
    _sys.path.insert(0, _backend_dir)
import community_data as cd

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
            "SELECT name, summary, comm_lv FROM community_llm_results WHERE task_id=? AND edge_type=? AND comm_id=?",
            (tid, et, cid)
        )
        if not row:
            name = cid
            parts = [f"# {name}", "", f"**ID**: {cid}  **类型**: {et}", "",
                     "\u8be5\u7ec4\u4ef6\u6682\u65e0 LLM \u5206\u6790\u7ed3\u679c\uff0c\u8bf7\u5148\u901a\u8fc7 AI \u52a9\u624b\u8fd0\u884c\u7ec4\u4ef6\u5206\u6790\u3002"]
        else:
            name = row.get("name") or cid
            parts = [f"# {name}", "", f"**ID**: {cid}  **类型**: {et}", "", row.get("summary") or ""]
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
        project_root = (proj_row["root_path"] + "/") if proj_row and proj_row["root_path"] else ""
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


@app.get("/", response_class=HTMLResponse)
async def index(search: str = Query(None), page: int = Query(1), page_size: int = Query(50)):
    if not multi_db:
        return HTMLResponse('<html><body><h1>TopoCode</h1><p>Backend not ready</p></body></html>')
    try:
        ps = max(10, min(200, page_size))
        offset = (max(1, page) - 1) * ps
        q = search or ''

        # 查所有任务，按项目分组
        all_tasks = multi_db.main_db.fetchall(
            "SELECT t.id, t.name, t.status, t.project_id, p.name AS project_name "
            "FROM analysis_tasks t JOIN projects p ON t.project_id = p.id "
            "WHERE (? = '' OR t.name LIKE ? OR p.name LIKE ?) "
            "ORDER BY t.project_id, t.created_at DESC",
            (q, f'%{q}%', f'%{q}%')
        )

        # 按项目分组，优先排有文档的
        projects_map = {}
        for t in all_tasks:
            pid = t["project_id"]
            if pid not in projects_map:
                projects_map[pid] = {"name": t["project_name"], "tasks": [], "has_doc": False}
            has_ov = False
            try:
                pdb = multi_db.get_project_db(pid)
                doc = pdb.fetchone("SELECT id FROM report_subdocs WHERE id=?", (f"overall-{t['id']}",))
                has_ov = doc is not None
            except Exception:
                pass
            projects_map[pid]["tasks"].append({"id": t["id"], "name": t["name"], "status": t["status"], "hasDoc": has_ov})
            if has_ov:
                projects_map[pid]["has_doc"] = True

        # 排序：有文档的靠前，其余按项目名
        proj_list = sorted(projects_map.values(), key=lambda x: (not x["has_doc"], x["name"]))

        # 分页：所有任务扁平化后分页
        flat_tasks = []
        for proj in proj_list:
            for t in proj["tasks"]:
                flat_tasks.append((proj["name"], t))
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
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f5f5;color:#333;font-size:14px;line-height:1.6;padding:24px}
  .container{max-width:800px;margin:0 auto}
  h1{font-size:20px;margin-bottom:16px;color:#111}
  .toolbar{display:flex;gap:8px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
  .toolbar input{padding:6px 10px;border:1px solid #d0d0d0;border-radius:6px;font-size:13px;flex:1;min-width:160px;outline:none}
  .toolbar input:focus{border-color:#2563eb}
  .toolbar select{padding:6px 8px;border:1px solid #d0d0d0;border-radius:6px;font-size:12px}
  .toolbar .info{font-size:12px;color:#999}
  .project{background:#fff;border-radius:8px;border:1px solid #e0e0e0;margin-bottom:10px;overflow:hidden}
  .project-header{padding:10px 14px;font-weight:600;font-size:13px;background:#fafafa;border-bottom:1px solid #e0e0e0;cursor:pointer;display:flex;align-items:center;gap:8px}
  .project-header:hover{background:#f0f0f0}
  .project-header .arrow{transition:transform .2s;font-size:10px}
  .project-header .arrow.open{transform:rotate(90deg)}
  .task-item{padding:8px 14px 8px 32px;border-bottom:1px solid #f0f0f0;display:flex;align-items:center;gap:8px}
  .task-item:last-child{border-bottom:none}
  .task-item a{color:#2563eb;text-decoration:none;font-size:13px}
  .task-item a:hover{text-decoration:underline}
  .status-dot{width:6px;height:6px;border-radius:50%;display:inline-block;flex-shrink:0}
  .status-dot.done{background:#5a9e6f}
  .status-dot.pending{background:#c08a4b}
  .status-label{font-size:11px;font-weight:500}
  .status-label.done{color:#5a9e6f}
  .status-label.pending{color:#c08a4b}
  .empty{padding:20px;color:#999;font-size:13px;text-align:center}
  .pagination{display:flex;gap:6px;justify-content:center;margin-top:16px;flex-wrap:wrap}
  .pagination a,.pagination span{padding:4px 10px;border:1px solid #d0d0d0;border-radius:4px;font-size:12px;text-decoration:none;color:#333}
  .pagination a:hover{background:#f0f0f0}
  .pagination .active{background:#2563eb;color:#fff;border-color:#2563eb}
  @media(prefers-color-scheme:dark){
    body{background:#1a1a2e;color:#e0e0e0}
    h1{color:#fff}
    .project{background:#16213e;border-color:#333}
    .project-header{background:#1a1a2e;border-color:#333}
    .project-header:hover{background:#222}
    .task-item{border-color:#2a2a3e}
    .task-item a{color:#60a5fa}
    .toolbar input,.toolbar select{background:#222;border-color:#444;color:#e0e0e0}
    .pagination a,.pagination span{background:#222;border-color:#444;color:#e0e0e0}
    .pagination .active{background:#2563eb;border-color:#2563eb}
  }
</style></head><body>
<div class="container">
<h1>📄 TopoCode Documents</h1>
<div class="toolbar">
  <form method="get" action="/" style="display:flex;gap:8px;flex:1;align-items:center">
    <input type="text" name="search" placeholder="搜索项目/任务..." value="__Q_ESC__">
    <button type="submit" style="padding:6px 14px;border:1px solid #d0d0d0;border-radius:6px;background:#fff;cursor:pointer;font-size:12px">搜索</button>
  </form>
  <select onchange="location.href='/?search='+encodeURIComponent('__Q_ESC__')+'&page=1&page_size='+this.value">
    <option value="50"__PS_50__>50条/页</option>
    <option value="100"__PS_100__>100条/页</option>
    <option value="200"__PS_200__>200条/页</option>
  </select>
  <span class="info">共 __TOTAL__ 条</span>
</div>"""
        html = html.replace('__Q_ESC__', q_esc).replace('__TOTAL__', total_str)
        html = html.replace('__PS_50__', ps_sel_50).replace('__PS_100__', ps_sel_100).replace('__PS_200__', ps_sel_200)

        last_proj = None
        shown = 0
        for proj_name, t in page_tasks:
            shown += 1
            if proj_name != last_proj:
                if last_proj is not None:
                    html += '</div></div>'
                html += f'<div class="project"><div class="project-header" onclick="this.nextElementSibling.classList.toggle(\'open\');this.querySelector(\'.arrow\').classList.toggle(\'open\')"><span class="arrow">▶</span> {esc(proj_name)}</div><div class="project-tasks open">'
                last_proj = proj_name
            dot_class = 'done' if t["hasDoc"] else 'pending'
            if t["hasDoc"]:
                html += f'<div class="task-item"><span class="status-dot {dot_class}"></span><a href="/doc?taskId={esc(t["id"])}&docId=overall-{esc(t["id"])}">{esc(t["name"])}</a><span class="status-label {dot_class}">已生成</span></div>'
            else:
                html += f'<div class="task-item"><span class="status-dot {dot_class}"></span><span style="color:#999;font-size:13px">{esc(t["name"])}</span><span class="status-label {dot_class}">未生成</span></div>'
        if last_proj is not None:
            html += '</div></div>'
        if total == 0:
            html += '<div class="empty">暂无匹配结果</div>'

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
        project_root = (proj_row["root_path"] + "/") if proj_row and proj_row["root_path"] else ""

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
        project_root = (proj_row["root_path"] + "/") if proj_row and proj_row["root_path"] else ""

        def _rel(p):
            if not p: return p
            if p.startswith('file:'): p = p[5:]
            if project_root and p.startswith(project_root): p = p[len(project_root):]
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
        project_root = (proj_row["root_path"] + "/") if proj_row and proj_row["root_path"] else ""

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
        project_root = (proj_row["root_path"] + "/") if proj_row and proj_row["root_path"] else ""
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
        project_root = (proj_row["root_path"] + "/") if proj_row and proj_row["root_path"] else ""
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
        import_path = os.path.join(multi_db.data_dir, "imports")
        os.makedirs(import_path, exist_ok=True)
        local_path = os.path.join(import_path, f"upload-{uuid.uuid4().hex[:12]}.zip")
        content = await file.read()
        with open(local_path, "wb") as f:
            f.write(content)
        import_id = _import_svc.start_import(multi_db, local_path, _publish)
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


def create_app(multi_db_instance, zmq_server_instance=None) -> FastAPI:
    global multi_db, zmq_server
    multi_db = multi_db_instance
    zmq_server = zmq_server_instance
    return app


# ==================== 启动入口 ====================


async def start_http_server(multi_db_instance, port: int = 3456, host: str = '127.0.0.1',
                            cache_path: str = None, zmq_server_instance: object = None):
    global multi_db, http_port, zmq_server
    http_port = port
    multi_db = multi_db_instance
    zmq_server = zmq_server_instance
    if cache_path:
        _init_cache_db(cache_path)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Web server starting on http://{host}:{port}")
    await server.serve()
