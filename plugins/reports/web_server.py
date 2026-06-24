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
            "SELECT name, summary, comm_lv FROM community_llm_results WHERE task_id=? AND edge_type=? AND comm_id=?",
            (tid, et, cid)
        )
        if not row:
            raise HTTPException(404, "Community result not found")
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
        logger.info(f"[community-children] task={tid} parent={pid} edgeType={et}")
        # 先在主库查找该任务所属项目
        task_row = multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (tid,)
        )
        if not task_row:
            logger.info(f"[community-children] Task not found in main DB: {tid}")
            return []
        project_id = task_row["project_id"]
        logger.info(f"[community-children] Task {tid} belongs to project {project_id}")
        try:
            pdb = multi_db.get_project_db(project_id)
        except Exception as e:
            logger.warning(f"[community-children] Failed to get project DB: {e}")
            return []
        # 查询子社区：pid 为空时查顶级（parent_comm_id IS NULL），否则查指定父级
        # 先用指定 edge_type，若无数据则尝试另一种类型（仅 CALL / INCLUDE，DEPENDENCY 不在 DB 中存储）
        fallback_types = ['CALL', 'INCLUDE']
        if et and et in fallback_types:
            fallback_types.remove(et)
        for attempt_et in ([et] if et else []) + fallback_types:
            if pid:
                rows = pdb.fetchall(
                    """SELECT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count,
                              h.edge_type,
                              r.name AS llm_name
                       FROM community_hierarchy h
                       LEFT JOIN community_llm_results r
                         ON r.task_id = h.task_id AND r.edge_type = h.edge_type
                         AND r.comm_lv = h.comm_lv AND r.comm_id = h.comm_id
                       WHERE h.task_id = ? AND h.edge_type = ? AND h.parent_comm_id = ?
                       ORDER BY h.comm_lv, h.comm_id""",
                    (tid, attempt_et, pid)
                )
            else:
                rows = pdb.fetchall(
                    """SELECT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count,
                              h.edge_type,
                              r.name AS llm_name
                       FROM community_hierarchy h
                       LEFT JOIN community_llm_results r
                         ON r.task_id = h.task_id AND r.edge_type = h.edge_type
                         AND r.comm_lv = h.comm_lv AND r.comm_id = h.comm_id
                       WHERE h.task_id = ? AND h.edge_type = ? AND h.parent_comm_id IS NULL
                       ORDER BY h.comm_lv, h.comm_id""",
                    (tid, attempt_et)
                )
            if rows:
                break
        result = []
        for row in rows if rows else []:
            level = row["comm_lv"]
            edge = row.get("edge_type", attempt_et)
            result.append({
                "commId": row["comm_id"],
                "commLv": level,
                "parentCommId": row["parent_comm_id"],
                "name": row["llm_name"] or "",
                "hasDoc": bool(row["llm_name"]),
                "nodeCount": row["node_count"] or 0,
                "edgeType": edge,
            })
        logger.info(f"[community-children] Found {len(result)} children for task={tid} parent={pid} (query edgeType={attempt_et}, levels={set(r['commLv'] for r in result)})")
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
                              scope: str = Query(None), scope_: str = Query(None),
                              gran: str = Query(None), gran_: str = Query(None)):
    """社区结构图

    参数:
      gran / gran_ — component（社区级节点+边）| file（文件级节点+边）
      scope / scope_ — external（含跨社区边）| internal（仅内部边，仅 file 模式有效）
      comm_id / commId — 聚焦到指定社区
    """
    task_id = task_id or taskId
    edge_type = edge_type or edgeType or "CALL"
    comm_lv = comm_lv or commLv or ""
    comm_id = comm_id or commId or ""
    sc = (scope or scope_ or "external").lower()
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

        def _rel(p):
            if not p: return p
            if p.startswith('file:'): p = p[5:]
            if project_root and p.startswith(project_root): p = p[len(project_root):]
            return p.lstrip('/')

        def bad_id(v):
            s = str(v).strip()
            return not s or s == 'None'

        # ======== 文件级模式 ========
        if gn == "file":
            return _community_graph_file(pdb, task_id, et, comm_lv, comm_id, sc, _rel, bad_id)

        # ======== 社区级模式 ========
        # 1. 查询 graph_doc 获取社区元数据
        base_where = ["task_id=? AND edge_type=?"]
        base_params = [task_id, et]
        if comm_id:
            # 下钻：查找该社区的 children
            child_rows = pdb.fetchall(
                "SELECT comm_id, comm_lv FROM community_hierarchy "
                "WHERE task_id=? AND edge_type=? AND parent_comm_id=? "
                "ORDER BY comm_lv, comm_id",
                (task_id, et, comm_id)
            )
            if child_rows:
                # 有子社区 → 查子社区的 graph_doc
                child_ids = [r["comm_id"] for r in child_rows]
                ph = ','.join(['?' for _ in child_ids])
                base_where.append(f"comm_id IN ({ph})")
                base_params.extend(child_ids)
            else:
                # 叶子社区 → 返回该社区自身作为节点
                base_where.append("comm_id=?")
                base_params.append(comm_id)
        if comm_lv:
            base_where.append("comm_lv=?")
            base_params.append(comm_lv)

        rows = pdb.fetchall(
            f"SELECT comm_id, comm_lv, node_list, node_count, edge_count "
            f"FROM graph_doc WHERE {' AND '.join(base_where)} "
            f"ORDER BY comm_lv, comm_id",
            tuple(base_params)
        )
        if not rows:
            return {"nodes": [], "edges": [], "commIds": []}

        # 社区名称
        name_rows = pdb.fetchall(
            "SELECT comm_id, name FROM community_llm_results WHERE task_id=? AND edge_type=?",
            (task_id, et)
        )
        name_map = {r["comm_id"]: r["name"] or r["comm_id"] for r in name_rows}

        # 建立 file→comm 映射
        file_comm = {}
        for r in rows:
            cid = r["comm_id"]
            try:
                nlist = json.loads(r["node_list"]) if isinstance(r["node_list"], str) else r["node_list"] or []
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

        # 计算跨社区边
        kind = "imports" if et == "INCLUDE" else "calls"
        all_ge = pdb.fetchall(
            "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
            (task_id, kind)
        )
        node_set = set()
        cross_edge_set = set()
        for e in all_ge:
            src_raw = e["source_id"] or ""
            tgt_raw = e["target_id"] or ""
            src_key = _rel(src_raw)
            tgt_key = _rel(tgt_raw)
            if not src_key or not tgt_key:
                continue
            src_comm = file_comm.get(src_key)
            tgt_comm = file_comm.get(tgt_key)
            if src_comm and tgt_comm and src_comm != tgt_comm:
                eid = f"{src_comm}→{tgt_comm}"
                cross_edge_set.add(eid)
                node_set.add(src_comm)
                node_set.add(tgt_comm)
            elif src_comm:
                node_set.add(src_comm)
            elif tgt_comm:
                node_set.add(tgt_comm)

        # 没有跨社区边时仍显示所有查询到的社区
        if not cross_edge_set:
            for r in rows:
                node_set.add(r["comm_id"])

        # 构建社区级节点
        comm_node_map = {}
        comm_ids_meta = []
        for r in rows:
            cid = r["comm_id"]
            clv = r["comm_lv"]
            comm_ids_meta.append({"commId": cid, "commLv": clv, "name": name_map.get(cid, cid)})
            if cid in node_set:
                comm_node_map[cid] = {"id": cid, "label": name_map.get(cid, cid), "commLv": clv}

        return {
            "nodes": list(comm_node_map.values()),
            "edges": [{"id": e, "source": e.split("→")[0], "target": e.split("→")[1]} for e in cross_edge_set],
            "commIds": comm_ids_meta
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[community-graph] error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, str(e))


