"""验收 — plan-C-M0.md §6.7/§7.4（事实/意见分离 R6；L3 人工主判）。

保真纪律：
- L1 覆盖性 / L2 行为符合性 = **事实**（机械比对，可复现，落 arch_acceptance_facts）；
- L3 语义判断 = **参考意见**（模型辅助，带来源/置信度/证据，落 arch_acceptance_opinions，
  仅设计者手动激活端点可写入——无自动写入方）；
- 通过/打回由设计者判定（contracts.verdict，唯一判定入口）；
- 修复指令只起草不发送。

REST（/api/architect 前缀）：
  POST /acceptance/run                                  触发验收（严 profile 提取 + L1/L2 比对）
  GET  /acceptance/reports?packageId=                   报告列表
  GET  /acceptance/reports/{id}                         报告详情（facts/opinions 分区）
  POST /acceptance/reports/{id}/items/{itemId}/opinion  手动激活 L3
  POST /acceptance/items/{itemId}/fix-instruction       起草修复指令
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request

from . import asset_framework
from .. import store as _store
from ..common import err, ok
from ..store import AcceptanceStore, ContractItemStore, ContractPackageStore

logger = logging.getLogger(__name__)

router = APIRouter()


def _pid(body: Optional[dict]) -> str:
    data = body or {}
    from .semantic_assets import project_id_for
    return project_id_for(data.get("root"), data.get("project"))


def _norm(p: str) -> str:
    return (p or "").strip().replace("\\", "/").lstrip("./")


# ── L1 覆盖性 / L2 行为符合性（机械比对 = 事实） ─────────────────

def _match_asset(item: Dict[str, Any],
                 extracted: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """按 target.file/symbol 锚点在提取结果中定位资产；kind 匹配优先。"""
    target = item.get("target") or {}
    f = _norm(target.get("file") or "")
    sym = (target.get("symbol") or "").strip()
    best: Optional[Tuple[int, Dict[str, Any]]] = None
    for a in extracted:
        if (a.get("status") or "active") == "deleted":
            continue
        refs = a.get("astRefs") or []
        if not refs:
            continue
        files = {_norm(r.get("file") or "") for r in refs if r.get("file")}
        syms = {r.get("symbol") for r in refs if r.get("symbol")}
        if f and f not in files:
            if not any(x and (x.endswith(f) or f.endswith(x)) for x in files):
                continue
        if sym and sym not in syms:
            continue
        score = 2 if a.get("kind") == item.get("kind") else 1
        if not best or score > best[0]:
            best = (score, a)
    return best[1] if best else None


# ── B2 双图对照（期望 vs 实际；复用共享 IR，不 fork——§13.5 评估结论） ──

def _norm_sem(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _find_asset_for_item(item: Dict[str, Any], pid: str) -> Optional[Dict[str, Any]]:
    """按 target 锚点在库内 active 资产中定位（双图对照"实际"侧数据源）。"""
    target = item.get("target") or {}
    f = _norm(target.get("file") or "")
    sym = (target.get("symbol") or "").strip()
    if not f and not sym:
        return None
    rows = _store.SemanticAssetsStore.all_status(pid, limit=4000)
    for a in rows:
        if (a.get("status") or "active") != "active":
            continue
        files = {_norm(r.get("file") or "") for r in (a.get("astRefs") or []) if r.get("file")}
        syms = {r.get("symbol") for r in (a.get("astRefs") or []) if r.get("symbol")}
        if f and f not in files:
            continue
        if sym and sym not in syms:
            continue
        return a
    return None


def _units_to_flowchart(units: List[Dict[str, Any]], prefix: str,
                        missing_set: set, extra_set: set) -> Dict[str, Any]:
    """行为单元(steps/fields) → flowchart DiagramSchema。

    差异高亮用**既有 IR 字段**（DiagramNode.style.stroke），不扩展 IR：
    期望侧 missing（实现缺失）红描边；实际侧 extra（实现多余）琥珀描边。
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    for i, u in enumerate(units):
        sem = (u.get("semantic") or "").strip() or f"#{i + 1}"
        nid = f"{prefix}-{i}"
        node: Dict[str, Any] = {"id": nid, "label": sem, "kind": "rect"}
        norm = _norm_sem(sem)
        if norm in missing_set:
            node["style"] = {"stroke": "#ef4444", "fill": "#ef444410"}
        elif norm in extra_set:
            node["style"] = {"stroke": "#f59e0b", "fill": "#f59e0b10"}
        nodes.append(node)
        if i > 0:
            edges.append({"from": f"{prefix}-{i - 1}", "to": nid,
                          "kind": "solid", "arrow": "filled"})
    return {"version": 1, "type": "flowchart", "direction": "TB",
            "nodes": nodes, "edges": edges}


