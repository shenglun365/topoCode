"""契约条目 / 契约包 — plan-C-M0.md §2/§7.2/§7.3（V1-V8 校验）。

设计者在对话流中把期望固化为契约条目（draft→confirmed），打包为契约包
（框架版本快照随行冻结），注入 runner；验收比对在 acceptance 模块
（facts/opinions 物理分表 R6）。architect 只起草不判定：verdict 是
设计者唯一判定入口。

REST（/api/architect 前缀，经 __init__.router 挂载）：
  GET  /contracts/items?status=&reqId=        契约条目列表
  POST /contracts/items                        创建 draft（V1/V4/V5/V7）
  POST /contracts/items/{id}/confirm           设计者确认（V2；stale 重确认清标志 V8）
  POST /contracts/items/{id}/revise            rejected→改期望→version+1 回 confirmed（V6）
  POST /contracts/items/{id}/verdict           通过/打回（唯一判定入口）
  GET  /contracts/packages                     契约包列表
  POST /contracts/packages                     由 confirmed 条目建包（V3；框架快照+agentsMd）
  POST /contracts/packages/{id}/inject         注入 runner（条目→injected）
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from . import asset_framework
from .common import err, ok
from .store import ContractItemStore, ContractPackageStore

logger = logging.getLogger(__name__)

router = APIRouter()


def _pid(body: Optional[dict]) -> str:
    data = body or {}
    from .semantic_assets import project_id_for
    return project_id_for(data.get("root"), data.get("project"))


# ── 校验（V1/V4/V5/V7；V2/V3/V6/V8 在状态迁移处） ─────────────────

def _validate_item(pid: str, item: Dict[str, Any]) -> Optional[str]:
    """返回错误消息；None = 通过。"""
    kind = (item.get("kind") or "").strip()
    if not kind:
        return "kind 必填"
    if not asset_framework.is_kind_allowed(pid, kind):
        return f"kind '{kind}' 不在当前框架值域内（V1）"
    level = (item.get("level") or "implementation")
    if level not in asset_framework.allowed_levels(pid):
        return f"level '{level}' 不在当前框架值域内（V1）"
    behavior = item.get("behavior") or {}
    if kind != "state" and (behavior.get("states") or behavior.get("transitions")):
        return "behavior.states/transitions 仅 kind=state 可用（V7）"
    z_view = asset_framework._tier_view(asset_framework._active_config(pid))["z"]
    z_axis = item.get("zAxis") or []
    if z_axis and not z_view:
        return "low 档 zAxis 必须为空数组（V5）"
    for z in z_axis:
        cat = z.get("category") if isinstance(z, dict) else None
        if cat not in z_view:
            return f"zAxis category '{cat}' 不在值域内"
    return None


# ── agentsMd 生成（directivesDepth 决定详略：brief/full/full-scaffold） ──

def _behavior_lines(it: Dict[str, Any]) -> List[str]:
    b = it.get("behavior") or {}
    lines: List[str] = []
    for f in b.get("fields") or []:
        name = f.get("name") if isinstance(f, dict) else str(f)
        sem = (f.get("semantic") or "") if isinstance(f, dict) else ""
        lines.append(f"  - 字段 {name}" + (f"：{sem}" if sem else ""))
    for s in b.get("steps") or []:
        sem = (s.get("semantic") or "") if isinstance(s, dict) else str(s)
        cond = (s.get("condition") or "") if isinstance(s, dict) else ""
        lines.append(f"  - 步骤：{sem}" + (f"（条件 {cond}）" if cond else ""))
    for br in b.get("branches") or []:
        cond = br.get("condition") if isinstance(br, dict) else str(br)
        sem = (br.get("semantic") or "") if isinstance(br, dict) else ""
        lines.append(f"  - 分支：{cond} → {sem}")
    for st in b.get("states") or []:
        lines.append(f"  - 状态：{st}")
    for tr in b.get("transitions") or []:
        lines.append(f"  - 转移：{tr}")
    for r in b.get("relations") or []:
        tgt = r.get("target") if isinstance(r, dict) else r
        rtype = (r.get("type") or "") if isinstance(r, dict) else ""
        lines.append(f"  - 关联：{tgt}" + (f"（{rtype}）" if rtype else ""))
    return lines


def build_agents_md(pkg_id: str, snapshot: Dict[str, Any],
                    items: List[Dict[str, Any]]) -> str:
    """契约包 → runner 可读的 AGENTS.md 片段（期望即规约，逐条锚定）。"""
    depth = (snapshot or {}).get("directivesDepth") or "full"
    lines: List[str] = [
        f"# 契约包 {pkg_id}",
        f"> 框架快照：tier={snapshot.get('activeTier')} version={snapshot.get('version') or '-'}；"
        f"directivesDepth={depth}（快照随行冻结，当前框架变更不影响本包）",
        "> 以下是设计者已确认的契约期望。实现必须逐条满足，不得自行变更期望；"
        "若发现期望与代码事实冲突，如实上报等待设计者决策，不要静默适配。",
        "",
    ]
    for it in items:
        target = it.get("target") or {}
        tgt = " ".join(filter(None, [target.get("file") or "", target.get("symbol") or ""])) \
            or "（意图级，无锚点）"
        lines.append(f"## {it['id']} [{it.get('kind')}/{it.get('level')}]")
        lines.append(f"- target: {tgt}")
        if it.get("intentOnly"):
            lines.append("- ⚠ 意图级期望（无锚点）：实现位置由你决定，但必须满足下列期望")
        if depth in ("full", "full-scaffold"):
            for ln in _behavior_lines(it):
                lines.append(ln)
        acc = it.get("acceptance") or {}
        if acc.get("mode"):
            layers = acc.get("layers") or []
            lines.append(f"- 验收：mode={acc['mode']}"
                         + (f" layers={','.join(layers)}" if layers else ""))
        if acc.get("criteria"):
            lines.append(f"- 验收标准：{acc['criteria']}")
        if depth == "full-scaffold":
            for z in it.get("zAxis") or []:
                if not isinstance(z, dict):
                    continue
                lines.append(f"- 治理[{z.get('category')}]: {z.get('text') or ''}"
                             + (f"（锚点 {z['anchor']}）" if z.get("anchor") else ""))
        lines.append("")
    return "\n".join(lines)


# ── 状态机（V2/V3/V6/V8 在此强制） ──────────────────────────────

def create_item(pid: str, item: Dict[str, Any], author: str = "") -> Dict[str, Any]:
    e = _validate_item(pid, item)
    if e:
        raise ValueError(e)
    it = dict(item or {})
    target = dict(it.get("target") or {})
    # V4：无 file 且无 symbol → 强制意图级（如实纪律，不假装可机械验证）
    if not target.get("file") and not target.get("symbol"):
        it["intentOnly"] = True
    it["target"] = target
    it.setdefault("origin", {})
    it.setdefault("reqId", "")
    it.setdefault("convId", "")
    return ContractItemStore.create(pid, it, author=author)


def confirm_item(item_id: str, pid: str = "") -> Dict[str, Any]:
    item = ContractItemStore.get(item_id, pid or None)
    if not item:
        raise LookupError(f"契约条目不存在: {item_id}")
    # 正常确认：draft→confirmed；V8 重确认：框架变更标 stale 的非终态条目
    # （confirmed/injected/verifying）经设计者重确认清标志回到 confirmed。
    is_draft = item.get("status") == "draft"
    is_stale_reconfirm = (item.get("status") in ("confirmed", "injected", "verifying")
                          and item.get("staleByFramework"))
    if not (is_draft or is_stale_reconfirm):
        raise ValueError(f"当前状态不可确认（当前: {item.get('status')}"
                         f"{'' if is_draft else '，非框架变更 stale 条目'}）")
    # V2：无 origin（设计者原话引用）不得 confirmed
    if not (item.get("origin") or {}):
        raise ValueError("无 origin 不得确认（V2：设计者原话引用是证据链锚点）")
    ContractItemStore.set_status(item_id, "confirmed", "confirmed_at")
    # V8：框架变更标记的 stale 条目，设计者重确认即清除标志
    if item.get("staleByFramework"):
        ContractItemStore.update(item_id, {"staleByFramework": 0})
    return ContractItemStore.get(item_id) or {}


_REVISE_FIELDS = ("kind", "level", "target", "behavior", "zAxis", "acceptance")


def revise_item(item_id: str, patch: Dict[str, Any], pid: str = "") -> Dict[str, Any]:
    """V6：rejected 非终态——修改期望后 version+1 回 confirmed。"""
    item = ContractItemStore.get(item_id, pid or None)
    if not item:
        raise LookupError(f"契约条目不存在: {item_id}")
    if item.get("status") != "rejected":
        raise ValueError(f"仅 rejected 条目可修改期望（当前: {item.get('status')}）")
    merged = {**item, **{k: v for k, v in (patch or {}).items() if k in _REVISE_FIELDS}}
    e = _validate_item(item.get("projectId") or pid or "", merged)
    if e:
        raise ValueError(e)
    upd: Dict[str, Any] = {"version": int(item.get("version") or 1) + 1,
                           "status": "confirmed"}
    for k in _REVISE_FIELDS:
        if k in (patch or {}):
            upd[k] = patch[k]
    return ContractItemStore.update(item_id, upd) or {}


def update_draft(item_id: str, patch: Dict[str, Any], pid: str = "") -> Dict[str, Any]:
    """固化卡「修改」：仅 draft 态可编辑期望字段（确认前自由调整，不改 version）。"""
    item = ContractItemStore.get(item_id, pid or None)
    if not item:
        raise LookupError(f"契约条目不存在: {item_id}")
    if item.get("status") != "draft":
        raise ValueError(f"仅 draft 条目可修改（当前: {item.get('status')}）")
    merged = {**item, **{k: v for k, v in (patch or {}).items() if k in _REVISE_FIELDS}}
    e = _validate_item(item.get("projectId") or pid or "", merged)
    if e:
        raise ValueError(e)
    upd: Dict[str, Any] = {}
    for k in _REVISE_FIELDS:
        if k in (patch or {}):
            upd[k] = patch[k]
    return ContractItemStore.update(item_id, upd) or {}


def delete_draft(item_id: str, pid: str = "") -> bool:
    """固化卡「删」：仅 draft 态可删除（设计者放弃该期望，未确认无副作用）。"""
    item = ContractItemStore.get(item_id, pid or None)
    if not item:
        raise LookupError(f"契约条目不存在: {item_id}")
    if item.get("status") != "draft":
        raise ValueError(f"仅 draft 条目可删除（当前: {item.get('status')}）")
    return ContractItemStore.delete(item_id)


def verdict_item(item_id: str, verdict: str, pid: str = "") -> Dict[str, Any]:
    """唯一判定入口：accepted / rejected（设计者决定，architect 不代判）。"""
    if verdict not in ("accepted", "rejected"):
        raise ValueError("verdict 必须是 accepted|rejected")
    item = ContractItemStore.get(item_id, pid or None)
    if not item:
        raise LookupError(f"契约条目不存在: {item_id}")
    if item.get("status") not in ("confirmed", "injected", "verifying"):
        raise ValueError(f"当前状态 {item.get('status')} 不可判定"
                         f"（允许: confirmed/injected/verifying）")
    ContractItemStore.set_status(item_id, verdict, "verified_at")
    return ContractItemStore.get(item_id) or {}


def set_linked_tests(item_id: str, linked: List[str], pid: str = "") -> Dict[str, Any]:
    """A7：验收条目关联单测用例（引用关系，任意状态可改，不升 version 不动状态）。"""
    item = ContractItemStore.get(item_id, pid or None)
    if not item:
        raise LookupError(f"契约条目不存在: {item_id}")
    acc = dict(item.get("acceptance") or {})
    acc["linkedTests"] = [str(x).strip() for x in (linked or []) if str(x).strip()]
    return ContractItemStore.update(item_id, {"acceptance": acc}) or {}


# ── C1 可授权清单（Z 轴 × acceptance.mode=auto 细则；保真纪律边界） ───────

def _z_anchor_present(z: Any) -> bool:
    """Z 轴条目是否带可机械校验的锚点（anchor 含非空 file/symbol）。"""
    a = z.get("anchor") if isinstance(z, dict) else None
    if not isinstance(a, dict):
        return False
    return bool((a.get("file") or "").strip() or (a.get("symbol") or "").strip())


def _default_mode(pid: str) -> str:
    """条目未显式指定 mode 时按框架档位默认（low→auto，mid/high→assisted）。"""
    try:
        cfg = asset_framework._active_config(pid)
        tier = (cfg or {}).get("activeTier") or "mid"
        default = asset_framework._ACCEPTANCE_DEFAULT.get(tier) \
            or asset_framework._ACCEPTANCE_DEFAULT["mid"]
        return default.get("mode") or "assisted"
    except Exception:
        return "assisted"


def authorization_list(item_id: str, pid: str = "") -> Dict[str, Any]:
    """C1：可授权清单——当前 acceptance.mode 下哪些校验可自动授权、哪些必须人工。

    保真纪律边界（细则）：
    - **可自动授权**（机械可比）：L1 覆盖性、L2 行为符合性、**带锚点的 Z 轴条目**（锚点存在性）。
    - **必须人工**：意图级 Z 轴条目（无锚点，机械查不出"理解跑偏"）、L3 语义（永远不自动）。
    - mode 语义：auto=L1/L2 通过即过（low 默认，不跑 L3）；assisted=L1/L2 自动+L3 人工主判
      （mid/high 默认）；manual=逐条人审。
    - `autoPassable`=该条目**结构上**可被 mode=auto 自动授权（mode=auto 且无意图级 Z 轴条目）。
    """
    item = ContractItemStore.get(item_id, pid or None)
    if not item:
        raise LookupError(f"契约条目不存在: {item_id}")
    pid = pid or item.get("projectId") or ""
    mode = (item.get("acceptance") or {}).get("mode") or _default_mode(pid)
    mech_ok = mode in ("auto", "assisted")  # 机械项是否纳入自动授权

    checks: List[Dict[str, Any]] = []
    checks.append({
        "id": "L1", "label": "L1 覆盖性", "cls": "mechanical",
        "authorizable": mech_ok,
        "status": "not-run" if mode == "manual" else "pending",
        "note": "" if mech_ok else "manual 档：逐条人审",
    })
    checks.append({
        "id": "L2", "label": "L2 行为符合性", "cls": "mechanical",
        "authorizable": mech_ok,
        "status": "not-run" if mode == "manual" else "pending",
        "note": "" if mech_ok else "manual 档：逐条人审",
    })
    human_required: List[str] = []
    intent_z = 0
    for i, z in enumerate(item.get("zAxis") or []):
        text = (z.get("text") or "") if isinstance(z, dict) else str(z)
        cat = (z.get("category") or "") if isinstance(z, dict) else ""
        has_anchor = _z_anchor_present(z)
        authorizable = has_anchor and mech_ok
        cid = f"z-{i}"
        if not authorizable:
            human_required.append(cid)
        if not has_anchor:
            intent_z += 1
        checks.append({
            "id": cid, "label": f"Z 轴[{cat or '?'}] {text}".strip(),
            "cls": "mechanical" if has_anchor else "intent",
            "authorizable": authorizable,
            "status": "not-run" if not authorizable else "pending",
            "note": "" if authorizable else ("无锚点，意图级，需人工"
                                             if not has_anchor else "manual 档：逐条人审"),
        })
    # L3：永远不自动授权（mode=auto 不跑；assisted 人工主判按需激活；manual 人审）
    l3_note = {"auto": "auto 档不运行 L3",
               "assisted": "人工主判，按需手动激活模型辅助",
               "manual": "逐条人审"}.get(mode, "人工主判")
    checks.append({
        "id": "L3", "label": "L3 语义符合性", "cls": "opinion",
        "authorizable": False, "status": "not-run", "note": l3_note,
    })
    human_required.append("L3")
    auto_passable = (mode == "auto") and intent_z == 0
    return {
        "itemId": item_id,
        "mode": mode,
        "autoPassable": auto_passable,
        "intentZCount": intent_z,
        "humanRequired": human_required,
        "checks": checks,
    }


def create_package(pid: str, item_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """V3：仅 confirmed 条目可入包；框架快照随行冻结。"""
    if item_ids:
        items = []
        for iid in item_ids:
            it = ContractItemStore.get(iid, pid)
            if not it:
                raise LookupError(f"契约条目不存在: {iid}")
            if it.get("status") != "confirmed":
                raise ValueError(
                    f"V3: 未 confirmed 条目不得入包（{iid} 当前 {it.get('status')}）")
            items.append(it)
    else:
        items = ContractItemStore.list(pid, status="confirmed")
    if not items:
        raise ValueError("没有可打包的 confirmed 契约条目")
    cfg = asset_framework._active_config(pid)
    view = asset_framework._tier_view(cfg)
    snapshot = {"version": int(cfg.get("frameworkVersion") or 0),
                "activeTier": cfg.get("activeTier"),
                "directivesDepth": view["directivesDepth"],
                "acceptanceDefault": view["acceptanceDefault"]}
    pkg = ContractPackageStore.create(pid, snapshot, [i["id"] for i in items])
    md = build_agents_md(pkg["id"], snapshot, items)
    ContractPackageStore.update(pkg["id"], {"agentsMd": md})
    return ContractPackageStore.get(pkg["id"], pid) or pkg


def inject_package(pkg_id: str, injected_to: str = "runner", pid: str = "") -> Dict[str, Any]:
    pkg = ContractPackageStore.get(pkg_id, pid or None)
    if not pkg:
        raise LookupError(f"契约包不存在: {pkg_id}")
    if pkg.get("status") != "created":
        raise ValueError(f"包已注入/取代（当前: {pkg.get('status')}）")
    if not (pkg.get("agentsMd") or "").strip():
        items = [i for i in
                 (ContractItemStore.get(i, pkg.get("projectId") or pid or None)
                  for i in pkg.get("itemIds") or []) if i]
        pkg = dict(pkg)
        pkg["agentsMd"] = build_agents_md(
            pkg_id, pkg.get("frameworkSnapshot") or {}, items)
        ContractPackageStore.update(pkg_id, {"agentsMd": pkg["agentsMd"]})
    ContractPackageStore.mark_injected(pkg_id, injected_to)
    for iid in pkg.get("itemIds") or []:
        it = ContractItemStore.get(iid, pkg.get("projectId") or pid or None)
        if it and it.get("status") == "confirmed":
            ContractItemStore.set_status(iid, "injected", "injected_at")
    return ContractPackageStore.get(pkg_id) or {}


# ── REST ──────────────────────────────────────────────────────

@router.get("/contracts/items")
async def api_contracts_items(project: Optional[str] = None,
                              root: Optional[str] = None,
                              status: str = "", reqId: str = "",
                              limit: int = 500):
    from .semantic_assets import project_id_for
    pid = project_id_for(root, project)
    if not pid:
        return ok([])
    return ok(ContractItemStore.list(pid, status=status, req_id=reqId, limit=limit))


@router.post("/contracts/items")
async def api_contracts_item_create(request: Request):
    body = await request.json() or {}
    pid = _pid(body)
    if not pid:
        return err(400, "projectId 不能为空")
    item = body.get("item") if isinstance(body.get("item"), dict) else \
        {k: v for k, v in body.items() if k not in ("root", "project", "author")}
    try:
        row = create_item(pid, item, author=body.get("author") or "")
    except ValueError as e:
        return err(400, str(e))
    return ok(row)


@router.post("/contracts/items/{item_id}/confirm")
async def api_contracts_item_confirm(item_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    pid = _pid(body) if isinstance(body, dict) else ""
    try:
        row = confirm_item(item_id, pid)
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    return ok(row)


@router.put("/contracts/items/{item_id}")
async def api_contracts_item_update(item_id: str, request: Request):
    """固化卡「修改」：{patch: {kind?, level?, target?, behavior?, zAxis?, acceptance?}}（仅 draft）。"""
    body = await request.json() or {}
    pid = _pid(body)
    try:
        row = update_draft(item_id, body.get("patch") or {}, pid)
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    return ok(row)


@router.delete("/contracts/items/{item_id}")
async def api_contracts_item_delete(item_id: str, request: Request):
    """固化卡「删」：仅 draft 态可删除。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    pid = _pid(body) if isinstance(body, dict) else ""
    try:
        ok_del = delete_draft(item_id, pid)
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    return ok({"deleted": ok_del})


