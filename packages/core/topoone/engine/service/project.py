"""project.* 项目/导入命名空间 —— 原 core_service.py 解构（M03 T3.2）。"""
import logging

import asyncio
import time
import json
import os
import re
import shutil
import uuid
from datetime import datetime
from topoone.db.manager import SQLiteContext, MultiDBManager
from topoone.rpc.zmq_server import ZMQServer
from topoone.engine.task_manager import (
    detect_git_info as _tm_detect_git_info,
    save_git_info as _tm_save_git_info,
    get_git_info as _tm_get_git_info,
    check_import_status as _tm_check_import_status,
    save_positions as _tm_save_positions,
    load_positions as _tm_load_positions,
    clear_positions as _tm_clear_positions,
    list_position_keys as _tm_list_position_keys,
)

logger = logging.getLogger(__name__)

from topoone.engine.service._common import _ensure_topocode_dirs_in_gitignore, _simple_hash, _IMPORT_JOBS
import threading
from topoone.engine.service._common import _DELETE_JOBS
def register_project_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册项目管理方法"""
    main_db = multi_db.main_db

    def _refresh_project_storage_stats(project_id: str) -> dict:
        """计算并回写主库 projects 表存储统计缓存列（db_size + source_size）。"""
        return multi_db.refresh_project_storage_stats(project_id)

    @server.register("analysis.parseFileAst")
    def parse_file_ast(file_path: str = None, filePath: str = None, language: str = "",
                       max_bytes: int = 512 * 1024, implDetails: bool = False):
        """只读解析单文件 AST → 符号/imports/refs(**不落库**，供 architect AST 缓存层)。

        file_path 为磁盘绝对路径(读最新源码)；language 缺省按扩展名探测。
        implDetails=True 时追加实现细节(语句级条件/框架路由/常量值/配置键值)。
        复用 `plugins/parsers`(TreeSitterWalker) 成熟解析器；失败返回 {error}。
        """
        fp = file_path or filePath
        if not fp:
            raise ValueError("file_path is required")
        if not os.path.isfile(fp):
            return {"error": f"file not found: {fp}", "filePath": fp}
        try:
            from parsers.core.walker import TreeSitterWalker, _detect_language
            from parsers.core.impl_detail import extract_impl_details, _file_ext, _CONFIG_EXTS
            from parsers.languages import EXTRACTORS
            from parsers.language_loader import get_parser

            lang = (language or "").strip() or (_detect_language(fp) or "")
            is_config = _file_ext(fp) in _CONFIG_EXTS
            if not lang and not is_config:
                return {"error": f"unsupported file type: {fp}", "filePath": fp}
            extractor = EXTRACTORS.get(lang) if lang else None
            parser = get_parser(lang) if lang else None
            if lang and (extractor is None or parser is None):
                return {"error": f"no parser for language: {lang}", "filePath": fp}
            with open(fp, "rb") as fh:
                src_bytes = fh.read()
            if len(src_bytes) > max_bytes:
                return {"error": "file too large", "filePath": fp, "language": lang}
            table = None
            symbols, refs, imports, export_count = [], [], [], 0
            if lang:
                walker = TreeSitterWalker(fp, src_bytes, lang, extractor)
                table = walker.extract()
                # 同符号去重(keep-first): walker 对变量声明存在双路径提取
                # (显式路径+通用遍历), 同 (name,startLine,kind) 重复条目导致
                # 下游(architect 图谱落库/符号统计)重复。keep-first=显式路径
                # 产出的完整作用域链(实证: 重复组第一条 qualified_name 链完整)。
                seen_syms: set = set()
                for n in table.nodes:
                    if getattr(n.kind, "value", str(n.kind)) in ("file", "import", "export"):
                        continue
                    key = (n.name, n.start_line, getattr(n.kind, "value", str(n.kind)))
                    if key in seen_syms:
                        continue
                    seen_syms.add(key)
                    symbols.append({
                        "name": n.name,
                        "kind": getattr(n.kind, "value", str(n.kind)),
                        "qualifiedName": n.qualified_name,
                        "startLine": n.start_line, "endLine": n.end_line,
                        "startCol": n.start_col, "endCol": n.end_col,
                        "signature": n.signature,
                        "visibility": n.visibility,
                        "isExported": n.is_exported, "isAsync": n.is_async,
                        "isStatic": n.is_static, "docstring": n.docstring,
                        "typeParameters": n.type_parameters,
                    })
                refs = [{"name": r.reference_name,
                         "kind": getattr(r.reference_kind, "value", str(r.reference_kind)),
                         "line": r.line, "col": r.col}
                        for r in table.unresolved_refs]
                imports, export_count = table.imports, len(table.exports)
            result = {"filePath": fp, "language": lang,
                      "symbols": symbols, "imports": imports,
                      "refs": refs, "exportCount": export_count}
            if implDetails:
                result["implDetails"] = extract_impl_details(fp, src_bytes, lang, table)
            return result
        except Exception as e:
            logger.warning("[parseFileAst] %s failed: %s", fp, e)
            return {"error": str(e), "filePath": fp}

    @server.register("project.list")
    def list_projects():
        rows = main_db.fetchall("""
            SELECT p.*, COALESCE(dc.done_count, 0) AS done_task_count
            FROM projects p
            LEFT JOIN (
                SELECT project_id, COUNT(*) AS done_count
                FROM analysis_tasks
                WHERE status = 'done'
                GROUP BY project_id
            ) dc ON p.id = dc.project_id
            ORDER BY p.pinned DESC, p.sort_order ASC, p.updated_at DESC
        """)
        # 一次聚合全部项目的所属分组映射，避免 per-row 子查询
        group_map = {}
        try:
            mapping = main_db.fetchall(
                """SELECT m.project_id AS pid, g.id AS gid
                   FROM project_groups g
                   INNER JOIN project_group_map m ON g.id = m.group_id"""
            )
            for r in mapping:
                group_map.setdefault(r["pid"], []).append(r["gid"])
        except Exception:
            group_map = {}
        for row in rows:
            if row.get("tags"):
                row["tags"] = json.loads(row["tags"])
            # 附加项目所属分组 ID 列表
            pid = row.get("id")
            row["groups"] = group_map.get(pid, []) if pid else []
        # 一次性回填：尚无存储统计缓存的老项目（此前版本导入），补齐缓存列。
        for row in rows:
            if not row.get("storage_checked_at") and row.get("id"):
                cached = _refresh_project_storage_stats(row["id"])
                if cached:
                    row["db_size_bytes"] = cached.get("db_size_bytes", 0)
                    row["source_size_bytes"] = cached.get("source_size_bytes", 0)
                    row["storage_checked_at"] = cached.get("storage_checked_at")
        return rows

    @server.register("project.import")
    def import_project(path: str, mode: str = "git-local", branch: str = "",
                       head: str = "", repo_url: str = "",
                       local_repo_path: str = "", init_git: bool = False):
        """导入项目（后台执行，避免大项目阻塞网关 120s 超时）。

        仅支持 git-local / git-remote 两种模式（独立源码目录模式已取消：
        本地目录非 git 仓库时需 init_git=true 授权 TopoCode 自动初始化）。
        立即返回 {requestId, status:"running"}；进度经 `event:project.import.progress`
        推送，结果可用 `project.importStatus(requestId)` 轮询。
        """
        import threading

        mode = (mode or "git-local")
        if mode not in ("git-local", "git-remote"):
            raise ValueError(f"Invalid import mode: {mode}")

        request_id = f"imp-{uuid.uuid4().hex[:8]}"
        _IMPORT_JOBS[request_id] = {"status": "starting", "progress": 0, "phase": "scan", "projectId": ""}
        # 防止注册表无限增长：仅保留最近 100 条
        if len(_IMPORT_JOBS) > 100:
            for k in list(_IMPORT_JOBS.keys())[:-100]:
                _IMPORT_JOBS.pop(k, None)

        def _run():
            import asyncio as _asyncio
            try:
                _asyncio.run(_import_project_impl(
                    server, main_db, multi_db, path, mode, branch, head,
                    repo_url, local_repo_path, request_id, init_git=init_git))
            except Exception as e:
                logger.error(f"[import] background job {request_id} failed: {e}")
                _IMPORT_JOBS[request_id] = {"status": "error", "error": str(e), "progress": 100}
                try:
                    server.publish("project", "import.progress", {
                        "path": path, "progress": 100, "phase": "error", "error": str(e),
                    })
                except Exception:
                    pass

        threading.Thread(target=_run, name=f"import-{request_id}", daemon=True).start()
        return {"requestId": request_id, "status": "running", "importing": True}

    @server.register("project.importStatus")
    def import_status(requestId: str = ""):
        """后台导入任务状态（配合 project.import 后台化）。"""
        if not requestId:
            raise ValueError("requestId is required")
        job = _IMPORT_JOBS.get(requestId)
        if not job:
            return {"status": "unknown"}
        return dict(job)

    @server.register("project.get")
    def get_project(id: str):
        return main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))

    @server.register("project.remove")
    def remove_project(id: str, wait: bool = False):
        """删除项目（后台执行，大项目删除耗时较长）。

        默认后台执行：立即返回 {requestId, status:"deleting"}；
        进度经 `event:project.remove.progress` 推送，可用 `project.removeStatus(requestId)` 轮询。
        阶段: tasks(任务记录) → database(项目库) → source(源码缓存) → record(主库记录)。
        wait=true 时同步执行到底并返回 {deleted: true}（内部调用/测试用）。
        """
        if not id or id == "undefined":
            raise ValueError(f"Invalid project id: {id}")
        row = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))
        if not row:
            raise ValueError(f"Project not found: {id}")
        root_path = row.get("root_path") or ""

        if wait:
            _remove_project_impl(server, main_db, multi_db, id, root_path, "")
            return {"deleted": True}

        request_id = f"del-{uuid.uuid4().hex[:8]}"
        from topoone.engine.service._common import _DELETE_JOBS
        _DELETE_JOBS[request_id] = {
            "status": "starting", "progress": 0, "phase": "prepare", "projectId": id,
        }
        if len(_DELETE_JOBS) > 100:
            for k in list(_DELETE_JOBS.keys())[:-100]:
                _DELETE_JOBS.pop(k, None)

        def _run():
            try:
                _remove_project_impl(server, main_db, multi_db, id, root_path, request_id)
            except Exception as e:
                logger.error(f"[remove] background job {request_id} failed: {e}")
                from topoone.engine.service._common import _DELETE_JOBS as _J
                _J[request_id] = {"status": "error", "error": str(e), "progress": 100, "projectId": id}
                try:
                    server.publish("project", "remove.progress", {
                        "projectId": id, "requestId": request_id,
                        "progress": 100, "phase": "error", "error": str(e),
                    })
                except Exception:
                    pass

        threading.Thread(target=_run, name=f"remove-{request_id}", daemon=True).start()
        return {"requestId": request_id, "status": "deleting", "projectId": id}

    @server.register("project.removeStatus")
    def remove_project_status(requestId: str = ""):
        """项目删除后台任务状态（配合 project.remove 后台化）。"""
        if not requestId:
            raise ValueError("requestId is required")
        from topoone.engine.service._common import _DELETE_JOBS
        job = _DELETE_JOBS.get(requestId)
        if not job:
            return {"status": "unknown"}
        return dict(job)

    @server.register("project.gc")
    def project_gc(confirm: bool = False):
        """孤儿项目清扫：注册表(projects)无记录、但残留主库行/项目库目录/
        源码镜像的 pid。默认 dry-run 只返回报告; confirm=true 物理执行
        (与 project.remove 同口径级联)。在途导入/删除作业的 pid 自动跳过。"""
        from topoone.engine.service._common import _IMPORT_JOBS, _DELETE_JOBS
        busy = {j.get("projectId") for j in
                list(_IMPORT_JOBS.values()) + list(_DELETE_JOBS.values())
                if isinstance(j, dict) and j.get("projectId")}
        pids = _gc_orphan_pids(main_db, multi_db, busy=busy)
        report = {"orphans": pids, "purged": None, "taskOrphans": None}
        if confirm:
            purged = {}
            for p in pids:
                try:
                    purged[p] = _gc_purge_project(main_db, multi_db, p)
                except Exception as e:
                    purged[p] = {"error": str(e)}
            report["purged"] = purged
            report["taskOrphans"] = _gc_purge_task_orphans(main_db)
            logger.info("[project.gc] purged %d orphan(s): %s", len(pids), list(pids))
        return report

    @server.register("project.updateMeta")
    def update_project_meta(id: str, **kwargs):
        """更新项目元数据 (group, favorite, pinned, sort_order, name)"""
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))
        if not project:
            raise ValueError(f"Project not found: {id}")

        allowed = {"group", "favorite", "pinned", "sort_order", "name"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if updates:
            updates["updated_at"] = datetime.now().isoformat()
            main_db.update("projects", updates, "id = ?", (id,))

        return main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))

    @server.register("project.sync")
    async def sync_project(id: str):
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))
        if not project:
            raise ValueError(f"Project not found: {id}")

        main_db.update("projects", {"status": "syncing", "updated_at": datetime.now().isoformat()}, "id = ?", (id,))
        server.publish("project", "syncing", {"projectId": id, "progress": 0})

        project_db = multi_db.get_project_db(id)
        root_path = project["root_path"]

        # 先把镜像 fast-forward 到源 HEAD——否则变更检查(源 vs 镜像)永远
        # 残留旧差异, 「更新」形同虚设。ff 失败(分叉/冲突)不阻塞重扫, 仅提示。
        mirror_updated = ""
        try:
            from topoone.engine import git_service
            if os.path.isdir(root_path) and git_service.is_git_repo(root_path):
                mirror_head = git_service.rev_parse(root_path, "HEAD")
                source_repo = project.get("local_repo_path") or ""
                branch = project.get("branch") or git_service.current_branch(root_path)
                source_head = ""
                if source_repo and os.path.isdir(source_repo) and git_service.is_git_repo(source_repo):
                    try:
                        source_head = git_service.rev_parse(source_repo, "HEAD")
                    except Exception:  # noqa: BLE001
                        source_head = ""
                if not source_head:
                    try:
                        git_service.fetch(root_path, timeout=300)
                        source_head = git_service.rev_parse(
                            root_path, f"origin/{branch}" if branch else "origin/HEAD")
                    except Exception:  # noqa: BLE001
                        source_head = ""
                if source_head and mirror_head and source_head != mirror_head:
                    try:
                        _run = git_service._run_git
                        _run(root_path, "fetch", source_repo or "origin", branch or "HEAD", timeout=300)
                        _run(root_path, "merge", "--ff-only", "FETCH_HEAD", timeout=300)
                        mirror_updated = git_service.rev_parse(root_path, "HEAD")
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"[project.sync] mirror fast-forward failed: {e}")
                        mirror_updated = f"ff-failed: {e}"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[project.sync] mirror update skipped: {e}")

        # 清空旧文件
        project_db.execute("DELETE FROM source_files")

        # 重新扫描（git ls-files 是文件清单唯一事实源）
        file_count = _scan_file_tree(project_db, root_path)

        # 重新检测语言（从 source_files 统计最常见语言）
        lang_row = project_db.fetchone(
            "SELECT language, COUNT(*) as cnt FROM source_files WHERE language != 'directory' AND language != '' GROUP BY language ORDER BY cnt DESC LIMIT 1"
        )
        if lang_row:
            lang_key = lang_row["language"]
            # 反向映射: 从 language key 查找显示名
            lang_display_map = {
                "typescript": "TypeScript", "javascript": "JavaScript",
                "python": "Python", "go": "Go", "rust": "Rust", "java": "Java",
                "c": "C", "cpp": "C++", "c_sharp": "C#",
                "ruby": "Ruby", "php": "PHP", "swift": "Swift", "kotlin": "Kotlin",
                "scala": "Scala", "dart": "Dart", "lua": "Lua", "luau": "Luau",
                "objc": "Objective-C",
                "vue": "Vue", "html": "HTML", "css": "CSS", "scss": "SCSS",
                "json": "JSON", "markdown": "Markdown", "yaml": "YAML", "toml": "TOML",
                "r": "R", "sql": "SQL", "bash": "Bash",
                "perl": "Perl", "elixir": "Elixir", "erlang": "Erlang",
                "haskell": "Haskell", "ocaml": "OCaml",
                "zig": "Zig", "nim": "Nim", "verilog": "Verilog",
            }
            language = lang_display_map.get(lang_key, lang_key.capitalize())
        else:
            language = "Unknown"

        main_db.update("projects", {
            "file_count": file_count,
            "language": language,
            "status": "synced",
            "last_sync": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "has_file_changes": 0,
        }, "id = ?", (id,))
        if mirror_updated:
            logger.info(f"[project.sync] mirror head -> {mirror_updated[:12]}")

        # 同步后刷新存储统计缓存（源码已重扫）
        _refresh_project_storage_stats(id)

        server.publish("project", "synced", {"projectId": id, "fileCount": file_count})

        return main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))

    @server.register("project.getFileTree")
    def get_file_tree(id: str, fromPath: str = None):
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))
        if not project:
            raise ValueError(f"Project not found: {id}")

        project_db = multi_db.get_project_db(id)

        # 从项目库获取文件（SQLite，非实时文件系统）
        if fromPath and fromPath != "/":
            # 懒加载：只获取指定目录下的直接子节点
            files = project_db.fetchall(
                "SELECT * FROM source_files WHERE file_path LIKE ? AND parent_path = ?",
                (f"{fromPath}/%", fromPath)
            )
        else:
            # 获取根目录
            files = project_db.fetchall(
                "SELECT * FROM source_files WHERE parent_path IS NULL OR parent_path = ''"
            )

        # fromPath 非空时是懒加载，直接返回扁平子节点列表
        if fromPath and fromPath != "/":
            result = _build_flat_children(files, fromPath)
        else:
            # 初始加载也只返回根目录的直接子节点，不递归
            result = _build_file_tree(files, include_children=False)
        return result

    @server.register("project.checkGitRepo")
    def check_git_repo(path: str = ""):
        """检查本地目录是否为 git 仓库（导入弹窗据此提示自动初始化）"""
        if not path or not os.path.isdir(path):
            return {"exists": False, "isGitRepo": False}
        from topoone.engine import git_service
        return {"exists": True, "isGitRepo": git_service.is_git_repo(path)}

    @server.register("project.updatePath")
    def update_path(id: str, newRootPath: str):
        """修改项目根目录，校验相对路径有效性"""
        if not os.path.isdir(newRootPath):
            raise FileNotFoundError(f"Directory not found: {newRootPath}")
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))
        if not project:
            raise ValueError(f"Project not found: {id}")

        project_db = multi_db.get_project_db(id)

        # 校验相对路径有效性
        files = project_db.fetchall("SELECT file_path FROM source_files")
        invalid_files = []
        for f in files:
            full_path = os.path.join(newRootPath, f["file_path"])
            if not os.path.exists(full_path):
                invalid_files.append(f["file_path"])

        # 更新路径
        main_db.update("projects", {
            "root_path": newRootPath,
            "needs_resync": 1 if invalid_files else 0,
            "updated_at": datetime.now().isoformat(),
        }, "id = ?", (id,))
        # 迁移 proj-id 签名到新的根目录（项目库在中心，不受目录移动影响）
        if project.get("root_path") and project["root_path"] != newRootPath:
            multi_db.remove_proj_signature(project["root_path"])
        multi_db.write_proj_signature(newRootPath, id)

        return {
            "project": main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,)),
            "invalidFiles": invalid_files,
            "needsResync": len(invalid_files) > 0,
        }

    @server.register("project.checkFileChanges")
    async def check_file_changes(id: str):
        """检查文件变更（git 核心机制）。

        git 项目（git-local/git-remote）：比较 源仓库/上游 vs 镜像工作副本
        （镜像自身与上次扫描一致是预期，不能自比），返回源侧新增/修改/删除清单。
        """
        import asyncio

        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))
        if not project:
            raise ValueError(f"Project not found: {id}")

        def _git_changes():
            from topoone.engine import git_service
            root = project["root_path"]
            out = {"added": [], "modified": [], "deleted": [], "hasChanges": False,
                   "sourceHead": "", "mirrorHead": "", "branch": project.get("branch") or "",
                   "note": ""}
            if not os.path.isdir(root) or not git_service.is_git_repo(root):
                out["note"] = "mirror-missing"
                return out
            try:
                mirror_head = git_service.rev_parse(root, "HEAD")
            except Exception:
                mirror_head = ""
            try:
                branch = project.get("branch") or git_service.current_branch(root)
            except Exception:
                branch = project.get("branch") or ""
            out["mirrorHead"] = mirror_head
            out["branch"] = branch

            # 优先：本地源仓库 HEAD；否则（git-remote）fetch 上游后取 origin/<branch>
            source = project.get("local_repo_path") or ""
            source_head = ""
            source_repo = ""
            if source and os.path.isdir(source) and git_service.is_git_repo(source):
                try:
                    source_head = git_service.rev_parse(source, "HEAD")
                    source_repo = source
                except Exception as e:
                    logger.warning(f"[checkFileChanges] resolve source HEAD failed: {e}")
            if not source_head:
                try:
                    git_service.fetch(root, timeout=300)
                    ref = f"origin/{branch}" if branch else "origin/HEAD"
                    source_head = git_service.rev_parse(root, ref)
                    source_repo = root
                except Exception as e:
                    logger.warning(f"[checkFileChanges] fetch upstream failed: {e}")
                    out["note"] = "fetch-failed"
                    return out
            out["sourceHead"] = source_head
            if not mirror_head or mirror_head == source_head:
                return out
            try:
                diff = git_service.diff_name_status(source_repo, mirror_head, source_head)
            except Exception as e:
                logger.warning(f"[checkFileChanges] diff failed: {e}")
                out["hasChanges"] = True
                out["note"] = "diff-failed"
                return out
            out.update(diff)
            out["hasChanges"] = bool(diff["added"] or diff["modified"] or diff["deleted"])
            return out

        result = await asyncio.to_thread(_git_changes)

        if result.get("hasChanges"):
            main_db.update("projects", {"has_file_changes": 1}, "id = ?", (id,))

        return result

    @server.register("project.checkPathValidity")
    def check_path_validity(id: str):
        """项目打开时校验路径有效性"""
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))
        if not project:
            raise ValueError(f"Project not found: {id}")

        root_path = project["root_path"]
        path_valid = os.path.isdir(root_path)

        if not path_valid:
            main_db.update("projects", {"needs_resync": 1}, "id = ?", (id,))

        return {
            "pathValid": path_valid,
            "rootPath": root_path,
            "needsResync": not path_valid,
        }

    @server.register("project.getConfig")
    def get_config(project_id: str, key: str):
        """读取项目级配置"""
        project_db = multi_db.get_project_db(project_id)
        row = project_db.fetchone("SELECT value FROM project_config WHERE key = ?", (key,))
        if row and row["value"]:
            return json.loads(row["value"])
        return None

    @server.register("project.setConfig")
    def set_config(project_id: str, key: str, value):
        """写入项目级配置"""
        project_db = multi_db.get_project_db(project_id)
        value_json = json.dumps(value) if not isinstance(value, str) else value
        now = datetime.now().isoformat()

        existing = project_db.fetchone("SELECT id FROM project_config WHERE key = ?", (key,))
        if existing:
            project_db.execute(
                "UPDATE project_config SET value = ?, updated_at = ? WHERE key = ?",
                (value_json, now, key),
            )
        else:
            project_db.execute(
                "INSERT INTO project_config (id, key, value, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (f"cfg-{uuid.uuid4().hex[:8]}", key, value_json, now, now),
            )
            project_db.commit()

        return True

    @server.register("system.exportProject")
    def export_project(projectId: str, taskIds: list = None):
        """导出结构分析数据（JSONL + zip）"""
        import topoone.engine.export_service as export_service
        export_id = export_service.start_export(
            multi_db, projectId, taskIds,
            lambda ch, ev, data: server.publish(ch, ev, data)
        )
        return {"exportId": export_id}

    @server.register("system.exportStatus")
    def export_status(exportId: str):
        import topoone.engine.export_service as export_service
        return export_service.get_export_status(exportId)

    @server.register("system.exportRemoveArchive")
    def export_remove_archive(archivePath: str):
        import topoone.engine.export_service as export_service
        return {"ok": export_service.remove_archive(archivePath)}

    @server.register("system.exportCleanupOld")
    def export_cleanup_old(projectId: str):
        import topoone.engine.export_service as export_service
        export_service.cleanup_old_archives(multi_db, projectId)
        return {"ok": True}

    @server.register("system.importProjectArchive")
    def import_project_archive(archivePath: str, importMode: str = "share",
                               projectId: str = ""):
        """导入结构分析数据包（JSONL zip）

        importMode:
          - "share": 写入当前项目，保留原始 task_id（仅冲突时重映射）
          - "restore": 校验 projectId 一致后覆盖，保留 task_id 和原始状态

        projectId: 导入到的目标项目 ID（share/restore 都需要）

        兼容资源中心快捷操作（Electron 移植，Web 下从卡片菜单触发）：
          - archivePath = "reimport:<resourceId>"   重置资源项目（TOPORES_ID:<id>，清空数据重建成空项目）
          - archivePath = "delete_backup:<resourceId>"  删除资源项目及其备份目录
        """
        import topoone.engine.import_service as import_service
        if archivePath and archivePath.startswith("reimport:"):
            resource_id = archivePath[len("reimport:"):].strip()
            if not resource_id:
                raise ValueError("invalid reimport resourceId")
            return _reset_resource_project(resource_id, create_shell=True)
        if archivePath and archivePath.startswith("delete_backup:"):
            resource_id = archivePath[len("delete_backup:"):].strip()
            if not resource_id:
                raise ValueError("invalid delete_backup resourceId")
            _reset_resource_project(resource_id, create_shell=False)
            return {"ok": True, "deletedBackup": f"TOPORES_ID:{resource_id}"}
        if not projectId:
            raise ValueError("projectId is required")
        logger.info(f"[Import] system.importProjectArchive called: projectId={projectId!r}, importMode={importMode!r}, archivePath={archivePath!r}")
        import_id = import_service.start_import(
            multi_db, archivePath,
            lambda ch, ev, data: server.publish(ch, ev, data),
            import_mode=importMode,
            target_project_id=projectId,
        )
        return {"importId": import_id}

    def _reset_resource_project(resource_id: str, create_shell: bool) -> dict:
        """删除资源项目（TOPORES_ID:<id>）+ 备份目录；create_shell 时重建空项目壳。"""
        project_id = f"TOPORES_ID:{resource_id}"
        existing = main_db.fetchone("SELECT id FROM projects WHERE id = ?", (project_id,))
        if existing:
            try:
                multi_db.delete_project_db(project_id)
            except Exception as e:
                logger.warning(f"[importProjectArchive] delete project db failed: {e}")
            main_db.delete("projects", "id = ?", (project_id,))
        backup_dir = os.path.join(multi_db.data_dir, "resource-projects", resource_id)
        if os.path.exists(backup_dir):
            try:
                shutil.rmtree(backup_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"[importProjectArchive] remove backup dir failed: {e}")

        if not create_shell:
            return {"ok": True, "projectId": project_id}

        # 重建空资源项目（同 resource.importProject 的创建逻辑，无归档数据）
        os.makedirs(backup_dir, exist_ok=True)
        multi_db.init_project_db(project_id, project_root=backup_dir)
        now = datetime.now().isoformat()
        main_db.insert("projects", {
            "id": project_id,
            "name": f"Resource {resource_id}",
            "root_path": backup_dir,
            "language": "",
            "file_count": 0,
            "status": "synced",
            "needs_resync": 0,
            "has_file_changes": 0,
            "is_sample": 0,
            "last_sync": now,
            "storage_checked_at": now,
        })
        _refresh_project_storage_stats(project_id)
        return {"ok": True, "projectId": project_id, "reimport": True}

    @server.register("resource.importProject")
    def resource_import_project(archivePath: str, resourceId: str, name: str = "",
                                resourceProjectsDir: str = ""):
        """资源中心导入：创建项目 + 导入数据

        创建 ID 为 TOPORES_ID:{resourceId} 的项目，然后导入分析数据。
        """
        import topoone.engine.import_service as import_service
        project_id = f"TOPORES_ID:{resourceId}"
        now = datetime.now().isoformat()

        # 检查是否已存在（重复导入 = 重置）
        existing = main_db.fetchone("SELECT id FROM projects WHERE id = ?", (project_id,))
        if existing:
            multi_db.delete_project_db(project_id)
            main_db.delete("projects", "id = ?", (project_id,))

        # 创建项目库（资源项目使用 data_dir 下的 resource-projects/{resourceId}）
        base_dir = resourceProjectsDir or os.path.join(multi_db.data_dir, "resource-projects")
        project_root = os.path.join(base_dir, resourceId)
        os.makedirs(project_root, exist_ok=True)
        multi_db.init_project_db(project_id, project_root=project_root)

        # 写入主库
        main_db.insert("projects", {
            "id": project_id,
            "name": name or f"Resource {resourceId}",
            "root_path": project_root,
            "language": "",
            "file_count": 0,
            "status": "synced",
            "needs_resync": 0,
            "has_file_changes": 0,
            "is_sample": 0,
            "last_sync": now,
        })

        import_id = import_service.start_import(
            multi_db, archivePath,
            lambda ch, ev, data: server.publish(ch, ev, data),
            import_mode="share",
            target_project_id=project_id,
        )
        return {"importId": import_id, "projectId": project_id}

    @server.register("system.importStatus")
    def import_status(importId: str):
        import topoone.engine.import_service as import_service
        return import_service.get_import_status(importId)

    @server.register("system.verifyFiles")
    def verify_files(projectId: str):
        """文件比对校验"""
        from topoone.engine import verify_service
        verify_id = verify_service.start_verify(
            multi_db, projectId,
            lambda ch, ev, data: server.publish(ch, ev, data)
        )
        return {"verifyId": verify_id}

    @server.register("system.verifyStatus")
    def verify_status(verifyId: str):
        from topoone.engine import verify_service
        return verify_service.get_verify_status(verifyId)

    @server.register("project.clearSampleData")
    def clear_sample_data(project_id: str):
        """清除示例项目数据"""
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project or not project.get("is_sample"):
            raise ValueError("Not a sample project")

        # 删除项目库
        multi_db.delete_project_db(project_id)

        # 删除主库中的项目记录
        main_db.delete("projects", "id = ?", (project_id,))

        return {"success": True}

    @server.register("project.getStorageStats")
    def get_storage_stats(project_id: str = None, projectId: str = None):
        """获取项目存储空间统计（DB 文件 + 源码文件）"""
        pid = project_id or projectId
        if not pid:
            raise ValueError("project_id is required")

        # 项目 DB 文件路径（中心路径 data_dir/projects/<pid>/project.db）
        db_path = multi_db.project_db_path(pid)
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

        # WAL / SHM 文件（SQLite WAL 模式）
        wal_size = os.path.getsize(db_path + "-wal") if os.path.exists(db_path + "-wal") else 0
        shm_size = os.path.getsize(db_path + "-shm") if os.path.exists(db_path + "-shm") else 0

        # 源码文件大小之和
        source_size = 0
        try:
            project_db = multi_db.get_project_db(pid)
            if project_db:
                row = project_db.fetchone("SELECT COALESCE(SUM(size), 0) AS s FROM source_files")
                if row:
                    source_size = row.get("s") if isinstance(row, dict) else row[0]
                    source_size = source_size or 0
        except Exception:
            pass

        return {
            "projectId": pid,
            "dbSize": db_size + wal_size + shm_size,
            "dbFileSize": db_size,
            "walSize": wal_size,
            "shmSize": shm_size,
            "sourceSize": source_size,
        }

    # ==================== 项目 Git 信息 ====================

    @server.register("project.detectGitInfo")
    def detect_git_info(project_id: str = None, projectId: str = None):
        pid = project_id or projectId
        if not pid: raise ValueError("project_id is required")
        return _tm_detect_git_info(multi_db, pid)

    @server.register("project.saveGitInfo")
    def save_git_info(project_id: str = None, projectId: str = None,
                      remote_url: str = None, current_branch: str = None,
                      current_commit: str = None, latest_tag: str = None,
                      tags: str = None, branches: str = None, recent_commits: str = None):
        pid = project_id or projectId
        if not pid: raise ValueError("project_id is required")
        return _tm_save_git_info(multi_db, pid, remote_url, current_branch, current_commit,
                                 latest_tag, tags, branches, recent_commits)

    @server.register("project.getGitInfo")
    def get_git_info(project_id: str = None, projectId: str = None):
        pid = project_id or projectId
        if not pid: raise ValueError("project_id is required")
        return _tm_get_git_info(multi_db, pid)

    @server.register("project.checkImportStatus")
    def check_import_status(project_id: str = None, projectId: str = None):
        pid = project_id or projectId
        if not pid: raise ValueError("project_id is required")
        return _tm_check_import_status(multi_db, pid)

    @server.register("project.saveBaseline")
    def save_baseline(project_id: str = None, projectId: str = None,
                      remote_url: str = "", local_repo_path: str = "",
                      branch: str = "", head: str = ""):
        """保存项目版本基线信息（远端/本地仓库、分支、head）。

        这是源码知识库的版本基线：static 项目可手工填写，git 项目由导入/更新自动维护。
        更新 projects 字段 + project_git_info，并按 (branch, head) 注册版本基线。
        """
        import topoone.engine.version_sync_service as vss
        pid = project_id or projectId
        if not pid:
            raise ValueError("project_id is required")

        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (pid,))
        if not project:
            raise ValueError(f"Project not found: {pid}")

        updates = {}
        if remote_url is not None and remote_url != project.get("remote_url", ""):
            updates["remote_url"] = remote_url or ""
        if local_repo_path is not None and local_repo_path != project.get("local_repo_path", ""):
            updates["local_repo_path"] = local_repo_path or ""
        if updates:
            updates["updated_at"] = datetime.now().isoformat()
            main_db.update("projects", updates, "id = ?", (pid,))

        # 同步 project_git_info（手动编辑标记）
        try:
            _tm_save_git_info(multi_db, pid, remote_url=remote_url or None,
                              current_branch=branch or None,
                              current_commit=head or None)
        except Exception as e:
            logger.warning(f"[saveBaseline] git_info save failed: {e}")

        # 注册/刷新版本基线（force 使无内容变化时也记录 branch/head 标签）
        try:
            result = vss.sync(multi_db, pid, branch=branch, head=head,
                              label="baseline", force=bool(branch or head))
            return {
                "ok": True,
                "projectId": pid,
                "remoteUrl": remote_url or project.get("remote_url", ""),
                "localRepoPath": local_repo_path or project.get("local_repo_path", ""),
                "version": result.get("version") if result.get("changed") else None,
            }
        except Exception as e:
            logger.warning(f"[saveBaseline] version sync failed: {e}")
            return {"ok": True, "projectId": pid,
                    "remoteUrl": remote_url or "", "localRepoPath": local_repo_path or "",
                    "version": None}

    # ==================== 图节点位置 ====================

    @server.register("graph.savePositions")
    def save_positions(task_id: str = None, taskId: str = None,
                       edge_type: str = None, edgeType: str = None,
                       drill_key: str = None, drillKey: str = None,
                       snapshot_id: str = None, snapshotId: str = None,
                       layout_type: str = None, layoutType: str = None,
                       positions: list = None):
        tid = task_id or taskId
        et = edge_type or edgeType
        dk = drill_key or drillKey
        lt = layout_type or layoutType
        sid = snapshot_id or snapshotId
        if not tid or not et or not dk or not lt:
            raise ValueError("task_id, edge_type, drill_key, layout_type are required")
        return _tm_save_positions(multi_db, tid, et, dk, lt, positions or [], sid)

    @server.register("graph.loadPositions")
    def load_positions(task_id: str = None, taskId: str = None,
                       edge_type: str = None, edgeType: str = None,
                       drill_key: str = None, drillKey: str = None,
                       snapshot_id: str = None, snapshotId: str = None,
                       layout_type: str = None, layoutType: str = None):
        tid = task_id or taskId
        et = edge_type or edgeType
        dk = drill_key or drillKey
        lt = layout_type or layoutType
        sid = snapshot_id or snapshotId
        if not tid or not et or not dk or not lt:
            raise ValueError("task_id, edge_type, drill_key, layout_type are required")
        return _tm_load_positions(multi_db, tid, et, dk, lt, sid)

    @server.register("graph.clearPositions")
    def clear_positions(task_id: str = None, taskId: str = None,
                        edge_type: str = None, edgeType: str = None,
                        drill_key: str = None, drillKey: str = None,
                        layout_type: str = None, layoutType: str = None):
        tid = task_id or taskId
        et = edge_type or edgeType
        dk = drill_key or drillKey
        lt = layout_type or layoutType
        if not tid or not et or not dk or not lt:
            raise ValueError("task_id, edge_type, drill_key, layout_type are required")
        return _tm_clear_positions(multi_db, tid, et, dk, lt)

    @server.register("graph.listSavedPositionKeys")
    def list_saved_position_keys(project_id: str = None, projectId: str = None):
        pid = project_id or projectId
        if not pid: raise ValueError("project_id is required")
        return _tm_list_position_keys(multi_db, pid)

    # ==================== 分组管理方法 ====================

    @server.register("group.list")
    def list_groups():
        """获取所有分组（树形结构）"""
        rows = main_db.fetchall("SELECT * FROM project_groups ORDER BY sort_order, created_at")
        groups = [dict(r) for r in rows]
        # 构建树形结构
        def build_tree(parent_id=None, depth=0):
            result = []
            for g in groups:
                if g.get('parent_id') == parent_id:
                    node = {**g, 'children': build_tree(g['id'], depth + 1)}
                    result.append(node)
            return result
        return build_tree(None)

    @server.register("group.create")
    def create_group(name: str, parent_id: str = None):
        """创建分组（支持父子层级，最多4层）"""
        # 校验层级深度
        if parent_id:
            parent = main_db.fetchone("SELECT * FROM project_groups WHERE id = ?", (parent_id,))
            if not parent:
                raise ValueError("Parent group not found")
            if parent.get('depth', 0) >= 3:
                raise ValueError("Group nesting exceeds max 4 levels (recommend 2-3)")
            depth = parent['depth'] + 1
        else:
            depth = 0

        gid = str(uuid.uuid4())[:12]
        main_db.execute(
            "INSERT INTO project_groups (id, name, parent_id, depth, sort_order) VALUES (?, ?, ?, ?, ?)",
            (gid, name, parent_id, depth, 0)
        )
        main_db.commit()
        return {"id": gid, "name": name, "parent_id": parent_id, "depth": depth}

    @server.register("group.update")
    def update_group(id: str, name: str = None, parent_id: str = None):
        """更新分组名称或父级"""
        group = main_db.fetchone("SELECT * FROM project_groups WHERE id = ?", (id,))
        if not group:
            raise ValueError("Group not found")

        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if parent_id is not None:
            # 不能把自己设为子节点（防止循环）
            if parent_id == id:
                raise ValueError("Cannot set group as its own parent")
            # 校验层级
            if parent_id:
                parent = main_db.fetchone("SELECT * FROM project_groups WHERE id = ?", (parent_id,))
                if not parent:
                    raise ValueError("Parent group not found")
                if parent.get('depth', 0) >= 3:
                    raise ValueError("Group nesting exceeds max 4 levels")
            updates.append("parent_id = ?")
            updates.append("depth = ?")
            params.append(parent_id)
            params.append(parent['depth'] + 1 if parent_id else 0)
        if updates:
            params.append(id)
            main_db.execute(f"UPDATE project_groups SET {', '.join(updates)} WHERE id = ?", params)
            main_db.commit()

        return {"success": True}

    @server.register("group.delete")
    def delete_group(id: str):
        """删除分组（级联删除子分组和关联）"""
        main_db.execute("DELETE FROM project_groups WHERE id = ?", (id,))
        main_db.commit()
        return {"success": True}

    @server.register("group.addProject")
    def add_project_to_group(project_id: str, group_id: str):
        """将项目加入分组"""
        # 验证存在
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        group = main_db.fetchone("SELECT * FROM project_groups WHERE id = ?", (group_id,))
        if not project:
            raise ValueError("Project not found")
        if not group:
            raise ValueError("Group not found")

        main_db.execute(
            "INSERT OR IGNORE INTO project_group_map (project_id, group_id) VALUES (?, ?)",
            (project_id, group_id)
        )
        main_db.commit()
        return {"success": True}

    @server.register("group.removeProject")
    def remove_project_from_group(project_id: str, group_id: str):
        """将项目从分组移除"""
        main_db.execute(
            "DELETE FROM project_group_map WHERE project_id = ? AND group_id = ?",
            (project_id, group_id)
        )
        main_db.commit()
        return {"success": True}

    @server.register("group.getProjectGroups")
    def get_project_groups(project_id: str):
        """获取项目所属的所有分组"""
        rows = main_db.fetchall(
            """SELECT g.* FROM project_groups g
               INNER JOIN project_group_map m ON g.id = m.group_id
               WHERE m.project_id = ?""",
            (project_id,)
        )
        return [dict(r) for r in rows]

    # ── system.* —— 浏览器模式文件/目录选择（D7/P2：服务端 pickDirectory） ──

    @server.register("system.pickDirectory")
    def pick_directory():
        """服务端目录选择器（Linux zenity/kdialog · macOS osascript · Windows PowerShell）。
        headless 无 GUI 时返回空串（前端降级手动输入）。"""
        import shutil
        import subprocess
        import sys as _sys
        if _sys.platform == "win32":
            return {"path": ""}
        if _sys.platform == "darwin":
            try:
                script = 'set d to choose folder with prompt "选择项目目录"\nreturn POSIX path of d'
                out = subprocess.check_output(["osascript", "-e", script], timeout=30,
                                              stderr=subprocess.DEVNULL).decode().strip()
                return {"path": out}
            except Exception:
                return {"path": ""}
        # Linux: zenity / kdialog
        for cmd in (["zenity", "--file-selection", "--directory"],
                    ["kdialog", "--getexistingdirectory"]):
            if shutil.which(cmd[0]):
                try:
                    out = subprocess.check_output(cmd, timeout=60, stderr=subprocess.DEVNULL).decode().strip()
                    return {"path": out}
                except Exception:
                    return {"path": ""}
        return {"path": ""}

    @server.register("system.pickFile")
    def pick_file():
        """服务端文件选择器；headless 返回空串。"""
        import shutil
        import subprocess
        import sys as _sys
        if _sys.platform == "win32":
            return {"path": ""}
        if _sys.platform == "darwin":
            try:
                script = 'set f to choose file with prompt "选择文件"\nreturn POSIX path of f'
                out = subprocess.check_output(["osascript", "-e", script], timeout=30,
                                              stderr=subprocess.DEVNULL).decode().strip()
                return {"path": out}
            except Exception:
                return {"path": ""}
        for cmd in (["zenity", "--file-selection"], ["kdialog", "--getopenfilename"]):
            if shutil.which(cmd[0]):
                try:
                    out = subprocess.check_output(cmd, timeout=60, stderr=subprocess.DEVNULL).decode().strip()
                    return {"path": out}
                except Exception:
                    return {"path": ""}
        return {"path": ""}

    @server.register("system.readFile")
    def read_file(path: str):
        """服务端读取文本文件（带路径守卫：仅允许主库项目目录下的文件）。"""
        import os as _os
        abs_path = _os.path.abspath(path)
        data_dir = _os.path.abspath(multi_db.data_dir)
        # 允许 data_dir 及其下任意路径；否则拒绝（防越权读任意文件）
        if not (abs_path == data_dir or abs_path.startswith(data_dir + _os.sep)):
            raise ValueError(f"path not allowed: {path}")
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return {"content": f.read()}

    return server


# ==================== 服务器目录浏览器 (dir.*) ====================
def register_dir_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册服务器目录浏览器方法 — Web 端替代 Electron dialog 选目录。

    供「导入项目」等场景按层级浏览服务器目录、新建目录，并对选定目录做
    git/重复项目/源码签名识别（移植自 architect plugins/architect/arch_routes/dirs.py）。
    """
    import socket
    import stat as _stat
    import subprocess

    main_db = multi_db.main_db

    # 分析时跳过系统/隐藏目录，避免目录树噪声
    _SKIP = {".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__", ".DS_Store",
             "node_modules", "dist", "build"}

    def _access(path: str) -> dict:
        r, w = os.access(path, os.R_OK), os.access(path, os.W_OK)
        return {"readable": r, "writable": w, "r": r, "w": w}

    def _entry_stat(full: str) -> dict:
        try:
            st = os.stat(full)
            return {
                "mtime": int(st.st_mtime * 1000),
                "size": st.st_size if not _stat.S_ISDIR(st.st_mode) else 0,
            }
        except OSError:
            return {"mtime": 0, "size": 0}

    def _host_info() -> dict:
        name = socket.gethostname()
        ip = ""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except OSError:
            ip = ""
        return {"name": name, "ip": ip}

    def _git_toplevel(path: str) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", path, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return ""
        return (r.stdout or "").strip() if r.returncode == 0 else ""

    def _git_branch(path: str) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", path, "branch", "--show-current"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return ""
        return (r.stdout or "").strip() if r.returncode == 0 else ""

    def _has_code(path: str) -> bool:
        try:
            names = os.listdir(path)
        except OSError:
            return False
        for n in names:
            if n.startswith(".") or n in _SKIP:
                continue
            full = os.path.join(path, n)
            if os.path.isfile(full) or os.path.isdir(full):
                return True
        return False

    @server.register("dir.list")
    def dir_list(path: str = None):
        """列出服务器目录内容（顶层目录/文件），按目录优先 + 名称排序。"""
        abs_path = os.path.abspath(os.path.expanduser(path or os.path.expanduser("~")))
        if not os.path.isdir(abs_path):
            raise ValueError(f"Directory not found or not a directory: {abs_path}")
        try:
            names = sorted(os.listdir(abs_path),
                           key=lambda n: (not os.path.isdir(os.path.join(abs_path, n)), n.lower()))
        except OSError as e:
            raise ValueError(f"Failed to read directory: {e}")
        entries = []
        for name in names:
            if name in _SKIP or name.startswith("."):
                continue
            full = os.path.join(abs_path, name)
            is_dir = os.path.isdir(full)
            info = _entry_stat(full)
            entries.append({
                "name": name, "isDir": is_dir,
                "size": info["size"], "mtime": info["mtime"],
                **(_access(full) if is_dir else {}),
            })
        return {
            "path": abs_path,
            "parent": os.path.dirname(abs_path) if os.path.dirname(abs_path) != abs_path else None,
            "host": _host_info(),
            **_access(abs_path),
            "entries": entries,
        }

    @server.register("dir.create")
    def dir_create(parent: str = None, name: str = None):
        """在指定父目录下新建一个目录（需父目录写权限）。"""
        parent = os.path.abspath(os.path.expanduser(parent or ""))
        name = (name or "").strip()
        if not parent or not name:
            raise ValueError("parent and name are required")
        if not os.path.isdir(parent):
            raise ValueError(f"Parent directory not found: {parent}")
        if not os.access(parent, os.W_OK):
            raise PermissionError(f"Parent directory is not writable: {parent}")
        if os.sep in name or name in (".", "..") or "\x00" in name:
            raise ValueError(f"Invalid directory name: {name}")
        target = os.path.join(parent, name)
        if os.path.exists(target):
            raise ValueError(f"Directory already exists: {target}")
        try:
            os.makedirs(target)
        except OSError as e:
            raise ValueError(f"Failed to create directory: {e}")
        return {"path": target, "name": name, **_access(target)}

    @server.register("dir.analyze")
    def dir_analyze(root: str = None):
        """分析选定目录：git 顶层/分支、是否空、是否有代码、重复项目、签名重关联。"""
        root = (root or "").strip()
        if not root:
            raise ValueError("root is required")
        abs_root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(abs_root):
            raise ValueError(f"Directory not found or not a directory: {abs_root}")

        toplevel = _git_toplevel(abs_root)
        is_git_root = bool(toplevel) and os.path.normpath(toplevel) == os.path.normpath(abs_root)

        names = []
        try:
            names = os.listdir(abs_root)
        except OSError:
            pass
        isEmpty = not any(n for n in names if not n.startswith(".") and n not in _SKIP)
        hasCode = not isEmpty and _has_code(abs_root)

        # 重复项目：KB projects 表中同 root_path 的项目
        duplicate = None
        try:
            existing = main_db.fetchone("SELECT * FROM projects WHERE root_path = ?", (abs_root,))
            if existing:
                duplicate = {
                    "id": existing["id"], "name": existing["name"],
                    "rootPath": existing["root_path"], "mode": existing.get("import_mode", ""),
                }
        except Exception:
            duplicate = None

        # proj-id 签名重关联提示：源码目录整体移动后指向已有项目
        signature_project = None
        sig_id = multi_db.read_proj_signature(abs_root)
        if sig_id:
            sig_row = main_db.fetchone("SELECT id, name, root_path FROM projects WHERE id = ?", (sig_id,))
            if sig_row:
                signature_project = {
                    "id": sig_row["id"], "name": sig_row["name"],
                    "rootPath": sig_row["root_path"],
                }

        return {
            "root": abs_root,
            "name": abs_root.rstrip("/").rsplit("/", 1)[-1] or "/",
            **_access(abs_root),
            "isGitRoot": is_git_root,
            "gitToplevel": toplevel or None,
            "gitBranch": _git_branch(abs_root) or None,
            "isEmpty": isEmpty,
            "hasCode": hasCode,
            "duplicate": duplicate,
            "signatureProject": signature_project,
        }


