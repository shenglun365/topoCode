"""Core Service - 方法注册 + 业务逻辑 (多数据库架构)"""

import asyncio
import fnmatch
import hashlib
import json
import os

import re
import shutil
import uuid
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from sqlite_ctx import SQLiteContext, MultiDBManager
from zmq_server import ZMQServer

# 解析任务线程池 - 隔离 CPU 密集型工作，不阻塞 ZMQ 事件循环
parse_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="parse-worker")



# ==================== .gitignore 解析器 ====================

class GitIgnoreParser:
    """完整的 .gitignore 语法解析器"""

    def __init__(self):
        self.patterns: list[tuple[str, bool]] = []  # (pattern, negated)

    def load_file(self, filepath: str) -> 'GitIgnoreParser':
        """从文件加载规则"""
        if not os.path.exists(filepath):
            return self
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                self.add_pattern(line.strip())
        return self

    def add_pattern(self, pattern: str):
        """添加单个规则"""
        if not pattern or pattern.startswith('#'):
            return
        negated = pattern.startswith('!')
        if negated:
            pattern = pattern[1:]
        # 处理尾随斜杠 (目录匹配)
        is_dir_only = pattern.endswith('/')
        if is_dir_only:
            pattern = pattern[:-1]
        # 转义通配符
        if is_dir_only:
            pattern = pattern + '/'
        self.patterns.append((pattern, negated))

    def is_ignored(self, path: str, is_dir: bool = False) -> bool:
        """检查路径是否被忽略"""
        # 规范化路径
        path = path.lstrip('/')
        parts = path.split('/')

        for pattern, negated in self.patterns:
            matches = self._match_pattern(pattern, path, parts, is_dir)
            if matches:
                if negated:
                    return False  # 否定规则，取消忽略
                else:
                    return True  # 匹配到忽略规则

        return False

    def _match_pattern(self, pattern: str, path: str, parts: list[str], is_dir: bool) -> bool:
        """匹配单个模式"""
        # 目录专用模式
        if pattern.endswith('/'):
            if not is_dir:
                # 文件也匹配父目录模式
                dir_pattern = pattern[:-1]
                for i in range(len(parts)):
                    subpath = '/'.join(parts[:i + 1])
                    if fnmatch.fnmatch(subpath, dir_pattern):
                        return True
                return False
            else:
                pattern = pattern[:-1]

        # 锚定模式 (以/开头)
        if pattern.startswith('/'):
            pattern = pattern[1:]
            return fnmatch.fnmatch(path, pattern)

        # 包含/的模式 (锚定)
        if '/' in pattern:
            return fnmatch.fnmatch(path, pattern)

        # 否则匹配 basename 或任何路径段
        basename = parts[-1]
        if fnmatch.fnmatch(basename, pattern):
            return True
        for i in range(len(parts)):
            subpath = '/'.join(parts[i:])
            if fnmatch.fnmatch(subpath, pattern):
                return True

        return False


# 默认忽略模式
DEFAULT_IGNORE_PATTERNS = [
    # 构建产物
    'node_modules/', 'dist/', 'build/', '.next/', '.nuxt/',
    '__pycache__/', '*.pyc', '*.pyo', '*.pyd', '.Python/',
    'env/', 'venv/', '.venv/',
    'target/', 'out/', 'bin/', 'obj/',
    '*.o', '*.a', '*.so', '*.dylib', '*.dll', '*.exe',
    # 包管理器
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'poetry.lock', 'Cargo.lock', 'Go.sum',
    '*.egg-info/', '*.egg', '.eggs/',
    # IDE
    '.idea/', '.vscode/', '*.swp', '*.swo', '*~',
    '.DS_Store', 'Thumbs.db',
    # 日志
    '*.log', 'npm-debug.log*', 'yarn-debug.log*',
    # 临时文件
    'tmp/', 'temp/', '.cache/',
]


def should_ignore_file(rel_path: str, gitignore_parser: GitIgnoreParser | None = None, is_dir: bool = False) -> bool:
    """检查文件是否应该被忽略"""
    # 检查 .gitignore
    if gitignore_parser:
        if gitignore_parser.is_ignored(rel_path, is_dir):
            return True

    # 检查默认忽略模式
    for pattern in DEFAULT_IGNORE_PATTERNS:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if fnmatch.fnmatch(os.path.basename(rel_path), pattern):
            return True

    return False


# ==================== 项目管理方法 ====================