@router.post("/contracts/items/{item_id}/revise")
async def api_contracts_item_revise(item_id: str, request: Request):
    body = await request.json() or {}
    pid = _pid(body)
    try:
        row = revise_item(item_id, body.get("patch") or {}, pid)
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    return ok(row)


def _induce_from_rejection_async(pid: str, item_id: str) -> None:
    """A1 经验回写：rejected 后后台线程归纳 pending 规约提案（不阻塞判定响应）。"""
    import threading

    def _run() -> None:
        try:
            from .naming import induce_from_rejection
            induce_from_rejection(pid, item_id, author="induce")
        except Exception as e:
            logger.warning("[contracts] A1 经验回写失败: %s", e)

    threading.Thread(target=_run, daemon=True).start()


@router.post("/contracts/items/{item_id}/verdict")
async def api_contracts_item_verdict(item_id: str, request: Request):
    body = await request.json() or {}
    pid = _pid(body)
    try:
        row = verdict_item(item_id, (body.get("verdict") or "").strip(), pid)
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    # A1 经验回写：rejected → 归纳 pending 规约提案（设计者确认生效；后台，失败不影响判定）
    if (row or {}).get("status") == "rejected":
        _induce_from_rejection_async(pid, item_id)
    return ok(row)


@router.post("/contracts/items/{item_id}/linked-tests")
async def api_contracts_item_linked_tests(item_id: str, request: Request):
    """A7：验收条目关联单测用例（引用关系；任意状态可改，不升 version）。"""
    body = await request.json() or {}
    pid = _pid(body)
    linked = body.get("linkedTests")
    if not isinstance(linked, list):
        return err(400, "linkedTests 必须是数组")
    try:
        row = set_linked_tests(item_id, [str(x) for x in linked], pid)
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    return ok(row)