def _community_graph_file(pdb, task_id, et, comm_lv, comm_id, sc, _rel, bad_id):
    """文件级模式：返回社区内的文件节点 + 边"""
    base_where = ["task_id=? AND edge_type=?"]
    base_params = [task_id, et]
    if comm_id:
        base_where.append("comm_id=?")
        base_params.append(comm_id)
    if comm_lv:
        base_where.append("comm_lv=?")
        base_params.append(comm_lv)

    rows = pdb.fetchall(
        f"SELECT comm_id, comm_lv, node_list, edge_list, node_count, edge_count "
        f"FROM graph_doc WHERE {' AND '.join(base_where)} "
        f"ORDER BY comm_lv, comm_id",
        tuple(base_params)
    )
    if not rows:
        return {"nodes": [], "edges": [], "commIds": []}

    name_rows = pdb.fetchall(
        "SELECT comm_id, name FROM community_llm_results WHERE task_id=? AND edge_type=?",
        (task_id, et)
    )
    name_map = {r["comm_id"]: r["name"] or r["comm_id"] for r in name_rows}

    all_nodes = {}
    all_edges = {}
    comm_ids_meta = []

    for r in rows:
        cid = r["comm_id"]
        clv = r["comm_lv"]
        comm_ids_meta.append({"commId": cid, "commLv": clv, "name": name_map.get(cid, cid)})

        try:
            raw_nodes = json.loads(r["node_list"]) if isinstance(r["node_list"], str) else r["node_list"] or []
        except Exception:
            raw_nodes = []
        if not isinstance(raw_nodes, list):
            raw_nodes = [raw_nodes]

        try:
            raw_edges = json.loads(r["edge_list"]) if isinstance(r["edge_list"], str) else r["edge_list"] or []
        except Exception:
            raw_edges = []
        if not isinstance(raw_edges, list):
            raw_edges = [raw_edges]

        if et == "CALL":
            for node_id in raw_nodes:
                if isinstance(node_id, dict):
                    nid = str(node_id.get("id", ""))
                else:
                    nid = str(node_id)
                if bad_id(nid):
                    continue
                clean = nid.split(':')[0] if ':' in nid else nid
                if clean and clean not in all_nodes:
                    label = clean.split("/")[-1] if "/" in clean else clean
                    all_nodes[clean] = {"id": clean, "label": label, "commId": cid, "commLv": clv}

            for edge in raw_edges:
                if isinstance(edge, dict):
                    src = edge.get("source", "")
                    tgt = edge.get("target", "")
                elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    src = edge[0]
                    tgt = edge[1]
                else:
                    continue
                s = _rel(str(src))
                t = _rel(str(tgt))
                if not s or not t:
                    continue
                s_clean = s.split(':')[0] if ':' in s else s
                t_clean = t.split(':')[0] if ':' in t else t
                if bad_id(s_clean) or bad_id(t_clean) or s_clean == t_clean:
                    continue
                eid = f"{s_clean}→{t_clean}"
                if eid not in all_edges:
                    all_edges[eid] = {"id": eid, "source": s_clean, "target": t_clean}
                if s_clean not in all_nodes:
                    label = s_clean.split("/")[-1] if "/" in s_clean else s_clean
                    all_nodes[s_clean] = {"id": s_clean, "label": label, "commId": cid, "commLv": clv}
                if t_clean not in all_nodes:
                    label = t_clean.split("/")[-1] if "/" in t_clean else t_clean
                    all_nodes[t_clean] = {"id": t_clean, "label": label, "commId": cid, "commLv": clv}
        else:
            for node_id in raw_nodes:
                if isinstance(node_id, dict):
                    nid = str(node_id.get("id", ""))
                    label = node_id.get("name", "") or nid.split("/")[-1] if "/" in nid else nid
                else:
                    nid = str(node_id)
                    label = nid.split("/")[-1] if "/" in nid else nid
                if bad_id(nid):
                    continue
                nid = _rel(nid)
                if nid and nid not in all_nodes:
                    all_nodes[nid] = {"id": nid, "label": label, "commId": cid, "commLv": clv}

            for edge in raw_edges:
                if isinstance(edge, dict):
                    src = edge.get("source", "")
                    tgt = edge.get("target", "")
                elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    src = edge[0]
                    tgt = edge[1]
                else:
                    continue
                s = _rel(str(src))
                t = _rel(str(tgt))
                if not s or not t or s == t:
                    continue
                eid = f"{s}→{t}"
                if eid not in all_edges:
                    all_edges[eid] = {"id": eid, "source": s, "target": t}
                if s not in all_nodes:
                    all_nodes[s] = {"id": s, "label": s.split("/")[-1] if "/" in s else s, "commId": cid, "commLv": clv}
                if t not in all_nodes:
                    all_nodes[t] = {"id": t, "label": t.split("/")[-1] if "/" in t else t, "commId": cid, "commLv": clv}

    # scope=external + comm_id: 从 graph_edge 补充跨社区边
    if sc == "external" and comm_id:
        kind = "imports" if et == "INCLUDE" else "calls"
        file_comm = {}
        for r in rows:
            cid2 = r["comm_id"]
            try:
                nlist = json.loads(r["node_list"]) if isinstance(r["node_list"], str) else r["node_list"] or []
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
                    file_comm[fp] = cid2

        all_ge = pdb.fetchall(
            "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
            (task_id, kind)
        )
        for e in all_ge:
            src = _rel(e["source_id"] or "")
            tgt = _rel(e["target_id"] or "")
            if not src or not tgt:
                continue
            src_comm = file_comm.get(src)
            tgt_comm = file_comm.get(tgt)
            if not src_comm or not tgt_comm or src_comm == tgt_comm:
                continue
            if src_comm == comm_id or tgt_comm == comm_id:
                eid = f"{src}→{tgt}"
                if eid not in all_edges:
                    all_edges[eid] = {"id": eid, "source": src, "target": tgt}
                if src not in all_nodes:
                    all_nodes[src] = {"id": src, "label": src.split("/")[-1] if "/" in src else src, "commId": src_comm or "", "commLv": ""}
                if tgt not in all_nodes:
                    all_nodes[tgt] = {"id": tgt, "label": tgt.split("/")[-1] if "/" in tgt else tgt, "commId": tgt_comm or "", "commLv": ""}

    return {"nodes": list(all_nodes.values()), "edges": list(all_edges.values()), "commIds": comm_ids_meta}


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
        pid, pdb = _resolve_project_db(task_id)
        et = (edge_type or edgeType or "CALL").upper()
        rows = pdb.fetchall(
            """SELECT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count, h.edge_count,
                      r.name AS llm_name
               FROM community_hierarchy h
               LEFT JOIN community_llm_results r
                 ON r.task_id = h.task_id AND r.edge_type = h.edge_type
                 AND r.comm_lv = h.comm_lv AND r.comm_id = h.comm_id
               WHERE h.task_id = ? AND h.edge_type = ?
               ORDER BY h.comm_lv, h.comm_id""",
            (task_id, et)
        )
        groups = {}
        for r in rows:
            lv = r["comm_lv"]
            if lv not in groups:
                groups[lv] = []
            groups[lv].append({
                "commId": r["comm_id"],
                "commLv": lv,
                "parentCommId": r["parent_comm_id"],
                "name": r["llm_name"] or r["comm_id"],
                "nodeCount": r["node_count"] or 0,
                "edgeCount": r["edge_count"] or 0,
            })
        levels = [{"lv": k, "items": v} for k, v in sorted(groups.items())]
        return {"levels": levels}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/heatmap")
