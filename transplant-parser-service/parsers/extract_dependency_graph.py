# parsers/extract_dependency_graph.py
"""
多语言依赖图提取器

从 MongoDB 中的 AST 节点提取文件级依赖关系（如 #include, import, require 等），
并写入 graph_node 集合。

使用策略模式，根据项目的主要编程语言自动选择对应的依赖提取器。

支持的语言:
- C/C++: #include 依赖
- Python: import/from...import 依赖
- Java: import 依赖
- JavaScript/TypeScript: import/require 依赖
- Go: import 依赖
- 更多语言正在添加中...

架构:
- 使用 DependencyExtractorRegistry 注册和获取语言特定的提取器
- 每个语言提取器实现 DependencyExtractor 抽象基类
- 支持多语言混合项目（按文件语言分别处理）

依赖类型:
- internal: 指向项目内部文件
- system: 指向系统库（如 <stdio.h>）
- external_local: 指向外部本地库（如 "local_lib.h"）
"""
import os
import json
import logging
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict

from databases.db_pools import get_mongo_client

# 导入依赖提取器工厂
from parsers.languages.dependence_parser.extractor_factory import (
    DependencyExtractor,
    DependencyExtractorRegistry,
    get_dependency_extractor,
    get_supported_dependency_languages
)

logger = logging.getLogger(__name__)


def extract_dependency_graph(proj_id: int, language: str = None) -> List[Dict]:
    """
    从 MongoDB 提取依赖图，写入 graph_node 集合
    
    Args:
        proj_id: 项目 ID
        language: 指定语言（可选），如果为 None 则自动检测项目主要语言
        
    Returns:
        依赖关系列表
        
    Raises:
        ValueError: 当语言不支持时
        Exception: 提取失败时抛出异常
    """
    mongo_client = get_mongo_client()
    db = mongo_client.topocode
    proj_info_coll = db.proj_info
    base_node_coll = db.base_node
    graph_node_coll = db.graph_node

    logger.info(f"Extracting dependency graph for proj_id={proj_id}")

    # === Step 1: 加载项目文件信息 ===
    original_files = _load_project_files(proj_info_coll, proj_id, language)

    if not original_files:
        logger.warning(f"No original files found for proj_id={proj_id}" + (f" with language={language}" if language else ""))
        return []

    # 构建文件索引
    filename_to_id, id_to_filename = _build_file_indices(original_files)
    file_id_to_extractor = _initialize_extractors(original_files, language)
    
    # 构建 basename 索引
    project_files_by_basename = _build_basename_index(original_files)

    # === Step 2: 加载依赖相关的 AST 节点 ===
    dependency_nodes = _load_dependency_nodes(base_node_coll, proj_id, file_id_to_extractor)
    
    if not dependency_nodes:
        logger.info("No dependency-related nodes found.")
        return []

    # === Step 3: 按 file_id 分组节点 ===
    nodes_by_file = _group_nodes_by_file(dependency_nodes)

    # === Step 4: 逐文件提取依赖 ===
    raw_deps = _extract_raw_dependencies(
        nodes_by_file=nodes_by_file,
        file_id_to_extractor=file_id_to_extractor
    )

    # === Step 5: 分类依赖 ===
    dependencies, system_targets = _classify_dependencies(
        proj_id=proj_id,
        raw_deps=raw_deps,
        file_id_to_extractor=file_id_to_extractor,
        project_files_by_basename=project_files_by_basename
    )

    # === Step 6: 为 system includes 分配 file_id ===
    system_filename_to_id = _assign_system_file_ids(
        proj_info_coll=proj_info_coll,
        proj_id=proj_id,
        system_targets=system_targets
    )

    # === Step 7: 填充 to_file_id ===
    final_dependencies = _finalize_dependencies(
        dependencies=dependencies,
        system_filename_to_id=system_filename_to_id
    )

    # === Step 8: 写入 MongoDB ===
    if final_dependencies:
        # 只在处理第一种语言时删除旧数据
        existing_count = graph_node_coll.count_documents({
            "proj_id": proj_id,
            "symbol_node_type": "dependence"
        })
        if existing_count == 0:
            logger.info(f"Cleaning old dependency data for proj_id={proj_id}")
            graph_node_coll.delete_many({
                "proj_id": proj_id,
                "symbol_node_type": "dependence"
            })
        
        _save_dependencies(graph_node_coll, proj_id, final_dependencies, language)
        logger.info(f"Inserted {len(final_dependencies)} dependencies.")

    # === Step 9: 写入新的 system 文件到 proj_info ===
    new_system_entries = _save_system_files(
        proj_info_coll=proj_info_coll,
        proj_id=proj_id,
        system_filename_to_id=system_filename_to_id
    )
    
    if new_system_entries:
        logger.info(f"Inserted {len(new_system_entries)} system includes.")

    logger.info("Dependency graph extraction completed.")
    return final_dependencies


