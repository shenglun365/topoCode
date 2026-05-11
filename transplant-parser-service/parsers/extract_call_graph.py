# parsers/extract_call_graph.py
"""
多语言调用图提取器

从 MongoDB 中的 AST 节点提取函数调用关系，并写入 graph_node 集合。
使用策略模式，根据项目的主要编程语言自动选择对应的提取器。

支持的语言:
- C/C++: 函数调用、宏调用
- Python: 函数调用、方法调用
- Java: 方法调用、构造函数调用
- JavaScript/TypeScript: 函数调用、方法调用
- Go: 函数调用、方法调用
- 更多语言正在添加中...

架构:
- 使用 CallGraphExtractorRegistry 注册和获取语言特定的提取器
- 每个语言提取器实现 CallGraphExtractor 抽象基类
- 支持多语言混合项目（按文件语言分别处理）
"""
import json
import logging
from typing import Dict, Any, List, Optional, Set
from collections import defaultdict

from databases.db_pools import get_mongo_client

# 导入调用图提取器工厂
from parsers.languages.call_parser.extractor_factory import (
    CallGraphExtractorRegistry,
    get_call_graph_extractor,
    get_supported_call_graph_languages
)

# 导入跨语言调用规则
from config.cross_lang_call_rules import get_preferred_languages

logger = logging.getLogger(__name__)


