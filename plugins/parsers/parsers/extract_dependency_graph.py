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

    **文件级语言分发**：遍历所有文件，按每个文件的语言路由到对应提取器，
    支持多语言混合项目。

    Args:
        adapter: SQLiteAdapter 实例
        language: 指定语言（可选），如果为 None 则按文件级语言分发

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

    # === Step 2: 加载 AST 节点 ===
    all_nodes_by_file: Dict[str, Dict[str, Dict]] = defaultdict(dict)
    for file_id in file_id_to_path:
        nodes_list = adapter.find_nodes(file_id=file_id)
        for node in nodes_list:
            all_nodes_by_file[file_id][node["node_id"]] = node

    # === Step 3: 按文件级语言分发提取依赖边 ===
    # 文件级语言分发：按文件语言分组
    files_by_language: Dict[str, List[str]] = defaultdict(list)
    for file_id, file_path in file_id_to_path.items():
        file_lang = _detect_file_language(file_path)
        files_by_language[file_lang].append(file_id)

    lang_stats = {lang: len(fids) for lang, fids in files_by_language.items()}
    logger.info(f"[extract_dependency_graph] 文件级语言分发: {lang_stats}")

    all_dep_edges: List[Dict[str, Any]] = []

    # 遍历每种语言的文件组
    for file_lang, file_group in files_by_language.items():
        extractor = get_dependency_extractor(file_lang)
        if extractor is None:
            logger.warning(f"No dependency extractor for '{file_lang}', using generic logic")
            # fallback 到通用提取逻辑
            for file_id in file_group:
                file_path = file_id_to_path.get(file_id, "")
                nodes = all_nodes_by_file[file_id]
                edges = _extract_file_dependencies_generic(
                    file_id=file_id,
                    file_path=file_path,
                    nodes=nodes,
                    path_to_file_id=path_to_file_id,
                )
                all_dep_edges.extend(edges)
            continue

        logger.info(f"[extract_dependency_graph] 使用 {file_lang} 提取器处理 {len(file_group)} 个文件")

        for file_id in file_group:
            file_path = file_id_to_path.get(file_id, "")
            nodes = all_nodes_by_file[file_id]
            edges = _extract_file_dependencies(
                file_id=file_id,
                file_path=file_path,
                nodes=nodes,
                path_to_file_id=path_to_file_id,
                extractor=extractor,
            )
            all_dep_edges.extend(edges)

    dep_edges = all_dep_edges

    # === Step 4: 保存依赖边 ===
    if dep_edges:
        adapter.insert_graph(dep_edges)
        logger.info(f"Inserted {len(dep_edges)} dependency edges for task {task_id}")
    else:
        logger.info(f"No dependency edges found for task {task_id}")

    return dep_edges


def _detect_file_language(file_path: str) -> str:
    """
    根据文件扩展名检测语言（文件级）

    Returns:
        语言名称，未知语言返回 'unknown'
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    ext_to_lang = {
        '.c': 'c', '.h': 'c',
        '.cpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp', '.hh': 'cpp', '.hxx': 'cpp',
        '.java': 'java',
        '.py': 'python', '.pyw': 'python', '.pyi': 'python',
        '.js': 'javascript', '.jsx': 'javascript', '.mjs': 'javascript', '.es6': 'javascript',
        '.ts': 'typescript', '.tsx': 'typescript', '.cts': 'typescript', '.mts': 'typescript',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.php': 'php',
        '.cs': 'csharp',
        '.swift': 'swift',
        '.kt': 'kotlin',
    }
    
    return ext_to_lang.get(ext, 'unknown')


def _extract_file_dependencies_generic(
    file_id: str,
    file_path: str,
    nodes: Dict[str, Dict],
    path_to_file_id: Dict[str, str],
) -> List[Dict[str, Any]]:
    """通用依赖提取（当没有语言特定提取器时使用）"""
    dep_edges: List[Dict[str, Any]] = []

    for node_id, node in nodes.items():
        node_type = node.get("type", "")
        if node_type not in ('import_declaration', 'include_declaration', 'import_statement',
                              'from_import', 'require_call'):
            continue

        target = _extract_dependency_target(node, nodes)
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
    """
    提取单个文件的依赖边

    修复: 优先调用语言特定提取器的 extract_dependencies() 方法，
    各语言提取器中精心实现的逻辑（如 Java 静态导入区分、Python 相对导入）才能真正生效。
     fallback 到通用提取逻辑。
    """
    dep_edges: List[Dict[str, Any]] = []

    # 获取依赖相关的 AST 节点类型
    try:
        dep_types = extractor.get_required_node_types()
    except (AttributeError, NotImplementedError):
        dep_types = [
            'import_declaration', 'include_declaration', 'import_statement',
            'from_import', 'require_call',
        ]

    # 收集依赖节点
    dep_nodes = []
    for node_id, node in nodes.items():
        if node.get("type") not in dep_types:
            continue
        # 附加 file_id 供 extract_dependencies 使用
        node_with_file = dict(node)
        node_with_file["file_id"] = file_id
        dep_nodes.append(node_with_file)

    if not dep_nodes:
        return dep_edges

    # 尝试调用语言特定的 extract_dependencies()
    try:
        dependencies, system_targets = extractor.extract_dependencies(dep_nodes)

        for dep in dependencies:
            target = dep.get("target", "")
            if not target:
                continue

            is_system = dep.get("is_system", target in system_targets
                             or _is_system_dependency(target, file_path))
            target_file_id = path_to_file_id.get(target)

            edge = {
                "symbol_node_type": "dependence",
                "file_id": file_id,
                "include_path": target,
                "is_system": 1 if is_system else 0,
            }

            if target_file_id:
                edge["callee_file_id"] = target_file_id

            # 保留额外属性
            if dep.get("is_static"):
                edge["is_static_import"] = 1
            if dep.get("is_wildcard"):
                edge["is_wildcard"] = 1

            dep_edges.append(edge)

    except (AttributeError, NotImplementedError):
        # fallback: 通用提取逻辑
        for node in dep_nodes:
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
    """
    从依赖节点提取目标路径

    修复: 原来只取 refs[0] 导致 "org.springframework.beans.BeansException" 被截断为 "org"
    现在拼接完整路径: '.'.join(refs)
    """
    refs = node.get("refs", [])
    # refs 在 SQLite 中存为 JSON 字符串，需解析
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except (json.JSONDecodeError, TypeError):
            refs = []

    if refs and isinstance(refs, list):
        # 过滤空元素并统一为字符串
        valid_refs = [str(r).strip('"').strip("'").strip('<').strip('>')
                      for r in refs if r and str(r).strip()]
        if valid_refs:
            # 拼接完整路径: ["org", "springframework", "beans", "BeansException"]
            # → "org.springframework.beans.BeansException"
            return '.'.join(valid_refs)

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
