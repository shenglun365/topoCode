"""semantic_assets 拆分模块（A1 修正：纯移动，逻辑零改动）。

原 semantic_assets.py 5555 行 god-file 按段拆出；本模块由构建脚本生成段内容，
跨模块引用为显式 import。每步拆分均跑 28 个后端测试文件保护。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import store
from ..common import _ts, err, ok  # noqa: F401

logger = logging.getLogger(__name__)

from .paths import _norm_path


# ── 范围解析 ──────────────────────────────────────────────────

def _comm_components(root: str, project: Optional[str] = None) -> List[dict]:
    """组件全集：组件目录(architecture.catalog)为主，架构模型兜底（去重 by id）。"""
    from ..common import build_component_catalog, build_architecture_model
    comps: List[dict] = []
    seen: set = set()
    for fetch in (lambda: build_component_catalog(root, project),
                  lambda: build_architecture_model(root, project)):
        try:
            for c in fetch().get("components") or []:
                cid = c.get("id") or ""
                if cid and cid not in seen:
                    seen.add(cid)
                    comps.append(c)
        except Exception as e:
            logger.warning("[semantic] 组件来源解析失败: %s", e, exc_info=True)
    return comps


def _comm_match(comps: List[dict], comm_key: str) -> Tuple[Optional[dict], List[dict]]:
    """按 key 匹配组件：精确 id → 精确名称 → 忽略大小写 → 唯一子串包含。

    返回 (命中组件|None, 子串多义时的候选列表)。多义不猜（保真：宁可返回候选）。
    """
    key = (comm_key or "").strip()
    if not key:
        return None, []
    for c in comps:
        if c.get("id") == key:
            return c, []
    for c in comps:
        if (c.get("name") or "") == key:
            return c, []
    low = key.lower()
    for c in comps:
        if str(c.get("id") or "").lower() == low or str(c.get("name") or "").lower() == low:
            return c, []
    subs = [c for c in comps
            if low and (low in str(c.get("name") or "").lower()
                        or low in str(c.get("id") or "").lower()
                        or str(c.get("name") or "").lower() in low)]
    if len(subs) == 1:
        return subs[0], []
    return None, subs


def _comm_files_ex(root: str, comm_key: str, project: Optional[str] = None
                   ) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    """组件范围 → (文件集合, 未命中诊断)。

    命中 → (files, None)；未命中 → ([], {error, candidates:[{id,name}…]})——
    诊断随提取结果透传给 agent（如实报告失败原因与可选组件，禁止静默空结果）。
    """
    comps = _comm_components(root, project)
    hit, subs = _comm_match(comps, comm_key)
    if hit:
        files = [_norm_path(f) for f in (hit.get("owns") or []) if f]
        logger.info("[semantic] comm %s 命中组件 %s(%s), 文件数=%d",
                    comm_key, hit.get("name"), hit.get("id"), len(files))
        return files, None
    candidates = [{"id": c.get("id"), "name": c.get("name")}
                  for c in (subs or comps)[:12]]
    why = "组件目录与模型均未命中" if not subs else "名称模糊命中多个组件，需精确组件ID"
    logger.warning("[semantic] comm %s %s, 返回空文件集合(候选 %d 个)",
                   comm_key, why, len(candidates))
    return [], {"error": f"组件范围「{comm_key}」{why}",
                "candidates": candidates}


def _comm_files(root: str, comm_key: str, project: Optional[str] = None) -> List[str]:
    """组件范围 → 文件集合（兼容旧调用点；未命中返回空集合）。"""
    files, _ = _comm_files_ex(root, comm_key, project)
    return files


def resolve_scope_files(root: str, scope_type: str, scope_key: str,
                        files: Optional[List[str]] = None,
                        symbols: Optional[List[str]] = None,
                        project: Optional[str] = None,
                        out: Optional[Dict[str, Any]] = None):
    """范围 → (files, symbols)。comm 解析为文件集合；symbols 保持符号名列表。

    out(可选)：comm 未命中时写入 out["scopeError"]={error, candidates}（诊断透传）。
    """
    st = scope_type or "project"
    if st == "files":
        return [_norm_path(f) for f in (files or []) if f], []
    if st == "symbols":
        return [], [s for s in (symbols or []) if s]
    if st == "comm":
        fs, err_info = _comm_files_ex(root, scope_key, project)
        if out is not None and err_info:
            out["scopeError"] = err_info
        return fs, []
    return [], []  # project: 全量


def _file_to_components(root: str, project: Optional[str]) -> Dict[str, List[str]]:
    """文件 → 拥有它的组件 id 列表(跨 INCLUDE/CALL 两套口径)。
    供 `_save_assets` 把资产按锚点文件归属到所有组件(资产身份=代码，组件是下游投影)。

    ⚠️ _component_file_map 延迟导入：定义在 engine(带 TTL 缓存)，而 engine 顶层
    import 本模块——顶层互相导入会循环。此前重构(e5af8ac)漏改为顶层名字，
    NameError 被 _save_assets 的 try/except 吞成空映射 → 所有资产 meta.scopes
    恒空 → 前端子组件(L1+)分组无资产不显示(实测 topoOne-animation 238 资产
    scopes 全空回归)。
    """
    from .engine import _component_file_map

    out: Dict[str, List[str]] = {}
    for cid, files in _component_file_map(root, project).items():
        for f in files:
            if f not in out:
                out[f] = []
            if cid not in out[f]:
                out[f].append(cid)
    return out


def _asset_scope_membership(ast_refs: List[dict],
                            file_to_comps: Dict[str, List[str]]) -> List[str]:
    """资产锚点文件 → 归属组件 id 集合(去重排序)。无锚点/无归属 → 空。"""
    comps: List[str] = []
    for r in ast_refs or []:
        f = _norm_path(r.get("file") or "")
        for cid in file_to_comps.get(f) or []:
            if cid not in comps:
                comps.append(cid)
    return sorted(comps)