def extract_call_graph(proj_id: int, language: str = None) -> List[Dict[str, Any]]:
    """
    从 MongoDB 提取调用图，写入 graph_node 集合

    Args:
        proj_id: 项目 ID
        language: 指定语言（可选），如果为 None 则自动检测项目主要语言

    Returns:
        调用边列表

    Raises:
        ValueError: 当语言不支持时
        Exception: 提取失败时抛出异常
    """
    mongo_client = get_mongo_client()
    db = mongo_client.topocode

    proj_info_coll = db.proj_info
    base_node_coll = db.base_node
    graph_node_coll = db.graph_node

    # === Step 1: 获取项目文件信息 ===
    # 如果指定了 language，使用 file_lang 字段过滤
    query = {
        "proj_id": proj_id,
        "file_id": {"$lt": 1000000}  # 排除系统文件
    }
    if language:
        query["file_lang"] = language

    file_records = list(proj_info_coll.find(query, {"file_id": 1, "file_name": 1, "_id": 0}))

    if not file_records:
        logger.warning(f"No files found for proj_id={proj_id}" + (f" with language={language}" if language else ""))
        return []

    file_id_to_name: Dict[int, str] = {
        rec["file_id"]: rec["file_name"] for rec in file_records
    }
    file_ids = list(file_id_to_name.keys())

    logger.info(f"Found {len(file_records)} files for proj_id={proj_id}" + (f" (language={language})" if language else ""))

    # === Step 2: 确定项目语言并获取提取器 ===
    project_language = language or _detect_project_language(proj_id, file_records)

    extractor = get_call_graph_extractor(project_language)
    if extractor is None:
        supported_langs = get_supported_call_graph_languages()
        raise ValueError(
            f"Call graph extractor not found for language '{project_language}'. "
            f"Supported languages: {supported_langs}"
        )

    logger.info(f"Using CallGraphExtractor for language: {project_language}")

    # === Step 3: 加载 AST 节点（按 file_id 分组） ===
    logger.info("Loading AST nodes from base_node...")
    all_nodes_by_file_id: Dict[int, Dict[int, Dict]] = defaultdict(dict)

    base_nodes_cursor = base_node_coll.find(
        {"proj_id": proj_id, "file_id": {"$in": file_ids}},
        {"_id": 0}
    )

    for node in base_nodes_cursor:
        file_id = node["file_id"]
        node_id = node["node_id"]
        all_nodes_by_file_id[file_id][node_id] = node

    logger.info(f"Loaded {sum(len(nodes) for nodes in all_nodes_by_file_id.values())} AST nodes")

    # === Step 4: 构建全局符号映射 ===
    # 构建全局函数定义映射：func_name -> {file_id, node_id}
    logger.info("Building global function definition map...")
    global_func_def_map = _build_function_map(proj_id, graph_node_coll)
    logger.info(f"Found {len(global_func_def_map)} global functions")

    # 构建全局宏定义映射
    logger.info("Building global macro map...")
    global_macro_map = _build_macro_map(proj_id, graph_node_coll)
    logger.info(f"Found {len(global_macro_map)} global macros")

    # === Step 5: 提取调用边 ===
    logger.info("Extracting call edges...")
    
    # 详细日志：检查 AST 节点中的 call_expression 数量
    call_expr_count = 0
    jsx_expr_count = 0
    for file_id, nodes in all_nodes_by_file_id.items():
        for node in nodes.values():
            node_type = node.get("type", "")
            if node_type == "call_expression":
                call_expr_count += 1
            elif node_type in ["jsx_element", "jsx_self_closing_element"]:
                jsx_expr_count += 1
    
    logger.info(f"🔍 AST 节点统计：call_expression={call_expr_count}, JSX 组件={jsx_expr_count}")
    logger.info(f"   调用图提取器类型：{type(extractor).__name__}")
    logger.info(f"   调用图提取器配置：CALL_EXPRESSION_TYPES={getattr(extractor, 'CALL_EXPRESSION_TYPES', 'N/A')}")
    logger.info(f"   调用图提取器配置：JSX_COMPONENT_TYPES={getattr(extractor, 'JSX_COMPONENT_TYPES', 'N/A')}")

    # 对于 Java/JavaScript/TypeScript 语言，使用专门的提取器
    if project_language in ['java', 'javascript', 'typescript']:
        logger.info(f"🔧 开始使用 {project_language} 专用提取器...")
        logger.info(f"   传入的 nodes_by_file 文件数：{len(all_nodes_by_file_id)}")
        logger.info(f"   传入的 nodes_by_file 总节点数：{sum(len(nodes) for nodes in all_nodes_by_file_id.values())}")
        
        call_edges = extractor.extract(proj_id, all_nodes_by_file_id)
        logger.info(f"✅ {project_language} 提取器返回 {len(call_edges)} 条调用边")
        
        # 详细日志：检查返回的边结构
        if call_edges:
            logger.info(f"   前 3 条边样例:")
            for i, edge in enumerate(call_edges[:3], 1):
                logger.info(f"     [{i}] caller={edge.get('caller_func_name')} -> callee={edge.get('callee_name')}")
        else:
            logger.warning(f"⚠️  {project_language} 提取器返回 0 条边，可能原因:")
            logger.warning(f"   1. AST 节点中没有 call_expression 类型")
            logger.warning(f"   2. 提取器未正确识别 call_expression 节点")
            logger.warning(f"   3. find_enclosing_function 未找到 enclosing function")
            logger.warning(f"   4. extract_callee_name 未能提取 callee 名称")
    else:
        # 其他语言使用通用逻辑
        call_edges = _extract_call_edges(
            proj_id=proj_id,
            all_nodes_by_file_id=all_nodes_by_file_id,
            func_def_map=global_func_def_map,
            macro_map=global_macro_map,
            extractor=extractor
        )

    # === Step 6: 写入 MongoDB ===
    if call_edges:
        logger.info(f"Inserting {len(call_edges)} call relations into graph_node...")
        _save_call_edges(graph_node_coll, proj_id, call_edges, language)
        logger.info("Call graph extraction completed.")
    else:
        logger.info("No call edges found.")

    return call_edges


