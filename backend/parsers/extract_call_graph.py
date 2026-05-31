# parsers/extract_call_graph.py
"""
多语言调用图提取器 — SQLite 版本

从 SQLite 项目库中的 AST 节点提取函数调用关系，并写入 graph_node 表。
使用策略模式，根据项目的主要编程语言自动选择对应的提取器。

支持的语言:
- C/C++: 函数调用、宏调用
- Python: 函数调用、方法调用
- Java: 方法调用、构造函数调用
- JavaScript/TypeScript: 函数调用、方法调用
- Go: 函数调用、方法调用

架构:
- 使用 CallGraphExtractorRegistry 注册和获取语言特定的提取器
- 每个语言提取器实现 CallGraphExtractor 抽象基类
- 支持多语言混合项目（按文件语言分别处理）
"""
import json
import logging
import os
from typing import Dict, Any, List, Optional, Set
from collections import defaultdict

from parsers.db_adapter import SQLiteAdapter

# 导入调用图提取器工厂
from parsers.call_parser.extractor_factory import (
    CallGraphExtractorRegistry,
    get_call_graph_extractor,
    get_supported_call_graph_languages
)

logger = logging.getLogger(__name__)


def extract_call_graph(adapter: SQLiteAdapter, language: str = None) -> List[Dict[str, Any]]:
    """
    从 SQLite 项目库提取调用图，写入 graph_node 表

    **文件级语言分发**：遍历所有文件，按每个文件的语言路由到对应提取器，
    支持多语言混合项目。

    Args:
        adapter: SQLiteAdapter 实例
        language: 指定语言（可选），如果为 None 则按文件级语言分发

    Returns:
        调用边列表
    """
    task_id = adapter._task_id
    logger.info(f"[extract_call_graph] 入口: task_id={task_id}, adapter._store id={id(adapter._store)}, language={language}")

    # === Step 1: 获取项目文件信息 ===
    # 如果指定了 language，按该语言过滤；否则获取所有文件（文件级分发）
    files = adapter.list_files(language=language)
    if not files:
        logger.warning(f"No files found for task {task_id}" + (f" with language={language}" if language else ""))
        return []

    file_id_to_name: Dict[str, str] = {f["id"]: f.get("file_path", "") for f in files}
    file_ids = list(file_id_to_name.keys())

    logger.info(f"Found {len(files)} files for task {task_id}" + (f" (language={language})" if language else ""))

    # === Step 2: 加载 AST 节点（按 file_id 分组） ===
    logger.info("Loading AST nodes from base_node...")
    all_nodes_by_file_id: Dict[str, Dict[str, Dict]] = defaultdict(dict)

    for file_id in file_ids:
        nodes_list = adapter.find_nodes(file_id=file_id)
        for node in nodes_list:
            all_nodes_by_file_id[file_id][node["node_id"]] = node

    logger.info(f"Loaded {sum(len(nodes) for nodes in all_nodes_by_file_id.values())} AST nodes")

    # === Step 3: 构建全局符号映射 ===
    logger.info("Building global function definition map...")
    global_func_def_map = _build_function_map(adapter)
    logger.info(f"Found {len(global_func_def_map)} global functions")

    logger.info("Building global macro map...")
    global_macro_map = _build_macro_map(adapter)
    logger.info(f"Found {len(global_macro_map)} global macros")

    # === Step 4: 按文件级语言分发提取调用边 ===
    logger.info("Extracting call edges...")

    # 统计 call_expression
    call_expr_count = 0
    for file_id, nodes in all_nodes_by_file_id.items():
        for node in nodes.values():
            if node.get("type") == "call_expression":
                call_expr_count += 1

    logger.info(f"AST 节点统计：call_expression={call_expr_count}")

    # 文件级语言分发：按文件语言分组
    files_by_language: Dict[str, List[str]] = defaultdict(list)
    for file_id, file_path in file_id_to_name.items():
        file_lang = _detect_file_language(file_path)
        files_by_language[file_lang].append(file_id)

    lang_stats = {lang: len(fids) for lang, fids in files_by_language.items()}
    logger.info(f"[extract_call_graph] 文件级语言分发: {lang_stats}")

    all_call_edges: List[Dict[str, Any]] = []

    # 遍历每种语言的文件组
    for file_lang, file_group in files_by_language.items():
        extractor = get_call_graph_extractor(file_lang)
        if extractor is None:
            logger.warning(f"No call graph extractor for language '{file_lang}', using generic logic")
            # fallback 到通用提取逻辑
            for file_id in file_group:
                nodes = all_nodes_by_file_id[file_id]
                edges = _extract_file_call_edges(
                    file_id=file_id,
                    nodes=nodes,
                    global_func_def_map=global_func_def_map,
                    global_macro_map=global_macro_map,
                    extractor=None,
                )
                all_call_edges.extend(edges)
            continue

        logger.info(f"[extract_call_graph] 使用 {file_lang} 提取器处理 {len(file_group)} 个文件")

        # 构建该语言的文件节点映射
        lang_nodes_by_file: Dict[str, Dict[str, Dict]] = {}
        for file_id in file_group:
            lang_nodes_by_file[file_id] = all_nodes_by_file_id[file_id]

        # 对于 Java/JavaScript/TypeScript/C/C++/Go，使用专门的提取器
        if file_lang in ['java', 'javascript', 'typescript', 'c', 'cpp', 'go']:
            logger.info(f"[extract_call_graph] {file_lang} 专用提取器: nodes_by_file count={len(lang_nodes_by_file)}")
            call_edges = extractor.extract(adapter._task_id, lang_nodes_by_file)
            logger.info(f"[extract_call_graph] {file_lang} 专用提取器返回: {len(call_edges)} 条边")
            all_call_edges.extend(call_edges)
        else:
            # 通用提取逻辑
            for file_id in file_group:
                nodes = all_nodes_by_file_id[file_id]
                edges = _extract_file_call_edges(
                    file_id=file_id,
                    nodes=nodes,
                    global_func_def_map=global_func_def_map,
                    global_macro_map=global_macro_map,
                    extractor=extractor,
                )
                all_call_edges.extend(edges)

    call_edges = all_call_edges

    # === Step 5: 保存调用边 ===
    if call_edges:
        adapter.insert_graph(call_edges)
        logger.info(f"Inserted {len(call_edges)} call edges into graph_node for task {task_id}")
    else:
        logger.info(f"No call edges found for task {task_id}")

    return call_edges


