"""组件目录统一适配层（批 0-2：五处 owns 匹配收编单源）。

消费方：sem/engine._component_file_map / sem/scope._comm_components /
arch_routes/project._by_kb_components / sem/compare（基线对比归属）/
arch_routes/asset_framework.coverage（覆盖度统计）。

语义统一：
- 来源：KB architecture.catalog 为主（唯一 id + parentId + owns 完整组件树），
  architecture.model 兜底（拍平、id 可能重复——仅目录缺失时降级），按 id 去重；
- 归属匹配 owners_of：归一化路径 精确/双向后缀对齐——git 工作目录相对路径
  vs KB 镜像根相对路径口径差异（原 compare._owner_of 与 project._owns_match
  实证）；父子重叠时最深（最具体）组件优先；
- hierLevel：parentId 链推导深度（0=根），补齐 KB 端缺失的层级信息；
- TTL 进程缓存：目录极少变化（收编原 engine._comp_file_map_cache 模式）。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_CATALOG_TTL = 60.0
_cache: Dict[Tuple[str, str], Tuple[float, dict]] = {}  # (root, project) -> (ts, cat)


def _catalog_source() -> str:
    """组件目录源开关（数据主权批B）：arch_only(默认, 自有社区组件) | kb | merge。

    用户裁决：KB 与 architect 并行各存组件视角、互不影响——默认读自管
    arch_components(community_group 作业产物)；kb/merge 为兼容/实验位。
    """
    try:
        from .. import ctx
        row = ctx.db().fetchone(
            "SELECT value FROM arch_settings WHERE key = 'arch.catalogSource'")
        if row and row.get("value"):
            return (json.loads(row["value"]) or {}).get("mode") or "arch_only"
    except Exception:  # noqa: BLE001
        pass
    return "arch_only"


def _fetch_arch_components(project: Optional[str]) -> List[dict]:
    """自管组件目录（最新 rev）→ catalog 组件形状（{id,name,owns,parentId}）。"""
    if not project:
        return []
    try:
        from ..store.graph import ComponentStore
        rev = ComponentStore.latest_rev(project)
        if not rev:
            return []
        return ComponentStore.list_rev(project, rev)
    except Exception as e:  # noqa: BLE001
        logger.warning("[catalog] 自管组件读取失败: %s", e)
        return []


def _fetch_catalog(root: Optional[str], project: Optional[str]) -> Tuple[List[dict], str, str]:
    """→ (components, source, note)。source: arch | catalog | model | merged | empty。

    源开关 _catalog_source()：arch_only → 仅自管社区组件（KB 缺席照常）；
    kb → 既有 KB 双源链；merge → arch 优先并集（按 id 去重，arch 优先）。
    KB 双源合并语义（与原 scope._comm_components 一致）：catalog 与 model
    取并集、按 id 去重（catalog 优先——model 拍平且 id 可能重复，仅补缺）。
    """
    mode = _catalog_source()
    arch_comps = _fetch_arch_components(project) if mode in ("arch_only", "merge") else []
    if mode == "arch_only":
        if arch_comps:
            return arch_comps, "arch", ""
        return [], "empty", "自有组件目录为空(先运行 collect-graph 采集 + community-group 分组)"
    from ..common import build_architecture_model, build_component_catalog
    comps: List[dict] = []
    seen: set = set()
    source = "empty"
    try:
        cat = build_component_catalog(root, project)
        for c in (cat.get("components") or []):
            cid = c.get("id")
            if cid and cid not in seen:
                seen.add(cid)
                comps.append(c)
        if comps:
            source = "catalog"
    except Exception as e:
        logger.warning("[catalog] architecture.catalog 失败: %s", e)
    try:
        model = build_architecture_model(root, project)
        extra = 0
        for c in (model.get("components") or []):
            cid = c.get("id")
            if cid and cid not in seen:
                seen.add(cid)
                comps.append(c)
                extra += 1
        if extra:
            source = "merged" if source == "catalog" else "model"
    except Exception as e:
        logger.warning("[catalog] architecture.model 兜底失败: %s", e)
    if mode == "merge" and arch_comps:
        merged = list(arch_comps)
        seen = {c.get("id") for c in arch_comps}
        for c in comps:
            if c.get("id") and c["id"] not in seen:
                merged.append(c)
        comps = merged
        source = f"{source}+arch" if source != "empty" else "arch"
    note = "" if comps else "KB 无组件数据（未关联基线或调用失败）"
    return comps, source, note


def _depths(by_id: Dict[str, dict]) -> Dict[str, int]:
    """parentId 链深度（0=根；环防护）。"""
    depth: Dict[str, int] = {}

    def _d(cid: str, seen: Tuple[str, ...] = ()) -> int:
        if cid in depth:
            return depth[cid]
        if cid in seen:
            return 0
        pid = (by_id.get(cid) or {}).get("parentId") or ""
        d = 0 if pid not in by_id else _d(pid, seen + (cid,))
        depth[cid] = d
        return d

    for cid in by_id:
        _d(cid)
    return depth


def component_catalog(root: Optional[str] = None, project: Optional[str] = None,
                      *, force: bool = False) -> dict:
    """统一组件目录 → {components, byId, depths, ownIndex, fileOwner, source, note}。

    - components：原样组件 + hierLevel（父链深度，0=根）；
    - ownIndex：[(归一化owns路径, cid)] 扁平索引（owners_of 快速匹配）；
    - fileOwner：归一化路径 → 最深组件 id；
    - 空目录为合法降级态（source='empty'，note 带原因），不抛异常。
    """
    from .paths import _norm_path
    key = (root or "", project or "")
    now = time.time()
    if not force:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CATALOG_TTL:
            return hit[1]
    comps, source, note = _fetch_catalog(root, project)
    by_id = {c["id"]: c for c in comps}
    depths = _depths(by_id)
    for c in comps:
        c["hierLevel"] = depths.get(c["id"], 0)
    own_index: List[Tuple[str, str]] = []
    file_owner: Dict[str, str] = {}
    for cid, c in by_id.items():
        for f in (c.get("owns") or []):
            nf = _norm_path(f)
            if not nf:
                continue
            own_index.append((nf, cid))
            cur = file_owner.get(nf)
            if cur is None or depths[cid] > depths[cur]:
                file_owner[nf] = cid
    cat = {"components": comps, "byId": by_id, "depths": depths,
           "ownIndex": own_index, "fileOwner": file_owner,
           "source": source, "note": note}
    _cache[key] = (now, cat)
    return cat


def owners_of(file: str, cat: dict) -> List[str]:
    """文件 → 归属组件 id 列表（深度降序，最深优先；覆盖全部命中组件）。

    精确/双向后缀对齐（与原 project._owns_match、compare._owner_of 同语义）。
    """
    from .paths import _norm_path
    p = _norm_path(file)
    if not p or not cat:
        return []
    depths = cat.get("depths") or {}
    hits = {cid for no, cid in (cat.get("ownIndex") or [])
            if no == p or p.endswith("/" + no) or no.endswith("/" + p)}
    return sorted(hits, key=lambda cid: depths.get(cid, 0), reverse=True)


def file_to_components(root: Optional[str] = None,
                       project: Optional[str] = None) -> Dict[str, Set[str]]:
    """组件 id → 归一化文件集合（engine._component_file_map 兼容形状）。"""
    from .paths import _norm_path
    cat = component_catalog(root, project)
    out: Dict[str, Set[str]] = {}
    for cid, c in (cat.get("byId") or {}).items():
        for f in (c.get("owns") or []):
            nf = _norm_path(f)
            if nf:
                out.setdefault(cid, set()).add(nf)
    return out