def _load_project_files(proj_info_coll, proj_id: int, language: str = None) -> List[Dict]:
    """
    加载项目文件信息（排除系统文件）

    Args:
        proj_info_coll: MongoDB proj_info 集合
        proj_id: 项目 ID
        language: 语言名称（可选），如果指定则只返回该语言的文件

    Returns:
        文件记录列表
    """
    query = {"proj_id": proj_id, "file_id": {"$lte": 1000000}}
    if language:
        query["file_lang"] = language
    
    original_files = list(proj_info_coll.find(query, {"file_id": 1, "file_name": 1, "_id": 0}))

    if language:
        logger.info(f"Loaded {len(original_files)} project files for language={language}")
    else:
        logger.info(f"Loaded {len(original_files)} project files")
    
    return original_files


def _build_file_indices(files: List[Dict]) -> Tuple[Dict[str, int], Dict[int, str]]:
    """
    构建文件索引
    
    Args:
        files: 文件记录列表
        
    Returns:
        (filename_to_id, id_to_filename)
    """
    filename_to_id = {}
    id_to_filename = {}
    
    for rec in files:
        fid = rec["file_id"]
        fname = rec["file_name"]
        filename_to_id[fname] = fid
        id_to_filename[fid] = fname
    
    return filename_to_id, id_to_filename


def _initialize_extractors(files: List[Dict], language: str = None) -> Dict[int, DependencyExtractor]:
    """
    初始化各文件的依赖提取器
    
    Args:
        files: 文件记录列表
        language: 指定语言（可选）
        
    Returns:
        {file_id: extractor}
    """
    file_id_to_extractor = {}
    
    # 确定项目语言
    project_language = language or _detect_project_language(files)
    
    # 获取对应语言的提取器
    extractor = get_dependency_extractor(project_language)
    
    if extractor is None:
        supported_langs = get_supported_dependency_languages()
        logger.warning(
            f"Dependency extractor not found for language '{project_language}'. "
            f"Supported languages: {supported_langs}. "
            f"Using CIncludeExtractor as fallback."
        )
        extractor = get_dependency_extractor('c')
    
    # 为所有文件分配提取器（简化处理：项目内所有文件使用同一提取器）
    for rec in files:
        fid = rec["file_id"]
        file_id_to_extractor[fid] = extractor
    
    logger.info(f"Using DependencyExtractor for language: {project_language}")
    return file_id_to_extractor


def _detect_project_language(files: List[Dict]) -> str:
    """
    检测项目的主要编程语言
    
    Args:
        files: 文件记录列表
        
    Returns:
        主要语言名称，默认返回 'c'
    """
    from parsers.languages.code_parser.lang_parser_conf import detect_language
    
    lang_counts: Dict[str, int] = defaultdict(int)
    
    for rec in files:
        file_name = rec.get("file_name", "")
        lang = detect_language(file_name)
        if lang:
            lang_counts[lang] += 1
    
    if not lang_counts:
        return 'c'
    
    primary_lang = max(lang_counts.items(), key=lambda x: x[1])[0]
    logger.info(f"Detected primary language for dependency: {primary_lang}")
    
    return primary_lang


def _build_basename_index(files: List[Dict]) -> Dict[str, List[int]]:
    """
    构建 basename 索引
    
    Args:
        files: 文件记录列表
        
    Returns:
        {basename: [file_id, ...]}
    """
    project_files_by_basename = defaultdict(list)
    
    for rec in files:
        fid = rec["file_id"]
        fname = rec["file_name"]
        basename = os.path.basename(fname)
        project_files_by_basename[basename].append(fid)
    
    return project_files_by_basename