def _detect_project_language(proj_id: int, file_records: List[Dict]) -> str:
    """
    检测项目的主要编程语言
    
    策略:
    1. 统计各语言的文件数量
    2. 返回文件数最多的语言
    
    Args:
        proj_id: 项目 ID
        file_records: 文件记录列表
        
    Returns:
        主要语言名称，默认返回 'c'
    """
    from parsers.languages.code_parser.lang_parser_conf import detect_language
    
    lang_counts: Dict[str, int] = defaultdict(int)
    
    for rec in file_records:
        file_name = rec.get("file_name", "")
        lang = detect_language(file_name)
        if lang:
            lang_counts[lang] += 1
    
    if not lang_counts:
        logger.warning("Could not detect project language, defaulting to 'c'")
        return 'c'
    
    # 返回文件数最多的语言
    primary_lang = max(lang_counts.items(), key=lambda x: x[1])[0]
    logger.info(f"Detected primary language: {primary_lang} (files: {lang_counts[primary_lang]})")
    
    return primary_lang


def _build_function_map(proj_id: int, graph_node_coll, language: str = None) -> Dict[str, Dict[str, Dict[str, int]]]:
    """
    构建全局函数定义映射（支持多语言）

    返回结构：
    {
        "init": {
            "typescript": {"file_id": 100, "node_id": 200},
            "javascript": {"file_id": 500, "node_id": 600}
        },
        "helper": {
            "typescript": {"file_id": 101, "node_id": 201}
        }
    }

    Args:
        proj_id: 项目 ID
        graph_node_coll: MongoDB graph_node 集合
        language: 如果指定，只加载该语言的符号（用于按语言隔离处理）

    Returns:
        嵌套字典：{func_name: {language: {file_id, node_id}}}
    """
    func_map: Dict[str, Dict[str, Dict[str, int]]] = {}

    # 构建查询
    query = {
        "proj_id": proj_id,
        "symbol_node_type": "func_name"
    }
    if language:
        query["language"] = language

    # 查询 C/C++/Go 等语言的函数定义
    func_nodes = graph_node_coll.find(
        query,
        {"func_name": 1, "language": 1, "def_file_id": 1, "def_node_id": 1, "_id": 0}
    )

    for rec in func_nodes:
        name = rec["func_name"]
        lang = rec.get("language", "unknown")
        
        if name not in func_map:
            func_map[name] = {}
        
        # 同一函数名可能有多个语言定义
        func_map[name][lang] = {
            "file_id": rec["def_file_id"],
            "node_id": rec["def_node_id"]
        }

    # 查询 Java 等语言的方法定义
    method_query = {
        "proj_id": proj_id,
        "symbol_node_type": "method_name"
    }
    if language:
        method_query["language"] = language
    
    method_nodes = graph_node_coll.find(
        method_query,
        {"method_name": 1, "language": 1, "def_file_id": 1, "def_node_id": 1, "_id": 0}
    )

    for rec in method_nodes:
        name = rec["method_name"]
        lang = rec.get("language", "unknown")
        
        if name not in func_map:
            func_map[name] = {}
        
        func_map[name][lang] = {
            "file_id": rec["def_file_id"],
            "node_id": rec["def_node_id"]
        }

    lang_filter = f" (language={language})" if language else ""
    logger.info(f"Built function map for proj_id={proj_id}{lang_filter}: "
                f"{len(func_map)} unique function names")

    return func_map


