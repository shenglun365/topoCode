"""Semantic Data Assets — architect 自持语义数据资产提取/检索服务。

语义资产按「类别(关切维度) × 抽象粒度(离代码远近)」二维正交分类：
  类别 kind:
    - structure : 结构(数据/状态)      - behavior : 行为(流程)
    - rule      : 规则(决策/约束)      - contract : 契约(接口/交互)
  粒度 level(越低越贴近代码实现):
    - high   : 概念/业务级(domain_entity / business_process / business_rule / business_contract)
    - medium : 逻辑/设计级(data_structure / processing_flow / control_logic / service_contract)
    - low    : 实现/代码级(concrete_type / call_chain / branch_logic / message_contract)

设计要点(结合最新代码结构):
  - 符号数据源: codegraph `.codegraph/codegraph.db`(提取前 `codegraph sync` 保鲜)，
    缺失时降级为轻量文件扫描; KB `architecture.model` 仅作组件归属/baseline 上下文。
  - LLM 通道: 复用 req_agent.llm_sync(经 KbGateway 转主后端)。LLM 不可用 → 启发式降级
    (L 级确定性映射/名=符号名、描述=docstring/签名摘要)，AST 锚点始终取真实 codegraph 节点。
  - 粒度策略: L 级确定性提取(零 LLM 成本，代码事实层)；M 级 LLM 按组件归纳(逻辑组织层)；
    H 级按需聚合(业务功能模块层，从 M/L 资产 + 跨组件依赖图合成，锚定下级防漂移)。
  - AST 关联: LLM 以符号名引用 → 服务端按符号表解析为真实 AstNodeRef(file/symbol/
    kind/startLine/endLine)，杜绝臆造行号。
  - 增量: 同范围重提 → src_hash 比对，change ∈ same|added|modified，旧资产标 stale。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .common import _ts, err, ok
from . import store
from . import asset_tools  # noqa: F401  (模块级导入触发 asset.* 工具注册)

logger = logging.getLogger(__name__)
from .sem.taxonomy import DYNAMIC_KINDS, SEMANTIC_CATEGORY, SEMANTIC_KINDS, SEMANTIC_LEVELS, STATIC_KINDS, _AST_KIND_MAP, _CAT_CODE, _GRAN_CODE, _KIND_CODE, _KIND_LABEL, _LEVEL_KIND_FORM, _NODE_COLS, _SCHEMA_KIND_TO_LLM, _id_prefix
from .sem.paths import _norm_path, _stable_id, project_id_for, resolve_root
from .sem.codegraph import _cg_sample_paths, _open_cg, _query_edges, _query_nodes, cg_dir, ensure_synced
from .sem.scope import _asset_scope_membership, _comm_components, _comm_files, _comm_files_ex, _comm_match, _file_to_components, resolve_scope_files
from .sem.incremental import _AST_CACHE_VERSION, _anchor_hashes, _cache_content_hash, _canonical_key, _file_md5
from .sem.context import _CONTAINER_KINDS, _REF_EDGE_KINDS, _collect_impl_details, _collect_via_cache, _contains_edges, _cross_file_edges_text, _edge_lines, _fetch_impl_for_file, _impl_block, _impl_from_kb, _impl_from_row, _kb_parse_file, _local_parse_impl, _norm_cache_symbol, _ordered_call_lines, _peek_docstring, _peek_docstring_at_line, _rebuild_edges_from_refs, _scan_live, _symbol_block, build_symbol_table, collect_context
from .sem.anchors import _attach_step_refs, _node_index, _node_to_ref, _resolve_symbol_node, _symbol_tail, resolve_ast_refs
from .sem.engine import MainKbEditRejected, _AGG_BATCH, _AGG_MAX_ASSETS_PER_LEAF, _API_NAME_PREFIXES, _API_SIG_TOKENS, _ASSET_EXPECTED_ANCHOR_KIND, _COMP_FILE_MAP_TTL, _CONFIG_ACCESS_SIG, _CONFIG_CARRIER_NAMES, _CTX_OVERFLOW_MARKS, _DERIVED_EDGE_CACHE, _DERIVED_EDGE_TTL, _DERIVE_EDGE_KINDS, _DERIVE_EDGE_LIMIT, _EDGE_SEMANTIC, _ENHANCE, _HIGH_SCHEMA, _IMPL_KIND_CAP, _KIND_ALIASES, _LEVEL_ALIASES, _LINE_NOTE_MAX_LINES, _LN_MAX_DEPTH, _PURGE_REQ_REF_TYPES, _RECONCILE_AT, _RECONCILE_INTERVAL, _SA_ID_RE, _aggregate_high, _aggregate_high_best_effort, _aggregate_one_batch, _anchor_symbols, _asset_anchor_basis, _asset_anchor_kind_ok, _branch_dense, _branches_from_impl, _brief_grounded, _cached_derived_edges, _callee_names, _cg_contains_expand, _cg_edge_evidence, _cg_node_file_map, _cg_symbol_to_node, _check_main_kb_policy, _comp_file_map_cache, _component_asset_ids, _component_file_map, _component_order_map, _config_carrier_signal, _constants_from_impl, _derive_indirect_edges, _derive_project_edges, _derive_project_edges_kb, _derive_relations_from_edges, _enhance_state, _enhance_worker, _fields_from_node, _fields_from_source, _graph_node_detail, _grouped_search_items, _heuristic_extract_primary, _high_asset_text, _high_asset_text_for_comp, _impact_analysis, _impact_of_purge, _impl_for_file, _inherit_ast_refs_from_aggregates, _inherit_names, _is_contract_boundary_node, _is_ctx_overflow, _is_noise_line, _is_route_handler, _key_lines, _lazy_reconcile, _leaf_components, _line_note_context, _link_parent, _mark_invalidated, _member_fields_from_edges, _merge_high_details, _merge_relation, _n_hop_subgraph, _node_ids_for_files, _normalize_kind, _normalize_level, _postorder_component_nodes, _primary_kind_for_node, _pseudo_source_snippet, _relation_target_index, _relations_from_routes, _req_asset_ids, _resolve_extract_levels, _resolve_import, _resolve_relation_target, _save_assets, _scope, _structural_pseudo, api_aggregate_high, api_asset_diagram, api_batch, api_detail, api_edge_notes, api_enhance_desc, api_enhance_desc_status, api_extract, api_graph, api_handle_stale, api_impact, api_in_edges, api_line_notes, api_mappings, api_node_brief, api_asset_desc, api_pseudo, api_purge_semantic, api_reconcile, api_refresh, api_search, api_semantic_stats, api_source_snippet, api_status, batch_manage, changed_files, context_block_for, detail, edit_asset_desc, extract_scope, generate_edge_notes, generate_line_notes, generate_node_brief, generate_node_briefs_batch, generate_pseudo, handle_stale_asset, invalidate_assets_for_files, mappings, merge_assets, node_briefs_after_extract, probe_impact, purge_semantic_assets, reconcile_semantic, referencing_assets, refresh_scope, register_scope_refs, rename_asset, save_agent_assets, search, semantic_graph, split_asset
from .sem import router

from .sem import router  # 实例驻留 sem/__init__（路由随 sem 模块就地注册）



# ── REST ──────────────────────────────────────────────────────

# ── 就地认知编辑端点（plan-C-M0 §7.2；R5: main-KB 拒绝→深链，standalone 直过） ──

def _run_cognitive_edit(fn, *args, **kwargs):
    """认知编辑统一错误面：MainKbEditRejected → 409+深链；ValueError → 400。"""
    try:
        return ok(fn(*args, **kwargs))
    except MainKbEditRejected as e:
        return JSONResponse(status_code=409, content={
            "code": 409, "message": str(e),
            "data": {"mainKb": True, "kbProjectId": e.kb_project_id,
                     "deepLink": e.deep_link},
        })
    except ValueError as e:
        return err(400, str(e))


@router.post("/semantic/assets/rename")
async def api_asset_rename(request: Request):
    """资产改名（认知层编辑 → overlay 审计；旧名入 renamedFrom/nameAlias）。

    body: {assetId, newName, author?}
    """
    body = await request.json()
    return _run_cognitive_edit(
        rename_asset, (body.get("assetId") or "").strip(),
        body.get("newName") or "", (body.get("author") or "").strip())


@router.post("/semantic/assets/merge")
async def api_asset_merge(request: Request):
    """资产合并（目标锚点并入 intoId；目标行 deleted + mergedInto 溯源）。

    body: {intoId, targetIds[], targetName?, author?}
    """
    body = await request.json()
    return _run_cognitive_edit(
        merge_assets, (body.get("intoId") or "").strip(),
        list(body.get("targetIds") or []),
        (body.get("targetName") or "").strip(), (body.get("author") or "").strip())


@router.post("/semantic/assets/split")
async def api_asset_split(request: Request):
    """资产拆分（按 anchorKeys=file:symbol 锚点组拆出新资产；原行 deleted + splitInto）。

    body: {assetId, parts[{name, anchorKeys[], desc?}], author?}
    """
    body = await request.json()
    return _run_cognitive_edit(
        split_asset, (body.get("assetId") or "").strip(),
        list(body.get("parts") or []), (body.get("author") or "").strip())