# ==================== KB 版本基线方法 ====================

def register_version_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册 KB 版本基线 + 增量更新 + 更新请求方法。

    对外契约（architect 经 data_api /zmq/{method} 代理调用）：
      version.list / version.get / version.preview / version.sync /
      version.diff / version.materialize /
      knowledge.pullRequest / knowledge.pendingUpdates /
      knowledge.updateConfirm / knowledge.updateCancel
    """
    import topoone.engine.version_sync_service as vss

    @server.register("version.list")
    def version_list(project_id: str = None, projectId: str = None):
        return vss.list_versions(multi_db, project_id or projectId)

    @server.register("version.get")
    def version_get(project_id: str = None, version_id: str = None,
                    projectId: str = None, versionId: str = None):
        return vss.get_version(multi_db, project_id or projectId, version_id or versionId)

    @server.register("version.preview")
    def version_preview(project_id: str = None, branch: str = "", head: str = "",
                        projectId: str = None):
        return vss.preview(multi_db, project_id or projectId, branch=branch, head=head)

    @server.register("version.sync")
    def version_sync(project_id: str = None, branch: str = "", head: str = "",
                     label: str = "", stages: dict = None, force: bool = False,
                     request_id: str = None, task_id: str = None,
                     projectId: str = None, requestId: str = None,
                     taskId: str = None):
        return vss.sync(multi_db, project_id or projectId,
                        branch=branch, head=head, label=label, stages=stages,
                        force=force, request_id=request_id or requestId,
                        task_id=task_id or taskId)

    @server.register("version.diff")
    def version_diff(project_id: str = None, from_id: str = None, to_id: str = None,
                     projectId: str = None, fromId: str = None, toId: str = None):
        return vss.diff_versions(multi_db, project_id or projectId,
                                 from_id or fromId, to_id or toId)

    @server.register("version.materialize")
    def version_materialize(project_id: str = None, version_id: str = None,
                            projectId: str = None, versionId: str = None):
        return vss.materialize(multi_db, project_id or projectId, version_id or versionId)

    @server.register("version.cleanup")
    def version_cleanup(project_id: str = None, keep_versions: int = 0,
                        projectId: str = None, keepVersions: int = None):
        kv = keepVersions if keepVersions is not None else keep_versions
        return vss.cleanup(multi_db, project_id or projectId, keep_versions=kv)

    @server.register("knowledge.pullRequest")
    def knowledge_pull_request(project_id: str = None, repo_url: str = "",
                               local_repo_path: str = "", branch: str = "",
                               head: str = "", note: str = "",
                               projectId: str = None):
        return vss.pull_request(multi_db, project_id or projectId,
                                repo_url=repo_url, local_repo_path=local_repo_path,
                                branch=branch, head=head, note=note)

    @server.register("knowledge.pendingUpdates")
    def knowledge_pending_updates(project_id: str = None, projectId: str = None):
        return vss.pending_updates(multi_db, project_id or projectId)

    @server.register("knowledge.updateConfirm")
    def knowledge_update_confirm(request_id: str = None, method: str = "pull",
                                 requestId: str = None):
        return vss.confirm_update(multi_db, request_id or requestId, method=method)

    @server.register("knowledge.updateCancel")
    def knowledge_update_cancel(request_id: str = None, requestId: str = None):
        return {"cancelled": vss.cancel_update(multi_db, request_id or requestId)}

    @server.register("architecture.model")
    def architecture_model(project_id: str = None, task_id: str = "",
                           level: str = "L1", edge_type: str = "UNIFIED",
                           projectId: str = None, taskId: str = None):
        """(KB-REQ-17) 项目真实架构模型：由分析图社区/节点/边/版本差异构建。

        architect 前端的组件索引、代码映射、依赖关系均来自此处，取代静态演示模型。
        """
        from topoone.engine.architecture_model_service import build_architecture_model
        pid = project_id or projectId
        tid = task_id or taskId
        return build_architecture_model(multi_db, pid, task_id=tid,
                                        level=level, edge_type=edge_type)

    @server.register("architecture.catalog")
    def architecture_catalog(project_id: str = None, task_id: str = "",
                             projectId: str = None, taskId: str = None):
        """(KB-REQ-17) 组件目录：合并 依赖分析(INCLUDE)/调用分析(CALL) 与 L0/L1
        层社区，附带父组件 / 文件数 / 类型元数据，供组件选择器筛选。"""
        from topoone.engine.architecture_model_service import build_component_catalog
        pid = project_id or projectId
        tid = task_id or taskId
        return build_component_catalog(multi_db, pid, task_id=tid)

    return server


# ==================== 代码分析方法 ====================

# analysis.* 方法已迁移到 task_manager.py
from topoone.engine.task_manager import register_analysis_methods


# ==================== 设置配置方法 ====================

def register_settings_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册设置配置方法"""
    main_db = multi_db.main_db

    @server.register("settings.getModels")
    def get_models():
        rows = main_db.fetchall("SELECT * FROM model_configs ORDER BY is_default DESC, name")
        for row in rows:
            row["isDefault"] = bool(row.get("is_default"))
            # 安全：不返回 api_key，只标记是否存在
            row["hasApiKey"] = bool(row.get("api_key"))
            if row.get("api_key"):
                del row["api_key"]
            if row.get("extra_config"):
                try:
                    row["extraConfig"] = json.loads(row["extra_config"])
                except (json.JSONDecodeError, TypeError):
                    row["extraConfig"] = {}
        return rows

    @server.register("settings.addModel")
    def add_model(name: str, provider: str, model: str, url: str, type: str = "local", **kwargs):
        now = datetime.now().isoformat()

        # 去重: 同名 + 同 provider 的模型自动更新
        existing = main_db.fetchone(
            "SELECT id FROM model_configs WHERE name = ? AND provider = ?",
            (name, provider),
        )
        if existing:
            logger.info(f"[addModel] model already exists, auto-updating: {existing['id']} ({name}/{provider})")
            return update_model(existing["id"], **kwargs,
                              name=name, provider=provider, model=model, url=url, type=type)

        model_id = f"model-{uuid.uuid4().hex[:8]}"

        if kwargs.get("isDefault"):
            main_db.execute("UPDATE model_configs SET is_default = 0")

        # 统一 URL 格式：去掉末尾的 /v1（兼容用户输入 https://xxx/v1 的情况）
        clean_url = url.rstrip('/')
        if clean_url.endswith('/v1'):
            clean_url = clean_url[:-3]

        data = {
            "id": model_id,
            "name": name,
            "provider": provider,
            "model": model,
            "url": clean_url,
            "type": type,
            "status": "offline",
            "is_default": 1 if kwargs.get("isDefault") else 0,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("maxTokens", 16384),
            "frequency_penalty": kwargs.get("frequencyPenalty", 0.0),
            "presence_penalty": kwargs.get("presencePenalty", 0.0),
            "timeout": kwargs.get("timeout", 300),
            "extra_config": json.dumps(kwargs["extraConfig"]) if kwargs.get("extraConfig") else None,
            "context_window": kwargs.get("contextWindow", 8192),
            "created_at": now,
            "updated_at": now,
        }
        if kwargs.get("apiKey"):
            data["api_key"] = kwargs["apiKey"]

        main_db.insert("model_configs", data)
        row = main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (model_id,))
        if row and row.get("extra_config"):
            try:
                row["extraConfig"] = json.loads(row["extra_config"])
            except (json.JSONDecodeError, TypeError):
                row["extraConfig"] = {}
        return row

    @server.register("settings.updateModel")
    def update_model(id: str, **kwargs):
        allowed = {"name", "temperature", "maxTokens", "url", "isDefault", "provider", "model", "apiKey", "maxRequestsPerDay", "maxTokensPerDay", "frequencyPenalty", "presencePenalty", "timeout", "contextWindow", "extraConfig"}
        data = {}
        for k, v in kwargs.items():
            if k == "isDefault":
                if v:
                    main_db.execute("UPDATE model_configs SET is_default = 0")
                data["is_default"] = 1 if v else 0
            elif k == "maxTokens":
                data["max_tokens"] = v
            elif k == "frequencyPenalty":
                data["frequency_penalty"] = v
            elif k == "presencePenalty":
                data["presence_penalty"] = v
            elif k == "maxRequestsPerDay":
                data["max_requests_per_day"] = int(v) if v else 0
            elif k == "maxTokensPerDay":
                data["max_tokens_per_day"] = int(v) if v else 0
            elif k == "apiKey":
                if v:
                    data["api_key"] = v
            elif k == "timeout":
                data["timeout"] = int(v) if v else 300
            elif k == "contextWindow":
                data["context_window"] = int(v) if v else 8192
            elif k == "extraConfig":
                data["extra_config"] = json.dumps(v) if isinstance(v, dict) else str(v)
            elif k == "url":
                clean_url = v.rstrip('/')
                if clean_url.endswith('/v1'):
                    clean_url = clean_url[:-3]
                data["url"] = clean_url
            elif k in allowed:
                data[k] = v
        data["updated_at"] = datetime.now().isoformat()

        main_db.update("model_configs", data, "id = ?", (id,))
        row = main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (id,))
        if row and row.get("extra_config"):
            try:
                row["extraConfig"] = json.loads(row["extra_config"])
            except (json.JSONDecodeError, TypeError):
                row["extraConfig"] = {}
        return row

    @server.register("settings.removeModel")
    def remove_model(id: str):
        main_db.delete("model_configs", "id = ?", (id,))

    @server.register("settings.testModel")
    async def test_model(id: str):
        """测试模型连接 — 自适应 API Key，如实返回服务端错误"""
        model = main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (id,))
        if not model:
            raise ValueError(f"Model not found: {id}")

        import requests as req
        start = __import__('time').time()
        try:
            base = model['url'].rstrip('/')
            if base.endswith('/v1'):
                base = base[:-3]
            headers = {'Content-Type': 'application/json'}
            api_key = model.get('api_key')
            if api_key:
                headers['Authorization'] = f"Bearer {api_key}"

            if model.get('provider') == 'ollama':
                resp = req.post(f"{base}/api/tags", timeout=10)
            else:
                payload = {
                    "model": model["model"],
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 1,
                    "stream": False,
                }
                resp = req.post(f"{base}/v1/chat/completions",
                                json=payload, headers=headers, timeout=15)

            latency = int((__import__('time').time() - start) * 1000)

            if resp.status_code == 200:
                try:
                    main_db.update("model_configs", {"status": "connected"}, "id = ?", (id,))
                except Exception:
                    pass
                return {"status": "connected", "latency": latency, "model": model["model"]}
            else:
                msg = f"HTTP {resp.status_code}"
                try:
                    body = resp.json()
                    if "error" in body:
                        msg = str(body["error"])
                    elif "message" in body:
                        msg = str(body["message"])
                except Exception:
                    msg = resp.text[:200] if resp.text else msg
                return {"status": "error", "latency": latency, "error": msg}

        except Exception as e:
            return {"status": "error", "latency": 0, "error": str(e)}

    @server.register("settings.getAgents")
    def get_agents():
        rows = main_db.fetchall("SELECT * FROM agent_configs ORDER BY is_default DESC, name")
        for row in rows:
            row["isDefault"] = bool(row.get("is_default"))
        return rows

    @server.register("settings.addAgent")
    def add_agent(name: str, path: str, args: str = "", type: str = "custom"):
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        main_db.insert("agent_configs", {
            "id": agent_id,
            "name": name,
            "type": type,
            "path": path,
            "args": args,
            "status": "configured",
            "created_at": now,
            "updated_at": now,
        })

        return main_db.fetchone("SELECT * FROM agent_configs WHERE id = ?", (agent_id,))

    @server.register("settings.updateAgent")
    def update_agent(id: str, **kwargs):
        allowed = {"path", "args", "name", "type"}
        data = {k: v for k, v in kwargs.items() if k in allowed}
        data["updated_at"] = datetime.now().isoformat()

        main_db.update("agent_configs", data, "id = ?", (id,))
        return main_db.fetchone("SELECT * FROM agent_configs WHERE id = ?", (id,))

    @server.register("settings.removeAgent")
    def remove_agent(id: str):
        main_db.delete("agent_configs", "id = ?", (id,))

    @server.register("settings.detectAgent")
    async def detect_agent(id: str):
        agent = main_db.fetchone("SELECT * FROM agent_configs WHERE id = ?", (id,))
        if not agent:
            raise ValueError(f"Agent not found: {id}")

        if os.path.exists(agent["path"]):
            status = "online"
            version = "unknown"
            try:
                result = os.popen(f'{agent["path"]} --version 2>/dev/null').read().strip()
                if result:
                    version = result
            except:
                pass
        else:
            status = "not-detected"
            version = None

        main_db.update("agent_configs", {"status": status, "version": version}, "id = ?", (id,))

        return {"status": status, "version": version}

    @server.register("settings.executeAgent")
    async def execute_agent(id: str, task: str = "", args: str = "", task_id: str = "", env: dict = None):
        """异步执行外部 Agent 命令，写入 agent_executions 表追踪状态"""
        import shlex
        import tempfile

        agent = main_db.fetchone("SELECT * FROM agent_configs WHERE id = ?", (id,))
        if not agent:
            raise ValueError(f"Agent not found: {id}")

        exec_id = f"aex-{uuid.uuid4().hex[:8]}"
        user_args = shlex.split(args or "") if args else []
        cmd_parts = [agent["path"]] + shlex.split(agent["args"] or "") + user_args
        if task:
            cmd_parts.append(task)
        cmd = " ".join(cmd_parts)

        stdout_fd, stdout_path = tempfile.mkstemp(prefix=f"agent-exec-{exec_id}-stdout-", suffix=".log")
        stderr_fd, stderr_path = tempfile.mkstemp(prefix=f"agent-exec-{exec_id}-stderr-", suffix=".log")
        os.close(stdout_fd)
        os.close(stderr_fd)

        proc_env = os.environ.copy()
        if agent["env"]:
            try:
                proc_env.update(json.loads(agent["env"]))
            except Exception:
                pass
        if env:
            proc_env.update(env)

        now = datetime.now().isoformat()
        main_db.insert("agent_executions", {
            "id": exec_id,
            "agent_config_id": id,
            "task_id": task_id or "",
            "status": "queued",
            "args": args,
            "env": json.dumps(env) if env else "",
            "command": cmd,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "created_at": now,
        })

        async def _run():
            started = datetime.now().isoformat()
            main_db.update("agent_executions", {"status": "running", "started_at": started}, "id = ?", (exec_id,))
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=open(stdout_path, "w"), stderr=open(stderr_path, "w"),
                    env=proc_env,
                )
                timeout = agent.get("timeout", 300) / 1000.0 if agent.get("timeout") else 300.0
                try:
                    exit_code = await asyncio.wait_for(proc.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    exit_code = -1
                    error = f"timeout after {timeout}s"

                finished = datetime.now().isoformat()
                started_ts = datetime.fromisoformat(started)
                finished_ts = datetime.fromisoformat(finished)
                duration = int((finished_ts - started_ts).total_seconds() * 1000)

                final_status = "completed" if exit_code == 0 else ("timed_out" if exit_code == -1 else "failed")
                main_db.update("agent_executions", {
                    "status": final_status,
                    "exit_code": exit_code,
                    "finished_at": finished,
                    "duration_ms": duration,
                    "error": error or "",
                }, "id = ?", (exec_id,))
            except Exception as e:
                logger.exception(f"executeAgent {exec_id} crashed")
                main_db.update("agent_executions", {
                    "status": "failed", "error": str(e),
                    "finished_at": datetime.now().isoformat(),
                }, "id = ?", (exec_id,))

        asyncio.get_event_loop().create_task(_run())
        return {"id": exec_id, "agentId": id, "command": cmd, "status": "queued"}

    @server.register("settings.getAgentExecution")
    def get_agent_execution(exec_id: str):
        row = main_db.fetchone("SELECT * FROM agent_executions WHERE id = ?", (exec_id,))
        if not row:
            return {"found": False}
        return row

    @server.register("settings.listAgentExecutions")
    def list_agent_executions(agent_id: str = "", task_id: str = "", status_filter: str = "", limit: int = 50):
        where = ["1=1"]
        params = []
        if agent_id:
            where.append("agent_config_id = ?")
            params.append(agent_id)
        if task_id:
            where.append("task_id = ?")
            params.append(task_id)
        if status_filter:
            statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
            if statuses:
                where.append("status IN (" + ",".join("?" for _ in statuses) + ")")
                params.extend(statuses)
        sql = f"SELECT * FROM agent_executions WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return main_db.fetchall(sql, tuple(params))

    @server.register("settings.cancelAgentExecution")
    def cancel_agent_execution(exec_id: str):
        row = main_db.fetchone("SELECT * FROM agent_executions WHERE id = ?", (exec_id,))
        if not row:
            raise ValueError(f"Agent execution not found: {exec_id}")
        if row["status"] not in ("queued", "running"):
            return {"cancelled": False, "message": f"status is {row['status']}"}
        main_db.update("agent_executions", {"status": "cancelled", "finished_at": datetime.now().isoformat()}, "id = ?", (exec_id,))
        return {"cancelled": True}

    @server.register("settings.getSkills")
    def get_skills():
        rows = main_db.fetchall("SELECT * FROM skill_configs ORDER BY name")
        for row in rows:
            row["enabled"] = bool(row.get("enabled"))
            if row.get("config"):
                row["config"] = json.loads(row["config"])
        return rows

    @server.register("settings.updateSkill")
    def update_skill(id: str, enabled: bool):
        main_db.update("skill_configs", {"enabled": 1 if enabled else 0, "updated_at": datetime.now().isoformat()}, "id = ?", (id,))
        return main_db.fetchone("SELECT * FROM skill_configs WHERE id = ?", (id,))

    @server.register("settings.getBindings")
    def get_bindings():
        rows = main_db.fetchall("SELECT task_type, model_id FROM task_model_bindings")
        return {row["task_type"]: row["model_id"] for row in rows}

    @server.register("settings.updateBindings")
    def update_bindings(bindings: dict):
        for task_type, model_id in bindings.items():
            main_db.execute(
                "INSERT OR REPLACE INTO task_model_bindings (id, task_type, model_id) VALUES (?, ?, ?)",
                (f"bind-{task_type}", task_type, model_id),
            )
        return bindings

    # ==================== 模型用量统计 ====================

    # 确保 model_daily_usage 表存在（兼容旧版本升级）
    def _ensure_usage_table():
        try:
            main_db.execute("SELECT 1 FROM model_daily_usage LIMIT 1")
        except Exception:
            main_db.execute("""CREATE TABLE IF NOT EXISTS model_daily_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL REFERENCES model_configs(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(model_id, date)
            )""")
        # 确保索引存在（每次调用都执行，兼容旧版本升级）
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_mdu_model ON model_daily_usage(model_id)",
            "CREATE INDEX IF NOT EXISTS idx_mdu_date ON model_daily_usage(date)",
            "CREATE INDEX IF NOT EXISTS idx_mdu_model_date ON model_daily_usage(model_id, date)",
        ]:
            try:
                main_db.execute(idx_sql)
            except Exception:
                pass

    @server.register("model.getUsageStats")
    def get_usage_stats(model_id: str = None, start_date: str = None, end_date: str = None):
        _ensure_usage_table()
        sql = "SELECT d.*, m.name AS model_name FROM model_daily_usage d JOIN model_configs m ON d.model_id = m.id WHERE 1=1"
        params = []
        if model_id:
            sql += " AND d.model_id = ?"
            params.append(model_id)
        if start_date:
            sql += " AND d.date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND d.date <= ?"
            params.append(end_date)
        sql += " ORDER BY d.date DESC, m.name"
        rows = main_db.fetchall(sql, tuple(params))
        for row in rows:
            row["modelId"] = row.pop("model_id")
            row["requestCount"] = row.pop("request_count")
            row["promptTokens"] = row.pop("prompt_tokens")
            row["completionTokens"] = row.pop("completion_tokens")
            row["totalTokens"] = row.pop("total_tokens")
            row["modelName"] = row.pop("model_name")
        return rows

    @server.register("model.deleteUsageStats")
    def delete_usage_stats(id: int):
        _ensure_usage_table()
        main_db.delete("model_daily_usage", "id = ?", (id,))

    @server.register("model.deleteUsageStatsBatch")
    def delete_usage_stats_batch(ids: list):
        _ensure_usage_table()
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        main_db.execute(f"DELETE FROM model_daily_usage WHERE id IN ({placeholders})", tuple(ids))

    @server.register("model.deleteUsageStatsByCondition")
    def delete_usage_stats_by_condition(model_id: str = None, start_date: str = None, end_date: str = None):
        _ensure_usage_table()
        sql = "DELETE FROM model_daily_usage WHERE 1=1"
        params = []
        if model_id:
            sql += " AND model_id = ?"
            params.append(model_id)
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)
        main_db.execute(sql, tuple(params))

    # ==================== 导入配置 ====================
    # （已随纯 git 视图机制移除：文件范围完全由 git 决定）

    return server


