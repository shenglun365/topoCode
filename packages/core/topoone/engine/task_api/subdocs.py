"""report.* 写方法域 + agent.getConfig（MS5-V1 自 task_manager.py 切分；注册顺序经 task_api/__init__ 锁序）。
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
    @server.register("report.createSubDoc")
    def create_sub_doc(task_id=None, taskId=None, edge_type=None, edgeType=None,
                       comm_id=None, commId=None, title=None, content=None,
                       template_id=None, templateId=None,
                       id=None, docId=None):
        """创建分析报告子文档（写入 ingest 文件，由消费端入库）"""
        from topoone.engine.ingest import write_ingest
        tid = task_id or taskId
        et = edge_type or edgeType or 'UNIFIED'
        cid = comm_id or commId
        tpl = template_id or templateId
        provided_id = id or docId

        if not tid or not title or not content:
            raise ValueError("task_id, title, and content are required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]
        project_root = S.get_project_root(project_id)

        doc_id = provided_id or f"subdoc-{uuid.uuid4().hex[:12]}"
        now = time.strftime('%Y-%m-%d %H:%M:%S')

        data = {
            "project_id": project_id,
            "doc_id": doc_id,
            "task_id": tid,
            "edge_type": et,
            "comm_id": cid,
            "title": title,
            "content": content,
            "template_id": tpl,
            "created_at": now,
            "updated_at": now,
        }
        write_ingest(project_id, "subdoc", data, data_dir=multi_db.data_dir)

        return {'id': doc_id}

    @server.register("report.listSubDocs")
    def list_sub_docs(task_id=None, taskId=None, comm_id=None, commId=None):
        """列出报告子文档"""
        tid = task_id or taskId
        cid = comm_id or commId

        if not tid:
            raise ValueError("task_id is required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]
        project_db = multi_db.get_project_db(project_id)

        if cid:
            rows = project_db.execute(
                "SELECT id, title, template_id, created_at, updated_at FROM report_subdocs WHERE task_id=? AND comm_id=? ORDER BY created_at DESC",
                (tid, cid)
            ).fetchall()
        else:
            rows = project_db.execute(
                "SELECT id, title, template_id, created_at, updated_at FROM report_subdocs WHERE task_id=? ORDER BY created_at DESC",
                (tid,)
            ).fetchall()

        return [
            {
                'id': row[0],
                'title': row[1],
                'template_id': row[2],
                'created_at': row[3],
                'updated_at': row[4],
            }
            for row in rows
        ]

    def _find_subdoc_project(multi_db, sub_doc_id):
        """
        查找子文档所属项目 ID。
        优先级：ID 前缀推断 → doc_project_map 缓存表 → 全量遍历（兜底）。
        """
        # 1. 快速路径：ID 前缀推断
        for prefix in ("overall-", "subdoc-"):
            if sub_doc_id.startswith(prefix):
                task_id = sub_doc_id[len(prefix):]
                try:
                    task = multi_db.main_db.fetchone(
                        "SELECT project_id FROM analysis_tasks WHERE id=?", (task_id,)
                    )
                    if task:
                        pid = task["project_id"]
                        pdb = multi_db.get_project_db(pid)
                        row = pdb.fetchone(
                            "SELECT id, task_id, edge_type, comm_id, title, content, template_id, created_at, updated_at FROM report_subdocs WHERE id=?",
                            (sub_doc_id,)
                        )
                        if row:
                            return pid, row
                except Exception:
                    pass
        # 2. 查 doc_project_map 映射表
        try:
            doc_row = multi_db.main_db.fetchone(
                "SELECT project_id FROM doc_project_map WHERE doc_id=?", (sub_doc_id,)
            )
            if doc_row:
                pid = doc_row["project_id"]
                pdb = multi_db.get_project_db(pid)
                row = pdb.fetchone(
                    "SELECT id, task_id, edge_type, comm_id, title, content, template_id, created_at, updated_at FROM report_subdocs WHERE id=?",
                    (sub_doc_id,)
                )
                if row:
                    return pid, row
        except Exception:
            pass
        # 3. 兜底：全量遍历所有项目查找
        projects = multi_db.main_db.fetchall("SELECT id FROM projects")
        for proj in projects:
            pid = proj["id"]
            try:
                pdb = multi_db.get_project_db(pid)
                row = pdb.fetchone(
                    "SELECT id, task_id, edge_type, comm_id, title, content, template_id, created_at, updated_at FROM report_subdocs WHERE id=?",
                    (sub_doc_id,)
                )
                if row:
                    # 写入缓存，后续秒回
                    try:
                        multi_db.main_db.execute(
                            "INSERT OR IGNORE INTO doc_project_map (doc_id, project_id, task_id) VALUES (?, ?, ?)",
                            (sub_doc_id, pid, row["task_id"] or ""),
                        )
                    except Exception:
                        pass
                    return pid, row
            except Exception:
                continue
        return None, None

    @server.register("report.getSubDoc")
    def get_sub_doc(sub_doc_id=None, subDocId=None):
        """获取子文档内容"""
        sid = sub_doc_id or subDocId
        if not sid:
            raise ValueError("sub_doc_id is required")

        pid, row = _find_subdoc_project(multi_db, sid)
        if row:
            return {
                'id': row['id'],
                'task_id': row['task_id'],
                'edge_type': row['edge_type'],
                'comm_id': row['comm_id'],
                'title': row['title'],
                'content': row['content'],
                'template_id': row['template_id'],
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
            }

        raise ValueError(f"SubDoc {sid} not found")

    @server.register("report.updateSubDoc")
    def update_sub_doc(sub_doc_id=None, subDocId=None, title=None, content=None):
        """更新子文档"""
        sid = sub_doc_id or subDocId
        if not sid:
            raise ValueError("sub_doc_id is required")

        pid, _ = _find_subdoc_project(multi_db, sid)
        if pid:
            pdb = multi_db.get_project_db(pid)
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            if content is not None:
                pdb.execute(
                    "UPDATE report_subdocs SET content=?, updated_at=? WHERE id=?",
                    (content, now, sid)
                )
            if title is not None:
                pdb.execute(
                    "UPDATE report_subdocs SET title=?, updated_at=? WHERE id=?",
                    (title, now, sid)
                )
            pdb.commit()
            return {'ok': True}

        raise ValueError(f"SubDoc {sid} not found")

    @server.register("report.deleteSubDoc")
    def delete_sub_doc(sub_doc_id=None, subDocId=None):
        """删除子文档"""
        sid = sub_doc_id or subDocId
        if not sid:
            raise ValueError("sub_doc_id is required")

        pid, _ = _find_subdoc_project(multi_db, sid)
        if pid:
            pdb = multi_db.get_project_db(pid)
            pdb.execute("DELETE FROM report_subdocs WHERE id=?", (sid,))
            pdb.commit()
            # 同步删除 doc_project_map
            try:
                multi_db.main_db.execute(
                    "DELETE FROM doc_project_map WHERE doc_id=?", (sid,)
                )
            except Exception:
                pass
            return {'ok': True}

        raise ValueError(f"SubDoc {sid} not found")

    @server.register("agent.getConfig")
    def get_agent_config():
        """返回当前 Agent 路由、技能、工具的元数据"""
        # 从 DB 读取已注册的技能，fallback 到硬编码列表
        skills = []
        try:
            rows = multi_db.main_db.execute(
                "SELECT name, description, category, config FROM skill_configs WHERE enabled = 1 ORDER BY name"
            ).fetchall()
            for r in rows:
                name = r["name"] if isinstance(r, dict) else r[0]
                desc = r["description"] if isinstance(r, dict) else r[1]
                config_str = r["config"] if isinstance(r, dict) else r[3]
                steps = 1
                if config_str:
                    try:
                        import json
                        cfg = json.loads(config_str)
                        steps = cfg.get("steps", 1)
                    except Exception:
                        pass
                skills.append({"name": name, "description": desc or "", "steps": steps})
        except Exception:
            skills = [
                {"name": "skill_generate_arch_overview", "description": "Generate architecture overview", "steps": 3},
                {"name": "skill_analyze_community", "description": "Analyze a community in depth", "steps": 4},
                {"name": "skill_fix_mermaid", "description": "Fix Mermaid diagram syntax", "steps": 2},
                {"name": "skill_fix_plantuml", "description": "Fix PlantUML diagram syntax", "steps": 2},
                {"name": "skill_fix_diagram", "description": "Fix generic diagram syntax", "steps": 2},
                {"name": "skill_explain_arch_pattern", "description": "Explain architecture pattern", "steps": 3},
                {"name": "skill_compare_arch", "description": "Compare architecture", "steps": 4},
                {"name": "skill_recommend_refactor", "description": "Recommend refactoring", "steps": 3},
                {"name": "skill_validate_arch_impact", "description": "Validate architecture impact", "steps": 3},
                {"name": "skill_detect_arch_drift", "description": "Detect architecture drift", "steps": 3},
                {"name": "skill_batch_analyze_communities", "description": "Batch analyze communities", "steps": 5},
                {"name": "skill_track_ai_session", "description": "Track AI session", "steps": 2},
                {"name": "skill_audit_changes", "description": "Audit changes", "steps": 3},
            ]
        return {
            "routes": [
                {"action": "overview", "workflow": "OverviewWorkflow", "description": "Generate overall architecture overview document"},
                {"action": "analyze_components", "workflow": "AgenticComponentAnalystWorkflow", "description": "Agent multi-turn component analysis"},
                {"action": "presummary_files", "workflow": "PreSummaryWorkflow", "description": "File pre-summary batch cache"},
            ],
            "skills": skills,
            "tools": [
                {"name": "read_file", "description": "Read source file content", "category": "file", "llm_visible": True},
                {"name": "search_content", "description": "Search file content by pattern", "category": "file", "llm_visible": True},
                {"name": "summarize_file", "description": "Summarize file via LLM", "category": "file", "llm_visible": True},
                {"name": "get_symbol_detail", "description": "Get symbol details", "category": "symbol", "llm_visible": True},
                {"name": "search_symbols", "description": "Search symbols by name", "category": "symbol", "llm_visible": True},
                {"name": "get_symbol_code", "description": "Get symbol source code", "category": "symbol", "llm_visible": True},
                {"name": "get_community_subgraph", "description": "Get community subgraph", "category": "graph", "llm_visible": True},
                {"name": "get_call_chain", "description": "Get call chain graph", "category": "graph", "llm_visible": True},
                {"name": "get_ast_node", "description": "Get AST node details", "category": "graph", "llm_visible": True},
                {"name": "get_edge_detail", "description": "Get edge details", "category": "edge", "llm_visible": True},
            ],
        }

    logger.info("[task_manager] all analysis.* methods registered")

