# parsers/parser.py
"""
多语言 AST 解析器

支持多种编程语言的 AST 解析，使用工厂模式动态选择解析器。
解析结果存储到 SQLite 项目库的 base_node 表。

架构:
- 使用 LanguageParserFactory 获取语言对应的 tree-sitter 解析器
- 使用 LanguageConfig 配置各语言的节点类型和处理规则
- 支持语言自动检测和回退策略
- 数据存储: SQLite (通过 db_adapter.SQLiteAdapter)
"""
from pathlib import Path
from tree_sitter import Node, Tree, Parser
import logging
import json
import hashlib
import os
from typing import Dict, List, Optional, Any, Tuple

# 导入工厂模式
from parsers.code_parser.parser_factory import (
    LanguageParserFactory,
    get_parser,
    get_supported_languages,
    UnsupportedLanguageError
)
from parsers.code_parser.registry import get_language_config
from parsers.code_parser.lang_parser_conf import detect_language
from parsers.db_adapter import SQLiteAdapter
from config import MAX_AST_NODES

logger = logging.getLogger(__name__)

# 文件大小限制 (500KB)
MAX_FILE_SIZE = 500 * 1024


def _count_ast_nodes(node: Node) -> int:
    """递归计算 AST 节点总数"""
    count = 1
    for child in node.children:
        count += _count_ast_nodes(child)
    return count


def parse_file(
    source_file_path: str,
    project_db,
    task_id: str,
    proj_path: str,
) -> int:
    """
    将源代码解析为 AST，并将结果存入 SQLite 项目库

    Args:
        source_file_path: 源代码文件路径（绝对路径）
        project_db: SQLiteContext (项目库连接)
        task_id: 分析任务 ID
        proj_path: 项目根路径（绝对路径）

    Returns:
        解析的节点数量，失败返回 0，跳过返回 -1
    """
    try:
        adapter = SQLiteAdapter(project_db, task_id)

        # === Step 1: 语言检测 ===
        language_name = detect_language(source_file_path)
        if language_name is None:
            logger.warning(f"Unsupported language for file: {source_file_path}")
            return 0

        # === Step 2: 获取解析器 ===
        try:
            parser = LanguageParserFactory.get_parser(language_name)
        except (UnsupportedLanguageError, Exception) as e:
            logger.warning(f"Parser not available for language '{language_name}': {e}")
            return 0

        if parser is None:
            logger.warning(f"Parser not available for language: {language_name}")
            return 0

        # === Step 3: 读取文件并检查大小 ===
        source_path = Path(source_file_path)
        if not source_path.exists():
            logger.error(f"Source file not found: {source_file_path}")
            return 0

        file_size = source_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            logger.warning(
                f"Skipping large file: {source_file_path} "
                f"({file_size / (1024*1024):.2f}MB > {MAX_FILE_SIZE/1024:.0f}KB)"
            )
            return -1

        rel_path = os.path.relpath(source_file_path, proj_path)

        # === Step 4: 获取或创建 file_id ===
        file_id = _get_or_create_file_id_sqlite(
            adapter=adapter,
            file_path=rel_path,
            file_name=source_path.name,
            language=language_name,
        )

        if file_id is None:
            logger.info(f"File unchanged, skipping AST parsing: {rel_path}")
            return 0

        # === Step 5: 解析 AST ===
        src_content = source_path.read_bytes()
        tree = parser.parse(src_content)

        # 检查 AST 节点总数是否超过限制
        node_count = _count_ast_nodes(tree.root_node)
        if node_count > MAX_AST_NODES:
            logger.warning(
                f"Skipping file with too many AST nodes: {source_file_path} "
                f"({node_count} > {MAX_AST_NODES})"
            )
            return -1

        nodes_final = extract_node_info(root_node=tree.root_node, language_name=language_name)

        if not nodes_final:
            logger.info(f"No important nodes extracted from {source_file_path}")
            return 0

        total_nodes = len(nodes_final)
        logger.info(f"Parsed {total_nodes} nodes from {rel_path}")

        # === Step 6: 批量插入 SQLite ===
        inserted_total = _batch_insert_ast_nodes_sqlite(
            adapter=adapter,
            file_id=file_id,
            nodes=nodes_final,
        )

        logger.info(
            f"Successfully inserted {inserted_total} AST nodes "
            f"for file_id={file_id}"
        )
        return inserted_total

    except Exception as e:
        logger.exception(
            f"Fatal error in parse_file for {source_file_path}: {e}"
        )
        raise


def _get_or_create_file_id_sqlite(
    adapter: SQLiteAdapter,
    file_path: str,
    file_name: str,
    language: str,
) -> Optional[str]:
    """
    获取或创建文件 ID（SQLite 版本）

    文件 ID 使用 source_files.id（TEXT 类型），如果文件已存在于项目库中则复用。

    Returns:
        file_id (str)，如果文件不存在于 source_files 则返回 None
    """
    existing = adapter.get_file_by_path(file_path)
    if existing:
        return existing.get('id')

    # 文件不在 source_files 中 — 跳过（由导入流程填充 source_files）
    return None


