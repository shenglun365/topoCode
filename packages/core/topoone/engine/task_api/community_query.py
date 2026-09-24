"""社区/符号/边/报表查询域（MS5-V1 自 task_manager.py 切分；注册顺序经 task_api/__init__ 锁序）。
"""
import asyncio
import json
import os
import subprocess
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from topoone.db.manager import MultiDBManager
from topoone.engine.store.task_store import TaskStore
from topoone.engine.store.analysis_store import AnalysisStore
from topoone.engine.analysis_utils import get_cascade_levels_impl, get_l0_comps
from topoone.engine.community_data import unified_l0_components
from topoone.engine.analyst_runner import (
    _execute_task, set_stop_flag, clear_stop_flag, is_task_executing, enqueue_analysis_task,
)
from . import common
from .common import (
    _FIELD_MAP,
    _resolve_node_list_items,
    _compute_file_ranks,
    _count_batched_source_files,
    _reset_tasks_to_pending,
    _with_fixed_report_types,
    _ensure_project_db,
    _ensure_table,
    Shared,
)
from .git_info import detect_git_info, save_git_info, get_git_info, check_import_status, _run_git
from .positions import save_positions, load_positions, list_position_keys, clear_positions

logger = logging.getLogger(__name__)


def register(server, multi_db, S):
    @server.register("analysis.scanFileStats")
    def scan_file_stats(project_id=None, projectId=None,
                        scope=None, scopes=None,
                        pattern_type=None, patternType=None,
                        pattern=None,
                        exclude_dirs=None, excludeDirs=None,
                        selected_extensions=None, selectedExtensions=None):
        pid = project_id or projectId
        if not pid:
            raise ValueError("project_id is required")

        # 字段别名
        pattern_type = pattern_type or patternType
        exclude_dirs = exclude_dirs or excludeDirs
        selected_extensions = selected_extensions or selectedExtensions

        try:
            project_db = multi_db.get_project_db(pid)
            store = AnalysisStore(project_db)
            final_scopes = scopes if scopes else ([scope] if scope else None)
            logger.debug(f"[scan_file_stats] scopes={scopes}, scope={scope}, final_scopes={final_scopes}")

            # 1. totalFiles — COUNT 查询（极快）
            total_files = store.count_files(
                scopes=final_scopes,
                extensions=selected_extensions,
                exclude_dirs=exclude_dirs,
                pattern_type=pattern_type,
                pattern=pattern,
            )
            logger.debug(f"[scan_file_stats] totalFiles={total_files}")

            # 2. 目录树 — 只取 file_path（路径列）
            all_paths = store.list_file_paths()
            logger.debug(f"[scan_file_stats] {len(all_paths)} paths for directory tree")

            # 3. 扩展名分布 — 跟随目录选项（scopes 过滤），不受 selected_extensions 限制
            extensions = store.count_by_extensions(
                scopes=final_scopes,
                extensions=None,
                exclude_dirs=exclude_dirs,
                pattern_type=pattern_type,
                pattern=pattern,
            )
            dir_count_paths = store.list_file_paths(
                extensions=selected_extensions,
                exclude_dirs=exclude_dirs,
                pattern_type=pattern_type,
                pattern=pattern,
            )
            logger.debug(f"[scan_file_stats] {len(dir_count_paths)} paths for directory counts, {len(extensions)} extension types")

        except Exception as e:
            logger.error(f"[scan_file_stats] error: {e}")
            total_files = 0
            all_paths = []
            extensions = {}
            dir_count_paths = []

        # 完整目录树（基于全量文件路径，不受 scopes 影响）
        dir_tree: dict = {}
        for dir_path in all_paths:
            if dir_path:
                dir_path = dir_path.replace('\\', '/')
                parts = dir_path.split("/")
                current = dir_tree
                for part in parts[:-1]:  # 跳过文件名，只处理目录
                    if part not in current:
                        current[part] = {}
                    current = current[part]

        # 按目录统计文件数（基于语言类型过滤，不受 scopes 影响）
        dir_counts: dict = {}
        for dir_path in dir_count_paths:
            if dir_path:
                dir_path = dir_path.replace('\\', '/')
                parts = dir_path.split("/")
                current = dir_counts
                # 遍历所有目录层级，每层计数 +1
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {"_count": 0}
                    current[part]["_count"] = current[part].get("_count", 0) + 1
                    # 进入下一层
                    next_level = current[part]
                    if not isinstance(next_level, dict):
                        next_level = {}
                        current[part] = {"_count": 0}
                    current = current[part]

        # 将树形结构展平为前端可用的格式
        def flatten_dir_tree(tree: dict, prefix: str = "", counts: dict = None) -> list:
            result = []
            for name, children in sorted(tree.items()):
                path = f"{prefix}/{name}" if prefix else name
                file_count = None
                if counts:
                    cnt_node = counts.get(name, {})
                    if isinstance(cnt_node, dict):
                        file_count = cnt_node.get("_count", 0) or None
                node = {
                    "name": name,
                    "path": path,
                    "children": flatten_dir_tree(children, path, counts.get(name, {}) if counts and isinstance(counts.get(name, {}), dict) else None) if children else [],
                }
                if file_count is not None:
                    node["fileCount"] = file_count
                result.append(node)
            return result

        def count_all_dirs(tree: dict) -> int:
            """递归计算目录树中的节点总数"""
            count = len(tree)
            for children in tree.values():
                count += count_all_dirs(children)
            return count

        dir_list = flatten_dir_tree(dir_tree, "", dir_counts)
        total_dirs = count_all_dirs(dir_tree)

        return {
            "extensions": extensions,
            "totalFiles": total_files,
            "totalDirs": total_dirs,
            "directories": dir_list,
        }

    # ==================== 社区 LLM 结果 ====================

    @server.register("analysis.saveCommunityResult")
    def save_community_result(task_id=None, taskId=None, edge_type=None, edgeType=None,
                                comm_lv=None, commLv=None, comm_id=None, commId=None,
                                name=None, summary=None,
                                model_id=None, modelId=None, template_id=None, templateId=None):
        from topoone.engine.ingest import write_ingest
        tid = task_id or taskId
        et = edge_type or edgeType
        cl = comm_lv or commLv
        cid = comm_id or commId
        mid = model_id or modelId
        tpid = template_id or templateId
        if not tid or not et or not cl or not cid:
            raise ValueError("task_id, edge_type, comm_lv, comm_id are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_root = S.get_project_root(task["project_id"])
        # 兜底：剥离语义文档 MD 中渲染期合成的元数据头部，
        # 避免编辑保存时把「社区:/ID:」头部固化进 summary（重复累积）。
        if summary:
            try:
                from topoone.engine.component_name_disambiguation import strip_doc_header
                summary = strip_doc_header(summary)
            except Exception as _e:
                logger.warning("[analysis.saveCommunityResult] strip header failed: %s", _e)
        data = {
            "project_id": task["project_id"],
            "task_id": tid, "edge_type": et, "comm_lv": cl, "comm_id": cid,
            "name": name, "summary": summary,
            "model_id": mid, "template_id": tpid,
            "component_type": "community", "status": "completed",
        }
        write_ingest(task["project_id"], "community_result", data, data_dir=multi_db.data_dir)
        logger.info("[analysis.saveCommunityResult] DONE task_id=%s comm_id=%s", tid, cid)
        return {"success": True}

    @server.register("analysis.getCommunityResult")
    def get_community_result(task_id=None, taskId=None, edge_type=None, edgeType=None,
                              comm_lv=None, commLv=None, comm_id=None, commId=None):
        tid = task_id or taskId
        et = edge_type or edgeType
        cl = comm_lv or commLv
        cid = comm_id or commId
        if not tid or not et or not cl or not cid:
            raise ValueError("task_id, edge_type, comm_lv, comm_id are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        store = AnalysisStore(project_db)
        return store.get_llm_result(tid, et, cl, cid) or {}

    @server.register("analysis.listCommunityResults")
    def list_community_results(task_id=None, taskId=None, edge_type=None, edgeType=None):
        tid = task_id or taskId
        et = edge_type or edgeType
        logger.info("[analysis.listCommunityResults] ENTRY task_id=%s edge_type=%s", tid, et)
        if not tid or not et:
            logger.error("[analysis.listCommunityResults] missing required fields")
            raise ValueError("task_id and edge_type are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            logger.error("[analysis.listCommunityResults] task not found task_id=%s", tid)
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        store = AnalysisStore(project_db)
        results = store.list_llm_results(tid, et)
        logger.info("[analysis.listCommunityResults] DONE task_id=%s edge_type=%s results=%d", tid, et, len(results))
        return {"results": results}

    @server.register("analysis.updateCommunityName")
    def update_community_name(task_id=None, taskId=None, edge_type=None, edgeType=None,
                               comm_lv=None, commLv=None, comm_id=None, commId=None, name=None):
        tid = task_id or taskId
        et = edge_type or edgeType
        cl = comm_lv or commLv
        cid = comm_id or commId
        if not tid or not et or not cl or not cid:
            raise ValueError("task_id, edge_type, comm_lv, comm_id are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        store = AnalysisStore(project_db)
        store.update_community_name(tid, et, cl, cid, name or "")
        return {"success": True}

    # ==================== 组件命名消歧（独立流程，可按需反复运行） ====================

    @server.register("analysis.scanComponentNameConflicts")
    def scan_component_name_conflicts(task_id=None, taskId=None,
                                      comm_ids=None, commIds=None):
        """组件命名冲突排查（零 LLM）：归一化精确重复 + 相似度分组"""
        tid = task_id or taskId
        ids = comm_ids or commIds
        if not tid:
            raise ValueError("task_id is required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        from topoone.engine.component_name_disambiguation import scan_name_conflicts
        result = scan_name_conflicts(project_db, tid, comm_ids=ids)
        logger.info("[analysis.scanComponentNameConflicts] task=%s scanned=%d groups=%d dirty=%d",
                    tid, result.get("scanned", 0), len(result.get("groups", [])),
                    len(result.get("dirtySummaryCommIds", [])))
        return result

    @server.register("analysis.resolveComponentNameConflicts")
    async def resolve_component_name_conflicts(task_id=None, taskId=None,
                                               members=None, language=None, language_=None):
        """对一组冲突组件做 LLM 消歧并写回（按组调用，前端逐组循环获得进度）"""
        tid = task_id or taskId
        keys = members or []
        if not tid or not keys:
            raise ValueError("task_id and members are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        from topoone.engine.component_name_disambiguation import resolve_group
        result = await resolve_group(multi_db, project_db, tid, keys,
                                     language=language or language_ or "")
        logger.info("[analysis.resolveComponentNameConflicts] task=%s renamed=%d failed=%d",
                    tid, len(result.get("changes", [])), len(result.get("failed", [])))
        return result

    @server.register("analysis.cleanCommunitySummaries")
    def clean_community_summaries(task_id=None, taskId=None):
        """存量清理：剥离 community_llm_results.summary 内嵌的合成头部"""
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        from topoone.engine.component_name_disambiguation import clean_community_summaries as _clean
        return _clean(project_db, tid)

    # ==================== 报告 Tab 接口 ====================

    @server.register("analysis.getAvailableLevels")
    def get_available_levels(task_id=None, taskId=None, edge_type=None, edgeType=None):
        """获取任务实际生成的社区层级列表"""
        tid = task_id or taskId
        et = edge_type or edgeType
        if not tid:
            raise ValueError("task_id is required")

        # 从主库获取任务所属项目
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            return []
        project_id = task["project_id"]

        project_db = multi_db.get_project_db(project_id)
        if et:
            rows = project_db.execute(
                "SELECT DISTINCT comm_lv FROM graph_doc WHERE task_id=? AND edge_type=? ORDER BY comm_lv",
                (tid, et)
            ).fetchall()
        else:
            rows = project_db.execute(
                "SELECT DISTINCT comm_lv FROM graph_doc WHERE task_id=? ORDER BY comm_lv",
                (tid,)
            ).fetchall()
        levels = [row[0] for row in rows]

        return levels

    @server.register("analysis.getCommunityGraph")
    def get_community_graph(task_id=None, taskId=None,
                            edge_type=None, edgeType=None,
                            comm_lv=None, commLv=None,
                            comm_ids=None, commIds=None,
                            depth=None):
        """按条件查询社区图数据，支持深度展开"""
        tid = task_id or taskId
        et = edge_type or edgeType
        lv = comm_lv or commLv
        ids = comm_ids or commIds
        d = depth or 2

        if not tid or not lv:
            raise ValueError("task_id and comm_lv are required")

        # 从主库获取任务所属项目
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]

        project_db = multi_db.get_project_db(project_id)

        # 构建 file_id → file_path 缓存 + file_id → 显示标签（使用相对路径避免同名文件混淆）
        file_rows = project_db.execute(
            "SELECT id, file_path FROM source_files"
        ).fetchall()
        file_path_map = {row[0]: row[1] for row in file_rows}
        file_name_map = {row[0]: row[1] for row in file_rows if row[1]}

        # ==================== 辅助函数 ====================

        def bad_id(v):
            """判断是否为无效 ID"""
            s = str(v).strip()
            return not s or s == 'None'

        def clean_edge_source(src):
            """清理边 source 中的 garbled 前缀"""
            s = str(src) if src else ''
            if s.startswith('None:['):
                s = s[6:]
            elif s.startswith('['):
                s = s[1:]
            return s

        def build_node_ref_map(all_node_lists, all_edge_lists):
            """构建 node_id → {label, fileId, filePath, graphNodeId, symbolName} 映射

            node_id 格式（当前）:
              - 文件节点: file:/full/path/to/file.ts
              - 符号节点: 16 位 hex hash
            """
            ref_map = {}

            # 收集所有唯一 node_id
            all_node_ids = set()
            for nl in all_node_lists:
                for nid in nl:
                    if nid and not bad_id(nid):
                        all_node_ids.add(str(nid))

            if not all_node_ids:
                return ref_map

            # 仅查询所需的 node_id（而非全表 30K+ 行），批量 IN 查询利用主键索引
            gn_index = {}  # node_id → row
            node_list = list(all_node_ids)
            batch_size = 500
            for i in range(0, len(node_list), batch_size):
                batch = node_list[i:i + batch_size]
                placeholders = ','.join(['?' for _ in batch])
                gn_rows = project_db.execute(
                    f"SELECT id, kind, name, qualified_name, file_path, file_id"
                    f" FROM graph_node WHERE task_id=? AND id IN ({placeholders})",
                    (tid, *batch)
                ).fetchall()
                for row in gn_rows:
                    gn_index[str(row['id'])] = row

            # 为每个 node_id 查询元数据 — 通过 graph_node 直接查找
            for nid in all_node_ids:
                row = gn_index.get(nid)
                if row:
                    file_path = str(row['file_path'] or '')
                    name = str(row['name'] or '')
                    qualified = str(row['qualified_name'] or '')
                    kind = str(row['kind'] or '')
                    file_id = str(row['file_id'] or '')

                    if kind == 'file':
                        label = os.path.basename(file_path) or nid
                    elif qualified:
                        label = qualified
                    elif name:
                        label = name
                    else:
                        label = nid

                    ref_map[nid] = {
                        'label': label,
                        'fileId': file_id or nid,
                        'filePath': file_path,
                        'graphNodeId': row['id'],
                        'symbolName': name if kind != 'file' else '',
                    }
                else:
                    # 不在 graph_node 中的 ID（可能是文件名/路径），尝试从 source_files 查找
                    file_name = file_name_map.get(nid, '')
                    if not file_name:
                        base = os.path.basename(nid) if isinstance(nid, str) else str(nid)
                        file_name = file_name_map.get(base, base)
                    ref_map[nid] = {
                        'label': file_name or nid,
                        'fileId': nid,
                        'filePath': file_path_map.get(nid, ''),
                        'graphNodeId': None,
                        'symbolName': '',
                    }

            return ref_map

        # 查询选中的社区
        if ids and len(ids) > 0:
            placeholders = ','.join(['?' for _ in ids])
            rows = project_db.execute(
                f"SELECT comm_id, node_list, edge_list, node_count, edge_count, quality_score, description FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=? AND comm_id IN ({placeholders})",
                [tid, et, lv] + ids
            ).fetchall()
        else:
            # 返回该层级所有社区
            rows = project_db.execute(
                "SELECT comm_id, node_list, edge_list, node_count, edge_count, quality_score, description FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=? ORDER BY quality_score DESC",
                (tid, et, lv)
            ).fetchall()

        nodes = []
        edges = []
        communities = []

        # 先收集所有 node_list / edge_list，用于批量构建 ref_map
        all_nls = []
        all_els = []
        rows_with_meta = []

        for row in rows:
            comm_id = row[0]
            node_list = json.loads(row[1]) if row[1] else []
            edge_list = json.loads(row[2]) if row[2] else []
            node_count = row[3] or 0
            edge_count = row[4] or 0
            quality_score = row[5] or 0
            description = row[6] or ''
            direction = row[7] if len(row) > 7 else ''

            all_nls.append(node_list)
            all_els.append(edge_list)
            rows_with_meta.append({
                'comm_id': comm_id,
                'node_list': node_list,
                'edge_list': edge_list,
                'node_count': node_count,
                'edge_count': edge_count,
                'quality_score': quality_score,
                'description': description,
            })

        # 批量构建实名映射
        ref_map = build_node_ref_map(all_nls, all_els)

        def node_display(nid):
            """获取节点的实名标签"""
            info = ref_map.get(nid, {})
            label = info.get('label', '')
            if label and label != str(nid):
                return label
            # 尝试去掉后缀再查 ref_map（CALL 汇总后 key 不匹配场景）
            if ':' in str(nid):
                bare_id = str(nid).split(':', 1)[0]
                info = ref_map.get(bare_id, {})
                label = info.get('label', '')
                if label and label != str(nid):
                    return label
            # Fallback: source_files 查询（多种 ID 格式兼容）
            label = file_name_map.get(nid, '')
            if not label:
                label = file_name_map.get(f'file-{nid}', '')
            if not label and nid.startswith('file-'):
                label = file_name_map.get(nid[5:], '')  # 去掉 file- 前缀再查
            return label or str(nid)

        def node_ref_id(nid):
            """获取节点的 graph_node 索引 ID"""
            info = ref_map.get(nid, {})
            return info.get('graphNodeId')

        def node_file_id(nid):
            """获取节点的 source_files.id"""
            info = ref_map.get(nid, {})
            return info.get('fileId', '')

        def node_file_path(nid):
            """获取节点的文件路径"""
            info = ref_map.get(nid, {})
            return info.get('filePath', '')

        def aggregate_to_files(_nodes, _edges):
            """将语法级节点汇聚到文件级：去重 + 合并边，优先通过 graph_node 查找文件归属"""
            file_nodes = {}
            for node_id in _nodes:
                # 优先通过 ref_map 获取文件归属（已修正为 graph_node 直查）
                ref_info = ref_map.get(node_id)
                if ref_info and ref_info.get('filePath'):
                    clean_id = ref_info['filePath']
                else:
                    # fallback: 解析 node_id（兼容旧格式）
                    clean_id = node_id.split(':')[0] if ':' in (node_id or '') else node_id
                if bad_id(clean_id):
                    continue
                if clean_id not in file_nodes:
                    label = file_name_map.get(clean_id, '')
                    if not label:
                        label = ref_map.get(node_id, {}).get('label', '')
                    if not label:
                        label = str(clean_id)
                    file_nodes[clean_id] = label

            file_edges = set()
            for edge in _edges:
                if isinstance(edge, dict):
                    s, t = edge.get('source', ''), edge.get('target', '')
                elif isinstance(edge, list) and len(edge) >= 2:
                    s, t = edge[0], edge[1]
                else:
                    continue
                s_clean = clean_edge_source(s).split(':')[0] if ':' in str(s) else clean_edge_source(s)
                t_clean = t.split(':')[0] if ':' in str(t) else str(t)
                if bad_id(s_clean) or bad_id(t_clean):
                    continue
                if s_clean and t_clean and s_clean != t_clean:
                    file_edges.add((s_clean, t_clean))

            return list(file_nodes.keys()), file_nodes, list(file_edges)

        for row in rows:
            comm_id = row[0]
            node_list = json.loads(row[1]) if row[1] else []
            edge_list = json.loads(row[2]) if row[2] else []
            node_count = row[3] or 0
            edge_count = row[4] or 0
            quality_score = row[5] or 0
            description = row[6] or ''

            # CALL 类型：汇聚到文件级
            agg_labels_map = {}
            if et == 'CALL':
                agg_ids, agg_labels_map, agg_edges = aggregate_to_files(node_list, edge_list)
                node_list = agg_ids
                edge_list = [{'source': s, 'target': t} for s, t in agg_edges]
                description = f'CALL community ({len(agg_ids)} files, {len(agg_edges)} edges)'

            # 添加社区节点
            communities.append({
                'comm_id': comm_id,
                'node_count': node_count,
                'edge_count': edge_count,
                'quality_score': quality_score,
                'description': description,
            })

            # 添加节点和边（使用实名 + 索引信息）
            for node in node_list:
                nodes.append({
                    'id': f'n_{node}',
                    'label': agg_labels_map.get(node) or node_display(node),
                    'refId': node_ref_id(node),
                    'fileId': node_file_id(node),
                    'filePath': node_file_path(node),
                    'comm_id': comm_id,
                    'type': 'symbol',
                })
            for edge in edge_list:
                if isinstance(edge, dict):
                    s, t = edge.get('source', ''), edge.get('target', '')
                    direction = edge.get('direction', '')
                elif isinstance(edge, list) and len(edge) >= 2:
                    s, t = edge[0], edge[1]
                    direction = edge[2] if len(edge) > 2 else ''
                else:
                    continue
                # 清理 garbled source
                s = clean_edge_source(s)
                t = t.split(':')[0] if ':' in str(t) else str(t)
                if bad_id(s) or bad_id(t):
                    continue
                edges.append({
                    'id': f'e_{s}_{t}',
                    'source': f'n_{s}',
                    'target': f'n_{t}',
                    'sourceLabel': agg_labels_map.get(s) or node_display(s),
                    'targetLabel': agg_labels_map.get(t) or node_display(t),
                    'sourceRefId': node_ref_id(s),
                    'targetRefId': node_ref_id(t),
                    'type': et or 'UNIFIED',
                    'direction': direction,
                })

            # 深度展开：查询子社区
            if d > 1:
                child_rows = project_db.execute(
                    "SELECT comm_id, node_list, edge_list, node_count, comm_lv FROM graph_doc WHERE task_id=? AND edge_type=? AND parent_comm_id=?",
                    (tid, et, comm_id)
                ).fetchall()

                for depth_level in range(d - 1):
                    child_comm_ids = [r[0] for r in child_rows]
                    for cr in child_rows:
                        child_comm_id = cr[0]
                        child_node_list = json.loads(cr[1]) if cr[1] else []
                        child_edge_list = json.loads(cr[2]) if cr[2] else []
                        child_node_count = cr[3] or 0

                        communities.append({
                            'comm_id': child_comm_id,
                            'node_count': child_node_count,
                            'edge_count': len(child_edge_list) if child_edge_list else 0,
                            'quality_score': 0,
                            'description': '',
                            'parent_comm_id': comm_id if depth_level == 0 else None,
                        })

                        # 如果深度还没到最大，继续查询子社区
                        if depth_level < d - 2:
                            grandchild_rows = project_db.execute(
                                "SELECT comm_id, node_list, edge_list, node_count FROM graph_doc WHERE task_id=? AND edge_type=? AND parent_comm_id=?",
                                (tid, et, child_comm_id)
                            ).fetchall()
                            child_rows = grandchild_rows
                        else:
                            # 最深层，直接添加符号节点（CALL 类型先汇聚到文件级）
                            if et == 'CALL':
                                agg_ids, agg_labels_map, agg_edges = aggregate_to_files(child_node_list, child_edge_list)
                                for node in agg_ids:
                                    nodes.append({
                                        'id': f'n_{child_comm_id}_{node}',
                                        'label': agg_labels_map.get(node, str(node)),
                                        'refId': node_ref_id(node),
                                        'fileId': node_file_id(node),
                                        'filePath': node_file_path(node),
                                        'comm_id': child_comm_id,
                                        'type': 'symbol',
                                    })
                                for s, t in agg_edges:
                                    edges.append({
                                        'id': f'e_{child_comm_id}_{s}_{t}',
                                        'source': f'n_{child_comm_id}_{s}',
                                        'target': f'n_{child_comm_id}_{t}',
                                        'sourceLabel': agg_labels_map.get(s) or node_display(s),
                                        'targetLabel': agg_labels_map.get(t) or node_display(t),
                                        'sourceRefId': node_ref_id(s),
                                        'targetRefId': node_ref_id(t),
                                        'type': et,
                                    })
                            else:
                                for node in child_node_list:
                                    nodes.append({
                                        'id': f'n_{child_comm_id}_{node}',
                                        'label': node_display(node),
                                        'refId': node_ref_id(node),
                                        'fileId': node_file_id(node),
                                        'filePath': node_file_path(node),
                                        'comm_id': child_comm_id,
                                        'type': 'symbol',
                                    })
                                for edge in (child_edge_list or []):
                                    if isinstance(edge, list) and len(edge) >= 2:
                                        edges.append({
                                            'id': f'e_{child_comm_id}_{edge[0]}_{edge[1]}',
                                            'source': f'n_{child_comm_id}_{edge[0]}',
                                            'target': f'n_{child_comm_id}_{edge[1]}',
                                            'sourceLabel': node_display(edge[0]),
                                            'targetLabel': node_display(edge[1]),
                                            'sourceRefId': node_ref_id(edge[0]),
                                            'targetRefId': node_ref_id(edge[1]),
                                            'type': et or 'UNIFIED',
                                        })
                            break

        return {
            'nodes': nodes,
            'edges': edges,
            'communities': communities,
        }

    @server.register("analysis.getSymbolDetail")
    def get_symbol_detail(task_id=None, taskId=None, symbol_id=None, symbolId=None):
        """获取符号详情 + 代码抽样"""
        tid = task_id or taskId
        sid = symbol_id or symbolId
        if not tid or not sid:
            raise ValueError("task_id and symbol_id are required")

        # 从主库获取任务所属项目
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]

        project_db = multi_db.get_project_db(project_id)

        # 查询符号信息
        row = project_db.execute(
            "SELECT kind, name, qualified_name, file_id FROM graph_node WHERE task_id=? AND id=?",
            (tid, sid)
        ).fetchone()

        if not row:
            # 尝试按名称搜索
            row = project_db.execute(
                "SELECT kind, name, qualified_name, file_id FROM graph_node WHERE task_id=? AND (name=? OR qualified_name=?)",
                (tid, sid, sid)
            ).fetchone()

        if not row:
            return None

        symbol_type = row[0]
        name = row[1]
        qualified_name = row[2]
        file_id = row[3]

        # 获取文件路径
        file_path = ''
        if file_id:
            file_row = project_db.execute(
                "SELECT file_path FROM source_files WHERE id=?",
                (file_id,)
            ).fetchone()
            file_path = file_row[0] if file_row else ''

        # 查询 graph_node 获取行号
        start_line = 1
        end_line = 20
        ast_row = project_db.execute(
            "SELECT start_line, end_line FROM graph_node WHERE file_id=? AND name=? LIMIT 1",
            (file_id, name or qualified_name)
        ).fetchone()

        if ast_row:
            try:
                start_line = int(ast_row[0])
                end_line = int(ast_row[1])
            except (ValueError, IndexError):
                pass

        # 读取代码抽样（最多 20 行）
        code_snippet = ''
        if file_path and start_line and end_line:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
                    snippet_start = max(0, start_line - 1)
                    snippet_end = min(len(lines), end_line)
                    code_snippet = ''.join(lines[snippet_start:snippet_end])
            except (FileNotFoundError, PermissionError):
                pass

        # 判断是否需要 LLM 压缩
        needs_summarize = len(code_snippet) > 500

        return {
            'symbol_id': sid,
            'symbol_type': symbol_type,
            'name': name or qualified_name or sid,
            'class_name': '',
            'file_path': file_path,
            'start_line': start_line,
            'end_line': end_line,
            'code_snippet': code_snippet,
            'needs_summarize': needs_summarize,
        }

    @server.register("analysis.getEdgeDetail")
    def get_edge_detail(task_id=None, taskId=None, edge_id=None, edgeId=None):
        """获取边详情"""
        tid = task_id or taskId
        eid = edge_id or edgeId
        if not tid or not eid:
            raise ValueError("task_id and edge_id are required")

        # 从主库获取任务所属项目
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]

        project_db = multi_db.get_project_db(project_id)

        # 从 edge_id 解析 source 和 target
        # edge_id 格式: e_source_target
        parts = eid.replace('e_', '').rsplit('_', 1)
        if len(parts) != 2:
            return None

        source_id, target_id = parts

        # 查询边的信息
        row = project_db.execute(
            "SELECT kind, source_id, target_id, provenance, line, col, file_path, metadata FROM graph_edge WHERE task_id=? AND id=?",
            (tid, eid)
        ).fetchone()

        if not row:
            # 尝试通过 source/target 查找
            row = project_db.execute(
                "SELECT kind, source_id, target_id, provenance, line, col, file_path, metadata FROM graph_edge WHERE task_id=? AND (source_id=? OR target_id=?)",
                (tid, source_id, target_id)
            ).fetchone()

        if not row:
            return None

        kind = row[0]

        if kind == 'calls':
            return {
                'edge_id': eid,
                'edge_type': 'CALL',
                'source': {
                    'name': row[1],  # source_id
                    'file_id': row[1],  # source_id
                },
                'target': {
                    'name': row[2],  # target_id
                    'file_id': row[2],  # target_id
                },
                'call_site_node_id': None,
            }
        elif kind == 'imports':
            return {
                'edge_id': eid,
                'edge_type': 'DEPENDENCE',
                'include_path': row[6],
                'is_system': False,
            }

        return None

    # ==================== 级联社区查询 ====================

    @server.register("analysis.getReportDashboard")
    def get_report_dashboard(task_id=None, taskId=None):
        """获取报告仪表盘数据：任务详情 + 社区层级 + LLM 结果 + 文件统计（一次调用）
        用于 ReportHome 页面初始加载，替代多次独立 RPC 调用
        """
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        t_total = time.perf_counter()
        logger.info("[analysis.getReportDashboard] ENTRY task_id=%s", tid)

        t0 = time.perf_counter()
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            return None
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        logger.info("[PERF] getReportDashboard load_task=%.1fms", (time.perf_counter() - t0) * 1000)

        # 1. 级联社区层级（组件统一：仅 UNIFIED；callLevels/depLevels 为兼容别名）
        t0 = time.perf_counter()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            uni_levels = pool.submit(get_cascade_levels_impl, project_db, tid, 'UNIFIED').result()
        t_cascade = time.perf_counter() - t0
        logger.info("[PERF] getReportDashboard cascade_levels total=%.1fms", t_cascade * 1000)

        # 2. LLM 结果（仅 UNIFIED）
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=1) as pool:
            uni_results = pool.submit(_list_community_results_impl, project_db, tid, 'UNIFIED').result()
        t_llm = time.perf_counter() - t0
        logger.info("[PERF] getReportDashboard llm_results total=%.1fms", t_llm * 1000)

        # 3. 获取文件统计
        t0 = time.perf_counter()
        file_stats = _scan_file_stats_impl(project_db, pid)
        logger.info("[PERF] getReportDashboard file_stats=%.1fms", (time.perf_counter() - t0) * 1000)

        # 4. 预摘要状态
        pre_summary = {'counts': {'P0': 0, 'P1': 0, 'P2': 0}, 'total_files': 0, 'cached_count': 0, 'project_root': '', 'failed_count': multi_db.cache_store.get_ps_failed(tid)}
        try:
            # 从 file_summaries 表直接统计缓存数（无社区数据时也能工作）
            p_rows = project_db.execute(
                "SELECT COUNT(*) as cnt FROM file_summaries WHERE project_id=?", (pid,)
            ).fetchone()
            cached = p_rows["cnt"] if p_rows else 0
            pre_summary['cached_count'] = cached

            # 尝试从社区计算总分批次（可能无社区数据，此时总文件数为 0）
            # 优先使用管线预缓存的排名数据（避免同步 I/O 阻塞事件循环）
            rank_data = multi_db.cache_store.get_file_ranks(tid)
            project_root = S.get_project_root(pid)
            if rank_data is None:
                comps = get_l0_comps(project_db, tid)
                rank_data = common._compute_file_ranks(tid, project_db, comps, project_root)
            if rank_data:
                pre_summary['counts'] = rank_data.get("counts", {'P0': 0, 'P1': 0, 'P2': 0, 'P3': 0})
                _files = rank_data.get("files", [])
                pre_summary['total_files'] = sum(1 for f in _files if f.get("batch") != "P3")
                pre_summary['p3_count'] = len(_files) - pre_summary['total_files']
            pre_summary['project_root'] = project_root
        except Exception as e:
            logger.warning("[getReportDashboard] preSummary failed: %s", e)

        logger.info("[PERF] getReportDashboard TOTAL=%.1fms task_id=%s", (time.perf_counter() - t_total) * 1000, tid)
        logger.info("[analysis.getReportDashboard] DONE task_id=%s", tid)
        return {
            'task': task,
            'uniLevels': uni_levels,
            'uniResults': uni_results,
            'fileStats': file_stats,
            'preSummary': pre_summary,
        }

    def get_cascade_levels_impl(project_db, tid, et, pid=None):
        """getCascadeLevels 内部实现（无 RPC 注册）"""
        t_sql = time.perf_counter()
        rows = []
        has_file_count = True
        # 优先 DuckDB LEFT JOIN（消除 N+1 相关子查询）
        if pid and multi_db:
            try:
                duck_rows = multi_db.duckdb.get_cascade_levels(tid, pid, et)
                if duck_rows:
                    rows = [(r.get("comm_lv"), r.get("comm_id"),
                             r.get("parent_comm_id"), r.get("node_count"),
                             r.get("file_count"), r.get("quality_score"),
                             r.get("edge_count"), r.get("metadata"))
                            for r in duck_rows]
                    logger.info("[PERF] cascade_duckdb %s rows=%d %.1fms",
                               et, len(rows), (time.perf_counter() - t_sql) * 1000)
            except Exception as e:
                logger.warning(f"[DuckDB] cascade_levels fallback to SQLite: {e}")
        # SQLite 回退
        if not rows:
            try:
                rows = project_db.execute(
                    """SELECT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count,
                               h.file_count, h.quality_score, h.edge_count,
                               (SELECT g.metadata FROM graph_doc g
                                WHERE g.task_id = h.task_id AND g.edge_type = h.edge_type AND g.comm_id = h.comm_id
                                LIMIT 1) AS metadata
                        FROM community_hierarchy h
                        WHERE h.task_id=? AND h.edge_type=?
                        ORDER BY h.comm_lv, h.comm_id""",
                    (tid, et)
                ).fetchall()
                has_file_count = True
            except Exception as e:
                if 'file_count' not in str(e).lower() and 'no such column' not in str(e).lower():
                    raise
                has_file_count = False
                rows = project_db.execute(
                    """SELECT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count,
                               h.quality_score, h.edge_count
                       FROM community_hierarchy h
                       WHERE h.task_id=? AND h.edge_type=?
                       ORDER BY h.comm_lv, h.comm_id""",
                    (tid, et)
                ).fetchall()
            logger.info("[PERF] cascade_sql %s rows=%d %.1fms", et, len(rows), (time.perf_counter() - t_sql) * 1000)

        levels_dict = {}
        for row in rows:
            if has_file_count:
                lv, comm_id, parent_id, node_count, file_count, quality, edge_count, metadata_raw = row
            else:
                lv, comm_id, parent_id, node_count, quality, edge_count = row
                file_count = 0
                metadata_raw = None
            metadata = {}
            if metadata_raw:
                try:
                    metadata = json.loads(metadata_raw)
                except (json.JSONDecodeError, TypeError):
                    pass
            if lv not in levels_dict:
                levels_dict[lv] = []
            levels_dict[lv].append({
                'id': comm_id, 'label': comm_id[:30], 'parentCommId': parent_id,
                'nodeCount': node_count or 0, 'fileCount': file_count or 0,
                'edgeCount': edge_count or 0, 'qualityScore': quality,
                'metadata': metadata,
            })

        # 1. 社区级别的文件覆盖（L0 node_list 去重）—— 精确但偏保守
        community_files = 0
        try:
            rows = project_db.execute(
                "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv='L0'",
                (tid, et)).fetchall()
            if rows:
                uniq = set()
                for r in rows:
                    nl = json.loads(r[0]) if r[0] else []
                    for nid in nl:
                        uniq.add(str(nid))
                community_files = len(uniq)
        except Exception:
            pass

        # 2. 边级别的文件覆盖（所有有 resolved 边参与的文件）—— 避免同类文件调用、孤立节点被过滤后的低估
        edge_files = community_files
        if et in ('CALL', 'INCLUDE'):
            edge_kind = 'calls' if et == 'CALL' else 'imports'
            try:
                t_edge = time.perf_counter()
                rows = project_db.execute(
                    f"""SELECT DISTINCT COALESCE(gn.file_path, ge.source_id) as fp
                        FROM graph_edge ge
                        LEFT JOIN graph_node gn ON gn.id = ge.source_id AND gn.task_id = ge.task_id
                        WHERE ge.task_id=? AND ge.kind=? AND ge.target_id != ''
                        UNION
                        SELECT DISTINCT COALESCE(gn.file_path, ge.target_id) as fp
                        FROM graph_edge ge
                        LEFT JOIN graph_node gn ON gn.id = ge.target_id AND gn.task_id = ge.task_id
                        WHERE ge.task_id=? AND ge.kind=? AND ge.target_id != ''""",
                    (tid, edge_kind, tid, edge_kind)
                ).fetchall()
                edge_files = len(rows)
                logger.info("[PERF] cascade_edge_files %s count=%d %.1fms",
                           et, edge_files, (time.perf_counter() - t_edge) * 1000)
            except Exception:
                pass

        # 使用边级计数作为 totalUniqueFiles（更准确反映"有调用/依赖关系的文件数"）
        total_unique = max(community_files, edge_files)

        result = []
        for lv in sorted(levels_dict.keys()):
            result.append({'lv': lv, 'items': levels_dict[lv]})
        return {'levels': result, 'totalUniqueFiles': total_unique}

    def _list_community_results_impl(project_db, tid, et):
        """listCommunityResults 内部实现"""
        try:
            rows = project_db.execute(
                "SELECT * FROM community_llm_results WHERE task_id=? AND edge_type=? ORDER BY comm_lv, comm_id",
                (tid, et)).fetchall()
            return {'results': [dict(r) for r in rows]}
        except Exception:
            return {'results': []}

    def _scan_file_stats_impl(project_db, pid):
        """scanFileStats 内部实现"""
        files = project_db.fetchall(
            "SELECT file_path, file_name, language, size FROM source_files WHERE language != 'directory' ORDER BY file_path")
        extensions = {}
        for f in files:
            lang = f.get("language", "unknown")
            extensions[lang] = extensions.get(lang, 0) + 1
        return {
            'extensions': extensions,
            'totalFiles': len(files),
            'totalDirs': 0,
            'directories': [],
        }

    @server.register("analysis.getCascadeLevels")
    def get_cascade_levels(task_id=None, taskId=None, edge_type=None, edgeType=None):
        """获取级联社区层级结构
        返回格式: {levels: [{lv: 'L0', items: [{id, label, nodeCount, parentCommId}]}]}
        """
        tid = task_id or taskId
        et = edge_type or edgeType or 'UNIFIED'
        if not tid:
            raise ValueError("task_id is required")
        logger.info("[analysis.getCascadeLevels] ENTRY task_id=%s edge_type=%s", tid, et)

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            logger.warning("[analysis.getCascadeLevels] task not found task_id=%s", tid)
            return {"levels": []}
        project_db = multi_db.get_project_db(task["project_id"])
        pid = task["project_id"]

        result = get_cascade_levels_impl(project_db, tid, et, pid=pid)
        logger.info("[analysis.getCascadeLevels] DONE task_id=%s edge_type=%s", tid, et)
        return result

    @server.register("analysis.getQueryStats")
    def get_query_stats(task_id=None, taskId=None, edge_type=None, edgeType=None,
                        comm_lv=None, commLv=None, comm_ids=None, commIds=None,
                        depth=None):
        """获取查询统计: 社区数、节点数、边数"""
        tid = task_id or taskId
        et = edge_type or edgeType or 'UNIFIED'
        cl = comm_lv or commLv
        cids = comm_ids or commIds or []
        d = depth or 1

        if not tid or not cl:
            raise ValueError("task_id and comm_lv are required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]
        project_db = multi_db.get_project_db(project_id)

        # 收集所有需要查询的社区ID(含深度展开)
        all_comm_ids = set(cids) if cids else set()

        # 如果不指定社区, 查询该层级所有社区
        if not all_comm_ids:
            rows = project_db.execute(
                "SELECT comm_id FROM community_hierarchy WHERE task_id=? AND edge_type=? AND comm_lv=?",
                (tid, et, cl)
            ).fetchall()
            all_comm_ids = {row[0] for row in rows}

        # 深度展开子社区
        if d and d > 1:
            current_ids = set(all_comm_ids)
            for _ in range(d - 1):
                placeholders = ','.join(['?' for _ in current_ids])
                child_rows = project_db.execute(
                    f"SELECT comm_id FROM community_hierarchy WHERE task_id=? AND edge_type=? AND parent_comm_id IN ({placeholders})",
                    [tid, et] + list(current_ids)
                ).fetchall()
                new_ids = {row[0] for row in child_rows}
                all_comm_ids.update(new_ids)
                current_ids = new_ids
                if not new_ids:
                    break

        # 统计
        total_nodes = 0
        total_edges = 0
        community_count = len(all_comm_ids)

        if all_comm_ids:
            placeholders = ','.join(['?' for _ in all_comm_ids])
            doc_rows = project_db.execute(
                f"SELECT node_count, edge_count FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id IN ({placeholders})",
                [tid, et] + list(all_comm_ids)
            ).fetchall()
            for row in doc_rows:
                total_nodes += row[0] or 0
                total_edges += row[1] or 0

        return {
            'communityCount': community_count,
            'nodeCount': total_nodes,
            'edgeCount': total_edges,
        }

    @server.register("analysis.getCrossCommunityEdges")
    def get_cross_community_edges(task_id=None, taskId=None,
                                   edge_type=None, edgeType=None,
                                   comm_lv=None, commLv=None):
        """获取指定层级社区间的跨社区边（聚合计数）"""
        tid = task_id or taskId
        et = edge_type or edgeType or 'UNIFIED'
        lv = comm_lv or commLv or 'L0'

        if not tid:
            raise ValueError("task_id is required")

        t_total = time.perf_counter()

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)

        # 获取项目根路径（用于归一化 edge 中的绝对路径）
        proj_row = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj_row["root_path"].replace('\\', '/') + "/") if proj_row and proj_row["root_path"] else ""

        edge_kind = 'calls' if et == 'CALL' else 'imports'

        # 1. Load all communities at the given level for this edge_type
        doc_rows = project_db.execute(
            "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=?",
            (tid, et, lv)
        ).fetchall()

        if not doc_rows:
            logger.info(f"[PERF] getCrossCommunityEdges TOTAL=%.1fms (no communities)",
                       (time.perf_counter() - t_total) * 1000)
            return {'crossEdges': []}

        # 2. Build node → comm_id reverse map
        # graph_doc.node_list contains file paths (without 'file:' prefix) for INCLUDE,
        # and file paths for CALL communities (after community detection aggregation).
        # graph_edge.source_id/target_id for 'imports' uses 'file:/path' format,
        # for 'calls' uses symbol hash IDs → need to resolve to file_path via graph_node.
        node_comm = {}  # normalized_key → comm_id

        for row in doc_rows:
            comm_id = row[0]
            try:
                nodes = json.loads(row[1]) if row[1] else []
            except Exception:
                nodes = []
            for nid in nodes:
                key = nid  # already a file path for INCLUDE, may be file path for CALL too
                node_comm[key] = comm_id

        logger.info(f"[getCrossCommunityEdges] loaded {len(node_comm)} nodes across {len(doc_rows)} communities")

        # 3. Load all edges for the task
        all_edges = project_db.execute(
            "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
            (tid, edge_kind)
        ).fetchall()

        # For CALL, pre-load symbol→file_path mapping (batch query from graph_node)
        symbol_file_map = {}
        if edge_kind == 'calls':
            # collect all unique symbol IDs from edges
            sym_ids = set()
            for edge in all_edges:
                if edge[0]: sym_ids.add(edge[0])
                if edge[1]: sym_ids.add(edge[1])
            if sym_ids:
                # batch lookup in chunks of 999 (SQLite variable limit)
                sym_list = list(sym_ids)
                batch_size = 900
                for i in range(0, len(sym_list), batch_size):
                    batch = sym_list[i:i + batch_size]
                    placeholders = ','.join(['?'] * len(batch))
                    rows = project_db.execute(
                        f"SELECT id, file_path FROM graph_node WHERE task_id=? AND id IN ({placeholders})",
                        [tid] + batch
                    ).fetchall()
                    for r in rows:
                        symbol_file_map[r[0]] = r[1] or ''

        __root = project_root.replace('\\', '/') if project_root else ''
        def _rel(p: str) -> str:
            """将可能的绝对路径转为项目相对路径（匹配 node_list 格式）"""
            if not p:
                return p
            if p.startswith('file:'):
                p = p[5:]
            p = p.replace('\\', '/')
            if __root and p.lower().startswith(__root.lower()):
                p = p[len(__root):]
            return p.lstrip('/')

        # 4. Resolve edge source/target to community keys
        def resolve_key(raw_id, edge_kind, sym_map, file_comm):
            """Resolve an edge endpoint to a community-matching key."""
            if not raw_id:
                return None
            if edge_kind == 'imports':
                key = _rel(raw_id)
                return file_comm.get(key)
            else:  # calls
                # resolve symbol ID → file_path, then match file_path in node_comm
                fpath = sym_map.get(raw_id, '')
                if fpath:
                    fpath_rel = _rel(fpath)
                    if fpath_rel in file_comm:
                        return file_comm[fpath_rel]
                # fallback: try direct lookup (some CALL node_lists may use symbol IDs)
                if raw_id in file_comm:
                    return file_comm[raw_id]
                return None

        # 5. Aggregate cross-community edges
        cross_map = {}  # (source_comm, target_comm) → count
        for edge in all_edges:
            src = edge[0] or ''
            tgt = edge[1] or ''
            if not src or not tgt:
                continue
            src_comm = resolve_key(src, edge_kind, symbol_file_map, node_comm)
            tgt_comm = resolve_key(tgt, edge_kind, symbol_file_map, node_comm)
            if not src_comm or not tgt_comm:
                continue
            if src_comm == tgt_comm:
                continue
            pair = (src_comm, tgt_comm)
            cross_map[pair] = cross_map.get(pair, 0) + 1

        cross_edges = [
            {'sourceCommId': p[0], 'targetCommId': p[1], 'edgeCount': cnt}
            for p, cnt in sorted(cross_map.items(), key=lambda x: -x[1])
        ]

        logger.info("[PERF] getCrossCommunityEdges TOTAL=%.1fms communities=%d crossEdges=%d edges=%d",
                   (time.perf_counter() - t_total) * 1000,
                   len(doc_rows), len(cross_edges), len(all_edges))

        return {'crossEdges': cross_edges}

    # 后台重建任务注册表（rebuildUnified 线程化：同步跑会阻塞事件循环 → health 探活失败被杀）
    _REBUILD_JOBS: dict = {}

    @server.register("analysis.rebuildUnified")
    def rebuild_unified(project_id=None, projectId=None, wait: bool = False):
        """组件统一：清库重算 UNIFIED 组件树（kb-unified-components-plan §5/§7 Stage 2）。

        对指定项目（缺省=全部有分析任务的项目）的最新分析任务重跑
        INCLUDE/CALL 社区 + UNIFIED 对齐合并；旧口径组件数据随重算清除。

        默认后台执行（大项目双线重算 + 合并为 CPU 密集长任务，同步跑会阻塞
        服务事件循环导致 health 探活超时被 supervisor 强杀）：立即返回
        {jobId, status:"running"}，用 analysis.rebuildStatus(jobId) 轮询。
        wait=true 同步执行到底（内部调用/测试用）。
        """
        import threading as _threading
        if not wait:
            job_id = f"rb-{uuid.uuid4().hex[:8]}"
            _REBUILD_JOBS[job_id] = {"status": "running", "projects": [], "done": [], "failed": []}

            def _run_rebuild():
                try:
                    result = _rebuild_unified_impl(server, multi_db, project_id or projectId)
                    _REBUILD_JOBS[job_id].update({"status": "done", "result": result})
                except Exception as e:
                    logger.error(f"[rebuildUnified] job {job_id} failed: {e}")
                    _REBUILD_JOBS[job_id].update({"status": "error", "error": str(e)})

            _threading.Thread(target=_run_rebuild, name=f"rebuild-{job_id}", daemon=True).start()
            return {"jobId": job_id, "status": "running"}

        return _rebuild_unified_impl(server, multi_db, project_id or projectId)

    @server.register("analysis.rebuildStatus")
    def rebuild_status(jobId: str = ""):
        """rebuildUnified 后台任务状态轮询。"""
        if not jobId:
            raise ValueError("jobId is required")
        job = _REBUILD_JOBS.get(jobId)
        if not job:
            return {"status": "unknown"}
        return dict(job)

    def _rebuild_unified_impl(server, multi_db, project_id=None):
        from topoone.engine.store.analysis_store import AnalysisStore
        from topoone.engine.store.task_store import TaskStore
        from topoone.plugins.community.community_analysis import analyze_communities
        from topoone.plugins.community.unified_merge import analyze_unified
        from topoone.config import (COMMUNITY_MIN_NODE_INCLUDE,
                                    COMMUNITY_MIN_NODE_CALL)

        t_store = TaskStore(multi_db.main_db)
        if pid := project_id:
            project_ids = [pid]
        else:
            rows = t_store._db.execute(
                "SELECT DISTINCT project_id FROM analysis_tasks ORDER BY project_id"
            ).fetchall()
            project_ids = [r["project_id"] for r in rows]

        results = []
        from topoone.engine.view_service import resolve_view_task_ids
        for pid in project_ids:
            try:
                # 重建对象 = 基线视图挂载任务（与对外 catalog/model 展示口径严格一致）
                tids = resolve_view_task_ids(multi_db, pid)
                if not tids:
                    results.append({"project_id": pid,
                                    "skipped": "baseline view has no mounted tasks"})
                    continue
                pdb = multi_db.get_project_db(pid)
                store = AnalysisStore(pdb)
                for tid in tids:
                    inc = analyze_communities(tid, store, "INCLUDE",
                                              min_node_cnt=COMMUNITY_MIN_NODE_INCLUDE)
                    call = analyze_communities(tid, store, "CALL",
                                               min_node_cnt=COMMUNITY_MIN_NODE_CALL)
                    uni = analyze_unified(tid, store)
                    results.append({
                        "project_id": pid, "task_id": tid,
                        "include": inc.get("community_count"),
                        "call": call.get("community_count"),
                        "unified": uni.get("community_count"),
                        "levels": uni.get("levels"),
                    })
            except Exception as e:
                results.append({"project_id": pid, "error": str(e)})
        return {"success": True, "rebuilt": results}


    @server.register("analysis.getExternalStats")
    def get_external_stats(task_id=None, taskId=None):
        """获取外部依赖/调用统计: 从已有数据聚合，不需社区分析"""
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        t_total = time.perf_counter()

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)

        # ── 诊断: 打印任务和项目信息 ──
        try:
            node_kinds = project_db.execute(
                "SELECT kind, COUNT(*) FROM graph_node WHERE task_id=? GROUP BY kind",
                (tid,)
            ).fetchall()
            edge_kinds = project_db.execute(
                "SELECT kind, COUNT(*) FROM graph_edge WHERE task_id=? GROUP BY kind",
                (tid,)
            ).fetchall()
            logger.info("[DIAG] getExternalStats task=%s pid=%s graph_node=%s graph_edge=%s",
                       tid, pid, dict(node_kinds), dict(edge_kinds))
        except Exception as e:
            logger.warning(f"[DIAG] getExternalStats schema query failed: {e}")

        # 1. 外部依赖 — 导入名无对应 INCLUDE 边的（按文件匹配）
        #    避免相关子查询: 先批量加载已解析导入，再 Python 差集过滤
        dep_rows = []
        import_count = 0
        resolved_count = 0
        t_dep_sql = time.perf_counter()
        try:
            # 加载所有 import 节点
            import_nodes = project_db.execute(
                "SELECT name, file_path FROM graph_node WHERE task_id = ? AND kind = 'import'",
                (tid,)
            ).fetchall()
            import_count = len(import_nodes)

            # 加载已解析的 (source_file, module) 对
            resolved_pairs = set()
            edge_rows = project_db.execute(
                """SELECT gn_src.file_path, json_extract(ge.metadata, '$.module')
                   FROM graph_edge ge
                   JOIN graph_node gn_src ON gn_src.id = ge.source_id AND gn_src.task_id = ge.task_id
                   WHERE ge.task_id = ? AND ge.kind = 'imports'""",
                (tid,)
            ).fetchall()
            resolved_count = len(edge_rows)
            for er in edge_rows:
                fp = er[0] or ""
                mod = er[1] or ""
                if fp and mod:
                    resolved_pairs.add((fp, mod))

            # 过滤：未出现在 resolved_pairs 中的 import 视为外部依赖
            for imp in import_nodes:
                pkg = imp[0] or ""
                fp = imp[1] or ""
                if not pkg:
                    continue
                if (fp, pkg) not in resolved_pairs:
                    dep_rows.append((pkg, fp))
        except Exception as e:
            logger.error(f"[DIAG] getExternalStats deps query failed: {e}", exc_info=True)
            dep_rows = []
        logger.info("[PERF] getExternalStats deps_sql imported=%d resolved_edges=%d external=%d %.1fms",
                   import_count, resolved_count, len(dep_rows),
                   (time.perf_counter() - t_dep_sql) * 1000)

        dep_map = {}
        for row in dep_rows:
            pkg = row[0] or ""
            fp = row[1] or ""
            if not pkg:
                continue
            if pkg not in dep_map:
                dep_map[pkg] = {"package": pkg, "fileCount": 0, "files": []}
            dep_map[pkg]["fileCount"] += 1
            # 去重（同文件可能多次 import 同一包）
            if fp not in dep_map[pkg]["files"]:
                dep_map[pkg]["files"].append(fp)

        external_deps = sorted(dep_map.values(), key=lambda x: -x["fileCount"])
        # 限制返回前 100
        external_deps = external_deps[:100]

        # 2. 外部调用 — 未解析的调用边
        calls_sql = """
            SELECT ge.source_id, gn.file_path, ge.metadata
            FROM graph_edge ge
            LEFT JOIN graph_node gn ON gn.id = ge.source_id AND gn.task_id = ge.task_id
            WHERE ge.task_id = ? AND ge.kind = 'calls' AND ge.target_id = ''
        """
        t_call_sql = time.perf_counter()
        try:
            call_rows = project_db.execute(calls_sql, (tid,)).fetchall()
        except Exception as e:
            logger.error(f"[DIAG] getExternalStats calls query failed: {e}", exc_info=True)
            call_rows = []
        logger.info("[PERF] getExternalStats calls_sql rows=%d %.1fms", len(call_rows), (time.perf_counter() - t_call_sql) * 1000)

        project_root = ""
        try:
            root_row = multi_db.main_db.execute(
                "SELECT root_path FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            if root_row and root_row["root_path"]:
                project_root = os.path.abspath(root_row["root_path"])
        except Exception:
            pass

        call_map = {}
        for row in call_rows:
            sid = row[0] or ""
            fp = row[1] or sid
            meta_str = row[2] or "{}"
            try:
                meta = json.loads(meta_str)
            except Exception:
                meta = {}
            call_name = meta.get("expression") or meta.get("callee") or ""
            if not call_name:
                # fallback: use source file abbreviation for readability
                if sid.startswith("file:"):
                    basename = os.path.basename(sid)
                    # __init__.py / __init__.ts → 用父目录名代替，避免大量调用归入无意义名称
                    if basename in ("__init__.py", "__init__.ts", "__init__.js",
                                    "index.ts", "index.js", "index.tsx", "index.jsx"):
                        parent_dir = os.path.basename(os.path.dirname(sid.replace("file:", "", 1)))
                        call_name = parent_dir or basename
                    else:
                        call_name = basename
                elif fp and fp != sid:
                    call_name = os.path.relpath(fp, project_root) if os.path.isabs(fp) else fp
                else:
                    call_name = sid[:16]
            if call_name not in call_map:
                call_map[call_name] = {"name": call_name, "count": 0, "files": []}
            call_map[call_name]["count"] += 1
            if fp not in call_map[call_name]["files"]:
                call_map[call_name]["files"].append(fp)

        external_calls = sorted(call_map.values(), key=lambda x: -x["count"])
        external_calls = external_calls[:100]

        # 总数统计
        total_ext_deps = len(dep_rows)
        unique_ext_dep_files = len(set(row[1] for row in dep_rows if row[1]))
        total_ext_calls = len(call_rows)
        unique_ext_call_files = len(set(
            row[1] if row[1] else row[0] for row in call_rows
        ))

        # 附加: 文件 → L0 社区归属映射 (用于前端外部依赖/调用 graph 视图)
        try:
            t_comm = time.perf_counter()

            def _build_file_comm(edge_type):
                """file_path → [{communityId}] for given edge_type's L0 communities"""
                rows = project_db.execute(
                    "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv='L0'",
                    (tid, edge_type)
                ).fetchall()
                file_comm = {}
                for row in rows:
                    cid = row[0]
                    try:
                        nodes = json.loads(row[1]) if row[1] else []
                    except Exception:
                        nodes = []
                    for fp in nodes:
                        if not fp:
                            continue
                        if fp not in file_comm:
                            file_comm[fp] = []
                        already = any(c['communityId'] == cid for c in file_comm[fp])
                        if not already:
                            file_comm[fp].append({'communityId': cid})
                return file_comm

            include_file_comm = _build_file_comm('INCLUDE')
            call_file_comm    = _build_file_comm('CALL')

            # 批量加载社区 LLM 名称
            name_rows = project_db.execute(
                "SELECT comm_id, name FROM community_llm_results WHERE task_id=? AND comm_lv='L0'",
                (tid,)
            ).fetchall()
            comm_names = {row[0]: row[1] for row in name_rows if row[1]}

            def _inject_communities(items, file_comm):
                for item in items:
                    item_files = item.get('files', [])
                    item_comms = []
                    seen_cids = set()
                    for f in item_files:
                        for c in file_comm.get(f, []):
                            cid = c['communityId']
                            if cid not in seen_cids:
                                seen_cids.add(cid)
                                item_comms.append({
                                    'communityId': cid,
                                    'name': comm_names.get(cid) or None,
                                })
                    item['communities'] = item_comms

            _inject_communities(external_deps, include_file_comm)
            _inject_communities(external_calls, call_file_comm)

            logger.info("[PERF] getExternalStats community map build=%.1fms",
                       (time.perf_counter() - t_comm) * 1000)
        except Exception as e:
            logger.warning(f"[getExternalStats] community mapping failed: {e}")

        logger.info("[PERF] getExternalStats TOTAL=%.1fms deps=%d calls=%d",
                   (time.perf_counter() - t_total) * 1000,
                   total_ext_deps, total_ext_calls)

        return {
            'externalDeps': external_deps,
            'externalCalls': external_calls,
            'totalExternalDeps': total_ext_deps,
            'uniqueExternalDepFiles': unique_ext_dep_files,
            'totalExternalCalls': total_ext_calls,
            'uniqueExternalCallFiles': unique_ext_call_files,
        }

    @server.register("analysis.getCommunityNodeLists")
    def get_community_node_lists(task_id=None, taskId=None, edge_type=None, edgeType=None,
                                  comm_lv=None, commLv=None):
        """返回指定层级+edge_type 下所有社区的文件路径列表。
        返回格式: { communityId: [filePath, ...] }"""
        tid = task_id or taskId
        et = edge_type or edgeType or 'UNIFIED'
        lv = comm_lv or commLv
        if not tid or not lv:
            raise ValueError("task_id and comm_lv are required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])

        rows = project_db.execute(
            "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=?",
            (tid, et, lv)
        ).fetchall()
        result = {}
        for row in rows:
            cid = row[0]
            try:
                nodes = json.loads(row[1]) if row[1] else []
            except Exception:
                nodes = []
            result[cid] = [str(n) for n in nodes if n]
        return result

    @server.register("analysis.getCommunityFileGraph")
    def get_community_file_graph(task_id=None, taskId=None, edge_type=None, edgeType=None,
                                  comm_id=None, commId=None):
        """返回叶子社区的文件级图数据（节点 + 边），来自 graph_doc 的 node_list / edge_list。"""
        tid = task_id or taskId
        et = edge_type or edgeType or 'UNIFIED'
        cid = comm_id or commId
        if not tid or not cid:
            raise ValueError("task_id and comm_id are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        row = project_db.execute(
            "SELECT node_list, edge_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id=?",
            (tid, et, cid)
        ).fetchone()
        if not row:
            return {"nodes": [], "edges": []}
        file_nodes = set()
        try:
            raw_nodes = json.loads(row["node_list"]) if row["node_list"] else []
            file_nodes = {str(n) for n in raw_nodes if n}
        except Exception:
            pass
        file_edges = []
        try:
            raw_edges = json.loads(row["edge_list"]) if row["edge_list"] else []
            for e in raw_edges:
                src = str(e.get("source", ""))
                tgt = str(e.get("target", ""))
                if src and tgt:
                    file_edges.append({"source": src, "target": tgt,
                                       "direction": e.get("direction", "")})
        except Exception:
            pass
        nodes = []
        for fp in sorted(file_nodes):
            fname = fp.replace('\\', '/').rstrip("/").split("/")[-1] if "/" in fp.replace('\\', '/') else fp
            nodes.append({"id": fp, "label": fname, "filePath": fp})
        return {"nodes": nodes, "edges": file_edges}

    # ==================== 架构 Agent 操作 ====================