def _resolve_callee(
    callee_name: str,
    caller_lang: str,
    func_map: Dict[str, Dict[str, Dict[str, int]]]
) -> Optional[Dict[str, int]]:
    """
    解析被调用函数（支持多语言重名处理）
    
    策略：
    1. 如果函数名唯一（只有一个语言定义），直接返回
    2. 如果有重名，优先匹配同语言
    3. 如果同语言没有，按配置允许的语言顺序查找
    
    Args:
        callee_name: 被调用函数名
        caller_lang: 调用方语言
        func_map: 函数映射表（来自 _build_function_map）
    
    Returns:
        函数定义信息 {file_id, node_id}，未找到返回 None
    """
    if callee_name not in func_map:
        return None
    
    lang_to_info = func_map[callee_name]
    
    # === 情况 1: 只有一个语言定义，直接返回 ===
    if len(lang_to_info) == 1:
        return next(iter(lang_to_info.values()))
    
    # === 情况 2: 多个语言定义，按优先级匹配 ===
    # 获取允许的语言列表（同语言优先）
    preferred_langs = get_preferred_languages(caller_lang)
    
    for lang in preferred_langs:
        if lang in lang_to_info:
            return lang_to_info[lang]
    
    # 如果配置允许的语言中都没有，返回第一个（降级处理）
    logger.debug(f"Function '{callee_name}' has {len(lang_to_info)} definitions "
                 f"in languages {list(lang_to_info.keys())}, "
                 f"caller_lang={caller_lang}, using first match")
    return next(iter(lang_to_info.values()))


def _load_file_language(proj_id: int, file_ids: List[int]) -> Dict[int, str]:
    """
    加载文件语言映射
    
    Args:
        proj_id: 项目 ID
        file_ids: 文件 ID 列表
    
    Returns:
        {file_id: language}
    """
    mongo_client = get_mongo_client()
    db = mongo_client.topocode
    proj_info_coll = db.proj_info
    
    file_lang_map = {}
    cursor = proj_info_coll.find(
        {"proj_id": proj_id, "file_id": {"$in": file_ids}},
        {"file_id": 1, "file_lang": 1, "_id": 0}
    )
    
    for rec in cursor:
        file_lang_map[rec["file_id"]] = rec.get("file_lang", "unknown")
    
    return file_lang_map


def _build_macro_map(proj_id: int, graph_node_coll) -> Dict[str, Dict[str, int]]:
    """
    构建全局宏定义映射
    
    Args:
        proj_id: 项目 ID
        graph_node_coll: MongoDB graph_node 集合
        
    Returns:
        {macro_name: {file_id: int, node_id: int}}
    """
    macro_map = {}
    macro_nodes = graph_node_coll.find(
        {"proj_id": proj_id, "symbol_node_type": "macro_name"},
        {"macro_name": 1, "def_file_id": 1, "def_node_id": 1, "_id": 0}
    )
    
    for rec in macro_nodes:
        name = rec["macro_name"]
        if name not in macro_map:  # 保留首次出现
            macro_map[name] = {
                "file_id": rec["def_file_id"],
                "node_id": rec["def_node_id"]
            }
    
    return macro_map


def _extract_call_edges(
    proj_id: int,
    all_nodes_by_file_id: Dict[int, Dict[int, Dict]],
    func_def_map: Dict[str, Dict[str, int]],
    macro_map: Dict[str, Dict[str, int]],
    extractor: 'CallGraphExtractor'
) -> List[Dict[str, Any]]:
    """
    提取调用边
    
    Args:
        proj_id: 项目 ID
        all_nodes_by_file_id: 按文件分组的 AST 节点
        func_def_map: 全局函数定义映射
        macro_map: 全局宏定义映射
        extractor: 调用图提取器实例
        
    Returns:
        调用边列表
    """
    call_edges = []

    # 加载文件语言映射
    file_id_to_lang = _load_file_language(proj_id, list(all_nodes_by_file_id.keys()))

    # 统计信息
    stats = {
        'total_call_expr': 0,
        'no_callee_count': 0,
        'no_caller_func_count': 0,
        'no_caller_name_count': 0
    }

    for file_id, nodes in all_nodes_by_file_id.items():
        caller_lang = file_id_to_lang.get(file_id, "unknown")
        file_edges = _extract_file_call_edges(
            proj_id=proj_id,
            file_id=file_id,
            nodes=nodes,
            func_def_map=func_def_map,
            macro_map=macro_map,
            extractor=extractor,
            stats=stats,
            caller_lang=caller_lang
        )
        call_edges.extend(file_edges)
    
    # 打印统计信息
    logger.info(f"Call extraction statistics:")
    logger.info(f"  Total call_expression nodes: {stats['total_call_expr']}")
    logger.info(f"  Skipped (missing callee_name): {stats['no_callee_count']}")
    logger.info(f"  Skipped (no enclosing function): {stats['no_caller_func_count']}")
    logger.info(f"  Skipped (failed caller name): {stats['no_caller_name_count']}")
    
    return call_edges


