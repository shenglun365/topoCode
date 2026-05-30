"""Core Service - 方法注册 + 业务逻辑 (多数据库架构)"""

import asyncio
import fnmatch
import hashlib
import json
import logging
import os

import re
import shutil
import uuid
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from sqlite_ctx import SQLiteContext, MultiDBManager
from zmq_server import ZMQServer
from report_tree_service import save_overall_doc as _save_overall_doc



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
        for row in rows:
            if row.get("tags"):
                row["tags"] = json.loads(row["tags"])
            # 附加项目所属分组 ID 列表
            pid = row.get("id")
            if pid:
                group_rows = main_db.fetchall(
                    """SELECT g.id FROM project_groups g
                       INNER JOIN project_group_map m ON g.id = m.group_id
                       WHERE m.project_id = ?""",
                    (pid,)
                )
                row["groups"] = [g["id"] for g in group_rows]
        return rows

    @server.register("project.import")
    async def import_project(path: str):
        """导入项目 — 单次遍历 + 事务批量写入 + 异步释放 event loop"""
        import asyncio
        import time

        logger.info(f"[import] ===== 开始导入项目: {path} =====")
        t0 = time.time()

        if not os.path.isdir(path):
            raise FileNotFoundError(f"Directory not found: {path}")

        # 加载 .gitignore
        logger.info(f"[import] 加载 .gitignore...")
        gitignore = GitIgnoreParser().load_file(os.path.join(path, '.gitignore'))
        logger.info(f"[import] .gitignore 加载完成, 耗时 {time.time() - t0:.2f}s")

        # 创建项目库
        project_id = f"proj-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        logger.info(f"[import] 创建项目库: {project_id}")
        project_db = multi_db.init_project_db(project_id)
        logger.info(f"[import] 项目库创建完成, 耗时 {time.time() - t0:.2f}s")

        # 单次遍历：同时完成语言检测和文件扫描
        logger.info(f"[import] 开始扫描文件...")
        scan_t0 = time.time()
        file_count, language = await _scan_and_import(project_db, path, gitignore, server, project_id)
        scan_elapsed = time.time() - scan_t0
        logger.info(f"[import] 扫描完成: {file_count} 个文件, 主语言={language}, 耗时 {scan_elapsed:.2f}s")

        # 插入主库
        logger.info(f"[import] 写入主库 projects 表...")
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

        server.publish("project", "import.progress", {
            "path": path,
            "progress": 100,
            "fileCount": file_count,
            "phase": "done",
        })
        total_elapsed = time.time() - t0
        logger.info(f"[import] ===== 导入完成: {project_id}, {file_count} 文件, 总耗时 {total_elapsed:.2f}s =====")

        return main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))

    @server.register("project.get")
    def get_project(id: str):
        return main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))

    @server.register("project.remove")
    def remove_project(id: str):
        if not id or id == "undefined":
            raise ValueError(f"Invalid project id: {id}")
        # 删除项目库
        multi_db.delete_project_db(id)
        # 删除主库记录
        main_db.delete("projects", "id = ?", (id,))

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
    async def check_file_changes(id: str):
        """对比文件系统与 source_files.content_hash，返回变更列表（应用 gitignore 过滤）"""
        import asyncio

        def _scan_files():
            """在后台线程执行文件扫描，不阻塞 event loop"""
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
                dirnames[:] = [d for d in dirnames if not should_ignore_file(
                    os.path.join(rel_root, d) if rel_root != '.' else d, gitignore, is_dir=True)]

                for filename in filenames:
                    full_path = os.path.join(dirpath, filename)
                    rel_path = os.path.relpath(full_path, root_path)
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

            return added, modified, deleted

        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (id,))
        if not project:
            raise ValueError(f"Project not found: {id}")

        added, modified, deleted = await asyncio.to_thread(_scan_files)
        has_changes = bool(added or modified or deleted)

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

    @server.register("project.clearSampleData")
    def clear_sample_data(project_id: str):
        """清除示例项目数据"""
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

    @server.register("project.getStorageStats")
    def get_storage_stats(project_id: str = None, projectId: str = None):
        """获取项目存储空间统计（DB 文件 + 源码文件）"""
        pid = project_id or projectId
        if not pid:
            raise ValueError("project_id is required")

        # 项目 DB 文件
        db_path = os.path.join(multi_db.data_dir, f"{pid}.db")
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

        # WAL / SHM 文件（SQLite WAL 模式）
        wal_size = 0
        shm_size = 0
        for suffix, out in [("-wal", "wal_size"), ("-shm", "shm_size")]:
            p = db_path + suffix
            if os.path.exists(p):
                locals()[out] = os.path.getsize(p)

        # 源码文件大小之和
        source_size = 0
        try:
            project_db = multi_db.get_project_db(pid)
            if project_db:
                row = project_db.fetchone("SELECT COALESCE(SUM(size), 0) FROM source_files")
                source_size = row[0] if row else 0
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
                raise ValueError("分组层级不能超过4层（建议控制在2-3层）")
            depth = parent['depth'] + 1
        else:
            depth = 0

        gid = str(uuid.uuid4())[:12]
        main_db.execute(
            "INSERT INTO project_groups (id, name, parent_id, depth, sort_order) VALUES (?, ?, ?, ?, ?)",
            (gid, name, parent_id, depth, 0)
        )
        main_db.conn.commit()
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
                raise ValueError("不能将自己设为父分组")
            # 校验层级
            if parent_id:
                parent = main_db.fetchone("SELECT * FROM project_groups WHERE id = ?", (parent_id,))
                if not parent:
                    raise ValueError("Parent group not found")
                if parent.get('depth', 0) >= 3:
                    raise ValueError("分组层级不能超过4层")
            updates.append("parent_id = ?")
            updates.append("depth = ?")
            params.append(parent_id)
            params.append(parent['depth'] + 1 if parent_id else 0)
        if updates:
            params.append(id)
            main_db.execute(f"UPDATE project_groups SET {', '.join(updates)} WHERE id = ?", params)
            main_db.conn.commit()

        return {"success": True}

    @server.register("group.delete")
    def delete_group(id: str):
        """删除分组（级联删除子分组和关联）"""
        main_db.execute("DELETE FROM project_groups WHERE id = ?", (id,))
        main_db.conn.commit()
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
        main_db.conn.commit()
        return {"success": True}

    @server.register("group.removeProject")
    def remove_project_from_group(project_id: str, group_id: str):
        """将项目从分组移除"""
        main_db.execute(
            "DELETE FROM project_group_map WHERE project_id = ? AND group_id = ?",
            (project_id, group_id)
        )
        main_db.conn.commit()
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

    return server


