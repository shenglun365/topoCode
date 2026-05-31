# parsers/extract_global_symbols.py
# 符号提取：提取数据结构、宏定义、函数、类等的 AST 信息
# SQLite 版本：从项目库读取 base_node，写入 graph_node

import json
import logging
import os
from collections import defaultdict
from typing import Dict, List, Any, Optional

from parsers.symbol_parser.language_handlers import get_handler_for_extension
from parsers.db_adapter import SQLiteAdapter

logger = logging.getLogger(__name__)


def detect_language_handler(filename: str):
    """
    根据文件扩展名返回对应的语言处理器
    
    实现真正的文件级语言分发，各语言独立隔离。
    """
    ext = os.path.splitext(filename)[1].lower()
    return get_handler_for_extension(ext)


def extract_java_symbols(file_id: str, nodes: Dict[str, Dict],
                         global_defs: List[Dict[str, Any]], class_defs: List[Dict[str, Any]]):
    """提取 Java 方法的符号"""
    method_types = {'method_declaration', 'constructor_declaration'}
    class_types = {'class_declaration', 'interface_declaration', 'enum_declaration'}

    for node in nodes.values():
        node_type = node.get("type")

        if node_type in class_types:
            class_name = node.get("name") or (node.get("refs")[0] if node.get("refs") else None)
            if class_name:
                class_defs.append({
                    "file_id": file_id,
                    "symbol_node_type": "class_name",
                    "class_name": class_name,
                    "def_file_id": file_id,
                    "def_node_id": str(node["node_id"]),
                    "start_line": str(node["start"]),
                    "end_line": str(node["end"])
                })

        elif node_type in method_types:
            method_name = node.get("name")
            if not method_name and node.get("refs"):
                method_name = node["refs"][0] if node_type == 'constructor_declaration' else next(
                    (ref for ref in node["refs"] if ref and len(ref) > 0 and ref[0].islower()), None)

            if not method_name:
                method_node_id = node["node_id"]
                for child_node in nodes.values():
                    if child_node.get("type") == "identifier" and child_node.get("scope_node_id") == method_node_id:
                        candidate_name = child_node.get("name")
                        if candidate_name and len(candidate_name) > 0 and candidate_name[0].islower():
                            method_name = candidate_name
                            break

            if method_name:
                global_defs.append({
                    "file_id": file_id,
                    "symbol_node_type": "method_name",
                    "method_name": method_name,
                    "def_file_id": file_id,
                    "def_node_id": str(node["node_id"]),
                    "start_line": str(node["start"]),
                    "end_line": str(node["end"])
                })


def extract_typescript_symbols(file_id: str, nodes: Dict[str, Dict],
                               global_defs: List[Dict[str, Any]], class_defs: List[Dict[str, Any]],
                               language: str = "typescript"):
    """提取 TypeScript/JavaScript 符号"""
    function_types = {'function_declaration', 'arrow_function', 'method_definition'}
    class_types = {'class_declaration', 'interface_declaration', 'type_alias_declaration'}

    for node in nodes.values():
        node_type = node.get("type")

        if node_type in class_types:
            class_name = node.get("name") or (node.get("refs")[0] if node.get("refs") else None)
            if class_name:
                class_defs.append({
                    "file_id": file_id,
                    "symbol_node_type": "class_name",
                    "class_name": class_name,
                    "def_file_id": file_id,
                    "def_node_id": str(node["node_id"]),
                    "start_line": str(node["start"]),
                    "end_line": str(node["end"])
                })

        elif node_type in function_types:
            method_name = node.get("name")
            if not method_name and node.get("refs"):
                method_name = node["refs"][0]

            if method_name:
                global_defs.append({
                    "file_id": file_id,
                    "symbol_node_type": "func_name",
                    "func_name": method_name,
                    "def_file_id": file_id,
                    "def_node_id": str(node["node_id"]),
                    "start_line": str(node["start"]),
                    "end_line": str(node["end"])
                })


