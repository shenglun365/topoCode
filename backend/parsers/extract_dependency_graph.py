# parsers/extract_dependency_graph.py
"""
多语言依赖图提取器 — SQLite 版本

从 SQLite 项目库中的 AST 节点提取文件级依赖关系（import/include/require），
并写入 graph_node 表。

支持的语言:
- C/C++: #include
- Python: import / from ... import
- Java: import
- JavaScript/TypeScript: import / require
- Go: import

架构:
- 使用 DependencyExtractorRegistry 注册和获取语言特定的提取器
- 每个语言提取器实现 DependencyExtractor 抽象基类
"""
import json
import logging
import os
from typing import Dict, Any, List, Optional
from collections import defaultdict

from parsers.db_adapter import SQLiteAdapter

# 导入依赖图提取器工厂
from parsers.dependence_parser.extractor_factory import (
    DependencyExtractorRegistry,
    get_dependency_extractor,
    get_supported_dependency_languages
)

logger = logging.getLogger(__name__)


def extract_dependency_graph(adapter: SQLiteAdapter, language: str = None) -> List[Dict[str, Any]]:
    """
    从 SQLite 项目库提取依赖图，写入 graph_node 表

    Args:
        adapter: SQLiteAdapter 实例
        language: 指定语言（可选）

    Returns:
        依赖边列表
    """
    task_id = adapter._task_id
    logger.info(f"[extract_dependency_graph] 入口: task_id={task_id}, adapter._store id={id(adapter._store)}, language={language}")

    # === Step 1: 获取项目文件信息 ===
    files = adapter.list_files(language=language)
    if not files:
        logger.warning(f"No files found for task {task_id}")
        return []

    file_id_to_path: Dict[str, str] = {f["id"]: f.get("file_path", "") for f in files}
    path_to_file_id: Dict[str, str] = {v: k for k, v in file_id_to_path.items()}

    logger.info(f"Found {len(files)} files for dependency extraction")

    # === Step 2: 确定语言并获取提取器 ===
    project_language = language or _detect_project_language(files)
    extractor = get_dependency_extractor(project_language)

    if extractor is None:
        supported = get_supported_dependency_languages()
        logger.warning(f"No dependency extractor for '{project_language}'. Supported: {supported}")
        return _extract_generic_dependencies(adapter, files, file_id_to_path, path_to_file_id)

    logger.info(f"Using DependencyExtractor for language: {project_language}")

    # === Step 3: 加载 AST 节点 ===
    all_nodes_by_file: Dict[str, Dict[str, Dict]] = defaultdict(dict)
    for file_id in file_id_to_path:
        nodes_list = adapter.find_nodes(file_id=file_id)
        for node in nodes_list:
            all_nodes_by_file[file_id][node["node_id"]] = node

    # === Step 4: 提取依赖边 ===
    dep_edges: List[Dict[str, Any]] = []

    for file_id, nodes in all_nodes_by_file.items():
        edges = _extract_file_dependencies(
            file_id=file_id,
            file_path=file_id_to_path.get(file_id, ""),
            nodes=nodes,
            path_to_file_id=path_to_file_id,
            extractor=extractor,
        )
        dep_edges.extend(edges)

    # === Step 5: 保存依赖边 ===
    if dep_edges:
        adapter.insert_graph(dep_edges)
        logger.info(f"Inserted {len(dep_edges)} dependency edges for task {task_id}")
    else:
        logger.info(f"No dependency edges found for task {task_id}")

    return dep_edges


def _detect_project_language(files: List[Dict]) -> str:
    """自动检测项目主要语言（排除非代码文件）"""
    CODE_LANGUAGES = {'c', 'cpp', 'c_header', 'cpp_header', 'python', 'javascript', 'typescript',
                      'tsx', 'java', 'go', 'rust', 'ruby', 'php', 'swift', 'kotlin', 'csharp'}
    lang_count: Dict[str, int] = defaultdict(int)
    for f in files:
        lang = f.get("language")
        if lang and lang in CODE_LANGUAGES:
            lang_count[lang] += 1
    return max(lang_count, key=lang_count.get) if lang_count else "python"


def _extract_file_dependencies(
    file_id: str,
    file_path: str,
    nodes: Dict[str, Dict],
    path_to_file_id: Dict[str, str],
    extractor,
) -> List[Dict[str, Any]]:
    """提取单个文件的依赖边"""
    dep_edges: List[Dict[str, Any]] = []

    dep_types = getattr(extractor, 'DEPENDENCY_NODE_TYPES', {
        'import_declaration', 'include_declaration', 'import_statement',
        'from_import', 'require_call',
    })

    for node_id, node in nodes.items():
        if node.get("type") not in dep_types:
            continue

        target_path = _extract_dependency_target(node, nodes)
        if not target_path:
            continue

        is_system = _is_system_dependency(target_path, file_path)
        target_file_id = path_to_file_id.get(target_path)

        edge = {
            "symbol_node_type": "dependence",
            "file_id": file_id,
            "include_path": target_path,
            "is_system": 1 if is_system else 0,
        }

        if target_file_id:
            edge["callee_file_id"] = target_file_id

        dep_edges.append(edge)

    return dep_edges


def _extract_dependency_target(node: Dict, nodes: Dict[str, Dict]) -> Optional[str]:
    """从依赖节点提取目标路径"""
    refs = node.get("refs", [])
    # refs 在 SQLite 中存为 JSON 字符串，需解析
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except (json.JSONDecodeError, TypeError):
            refs = []
    if refs and isinstance(refs, list):
        ref = refs[0] if isinstance(refs[0], str) else str(refs[0])
        return ref.strip('"').strip("'").strip('<').strip('>')

    return node.get("name")


def _is_system_dependency(target_path: str, source_path: str) -> bool:
    """判断是否为系统库依赖"""
    if target_path.startswith('/'):
        return True
    if not os.path.isabs(target_path):
        return not any(target_path.endswith(ext) for ext in
                       ['.py', '.c', '.cpp', '.h', '.java', '.js', '.ts', '.go'])
    return False


def _extract_generic_dependencies(
    adapter: SQLiteAdapter,
    files: List[Dict],
    file_id_to_path: Dict[str, str],
    path_to_file_id: Dict[str, str],
) -> List[Dict[str, Any]]:
    """通用依赖提取（当没有语言特定提取器时使用）"""
    dep_edges: List[Dict[str, Any]] = []

    for file_rec in files:
        file_id = file_rec["id"]
        file_path = file_rec.get("file_path", "")
        nodes_list = adapter.find_nodes(file_id=file_id)

        for node in nodes_list:
            node_type = node.get("type", "")
            if node_type not in ('import_declaration', 'include_declaration', 'import_statement',
                                  'from_import', 'require_call'):
                continue

            target = _extract_dependency_target(node, {})
            if target:
                is_system = _is_system_dependency(target, file_path)
                target_file_id = path_to_file_id.get(target)

                edge = {
                    "symbol_node_type": "dependence",
                    "file_id": file_id,
                    "include_path": target,
                    "is_system": 1 if is_system else 0,
                }
                if target_file_id:
                    edge["callee_file_id"] = target_file_id

                dep_edges.append(edge)

    return dep_edges