def _behavior_units(behavior: Dict[str, Any]) -> List[Dict[str, Any]]:
    steps = behavior.get("steps") or []
    if steps:
        return [{"semantic": s.get("semantic") or ""} for s in steps]
    return [{"semantic": f.get("name") or ""} for f in (behavior.get("fields") or [])]


def dual_diagram(item_id: str, pid: str = "") -> Dict[str, Any]:
    """B2 双图对照：契约条目期望子图 vs 匹配资产实际子图（复用共享 IR，差异用既有 style 字段）。"""
    item = ContractItemStore.get(item_id, pid or None)
    if not item:
        raise LookupError(f"契约条目不存在: {item_id}")
    pid = pid or item.get("projectId") or ""
    asset = _find_asset_for_item(item, pid)
    exp_units = _behavior_units(item.get("behavior") or {})
    act_units = _behavior_units((asset or {}).get("detail") or {})
    exp_sem = {_norm_sem(u["semantic"]) for u in exp_units if _norm_sem(u["semantic"])}
    act_sem = {_norm_sem(u["semantic"]) for u in act_units if _norm_sem(u["semantic"])}
    missing = {s for s in exp_sem if s not in act_sem}
    extra = {s for s in act_sem if s not in exp_sem}
    return {
        "itemId": item_id,
        "assetId": (asset or {}).get("id") or "",
        "assetName": (asset or {}).get("name") or "",
        "expected": _units_to_flowchart(exp_units, "exp", missing, set()),
        "actual": _units_to_flowchart(act_units, "act", set(), extra),
        "diffs": ([{"type": "missing", "semantic": s} for s in sorted(missing)]
                  + [{"type": "extra", "semantic": s} for s in sorted(extra)]),
    }