def register_project_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册项目管理方法"""
    main_db = multi_db.main_db

    @server.register("project.list")
    def list_projects():
        rows = main_db.fetchall("SELECT * FROM projects ORDER BY updated_at DESC")
        for row in rows:
            if row.get("tags"):
                row["tags"] = json.loads(row["tags"])
        return rows

    @server.register("project.import")
    def import_project(path: str):
        if not os.path.isdir(path):
            raise FileNotFoundError(f"Directory not found: {path}")

        # 加载 .gitignore
        gitignore = GitIgnoreParser().load_file(os.path.join(path, '.gitignore'))

        # 检测语言（统计最多语言）
        language = _detect_language(path, gitignore)

        # 创建项目库
        project_id = f"proj-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        # 扫描文件树（相对路径 + MD5，应用 gitignore）
        project_db = multi_db.init_project_db(project_id)
        file_count = _scan_file_tree(project_db, path, path, None, gitignore)

        # 插入主库
        main_db.insert("projects", {
            "id": project_id,
            "name": os.path.basename(path),
            "root_path": path,
            "language": language,
            "file_count": file_count,
            "status": "synced",
            "needs_resync": 0,
            "has_file_changes": 0,
            "is_sample": 0,
            "last_sync": now,
        })

        return main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))

    @server.register("project.get")
    def get_project(id: str):
        return main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))

    @server.register("project.remove")
    def remove_project(id: str):
        # 删除项目库
        multi_db.delete_project_db(id)
        # 删除主库记录
        main_db.delete("projects", "id = ?", (id,))

    @server.register("project.sync")
    async def sync_project(id: str):
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))
        if not project:
            raise ValueError(f"Project not found: {id}")

        main_db.update("projects", {"status": "syncing", "updated_at": datetime.now().isoformat()}, "id = ?", (id,))
        server.publish("project", "syncing", {"projectId": id, "progress": 0})

        project_db = multi_db.get_project_db(id)
        root_path = project["root_path"]

        # 加载 .gitignore
        gitignore = GitIgnoreParser().load_file(os.path.join(root_path, '.gitignore'))

        # 清空旧文件
        project_db.execute("DELETE FROM source_files")

        # 重新扫描
        file_count = _scan_file_tree(project_db, root_path, root_path, None, gitignore)

        # 重新检测语言
        language = _detect_language(root_path, gitignore)

        main_db.update("projects", {
            "file_count": file_count,
            "language": language,
            "status": "synced",
            "last_sync": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "has_file_changes": 0,
        }, "id = ?", (id,))

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

        return {
            "project": main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,)),
            "invalidFiles": invalid_files,
            "needsResync": len(invalid_files) > 0,
        }

    @server.register("project.checkFileChanges")
    def check_file_changes(id: str):
        """对比文件系统与 source_files.content_hash，返回变更列表（应用 gitignore 过滤）"""
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))
        if not project:
            raise ValueError(f"Project not found: {id}")

        project_db = multi_db.get_project_db(id)
        root_path = project["root_path"]

        # 加载 .gitignore
        gitignore = GitIgnoreParser().load_file(os.path.join(root_path, '.gitignore'))

        # 获取数据库中所有文件
        db_files = project_db.fetchall("SELECT file_path, content_hash FROM source_files")
        db_file_map = {f["file_path"]: f["content_hash"] for f in db_files}

        # 扫描当前文件系统（应用 gitignore）
        current_files = {}
        for dirpath, dirnames, filenames in os.walk(root_path):
            rel_root = os.path.relpath(dirpath, root_path)
            # 过滤被忽略的目录
            dirnames[:] = [d for d in dirnames if not should_ignore_file(
                os.path.join(rel_root, d) if rel_root != '.' else d, gitignore, is_dir=True)]

            for filename in filenames:
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, root_path)
                # 跳过被忽略的文件
                if should_ignore_file(rel_path, gitignore):
                    continue
                content_hash = multi_db.compute_md5(full_path)
                current_files[rel_path] = content_hash

        # 对比变更
        added = []
        modified = []
        deleted = []

        for rel_path, hash_val in current_files.items():
            if rel_path not in db_file_map:
                added.append(rel_path)
            elif db_file_map[rel_path] != hash_val:
                modified.append(rel_path)

        for rel_path in db_file_map:
            if rel_path not in current_files:
                deleted.append(rel_path)

        has_changes = bool(added or modified or deleted)

        # 更新状态
        if has_changes:
            main_db.update("projects", {"has_file_changes": 1}, "id = ?", (id,))

        return {
            "added": added,
            "modified": modified,
            "deleted": deleted,
            "hasChanges": has_changes,
        }

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
            project_db.conn.commit()

        return True

    @server.register("system.exportProject")
    def export_project(project_id: str, outputPath: str):
        """导出项目库为 .topoone-archive (zip)"""
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        project_db_path = os.path.join(multi_db.data_dir, f"{project_id}.db")
        if not os.path.exists(project_db_path):
            raise FileNotFoundError(f"Project database not found: {project_id}")

        # 创建临时目录
        temp_dir = os.path.join(multi_db.data_dir, f"export_{project_id}")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            # 复制项目库
            shutil.copy2(project_db_path, os.path.join(temp_dir, f"{project_id}.db"))

            # 导出 graph 文件（JSON 格式）
            graph_data = _export_graph_data(multi_db, project_id)
            graph_path = os.path.join(temp_dir, "graph.json")
            with open(graph_path, "w", encoding="utf-8") as f:
                json.dump(graph_data, f, ensure_ascii=False, indent=2)

            # 打包为 zip
            archive_path = f"{outputPath}.topoone-archive" if not outputPath.endswith(".topoone-archive") else outputPath
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zf.write(file_path, arcname)

            return {"archivePath": archive_path, "size": os.path.getsize(archive_path)}
        finally:
            # 清理临时目录
            shutil.rmtree(temp_dir, ignore_errors=True)

    @server.register("system.importProject")
    def import_project_archive(archivePath: str):
        """导入项目数据包"""
        if not os.path.exists(archivePath):
            raise FileNotFoundError(f"Archive not found: {archivePath}")

        # 解压到临时目录
        temp_dir = os.path.join(multi_db.data_dir, f"import_{uuid.uuid4().hex[:8]}")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(archivePath, "r") as zf:
                zf.extractall(temp_dir)

            # 查找 .db 文件
            db_files = [f for f in os.listdir(temp_dir) if f.endswith(".db")]
            if not db_files:
                raise ValueError("No database file found in archive")

            db_file = db_files[0]
            project_id = db_file.replace(".db", "")

            # 复制项目库到目标位置
            target_db_path = os.path.join(multi_db.data_dir, db_file)
            shutil.copy2(os.path.join(temp_dir, db_file), target_db_path)

            # 在主库中创建项目记录
            project_db = multi_db.get_project_db(project_id)
            existing_project = main_db.fetchone("SELECT id FROM projects WHERE id = ?", (project_id,))

            if not existing_project:
                # 尝试从 project_config 获取项目信息，或使用默认值
                now = datetime.now().isoformat()
                main_db.insert("projects", {
                    "id": project_id,
                    "name": f"Imported Project ({project_id[:8]})",
                    "root_path": "",
                    "language": "Unknown",
                    "file_count": 0,
                    "status": "error",
                    "needs_resync": 1,
                    "has_file_changes": 0,
                    "is_sample": 0,
                    "created_at": now,
                    "updated_at": now,
                })

            return {"projectId": project_id, "status": "imported"}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return server


# ==================== 代码分析方法 ====================

def register_analysis_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册代码分析方法"""
    main_db = multi_db.main_db

    @server.register("analysis.listTasks")
    def list_tasks(project_id: str = None, projectId: str = None):
        pid = project_id or projectId
        # 获取任务列表，LEFT JOIN 运行记录获取统计信息
        rows = main_db.fetchall("""
            SELECT t.*,
                   COALESCE(r.run_count, 0) as run_count,
                   r.last_run_status,
                   r.last_run_number
            FROM analysis_tasks t
            LEFT JOIN (
                SELECT task_id,
                       COUNT(*) as run_count,
                       MAX(run_number) as last_run_number,
                       status as last_run_status
                FROM analysis_task_runs
                GROUP BY task_id
            ) r ON t.id = r.task_id
            WHERE t.project_id = ?
            ORDER BY t.updated_at DESC
        """, (pid,))
        for row in rows:
            if row.get("tags"):
                row["tags"] = json.loads(row["tags"])
            if row.get("scopes"):
                row["scopes"] = json.loads(row["scopes"])
            if row.get("extensions"):
                row["extensions"] = json.loads(row["extensions"])
            if row.get("exclude_dirs"):
                row["exclude_dirs"] = json.loads(row["exclude_dirs"])
            if row.get("report_types"):
                row["report_types"] = json.loads(row["report_types"])
        return rows

    @server.register("analysis.createTask")
    def create_task(project_id: str = None, projectId: str = None, type: str = None, name: str = None, scope: str = None, scopes: list = None, extensions: list = None, exclude_dirs: list = None, excludeDirs: list = None, report_types: list = None, reportTypes: list = None, pattern_type: str = None, patternType: str = None, pattern: str = None):
        pid = project_id or projectId
        # UUID v4 格式
        task_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        # 兼容 camelCase 参数
        ext = extensions or excludeDirs or []
        excl = exclude_dirs or excludeDirs or []
        rpt = report_types or reportTypes or []

        # 如果没有提供名称，使用 UUID 作为默认名称
        task_name = name if name else task_id

        pt = pattern_type or patternType
        main_db.insert("analysis_tasks", {
            "id": task_id,
            "project_id": pid,
            "type": type,
            "name": task_name,
            "status": "pending",
            "total": 100,
            "scope": scope,
            "scopes": json.dumps(scopes) if scopes else None,
            "extensions": json.dumps(ext) if ext else None,
            "exclude_dirs": json.dumps(excl) if excl else None,
            "report_types": json.dumps(rpt) if rpt else None,
            "pattern_type": pt,
            "pattern": pattern,
            "config_version": 1,
            "created_at": now,
            "updated_at": now,
        })

        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        # JSON 解析数组字段，确保前端收到的是 JS 数组而非字符串
        for key in ("scopes", "extensions", "exclude_dirs", "report_types", "tags"):
            if task.get(key) and isinstance(task[key], str):
                try:
                    task[key] = json.loads(task[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        logger.info(f"[analysis.createTask] id={task_id} name={task_name} projectId={pid} scopes={scopes}")
        return task

    @server.register("analysis.runTask")
    async def run_task(task_id: str = None, taskId: str = None):
        task_id = task_id or taskId
        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        if task.get("status") == "running":
            raise ValueError(f"Task is already running: {task_id}")

        # 获取当前运行次数
        run_count_row = main_db.fetchone(
            "SELECT COALESCE(MAX(run_number), 0) as cnt FROM analysis_task_runs WHERE task_id = ?",
            (task_id,)
        )
        run_number = (run_count_row["cnt"] if run_count_row else 0) + 1

        # 创建运行记录
        run_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        main_db.insert("analysis_task_runs", {
            "id": run_id,
            "task_id": task_id,
            "run_number": run_number,
            "status": "running",
            "progress": 0,
            "total": task.get("total", 100),
            "current": 0,
            "started_at": now,
            "snapshot_scope": task.get("scope"),
            "snapshot_scopes": task.get("scopes"),
            "snapshot_extensions": task.get("extensions"),
            "snapshot_exclude_dirs": task.get("exclude_dirs"),
            "snapshot_report_types": task.get("report_types"),
        })

        # 更新任务状态
        main_db.update("analysis_tasks", {
            "status": "running",
            "progress": 0,
            "current": 0,
            "last_run_id": run_id,
            "updated_at": now,
        }, "id = ?", (task_id,))

        asyncio.create_task(_execute_task(server, main_db, multi_db, task_id, run_id))

        return {"taskId": task_id, "runId": run_id, "runNumber": run_number, "status": "running"}

    @server.register("analysis.getTask")
    def get_task(task_id: str = None, taskId: str = None):
        task_id = task_id or taskId
        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        if task:
            # 解析 JSON 字段为数组
            for key in ("scopes", "extensions", "exclude_dirs", "report_types", "tags"):
                if task.get(key) and isinstance(task[key], str):
                    try:
                        task[key] = json.loads(task[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
        return task

    @server.register("analysis.getResults")
    def get_results(task_id: str = None, taskId: str = None):
        task_id = task_id or taskId
        # 优先获取最后一次运行的报告
        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        if task and task.get("last_run_id"):
            report = main_db.fetchone("SELECT * FROM analysis_reports WHERE run_id = ?", (task["last_run_id"],))
        else:
            report = main_db.fetchone("SELECT * FROM analysis_reports WHERE task_id = ? ORDER BY created_at DESC LIMIT 1", (task_id,))

        if not report:
            return {
                "ast": {"type": "Program", "body": []},
                "callChain": [],
                "dependencies": {"modules": [], "files": []},
                "dataflow": [],
            }

        return {
            "ast": json.loads(report.get("ast_data") or "{}"),
            "callChain": json.loads(report.get("call_chain") or "[]"),
            "dependencies": json.loads(report.get("dependencies") or "{}"),
            "dataflow": json.loads(report.get("dataflow") or "[]"),
        }

    @server.register("analysis.updateTask")
    def update_task(task_id: str = None, taskId: str = None, **kwargs):
        task_id = task_id or taskId
        allowed = {"favorite", "pinned", "tags"}
        data = {k: v for k, v in kwargs.items() if k in allowed}
        if "tags" in data:
            data["tags"] = json.dumps(data["tags"])
        data["updated_at"] = datetime.now().isoformat()

        main_db.update("analysis_tasks", data, "id = ?", (task_id,))
        updated = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        # 解析 JSON 字段
        if updated:
            for key in ("extensions", "exclude_dirs", "report_types", "tags"):
                if updated.get(key) and isinstance(updated[key], str):
                    try:
                        updated[key] = json.loads(updated[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
        return updated

    @server.register("analysis.deleteTask")
    def delete_task(task_id: str = None, taskId: str = None):
        task_id = task_id or taskId
        main_db.delete("analysis_tasks", "id = ?", (task_id,))

    @server.register("analysis.stopTask")
    def stop_task(task_id: str = None, taskId: str = None):
        task_id = task_id or taskId
        """停止正在运行的分析任务"""
        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        if task["status"] != "running":
            raise ValueError(f"Task is not running (status={task['status']})")

        now = datetime.now().isoformat()

        # 更新任务状态
        main_db.update("analysis_tasks", {
            "status": "stopped",
            "updated_at": now,
        }, "id = ?", (task_id,))

        # 更新当前运行记录的状态
        if task.get("last_run_id"):
            main_db.update("analysis_task_runs", {
                "status": "stopped",
                "finished_at": now,
            }, "id = ?", (task["last_run_id"],))

        return {"taskId": task_id, "status": "stopped"}

    @server.register("analysis.reRunTask")
    async def re_run_task(task_id: str = None, taskId: str = None):
        task_id = task_id or taskId
        """使用原任务配置重新执行，创建新的运行记录"""
        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        if task.get("status") == "running":
            raise ValueError(f"Task is already running: {task_id}")

        # 获取当前运行次数
        run_count_row = main_db.fetchone(
            "SELECT COALESCE(MAX(run_number), 0) as cnt FROM analysis_task_runs WHERE task_id = ?",
            (task_id,)
        )
        run_number = (run_count_row["cnt"] if run_count_row else 0) + 1

        run_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        main_db.insert("analysis_task_runs", {
            "id": run_id,
            "task_id": task_id,
            "run_number": run_number,
            "status": "running",
            "progress": 0,
            "total": task.get("total", 100),
            "current": 0,
            "started_at": now,
            "snapshot_scope": task.get("scope"),
            "snapshot_scopes": task.get("scopes"),
            "snapshot_extensions": task.get("extensions"),
            "snapshot_exclude_dirs": task.get("exclude_dirs"),
            "snapshot_report_types": task.get("report_types"),
        })

        # 更新任务状态
        main_db.update("analysis_tasks", {
            "status": "running",
            "progress": 0,
            "current": 0,
            "last_run_id": run_id,
            "updated_at": now,
        }, "id = ?", (task_id,))

        asyncio.create_task(_execute_task(server, main_db, multi_db, task_id, run_id))

        return main_db.fetchone("SELECT * FROM analysis_task_runs WHERE id = ?", (run_id,))

    @server.register("analysis.getTaskRuns")
    def get_task_runs(task_id: str = None, taskId: str = None):
        task_id = task_id or taskId
        """获取任务的运行历史"""
        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        runs = main_db.fetchall(
            "SELECT * FROM analysis_task_runs WHERE task_id = ? ORDER BY run_number DESC",
            (task_id,)
        )
        # 反序列化快照字段
        for run in runs:
            for key in ("snapshot_scope", "snapshot_extensions", "snapshot_exclude_dirs", "snapshot_report_types"):
                val = run.get(key)
                if val:
                    try:
                        run[key] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
        return runs

    @server.register("analysis.getTaskLogs")
    def get_task_logs(task_id: str = None, taskId: str = None, run_id: str = None, runId: str = None):
        # Handle nested params from frontend: { taskId: { taskId: '...', runId: '...' } }
        if isinstance(taskId, dict):
            task_id = task_id or taskId.get("taskId")
            run_id = run_id or taskId.get("runId")
        else:
            task_id = task_id or taskId
            run_id = run_id or runId
        """获取任务的执行日志，支持按运行实例读取"""
        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        # 如果指定了 run_id，按 run_id 查找；否则按 last_run_id 或 task_id
        if run_id:
            report = main_db.fetchone("SELECT * FROM analysis_reports WHERE run_id = ?", (run_id,))
        elif task.get("last_run_id"):
            report = main_db.fetchone("SELECT * FROM analysis_reports WHERE run_id = ?", (task["last_run_id"],))
        else:
            report = main_db.fetchone("SELECT * FROM analysis_reports WHERE task_id = ? ORDER BY created_at DESC LIMIT 1", (task_id,))

        logs = []
        if report and report.get("logs"):
            logs = json.loads(report.get("logs"))

        # 获取当前运行记录的状态
        current_run = None
        if run_id:
            current_run = main_db.fetchone("SELECT * FROM analysis_task_runs WHERE id = ?", (run_id,))
        elif task.get("last_run_id"):
            current_run = main_db.fetchone("SELECT * FROM analysis_task_runs WHERE id = ?", (task["last_run_id"],))

        completed = False
        if current_run:
            completed = current_run["status"] in ("done", "error", "stopped")
        else:
            completed = task["status"] in ("done", "error", "stopped")

        return {
            "logs": logs,
            "completed": completed,
        }

    @server.register("analysis.updateTaskConfig")
    def update_task_config(task_id: str = None, taskId: str = None, **kwargs):
        task_id = task_id or taskId
        # 前端传参: { taskId: '...', config: { name: '...', extensions: ['vue'] } }
        config = kwargs.get("config", {})
        if not config:
            config = kwargs  # fallback: 直接传参
        # 修复前端传来的 extensions 被拆成字符的问题
        if "extensions" in config and isinstance(config["extensions"], list):
            exts = config["extensions"]
            # 检测是否是字符数组（JSON 字符串被拆成字符）
            if all(isinstance(e, str) and len(e) <= 1 for e in exts):
                joined = "".join(exts)
                try:
                    config["extensions"] = json.loads(joined)
                except (json.JSONDecodeError, TypeError):
                    pass
        """更新任务的配置（编辑功能）- 变更前保存旧配置到历史表"""
        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        if task["status"] == "running":
            raise ValueError("Cannot update config of running task")

        # 保存旧配置到历史表
        import uuid as uuid_mod
        history_id = f"hist-{uuid_mod.uuid4().hex[:12]}"
        main_db.insert("task_config_history", {
            "id": history_id,
            "task_id": task_id,
            "config_version": task.get("config_version") or 1,
            "name": task.get("name"),
            "scope": task.get("scope"),
            "scopes": task.get("scopes"),
            "extensions": task.get("extensions"),
            "exclude_dirs": task.get("exclude_dirs"),
            "report_types": task.get("report_types"),
            "pattern_type": task.get("pattern_type"),
            "pattern": task.get("pattern"),
        })

        # 兼容 camelCase 和 snake_case
        field_map = {
            "excludeDirs": "exclude_dirs",
            "reportTypes": "report_types",
            "patternType": "pattern_type",
            "exclude_dirs": "exclude_dirs",
            "report_types": "report_types",
            "pattern_type": "pattern_type",
        }
        allowed = {"name", "scope", "scopes", "extensions", "exclude_dirs", "report_types", "pattern_type", "pattern", "patternType"}
        data = {}
        for k, v in config.items():
            if v is None:
                continue
            mapped = field_map.get(k, k)
            if mapped in allowed:
                data[mapped] = v
        # 序列化列表字段
        for key in ("scopes", "extensions", "exclude_dirs", "report_types"):
            if key in data and isinstance(data[key], list):
                data[key] = json.dumps(data[key])

        # 版本号 +1，更新状态为 pending（等待重新运行）
        data["config_version"] = (task.get("config_version") or 1) + 1
        data["status"] = "pending"
        data["updated_at"] = datetime.now().isoformat()

        main_db.update("analysis_tasks", data, "id = ?", (task_id,))
        updated = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
        # 解析 JSON 字段
        if updated:
            for key in ("extensions", "exclude_dirs", "report_types", "tags"):
                if updated.get(key) and isinstance(updated[key], str):
                    try:
                        updated[key] = json.loads(updated[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
        return updated

    @server.register("analysis.scanFileStats")
    def scan_file_stats(project_id: str = None, projectId: str = None, scope: str = None, scopes: list = None, pattern_type: str = "all", patternType: str = None, pattern: str = None, exclude_dirs: list = None, excludeDirs: list = None, selected_extensions: list = None, selectedExtensions: list = None):
        """从 SQLite source_files 表读取文件类型分布统计，支持目录多选"""
        import logging
        logger = logging.getLogger(__name__)
        pid = project_id or projectId
        pt = pattern_type or patternType or "all"
        ed = exclude_dirs or excludeDirs or []
        sel_ext = selected_extensions or selectedExtensions or []
        logger.info(f"[scanFileStats] called: pid={pid}, pt={pt}, scope={scope}, scopes={scopes}, ed={ed}, sel_ext={sel_ext}")
        logger.info(f"[scanFileStats] ALL params: project_id={project_id}, projectId={projectId}, scope={scope}, scopes={scopes}, pattern_type={pattern_type}, patternType={patternType}, pattern={pattern}, exclude_dirs={exclude_dirs}, excludeDirs={excludeDirs}, selected_extensions={selected_extensions}, selectedExtensions={selectedExtensions}")
        project_db = multi_db.get_project_db(pid)

        # 构建 WHERE 子句
        where_clauses = []
        params = []

        # 支持 scopes 多选（优先）或 scope 单选
        active_scopes = scopes if scopes else ([scope] if scope else [])
        if active_scopes:
            placeholders = " OR ".join(["file_path LIKE ?" for _ in active_scopes])
            where_clauses.append(f"(({placeholders}))")
            params.extend([f"{s}/%" for s in active_scopes])

        if ed:
            for d in ed:
                where_clauses.append("file_path NOT LIKE ?")
                params.append(f"%/{d}/%")
                where_clauses.append("file_path NOT LIKE ?")
                params.append(f"{d}/%")

        if pt == "glob" and pattern:
            sql_pattern = pattern.replace('*', '%')
            where_clauses.append("file_path LIKE ?")
            params.append(sql_pattern)

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # 按语言分组统计
        rows = project_db.fetchall(
            f"SELECT language, COUNT(*) as count, SUM(size) as total_size FROM source_files {where_sql} GROUP BY language ORDER BY count DESC",
            params
        )
        extensions = {}
        total_files = 0
        for row in rows:
            lang = row.get("language") or "unknown"
            extensions[lang] = row["count"]
            total_files += row["count"]

        # 提取目录列表 (在原有 WHERE 基础上加条件)
        dir_where = where_sql
        dir_params = list(params)
        if dir_where:
            dir_where += " AND parent_path IS NOT NULL"
        else:
            dir_where = "WHERE parent_path IS NOT NULL"
        dir_rows = project_db.fetchall(
            f"SELECT DISTINCT parent_path FROM source_files {dir_where} ORDER BY parent_path",
            dir_params
        )
        directories = [r["parent_path"] for r in dir_rows if r["parent_path"]]

        # 正则匹配处理：如果 pt == 'regex'，在 Python 层过滤
        if pt == "regex" and pattern:
            import re
            try:
                regex = re.compile(pattern)
                # 重新从数据库取所有 file_path 来过滤
                all_files = project_db.fetchall(
                    f"SELECT file_path, language, size FROM source_files {where_sql}",
                    params if where_sql else []
                )
                filtered = [f for f in all_files if regex.search(f["file_path"])]
                extensions = {}
                total_files = 0
                for f in filtered:
                    lang = f.get("language") or "unknown"
                    extensions[lang] = extensions.get(lang, 0) + 1
                    total_files += 1
                # 重新提取目录
                filtered_dirs = set()
                for f in filtered:
                    parts = f["file_path"].rsplit('/', 1)
                    if len(parts) > 1:
                        filtered_dirs.add(parts[0])
                directories = sorted(filtered_dirs)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern: {e}")

        result = {
            "extensions": extensions,
            "totalFiles": total_files,
            "totalDirs": len(directories),
            "directories": directories,
        }
        logger.info(f"[scanFileStats] returning: totalFiles={total_files}, totalDirs={len(directories)}, dirs={directories[:5]}..., exts={list(extensions.keys())[:5]}...")
        return result

    return server


# ==================== 知识库方法 ====================

def register_knowledge_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册知识库方法"""
    knowledge_db = multi_db.knowledge_db

    @server.register("knowledge.listDocs")
    def list_docs(search: str = "", dimensions: dict = None, sort_by: str = "updated-desc"):
        query = "SELECT * FROM knowledge_docs WHERE 1=1"
        params = []

        if search:
            query += " AND (title LIKE ? OR description LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        if sort_by == "created":
            order = "created_at DESC"
        else:
            order = "updated_at DESC"

        query += f" ORDER BY pinned DESC, favorite DESC, {order}"

        rows = knowledge_db.fetchall(query, tuple(params))
        for row in rows:
            if row.get("tags"):
                row["tags"] = json.loads(row["tags"])
        return rows

    @server.register("knowledge.createDoc")
    def create_doc(title: str, content: str = "", project_id: str = None, tags: dict = None, type: str = "document"):
        doc_id = f"doc-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        knowledge_db.insert("knowledge_docs", {
            "id": doc_id,
            "title": title,
            "type": type,
            "description": content[:200] if content else "",
            "content": content,
            "project_id": project_id,
            "tags": json.dumps(tags or {}),
            "status": "draft",
            "created_at": now,
            "updated_at": now,
        })

        return knowledge_db.fetchone("SELECT * FROM knowledge_docs WHERE id = ?", (doc_id,))

    @server.register("knowledge.getDoc")
    def get_doc(id: str):
        row = knowledge_db.fetchone("SELECT * FROM knowledge_docs WHERE id = ?", (id,))
        if row and row.get("tags"):
            row["tags"] = json.loads(row["tags"])
        return row

    @server.register("knowledge.updateDoc")
    def update_doc(id: str, **kwargs):
        allowed = {"content", "tags", "status", "favorite", "pinned", "title", "description"}
        data = {k: v for k, v in kwargs.items() if k in allowed}
        if "tags" in data:
            existing = knowledge_db.fetchone("SELECT tags FROM knowledge_docs WHERE id = ?", (id,))
            if existing and existing.get("tags"):
                existing_tags = json.loads(existing["tags"])
                existing_tags.update(data["tags"])
                data["tags"] = json.dumps(existing_tags)
            else:
                data["tags"] = json.dumps(data["tags"])
        data["updated_at"] = datetime.now().isoformat()

        knowledge_db.update("knowledge_docs", data, "id = ?", (id,))
        return get_doc(id)

    @server.register("knowledge.deleteDoc")
    def delete_doc(id: str):
        knowledge_db.delete("knowledge_docs", "id = ?", (id,))

    @server.register("knowledge.getGraph")
    def get_graph(project_id: str = None):
        docs = knowledge_db.fetchall("SELECT id, title, type, tags FROM knowledge_docs")
        nodes = []
        edges = []

        for doc in docs:
            tags = json.loads(doc.get("tags") or "{}")
            nodes.append({
                "id": doc["id"],
                "label": doc["title"],
                "type": doc["type"],
                "category": "document",
            })
            for category, tag_list in tags.items():
                for tag in (tag_list or []):
                    tag_id = f"tag-{category}-{tag}"
                    if not any(n["id"] == tag_id for n in nodes):
                        nodes.append({
                            "id": tag_id,
                            "label": tag,
                            "type": "tag",
                            "category": category,
                        })
                    edges.append({
                        "source": doc["id"],
                        "target": tag_id,
                        "type": "tagged",
                    })

        return {"nodes": nodes, "edges": edges}

    @server.register("knowledge.getDimensions")
    def get_dimensions():
        docs = knowledge_db.fetchall("SELECT tags FROM knowledge_docs")
        dimensions = {
            "lifecycle": set(),
            "techStack": set(),
            "abstraction": set(),
            "purpose": set(),
        }

        for doc in docs:
            if doc.get("tags"):
                tags = json.loads(doc["tags"])
                for key in dimensions:
                    if key in tags and tags[key]:
                        dimensions[key].update(tags[key])

        return {k: sorted(v) for k, v in dimensions.items()}

    return server


# ==================== 设置配置方法 ====================

def register_settings_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册设置配置方法"""
    main_db = multi_db.main_db

    @server.register("settings.getModels")
    def get_models():
        rows = main_db.fetchall("SELECT * FROM model_configs ORDER BY is_default DESC, name")
        for row in rows:
            row["isDefault"] = bool(row.get("is_default"))
            if row.get("extra_config"):
                row["extraConfig"] = json.loads(row["extra_config"])
        return rows

    @server.register("settings.addModel")
    def add_model(name: str, provider: str, model: str, url: str, type: str = "local", **kwargs):
        model_id = f"model-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        if kwargs.get("isDefault"):
            main_db.execute("UPDATE model_configs SET is_default = 0")

        main_db.insert("model_configs", {
            "id": model_id,
            "name": name,
            "provider": provider,
            "model": model,
            "url": url,
            "type": type,
            "status": "offline",
            "is_default": 1 if kwargs.get("isDefault") else 0,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("maxTokens", 4096),
            "created_at": now,
            "updated_at": now,
        })

        return main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (model_id,))

    @server.register("settings.updateModel")
    def update_model(id: str, **kwargs):
        allowed = {"name", "temperature", "maxTokens", "url", "isDefault"}
        data = {}
        for k, v in kwargs.items():
            if k == "isDefault":
                if v:
                    main_db.execute("UPDATE model_configs SET is_default = 0")
                data["is_default"] = 1 if v else 0
            elif k == "maxTokens":
                data["max_tokens"] = v
            elif k in allowed:
                data[k] = v
        data["updated_at"] = datetime.now().isoformat()

        main_db.update("model_configs", data, "id = ?", (id,))
        return main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (id,))

    @server.register("settings.removeModel")
    def remove_model(id: str):
        main_db.delete("model_configs", "id = ?", (id,))

    @server.register("settings.testModel")
    async def test_model(id: str):
        model = main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (id,))
        if not model:
            raise ValueError(f"Model not found: {id}")

        await asyncio.sleep(0.5)
        return {
            "status": "connected",
            "latency": 50,
            "model": model["model"],
        }

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

    return server


# ==================== 后端管理方法 ====================

def register_backend_methods(server: ZMQServer, multi_db: MultiDBManager):
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
        return {"status": "running", "pid": os.getpid(), "port": 5671}

    @server.register("backend.ping")
    def ping():
        return {"pong": True, "timestamp": datetime.now().isoformat()}

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

    return server


# ==================== 渲染方法 ====================

def register_render_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册渲染服务方法"""

    @server.register("render.plantuml")
    def render_plantuml(code: str, format: str = "svg", use_remote: bool = True):
        try:
            from plantuml_service import render_plantuml as _render
            data = _render(code, format, use_remote)
            import base64
            return {
                "data": base64.b64encode(data).decode("ascii"),
                "format": format,
                "size": len(data),
            }
        except Exception as e:
            raise RuntimeError(f"PlantUML render failed: {e}")

    @server.register("render.testPlantuml")
    def test_plantuml(use_remote: bool = True):
        try:
            from plantuml_service import test_plantuml_connection
            return test_plantuml_connection(use_remote)
        except Exception as e:
            return {"status": "error", "error": str(e)}

    return server


# ==================== 辅助函数 ====================

def _detect_language(path: str, gitignore: GitIgnoreParser | None = None) -> str:
    """检测项目主要编程语言（统计所有扩展名后返回数量最多的语言，排除忽略文件）"""
    extensions = {}
    for root, dirs, files in os.walk(path):
        rel_root = os.path.relpath(root, path)
        # 过滤被忽略的目录
        if gitignore:
            dirs[:] = [d for d in dirs if not should_ignore_file(
                os.path.join(rel_root, d) if rel_root != '.' else d, gitignore, is_dir=True)]

        for f in files:
            rel_path = os.path.relpath(os.path.join(root, f), path)
            # 跳过被忽略的文件
            if gitignore and should_ignore_file(rel_path, gitignore):
                continue
            ext = os.path.splitext(f)[1].lower()
            extensions[ext] = extensions.get(ext, 0) + 1

    lang_map = {
        ".ts": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript", ".tsx": "TypeScript",
        ".py": "Python", ".go": "Go", ".rs": "Rust", ".java": "Java",
        ".cpp": "C++", ".c": "C", ".h": "C", ".cs": "C#",
        ".vue": "Vue", ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
        ".json": "JSON", ".md": "Markdown", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
    }

    lang_counts = {}
    for ext, count in extensions.items():
        lang = lang_map.get(ext)
        if lang:
            lang_counts[lang] = lang_counts.get(lang, 0) + count

    if not lang_counts:
        return "Unknown"

    return max(lang_counts, key=lang_counts.get)


def _scan_file_tree(project_db: SQLiteContext, root_path: str, current_path: str, parent_path: str = None, gitignore: GitIgnoreParser | None = None) -> int:
    """
    扫描文件树到项目库（相对路径 + MD5 哈希，应用 gitignore 过滤）
    返回文件数量
    """
    file_count = 0
    try:
        for entry in os.scandir(current_path):
            rel_path = os.path.relpath(entry.path, root_path)

            # 跳过被忽略的文件/目录
            if gitignore and should_ignore_file(rel_path, gitignore, entry.is_dir()):
                continue

            ext = os.path.splitext(entry.name)[1].lower()

            lang_map = {
                ".ts": "typescript", ".js": "javascript", ".jsx": "javascript", ".tsx": "typescript",
                ".py": "python", ".go": "go", ".rs": "rust", ".java": "java",
                ".vue": "vue", ".html": "html", ".css": "css", ".scss": "scss",
                ".json": "json", ".md": "markdown", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
            }

            if entry.is_file():
                content_hash = _compute_file_hash(entry.path)
                file_id = f"file-{_simple_hash(rel_path)}"
                language = lang_map.get(ext) or ""
                size = int(entry.stat().st_size)

                project_db.execute(
                    """INSERT OR REPLACE INTO source_files
                       (id, file_path, language, size, content_hash, parent_path)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (file_id, rel_path, language, size, content_hash, parent_path),
                )
                file_count += 1
            elif entry.is_dir():
                dir_id = f"dir-{_simple_hash(rel_path)}"
                project_db.execute(
                    """INSERT OR REPLACE INTO source_files
                       (id, file_path, language, size, content_hash, parent_path)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (dir_id, rel_path, "directory", 0, _simple_hash(rel_path), parent_path),
                )
                file_count += _scan_file_tree(project_db, root_path, entry.path, rel_path, gitignore)
    except PermissionError:
        pass

    return file_count


def _compute_file_hash(file_path: str) -> str:
    """计算文件的 MD5 哈希"""
    import hashlib
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except (PermissionError, OSError):
        return ""


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

        node = {
            "name": child_name,
            "type": "directory" if f.get("language") == "directory" else "file",
            "path": file_path,
        }
        if f.get("language") != "directory":
            node["language"] = f.get("language")
            node["size"] = f.get("size")
        else:
            node["children"] = []
        result.append(node)

    # 排序：文件夹在前，文件在后，各自按名称字母排序
    result.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
    return result


def _build_file_tree(files: list, include_children: bool = True) -> list:
    """从扁平文件列表构建树形结构"""
    # 按层级分组
    tree = {}
    for f in files:
        parts = f["file_path"].split(os.sep)
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


def _flatten_tree(tree: dict, parent_path: str = "", include_children: bool = True) -> list:
    """扁平化树形结构，为每个节点设置正确的 path
    include_children: 是否递归包含子节点（懒加载时设为 False）
    """
    result = []
    for name, data in tree.items():
        current_path = f"{parent_path}/{name}" if parent_path else name
        if "_children" in data:
            result.append({
                "name": name,
                "type": "directory",
                "path": current_path,
                "children": _flatten_tree(data["_children"], current_path) if include_children else [],
            })
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


async def _execute_task(server: ZMQServer, main_db: SQLiteContext, multi_db: MultiDBManager, task_id: str, run_id: str = None):
    """调度层：将解析工作提交到线程池，自身不阻塞事件循环"""
    task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
    if not task:
        return

    start_time = datetime.now()

    try:
        # 将 CPU 密集型解析工作提交到线程池
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            parse_executor,
            _do_parse,
            server, main_db, task_id, run_id, start_time
        )
    except Exception as e:
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        main_db.update("analysis_tasks", {
            "status": "error",
            "error": str(e),
            "updated_at": end_time.isoformat(),
        }, "id = ?", (task_id,))

        if run_id:
            main_db.update("analysis_task_runs", {
                "status": "error",
                "error": str(e),
                "finished_at": end_time.isoformat(),
                "duration_ms": duration_ms,
            }, "id = ?", (run_id,))

        server.publish("task", "error", {
            "taskId": task_id,
            "runId": run_id,
            "error": str(e),
        })


def _do_parse(server: ZMQServer, main_db: SQLiteContext, task_id: str, run_id: str, start_time: datetime):
    """
    解析工作层：在独立线程中执行，可安全调用阻塞式 CPU 操作。

    TODO: 替换为真实 Tree-sitter 解析逻辑。
    当前为 mock 实现，模拟进度推进和报告生成。

    接入真实解析时的替换点：
    1. 读取 task 配置 (scope, extensions, exclude_dirs, report_types)
    2. 调用 Tree-sitter 解析器扫描文件
    3. 每处理一个文件，调用 _update_progress 更新进度
    4. 解析完成后，写入 analysis_reports 表
    5. 调用 server.publish 通知前端
    """
    task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,))
    if not task:
        return

    total = task.get("total", 100)

    def _update_progress(current: int):
        """线程安全：更新进度 + 推送事件"""
        progress = int(current / total * 100) if total > 0 else 0
        main_db.update("analysis_tasks", {
            "progress": progress,
            "current": current,
            "updated_at": datetime.now().isoformat(),
        }, "id = ?", (task_id,))

        if run_id:
            main_db.update("analysis_task_runs", {
                "progress": progress,
                "current": current,
            }, "id = ?", (run_id,))

        server.publish("task", "progress", {
            "taskId": task_id,
            "runId": run_id,
            "progress": progress,
            "total": total,
            "current": current,
        })

    try:
        # ============================================================
        # TODO: 替换以下 mock 循环为真实解析逻辑
        #
        # 示例伪代码:
        #   from tree_sitter import Language, Parser
        #   ts_language = Language("build/my-languages.so", "python")
        #   parser = Parser()
        #   parser.set_language(ts_language)
        #
        #   files = _collect_files(task.get("scope"), task.get("extensions"), task.get("exclude_dirs"))
        #   for idx, filepath in enumerate(files):
        #       with open(filepath, "rb") as f:
        #           source = f.read()
        #       tree = parser.parse(source)
        #       ast_json = _tree_to_json(tree.root_node)
        #       # 累积 AST / 调用链 / 依赖 / 数据流 ...
        #       _update_progress(idx + 1)
        # ============================================================

        # --- Mock 实现 (待替换) ---
        import time
        for i in range(0, total + 1, 5):
            time.sleep(0.1)  # 模拟 CPU 耗时（线程中用 time.sleep，非 asyncio.sleep）
            _update_progress(i)

        # --- 生成报告 (mock 数据，待替换) ---
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        main_db.update("analysis_tasks", {
            "status": "done",
            "progress": 100,
            "current": total,
            "updated_at": end_time.isoformat(),
        }, "id = ?", (task_id,))

        if run_id:
            main_db.update("analysis_task_runs", {
                "status": "done",
                "progress": 100,
                "current": total,
                "finished_at": end_time.isoformat(),
                "duration_ms": duration_ms,
            }, "id = ?", (run_id,))

        report_id = str(uuid.uuid4())
        main_db.insert("analysis_reports", {
            "id": report_id,
            "task_id": task_id,
            "run_id": run_id,
            "ast_data": json.dumps({"type": "Program", "body": []}),
            "call_chain": json.dumps([]),
            "dependencies": json.dumps({"modules": [], "files": []}),
            "dataflow": json.dumps([]),
            "summary": "Analysis complete (mock data)",
            "logs": json.dumps([
                {"timestamp": start_time.isoformat(), "message": "开始分析..."},
                {"timestamp": start_time.isoformat(), "message": f"扫描目录: {task.get('scope', '全部')}"},
                {"timestamp": end_time.isoformat(), "message": f"完成, 耗时 {duration_ms}ms"},
            ]),
        })

        server.publish("task", "complete", {
            "taskId": task_id,
            "runId": run_id,
            "status": "done",
            "progress": 100,
        })

    except Exception as e:
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        main_db.update("analysis_tasks", {
            "status": "error",
            "error": str(e),
            "updated_at": end_time.isoformat(),
        }, "id = ?", (task_id,))

        if run_id:
            main_db.update("analysis_task_runs", {
                "status": "error",
                "error": str(e),
                "finished_at": end_time.isoformat(),
                "duration_ms": duration_ms,
            }, "id = ?", (run_id,))

        server.publish("task", "error", {
            "taskId": task_id,
            "runId": run_id,
            "error": str(e),
        })

    def init_sample_data():
        """初始化示例项目数据"""
        project_id = f"sample-{uuid.uuid4().hex[:8]}"
        project_name = "Sample Project"
        now = datetime.now().isoformat()

        # 在主库中创建示例项目
        main_db.insert("projects", {
            "id": project_id,
            "name": project_name,
            "root_path": "",  # 示例项目无实际路径
            "language": "TypeScript",
            "file_count": 0,
            "status": "synced",
            "is_sample": 1,
            "needs_resync": 0,
            "has_file_changes": 0,
            "created_at": now,
            "updated_at": now,
        })

        # 创建项目库
        project_db = multi_db.get_project_db(project_id)

        # 插入示例文件
        sample_files = [
            {"path": "src/main.ts", "language": "typescript", "size": 1200, "content_hash": "abc123"},
            {"path": "src/App.vue", "language": "vue", "size": 2400, "content_hash": "def456"},
            {"path": "src/components/HelloWorld.vue", "language": "vue", "size": 800, "content_hash": "ghi789"},
            {"path": "package.json", "language": "json", "size": 500, "content_hash": "jkl012"},
            {"path": "README.md", "language": "markdown", "size": 1500, "content_hash": "mno345"},
        ]

        for f in sample_files:
            project_db.insert("source_files", {
                "path": f["path"],
                "language": f["language"],
                "size": f["size"],
                "content_hash": f["content_hash"],
                "created_at": now,
                "updated_at": now,
            })

        # 更新文件计数
        main_db.update("projects", {"file_count": len(sample_files)}, "id = ?", (project_id,))

        return {"project": main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))}

    @server.register("project.clearSampleData")
    def clear_sample_data(project_id: str):
        """清除示例项目数据"""
        # 验证是否为示例项目
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project or not project.get("is_sample"):
            raise ValueError("Not a sample project")

        # 删除项目库
        multi_db.close_project_db(project_id)
        project_db_path = os.path.join(multi_db.data_dir, f"{project_id}.db")
        if os.path.exists(project_db_path):
            os.remove(project_db_path)

        # 删除主库中的项目记录
        main_db.delete("projects", "id = ?", (project_id,))

        return {"success": True}