def _batch_insert_ast_nodes_sqlite(
    adapter: SQLiteAdapter,
    file_id: str,
    nodes: List[Dict],
    batch_size: int = 5000,
) -> int:
    """
    批量插入 AST 节点到 SQLite

    Args:
        adapter: SQLiteAdapter 实例
        file_id: 文件 ID（TEXT）
        nodes: AST 节点列表
        batch_size: 批次大小

    Returns:
        插入的节点总数
    """
    total_nodes = len(nodes)
    inserted_total = 0

    for i in range(0, total_nodes, batch_size):
        batch = nodes[i:i + batch_size]

        documents = []
        for obj in batch:
            doc = {
                "file_id": file_id,
                "node_id": str(obj.get("node_id", i + batch.index(obj) + 1)),
                "type": obj["type"],
                "start": str(obj["start"]) if hasattr(obj["start"], "__iter__") else obj["start"],
                "end": str(obj["end"]) if hasattr(obj["end"], "__iter__") else obj["end"],
                "name": obj.get("name"),
                "op": obj.get("op"),
                "refs": obj.get("refs", []) if obj["type"] != "translation_unit" else [],
                "scope_node_id": str(obj.get("scope_node_id", "")) if obj.get("scope_node_id") is not None else "",
                "def_node_id": str(obj.get("def_node_id", "")) if obj.get("def_node_id") else "",
                "content_size": obj.get("content_size", 0),
            }
            documents.append(doc)

        adapter.insert_nodes(documents)
        inserted_total += len(documents)
        logger.info(
            f"Batch inserted {len(documents)} AST nodes, "
            f"batch {(i // batch_size) + 1}/{(total_nodes + batch_size - 1) // batch_size}"
        )

    return inserted_total


def extract_node_info(root_node: Node, language_name: str) -> List[Dict[str, Any]]:
    """
    从 tree-sitter AST 根节点提取重要节点信息
    
    算法:
    1. DFS 遍历 AST，收集重要节点
    2. 构建作用域链（scope_node_id）
    3. 构建符号表（name -> definitions）
    4. 解析引用关系（refs）
    5. 解析定义关系（def_node_id）
    
    Args:
        root_node: tree-sitter AST 根节点
        language_name: 语言名称
        
    Returns:
        提取的节点列表
    """
    config = get_language_config(language_name)

    # === Step 1: DFS 收集重要节点 ===
    nodes = _collect_important_nodes(root_node, config)
    
    if not nodes:
        return []

    # === Step 2: 构建作用域信息 ===
    _build_scope_info(nodes, config)

    # === Step 3: 构建符号表并解析定义 ===
    _build_symbol_table_and_resolve_definitions(nodes, config)

    # === Step 4: 解析引用关系 ===
    _resolve_references(nodes)

    # === Step 5: 清理中间字段 ===
    _cleanup_intermediate_fields(nodes)

    return nodes


def _clean_name_string(text: str) -> str:
    """
    清理名称字符串，去除引号、尖括号等符号
    
    Args:
        text: 原始文本
        
    Returns:
        清理后的文本
    """
    # 去除首尾的引号或尖括号
    if (text.startswith('"') and text.endswith('"')) or \
       (text.startswith("'") and text.endswith("'")) or \
       (text.startswith('<') and text.endswith('>')):
        return text[1:-1]
    return text


def _extract_name_from_node(cur: Node, config) -> Optional[str]:
    """
    从 AST 节点提取名称（函数名、类名等）
    
    通过查找子节点中的标识符来提取名称。
    
    Args:
        cur: tree-sitter 节点
        config: 语言配置
        
    Returns:
        提取的名称，如果无法提取则返回 None
    """
    rules = config.name_extract_rules.get(cur.type, [])
    
    if not rules:
        return None
    
    # 按优先级顺序查找子节点
    for child_type in rules:
        for child in cur.children:
            if child.type == child_type:
                return child.text.decode('utf-8')
    
    # 如果直接子节点没有找到，递归查找（但不超过一层）
    for child in cur.children:
        if child.type in config.important_node_types:
            name = _extract_name_from_node(child, config)
            if name:
                return name
    
    return None


def _collect_important_nodes(root_node: Node, config) -> List[Dict]:
    """
    DFS 收集重要节点，并记录父节点信息

    Args:
        root_node: AST 根节点
        config: 语言配置

    Returns:
        节点列表
    """
    nodes = []
    stack = [(root_node, None)]  # (node, parent_id)
    node_id_counter = 1

    while stack:
        cur, parent_id = stack.pop()

        if cur.type in config.important_node_types:
            is_name = cur.type in config.is_name_node_types
            
            # 对于名称节点，提取 text 并清理引号/尖括号
            if is_name:
                raw_name = cur.text.decode('utf-8')
                name = _clean_name_string(raw_name)
            else:
                # 尝试从子节点提取名称（用于 function_declaration, class_declaration 等）
                name = _extract_name_from_node(cur, config)
            
            op = config.node_type_to_op.get(cur.type, cur.type)

            node_entry = {
                "node_id": node_id_counter,
                "type": cur.type,
                "start": cur.start_point,
                "end": cur.end_point,
                "isNameNode": 1 if is_name else 0,
                "name": name,
                "op": op,
                "parent_id": parent_id,
                "children_ids": [],
                "name_node_id": [],
                "def_node_id": [],
                "refs": [],
                "scope_node_id": None,
                "content_size": len(cur.text),
            }
            nodes.append(node_entry)
            current_id = node_id_counter
            node_id_counter += 1

            # 更新父节点的 children_ids
            if parent_id is not None:
                for n in nodes:
                    if n["node_id"] == parent_id:
                        n["children_ids"].append(current_id)
                        break

            # 继续遍历子节点
            for child in reversed(cur.children):
                stack.append((child, current_id))
        else:
            # 非重要节点仍需遍历其子树
            for child in reversed(cur.children):
                stack.append((child, parent_id))

    return nodes