@router.post("/contracts/items/{item_id}/authorization")
async def api_contracts_item_authorization(item_id: str, request: Request):
    """C1 可授权清单：当前 mode 下哪些校验可自动授权、哪些必须人工（Z 轴 × mode=auto 细则）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    pid = _pid(body) if isinstance(body, dict) else ""
    try:
        return ok(authorization_list(item_id, pid))
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    except Exception as e:
        logger.exception("[authorization] failed for item %s", item_id)
        return err(500, f"可授权清单计算失败: {e}")


@router.get("/contracts/packages")
async def api_contracts_packages(project: Optional[str] = None,
                                 root: Optional[str] = None, limit: int = 100):
    from .semantic_assets import project_id_for
    pid = project_id_for(root, project)
    if not pid:
        return ok([])
    return ok(ContractPackageStore.list(pid, limit=limit))


@router.post("/contracts/packages")
async def api_contracts_package_create(request: Request):
    body = await request.json() or {}
    pid = _pid(body)
    if not pid:
        return err(400, "projectId 不能为空")
    item_ids = body.get("itemIds") or None
    if item_ids is not None and not isinstance(item_ids, list):
        return err(400, "itemIds 必须是数组")
    try:
        row = create_package(pid, [str(i) for i in item_ids] if item_ids else None)
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    return ok(row)


@router.post("/contracts/packages/{pkg_id}/inject")
async def api_contracts_package_inject(pkg_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    pid = _pid(body) if isinstance(body, dict) else ""
    try:
        row = inject_package(pkg_id,
                             injected_to=(body or {}).get("injectedTo") or "runner",
                             pid=pid)
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    return ok(row)
