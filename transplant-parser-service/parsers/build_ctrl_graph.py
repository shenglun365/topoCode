import os
import json
import argparse
from collections import defaultdict, deque
import logging

def build_scope_to_children(ast_nodes):
    scope_map = defaultdict(list)
    for node in ast_nodes:
        scope_map[node["scope_node_id"]].append(node)
    return scope_map

def find_function_body(func_node, scope_map):
    # 第一层子节点
    candidates = scope_map.get(func_node["node_id"], [])
    # 按行号排序确保顺序（可选）
    candidates.sort(key=lambda x: x.get("start", [0, 0]))
    for child in candidates:
        if child["type"] == "compound_statement":
            return child
    # 第二层（某些解析器将 compound_statement 嵌套在 declarator 内）
    for child in candidates:
        grandchildren = scope_map.get(child["node_id"], [])
        for gc in grandchildren:
            if gc["type"] == "compound_statement":
                return gc
    return None

def load_jsonl(file_path):
    """加载 .jsonl 文件为列表"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]

def extract_statements_in_scope(node, scope_map):
    statements = []
    stmt_types = {
        "expression_statement", "if_statement", "while_statement",
        "for_statement", "return_statement", "switch_statement",
        "goto_statement", "break_statement", "continue_statement"
    }
    if node["type"] in stmt_types:
        statements.append(node)
    
    # 递归子节点
    for child in scope_map.get(node["node_id"], []):
        statements.extend(extract_statements_in_scope(child, scope_map))
    
    return statements

def construct_basic_blocks(statements):
    """将语句划分为基本块（简化版）"""
    blocks = []
    current_block = []
    for stmt in statements:
        current_block.append(stmt)
        if is_terminator(stmt):  # 如 return, goto, break 等
            blocks.append(current_block)
            current_block = []
    if current_block:
        blocks.append(current_block)
    return blocks

def is_terminator(stmt):
    return stmt["type"] in {"return_statement", "goto_statement"}

def infer_control_flow(blocks):
    """推断基本块之间的控制流（简化：顺序 + 条件分支）"""
    edges = []
    for i, block in enumerate(blocks):
        last_stmt = block[-1]
        if last_stmt["type"] == "if_statement":
            # 假设有 then_block 和 else_block 的引用（需 AST 支持）
            # 此处简化为连接下两个块
            if i + 1 < len(blocks):
                edges.append((i, i + 1))  # then
            if i + 2 < len(blocks):
                edges.append((i, i + 2))  # else
        else:
            if i + 1 < len(blocks):
                edges.append((i, i + 1))  # 顺序执行
    return edges

def build_cfg_for_function(func_def, ast_nodes_by_id, scope_map):
    func_node = ast_nodes_by_id.get(func_def["def_node_id"])
    if not func_node:
        #logging.info(f"Function node not found: {func_def['def_node_id']}")
        return {"func_name": func_def["func_name"], "file_id": func_def["def_file_id"], "basic_blocks": [], "edges": []}

    body_node = find_function_body(func_node, scope_map)
    if not body_node:
        #logging.info(f"No function body (compound_statement) found for {func_def['func_name']}")
        return {"func_name": func_def["func_name"], "file_id": func_def["def_file_id"], "basic_blocks": [], "edges": []}

    body_statements = extract_statements_in_scope(body_node, scope_map)
    basic_blocks = construct_basic_blocks(body_statements)
    cfg_edges = infer_control_flow(basic_blocks)

    return {
        "func_name": func_def["func_name"],
        "file_id": func_def["def_file_id"],
        "basic_blocks": [
            [{"node_id": s["node_id"], "type": s["type"], "start": s["start"], "end": s["end"]} for s in block]
            for block in basic_blocks
        ],
        "edges": cfg_edges
    }

def main():
    parser = argparse.ArgumentParser(description="Extract Control Flow Graph (CFG) from parsed AST and function definitions.")
    parser.add_argument(
        "--user_root_path",
        type=str,
        required=True,
        help="Root path where parsed_base_node and graph_node directories are located."
    )
    parser.add_argument(
        "--project_hash",
        type=str,
        required=True,
        help="Project hash code (pHashCode) used in directory names."
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=None,
        help="Directory to save CFG output files. Default: {user_root_path}/graph_node/{project_hash}/"
    )

    args = parser.parse_args()

    # 构建路径
    p_hash = args.project_hash
    user_root = args.user_root_path.rstrip('/')
    ast_dir = f"{user_root}/parsed_base_node/{p_hash}"
    graph_dir = f"{user_root}/graph_node/{p_hash}"
    output_dir = args.output_dir or graph_dir

    os.makedirs(output_dir, exist_ok=True)

    # 加载函数定义
    func_defs_path = f"{graph_dir}/global_function_defs.jsonl"
    func_defs = load_jsonl(func_defs_path)

    # 为每个源文件加载 AST 节点（按需）
    # 注意：AST 文件名需与 global_function_defs 中的 def_file_id 对应
    # 假设存在 file_index.jsonl 映射 file_id -> filename
    file_index_path = f"{graph_dir}/file_index.jsonl"
    file_index = load_jsonl(file_index_path)
    file_id_to_name = {item["file_id"]: item["filename"] for item in file_index}

    # 预加载所有 AST 节点（或按需加载）
    ast_cache = {}
    scope_map_cache = {}
    for file_id, filename in file_id_to_name.items():
        ast_path = f"{ast_dir}/{filename}.jsonl"
        if os.path.exists(ast_path):
            nodes = load_jsonl(ast_path)
            ast_cache[file_id] = {node["node_id"]: node for node in nodes}
            scope_map_cache[file_id] = build_scope_to_children(nodes)  # <-- 关键：构建 scope 映射
        else:
            logging.info(f"Warning: AST file not found for file_id={file_id}: {ast_path}")
            ast_cache[file_id] = {}
            scope_map_cache[file_id] = defaultdict(list)

    # 生成 CFG 并输出
    cfg_output_path = f"{output_dir}/function_cfgs.jsonl"
    with open(cfg_output_path, 'w', encoding='utf-8') as out_f:
        for func in func_defs:
            file_id = func["def_file_id"]
            ast_map = ast_cache.get(file_id, {})
            scope_map = scope_map_cache.get(file_id, defaultdict(list))
            try:
                cfg = build_cfg_for_function(func, ast_map, scope_map)
                out_f.write(json.dumps(cfg, ensure_ascii=False) + '\n')
            except Exception as e:
                logging.info(f"Error processing function {func['func_name']} (file_id={file_id}): {e}")

    logging.info(f"CFG extraction completed. Output saved to: {cfg_output_path}")

if __name__ == "__main__":
    main()
    
# python build_ctrl_graph.py --user_root_path /home/cuser/topoCodeFileUpload/05/d0/ef/U-B --project_hash 3838d9a1-3b08-4ba5-a2f5-daa63779d0e6