def _build_scope_info(nodes: List[Dict], config):
    """
    为每个节点分配 scope_node_id
    
    通过向上查找最近的 scope creating 节点来确定作用域
    
    Args:
        nodes: 节点列表
        config: 语言配置
    """
    node_map = {n["node_id"]: n for n in nodes}
    GLOBAL_SCOPE_ID = 0

    # 标记 scope 节点
    for node in nodes:
        node["is_scope"] = node["type"] in config.scope_creating_types

    # 为每个节点分配 scope_node_id
    for node in nodes:
        scope_id = GLOBAL_SCOPE_ID
        cur_id = node["parent_id"]
        
        while cur_id is not None:
            parent = node_map.get(cur_id)
            if parent and parent.get("is_scope"):
                scope_id = cur_id
                break
            cur_id = parent.get("parent_id") if parent else None
        
        node["scope_node_id"] = scope_id


def _build_symbol_table_and_resolve_definitions(nodes: List[Dict], config):
    """
    构建符号表并解析 name 节点的定义
    
    Args:
        nodes: 节点列表
        config: 语言配置
    """
    node_map = {n["node_id"]: n for n in nodes}
    symbol_table: Dict[str, List[Dict]] = {}

    # 遍历所有 name 节点，确定其是否为定义
    name_nodes = [n for n in nodes if n["isNameNode"] == 1]
    
    for name_node in name_nodes:
        # 向上找最近的 defining context
        cur_id = name_node["parent_id"]
        defining_node = None
        
        while cur_id is not None:
            parent = node_map.get(cur_id)
            if parent and parent["type"] in config.defining_context_types:
                defining_node = parent
                break
            cur_id = parent.get("parent_id") if parent else None

        if defining_node:
            name = name_node["name"]
            scope_id = name_node["scope_node_id"]
            
            if name not in symbol_table:
                symbol_table[name] = []
            
            symbol_table[name].append({
                "def_node_id": defining_node["node_id"],
                "scope_id": scope_id,
                "name_node_id": name_node["node_id"]
            })
            name_node["def_node_id"] = [defining_node["node_id"]]
        else:
            name_node["def_node_id"] = []

    # 对于未定义的 name 节点，尝试通过作用域链解析
    for name_node in name_nodes:
        if not name_node["def_node_id"]:
            name = name_node["name"]
            current_scope = name_node["scope_node_id"]
            
            if name in symbol_table:
                candidates = symbol_table[name]
                # 优先当前作用域
                match = next((c for c in candidates if c["scope_id"] == current_scope), None)
                if not match:
                    match = candidates[0]  # fallback to first
                if match:
                    name_node["def_node_id"] = [match["def_node_id"]]


def _resolve_references(nodes: List[Dict]):
    """
    为非-name 节点收集 refs（后代 name 节点的 name）

    Args:
        nodes: 节点列表
    """
    node_map = {n["node_id"]: n for n in nodes}

    for node in nodes:
        if node["isNameNode"] == 0:
            refs = set()

            # DFS 所有后代 name 节点
            stack = list(node["children_ids"])
            while stack:
                cid = stack.pop()
                child = node_map.get(cid)
                if child:
                    if child["isNameNode"] == 1:
                        refs.add(child["node_id"])
                    else:
                        stack.extend(child["children_ids"])

            refs_ids = sorted(refs)
            names = []
            for ref_id in refs_ids:
                ref_node = node_map.get(ref_id)
                if ref_node is not None:
                    names.append(ref_node.get("name"))
            node["refs"] = names


def _cleanup_intermediate_fields(nodes: List[Dict]):
    """
    清理中间字段
    
    Args:
        nodes: 节点列表
    """
    for node in nodes:
        node.pop("is_scope", None)
        node.pop("parent_id", None)
        node.pop("children_ids", None)


# 便捷函数
def get_ast_parser(language_name: str) -> Optional[Parser]:
    """
    便捷函数：获取 AST 解析器
    
    Args:
        language_name: 语言名称
        
    Returns:
        tree-sitter Parser 实例
    """
    return LanguageParserFactory.get_parser(language_name)


def get_supported_ast_languages() -> List[str]:
    """
    便捷函数：获取支持的 AST 解析语言列表
    
    Returns:
        支持的语言列表
    """
    return get_supported_languages()
