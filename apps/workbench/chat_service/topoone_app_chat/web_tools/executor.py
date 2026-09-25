"""WebToolExecutor 执行器（MS5-V3 重做）。"""
import logging

from topoone.db.manager import MultiDBManager

logger = logging.getLogger(__name__)


from .defs import MAX_RESULT_LENGTH, _is_empty_result, REF_TYPES, _strip_ref_prefix, WEB_TOOL_MAP


class WebToolExecutor:
    """Web AI 对话的工具执行器"""

    def __init__(self, multi_db: MultiDBManager, current_session_id: str = ""):
        self.multi_db = multi_db
        self._current_session_id = current_session_id
        self._handlers = {
            "web_list_projects": self._list_projects,
        "web_get_task_list": self._get_task_list,
            "web_get_architecture_overview": self._get_architecture_overview,
            "web_get_community_tree": self._get_community_tree,
            "web_get_community_detail": self._get_community_detail,
            "web_get_community_graph": self._get_community_graph,
            "web_get_community_files": self._get_community_files,
            "web_read_file": self._read_file,
            "web_read_file_lines": self._read_file_lines,
            "web_get_file_summary": self._get_file_summary,
            "web_search_symbols": self._search_symbols,
            "web_get_symbol_detail": self._get_symbol_detail,
            "web_get_call_chain": self._get_call_chain,
            "web_search_archives": self._search_archives,
            "web_save_archive": self._save_archive,
            "web_set_session_title": self._set_session_title,
            "web_search_conversation_history": self._search_conversation_history,
            "web_list_sessions": self._list_sessions,
            "web_get_session_info": self._get_session_info,
            "web_search_across_sessions": self._search_across_sessions,
            "web_get_session_messages": self._get_session_messages,
            "web_summarize_session": self._summarize_session,
            "web_extract_topics": self._extract_topics,
            "web_compare_sessions": self._compare_sessions,
            "web_list_archives": self._list_archives,
            "web_delete_archive": self._delete_archive,
            "web_update_archive": self._update_archive,
            "web_search_knowledge": self._search_knowledge,
            "web_get_document": self._get_document,
            "web_diagram_build": self._diagram_build,
            "web_diagram_validate": self._diagram_validate,
        }

    def execute(self, tool_name: str, args: dict) -> dict:
        handler = self._handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}", "skip": True}
        try:
            result = handler(args)
            result_str = json.dumps(result, ensure_ascii=False, default=str)
            if len(result_str) > MAX_RESULT_LENGTH:
                result_str = result_str[:MAX_RESULT_LENGTH] + "\n...(truncated)"
                return {"content": result_str, "truncated": True}
            # 空结果标记：让 LLM 知道此路径无有效数据，跳过
            if _is_empty_result(result):
                result["_skip"] = True
                result["_message"] = "此工具未返回有效数据，请跳过此路径，尝试其他方法"
            return result
        except Exception as e:
            logger.error(f"[WebToolExecutor] {tool_name} failed: {e}")
            return {"error": str(e), "skip": True, "_message": f"工具 {tool_name} 执行失败，请跳过此路径"}

    def _resolve_task(self, task_id: str) -> tuple:
        task = self.multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
        )
        if not task:
            task = self.multi_db.main_db.fetchone(
                "SELECT project_id FROM analysis_tasks WHERE id LIKE ?", (task_id + '%',)
            )
        if not task:
            raise ValueError(f"Task {task_id} not found")
        return task["project_id"], self.multi_db.get_project_db(task["project_id"])

    def _list_projects(self, args: dict) -> dict:
        rows = self.multi_db.main_db.fetchall(
            "SELECT id, name, root_path, created_at FROM projects ORDER BY created_at DESC"
        )
        return {
            "projects": [
                {"id": r["id"], "name": r["name"], "rootPath": r["root_path"], "createdAt": r["created_at"]}
                for r in rows
            ],
            "total": len(rows),
        }

    def _get_task_list(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        rows = self.multi_db.main_db.fetchall(
            "SELECT id, name, type, status, created_at "
            "FROM analysis_tasks WHERE project_id = ? ORDER BY created_at DESC",
            (pid,),
        )
        return {
            "tasks": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "type": r["type"],
                    "status": r["status"],
                    "createdAt": r["created_at"],
                }
                for r in rows
            ],
            "total": len(rows),
        }

    def _get_architecture_overview(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        pid, pdb = self._resolve_task(task_id)
        doc = pdb.fetchone(
            "SELECT id, title, content FROM report_subdocs WHERE id = ?",
            (f"overall-{task_id}",),
        )
        if not doc:
            return {"found": False, "message": "架构概览文档尚未生成，请先执行 /overview 命令"}
        return {"found": True, "title": doc["title"], "content": doc["content"]}

    def _get_community_tree(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        et = (args.get("edgeType") or "UNIFIED").upper()
        pid, pdb = self._resolve_task(task_id)
        levels = cd.get_cascade_levels(pdb, task_id, et)
        return {"levels": levels, "taskId": task_id, "edgeType": et}

    def _get_community_detail(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        comm_id = args.get("commId", "")
        et = (args.get("edgeType") or "UNIFIED").upper()
        inferred = cd._infer_edge_type(comm_id)
        if inferred:
            et = inferred
        pid, pdb = self._resolve_task(task_id)
        row = pdb.fetchone(
            "SELECT name, summary, comm_lv FROM community_llm_results "
            "WHERE task_id=? AND edge_type=? AND comm_id=?",
            (task_id, et, comm_id),
        )
        if row:
            return {
                "commId": comm_id,
                "name": row["name"],
                "summary": row["summary"],
                "level": row["comm_lv"],
                "edgeType": et,
                "found": True,
            }
        return {
            "commId": comm_id,
            "edgeType": et,
            "found": False,
            "message": "该社区尚无 LLM 分析结果",
        }

    def _get_community_graph(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        comm_id = args.get("commId", "")
        et = (args.get("edgeType") or "UNIFIED").upper()
        depth = int(args.get("depth", 1))
        gran = (args.get("gran") or "component").lower()
        pid, pdb = self._resolve_task(task_id)
        proj = self.multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj["root_path"].replace('\\', '/') + "/") if proj and proj["root_path"] else ""

        inferred = cd._infer_edge_type(comm_id)
        if inferred:
            et = inferred

        if gran == "component":
            result = cd.get_community_graph_component(
                pdb, task_id, et, '', comm_id, project_root, depth=depth
            )
        else:
            result = cd.get_community_graph_file(
                pdb, task_id, et, '', comm_id, project_root
            )
        # 若 file 粒度无结果，回退到 component 粒度
        if gran != "component" and _is_empty_result(result):
            result = cd.get_community_graph_component(
                pdb, task_id, et, '', comm_id, project_root, depth=depth
            )
        return result

    @staticmethod
    def _bad_id(v) -> bool:
        s = str(v).strip()
        return not s or s == 'None'

    @staticmethod
    def _normalize_path(p: str) -> str:
        p = p.replace("\\", "/")
        if p.startswith("file:"):
            p = p[5:]
        return p

    def _get_community_files(self, args: dict) -> dict:
        """列出社区包含的源码文件。
        UNIFIED 社区: node_list 为文件路径字符串列表。
        CALL 社区: node_list 为符号节点 [id 或 {id, ...}]，id 可能为文件路径或符号 hash。
        """
        task_id = args.get("taskId", "")
        comm_id = args.get("commId", "")
        et = (args.get("edgeType") or "UNIFIED").upper()
        inferred = cd._infer_edge_type(comm_id)
        if inferred:
            et = inferred
        pid, pdb = self._resolve_task(task_id)
        proj = self.multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj["root_path"].replace('\\', '/') + "/") if proj and proj["root_path"] else ""

        rows = pdb.fetchall(
            "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id=?",
            (task_id, et, comm_id),
        )
        if not rows:
            return {"files": [], "total": 0}
        seen = set()
        files = []
        for r in rows:
            try:
                nodes = json.loads(r["node_list"]) if isinstance(r["node_list"], str) else r["node_list"] or []
            except Exception:
                nodes = []
            if not isinstance(nodes, list):
                nodes = [nodes]
            for n in nodes:
                if et == "CALL":
                    nid = str(n) if isinstance(n, str) else str(n.get("id", ""))
                else:
                    nid = str(n) if isinstance(n, str) else str(n.get("path", n.get("id", "")))
                if self._bad_id(nid):
                    continue
                fp = self._normalize_path(nid)
                fp = fp.split(':')[0] if ':' in fp else fp
                if project_root and fp.lower().startswith(project_root.lower()):
                    fp = fp[len(project_root):]
                fp = fp.lstrip("/")
                if fp and fp not in seen:
                    seen.add(fp)
                    files.append({
                        "path": fp,
                        "name": fp.split("/")[-1],
                    })
        return {"files": files, "total": len(files)}

    def _read_file(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        path = args.get("path", "")
        task_id = args.get("taskId", "")
        proj = self.multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        if not proj:
            return {"error": f"Project {pid} not found"}
        root = proj["root_path"]
        full = os.path.normpath(os.path.join(root, path))
        if os.path.commonpath([full, os.path.normpath(root)]) != os.path.normpath(root):
            return {"error": "Path outside project root"}
        if not os.path.isfile(full):
            return {"error": f"File not found: {path}"}

        # 获取文件基本信息
        total_lines = 0
        try:
            with open(full, "rb") as f:
                total_lines = sum(1 for _ in f)
        except Exception:
            pass
        file_size = os.path.getsize(full)

        # 查询 graph_node 中的符号信息
        pdb = self.multi_db.get_project_db(pid)
        symbols = []
        if task_id:
            rows = pdb.fetchall(
                "SELECT name, kind, signature, docstring, start_line, end_line "
                "FROM graph_node WHERE file_path=? AND task_id=? ORDER BY start_line",
                (path, task_id),
            )
            symbols = rows
        else:
            # 如果没有指定 taskId，按项目下的任务顺序查找
            tasks = self.multi_db.main_db.fetchall(
                "SELECT id FROM analysis_tasks WHERE project_id=? ORDER BY created_at DESC",
                (pid,),
            )
            for t in tasks:
                rows = pdb.fetchall(
                    "SELECT name, kind, signature, docstring, start_line, end_line "
                    "FROM graph_node WHERE file_path=? AND task_id=? ORDER BY start_line",
                    (path, t["id"]),
                )
                if rows:
                    symbols = rows
                    task_id = t["id"]
                    break

        if symbols:
            # 构建符合列表
            overview_lines = []
            for s in symbols:
                name = s["name"]
                kind = s["kind"]
                sl = s["start_line"]
                el = s["end_line"]
                sig = (s["signature"] or "")[:120]
                entry = f"  [{kind}] {name}  L{sl}-L{el}"
                if sig:
                    entry += f"  {sig}"
                overview_lines.append(entry)
            overview = "\n".join(overview_lines)

            # 提取符号行号范围，去重合并重叠/相邻区间（跳过覆盖全文件的 file 级别符号）
            raw_ranges = []
            for s in symbols:
                if s["kind"] == "file":
                    continue
                sl, el = s["start_line"], s["end_line"]
                if sl and el and el >= sl:
                    raw_ranges.append((sl, el))
            raw_ranges.sort()
            merged = []
            for sl, el in raw_ranges:
                if merged and sl <= merged[-1][1] + 2:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], el))
                else:
                    merged.append((sl, el))

            # 读文件到列表
            file_lines = []
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    file_lines = f.readlines()
            except Exception:
                pass

            # 拼接代码片段
            MAX_CODE_LINES = 600
            MAX_SYMBOLS_WITH_CODE = 40
            MAX_LINES_PER_RANGE = 60
            code_output = []
            code_total = 0
            prev_end = 0
            ranges_shown = 0
            for sl, el in merged:
                if ranges_shown >= MAX_SYMBOLS_WITH_CODE or code_total >= MAX_CODE_LINES:
                    break
                # 省略标记
                if prev_end and sl > prev_end + 1:
                    code_output.append(f"// ... 省略 L{prev_end+1}-L{sl-1}")
                elif prev_end and sl == prev_end + 1:
                    code_output.append(f"// ... 省略 L{prev_end+1}")
                # 每区间限行数
                limit = min(el, sl + MAX_LINES_PER_RANGE - 1)
                for lineno in range(sl, limit + 1):
                    if code_total >= MAX_CODE_LINES:
                        break
                    if lineno - 1 < len(file_lines):
                        code_output.append(f"L{lineno}: {file_lines[lineno-1].rstrip()}")
                    code_total += 1
                if limit < el:
                    code_output.append(f"// ... 符号超出 {MAX_LINES_PER_RANGE} 行显示上限，剩余 L{limit+1}-L{el} 行省略")
                prev_end = el
                ranges_shown += 1
            remaining = len(merged) - ranges_shown
            if remaining > 0:
                code_output.append(f"// ... 剩余 {remaining} 个符号的代码已省略，如需查看请使用 web_read_file_lines")

            code_block = "\n".join(code_output) if code_output else "(无代码内容)"
            result = (
                f"文件: {path} ({file_size} bytes, {total_lines} 行)\n"
                f"符号数量: {len(symbols)}\n"
                f"符号概览:\n{overview}\n\n"
                f"代码片段:\n{code_block}\n\n"
                f"提示: 如需阅读其他行，请使用 web_read_file_lines 按行号读取。"
            )
            return {"path": path, "summary": True, "content": result, "size": file_size, "lines": total_lines, "symbol_count": len(symbols)}
        else:
            # 无符号信息时，回退读取前 100 行作为概览
            preview_lines = []
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f):
                        if i >= 100:
                            break
                        preview_lines.append(f"{i+1}: {line}")
            except Exception:
                pass
            preview = "".join(preview_lines)
            note = "(无解析符号，以下为文件前 100 行预览)"
            if not preview:
                preview = "(文件为空或无法读取)"
            result = f"文件: {path} ({file_size} bytes, {total_lines} 行)\n{note}\n{preview}"
            return {"path": path, "summary": True, "content": result, "size": file_size, "lines": total_lines, "symbol_count": 0}

    def _read_file_lines(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        path = args.get("path", "")
        start_line = int(args.get("startLine", 1))
        end_line = int(args.get("endLine", 10))
        proj = self.multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        if not proj:
            return {"error": f"Project {pid} not found"}
        root = proj["root_path"]
        full = os.path.normpath(os.path.join(root, path))
        if os.path.commonpath([full, os.path.normpath(root)]) != os.path.normpath(root):
            return {"error": "Path outside project root"}
        if not os.path.isfile(full):
            return {"error": f"File not found: {path}"}
        if start_line < 1:
            start_line = 1
        if end_line < start_line:
            end_line = start_line
        lines = []
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    lineno = i + 1
                    if lineno > end_line:
                        break
                    if lineno >= start_line:
                        lines.append({"lineNo": lineno, "content": line.rstrip("\n\r")})
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}
        content = "\n".join(f"{l['lineNo']}: {l['content']}" for l in lines)
        return {
            "path": path, "startLine": start_line, "endLine": end_line,
            "content": content, "lines_returned": len(lines),
        }

    def _get_file_summary(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        path = args.get("path", "")
        pid, pdb = self._resolve_task(task_id)
        row = pdb.fetchone(
            "SELECT summary, summary_len, source FROM file_summaries "
            "WHERE project_id=? AND file_path=? ORDER BY created_at DESC LIMIT 1",
            (pid, path),
        )
        if row:
            return {"found": True, "summary": row["summary"], "source": row["source"]}
        return {"found": False, "message": "该文件尚无预摘要"}

    def _search_symbols(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        query = args.get("query", "")
        limit = int(args.get("limit", 20))
        pdb = self.multi_db.get_project_db(pid)
        rows = pdb.fetchall(
            "SELECT id, file_path, func_name, class_name, method_name, symbol_type FROM graph_node "
            "WHERE func_name LIKE ? OR class_name LIKE ? OR method_name LIKE ? "
            "OR file_path LIKE ? LIMIT ?",
            (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", limit),
        )
        return {
            "symbols": [
                {
                    "id": r["id"],
                    "filePath": r["file_path"],
                    "name": r["func_name"] or r["class_name"] or r["method_name"] or r["file_path"],
                    "type": r["symbol_type"],
                }
                for r in rows
            ],
            "total": len(rows),
        }

    def _get_symbol_detail(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        symbol_id = args.get("symbolId", "")
        pdb = self.multi_db.get_project_db(pid)
        row = pdb.fetchone(
            "SELECT id, file_path, func_name, class_name, method_name, symbol_type,"
            " docstring, line_start, line_end FROM graph_node WHERE id = ?",
            (symbol_id,),
        )
        if not row:
            return {"error": f"Symbol {symbol_id} not found"}
        return {
            "id": row["id"],
            "filePath": row["file_path"],
            "name": row["func_name"] or row["class_name"] or row["method_name"] or "",
            "type": row["symbol_type"],
            "docstring": row["docstring"],
            "lineStart": row["line_start"],
            "lineEnd": row["line_end"],
        }

    def _get_call_chain(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        symbol = args.get("symbol", "")
        depth = int(args.get("depth", 2))
        pdb = self.multi_db.get_project_db(pid)
        kind = "calls"
        rows = pdb.fetchall(
            "SELECT e.source_id, e.target_id, n1.func_name AS src_name, "
            "n2.func_name AS tgt_name, n1.file_path AS src_file, n2.file_path AS tgt_file "
            "FROM graph_edge e "
            "LEFT JOIN graph_node n1 ON e.source_id = n1.id "
            "LEFT JOIN graph_node n2 ON e.target_id = n2.id "
            "WHERE e.task_id IN (SELECT id FROM analysis_tasks WHERE project_id=?) "
            "AND e.kind=?",
            (pid, kind),
        )
        callers = []
        callees = []
        for r in rows:
            if symbol.lower() in (r["src_name"] or "").lower():
                callees.append({
                    "from": r["src_name"] or r["source_id"],
                    "to": r["tgt_name"] or r["target_id"],
                    "toFile": r["tgt_file"],
                })
            if symbol.lower() in (r["tgt_name"] or "").lower():
                callers.append({
                    "from": r["src_name"] or r["source_id"],
                    "fromFile": r["src_file"],
                    "to": r["tgt_name"] or r["target_id"],
                })
        return {
            "symbol": symbol,
            "callers": callers[:depth * 10],
            "callees": callees[:depth * 10],
        }

    def _search_archives(self, args: dict) -> dict:
        query = args.get("query", "")
        project_id = args.get("projectId", "")
        category = args.get("category", "")
        wheres = ["content LIKE ? OR title LIKE ?"]
        params = [f"%{query}%", f"%{query}%"]
        if project_id:
            wheres.append("project_id = ?")
            params.append(project_id)
        if category:
            wheres.append("category = ?")
            params.append(category)
        sql = f"SELECT id, title, content, category, tags, created_at FROM chat_archives WHERE {' AND '.join(wheres)} ORDER BY created_at DESC LIMIT 20"
        rows = self.multi_db.chat_db.fetchall(sql, tuple(params))
        return {
            "archives": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "content": r["content"][:500],
                    "category": r["category"],
                    "tags": r["tags"],
                    "createdAt": r["created_at"],
                }
                for r in rows
            ],
            "total": len(rows),
        }

    def _save_archive(self, args: dict) -> dict:
        import uuid
        aid = f"arch_{uuid.uuid4().hex[:12]}"
        title = args.get("title", "")
        content = args.get("content", "")
        session_id = args.get("sessionId", "")
        category = args.get("category", "note")
        tags = args.get("tags", "")
        pid = None
        if session_id:
            row = self.multi_db.chat_db.fetchone(
                "SELECT json_extract(metadata, '$.project_id') AS pid FROM llm_sessions WHERE id = ?",
                (session_id,),
            )
            if row:
                pid = row["pid"]
        self.multi_db.chat_db.execute(
            "INSERT INTO chat_archives (id, session_id, project_id, title, content, category, tags, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'manual')",
            (aid, session_id, pid, title, content, category, tags),
        )
        return {"id": aid, "ok": True}

    def _search_conversation_history(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("session_id", self._current_session_id or ""))
        query = args.get("query", "")
        limit = min(args.get("limit", 10), 50)

        # 空 query + 指定 session_id：返回该会话的全部消息（LLM 试探会话内容）
        if not query and session_id:
            try:
                rows = self.multi_db.chat_db.fetchall(
                    "SELECT role, content, created_at FROM llm_messages "
                    "WHERE session_id = ? ORDER BY created_at LIMIT 50",
                    (session_id,),
                )
                if not rows:
                    return {"found": False, "results": [], "total": 0, "message": "会话无消息记录"}
                results = []
                for r in rows:
                    c = (r["content"] or "")[:800]
                    if c:
                        results.append({
                            "role": r["role"],
                            "content": c,
                            "createdAt": r["created_at"],
                        })
                return {"found": True, "results": results, "total": len(results)}
            except Exception as e:
                return {"error": str(e), "skip": True}

        if not query:
            return {"error": "query is required", "skip": True}

        try:
            rows = self.multi_db.chat_db.fetchall(
                "SELECT role, content, created_at FROM llm_messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') "
                "AND content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (session_id, f"%{query}%", limit),
            )
            results = []
            for r in rows:
                c = (r["content"] or "")[:800]
                if c:
                    results.append({
                        "role": r["role"],
                        "content": c,
                        "createdAt": r["created_at"],
                    })
            return {"found": len(results) > 0, "results": results, "total": len(results)}
        except Exception as e:
            return {"error": str(e), "skip": True}

    def _set_session_title(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("sessionId", ""))
        title = args.get("title", "").strip()
        if not session_id or not title:
            return {"error": "sessionId and title are required", "skip": True}
        title = title[:20]
        from datetime import datetime as _dt
        now = _dt.now().isoformat()
        self.multi_db.chat_db.execute(
            "UPDATE llm_sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, session_id),
        )
        return {"ok": True, "title": title}

    # ── conversation_analyst tools ──

    def _list_sessions(self, args: dict) -> dict:
        project_id = args.get("project_id", "")
        status = args.get("status", "")
        limit = min(args.get("limit", 20), 100)
        offset = args.get("offset", 0)
        where = []
        params = []
        if project_id:
            where.append("project_id = ?"); params.append(project_id)
        if status:
            where.append("status = ?"); params.append(status)
        w = (" WHERE " + " AND ".join(where)) if where else ""
        rows = self.multi_db.chat_db.fetchall(
            f"SELECT id, title, project_id, status, metadata, created_at, updated_at "
            f"FROM llm_sessions{w} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return {"sessions": [
            {"id": r["id"], "title": r["title"], "projectId": r["project_id"],
             "status": r["status"], "createdAt": r["created_at"], "updatedAt": r["updated_at"]}
            for r in rows
        ], "total": len(rows)}

    def _get_session_info(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("session_id", ""))
        if not session_id:
            return {"error": "session_id is required", "skip": True}
        row = self.multi_db.chat_db.fetchone(
            "SELECT id, title, project_id, status, metadata, created_at, updated_at "
            "FROM llm_sessions WHERE id = ?", (session_id,)
        )
        if not row:
            return {"error": "Session not found", "skip": True}
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        cnt = self.multi_db.chat_db.fetchone(
            "SELECT COUNT(*) AS c FROM llm_messages WHERE session_id = ?", (session_id,)
        )
        return {
            "id": row["id"], "title": row["title"],
            "projectId": row["project_id"], "status": row["status"],
            "modelId": meta.get("model_id", ""),
            "activeSkills": meta.get("active_skills", []),
            "messageCount": cnt["c"] if cnt else 0,
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        }

    def _search_across_sessions(self, args: dict) -> dict:
        query = args.get("query", "")
        if not query:
            return {"error": "query is required", "skip": True}
        project_id = args.get("project_id", "")
        limit = min(args.get("limit", 5), 20)
        session_limit = min(args.get("session_limit", 10), 50)
        where = "1=1"
        params = []
        if project_id:
            where += " AND project_id = ?"; params.append(project_id)
        sessions = self.multi_db.chat_db.fetchall(
            f"SELECT id, title FROM llm_sessions WHERE {where} ORDER BY created_at DESC LIMIT ?",
            (*params, session_limit),
        )
        results = []
        for s in sessions:
            rows = self.multi_db.chat_db.fetchall(
                "SELECT role, content, created_at FROM llm_messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') "
                "AND content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (s["id"], f"%{query}%", limit),
            )
            for r in rows:
                c = (r["content"] or "")[:600]
                if c:
                    results.append({
                        "session_id": s["id"],
                        "session_title": s["title"],
                        "role": r["role"], "content": c,
                        "createdAt": r["created_at"],
                    })
        return {"found": len(results) > 0, "results": results, "total": len(results)}

    def _get_session_messages(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("session_id", ""))
        if not session_id:
            return {"error": "session_id is required", "skip": True}
        role = args.get("role", "all")
        limit = min(args.get("limit", 50), 200)
        offset = args.get("offset", 0)
        where = "session_id = ?"
        params = [session_id]
        if role and role != "all":
            where += " AND role = ?"; params.append(role)
        rows = self.multi_db.chat_db.fetchall(
            f"SELECT id, role, content, metadata, created_at FROM llm_messages "
            f"WHERE {where} ORDER BY created_at LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return {"messages": [
            {"id": r["id"], "role": r["role"], "content": (r["content"] or "")[:2000],
             "createdAt": r["created_at"]}
            for r in rows
        ], "total": len(rows)}

    def _summarize_session(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("session_id", ""))
        if not session_id:
            return {"error": "session_id is required", "skip": True}
        max_length = min(args.get("max_length", 500), 2000)
        rows = self.multi_db.chat_db.fetchall(
            "SELECT role, content FROM llm_messages "
            "WHERE session_id = ? AND role IN ('user', 'assistant') "
            "ORDER BY created_at LIMIT 100",
            (session_id,),
        )
        if not rows:
            return {"found": False, "summary": "会话无消息记录"}
        conv_text = "\n".join(
            f"[{'用户' if r['role']=='user' else 'AI'}] {(r['content'] or '')[:2000]}"
            for r in rows
        )
        return {"found": True, "summary": f"会话 {session_id[:12]}：\n{conv_text[:max_length * 4]}",
                "message_count": len(rows)}

    def _extract_topics(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("session_id", ""))
        if not session_id:
            return {"error": "session_id is required", "skip": True}
        detail = args.get("detail", "brief")
        rows = self.multi_db.chat_db.fetchall(
            "SELECT role, content, metadata FROM llm_messages "
            "WHERE session_id = ? AND role IN ('user', 'assistant') "
            "ORDER BY created_at LIMIT 100",
            (session_id,),
        )
        topics = set()
        resources = set()
        for r in rows:
            content = r["content"] or ""
            for kw in ["struct ", "class ", "function ", "module ", "社区", "文件", "协议", "驱动"]:
                if kw in content:
                    topics.add(kw.rstrip())
                    break
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
            for tc in meta.get("tool_calls", []):
                if tc.get("name"):
                    resources.add(tc["name"])
        return {
            "found": True,
            "topics": list(topics) if detail == "brief" else list(topics)[:10],
            "resources": list(resources)[:10],
            "message_count": len(rows),
        }

    def _compare_sessions(self, args: dict) -> dict:
        session_ids_str = args.get("session_ids", "")
        ids = [s.strip() for s in session_ids_str.split(",") if s.strip()]
        if len(ids) < 2:
            return {"error": "至少需要两个会话ID", "skip": True}
        aspect = args.get("aspect", "topic")
        sessions_info = []
        for sid in ids[:5]:
            row = self.multi_db.chat_db.fetchone(
                "SELECT title FROM llm_sessions WHERE id = ?", (sid.strip(),)
            )
            title = row["title"] if row else sid[:12]
            cnt = self.multi_db.chat_db.fetchone(
                "SELECT COUNT(*) AS c FROM llm_messages WHERE session_id = ?", (sid.strip(),)
            )
            sessions_info.append({"id": sid.strip(), "title": title, "messageCount": cnt["c"] if cnt else 0})
        return {"found": True, "aspect": aspect, "sessions": sessions_info}

    # ── knowledge_keeper enhanced tools ──

    def _list_archives(self, args: dict) -> dict:
        project_id = args.get("project_id", "")
        category = args.get("category", "")
        tag = args.get("tag", "")
        limit = min(args.get("limit", 20), 100)
        offset = args.get("offset", 0)
        where = []
        params = []
        if project_id:
            where.append("project_id = ?"); params.append(project_id)
        if category:
            where.append("category = ?"); params.append(category)
        if tag:
            where.append("tags LIKE ?"); params.append(f"%{tag}%")
        w = (" WHERE " + " AND ".join(where)) if where else ""
        rows = self.multi_db.chat_db.fetchall(
            f"SELECT id, session_id, project_id, title, content, category, tags, source, created_at "
            f"FROM chat_archives{w} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return {"archives": [{
            "id": r["id"], "title": r["title"], "category": r["category"],
            "tags": r["tags"], "content": (r["content"] or "")[:500],
            "createdAt": r["created_at"],
        } for r in rows], "total": len(rows)}

    def _delete_archive(self, args: dict) -> dict:
        archive_id = args.get("archive_id", "")
        if not archive_id:
            return {"error": "archive_id is required", "skip": True}
        self.multi_db.chat_db.execute("DELETE FROM chat_archives WHERE id = ?", (archive_id,))
        return {"ok": True, "deleted": archive_id}

    def _update_archive(self, args: dict) -> dict:
        archive_id = args.get("archive_id", "")
        if not archive_id:
            return {"error": "archive_id is required", "skip": True}
        updates = []
        params = []
        if args.get("category"):
            updates.append("category = ?"); params.append(args["category"])
        if "tags" in args:
            updates.append("tags = ?"); params.append(args.get("tags", ""))
        if not updates:
            return {"error": "没有要更新的字段", "skip": True}
        params.append(archive_id)
        self.multi_db.chat_db.execute(
            f"UPDATE chat_archives SET {', '.join(updates)} WHERE id = ?", params
        )
        return {"ok": True}

    def _search_knowledge(self, args: dict) -> dict:
        q = args.get("search", "")
        type_filter = args.get("types", []) or []
        pid = args.get("project_id", "") or ""
        limit = min(int(args.get("limit", 10)), 30)
        results = []
        if not q:
            return {"results": [], "total": 0}

        # L1: 用户存档文档 (knowledge_docs)
        if not type_filter or "user_doc" in type_filter:
            try:
                rows = self.multi_db.knowledge_db.fetchall(
                    "SELECT id, title, description AS snippet, updated_at, project_id FROM knowledge_docs "
                    "WHERE (id LIKE ? OR title LIKE ? OR content LIKE ?) ORDER BY created_at DESC LIMIT ?",
                    (f"%{q}%", f"%{q}%", f"%{q}%", limit)
                )
                for r in rows:
                    results.append({"source_type": "user_doc", "source_label": "用户存档文档",
                        "id": r["id"], "title": r["title"] or "", "snippet": (r["snippet"] or "")[:200],
                        "project_id": r["project_id"] or "", "updated_at": r["updated_at"] or ""})
            except Exception:
                pass

        # L1: 对话归档 (chat_archives)
        if not type_filter or "archive" in type_filter:
            try:
                rows = self.multi_db.chat_db.fetchall(
                    "SELECT id, title, content, category, created_at, project_id FROM chat_archives "
                    "WHERE (id LIKE ? OR title LIKE ? OR content LIKE ?) ORDER BY created_at DESC LIMIT ?",
                    (f"%{q}%", f"%{q}%", f"%{q}%", limit)
                )
                for r in rows:
                    results.append({"source_type": "archive", "source_label": "对话归档",
                        "id": r["id"], "title": r["title"] or r["category"] or "", "snippet": (r["content"] or "")[:200],
                        "project_id": r["project_id"] or "", "updated_at": r["created_at"] or ""})
            except Exception:
                pass

        # L2: 社区分析 / 架构报告（需 project_id）
        if pid and (not type_filter or "community_analysis" in type_filter or "report" in type_filter):
            try:
                project_db = self.multi_db.get_project_db(pid)
            except Exception:
                project_db = None
            if project_db:
                # 社区分析
                if not type_filter or "community_analysis" in type_filter:
                    try:
                        rows = project_db.fetchall(
                            "SELECT comm_id AS id, name AS title, summary AS snippet, created_at, task_id FROM community_llm_results "
                            "WHERE (comm_id LIKE ? OR name LIKE ? OR summary LIKE ?) ORDER BY created_at DESC LIMIT ?",
                            (f"%{q}%", f"%{q}%", f"%{q}%", limit)
                        )
                        for r in rows:
                            results.append({"source_type": "community_analysis", "source_label": "社区分析报告",
                                "id": r["id"], "title": r["title"] or "", "snippet": (r["snippet"] or "")[:200],
                                "project_id": pid, "updated_at": r["created_at"] or ""})
                    except Exception:
                        pass
                # 架构报告
                if not type_filter or "report" in type_filter:
                    try:
                        rows = project_db.fetchall(
                            "SELECT id, title, content AS snippet, created_at, comm_id FROM report_subdocs "
                            "WHERE (id LIKE ? OR title LIKE ? OR content LIKE ?) ORDER BY created_at DESC LIMIT ?",
                            (f"%{q}%", f"%{q}%", f"%{q}%", limit)
                        )
                        for r in rows:
                            results.append({"source_type": "report", "source_label": "架构分析报告",
                                "id": r["id"], "title": r["title"] or "", "snippet": (r["snippet"] or "")[:200],
                                "project_id": pid, "updated_at": r["created_at"] or ""})
                    except Exception:
                        pass

        results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return {"results": results[:limit], "total": len(results)}

    def _get_document(self, args: dict) -> dict:
        doc_id = args.get("doc_id", "")
        if not doc_id:
            return {"error": "doc_id is required", "_skip": True}
        try:
            row = self.multi_db.knowledge_db.fetchone(
                "SELECT id, title, content, project_id, tags, created_at, updated_at FROM knowledge_docs WHERE id = ?",
                (doc_id,)
            )
            if not row:
                return {"error": f"Document {doc_id} not found", "_skip": True}
            return {"doc": dict(row)}
        except Exception as e:
            return {"error": str(e), "_skip": True}

    # ── Diagram Tools ──

    def _diagram_build(self, args: dict) -> dict:
        ir = args.get("ir")
        if not ir:
            return {"error": "ir is required", "_skip": True}
        try:
            from topoone.diagram import build_from_ir, is_legacy_ir, schema_to_legacy_ir
            from topoone.diagram.validation import validate_schema_document
            from topoone.diagram._ir_schema import validate_ir
            from topoone.diagram._validator import validate_diagram_syntax

            if is_legacy_ir(ir):
                legacy, lang = ir, ir.get("lang", "mermaid")
                dt = ir.get("diagram_type", "")
                valid_schema, schema_errors = validate_ir(ir, dt) if dt else (True, [])
                if not valid_schema:
                    return {"error": f"IR schema validation failed: {schema_errors[:3]}", "_skip": True}
            else:
                report = validate_schema_document(ir)
                if not report["ok"]:
                    codes = [e["code"] for e in report["errors"]][:3]
                    return {"error": f"DiagramSchema validation failed: {codes}", "_skip": True}
                legacy = schema_to_legacy_ir(ir)
                lang = ir.get("lang") or legacy.get("lang", "mermaid")

            result = build_from_ir(legacy)
            if "error" in result:
                return {"error": result["error"], "_skip": True}
            validation = validate_diagram_syntax(result["code"], lang)
            modified_nodes = sum(1 for n in (legacy.get("nodes") or []) if n.get("_is_modified"))
            modified_edges = sum(1 for e in (legacy.get("edges") or []) if e.get("_is_modified"))
            resp: dict = {
                "code": result["code"],
                "type": result["type"],
                "validation": validation,
                "_tool_generated": True,
                "edit_summary": {
                    "modified_nodes": modified_nodes,
                    "modified_edges": modified_edges,
                },
            }
            if not validation["valid"]:
                resp["warning"] = "生成的代码存在语法问题，建议检查"
            return resp
        except Exception as e:
            return {"error": f"Build failed: {e}", "_skip": True}

    def _diagram_validate(self, args: dict) -> dict:
        code = args.get("code", "")
        lang = args.get("lang", "mermaid")
        if not code:
            return {"error": "code is required", "_skip": True}
        try:
            from topoone.diagram._validator import validate_diagram_syntax
            return validate_diagram_syntax(code, lang)
        except Exception as e:
            return {"error": f"Validation failed: {e}", "_skip": True}


# ==================== 引用解析 ====================