# ==================== 后端管理方法 ====================

def register_backend_methods(server: ZMQServer, multi_db: MultiDBManager, plugin_manager: 'PluginManager' = None):
    """注册后端管理方法"""

    @server.register("backend.start")
    def start_backend():
        return {"status": "running", "pid": os.getpid(), "port": 5671}

    @server.register("backend.stop")
    def stop_backend():
        server.stop()
        return {"status": "stopped"}

    @server.register("backend.restart")
    def restart_backend():
        return {"status": "restarting"}

    @server.register("backend.getStatus")
    def get_status():
        http_port = getattr(multi_db, 'http_port', None)
        http_host = getattr(multi_db, 'http_host', None)
        result = {"status": "running", "pid": os.getpid(), "port": 5671, "httpPort": http_port, "httpHost": http_host}
        sv = getattr(multi_db, '_supervisor', None)
        if sv:
            result["supervisor"] = sv.get_status()
        return result

    @server.register("backend.getMetrics")
    def get_metrics():
        """返回 Prometheus-style 运行时指标"""
        import os as _os
        import time as _time
        metrics = {
            "pid": os.getpid(),
            "uptime_sec": _time.time() - _time.monotonic(),
            "memory_mb": 0,
            "active_tasks": [],
            "supervisor": {},
        }
        # 内存
        try:
            import psutil
            proc = psutil.Process()
            metrics["memory_mb"] = proc.memory_info().rss / 1024 / 1024
        except Exception:
            pass
        # 任务
        from topoone.engine.store.task_store import TaskStore
        try:
            rows = TaskStore(multi_db.main_db)._db.execute(
                "SELECT id, name, status, progress FROM analysis_tasks WHERE status IN ('running','queued')"
            ).fetchall()
            metrics["active_tasks"] = [dict(r) for r in rows]
        except Exception:
            pass
        # supervisor
        sv = getattr(multi_db, '_supervisor', None)
        if sv:
            metrics["supervisor"] = sv.get_status()
        return metrics

    @server.register("backend.saveHttpConfig")
    def save_http_config(host: str = None, port: int = None):
        """持久化 HTTP 配置到 app_config 表"""
        from datetime import datetime
        now = datetime.now().isoformat()
        if host is not None:
            multi_db.main_db.execute(
                "INSERT OR REPLACE INTO app_config (key, value, updated_at) VALUES (?, ?, ?)",
                ("http_host", host, now)
            )
        if port is not None:
            multi_db.main_db.execute(
                "INSERT OR REPLACE INTO app_config (key, value, updated_at) VALUES (?, ?, ?)",
                ("http_port", str(port), now)
            )
        multi_db.main_db.commit()
        logger.info(f"[saveHttpConfig] host={host} port={port}")
        return {"success": True}

    @server.register("backend.getHttpConfig")
    def get_http_config():
        """从 app_config 表读取持久化的 HTTP 配置"""
        rows = main_db.fetchall("SELECT key, value FROM app_config WHERE key IN ('http_host', 'http_port')")
        result = {}
        for r in rows:
            result[r["key"]] = r["value"]
        return {
            "host": result.get("http_host", ""),
            "port": int(result.get("http_port", 0)) if result.get("http_port") else 0,
        }

    @server.register("backend.ping")
    def ping():
        return {"pong": True, "timestamp": datetime.now().isoformat()}

    @server.register("app.checkVersion")
    def check_version(current: str = ""):
        """检查应用版本更新"""
        rows = main_db.fetchall(
            "SELECT key, value FROM app_config WHERE key IN ('latest_version', 'download_url_github', 'download_url_gitee')"
        )
        config = {r["key"]: r["value"] for r in rows}
        latest = config.get("latest_version", current)
        has_update = latest > current if current and latest else False
        return {
            "latest_version": latest,
            "has_update": has_update,
            "download_urls": {
                "github": config.get("download_url_github", ""),
                "gitee": config.get("download_url_gitee", ""),
            },
        }

    @server.register("backend.testPort")
    def test_port(port: int):
        """测试端口是否可用"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return {"port": port, "available": True}
            except OSError:
                return {"port": port, "available": False}

    # ==================== 插件管理 ====================
    if plugin_manager:
        @server.register("plugin.list")
        def list_plugins():
            plugins = plugin_manager.list_plugins()
            return {
                name: {
                    "name": info.name,
                    "version": info.version,
                    "description": info.description,
                    "loaded": name in plugin_manager._loaded,
                    "platforms": list(info.platforms) if info.platforms else [],
                }
                for name, info in plugins.items()
            }

        @server.register("plugin.get")
        def get_plugin(name: str):
            info = plugin_manager.get_plugin(name)
            if not info:
                return None
            return {
                "name": info.name,
                "version": info.version,
                "description": info.description,
                "entry": info.entry,
                "loaded": name in plugin_manager._loaded,
                "platforms": list(info.platforms) if info.platforms else [],
            }

        @server.register("plugin.load")
        def load_plugin(name: str):
            success = plugin_manager.load_plugin(name)
            return {"success": success}

        @server.register("plugin.unload")
        def unload_plugin(name: str):
            success = plugin_manager.unload_plugin(name)
            return {"success": success}

        @server.register("plugin.reload")
        def reload_plugin(name: str):
            success = plugin_manager.reload_plugin(name)
            return {"success": success}

        @server.register("plugin.install")
        def install_plugin(name: str):
            success = plugin_manager.install_requirements(name)
            return {"success": success}

    return server


# ==================== 模块管理方法（远程下载） ====================

def register_module_methods(server: ZMQServer, module_manager=None):
    """注册模块管理方法（registry 查询 / 下载 / 安装 / 卸载 / 更新）"""
    from topoone.engine.module_manager import get_module_manager
    mm = module_manager or get_module_manager()

    @server.register("module.listRegistry")
    def list_module_registry(registry_url: str = None):
        mm.fetch_registry(registry_url)
        return {
            mod_id: {
                "id": mod.id,
                "name": mod.name,
                "version": mod.version,
                "description": mod.description,
                "size_kb": mod.size_kb,
                "platforms": list(mod.platforms) if mod.platforms else [],
                "dependencies": mod.dependencies,
            }
            for mod_id, mod in mm.list_registry().items()
        }

    @server.register("module.getInstalled")
    def get_installed_modules():
        installed = mm.get_installed()
        return {
            mod_id: {
                "id": mod.id,
                "name": mod.name,
                "version": mod.version,
                "description": mod.description,
                "entry": mod.entry,
                "size_kb": mod.size_kb,
                "loaded": mod.loaded,
                "dependencies": mod.dependencies,
            }
            for mod_id, mod in installed.items()
        }

    @server.register("module.install")
    def install_module(name: str, registry_url: str = None):
        success = mm.install(name, registry_url)
        return {"success": success}

    @server.register("module.uninstall")
    def uninstall_module(name: str):
        success = mm.uninstall(name)
        return {"success": success}

    @server.register("module.update")
    def update_module(name: str, registry_url: str = None):
        success = mm.update(name, registry_url)
        return {"success": success}

    @server.register("module.search")
    def search_module(query: str):
        results = {}
        for mod_id, mod in mm.list_registry().items():
            if query.lower() in mod_id.lower() or query.lower() in mod.name.lower():
                results[mod_id] = {
                    "id": mod.id,
                    "name": mod.name,
                    "version": mod.version,
                    "description": mod.description,
                    "size_kb": mod.size_kb,
                    "platforms": list(mod.platforms) if mod.platforms else [],
                }
        return results

    return server


# ==================== 辅助函数 ====================


def _project_keyed_tables(main_db) -> dict:
    """动态派生项目级联表清单(schema 单一事实源, 加表免维护):
    {表名: 键列} —— 含 project_id 列的表走直键; 仅含 task_id 列的表
    (task_config_history 等)经项目任务集合间接删除。sqlite 内部表排除。"""
    out: dict = {}
    for row in main_db.fetchall("SELECT name FROM sqlite_master WHERE type='table'"):
        t = row["name"]
        if not t or t.startswith("sqlite_"):
            continue
        try:
            cols = {c["name"] for c in main_db.fetchall(f"PRAGMA table_info({t})")}
        except Exception:
            continue
        if "project_id" in cols:
            out[t] = "project_id"
        elif "task_id" in cols:
            out[t] = "task_id"
    return out


def _cascade_delete_project_rows(main_db, pid: str, task_ids: list) -> dict:
    """删除主库中所有归属 pid 的行(project_id 直键 + task_id 间接键)。
    projects 行由调用方最后删除。返回 {表: 删除行数} 供日志与进度。"""
    deleted: dict = {}
    for t, key in _project_keyed_tables(main_db).items():
        if t == "projects":
            continue
        try:
            if key == "project_id":
                n = main_db.delete(t, "project_id=?", (pid,))
            else:
                if not task_ids:
                    continue
                ph = ",".join("?" for _ in task_ids)
                n = main_db.delete(t, f"task_id IN ({ph})", tuple(task_ids))
            if n:
                deleted[t] = n
        except Exception as e:
            logger.warning("[cascade] delete %s failed for %s: %s", t, pid, e)
    return deleted


def _gc_purge_task_orphans(main_db) -> dict:
    """全局清扫 task 间接键孤儿: task_id 已不存在于 analysis_tasks 的行
    (历史删除先清 tasks 后崩/旧版仅删 tasks 所致, pid 反查不可达)。"""
    cleaned: dict = {}
    for t, key in _project_keyed_tables(main_db).items():
        if key != "task_id" or t == "analysis_tasks":
            continue
        try:
            n = main_db.delete(
                t, "task_id NOT IN (SELECT id FROM analysis_tasks)")
            if n:
                cleaned[t] = n
        except Exception as e:
            logger.warning("[gc] task-orphan sweep %s failed: %s", t, e)
    if cleaned:
        main_db.conn.commit()
    return cleaned


def _gc_orphan_pids(main_db, multi_db: MultiDBManager, busy: set = None) -> list:
    """扫描孤儿项目 pid 候选: 主库残留行 / 项目库目录 / 源码镜像中
    出现、但 projects 注册表无记录的 pid。busy 中的 pid(在途导入/删除)
    跳过。只读扫描, 删除由调用方执行。"""
    try:
        live = {r["id"] for r in main_db.fetchall("SELECT id FROM projects")}
    except Exception as e:
        logger.error("[gc] projects 表不可读, 跳过本轮扫描: %s", e)
        return []
    busy = busy or set()
    cand: set = set()
    for t, key in _project_keyed_tables(main_db).items():
        if key != "project_id":
            continue
        try:
            for r in main_db.fetchall(f"SELECT DISTINCT project_id AS pid FROM {t}"):
                if r["pid"]:
                    cand.add(r["pid"])
        except Exception:
            continue
    try:
        proj_root = os.path.join(multi_db.data_dir, "projects")
        if os.path.isdir(proj_root):
            # 仅目录是候选 pid(根下游离 project.db 等文件是历史 bug 产物, 单独清)
            cand.update(d for d in os.listdir(proj_root)
                        if os.path.isdir(os.path.join(proj_root, d)))
        sc_dir = os.path.dirname(multi_db.source_cache_dir_for("_probe_"))  # {镜像根}
        if os.path.isdir(sc_dir):
            cand.update(d for d in os.listdir(sc_dir) if d.startswith("proj-"))
    except Exception as e:
        logger.warning("[gc] 目录扫描部分失败(继续): %s", e)
    return sorted(p for p in cand - live if p not in busy)


def _gc_purge_project(main_db, multi_db: MultiDBManager, pid: str) -> dict:
    """对单个孤儿 pid 执行与 project.remove 同口径的物理清扫
    (主库行 + 项目库目录 + 源码镜像)。返回清扫报告。"""
    report: dict = {"rows": {}, "files": []}
    task_ids = [t["id"] for t in main_db.fetchall(
        "SELECT id FROM analysis_tasks WHERE project_id=?", (pid,))]
    report["rows"] = _cascade_delete_project_rows(main_db, pid, task_ids)
    main_db.conn.commit()
    try:
        multi_db.delete_project_db(pid)
        report["files"].append(f"projects/{pid}/project.db")
    except Exception as e:
        logger.warning("[gc] project db delete failed %s: %s", pid, e)
    for d in (os.path.join(multi_db.data_dir, "projects", pid),
              multi_db.source_cache_dir_for(pid)):
        try:
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                report["files"].append(d)
        except Exception as e:
            logger.warning("[gc] rmtree failed %s: %s", d, e)
    return report


def _remove_project_impl(server, main_db, multi_db: MultiDBManager, pid: str,
                         root_path: str, request_id: str):
    """项目删除实现：tasks → database → source → record 四阶段，进度写入 _DELETE_JOBS 并推送事件。"""
    import logging as _logging
    _log = _logging.getLogger(__name__)

    def _set(phase: str, progress: int, **extra):
        if request_id:
            job = _DELETE_JOBS.get(request_id)
            if job is not None:
                job.update({"phase": phase, "progress": progress, "status": "deleting", "projectId": pid, **extra})
        try:
            server.publish("project", "remove.progress", {
                "projectId": pid, "requestId": request_id,
                "progress": progress, "phase": phase, **extra,
            })
        except Exception:
            pass

    _set("prepare", 1)

    # 阶段 1: 任务记录（runs + tasks）
    _set("tasks", 5)
    tasks = main_db.fetchall("SELECT id FROM analysis_tasks WHERE project_id=?", (pid,))
    for i, t in enumerate(tasks):
        main_db.delete("analysis_task_runs", "task_id=?", (t["id"],))
        if i % 50 == 0:
            _set("tasks", 5 + int(15 * (i + 1) / max(len(tasks), 1)))
    main_db.delete("analysis_tasks", "project_id=?", (pid,))
    _set("tasks", 20)

    # 阶段 2: 项目库文件
    _set("database", 25)
    multi_db.delete_project_db(pid)
    # 项目库目录一并清除(delete_project_db 只删 project.db 文件, 目录残留)
    try:
        pdb_dir = os.path.join(multi_db.data_dir, "projects", pid)
        if os.path.isdir(pdb_dir):
            shutil.rmtree(pdb_dir, ignore_errors=True)
    except Exception as e:
        logger.warning("[remove] project db dir cleanup failed %s: %s", pid, e)
    _set("database", 60)

    # 阶段 3: 源码镜像缓存（按字节计进度，大目录的主要耗时来源）
    _set("source", 65)
    try:
        src_dir = multi_db.source_cache_dir_for(pid)
    except Exception:
        src_dir = ""
    if src_dir and os.path.isdir(src_dir):
        files: list = []
        total_bytes = 0
        for r, _d, fs in os.walk(src_dir):
            for f in fs:
                fp = os.path.join(r, f)
                try:
                    total_bytes += os.path.getsize(fp)
                except OSError:
                    pass
                files.append(fp)
        done_bytes = 0
        for i, fp in enumerate(files):
            try:
                done_bytes += os.path.getsize(fp)
            except OSError:
                pass
            try:
                os.remove(fp)
            except OSError:
                pass
            if i % 200 == 0 or i == len(files) - 1:
                _set("source", 65 + int(25 * done_bytes / max(total_bytes, 1)))
        shutil.rmtree(src_dir, ignore_errors=True)
    _set("source", 90)

    # 阶段 4: 签名 + 主库记录 + 级联清扫
    _set("record", 92)
    if root_path:
        try:
            multi_db.remove_proj_signature(root_path)
        except Exception:
            pass
    # 级联清扫所有 pid 键行(versions/version_files/update_requests/
    # storage_stats/git_info/group_map/doc_map/task_config_history/
    # view_* 等, 动态派生) —— 此前仅删 tasks/runs, 其余全部残留为孤儿。
    try:
        task_ids = [t["id"] for t in tasks]
        swept = _cascade_delete_project_rows(main_db, pid, task_ids)
        if swept:
            logger.info(f"[remove] cascade swept {pid}: {swept}")
    except Exception as e:
        logger.warning(f"[remove] cascade sweep failed for {pid}: {e}")
    main_db.delete("projects", "id = ?", (pid,))
    main_db.conn.commit()
    # 基线视图随项目删除（视图行 + 挂载记录）
    try:
        from topoone.engine.view_service import remove_project_view
        remove_project_view(main_db, pid)
    except Exception as e:
        logger.warning("[remove] view cleanup failed for %s: %s", pid, e)
    _set("record", 100)

    if request_id:
        job = _DELETE_JOBS.get(request_id)
        if job is not None:
            job.update({"status": "done", "progress": 100, "phase": "done"})
    try:
        server.publish("project", "remove.progress", {
            "projectId": pid, "requestId": request_id, "progress": 100, "phase": "done",
        })
    except Exception:
        pass
    _log.info(f"[remove] project {pid} deleted")


async def _import_project_impl(server: ZMQServer, main_db, multi_db: MultiDBManager,
                               path: str, mode: str = "git-local", branch: str = "",
                               head: str = "", repo_url: str = "",
                               local_repo_path: str = "", request_id: str = "",
                               init_git: bool = False):
    """project.import 后台执行体（在独立线程的 asyncio 循环中运行）。

    仅支持 git-local / git-remote 两种模式：克隆到可配置的源码镜像目录，
    并把首次 checkout 的目录树快照进项目自有基线仓库（baseline.git），
    完成后注册初始 KB 版本基线，回写存储统计缓存列。
    """
    import time as _t

    logger.info(f"[import] ===== import started: {path} mode={mode} =====")
    t0 = _t.time()

    from topoone.engine import git_service
    from topoone.engine.version_sync_service import register_version

    mode = (mode or "git-local")
    if mode not in ("git-local", "git-remote"):
        raise ValueError(f"Invalid import mode: {mode}")

    if request_id:
        _IMPORT_JOBS[request_id] = {"status": "running", "progress": 0, "phase": "scan", "projectId": ""}

    project_id = f"proj-{uuid.uuid4().hex[:8]}"
    source_cache_dir = multi_db.source_cache_dir_for(project_id)
    effective_root = path
    resolved_head = head
    resolved_remote = repo_url
    resolved_local = local_repo_path

    # 项目名：static 用所选目录名；git 模式用仓库主目录名（而非 worktree 缓存目录名）
    def _project_name_source() -> str:
        if mode == "git-local":
            return os.path.basename((local_repo_path or path).rstrip("/\\"))
        if mode == "git-remote":
            repo = (repo_url or "").rstrip("/\\")
            name = os.path.basename(repo)
            if name.endswith(".git"):
                name = name[:-4]
            return name
        return os.path.basename(path.rstrip("/\\"))

    project_name = _project_name_source()

    # ── git 模式：克隆到源码镜像目录 ──
    if mode in ("git-local", "git-remote"):
        if mode == "git-local":
            if not local_repo_path and not path:
                raise ValueError("local_repo_path is required for git-local")
            source = local_repo_path or path
            resolved_local = source
            if not git_service.is_git_repo(source):
                # 独立源码目录模式已取消：非 git 仓库需用户勾选授权后自动初始化
                if not init_git:
                    raise ValueError(f"NOT_A_GIT_REPO: {source}")
                logger.info(f"[import] initializing git repo at {source} (user consented)")
                git_service.ensure_git_repo(source)
            resolved_remote = git_service.remote_url(source)
        else:
            if not repo_url:
                raise ValueError("repo_url is required for git-remote")
            source = repo_url
            resolved_local = ""

        cache_root = os.path.join(source_cache_dir, "worktree")
        logger.info(f"[import] cloning {mode} source into {cache_root} ...")
        resolved_head = git_service.clone(source, cache_root,
                                          branch=branch or None,
                                          head=head or None)
        if not resolved_remote:
            resolved_remote = git_service.remote_url(cache_root)
        if not branch:
            try:
                branch = git_service.current_branch(cache_root)
            except Exception:
                branch = ""
        effective_root = cache_root

        # 基线快照：镜像仓库作为代码基线，自有 git 版本管理（baseline.git）
        baseline_commit = ""
        try:
            baseline_commit = git_service.snapshot_baseline(
                cache_root, os.path.join(source_cache_dir, "baseline.git"),
                f"baseline: {resolved_remote or source}#{branch}@{resolved_head} (import)")
            logger.info(f"[import] baseline snapshot: {baseline_commit[:8]}")
        except Exception as e:
            logger.warning(f"[import] baseline snapshot failed (non-fatal): {e}")

    if not os.path.isdir(effective_root):
        raise FileNotFoundError(f"Directory not found: {effective_root}")

    # ── proj-id 签名重关联：源码目录整体移动后快速找回既有项目 ──
    # static 模式读 <path>/.topocode/proj-id；git 模式按 remote_url 匹配既有项目
    reassociated_id = None
    reuse_existing_project = False
    sig_id = multi_db.read_proj_signature(effective_root)
    if sig_id:
        existing = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (sig_id,))
        if existing:
            reassociated_id = sig_id
    if not reassociated_id and mode in ("git-local", "git-remote") and resolved_remote:
        existing = main_db.fetchone(
            "SELECT * FROM projects WHERE remote_url = ? AND id != ? LIMIT 1",
            (resolved_remote, project_id))
        if existing and (existing.get("import_mode") in ("git-local", "git-remote")):
            reassociated_id = existing["id"]

    if reassociated_id:
        existing = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (reassociated_id,))
        if existing and (existing.get("file_count") or 0) > 0:
            # 已有文件的项目：源码目录整体移动/重新选择 → 快速重关联（保留既有分析数据）
            now = datetime.now().isoformat()
            updates = {
                "root_path": effective_root,
                "updated_at": now,
            }
            if mode in ("git-local", "git-remote"):
                updates.update({
                    "source_cache_dir": source_cache_dir,
                    "remote_url": resolved_remote or "",
                    "local_repo_path": resolved_local,
                })
            main_db.update("projects", updates, "id = ?", (reassociated_id,))
            multi_db.write_proj_signature(effective_root, reassociated_id)
            multi_db.refresh_project_storage_stats(reassociated_id)
            logger.info(f"[import] reassociated moved source {effective_root} -> {reassociated_id}")
            if request_id:
                _IMPORT_JOBS[request_id] = {"status": "done", "progress": 100, "phase": "done",
                                            "projectId": reassociated_id, "reassociated": True}
            server.publish("project", "import.progress", {
                "path": effective_root,
                "progress": 100,
                "fileCount": existing.get("file_count", 0),
                "phase": "done",
            })
            row = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (reassociated_id,))
            return {**(row or {}), "reassociated": True}
        elif existing:
            # 空项目（此前导入失败/未成功扫描）：复用其 id 走完整扫描导入
            logger.info(f"[import] empty project {reassociated_id} (file_count=0), "
                        f"re-scanning full source: {effective_root}")
            project_id = reassociated_id
            reuse_existing_project = True
        reassociated_id = None

    now = datetime.now().isoformat()
    logger.info(f"[import] creating project db: {project_id}")
    project_db = multi_db.init_project_db(project_id, project_root=os.path.abspath(effective_root))
    logger.info(f"[import] project db created, elapsed {_t.time() - t0:.2f}s")

    # 单次遍历：同时完成语言检测和文件扫描（git ls-files 物化投影）
    logger.info(f"[import] starting file scan...")
    scan_t0 = _t.time()
    file_count, language = await _scan_and_import(
        project_db, effective_root, server, project_id)
    scan_elapsed = _t.time() - scan_t0
    logger.info(f"[import] scan complete: {file_count} files, language={language}, elapsed {scan_elapsed:.2f}s")

    # 插入主库（附带存储统计缓存列）
    logger.info(f"[import] writing to main projects table...")
    source_size = 0
    try:
        size_row = project_db.fetchone("SELECT COALESCE(SUM(size), 0) AS s FROM source_files")
        if size_row:
            source_size = size_row.get("s") if isinstance(size_row, dict) else size_row[0]
            source_size = source_size or 0
    except Exception:
        pass
    main_row = {
        "id": project_id,
        "name": project_name or os.path.basename(effective_root),
        "root_path": effective_root,
        "language": language,
        "file_count": file_count,
        "status": "synced",
        "needs_resync": 0,
        "has_file_changes": 0,
        "is_sample": 0,
        "import_mode": mode,
        "remote_url": resolved_remote or "",
        "local_repo_path": resolved_local or "",
        "source_cache_dir": source_cache_dir,
        "last_sync": now,
        "db_size_bytes": os.path.getsize(multi_db.project_db_path(project_id)) if os.path.exists(multi_db.project_db_path(project_id)) else 0,
        "source_size_bytes": source_size,
        "storage_checked_at": datetime.now().isoformat(),
    }
    if reuse_existing_project:
        main_row["updated_at"] = now
        main_db.update("projects", main_row, "id = ?", (project_id,))
    else:
        main_db.insert("projects", main_row)

    _ensure_topocode_dirs_in_gitignore(effective_root)
    multi_db.write_proj_signature(effective_root, project_id)

    # ── 注册初始 KB 版本基线（全部文件 = added）──
    try:
        file_rows = project_db.fetchall("SELECT file_path FROM source_files")
        all_paths = [r["file_path"] for r in file_rows]
        version = register_version(
            multi_db, project_id,
            branch=branch or "",
            head=resolved_head or "",
            label="initial-import",
            change_type="minor",
            delta={"added": all_paths, "modified": [], "deleted": []},
            is_baseline=True,
            baseline_commit=baseline_commit,
        )
        project_db.executemany(
            "UPDATE source_files SET version_from = ? WHERE version_from IS NULL",
            [(version["id"],)],
        )
        project_db.conn.commit()
        logger.info(f"[import] initial baseline version registered: {version['id']}")
    except Exception as e:
        logger.warning(f"[import] initial version registration failed: {e}")

    if request_id:
        _IMPORT_JOBS[request_id] = {"status": "done", "progress": 100, "phase": "done",
                                    "projectId": project_id}
    server.publish("project", "import.progress", {
        "path": effective_root,
        "progress": 100,
        "fileCount": file_count,
        "phase": "done",
    })
    total_elapsed = _t.time() - t0
    logger.info(f"[import] ===== import complete: {project_id}, {file_count} files, total {total_elapsed:.2f}s =====")

    return main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
async def _scan_and_import(project_db, root_path: str, server=None, project_id: str = "") -> tuple:
    """
    git 为文件清单唯一事实源：git ls-files → source_files 物化投影（批量写入）。
    返回 (file_count, primary_language)
    """
    import asyncio
    import time

    from topoone.engine import git_service

    # 语言映射（显示名用于项目语言，小写名用于文件语言）
    LANG_MAP_DISPLAY = {
        ".ts": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript", ".tsx": "TypeScript",
        ".py": "Python", ".go": "Go", ".rs": "Rust", ".java": "Java",
        ".cpp": "C++", ".c": "C", ".h": "C", ".cs": "C#",
        ".vue": "Vue", ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
        ".json": "JSON", ".md": "Markdown", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
        ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".kt": "Kotlin",
        ".scala": "Scala", ".dart": "Dart", ".lua": "Lua",
    }
    LANG_MAP_FILE = {
        ".ts": "typescript", ".js": "javascript", ".jsx": "javascript", ".tsx": "typescript",
        ".mts": "typescript", ".cts": "typescript", ".mjs": "javascript", ".cjs": "javascript",
        ".py": "python", ".pyw": "python", ".go": "go", ".rs": "rust", ".java": "java",
        ".c": "c", ".h": "c",
        ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
        ".cs": "c_sharp",
        ".vue": "vue", ".html": "html", ".css": "css", ".scss": "scss",
        ".json": "json", ".md": "markdown", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
        ".rb": "ruby", ".rake": "ruby", ".php": "php", ".inc": "php",
        ".swift": "swift", ".kt": "kotlin", ".kts": "kotlin",
        ".scala": "scala", ".sc": "scala",
        ".r": "r", ".sql": "sql", ".sh": "bash",
        ".dart": "dart", ".lua": "lua", ".luau": "luau",
        ".m": "objc", ".mm": "objc",
        ".perl": "perl", ".pl": "perl",
        ".elixir": "elixir", ".ex": "elixir", ".exs": "elixir",
        ".erl": "erlang", ".hs": "haskell", ".ml": "ocaml",
        ".zig": "zig", ".nim": "nim", ".v": "verilog",
    }

    file_count = 0
    dir_count = 0
    lang_counts = {}  # 扩展名 -> 计数
    batch_records = []  # 收集所有记录，事务批量写入
    BATCH_SIZE = 500  # 每 500 条提交一次
    scan_t0 = time.time()

    # git ls-files：文件清单唯一事实源（嵌套 .gitignore 等忽略语义由 git 原生保证）
    tracked = git_service.list_files(root_path)
    total_estimate = max(len(tracked), 1)
    logger.info(f"[import] git ls-files: {len(tracked)} tracked files")

    # KB 元数据目录防御性过滤（正常不会出现在 git 跟踪清单中）
    def _kb_meta(rel: str) -> bool:
        return (rel == '.topocode' or rel.startswith('.topocode/')
                or rel == '.codegraph' or rel.startswith('.codegraph/')
                or rel == '.git' or rel.startswith('.git/'))

    seen_dirs: set = set()
    for idx, rel_path in enumerate(tracked, 1):
        if _kb_meta(rel_path):
            continue

        # 每处理 200 个文件释放一次 event loop 并打印进度
        if idx % 200 == 0:
            await asyncio.sleep(0)
            elapsed = time.time() - scan_t0
            progress_pct = min(int(idx / total_estimate * 100), 99)
            logger.info(f"[import] scan progress: {idx}/{total_estimate} ({progress_pct}%), {dir_count} dirs, elapsed {elapsed:.1f}s")
            if server and project_id:
                server.publish("project", "import.progress", {
                    "path": root_path,
                    "progress": progress_pct,
                    "fileCount": file_count,
                    "totalEstimate": total_estimate,
                    "phase": "scan",
                })

        # 合成祖先目录行（getFileTree 懒加载依赖 parent_path 结构）
        parts = rel_path.split('/')[:-1]
        for i in range(len(parts)):
            d = '/'.join(parts[:i + 1])
            if d in seen_dirs:
                continue
            seen_dirs.add(d)
            dir_count += 1
            batch_records.append((
                f"dir-{_simple_hash(d)}", d, d.rsplit('/', 1)[-1],
                "directory", 0, "", (d.rsplit('/', 1)[0] if '/' in d else None),
            ))

        full_path = os.path.join(root_path, rel_path.replace('/', os.sep))
        ext = os.path.splitext(rel_path)[1].lower()

        # 统计语言
        if ext in LANG_MAP_DISPLAY:
            lang_counts[ext] = lang_counts.get(ext, 0) + 1

        file_id = f"file-{_simple_hash(rel_path)}"
        language = LANG_MAP_FILE.get(ext) or ""
        try:
            size = int(os.stat(full_path).st_size)
        except OSError:
            size = 0

        base = rel_path.rsplit('/', 1)[-1]
        fname = base.rsplit('.', 1)[0] if '.' in base else base
        parent = rel_path.rsplit('/', 1)[0] if '/' in rel_path else None
        batch_records.append((
            file_id, rel_path, fname, language, size, "", parent
        ))
        file_count += 1

    scan_elapsed = time.time() - scan_t0
    logger.info(f"[import] scan complete: {file_count} files, {dir_count} dirs, elapsed {scan_elapsed:.2f}s")

    # 打印语言分布 Top 10
    if lang_counts:
        sorted_langs = sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        lang_summary = ", ".join(f"{ext}={cnt}" for ext, cnt in sorted_langs)
        logger.info(f"[import] language distribution Top10: {lang_summary}")

    # 批量写入（executemany 已通过 WriteQueue execute_batch 自管理事务）
    if batch_records:
        write_t0 = time.time()
        num_batches = (len(batch_records) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"[import] starting batch write: {len(batch_records)} records, {num_batches} batches ({BATCH_SIZE} per batch)")
        try:
            for i in range(0, len(batch_records), BATCH_SIZE):
                chunk = batch_records[i:i + BATCH_SIZE]
                project_db.executemany(
                    """INSERT OR REPLACE INTO source_files
                       (id, file_path, file_name, language, size, content_hash, parent_path)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    chunk,
                )
                batch_num = i // BATCH_SIZE + 1
                elapsed = time.time() - write_t0
                logger.info(f"[import] write progress: batch {batch_num}/{num_batches}, written {min(i + BATCH_SIZE, len(batch_records))}/{len(batch_records)}, elapsed {elapsed:.2f}s")
                if server and project_id:
                    write_pct = int(batch_num / num_batches * 10) + 90  # 90→100
                    server.publish("project", "import.progress", {
                        "path": root_path,
                        "progress": min(write_pct, 99),
                        "fileCount": file_count,
                        "totalEstimate": total_estimate,
                        "phase": "write",
                        "batch": batch_num,
                        "totalBatches": num_batches,
                    })
        except Exception as e:
            logger.error(f"[import] batch write failed: {e}")
            raise

    # 确定主要语言（仅统计系统可解析的语言类型，避免将 HTML/JSON/Markdown 等误识别为主语言）
    SUPPORTED_LANGUAGES = {
        "python", "javascript", "typescript", "tsx",
        "java", "c", "cpp", "go", "rust", "c_sharp",
        "swift", "ruby", "kotlin", "php", "dart",
        "scala", "lua", "luau", "objc",
    }
    if not lang_counts:
        primary_language = "Unknown"
    else:
        supported_counts = {}
        for ext, count in lang_counts.items():
            lang_key = LANG_MAP_FILE.get(ext, "")
            if lang_key in SUPPORTED_LANGUAGES:
                supported_counts[ext] = count
        if supported_counts:
            primary_ext = max(supported_counts, key=supported_counts.get)
            primary_language = LANG_MAP_DISPLAY.get(primary_ext, "Unknown")
        else:
            primary_ext = max(lang_counts, key=lang_counts.get)
            primary_language = LANG_MAP_DISPLAY.get(primary_ext, "Unknown")

    total_elapsed = time.time() - scan_t0
    logger.info(f"[import] _scan_and_import done: {file_count} files, language={primary_language}, total {total_elapsed:.2f}s")

    return file_count, primary_language