def extract_global_symbols(adapter: SQLiteAdapter) -> int:
    """
    从 SQLite 项目库中提取全局符号（宏、函数、方法、类等）

    Args:
        adapter: SQLiteAdapter 实例

    Returns:
        提取的符号总数
    """
    task_id = adapter._task_id

    # 获取所有文件
    files = adapter.list_files()
    if not files:
        logger.warning(f"No files found for task {task_id}")
        return 0

    file_id_to_name: Dict[str, str] = {f["id"]: f.get("file_path", "") for f in files}

    # 统计语言分布
    lang_stats: Dict[str, int] = defaultdict(int)
    for f in files:
        ext = os.path.splitext(f.get("file_path", ""))[1].lower()
        if ext == '.java':
            lang_stats['java'] += 1
        elif ext in ['.ts', '.tsx', '.mts', '.js', '.jsx', '.mjs']:
            lang_stats['ts_js'] += 1
        else:
            lang_stats['other(CFamily)'] += 1
    logger.info(f"[extract_global_symbols] 入口: task_id={task_id}, total_files={len(files)}, lang_distribution={dict(lang_stats)}")

    macro_records: List[Dict[str, Any]] = []
    global_defs: List[Dict[str, Any]] = []
    class_defs: List[Dict[str, Any]] = []

    processed_count = 0
    java_count = 0
    ts_js_count = 0
    c_family_count = 0

    for file_rec in files:
        file_id = file_rec["id"]
        filename = file_rec.get("file_path", "")
        processed_count += 1

        if processed_count % 50 == 0:
            logger.info(f"Processed {processed_count}/{len(files)} files")

        # 查询该文件的所有 AST 节点
        nodes_list = adapter.find_nodes(file_id=file_id)
        nodes: Dict[str, Dict] = {n["node_id"]: n for n in nodes_list}

        if not nodes:
            continue

        ext = os.path.splitext(filename)[1].lower()
        handler = detect_language_handler(filename)

        # 按语言分类统计
        if ext == '.java':
            java_count += 1
        elif ext in ['.ts', '.tsx', '.mts', '.js', '.jsx', '.mjs']:
            ts_js_count += 1
        else:
            c_family_count += 1

        # 统一的符号提取逻辑 — 各语言处理器独立处理
        for node in nodes.values():
            node_type = node.get("type")

            # 预处理宏（仅 C 家族支持）
            if node_type in handler.preproc_node_types:
                macro_name = handler.extract_macro_name(node, nodes)
                if macro_name:
                    macro_records.append({
                        "file_id": file_id,
                        "symbol_node_type": "macro_name",
                        "macro_name": macro_name,
                        "def_file_id": file_id,
                        "def_node_id": str(node["node_id"]),
                        "start_line": str(node["start"]),
                        "end_line": str(node["end"]),
                    })

            # 函数/方法定义 (Go: function_declaration, method_declaration)
            elif node_type in ("function_definition", "function_declaration", "method_declaration", "constructor_declaration"):
                func_name = handler.extract_function_name(node, nodes)
                if func_name:
                    # Java 方法使用 method_name，其他语言使用 func_name
                    symbol_type = "method_name" if ext == '.java' else "func_name"
                    global_defs.append({
                        "file_id": file_id,
                        "symbol_node_type": symbol_type,
                        "func_name": func_name if symbol_type == "func_name" else None,
                        "method_name": func_name if symbol_type == "method_name" else None,
                        "def_file_id": file_id,
                        "def_node_id": str(node["node_id"]),
                        "start_line": str(node["start"]),
                        "end_line": str(node["end"])
                    })

            # 类/接口/枚举定义 (Go: type_declaration, struct_type, interface_type)
            elif node_type in ("class_specifier", "struct_specifier", "class_declaration",
                              "interface_declaration", "enum_declaration",
                              "interface_declaration", "type_alias_declaration",
                              "type_declaration", "struct_type", "interface_type"):
                class_name = handler.extract_class_name(node, nodes)
                if class_name:
                    class_defs.append({
                        "file_id": file_id,
                        "symbol_node_type": "class_name",
                        "class_name": class_name,
                        "def_file_id": file_id,
                        "def_node_id": str(node["node_id"]),
                        "start_line": str(node["start"]),
                        "end_line": str(node["end"])
                    })

    # 写入 graph_node
    all_records = macro_records + global_defs + class_defs
    logger.info(f"[extract_global_symbols] 处理完成: java={java_count}, ts_js={ts_js_count}, c_family={c_family_count}, macros={len(macro_records)}, funcs={len(global_defs)}, classes={len(class_defs)}")
    if all_records:
        adapter.insert_graph(all_records)
        logger.info(f"Inserted {len(all_records)} symbol records into graph_node for task {task_id}")
    else:
        logger.info(f"No global symbols found for task {task_id}")

    return len(all_records)