def _load_dependency_nodes(
    base_node_coll,
    proj_id: int,
    file_id_to_extractor: Dict[int, DependencyExtractor]
) -> List[Dict]:
    """
    加载依赖相关的 AST 节点
    
    Args:
        base_node_coll: MongoDB base_node 集合
        proj_id: 项目 ID
        file_id_to_extractor: 文件提取器映射
        
    Returns:
        依赖节点列表
    """
    # 收集所有需要的节点类型
    all_possible_types = set()
    for extractor in file_id_to_extractor.values():
        if extractor:
            all_possible_types.update(extractor.get_required_node_types())
    
    if not all_possible_types:
        all_possible_types.add("preproc_include")  # fallback
    
    logger.info(f"Loading dependency nodes with types: {all_possible_types}")
    
    include_nodes = list(base_node_coll.find(
        {"proj_id": proj_id, "type": {"$in": list(all_possible_types)}},
        {"file_id": 1, "type": 1, "refs": 1, "_id": 0}
    ))
    
    logger.info(f"Loaded {len(include_nodes)} dependency nodes")
    return include_nodes


def _group_nodes_by_file(nodes: List[Dict]) -> Dict[int, List[Dict]]:
    """
    按 file_id 分组节点
    
    Args:
        nodes: 节点列表
        
    Returns:
        {file_id: [nodes]}
    """
    nodes_by_file = defaultdict(list)
    for node in nodes:
        fid = node["file_id"]
        nodes_by_file[fid].append(node)
    return nodes_by_file


def _extract_raw_dependencies(
    nodes_by_file: Dict[int, List[Dict]],
    file_id_to_extractor: Dict[int, DependencyExtractor]
) -> List[Dict]:
    """
    逐文件提取原始依赖
    
    Args:
        nodes_by_file: 按文件分组的节点
        file_id_to_extractor: 文件提取器映射
        
    Returns:
        原始依赖列表
    """
    raw_deps = []
    
    for file_id, nodes in nodes_by_file.items():
        extractor = file_id_to_extractor.get(file_id)
        if not extractor:
            continue

        required_types = set(extractor.get_required_node_types())
        filtered_nodes = [n for n in nodes if n["type"] in required_types]
        
        if not filtered_nodes:
            continue

        deps, _ = extractor.extract_dependencies(filtered_nodes)
        raw_deps.extend(deps)
    
    logger.info(f"Extracted {len(raw_deps)} raw dependencies")
    return raw_deps


def _classify_dependencies(
    proj_id: int,
    raw_deps: List[Dict],
    file_id_to_extractor: Dict[int, DependencyExtractor],
    project_files_by_basename: Dict[str, List[int]]
) -> Tuple[List[Dict], Set[str]]:
    """
    分类依赖（internal/system/external_local）

    Args:
        proj_id: 项目 ID
        raw_deps: 原始依赖列表
        file_id_to_extractor: 文件提取器映射
        project_files_by_basename: 项目文件 basename 索引

    Returns:
        (dependencies, system_targets)
    """
    dependencies = []
    system_targets = set()

    for dep in raw_deps:
        from_file_id = dep["from_file_id"]
        target = dep["target"]
        is_angle_bracket = dep.get("is_angle_bracket", False)

        extractor = file_id_to_extractor.get(from_file_id)
        if not extractor:
            # 使用默认提取器
            extractor = get_dependency_extractor('c')

        # 判断是否 internal (使用位置参数以兼容不同实现)
        is_internal, to_file_id = extractor.is_internal_dependency(
            target,
            project_files_by_basename
        )

        if is_internal:
            dependencies.append({
                "proj_id": proj_id,
                "symbol_node_type": "dependence",
                "from_file_id": from_file_id,
                "to_file_id": to_file_id,
                "include_type": "internal",
                "target": target
            })
        else:
            # 不是 internal
            if is_angle_bracket:
                include_type = "system"
                system_targets.add(target)
            else:
                include_type = "external_local"

            dependencies.append({
                "proj_id": proj_id,
                "symbol_node_type": "dependence",
                "from_file_id": from_file_id,
                "to_file_id": None,
                "include_type": include_type,
                "target": target
            })
    
    logger.info(f"Classified dependencies: {len(dependencies)} total, {len(system_targets)} system")
    return dependencies, system_targets