async def get_heatmap(task_id: str = Query(None), taskId: str = Query(None),
                       edge_type: str = Query(None), edgeType: str = Query(None),
                       size: int = Query(10)):
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
        lv = "L0"  # 热力图基于 L0 社区

        # 获取项目根路径（用于归一化 edge 中的绝对路径）
        proj_row = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj_row["root_path"] + "/") if proj_row and proj_row["root_path"] else ""

        def _rel(p: str) -> str:
            if not p:
                return p
            if p.startswith('file:'):
                p = p[5:]
            if project_root and p.startswith(project_root):
                p = p[len(project_root):]
            return p.lstrip('/')

        # 1. 加载 L0 社区 node_list
        doc_rows = pdb.fetchall(
            "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=?",
            (task_id, et, lv)
        )
        if not doc_rows:
            return {"rows": [], "cols": [], "matrix": [], "maxCount": 0}

        # 2. 构建 node → comm_id 反向映射
        node_comm = {}
        comm_names = {}
        comm_order = []
        for r in doc_rows:
            cid = r["comm_id"]
            comm_order.append(cid)
            try:
                nodes = json.loads(r["node_list"]) if r["node_list"] else []
            except Exception:
                nodes = []
            for n in (nodes if isinstance(nodes, list) else [nodes]):
                key = n["id"] if isinstance(n, dict) else str(n)
                if key:
                    node_comm[key] = cid

        # 获取社区名称
        name_rows = pdb.fetchall(
            "SELECT comm_id, name FROM community_llm_results WHERE task_id=? AND edge_type=? AND comm_lv=?",
            (task_id, et, lv)
        )
        name_map = {r["comm_id"]: r["name"] or r["comm_id"] for r in name_rows}
        comm_names_list = [name_map.get(cid, cid) for cid in comm_order]
        n = len(comm_order)

        # 3. 加载边数据
        if et == "INCLUDE":
            all_edges = pdb.fetchall(
                "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind='imports'",
                (task_id,)
            )
        else:
            all_edges = pdb.fetchall(
                "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind='calls'",
                (task_id,)
            )
            sym_ids = set()
            for e in all_edges:
                if e['source_id']: sym_ids.add(e['source_id'])
                if e['target_id']: sym_ids.add(e['target_id'])
            symbol_file_map = {}
            if sym_ids:
                sym_list = list(sym_ids)
                batch_size = 900
                for i in range(0, len(sym_list), batch_size):
                    batch = sym_list[i:i + batch_size]
                    placeholders = ",".join("?" * len(batch))
                    gn_rows = pdb.fetchall(
                        f"SELECT id, file_path FROM graph_node WHERE task_id=? AND id IN ({placeholders})",
                        [task_id] + batch
                    )
                    for gr in gn_rows:
                        symbol_file_map[gr['id']] = gr['file_path'] or ""

        # 4. 统计跨社区边
        comm_index = {cid: i for i, cid in enumerate(comm_order)}
        matrix = [[0] * n for _ in range(n)]
        for edge in all_edges:
            src_raw = edge['source_id'] or ""
            tgt_raw = edge['target_id'] or ""
            if not src_raw or not tgt_raw:
                continue
            if et == "INCLUDE":
                src_key = _rel(src_raw)
                tgt_key = _rel(tgt_raw)
            else:
                src_key = _rel(symbol_file_map.get(src_raw, ""))
                tgt_key = _rel(symbol_file_map.get(tgt_raw, ""))
            src_comm = node_comm.get(src_key)
            tgt_comm = node_comm.get(tgt_key)
            if src_comm and tgt_comm and src_comm != tgt_comm:
                si = comm_index.get(src_comm)
                ti = comm_index.get(tgt_comm)
                if si is not None and ti is not None:
                    matrix[si][ti] += 1

        max_count = max(max(row) for row in matrix) if n > 0 else 0
        return {"rows": comm_names_list, "cols": comm_names_list, "matrix": matrix, "maxCount": max_count}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[heatmap] error: {e}\n{traceback.format_exc()}")
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


def create_app(multi_db_instance) -> FastAPI:
    global multi_db
    multi_db = multi_db_instance
    return app


# ==================== 启动入口 ====================


async def start_http_server(multi_db_instance, port: int = 3456, host: str = '127.0.0.1', cache_path: str = None):
    global multi_db, http_port
    http_port = port
    multi_db = multi_db_instance
    if cache_path:
        _init_cache_db(cache_path)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Web server starting on http://{host}:{port}")
    await server.serve()