def check_l1(item: Dict[str, Any],
             asset: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """L1 覆盖性：期望 target 是否已被实现（锚定存在）。"""
    target = item.get("target") or {}
    if item.get("intentOnly") or (not target.get("file") and not target.get("symbol")):
        return "partial", {
            "assetId": (asset or {}).get("id") or "",
            "detail": "意图级期望（无锚点），覆盖性不可机械验证，需人工判定"}
    if asset:
        return "pass", {
            "assetId": asset.get("id"),
            "anchors": (asset.get("astRefs") or [])[:5],
            "detail": f"匹配资产「{asset.get('name')}」(kind={asset.get('kind')}, "
                      f"level={asset.get('level')})"}
    return "fail", {
        "assetId": "",
        "detail": f"当前变更范围内未找到匹配 target "
                  f"{target.get('file') or ''}::{target.get('symbol') or ''} 的资产"}


def _seq_ratio(expected: List[Any], actual: List[Any]) -> Tuple[float, str]:
    """顺序命中比：每条期望语义在实现结构中命中(互相包含即视为同一语义)。"""
    if not expected:
        return 1.0, "无期望声明"
    if not actual:
        return 0.0, "实现无对应结构"
    hits = 0
    for e in expected:
        es = ((e.get("semantic") or "") if isinstance(e, dict) else str(e)).strip()
        if not es:
            continue
        for a in actual:
            as_ = ((a.get("semantic") or "") if isinstance(a, dict) else str(a)).strip()
            if not as_:
                continue
            if es in as_ or as_ in es:
                hits += 1
                break
    return hits / len(expected), f"{hits}/{len(expected)} 命中"


def check_l2(item: Dict[str, Any],
             asset: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """L2 行为符合性：声明的行为期望 vs 资产 detail（steps/branches/fields/relations）。"""
    if not asset:
        return "fail", {"assetId": "", "detail": "L1 未过，无资产可比对"}
    b = item.get("behavior") or {}
    detail = asset.get("detail") or {}
    ratios: List[float] = []
    notes: List[str] = []
    if b.get("steps"):
        r, note = _seq_ratio(b["steps"], detail.get("steps") or [])
        ratios.append(r)
        notes.append(f"steps {note}")
    if b.get("branches"):
        r, note = _seq_ratio(b["branches"], detail.get("branches") or [])
        ratios.append(r)
        notes.append(f"branches {note}")
    if b.get("fields"):
        exp = {((f.get("name") if isinstance(f, dict) else str(f)) or "").strip()
               for f in b["fields"]}
        exp.discard("")
        if exp:
            act = {(f.get("name") or "") for f in (detail.get("fields") or [])
                   if isinstance(f, dict)}
            hits = len(exp & act)
            ratios.append(hits / len(exp))
            notes.append(f"fields {hits}/{len(exp)}")
    if b.get("relations"):
        exp = {(r.get("target") or "") for r in b["relations"]
               if isinstance(r, dict)}
        exp.discard("")
        if exp:
            act = {(r.get("target") or "") for r in (detail.get("relations") or [])
                   if isinstance(r, dict)}
            hits = len(exp & act)
            ratios.append(hits / len(exp))
            notes.append(f"relations {hits}/{len(exp)}")
    if not ratios:
        return "pass", {"assetId": asset.get("id"),
                        "detail": "未声明行为级期望（L2 跳过）", "notes": []}
    avg = sum(ratios) / len(ratios)
    verdict = "pass" if avg >= 0.99 else ("partial" if avg >= 0.5 else "fail")
    return verdict, {"assetId": asset.get("id"),
                     "detail": f"行为符合性 {avg:.0%}", "notes": notes}


# ── 验收执行（触发 → 严 profile 提取 → L1/L2 事实落库） ─────────

def run_acceptance(pid: str, root: str, project: str, package_id: str,
                   trigger_type: str = "manual", ref: str = "",
                   base_commit: str = "") -> Dict[str, Any]:
    """触发验收：变更范围严 profile 提取 → 逐条目 L1/L2 机械比对 → 报告落库。

    条目 → verifying（等待设计者判定）；不自动判定、不自动激活 L3。
    """
    from .agent_roles import role_model_id
    from .semantic_assets import changed_files, extract_scope

    pkg = ContractPackageStore.get(package_id, pid)
    if not pkg:
        raise LookupError(f"契约包不存在: {package_id}")
    items = [i for i in
             (ContractItemStore.get(iid, pid) for iid in pkg.get("itemIds") or [])
             if i]
    # 状态机守卫：仅可验收态条目进入 verifying（draft/accepted/rejected 不受触碰）
    items = [i for i in items
             if i.get("status") in ("confirmed", "injected", "verifying")]
    if not items:
        raise ValueError("契约包没有可验收条目(confirmed/injected/verifying)")

    # 1) 变更范围：
    #    S2 任务分支协议优先——base_commit 给定时用 git diff base...HEAD（工程目录
    #    已在任务分支，worktree 落地后是干净的，脏 diff 不再可信）；
    #    否则回退 git worktree diff vs baseline；仍无变更 → 条目 target 文件兜底。
    if base_commit and root:
        from .branch_service import branch_diff
        files = sorted({_norm(f["path"]) for f in branch_diff(root, base_commit) if f.get("path")})
    else:
        diff = changed_files(root, project) if root else {"added": [], "modified": []}
        files = sorted({_norm(f) for f in
                        (diff.get("added") or []) + (diff.get("modified") or []) if f})
    if not files:
        files = sorted({_norm((it.get("target") or {}).get("file") or "")
                        for it in items if (it.get("target") or {}).get("file")})

    # 2) 严 profile 提取（规则候选 + LLM 定向互证；提取角色模型映射生效）
    res = extract_scope(root, project, "files", "acceptance", files=files,
                        kinds=asset_framework.allowed_kinds(pid),
                        model_id=role_model_id("extract"),
                        use_llm=True, level="implementation")
    extracted = res.get("assets") or []
    logger.info("[acceptance] 严 profile 提取: files=%d assets=%d degraded=%s",
                len(files), len(extracted), res.get("degraded"))

    # 3) 逐条目 L1/L2 机械比对（facts 落库；条目 → verifying）
    report = AcceptanceStore.create_report(
        pid, package_id, {"type": trigger_type, "ref": ref, "files": files},
        profile="strict")
    n_pass = n_fail = n_partial = 0
    for it in items:
        asset = _match_asset(it, extracted)
        v1, e1 = check_l1(it, asset)
        v2, e2 = check_l2(it, asset)
        AcceptanceStore.add_fact(pid, report["id"], it["id"], "L1", v1, e1)
        AcceptanceStore.add_fact(pid, report["id"], it["id"], "L2", v2, e2)
        ContractItemStore.set_status(it["id"], "verifying", "")
        verdicts = {v1, v2}
        if "fail" in verdicts:
            n_fail += 1
        elif "partial" in verdicts:
            n_partial += 1
        else:
            n_pass += 1
    summary = {"total": len(items), "pass": n_pass, "fail": n_fail,
               "awaitingHuman": n_partial,
               "degraded": bool(res.get("degraded")),
               "l3AwaitingHuman": (n_fail + n_partial) > 0}
    AcceptanceStore.update_summary(report["id"], summary)
    return AcceptanceStore.report_detail(report["id"], pid) or {}


# ── L3 参考意见（仅手动激活；模型辅助，设计者主判） ──────────────

_CONF_RE = re.compile(r"置信度[:：]\s*(0(\.\d+)?|1(\.0)?)")


def _parse_confidence(text: str) -> float:
    m = _CONF_RE.search(text or "")
    if not m:
        return 0.5
    try:
        return max(0.0, min(1.0, float(m.group(1))))
    except (TypeError, ValueError):
        return 0.5


def activate_l3_opinion(pid: str, report_id: str, item_id: str,
                        instruction: str = "", trigger_by: str = "") -> Dict[str, Any]:
    detail = AcceptanceStore.report_detail(report_id, pid)
    if not detail:
        raise LookupError(f"验收报告不存在: {report_id}")
    item = ContractItemStore.get(item_id, pid)
    if not item:
        raise LookupError(f"契约条目不存在: {item_id}")
    facts = [f for f in detail["facts"] if f.get("itemId") == item_id]

    asset_line = ""
    aid = next((f.get("evidence") or {}).get("assetId")
               for f in facts if (f.get("evidence") or {}).get("assetId"))
    if aid:
        a = _store.SemanticAssetsStore.get(aid)
        if a:
            asset_line = json.dumps(
                {"name": a.get("name"), "kind": a.get("kind"),
                 "desc": a.get("desc"), "detail": a.get("detail") or {}},
                ensure_ascii=False)

    messages = [
        {"role": "system",
         "content": "你是 TopoCode architect 的 L3 语义验收判断器。你的输出只是参考意见，"
                    "不是判定——通过/打回由设计者决定。请对照契约条目期望与实现事实，"
                    "指出语义缺口与风险（可验证的具体点），结尾单独一行输出"
                    "「置信度: 0.0~1.0」。"},
        {"role": "user",
         "content": (
             "## 契约条目期望（设计者已确认）\n"
             + json.dumps({k: item.get(k) for k in
                           ("kind", "level", "target", "behavior", "zAxis", "acceptance")},
                          ensure_ascii=False, indent=1)
             + "\n\n## L1/L2 机械比对事实\n"
             + json.dumps(facts, ensure_ascii=False, indent=1)
              + (f"\n\n## 实现资产明细\n{asset_line}" if asset_line else "")
              + (("\n\n## 设计者指令\n" + instruction)
                 if instruction else "\n\n请对该条目期望是否被满足给出 L3 语义参考意见。")
          )},
    ]
    from ..agent.turns.catalog import catalog_call
    from .agent_roles import role_model_id
    model_id = role_model_id("verify")   # 存档口径(与目录路由同源)
    res = catalog_call("role:verify", messages)
    content = ((res or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("模型不可用，无法生成 L3 参考意见（请稍后重试）")
    return AcceptanceStore.add_opinion(
        pid, report_id, item_id, content, _parse_confidence(content),
        (res or {}).get("modelId") or model_id or "",
        {"facts": [f.get("id") for f in facts]},
        trigger_by=trigger_by or "user")


# ── 修复指令起草（只起草，不发送——保真纪律） ────────────────────

def draft_fix_instruction(pid: str, item_id: str) -> Dict[str, Any]:
    item = ContractItemStore.get(item_id, pid)
    if not item:
        raise LookupError(f"契约条目不存在: {item_id}")
    fail_facts: List[Dict[str, Any]] = []
    for r in AcceptanceStore.list_reports(pid, limit=20):
        d = AcceptanceStore.report_detail(r["id"], pid)
        if not d:
            continue
        fs = [f for f in d["facts"]
              if f.get("itemId") == item_id and f.get("verdict") == "fail"]
        if fs:
            fail_facts = fs
            break
    messages = [
        {"role": "system",
         "content": "你是 TopoCode architect 的修复指令起草器。基于契约条目期望与失败的"
                    "机械比对事实，起草一份给 coding agent 的修复指令（只起草、不发送；"
                    "由设计者决定是否下发）。要求：只引用事实与期望，不臆测未声明的需求，"
                    "指出需要满足的期望与当前差距。"},
        {"role": "user",
         "content": (
             "## 契约条目期望\n"
             + json.dumps({k: item.get(k) for k in
                           ("kind", "level", "target", "behavior", "acceptance")},
                          ensure_ascii=False, indent=1)
             + "\n\n## 失败的机械比对事实\n"
             + (json.dumps(fail_facts, ensure_ascii=False, indent=1)
                if fail_facts else "（无失败事实——条目可能尚未验收或全部通过）")
         )},
    ]
    from ..agent.turns.catalog import catalog_call
    from .agent_roles import role_model_id
    model_id = role_model_id("verify")   # 存档口径(与目录路由同源)
    res = catalog_call("role:verify", messages)
    content = ((res or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("模型不可用，无法起草修复指令（请稍后重试）")
    return {"instruction": content, "source": "draft", "itemId": item_id,
            "basedOnFacts": len(fail_facts)}


# ── REST ──────────────────────────────────────────────────────

@router.post("/acceptance/run")
async def api_acceptance_run(request: Request):
    """{root?, project?, packageId, triggerType?: manual|runner_done|git_diff, ref?}"""
    body = await request.json() or {}
    pid = _pid(body)
    if not pid:
        return err(400, "projectId 不能为空")
    from .project import _resolve_project
    root = ""
    try:
        proj = _resolve_project(body.get("root"), body.get("project"))
        root = (proj or {}).get("root") or ""
    except Exception:
        root = body.get("root") or ""
    trigger = body.get("trigger") or {}
    if not isinstance(trigger, dict):
        trigger = {}
    try:
        detail = run_acceptance(
            pid, root, body.get("project") or "",
            (body.get("packageId") or "").strip(),
            trigger_type=(trigger.get("type") or body.get("triggerType") or "manual"),
            ref=trigger.get("ref") or body.get("ref") or "")
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    except Exception as e:
        logger.exception("[acceptance] run failed")
        return err(500, f"验收执行失败: {e}")
    return ok(detail)


@router.get("/acceptance/reports")
async def api_acceptance_reports(project: Optional[str] = None,
                                 root: Optional[str] = None,
                                 packageId: str = "", limit: int = 100):
    from .semantic_assets import project_id_for
    pid = project_id_for(root, project)
    if not pid:
        return ok([])
    return ok(AcceptanceStore.list_reports(pid, package_id=packageId, limit=limit))


@router.get("/acceptance/reports/{report_id}")
async def api_acceptance_report_detail(report_id: str,
                                       project: Optional[str] = None,
                                       root: Optional[str] = None):
    from .semantic_assets import project_id_for
    detail = AcceptanceStore.report_detail(report_id, project_id_for(root, project))
    if not detail:
        return err(404, "验收报告不存在")
    return ok(detail)


@router.post("/acceptance/reports/{report_id}/items/{item_id}/opinion")
async def api_acceptance_l3_opinion(report_id: str, item_id: str, request: Request):
    """手动激活 L3：{instruction?, triggerBy?} → 模型辅助参考意见落 opinions 表。"""
    body = await request.json() or {}
    pid = _pid(body)
    try:
        row = activate_l3_opinion(pid, report_id, item_id,
                                  instruction=body.get("instruction") or "",
                                  trigger_by=body.get("triggerBy") or "")
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    except RuntimeError as e:
        return err(503, str(e))
    return ok(row)


@router.post("/acceptance/items/{item_id}/fix-instruction")
async def api_acceptance_fix_instruction(item_id: str, request: Request):
    """起草修复指令（只起草不发送）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    pid = _pid(body) if isinstance(body, dict) else ""
    try:
        row = draft_fix_instruction(pid, item_id)
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    except RuntimeError as e:
        return err(503, str(e))
    return ok(row)


@router.post("/acceptance/items/{item_id}/dual-diagram")
async def api_acceptance_dual_diagram(item_id: str, request: Request):
    """B2 双图对照：契约条目期望子图 vs 匹配资产实际子图（复用共享 IR，§13.5）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    pid = _pid(body) if isinstance(body, dict) else ""
    try:
        return ok(dual_diagram(item_id, pid))
    except (LookupError, ValueError) as e:
        return err(400, str(e))
    except Exception as e:
        logger.exception("[dual-diagram] failed for item %s", item_id)
        return err(500, f"双图对照失败: {e}")