# ==================== 代码分析方法 ====================

# analysis.* 方法已迁移到 task_manager.py
from task_manager import register_analysis_methods


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
            # 安全：不返回 api_key，只标记是否存在
            row["hasApiKey"] = bool(row.get("api_key"))
            if row.get("api_key"):
                del row["api_key"]
            if row.get("extra_config"):
                row["extraConfig"] = json.loads(row["extra_config"])
        return rows

    @server.register("settings.addModel")
    def add_model(name: str, provider: str, model: str, url: str, type: str = "local", **kwargs):
        model_id = f"model-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

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
            "max_tokens": kwargs.get("maxTokens", 4096),
            "created_at": now,
            "updated_at": now,
        }
        if kwargs.get("apiKey"):
            data["api_key"] = kwargs["apiKey"]

        main_db.insert("model_configs", data)
        return main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (model_id,))

    @server.register("settings.updateModel")
    def update_model(id: str, **kwargs):
        allowed = {"name", "temperature", "maxTokens", "url", "isDefault", "provider", "model", "maxRequestsPerDay", "maxTokensPerDay"}
        data = {}
        for k, v in kwargs.items():
            if k == "isDefault":
                if v:
                    main_db.execute("UPDATE model_configs SET is_default = 0")
                data["is_default"] = 1 if v else 0
            elif k == "maxTokens":
                data["max_tokens"] = v
            elif k == "maxRequestsPerDay":
                data["max_requests_per_day"] = int(v) if v else 0
            elif k == "maxTokensPerDay":
                data["max_tokens_per_day"] = int(v) if v else 0
            elif k == "apiKey":
                data["api_key"] = v
            elif k == "url":
                clean_url = v.rstrip('/')
                if clean_url.endswith('/v1'):
                    clean_url = clean_url[:-3]
                data["url"] = clean_url
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
        """测试模型连接 — 真实调用 LLM API"""
        model = main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (id,))
        if not model:
            raise ValueError(f"Model not found: {id}")

        import requests as req
        start = __import__('time').time()
        try:
            base = model['url'].rstrip('/')
            # 兼容旧数据中 URL 末尾带 /v1 的情况
            if base.endswith('/v1'):
                base = base[:-3]
            if model.get('provider') == 'ollama':
                resp = req.post(f"{base}/api/tags", timeout=10)
                if resp.status_code != 200:
                    return {"status": "error", "latency": 0, "error": f"Ollama API {resp.status_code}"}
            else:
                headers = {'Content-Type': 'application/json'}
                if model.get('api_key'):
                    headers['Authorization'] = f"Bearer {model['api_key']}"
                resp = req.get(f"{base}/v1/models", headers=headers, timeout=10)
                if resp.status_code != 200:
                    return {"status": "error", "latency": 0, "error": f"API {resp.status_code}"}
            latency = int((__import__('time').time() - start) * 1000)
            # 只更新 status，不写入 latency 字段（表结构可能不含该列）
            try:
                main_db.update("model_configs", {"status": "connected"}, "id = ?", (id,))
            except Exception:
                pass
            return {"status": "connected", "latency": latency, "model": model["model"]}
        except Exception as e:
            model['status'] = 'error'
            main_db.update("model_configs", {"status": "error"}, "id = ?", (id,))
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
            main_db.execute("CREATE INDEX IF NOT EXISTS idx_mdu_model ON model_daily_usage(model_id)")
            main_db.execute("CREATE INDEX IF NOT EXISTS idx_mdu_date ON model_daily_usage(date)")

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
        http_port = getattr(multi_db, 'http_port', None)
        http_host = getattr(multi_db, 'http_host', None)
        return {"status": "running", "pid": os.getpid(), "port": 5671, "httpPort": http_port, "httpHost": http_host}

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
            msg = str(e)
            if 'PlantUML render failed:' in msg:
                raise  # 保持 _render_remote 的详细错误
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

