# parsers/extract_global_symbols.py
# 符号提取：提取数据结构、宏定义、函数、类等的 AST 信息
# 修改为：从 MongoDB 读取 proj_info 和 base_node，写入 graph_node

import json
import logging
import os
from collections import defaultdict
from typing import Dict, List, Any

from parsers.languages.symbol_parser.c_family_handler import CFamilyHandler
from databases.db_pools import get_mongo_client


def detect_language_handler(filename: str):
    """根据文件扩展名返回对应的语言处理器"""
    ext = filename.split('.')[-1].lower() if '.' in filename else ''
    if ext in ('c', 'h', 'cpp', 'cc', 'hpp', 'cxx'):
        return CFamilyHandler()
    return CFamilyHandler()  # 默认


def extract_java_symbols(proj_id: int, file_id: int, nodes: Dict[int, Dict],
                         global_defs: List[Dict[str, Any]], class_defs: List[Dict[str, Any]]):
    """
    提取 Java 方法的符号
    """
    # Java 方法定义节点类型
    method_types = {'method_declaration', 'constructor_declaration'}
    class_types = {'class_declaration', 'interface_declaration', 'enum_declaration'}

    for node in nodes.values():
        node_type = node.get("type")

        # 提取类/接口/枚举
        if node_type in class_types:
            class_name = node.get("name") or (node.get("refs")[0] if node.get("refs") else None)
            if class_name:
                class_defs.append({
                    "proj_id": proj_id,
                    "file_id": file_id,
                    "symbol_node_type": "class_name",
                    "class_name": class_name,
                    "def_file_id": file_id,
                    "def_node_id": node["node_id"],
                    "start_line": node["start"],
                    "end_line": node["end"]
                })

        # 提取方法
        elif node_type in method_types:
            method_name = node.get("name")
            if not method_name and node.get("refs"):
                method_name = node["refs"][0] if node_type == 'constructor_declaration' else next((ref for ref in node["refs"] if ref and len(ref) > 0 and ref[0].islower()), None)

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
                    "proj_id": proj_id,
                    "file_id": file_id,
                    "symbol_node_type": "method_name",
                    "method_name": method_name,
                    "def_file_id": file_id,
                    "def_node_id": node["node_id"],
                    "start_line": node["start"],
                    "end_line": node["end"]
                })


def extract_typescript_symbols(proj_id: int, file_id: int, nodes: Dict[int, Dict],
                               global_defs: List[Dict[str, Any]], class_defs: List[Dict[str, Any]],
                               language: str = "typescript"):
    """
    提取 TypeScript/JavaScript 符号

    支持的符号类型:
    - function_declaration: 函数声明
    - class_declaration: 类声明
    - interface_declaration: 接口声明
    - method_definition: 方法定义
    - arrow_function: 箭头函数
    
    Args:
        proj_id: 项目 ID
        file_id: 文件 ID
        nodes: AST 节点字典
        global_defs: 函数定义列表（输出参数）
        class_defs: 类定义列表（输出参数）
        language: 语言名称（typescript 或 javascript）
    """
    function_types = {'function_declaration', 'arrow_function', 'method_definition'}
    class_types = {'class_declaration', 'interface_declaration', 'type_alias_declaration'}

    for node in nodes.values():
        node_type = node.get("type")

        # 提取类/接口
        if node_type in class_types:
            class_name = node.get("name") or (node.get("refs")[0] if node.get("refs") else None)
            if class_name:
                class_defs.append({
                    "proj_id": proj_id,
                    "file_id": file_id,
                    "symbol_node_type": "class_name",
                    "class_name": class_name,
                    "language": language,  # ← 新增
                    "def_file_id": file_id,
                    "def_node_id": node["node_id"],
                    "start_line": node["start"],
                    "end_line": node["end"]
                })

        # 提取函数
        elif node_type in function_types:
            method_name = node.get("name")
            if not method_name and node.get("refs"):
                method_name = node["refs"][0]

            if method_name:
                global_defs.append({
                    "proj_id": proj_id,
                    "file_id": file_id,
                    "symbol_node_type": "func_name",
                    "func_name": method_name,
                    "language": language,  # ← 新增
                    "def_file_id": file_id,
                    "def_node_id": node["node_id"],
                    "start_line": node["start"],
                    "end_line": node["end"]
                })