def _assign_system_file_ids(
    proj_info_coll,
    proj_id: int,
    system_targets: Set[str]
) -> Dict[str, int]:
    """
    为 system includes 分配 file_id
    
    Args:
        proj_info_coll: MongoDB proj_info 集合
        proj_id: 项目 ID
        system_targets: 系统库目标集合
        
    Returns:
        {target: file_id}
    """
    system_filename_to_id = {}
    next_system_id = 1000001

    # 加载已存在的 system 文件
    existing_system_files = {
        rec["file_name"]: rec["file_id"]
        for rec in proj_info_coll.find(
            {"proj_id": proj_id, "file_id": {"$gt": 1000000}},
            {"file_name": 1, "file_id": 1, "_id": 0}
        )
    }

    for target in sorted(system_targets):
        if target in existing_system_files:
            system_filename_to_id[target] = existing_system_files[target]
        else:
            system_filename_to_id[target] = next_system_id
            next_system_id += 1
    
    return system_filename_to_id


def _finalize_dependencies(
    dependencies: List[Dict],
    system_filename_to_id: Dict[str, int]
) -> List[Dict]:
    """
    填充 system 依赖的 to_file_id
    
    Args:
        dependencies: 依赖列表
        system_filename_to_id: system 文件 ID 映射
        
    Returns:
        最终依赖列表
    """
    final_dependencies = []
    
    for dep in dependencies:
        if dep["include_type"] == "system":
            dep["to_file_id"] = system_filename_to_id.get(dep["target"])
        final_dependencies.append(dep)
    
    return final_dependencies


def _save_dependencies(graph_node_coll, proj_id: int, dependencies: List[Dict], language: str = None):
    """
    保存依赖到 MongoDB

    Args:
        graph_node_coll: MongoDB graph_node 集合
        proj_id: 项目 ID
        dependencies: 依赖列表
        language: 语言名称（可选），用于标记依赖来源
    """
    # 不删除数据，让所有语言的依赖累积
    # 只在第一次运行时删除旧数据（通过检查是否存在该语言的依赖）

    # 批量插入（使用 update_one 避免重复）
    batch_size = 5000  # 增大批次大小以提高性能
    total = len(dependencies)

    from pymongo import UpdateOne

    for i in range(0, total, batch_size):
        batch = dependencies[i:i + batch_size]

        # 使用 bulk_write 进行 upsert 操作
        operations = []
        for dep in batch:
            # 构建唯一键
            filter_query = {
                "proj_id": proj_id,
                "symbol_node_type": "dependence",
                "from_file_id": dep["from_file_id"],
                "target": dep["target"]
            }
            operations.append(
                UpdateOne(
                    filter_query,
                    {"$set": dep},
                    upsert=True
                )
            )

        if operations:
            # 使用 ordered=False 提高性能
            graph_node_coll.bulk_write(operations, ordered=False)
            logger.info(f"✅ Upserted dependency batch {i//batch_size + 1}/{(total + batch_size - 1)//batch_size}, {len(operations)} items")


def _save_system_files(
    proj_info_coll,
    proj_id: int,
    system_filename_to_id: Dict[str, int]
) -> List[Dict]:
    """
    保存 system 文件记录到 proj_info
    
    Args:
        proj_info_coll: MongoDB proj_info 集合
        proj_id: 项目 ID
        system_filename_to_id: system 文件 ID 映射
        
    Returns:
        新插入的系统文件记录列表
    """
    # 获取已存在的 system 文件 ID
    existing_system_ids = {
        rec["file_id"]
        for rec in proj_info_coll.find(
            {"proj_id": proj_id, "file_id": {"$gt": 1000000}},
            {"file_id": 1, "_id": 0}
        )
    }
    
    new_system_entries = []
    for target, file_id in system_filename_to_id.items():
        if file_id not in existing_system_ids:
            new_system_entries.append({
                "proj_id": proj_id,
                "file_id": file_id,
                "file_name": target,
                "file_path": f"<system>/{target}",
                "hashcode": "",
                "mtime": 0
            })

    if new_system_entries:
        proj_info_coll.insert_many(new_system_entries)
    
    return new_system_entries


# ---------------- CLI 入口 ----------------
def main():
    """命令行入口"""
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python extract_dependency_graph.py <proj_id>")
        sys.exit(1)

    proj_id = int(sys.argv[1])
    
    try:
        deps = extract_dependency_graph(proj_id)
        logging.info(f"\nTotal dependencies extracted: {len(deps)}")
        if deps:
            logging.info("\nSample dependency:")
            logging.info(json.dumps(deps[0], indent=2, ensure_ascii=False))
    except Exception as e:
        logging.exception("Error during dependency graph extraction")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