async def _scan_and_import(project_db, root_path: str, gitignore: GitIgnoreParser | None = None, server=None, project_id: str = "") -> tuple:
    """
    单次遍历完成语言检测 + 文件扫描 + 事务批量写入
    返回 (file_count, primary_language)
    """
    import asyncio
    import hashlib
    import time

    # 语言映射（显示名用于项目语言，小写名用于文件语言）
    LANG_MAP_DISPLAY = {
        ".ts": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript", ".tsx": "TypeScript",
        ".py": "Python", ".go": "Go", ".rs": "Rust", ".java": "Java",
        ".cpp": "C++", ".c": "C", ".h": "C", ".cs": "C#",
        ".vue": "Vue", ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
        ".json": "JSON", ".md": "Markdown", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
    }
    LANG_MAP_FILE = {
        ".ts": "typescript", ".js": "javascript", ".jsx": "javascript", ".tsx": "typescript",
        ".py": "python", ".go": "go", ".rs": "rust", ".java": "java",
        ".c": "c", ".h": "c",
        ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
        ".cs": "csharp",
        ".vue": "vue", ".html": "html", ".css": "css", ".scss": "scss",
        ".json": "json", ".md": "markdown", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
        ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin", ".scala": "scala",
        ".r": "r", ".sql": "sql", ".sh": "bash",
        ".dart": "dart", ".lua": "lua", ".perl": "perl", ".pl": "perl",
        ".elixir": "elixir", ".ex": "elixir", ".exs": "elixir",
        ".erl": "erlang", ".hs": "haskell", ".ml": "ocaml",
        ".zig": "zig", ".nim": "nim", ".v": "verilog",
    }

    file_count = 0
    dir_count = 0
    ignored_count = 0
    lang_counts = {}  # 扩展名 -> 计数
    batch_records = []  # 收集所有记录，事务批量写入
    BATCH_SIZE = 500  # 每 500 条提交一次
    scan_t0 = time.time()

    async def _scan_dir(current_path: str, parent_path: str | None = None):
        nonlocal file_count, dir_count, ignored_count
        try:
            entries = list(os.scandir(current_path))
        except PermissionError:
            logger.warning(f"[import] 权限拒绝: {current_path}")
            return

        for entry in entries:
            # 每处理 100 个条目释放一次 event loop 并打印进度
            if file_count % 500 == 0 and file_count > 0:
                await asyncio.sleep(0)
                elapsed = time.time() - scan_t0
                progress_pct = min(int(file_count / total_estimate * 100), 99)
                logger.info(f"[import] 扫描进度: {file_count}/{total_estimate} ({progress_pct}%), {dir_count} 目录, {ignored_count} 忽略, 耗时 {elapsed:.1f}s")
                if server and project_id:
                    server.publish("project", "import.progress", {
                        "path": root_path,
                        "progress": progress_pct,
                        "fileCount": file_count,
                        "totalEstimate": total_estimate,
                        "phase": "scan",
                    })

            rel_path = os.path.relpath(entry.path, root_path)

            # 跳过被忽略的文件/目录
            if gitignore and should_ignore_file(rel_path, gitignore, entry.is_dir()):
                ignored_count += 1
                continue

            ext = os.path.splitext(entry.name)[1].lower()

            if entry.is_file():
                # 统计语言
                if ext in LANG_MAP_DISPLAY:
                    lang_counts[ext] = lang_counts.get(ext, 0) + 1

                # 计算文件哈希
                content_hash = ""
                try:
                    hash_md5 = hashlib.md5()
                    with open(entry.path, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            hash_md5.update(chunk)
                    content_hash = hash_md5.hexdigest()
                except (PermissionError, OSError):
                    pass

                file_id = f"file-{_simple_hash(rel_path)}"
                language = LANG_MAP_FILE.get(ext) or ""
                try:
                    size = int(entry.stat().st_size)
                except OSError:
                    size = 0

                fname = rel_path.rsplit('/', 1)[-1].rsplit('.', 1)[0] if '.' in rel_path.rsplit('/', 1)[-1] else rel_path.rsplit('/', 1)[-1]
                batch_records.append((
                    file_id, rel_path, fname, language, size, content_hash, parent_path
                ))
                file_count += 1

            elif entry.is_dir():
                dir_id = f"dir-{_simple_hash(rel_path)}"
                dname = rel_path.rsplit('/', 1)[-1]
                batch_records.append((
                    dir_id, rel_path, dname, "directory", 0, _simple_hash(rel_path), parent_path
                ))
                dir_count += 1

                # 递归扫描子目录
                await _scan_dir(entry.path, rel_path)

    # 快速统计总文件数（用于进度百分比）
    total_estimate = 0
    logger.info(f"[import] 快速估算文件总数...")
    try:
        for dirpath, dirnames, filenames in os.walk(root_path):
            total_estimate += len(filenames)
    except Exception:
        total_estimate = 0
    if total_estimate > 0:
        logger.info(f"[import] 估算总文件数: {total_estimate}")
    else:
        total_estimate = 1  # 避免除零

    # 执行扫描
    logger.info(f"[import] 开始递归扫描目录: {root_path}")
    await _scan_dir(root_path)
    scan_elapsed = time.time() - scan_t0
    logger.info(f"[import] 扫描完成: {file_count} 文件, {dir_count} 目录, {ignored_count} 忽略, 耗时 {scan_elapsed:.2f}s")

    # 打印语言分布 Top 10
    if lang_counts:
        sorted_langs = sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        lang_summary = ", ".join(f"{ext}={cnt}" for ext, cnt in sorted_langs)
        logger.info(f"[import] 语言分布 Top10: {lang_summary}")

    # 事务批量写入
    if batch_records:
        write_t0 = time.time()
        num_batches = (len(batch_records) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"[import] 开始批量写入: {len(batch_records)} 条记录, {num_batches} 批次 (每批 {BATCH_SIZE} 条)")
        project_db.execute("BEGIN TRANSACTION")
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
                logger.info(f"[import] 写入进度: 批次 {batch_num}/{num_batches}, 已写入 {min(i + BATCH_SIZE, len(batch_records))}/{len(batch_records)}, 耗时 {elapsed:.2f}s")
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
            project_db.execute("COMMIT")
            write_elapsed = time.time() - write_t0
            logger.info(f"[import] 批量写入完成, 总耗时 {write_elapsed:.2f}s")
        except Exception as e:
            logger.error(f"[import] 批量写入失败: {e}")
            project_db.execute("ROLLBACK")
            raise

    # 确定主要语言
    if not lang_counts:
        primary_language = "Unknown"
    else:
        primary_ext = max(lang_counts, key=lang_counts.get)
        primary_language = LANG_MAP_DISPLAY.get(primary_ext, "Unknown")

    total_elapsed = time.time() - scan_t0
    logger.info(f"[import] _scan_and_import 完成: {file_count} 文件, 主语言={primary_language}, 总耗时 {total_elapsed:.2f}s")

    return file_count, primary_language


def _scan_file_tree(project_db: SQLiteContext, root_path: str, current_path: str, parent_path: str = None, gitignore: GitIgnoreParser | None = None) -> int:
    """
    扫描文件树到项目库（相对路径 + MD5 哈希，应用 gitignore 过滤）
    返回文件数量

    注意：此函数保留用于 sync_project 等其他场景，import_project 已使用 _scan_and_import
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
                ".c": "c", ".h": "c",
                ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
                ".cs": "csharp",
                ".vue": "vue", ".html": "html", ".css": "css", ".scss": "scss",
                ".json": "json", ".md": "markdown", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
                ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin", ".scala": "scala",
                ".r": "r", ".sql": "sql", ".sh": "bash",
                ".dart": "dart", ".lua": "lua", ".perl": "perl", ".pl": "perl",
                ".elixir": "elixir", ".ex": "elixir", ".exs": "elixir",
                ".erl": "erlang", ".hs": "haskell", ".ml": "ocaml",
                ".zig": "zig", ".nim": "nim", ".v": "verilog",
            }

            if entry.is_file():
                content_hash = _compute_file_hash(entry.path)
                file_id = f"file-{_simple_hash(rel_path)}"
                language = lang_map.get(ext) or ""
                size = int(entry.stat().st_size)

                fname = rel_path.rsplit('/', 1)[-1].rsplit('.', 1)[0] if '.' in rel_path.rsplit('/', 1)[-1] else rel_path.rsplit('/', 1)[-1]
                project_db.execute(
                    """INSERT OR REPLACE INTO source_files
                       (id, file_path, file_name, language, size, content_hash, parent_path)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (file_id, rel_path, fname, language, size, content_hash, parent_path),
                )
                file_count += 1
            elif entry.is_dir():
                dir_id = f"dir-{_simple_hash(rel_path)}"
                dname = rel_path.rsplit('/', 1)[-1]
                project_db.execute(
                    """INSERT OR REPLACE INTO source_files
                       (id, file_path, file_name, language, size, content_hash, parent_path)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (dir_id, rel_path, dname, "directory", 0, _simple_hash(rel_path), parent_path),
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

_DEPENDENCY_FILE_PATTERNS = {
    'package.json': 'node',
    'requirements.txt': 'python',
    'pyproject.toml': 'python',
    'Pipfile': 'python',
    'Cargo.toml': 'rust',
    'go.mod': 'go',
    'pom.xml': 'java',
    'build.gradle': 'java',
    'build.gradle.kts': 'java',
    'Gemfile': 'ruby',
    'composer.json': 'php',
    'pubspec.yaml': 'dart',
    'CMakeLists.txt': 'cmake',
    'vcpkg.json': 'cpp',
    'conanfile.txt': 'cpp',
    '*.csproj': 'csharp',
}


def _parse_dependency_file(root_path: str, file_name: str, rel_path: str) -> Optional[Dict[str, Any]]:
    """解析单个依赖文件，返回结构化依赖信息"""
    full_path = os.path.join(root_path, rel_path)
    if not os.path.isfile(full_path):
        return None

    eco = _DEPENDENCY_FILE_PATTERNS.get(file_name)
    if not eco:
        return None

    dep_info = {"file": rel_path, "type": eco, "dependencies": {}}
    try:
        if file_name == 'package.json':
            import json as _json
            with open(full_path, 'r', encoding='utf-8') as f:
                pkg = _json.load(f)
            deps = {}
            for section in ('dependencies', 'devDependencies', 'peerDependencies'):
                if section in pkg:
                    for k, v in pkg[section].items():
                        deps[k] = str(v)
            dep_info["dependencies"] = deps

        elif file_name == 'Cargo.toml':
            dep_info["dependencies"] = _parse_toml_deps(full_path)

        elif file_name == 'go.mod':
            deps = {}
            with open(full_path, 'r', encoding='utf-8') as f:
                in_require = False
                for line in f:
                    line = line.strip()
                    if line.startswith('require ('):
                        in_require = True
                        continue
                    if in_require:
                        if line == ')':
                            break
                        parts = line.split()
                        if len(parts) >= 1:
                            deps[parts[0]] = parts[1] if len(parts) > 1 else ''
            dep_info["dependencies"] = deps

        elif file_name == 'pom.xml':
            deps = {}
            import re as _re
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            for m in _re.finditer(r'<dependency>\s*<groupId>(.+?)</groupId>\s*<artifactId>(.+?)</artifactId>\s*<version>(.+?)</version>', content, _re.DOTALL):
                deps[f"{m.group(1)}:{m.group(2)}"] = m.group(3)
            dep_info["dependencies"] = deps

        elif file_name in ('requirements.txt', 'Pipfile'):
            deps = {}
            with open(full_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = re.split(r'[=~<>!]+', line, maxsplit=1)
                        if len(parts) >= 1:
                            deps[parts[0].strip()] = parts[1].strip() if len(parts) > 1 else ''
            dep_info["dependencies"] = deps

        elif file_name == 'pyproject.toml':
            dep_info["dependencies"] = _parse_toml_deps(full_path)

        elif file_name in ('build.gradle', 'build.gradle.kts'):
            deps = {}
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            for m in re.finditer(r"(implementation|api|compileOnly|runtimeOnly)\s+['\"](.+?)['\"]", content):
                deps[m.group(2)] = m.group(1)
            dep_info["dependencies"] = deps

        else:
            # 通用文本解析 fallback
            deps = {}
            with open(full_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith(('#', '//', '/*')):
                        parts = line.split()
                        if len(parts) >= 1:
                            deps[parts[0]] = parts[1] if len(parts) > 1 else ''
            dep_info["dependencies"] = deps
    except Exception as e:
        logger.warning(f"[report] Failed to parse dependency file {rel_path}: {e}")
        dep_info["error"] = str(e)

    dep_info["count"] = len(dep_info.get("dependencies", {}))
    return dep_info


def _parse_toml_deps(full_path: str) -> Dict[str, str]:
    """解析 TOML 格式依赖文件"""
    deps = {}
    try:
        import tomllib
        with open(full_path, 'rb') as f:
            data = tomllib.load(f)
        for section_key in ('dependencies', 'dev-dependencies', 'build-dependencies'):
            if section_key in data:
                section = data[section_key]
                if isinstance(section, dict):
                    for k, v in section.items():
                        if isinstance(v, str):
                            deps[k] = v
                        elif isinstance(v, dict):
                            deps[k] = v.get('version', '')
                        else:
                            deps[k] = str(v)
    except ImportError:
        # Python < 3.11 fallback
        try:
            import tomli as tomllib
            with open(full_path, 'rb') as f:
                data = tomllib.load(f)
            for section_key in ('dependencies', 'dev-dependencies', 'build-dependencies'):
                if section_key in data:
                    section = data[section_key]
                    if isinstance(section, dict):
                        for k, v in section.items():
                            deps[k] = str(v) if not isinstance(v, dict) else v.get('version', '')
        except ImportError:
            logger.warning("[report] tomllib/tomli not available, skipping TOML parsing")
    return deps


def register_report_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册报告生成辅助方法"""
    main_db = multi_db.main_db

    @server.register("report.getReadmeContent")
    def get_readme_content(project_id=None, projectId=None):
        """获取 README.md 前 500 字符"""
        pid = project_id or projectId
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (pid,))
        if not project:
            raise ValueError(f"Project not found: {pid}")
        root_path = project["root_path"]
        for candidate in ('README.md', 'Readme.md', 'readme.md', 'README'):
            readme_path = os.path.join(root_path, candidate)
            if os.path.isfile(readme_path):
                try:
                    with open(readme_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read(5000)
                    return {"path": candidate, "content": content[:500], "fullLength": len(content)}
                except Exception as e:
                    return {"path": candidate, "error": str(e)}
        return {"path": None, "content": "", "error": "No README found"}

    @server.register("report.generateProjectSummary")
    async def generate_project_summary(project_id=None, projectId=None):
        """调用 LLM 生成项目概要 (500字以内), 存入 projects.summary"""
        pid = project_id or projectId
        logger.info(f"[generateProjectSummary] ENTRY pid={pid}")
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (pid,))
        if not project:
            logger.warning(f"[generateProjectSummary] Project not found: {pid}")
            raise ValueError(f"Project not found: {pid}")

        # 收集 README + 依赖信息作为 LLM 输入
        logger.info(f"[generateProjectSummary] fetching README for {pid}")
        readme_result = get_readme_content(projectId=pid)
        readme_text = readme_result.get("content", "") if readme_result else ""
        logger.info(f"[generateProjectSummary] README length={len(readme_text)}")
        deps_result = extract_dependency_files(projectId=pid)
        deps_text = ""
        if deps_result and deps_result.get("count", 0) > 0:
            lines = []
            for d in deps_result["dependencyFiles"]:
                deps_list = ", ".join(list(d.get("dependencies", {}).keys())[:30])
                lines.append(f"- {d['file']} ({d['type']}): {deps_list}")
            deps_text = "\n".join(lines)
            logger.info(f"[generateProjectSummary] dep files count={deps_result.get('count')}, text_len={len(deps_text)}")
        else:
            logger.info(f"[generateProjectSummary] no dep files found")

        prompt = (
            "你是一个代码架构分析专家。请根据以下项目的 README 和依赖信息，"
            "生成一段 500 字以内的项目概要。\n\n"
            "要求：\n"
            "1. 只提取功能性、技术栈、需求场景等对架构分析有用的信息\n"
            "2. 忽略无关的安装说明、贡献指南、许可信息等\n"
            "3. 用中文回答，简洁扼要\n"
            "4. 字数控制在 500 字以内\n\n"
        )
        if readme_text:
            prompt += f"## README\n{readme_text}\n\n"
        if deps_text:
            prompt += f"## 依赖文件\n{deps_text}\n\n"
        prompt += "请输出项目概要："
        logger.info(f"[generateProjectSummary] prompt built, total_len={len(prompt)}")

        # 调用 LLM
        from llm_service import LLMService
        lm = LLMService(multi_db)

        models = main_db.fetchall(
            "SELECT * FROM model_configs ORDER BY is_default DESC, name"
        )
        if not models:
            raise ValueError("No LLM model found")
        model_id = models[0]["id"]
        logger.info(f"[generateProjectSummary] using model_id={model_id} model_name={models[0].get('name')}")

        try:
            summary = await lm.sync_chat(
                messages=[{"role": "user", "content": prompt}],
                model_id=model_id,
            )
            raw_len = len(summary or "")
            logger.info(f"[generateProjectSummary] LLM response received, raw_len={raw_len}")
            summary = (summary or "").strip()
            if not summary:
                raise ValueError("LLM returned empty summary")
            if len(summary) > 2000:
                summary = summary[:2000]
                logger.info(f"[generateProjectSummary] summary truncated to 2000 chars")
            logger.info(f"[generateProjectSummary] summary final_len={len(summary)}, preview={summary[:120]!r}")
        except Exception as e:
            logger.error(f"[generateProjectSummary] LLM call failed: {e}")
            raise RuntimeError(f"生成项目概要失败: {e}")

        from datetime import datetime
        now = datetime.now().isoformat()
        main_db.execute(
            "UPDATE projects SET summary = ?, summary_generated_at = ?, updated_at = ? WHERE id = ?",
            (summary, now, now, pid)
        )
        logger.info(f"[generateProjectSummary] DB write OK, pid={pid}, summary_len={len(summary)}, generated_at={now}")
        return {"success": True, "summary": summary, "generated_at": now}

    @server.register("report.getProjectSummary")
    def get_project_summary(project_id=None, projectId=None):
        """获取已生成的项目概要"""
        pid = project_id or projectId
        logger.info(f"[getProjectSummary] ENTRY pid={pid}")
        row = main_db.fetchone(
            "SELECT summary, summary_generated_at FROM projects WHERE id = ?", (pid,)
        )
        if not row:
            return {"summary": "", "generated_at": None}
        return {"summary": row["summary"] or "", "generated_at": row["summary_generated_at"]}

    @server.register("report.extractDependencyFiles")
    def extract_dependency_files(project_id=None, projectId=None):
        """扫描项目根目录，提取所有已知的依赖管理文件"""
        pid = project_id or projectId
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (pid,))
        if not project:
            raise ValueError(f"Project not found: {pid}")
        root_path = project["root_path"]
        results = []
        for fname in _DEPENDENCY_FILE_PATTERNS:
            # 尝试根目录
            parsed = _parse_dependency_file(root_path, fname, fname)
            if parsed:
                results.append(parsed)
                continue
            # 尝试子目录（如 build.gradle 可能在 app/ 下）
            for dirpath, _, filenames in os.walk(root_path):
                for fn in filenames:
                    if fn == fname:
                        rel = os.path.relpath(os.path.join(dirpath, fn), root_path)
                        parsed = _parse_dependency_file(root_path, fname, rel)
                        if parsed:
                            results.append(parsed)
                        break  # only first match per pattern
        return {"dependencyFiles": results, "count": len(results)}

    @server.register("report.getLevelCommunityDetail")
    def get_level_community_detail(project_id=None, task_id=None, level="L2", edge_type=None,
                                    projectId=None, taskId=None, edgeType=None):
        """获取指定层级的社区完整信息（含节点路径和边详情）"""
        pid = project_id or projectId
        tid = task_id or taskId
        et = edge_type or edgeType or 'CALL'
        logger.info("[report.getLevelCommunityDetail] ENTRY task_id=%s level=%s edge_type=%s project_id=%s", tid, level, et, pid)
        project_db = multi_db.get_project_db(pid)
        communities = project_db.fetchall(
            """SELECT * FROM graph_doc
               WHERE task_id = ? AND edge_type = ? AND comm_lv = ?
               ORDER BY quality_score DESC""",
            (tid, et, level)
        )
        logger.info("[report.getLevelCommunityDetail] graph_doc query returned %d communities", len(communities))

        # 预加载 source_files 映射: id → {file_path, file_name}
        all_source_files = project_db.fetchall("SELECT id, file_path, file_name FROM source_files")
        sf_map = {row['id']: row for row in all_source_files}

        import re

        def _resolve_node(node_str: str) -> dict:
            """解析 node 字符串，返回 {id, name, filePath, type}"""
            node_str = str(node_str)

            # CASE 1: file-UUID:symbol_name (CALL 边)
            m = re.match(r'^([a-zA-Z0-9_-]+):(.+)$', node_str)
            if m:
                file_ref = m.group(1)
                symbol = m.group(2)
                sf = sf_map.get(file_ref)
                if sf:
                    return {
                        "id": node_str,
                        "name": symbol,
                        "filePath": sf['file_path'],
                        "type": "function",
                    }
                # file_ref 不在 source_files 中，但仍保留符号名
                return {
                    "id": node_str,
                    "name": symbol,
                    "filePath": "?",
                    "type": "function",
                }

            # CASE 2: 纯 file-UUID（INCLUDE 边的 source，或 CALL 边中无函数名的引用）
            sf = sf_map.get(node_str)
            if sf:
                name = sf['file_name']
                if not name:
                    name = sf['file_path'].rsplit('/', 1)[-1].rsplit('.', 1)[0] or node_str
                return {
                    "id": node_str,
                    "name": name,
                    "filePath": sf['file_path'],
                    "type": "file",
                }

            # CASE 3: include_path 或其他未知格式
            return {
                "id": node_str,
                "name": node_str,
                "filePath": "?",
                "type": "?",
            }

        result = []
        for comm in communities:
            node_list = json.loads(comm['node_list']) if isinstance(comm['node_list'], str) else comm['node_list']
            edge_list = json.loads(comm['edge_list']) if comm.get('edge_list') and isinstance(comm['edge_list'], str) else comm.get('edge_list', [])

            # 获取节点路径
            nodes_with_paths = []
            if isinstance(node_list, list):
                for node in node_list[:50]:  # limit to 50
                    if isinstance(node, dict):
                        nid = node.get('id', '')
                        sf = sf_map.get(nid)
                        nodes_with_paths.append({
                            "id": nid or node.get('name', ''),
                            "name": node.get('name', ''),
                            "type": node.get('type', ''),
                            "filePath": sf['file_path'] if sf else '?',
                        })
                    elif isinstance(node, str):
                        nodes_with_paths.append(_resolve_node(node))

            # 获取边的关系
            def _edge_display_name(node_str: str) -> str:
                """将 node 字符串转换为可读名称:
                   file-UUID → source_files.file_name
                   file-UUID:symbol → symbol
                   其他 → 原样返回
                """
                sf = sf_map.get(node_str)
                if sf:
                    name = sf['file_name']
                    if not name:
                        name = sf['file_path'].rsplit('/', 1)[-1].rsplit('.', 1)[0] or node_str
                    return name
                m = re.match(r'^([a-zA-Z0-9_-]+):(.+)$', node_str)
                if m:
                    return m.group(2)
                return node_str

            edges_with_details = []
            if isinstance(edge_list, list):
                for edge in edge_list[:50]:
                    if isinstance(edge, dict):
                        source_raw = edge.get('source', '')
                        target_raw = edge.get('target', '')
                        edges_with_details.append({
                            "source": source_raw,
                            "sourceDisplay": _edge_display_name(source_raw),
                            "target": target_raw,
                            "targetDisplay": _edge_display_name(target_raw),
                            "type": edge.get('type', edge_type),
                            "direction": "caller→callee" if edge.get('type', '').upper() == 'CALL' else "dependency",
                        })
                    elif isinstance(edge, str):
                        edges_with_details.append({"source": edge, "target": "?", "type": edge_type})

            actual_node_count = len(nodes_with_paths)
            actual_edge_count = len(edges_with_details)
            if actual_node_count != comm['node_count']:
                logger.warning(
                    f"[report.getLevelCommunityDetail] node_count mismatch: "
                    f"comm={comm['comm_id']} stored={comm['node_count']} actual={actual_node_count}"
                )
            if actual_edge_count != comm['edge_count']:
                logger.warning(
                    f"[report.getLevelCommunityDetail] edge_count mismatch: "
                    f"comm={comm['comm_id']} stored={comm['edge_count']} actual={actual_edge_count}"
                )
            result.append({
                "communityId": comm['comm_id'],
                "parentCommunityId": comm.get('parent_comm_id'),
                "level": comm['comm_lv'],
                "nodeCount": actual_node_count,
                "edgeCount": actual_edge_count,
                "qualityScore": comm.get('quality_score'),
                "nodes": nodes_with_paths,
                "edges": edges_with_details,
            })
        logger.info("[report.getLevelCommunityDetail] DONE task_id=%s level=%s edge_type=%s communities=%d total_nodes=%d total_edges=%d",
                     tid, level, et, len(result),
                     sum(c.get('nodeCount', 0) for c in result),
                     sum(c.get('edgeCount', 0) for c in result))
        return {"communities": result, "count": len(result), "level": level, "taskId": task_id}

    @server.register("report.saveFileSummaries")
    def save_file_summaries(project_id=None, task_id=None, summaries=None,
                            projectId=None, taskId=None):
        """批量保存文件摘要到 file_summaries 表"""
        pid = project_id or projectId
        tid = task_id or taskId
        project_db = multi_db.get_project_db(pid)
        import uuid
        now = datetime.now().isoformat()
        saved = 0
        for s in (summaries or []):
            sid = f"fs-{uuid.uuid4().hex[:8]}"
            summary_text = s.get('summary', '')[:100]
            try:
                project_db.execute(
                    """INSERT OR REPLACE INTO file_summaries
                       (id, project_id, task_id, file_path, summary, summary_len, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sid, pid, tid, s['filePath'], summary_text, len(summary_text),
                     s.get('source', 'llm'), now, now),
                )
                saved += 1
            except Exception as e:
                logger.warning(f"[report] Failed to save summary for {s.get('filePath')}: {e}")
        project_db.commit()
        return {"saved": saved}

    @server.register("report.getFileSummaries")
    def get_file_summaries(project_id=None, task_id=None, source='llm',
                            projectId=None, taskId=None):
        """获取文件摘要列表"""
        pid = project_id or projectId
        tid = task_id or taskId
        project_db = multi_db.get_project_db(pid)
        sql = "SELECT * FROM file_summaries WHERE project_id = ?"
        params = [pid]
        if tid:
            sql += " AND task_id = ?"
            params.append(tid)
        if source:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY created_at DESC"
        rows = project_db.fetchall(sql, tuple(params))
        return {"summaries": rows, "count": len(rows)}

    # ==================== LLM 调用日志查询 ====================

    @server.register("report.getCallLogs")
    def get_call_logs(
        session_id: str = None,
        request_id: str = None,
        template_id: str = None,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """查询 LLM 调用日志（llm_call_logs）"""
        main_db = multi_db.main_db
        sql = "SELECT * FROM llm_call_logs WHERE 1=1"
        params = []
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        if request_id:
            sql += " AND request_id = ?"
            params.append(request_id)
        if template_id:
            sql += " AND template_id = ?"
            params.append(template_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = main_db.fetchall(sql, tuple(params))
        return {"logs": rows, "count": len(rows)}

    @server.register("report.getInteractionLogs")
    def get_interaction_logs(
        session_id: str = None,
        request_id: str = None,
        template_id: str = None,
        limit: int = 100,
        offset: int = 0,
    ):
        """查询报告交互日志（report_interaction_log）"""
        main_db = multi_db.main_db
        sql = "SELECT * FROM report_interaction_log WHERE 1=1"
        params = []
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        if request_id:
            sql += " AND request_id = ?"
            params.append(request_id)
        if template_id:
            sql += " AND json_extract(meta_json, '$.template_id') = ?"
            params.append(template_id)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = main_db.fetchall(sql, tuple(params))
        return {"logs": rows, "count": len(rows)}

    # ==================== 报告文档持久化 ====================

    @server.register("report.saveOverallDoc")
    def save_overall_doc(task_id=None, title=None, content=None, taskId=None):
        """保存或更新整体架构文档到 report_subdocs"""
        tid = task_id or taskId
        if not tid or not title or not content:
            raise ValueError("taskId, title, and content are required")
        return _save_overall_doc(multi_db, tid, title, content)

    return server