def extract_global_symbols(proj_id: int, graph_node_dir: str = None):
    """
    从 MongoDB 中提取全局符号（宏、函数、方法、类等）
    :param proj_id: 项目 ID
    :param graph_node_dir: 保留参数（兼容性），实际不再使用
    """
    # 获取 MongoDB 客户端
    mongo_client = get_mongo_client()
    db = mongo_client.topocode  # 假设数据库名为 topocode

    proj_info_coll = db.proj_info
    base_node_coll = db.base_node
    graph_node_coll = db.graph_node  # 新集合

    # 清理旧数据（可选）
    graph_node_coll.delete_many({"proj_id": proj_id})

    # Step 1: 获取 proj_id 下的所有文件信息
    file_records = list(proj_info_coll.find({"proj_id": proj_id}, {
        "file_id": 1,
        "file_name": 1,
        "_id": 0
    }))
    if not file_records:
        logging.warning(f"No files found for proj_id={proj_id}")
        return

    file_id_to_name: Dict[int, str] = {
        rec["file_id"]: rec["file_name"] for rec in file_records
    }

    macro_records: List[Dict[str, Any]] = []
    global_defs: List[Dict[str, Any]] = []
    class_defs: List[Dict[str, Any]] = []

    # Step 2: 遍历每个文件，加载其 AST 节点
    java_file_count = 0
    processed_count = 0
    
    for file_id, filename in file_id_to_name.items():
        processed_count += 1
        
        # 每处理 50 个文件打印进度
        if processed_count % 50 == 0:
            logging.info(f"Processed {processed_count}/{len(file_id_to_name)} files, Java files: {java_file_count}")
        
        # 查询该文件的所有 AST 节点
        nodes_cursor = base_node_coll.find({
            "proj_id": proj_id,
            "file_id": file_id
        })
        nodes: Dict[int, Dict] = {node["node_id"]: node for node in nodes_cursor}

        if not nodes:
            continue

        # 检测文件类型并提取符号
        ext = os.path.splitext(filename)[1].lower()  # 返回 .java, .py 等

        if ext == '.java':
            # Java 文件特殊处理
            java_file_count += 1
            extract_java_symbols(proj_id, file_id, nodes, global_defs, class_defs)
        elif ext in ['.ts', '.tsx', '.mts', '.js', '.jsx', '.mjs']:
            # TypeScript/JavaScript 文件特殊处理
            extract_typescript_symbols(proj_id, file_id, nodes, global_defs, class_defs)
        else:
            # C/C++ 等其他语言
            handler = detect_language_handler(filename)

            for node in nodes.values():
                node_type = node.get("type")
                if node_type in handler.preproc_node_types:
                    macro_name = handler.extract_macro_name(node, nodes)
                    if macro_name:
                        macro_records.append({
                            "proj_id": proj_id,
                            "file_id": file_id,
                            "symbol_node_type": "macro_name",
                            "macro_name": macro_name,
                            "def_file_id": file_id,
                            "def_node_id": node["node_id"],
                            "start_line": node["start"],
                            "end_line": node["end"],
                        })
                elif node_type == "function_definition":
                    func_name = handler.extract_function_name(node, nodes)
                    if func_name:
                        global_defs.append({
                            "proj_id": proj_id,
                            "file_id": file_id,
                            "symbol_node_type": "func_name",
                            "func_name": func_name,
                            "def_file_id": file_id,
                            "def_node_id": node["node_id"],
                            "start_line": node["start"],
                            "end_line": node["end"]
                        })

    # Step 3: 写入 graph_node 集合（允许重复名称，不 dedup）
    all_records = macro_records + global_defs + class_defs
    if all_records:
        graph_node_coll.insert_many(all_records)
        logging.info(f"Inserted {len(all_records)} symbol records into graph_node for proj_id={proj_id}")
    else:
        logging.info(f"No global symbols found for proj_id={proj_id}")

    # 可选：生成重复统计（用于日志或调试）
    def log_duplicates(records: List[Dict], name_key: str):
        name_to_locs = defaultdict(list)
        for r in records:
            name_key_val = r.get(name_key) or r.get("method_name") or r.get("class_name")
            if name_key_val:
                name_to_locs[name_key_val].append({
                    "file_id": r["file_id"],
                    "def_node_id": r["def_node_id"],
                    "start_line": r["start_line"],
                    "end_line": r["end_line"]
                })
        duplicates = {name: locs for name, locs in name_to_locs.items() if len(locs) > 1}
        if duplicates:
            logging.info(f"Found {len(duplicates)} duplicate {name_key}s in proj_id={proj_id}")
            # 可选择写入日志文件或 MongoDB 的另一个集合（如 graph_meta）

    log_duplicates(macro_records, "macro_name")
    log_duplicates(global_defs, "func_name")
    log_duplicates(class_defs, "class_name")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python extract_global_symbols.py <proj_id>")
        sys.exit(1)
    proj_id = int(sys.argv[1])
    extract_global_symbols(proj_id)