def _scan_file_tree(project_db: SQLiteContext, root_path: str) -> int:
    """
    git ls-files → source_files 物化投影（相对路径，不算 MD5）
    返回文件数量
    """
    from topoone.engine import git_service

    lang_map = {
        ".ts": "typescript", ".js": "javascript", ".jsx": "javascript", ".tsx": "typescript",
        ".mts": "typescript", ".cts": "typescript", ".mjs": "javascript", ".cjs": "javascript",
        ".py": "python", ".pyw": "python", ".go": "go", ".rs": "rust", ".java": "java",
        ".c": "c", ".h": "c",
        ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
        ".cs": "c_sharp",
        ".vue": "vue", ".html": "html", ".css": "css", ".scss": "scss",
        ".json": "json", ".md": "markdown", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
        ".rb": "ruby", ".rake": "ruby", ".php": "php", ".inc": "php",
        ".swift": "swift", ".kt": "kotlin", ".kts": "kotlin",
        ".scala": "scala", ".sc": "scala",
        ".r": "r", ".sql": "sql", ".sh": "bash",
        ".dart": "dart", ".lua": "lua", ".luau": "luau",
        ".m": "objc", ".mm": "objc",
        ".perl": "perl", ".pl": "perl",
        ".elixir": "elixir", ".ex": "elixir", ".exs": "elixir",
        ".erl": "erlang", ".hs": "haskell", ".ml": "ocaml",
        ".zig": "zig", ".nim": "nim", ".v": "verilog",
    }

    batch = []
    seen_dirs: set = set()
    file_count = 0
    for rel_path in git_service.list_files(root_path):
        # KB 元数据目录防御性过滤
        if rel_path == '.topocode' or rel_path.startswith('.topocode/') \
                or rel_path == '.codegraph' or rel_path.startswith('.codegraph/') \
                or rel_path == '.git' or rel_path.startswith('.git/'):
            continue

        # 合成祖先目录行（getFileTree 懒加载依赖 parent_path 结构）
        parts = rel_path.split('/')[:-1]
        for i in range(len(parts)):
            d = '/'.join(parts[:i + 1])
            if d in seen_dirs:
                continue
            seen_dirs.add(d)
            batch.append((
                f"dir-{_simple_hash(d)}", d, d.rsplit('/', 1)[-1],
                "directory", 0, "", (d.rsplit('/', 1)[0] if '/' in d else None),
            ))

        full_path = os.path.join(root_path, rel_path.replace('/', os.sep))
        ext = os.path.splitext(rel_path)[1].lower()
        try:
            size = int(os.stat(full_path).st_size)
        except OSError:
            size = 0
        base = rel_path.rsplit('/', 1)[-1]
        fname = base.rsplit('.', 1)[0] if '.' in base else base
        parent = rel_path.rsplit('/', 1)[0] if '/' in rel_path else None
        batch.append((
            f"file-{_simple_hash(rel_path)}", rel_path, fname,
            lang_map.get(ext) or "", size, "", parent,
        ))
        file_count += 1

    if batch:
        project_db.executemany(
            """INSERT OR REPLACE INTO source_files
               (id, file_path, file_name, language, size, content_hash, parent_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )

    return file_count
def _simple_hash(path: str) -> str:
    """简单哈希"""
    import hashlib
    return hashlib.md5(path.encode()).hexdigest()[:12]


def _build_flat_children(files: list, fromPath: str) -> list:
    """从指定目录的文件列表构建扁平子节点（懒加载用）
    file_path 格式为 fromPath/子节点名，直接提取子节点名
    """
    result = []
    prefix = f"{fromPath}/"
    for f in files:
        file_path = f["file_path"]
        # 去掉 fromPath 前缀，得到子节点名
        if file_path.startswith(prefix):
            child_name = file_path[len(prefix):]
        else:
            # 如果 file_path 就是 fromPath 本身（目录节点），直接使用
            child_name = file_path

        is_dir = f.get("language") == "directory"
        node = {
            "name": child_name,
            "type": "directory" if is_dir else "file",
            "path": file_path,
        }
        if not is_dir:
            node["language"] = f.get("language")
            node["size"] = f.get("size")
        else:
            node["children"] = []
            # 检查是否为空目录：parent_path=fromPath 且 language=directory 的记录，
            # 如果该目录下没有其他文件，则为空目录
            # 这里简化处理：如果 files 中只有这个目录本身，没有其子路径的文件，则为空
            sub_files = [ff for ff in files if ff["file_path"].startswith(f"{file_path}/")]
            node["is_empty"] = len(sub_files) == 0
        result.append(node)

    # 排序：文件夹在前，文件在后，各自按名称字母排序
    result.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
    return result
def _build_file_tree(files: list, include_children: bool = True) -> list:
    """从扁平文件列表构建树形结构"""
    # 按层级分组
    tree = {}
    for f in files:
        parts = f["file_path"].replace('\\', '/').split('/')
        current = tree
        for part in parts[:-1]:
            if part not in current:
                current[part] = {"_children": {}}
            current = current[part]["_children"]

        # 区分目录和文件
        if f.get("language") == "directory":
            # 目录节点 — 确保存在
            if parts[-1] not in current:
                current[parts[-1]] = {"_children": {}}
        else:
            # 文件节点
            current[parts[-1]] = {
                "type": "file",
                "language": f.get("language"),
                "size": f.get("size"),
                "path": f.get("file_path"),
            }

    return _flatten_tree(tree, include_children=include_children)
def _is_empty_dir(tree_node: dict) -> bool:
    """检查目录节点是否为空目录（无文件，只有空子目录）"""
    if "type" in tree_node:
        return False  # 文件节点
    children = tree_node.get("_children", {})
    if not children:
        return True
    # 递归检查所有子节点是否都是空目录
    return all(_is_empty_dir(v) for v in children.values())
def _count_empty_chain(tree_node: dict) -> int:
    """计算连续空目录链的长度"""
    if "type" in tree_node:
        return 0  # 文件节点，链终止
    children = tree_node.get("_children", {})
    if not children:
        return 1  # 空目录
    # 只有一条子链且也是空目录时，累加
    if len(children) == 1:
        child = list(children.values())[0]
        if _is_empty_dir(child):
            return 1 + _count_empty_chain(child)
    return 0
def _flatten_tree(tree: dict, parent_path: str = "", include_children: bool = True) -> list:
    """扁平化树形结构，为每个节点设置正确的 path
    include_children: 是否递归包含子节点（懒加载时设为 False）
    """
    result = []
    for name, data in tree.items():
        current_path = f"{parent_path}/{name}" if parent_path else name
        if "_children" in data:
            is_empty = _is_empty_dir(data)
            node = {
                "name": name,
                "type": "directory",
                "path": current_path,
                "is_empty": is_empty,
                "children": _flatten_tree(data["_children"], current_path) if include_children else [],
            }
            result.append(node)
        else:
            result.append({
                "name": name,
                "type": "file",
                "language": data.get("language"),
                "size": data.get("size"),
                "path": data.get("path") or current_path,
            })
    # 排序：文件夹在前，文件在后，各自按名称字母排序
    result.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
    return result
def _export_graph_data(multi_db: MultiDBManager, project_id: str) -> dict:
    """导出项目 graph 数据（JSON 格式）"""
    project_db = multi_db.get_project_db(project_id)

    return {
        "projectId": project_id,
        "exportedAt": datetime.now().isoformat(),
        "schemaVersion": "1.0.0",
        "dependencies": project_db.fetchall("SELECT * FROM dependencies"),
        "callChains": project_db.fetchall("SELECT * FROM call_chains"),
        "components": project_db.fetchall("SELECT * FROM components"),
    }


# ==================== 报告生成辅助方法 ====================