def _extract_file_call_edges(
    proj_id: int,
    file_id: int,
    nodes: Dict[int, Dict],
    func_def_map: Dict[str, Dict[str, Dict[str, int]]],
    macro_map: Dict[str, Dict[str, int]],
    extractor: 'CallGraphExtractor',
    stats: Dict[str, int],
    caller_lang: str = "unknown"
) -> List[Dict[str, Any]]:
    """
    提取单个文件的调用边

    Args:
        proj_id: 项目 ID
        file_id: 文件 ID
        nodes: 文件内的 AST 节点映射
        func_def_map: 全局函数定义映射（支持多语言）
        macro_map: 全局宏定义映射
        extractor: 调用图提取器
        stats: 统计信息字典
        caller_lang: 调用方语言

    Returns:
        调用边列表
    """
    call_edges = []

    for node in nodes.values():
        if not extractor.is_call_expression(node):
            continue

        stats['total_call_expr'] += 1

        # 提取被调用函数名
        callee_name = extractor.extract_callee_name(node, nodes)
        if not callee_name:
            stats['no_callee_count'] += 1
            if stats['no_callee_count'] <= 5:
                logger.debug(f"callee_name is None/empty. Node: {node}")
            continue

        # 查找包含该节点的函数
        caller_func_node = extractor.find_enclosing_function(node, nodes)
        if not caller_func_node:
            stats['no_caller_func_count'] += 1
            if stats['no_caller_func_count'] <= 5:
                logger.debug(f"No enclosing function for call node {node['node_id']} in file {file_id}")
            continue

        # 提取调用函数名
        caller_name = extractor.extract_function_name(caller_func_node, nodes)
        if not caller_name:
            stats['no_caller_name_count'] += 1
            if stats['no_caller_name_count'] <= 5:
                logger.debug(f"Failed to extract caller name from func node {caller_func_node['node_id']}")
            continue

        # === 核心修改：使用 _resolve_callee 解析（支持多语言重名处理）===
        callee_info = _resolve_callee(callee_name, caller_lang, func_def_map)

        # 构建调用边
        edge = {
            "proj_id": proj_id,
            "symbol_node_type": "call_relation",
            "caller_file_id": file_id,
            "caller_func_name": caller_name,
            "caller_node_id": caller_func_node["node_id"],
            "callee_name": callee_name,
            "call_site_node_id": node["node_id"],
            "call_site_file_id": file_id,
        }

        if callee_info:
            edge.update({
                "callee_file_id": callee_info["file_id"],
                "callee_node_id": callee_info["node_id"],
                "callee_type": "function"
            })
        elif callee_name in macro_map:
            macro_info = macro_map[callee_name]
            edge.update({
                "callee_file_id": macro_info["file_id"],
                "callee_node_id": macro_info["node_id"],
                "callee_type": "macro"
            })
        else:
            edge.update({
                "callee_file_id": None,
                "callee_node_id": None,
                "callee_type": "external_or_unknown"
            })

        call_edges.append(edge)

    return call_edges


