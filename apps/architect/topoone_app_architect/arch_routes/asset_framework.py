"""认知框架配置（元认知框架即配置）— plan-C-M0.md §1/§6.3/§7.1。

三组默认预设（低/中/高）+ 自建框架；版本行即变更审计（arch_framework_configs）。
标准变更（切档/改值域/载自建）→ 存量资产整体作废（voided，不写墓碑 R1，命名不迁移）；
代码变更（标准不变）→ 既有 stale/墓碑/命名继承机制不受影响。

REST（/api/architect 前缀，经 __init__.router 挂载）：
  GET  /framework                  当前生效配置（无 → 默认 mid 预设，不落库）
  POST /framework/preview-change   dry-run 影响预览（作废确认流数据源）
  POST /framework/switch           执行变更（事务：新版本行 + 批量 voided）
  PUT  /framework/custom           保存自建框架（=switch change_kind=custom_load）
  GET  /framework/versions         版本历史
  GET  /semantic/coverage          覆盖度统计（概览徽标/覆盖度图层）
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from ..common import err, ok
from ..store import FrameworkConfigStore, _fetchall_routed, _row_to_api

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 内置值域（plan-C-M0.md §1.1） ──────────────────────────────

KIND_LABELS = {
    "entity": "实体", "contract": "契约", "state": "状态",
    "rule": "规则", "process": "过程", "decision": "决策",
}
LEVEL_LABELS = {"business": "业务", "logic": "逻辑", "implementation": "实现"}
Z_LABELS = {
    "observability": "可观测", "resilience": "韧性",
    "config": "配置", "security": "安全",
}

# 各档位值域（M0 §1.1 总表；low 无 state——状态用枚举/过程分支描述）
_TIER_X = {
    "low": ("entity", "contract", "rule", "process", "decision"),
    "mid": tuple(KIND_LABELS),
    "high": tuple(KIND_LABELS),
}
_TIER_Y = {
    # 逻辑层已转为「逻辑视图」(跨组件业务链条，非资产层级)——粒度轴收敛为实现单层
    "low": ("implementation",),
    "mid": ("implementation",),
    "high": ("implementation",),
}
_TIER_Z = {
    "low": (),
    "mid": tuple(Z_LABELS),
    "high": tuple(Z_LABELS),
}
_ACCEPTANCE_DEFAULT = {
    "low": {"mode": "auto", "layers": ["L1"], "l3": "off"},
    "mid": {"mode": "assisted", "layers": ["L1", "L2"], "l3": "human-on-demand"},
    "high": {"mode": "assisted", "layers": ["L1", "L2"], "l3": "human-on-demand"},
}
_DIRECTIVES_DEPTH = {"low": "brief", "mid": "full", "high": "full-scaffold"}

SCENARIOS = ("extract", "accept", "naming", "general")


def _axis_values(ids: tuple, labels: Dict[str, str]) -> List[Dict[str, Any]]:
    return [{"id": i, "label": labels.get(i, i), "builtin": True} for i in ids]


def build_preset(tier: str) -> Dict[str, Any]:
    """构建某档位的完整框架配置（M0 §1.2 YAML 的内存形态）。"""
    if tier not in _TIER_X:
        raise ValueError(f"未知档位: {tier}")
    tiers = {}
    for t in _TIER_X:
        tiers[t] = {
            "x": list(_TIER_X[t]), "y": list(_TIER_Y[t]), "z": list(_TIER_Z[t]),
            "acceptanceDefault": _ACCEPTANCE_DEFAULT[t],
            "directivesDepth": _DIRECTIVES_DEPTH[t],
        }
    return {
        "version": 1,
        "activeTier": tier,
        "axes": [
            {"id": "x", "label": "本体", "values": _axis_values(tuple(KIND_LABELS), KIND_LABELS)},
            {"id": "y", "label": "抽象", "values": _axis_values(tuple(LEVEL_LABELS), LEVEL_LABELS)},
            {"id": "z", "label": "治理", "values": _axis_values(tuple(Z_LABELS), Z_LABELS)},
        ],
        "tiers": tiers,
    }


def _validate_config(config: Dict[str, Any]) -> Optional[str]:
    """自建框架校验；返回错误消息或 None。"""
    if not isinstance(config, dict):
        return "config 必须是对象"
    tier = config.get("activeTier")
    if tier not in ("low", "mid", "high", "custom"):
        return "activeTier 必须是 low|mid|high|custom"
    tiers = config.get("tiers")
    if not isinstance(tiers, dict) or tier not in tiers:
        return "tiers 缺少当前档位定义"
    cur = tiers[tier] or {}
    kinds = cur.get("x") or []
    if not kinds or not all(k in KIND_LABELS for k in kinds):
        return "x 值域必须为内置本体类型的非空子集（自定义 kind 暫不开放）"
    levels = cur.get("y") or []
    if not levels or not all(l in LEVEL_LABELS for l in levels):
        return "y 值域必须为内置抽象粒度的非空子集"
    zcats = cur.get("z") or []
    if not all(z in Z_LABELS for z in zcats):
        return "z 值域必须为内置治理类别"
    return None


def _active_config(project_id: str) -> Dict[str, Any]:
    """当前生效配置；无定制 → 默认 mid 预设（不落库）。"""
    row = FrameworkConfigStore.get_active_raw(project_id)
    if row:
        import json
        try:
            cfg = json.loads(row.get("config") or "{}")
            if isinstance(cfg, dict) and cfg.get("activeTier"):
                cfg["frameworkVersion"] = int(row.get("version") or 1)
                return cfg
        except Exception:
            logger.warning("[framework] 激活配置解析失败 project=%s", project_id)
    return build_preset("mid")


def _tier_view(config: Dict[str, Any]) -> Dict[str, Any]:
    """当前档位的值域视图（供校验/UI 过滤）。"""
    tiers = config.get("tiers") or {}
    cur = tiers.get(config.get("activeTier") or "mid") or {}
    return {
        "kinds": list(cur.get("x") or []),
        "levels": list(cur.get("y") or []),
        "z": list(cur.get("z") or []),
        "acceptanceDefault": cur.get("acceptanceDefault") or _ACCEPTANCE_DEFAULT["mid"],
        "directivesDepth": cur.get("directivesDepth") or "full",
    }


# ── 供其它模块调用的判定助手（提取/保存路径用） ─────────────────

def allowed_kinds(project_id: str) -> List[str]:
    return _tier_view(_active_config(project_id))["kinds"]


def allowed_levels(project_id: str) -> List[str]:
    return _tier_view(_active_config(project_id))["levels"]


def is_kind_allowed(project_id: str, kind: str) -> bool:
    return kind in allowed_kinds(project_id)


# ── 标准变更（整体作废 + 版本落库） ────────────────────────────

def _void_all_assets(project_id: str, framework_version: int,
                     executed_by: str) -> int:
    """标准变更：存量资产整体作废（保留行、不写墓碑 R1、命名继承中断）。"""
    import time
    from ..store import _target_db
    db = _target_db("arch_semantic_assets", project_id=project_id)
    cur = db.execute(
        "UPDATE arch_semantic_assets SET status = 'voided', "
        "voided_reason = 'framework_change', voided_at = ?, voided_by = ?, "
        "voided_framework_version = ?, needs_update = 0 "
        "WHERE project_id = ? AND status IN ('active', 'stale')",
        (int(time.time() * 1000), executed_by, int(framework_version), project_id))
    db.commit()
    return cur.rowcount or 0


def _count_by_kind_pending(project_id: str) -> Dict[str, int]:
    """待作废（active/stale）资产的 kind 分布。"""
    rows, _ = _fetchall_routed(
        "arch_semantic_assets",
        "SELECT kind, COUNT(*) AS n FROM arch_semantic_assets "
        "WHERE project_id = ? AND status IN ('active','stale') GROUP BY kind",
        (project_id,), project_id or None)
    return {r["kind"]: int(r["n"]) for r in rows}


def preview_change(project_id: str) -> Dict[str, Any]:
    """dry-run：标准变更将作废的存量资产（全部 active/stale，含分布）。"""
    by_kind = _count_by_kind_pending(project_id)
    return {"voidedAssets": sum(by_kind.values()), "byKind": by_kind,
            "namingMigrated": False}


def switch_tier(project_id: str, tier: str, executed_by: str = "",
                note: str = "") -> Dict[str, Any]:
    """切换到某内置预设：影响预览 → 作废全部存量 → 版本落库 → 规约待复核。"""
    config = build_preset(tier)
    return _apply_change(project_id, config, change_kind="tier_switch",
                         executed_by=executed_by, note=note or f"切换到 {tier} 档")


def load_custom(project_id: str, config: Dict[str, Any], executed_by: str = "",
                note: str = "") -> Dict[str, Any]:
    err_msg = _validate_config(config)
    if err_msg:
        raise ValueError(err_msg)
    return _apply_change(project_id, config, change_kind="custom_load",
                         executed_by=executed_by, note=note or "载入自建框架")


def _apply_change(project_id: str, config: Dict[str, Any], change_kind: str,
                  executed_by: str, note: str) -> Dict[str, Any]:
    affected = preview_change(project_id)
    row = FrameworkConfigStore.activate(project_id, config, change_kind,
                                        affected=affected, executed_by=executed_by,
                                        note=note)
    voided = _void_all_assets(project_id, row["version"], executed_by)
    # 规约联动：关联旧值域的规约标记待复核（plan-C §5.3）
    try:
        from ..store import NamingConventionStore
        NamingConventionStore.mark_pending_review(project_id, row["version"])
    except Exception as e:
        logger.warning("[framework] 规约待复核标记失败: %s", e)
    # 契约条目联动（V8）：非 accepted 条目标 staleByFramework 需重确认；
    # 切到 z 空值域(如 low)时未 accepted 条目 z_axis 自动清空并提示
    try:
        from ..store import _target_db as _tdb
        db = _tdb("arch_contract_items", project_id=project_id)
        cur = db.execute(
            "UPDATE arch_contract_items SET stale_by_framework = 1 "
            "WHERE project_id = ? AND status IN ('draft','confirmed','injected','verifying')",
            (project_id,))
        affected["staleContractItems"] = cur.rowcount or 0
        if not _tier_view(config)["z"]:
            cur2 = db.execute(
                "UPDATE arch_contract_items SET z_axis = '[]' "
                "WHERE project_id = ? AND status IN ('draft','confirmed','injected','verifying') "
                "AND z_axis IS NOT NULL AND z_axis NOT IN ('', '[]', 'null')",
                (project_id,))
            affected["zAxisCleared"] = cur2.rowcount or 0
        db.commit()
    except Exception as e:
        logger.warning("[framework] 契约条目联动标记失败: %s", e)
    logger.info("[framework] 标准变更 project=%s version=%s kind=%s voided=%s",
                project_id, row["version"], change_kind, voided)
    row["voidedAssets"] = voided
    return row


# ── 覆盖度统计（概览徽标 / 覆盖度图层） ────────────────────────

def coverage(project_id: str, root: Optional[str] = None,
             project: Optional[str] = None) -> Dict[str, Any]:
    """按组件统计语义资产覆盖：已提取/过期/作废 + 未提取组件清单。

    组件来源 = 统一组件目录(sem/catalog，批 0-1 修复：原 build_component_catalog(None,None)
    恒空目录导致 componentsTotal 恒 0)；资产归属 = scope_key(comm-*) 或锚点文件
    反查(统一 owners_of 匹配)。诚实呈现部分真相（plan-C §4.3）。
    含 active + stale（作废 voided 不计入覆盖）。
    """
    from ..sem import catalog as _catalog
    try:
        cat = _catalog.component_catalog(root, project)
    except Exception as e:
        logger.warning("[framework] 组件目录获取失败: %s", e)
        cat = {"byId": {}, "ownIndex": []}

    comps = [{"id": c.get("id"), "name": c.get("name") or c.get("id"),
              "owns": c.get("owns") or []} for c in (cat.get("components") or [])
             if c.get("id")]

    rows, _ = _fetchall_routed(
        "arch_semantic_assets",
        "SELECT * FROM arch_semantic_assets "
        "WHERE project_id = ? AND status IN ('active','stale') LIMIT 5000",
        (project_id,), project_id or None)
    assets = [_row_to_api(r) for r in rows]
    by_comp: Dict[str, Dict[str, int]] = {}
    unowned = 0
    for a in assets:
        sk = a.get("scopeKey") or ""
        status = a.get("status") or "active"
        cids = [sk[4:]] if sk.startswith("comm-") else []
        if not cids:
            refs = a.get("astRefs") or []
            f0 = (refs[0] or {}).get("file") if refs else None
            if f0:
                cids = _catalog.owners_of(f0, cat)
        if not cids:
            unowned += 1
            continue
        for cid in cids:
            slot = by_comp.setdefault(cid, {"total": 0, "stale": 0})
            slot["total"] += 1
            if status == "stale":
                slot["stale"] += 1

    comp_status = []
    for c in comps:
        slot = by_comp.get(c["id"]) or {"total": 0, "stale": 0}
        comp_status.append({
            "componentId": c["id"], "name": c["name"],
            "coverage": "full" if slot["total"] > 0 and slot["stale"] == 0
            else ("partial" if slot["total"] > 0 else "none"),
            "assets": slot["total"], "stale": slot["stale"],
        })
    extracted = len(assets)
    stale = sum(1 for a in assets if (a.get("status") or "") == "stale")
    return {
        "extracted": extracted, "stale": stale, "unowned": unowned,
        "componentsTotal": len(comps),
        "componentsCovered": sum(1 for c in comp_status if c["coverage"] != "none"),
        "components": comp_status,
    }


# ── REST ──────────────────────────────────────────────────────

def _pid(body: Optional[dict]) -> str:
    data = body or {}
    from .semantic_assets import project_id_for
    return project_id_for(data.get("root"), data.get("project"))


@router.get("/framework")
async def api_framework_get(project: Optional[str] = None, root: Optional[str] = None):
    """当前生效框架配置（无定制 → 默认 mid 预设，不落库）。"""
    from .semantic_assets import project_id_for
    pid = project_id_for(root, project)
    cfg = _active_config(pid)
    return ok({"config": cfg, "view": _tier_view(cfg),
               "presets": {t: build_preset(t)["tiers"][t] for t in _TIER_X}})


@router.post("/framework/preview-change")
async def api_framework_preview(request: Request):
    """dry-run：标准变更影响预览（作废确认流数据源）。"""
    body = await request.json()
    pid = _pid(body)
    if not pid:
        return err(400, "projectId 不能为空")
    return ok(preview_change(pid))


@router.post("/framework/switch")
async def api_framework_switch(request: Request):
    """执行标准变更：{projectId?, tier: low|mid|high, executedBy?, note?}。"""
    body = await request.json()
    pid = _pid(body)
    tier = (body or {}).get("tier") or ""
    if not pid:
        return err(400, "projectId 不能为空")
    if tier not in _TIER_X:
        return err(400, f"tier 必须是 {'|'.join(_TIER_X)}")
    try:
        row = switch_tier(pid, tier, executed_by=(body or {}).get("executedBy") or "",
                          note=(body or {}).get("note") or "")
    except ValueError as e:
        return err(400, str(e))
    return ok(row)


@router.put("/framework/custom")
async def api_framework_custom(request: Request):
    """载入自建框架：{projectId?, config, executedBy?, note?}。"""
    body = await request.json()
    pid = _pid(body)
    config = (body or {}).get("config")
    if not pid:
        return err(400, "projectId 不能为空")
    try:
        row = load_custom(pid, config, executed_by=(body or {}).get("executedBy") or "",
                          note=(body or {}).get("note") or "")
    except ValueError as e:
        return err(400, str(e))
    return ok(row)


@router.get("/framework/versions")
async def api_framework_versions(project: Optional[str] = None,
                                 root: Optional[str] = None, limit: int = 50):
    """版本历史（变更留痕）。"""
    from .semantic_assets import project_id_for
    return ok(FrameworkConfigStore.versions(project_id_for(root, project), limit=limit))


@router.get("/semantic/coverage")
async def api_semantic_coverage(project: Optional[str] = None,
                                root: Optional[str] = None):
    """覆盖度统计（诚实呈现部分真相）。"""
    from .semantic_assets import project_id_for
    pid = project_id_for(root, project)
    if not pid:
        return ok({"extracted": 0, "stale": 0, "unowned": 0,
                   "componentsTotal": 0, "componentsCovered": 0, "components": []})
    return ok(coverage(pid, root, project))
