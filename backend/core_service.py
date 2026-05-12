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
from typing import Optional

logger = logging.getLogger(__name__)

from sqlite_ctx import SQLiteContext, MultiDBManager
from zmq_server import ZMQServer



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