def _save_symbols(
    graph_node_coll,
    proj_id: int,
    symbols: List[Dict],
    language: str,
    batch_size: int = 5000
):
    """
    保存符号到 MongoDB

    使用 bulk_write + upsert，支持多语言同名符号

    Args:
        graph_node_coll: MongoDB 集合
        proj_id: 项目 ID
        symbols: 符号列表
        language: 语言名称
        batch_size: 批次大小
    """
    from pymongo import UpdateOne

    logger.info(f"Saving {len(symbols)} symbols for language={language}")

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]

        operations = []
        for symbol in batch:
            # 唯一键：{proj_id, symbol_node_type, func_name/class_name, language}
            filter_query = {
                "proj_id": proj_id,
                "symbol_node_type": symbol["symbol_node_type"],
                "language": symbol["language"]
            }
            
            # 根据符号类型添加不同的名称字段
            if "func_name" in symbol:
                filter_query["func_name"] = symbol["func_name"]
            elif "class_name" in symbol:
                filter_query["class_name"] = symbol["class_name"]
            elif "method_name" in symbol:
                filter_query["method_name"] = symbol["method_name"]
            elif "macro_name" in symbol:
                filter_query["macro_name"] = symbol["macro_name"]
            
            operations.append(
                UpdateOne(
                    filter_query,
                    {"$set": symbol},
                    upsert=True
                )
            )

        if operations:
            result = graph_node_coll.bulk_write(operations, ordered=False)
            logger.debug(f"✅ Saved {len(batch)} symbols (batch {i//batch_size + 1})")
    
    logger.info(f"✅ Completed saving {len(symbols)} symbols for language={language}")


def _save_call_edges(graph_node_coll, proj_id: int, edges: List[Dict], language: str = None, batch_size: int = 1000):
    """
    保存调用边到 MongoDB

    使用 bulk_write + upsert 避免多语言数据覆盖

    Args:
        graph_node_coll: MongoDB 集合
        proj_id: 项目 ID
        edges: 调用边列表
        language: 当前处理的语言（可选）
        batch_size: 批次大小
    """
    # 只在处理第一种语言时删除旧数据（避免重复删除）
    if language is None:
        # 没有指定语言，删除所有旧数据
        logger.info(f"Cleaning old call graph data for proj_id={proj_id}")
        graph_node_coll.delete_many({
            "proj_id": proj_id,
            "symbol_node_type": "call_relation"
        })
    else:
        # 指定了语言，检查是否已有数据
        existing_count = graph_node_coll.count_documents({
            "proj_id": proj_id,
            "symbol_node_type": "call_relation"
        })
        if existing_count == 0:
            # 第一次运行，删除旧数据
            logger.info(f"Cleaning old call graph data for proj_id={proj_id}")
            graph_node_coll.delete_many({
                "proj_id": proj_id,
                "symbol_node_type": "call_relation"
            })

    # 批量插入（使用 upsert 避免重复）
    total = len(edges)
    from pymongo import UpdateOne

    for i in range(0, total, batch_size):
        batch = edges[i:i + batch_size]

        # 使用 bulk_write 进行 upsert 操作
        operations = []
        for edge in batch:
            # 构建唯一键
            filter_query = {
                "proj_id": proj_id,
                "symbol_node_type": "call_relation",
                "caller_file_id": edge["caller_file_id"],
                "caller_func_name": edge["caller_func_name"],
                "callee_name": edge["callee_name"],
                "call_site_node_id": edge["call_site_node_id"]
            }
            operations.append(
                UpdateOne(
                    filter_query,
                    {"$set": edge},
                    upsert=True
                )
            )

        if operations:
            # 使用 ordered=False 提高性能
            graph_node_coll.bulk_write(operations, ordered=False)
            logger.info(f"✅ Upserted call edge batch {i//batch_size + 1}/{(total + batch_size - 1)//batch_size}, {len(operations)} edges")


# ---------------- CLI 入口 ----------------
def main():
    """命令行入口"""
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python extract_call_graph.py <proj_id>")
        sys.exit(1)

    proj_id = int(sys.argv[1])
    
    try:
        edges = extract_call_graph(proj_id)
        logging.info(f"\nTotal call edges extracted: {len(edges)}")
        if edges:
            logging.info("\nSample edge:")
            logging.info(json.dumps(edges[0], indent=2, ensure_ascii=False))
    except Exception as e:
        logging.exception("Error during call graph extraction")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