def _detect_file_language(file_path: str) -> str:
    """
    根据文件扩展名检测语言（文件级）

    Returns:
        语言名称，未知语言返回 'unknown'
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    # 扩展名到语言的映射
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


def _detect_project_language(files: List[Dict]) -> str:
    """自动检测项目主要语言（排除非代码文件）"""
    CODE_LANGUAGES = {'c', 'cpp', 'c_header', 'cpp_header', 'python', 'javascript', 'typescript',
                      'tsx', 'java', 'go', 'rust', 'ruby', 'php', 'swift', 'kotlin', 'csharp'}
    lang_count: Dict[str, int] = defaultdict(int)
    for f in files:
        lang = f.get("language")
        if lang and lang in CODE_LANGUAGES:
            lang_count[lang] += 1

    if not lang_count:
        return "python"  # 默认

    return max(lang_count, key=lang_count.get)


def _build_function_map(adapter: SQLiteAdapter) -> Dict[str, Dict]:
    """构建全局函数定义映射：func_name -> {file_id, node_id}"""
    func_map: Dict[str, Dict] = {}

    # 获取所有函数符号（C/C++/Python/JS/Go/Rust 用 func_name）
    symbols = adapter.find_graph(symbol_node_type='func_name')
    for s in symbols:
        func_name = s.get('func_name')
        if func_name:
            if func_name not in func_map:
                func_map[func_name] = {
                    'file_id': s.get('file_id'),
                    'node_id': s.get('def_node_id'),
                }

    # 获取方法符号（Java 用 method_name）
    methods = adapter.find_graph(symbol_node_type='method_name')
    for m in methods:
        method_name = m.get('method_name')
        if method_name:
            if method_name not in func_map:
                func_map[method_name] = {
                    'file_id': m.get('file_id'),
                    'node_id': m.get('def_node_id'),
                }

    return func_map


def _build_macro_map(adapter: SQLiteAdapter) -> Dict[str, Dict]:
    """构建全局宏定义映射"""
    macro_map: Dict[str, Dict] = {}

    # 查询 macro 和 macro_name（兼容不同语言的写入格式）
    macros = adapter.find_graph(symbol_node_type='macro')
    if not macros:
        macros = adapter.find_graph(symbol_node_type='macro_name')
    for m in macros:
        macro_name = m.get('macro_name')
        if macro_name:
            if macro_name not in macro_map:
                macro_map[macro_name] = {
                    'file_id': m.get('file_id'),
                    'node_id': m.get('def_node_id'),
                }

    return macro_map


def _extract_call_edges(
    adapter: SQLiteAdapter,
    all_nodes_by_file_id: Dict[str, Dict[str, Dict]],
    global_func_def_map: Dict[str, Dict],
    global_macro_map: Dict[str, Dict],
    extractor,
    project_language: str,
) -> List[Dict[str, Any]]:
    """
    通用调用边提取逻辑

    遍历每个文件的 AST 节点，识别调用表达式，解析 callee，生成调用边。
    """
    task_id = adapter._task_id
    call_edges: List[Dict[str, Any]] = []

    for file_id, nodes in all_nodes_by_file_id.items():
        edges = _extract_file_call_edges(
            file_id=file_id,
            nodes=nodes,
            global_func_def_map=global_func_def_map,
            global_macro_map=global_macro_map,
            extractor=extractor,
        )
        call_edges.extend(edges)

    return call_edges


def _extract_file_call_edges(
    file_id: str,
    nodes: Dict[str, Dict],
    global_func_def_map: Dict[str, Dict],
    global_macro_map: Dict[str, Dict],
    extractor,
) -> List[Dict[str, Any]]:
    """提取单个文件的调用边"""
    call_edges: List[Dict[str, Any]] = []

    # 获取调用表达式类型
    call_types = getattr(extractor, 'CALL_EXPRESSION_TYPES', {'call', 'call_expression'})

    for node_id, node in nodes.items():
        if node.get("type") not in call_types:
            continue

        # 提取调用信息
        caller_func = _find_enclosing_function(node_id, nodes)
        callee_name = _extract_callee_name(node, nodes)

        if not callee_name:
            continue

        # 解析 callee 定义位置
        callee_info = global_func_def_map.get(callee_name) or global_macro_map.get(callee_name)

        edge = {
            "symbol_node_type": "call_relation",
            "caller_file_id": file_id,
            "caller_func_name": caller_func,
            "caller_node_id": node_id,
            "callee_name": callee_name,
        }

        if callee_info:
            edge["callee_file_id"] = callee_info.get("file_id")
            edge["callee_node_id"] = callee_info.get("node_id")

        call_edges.append(edge)

    return call_edges


def _find_enclosing_function(node_id: str, nodes: Dict[str, Dict]) -> Optional[str]:
    """查找包含调用点的函数"""
    node = nodes.get(node_id)
    if not node:
        return None

    scope_id = node.get("scope_node_id")
    if scope_id is not None:
        # scope_node_id 可能是 int 或 str
        scope_key = str(scope_id)
        scope_node = nodes.get(scope_key)
        if scope_node and scope_node.get("type") in ("function_definition", "method_definition", "function_declaration"):
            return scope_node.get("name")

    return None


def _extract_callee_name(node: Dict, nodes: Dict[str, Dict]) -> Optional[str]:
    """从调用表达式提取被调用函数名"""
    refs = node.get("refs", [])
    # refs 在 SQLite 中存为 JSON 字符串，需解析
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except (json.JSONDecodeError, TypeError):
            refs = []
    if refs and isinstance(refs, list):
        return refs[0] if isinstance(refs[0], str) else str(refs[0])

    return node.get("name")


def main():
    """CLI 入口（用于独立测试）"""
    import sys
    if len(sys.argv) < 2:
        print("Usage: python extract_call_graph.py <task_id>")
        sys.exit(1)

    task_id = sys.argv[1]
    print(f"Extracting call graph for task: {task_id}")
    # 实际使用需要通过 analyst_runner 调用
