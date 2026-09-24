"""命名治理（项目规约页）— plan-C-M0.md §7.2/§7.3。

命名规约 CRUD + 归纳提议（pending 提案，设计者确认后 active）+ 按场景检索
（agent 注入用，R7 禁全量）；术语表 CRUD + 项目文档导入（source_ref 记来源）；
墓碑参考池管理视图；资产命名历史（墓碑 + overlay 改名重放视图）。

REST（/api/architect 前缀）：
  GET    /naming/conventions?scenario=&status=   规约列表（场景/状态过滤）
  POST   /naming/conventions                     创建（manual）
  PUT    /naming/conventions/{id}                更新（含 status：pending→active 确认）
  DELETE /naming/conventions/{id}                删除
   POST   /naming/conventions/induce              agent 归纳提议（pending 提案）
   POST   /naming/conventions/induce-from-rejection  A1 经验回写（rejected→pending 提案）
   GET    /naming/glossary?q=                     术语表列表
  POST   /naming/glossary                        新增术语
  PUT    /naming/glossary/{id}                   更新术语
  DELETE /naming/glossary/{id}                   删除术语
  POST   /naming/glossary/import                 从项目文档导入
  GET    /naming/tombstones?q=                   参考池查询（管理视图）
  GET    /semantic/assets/{id}/names             命名历史（墓碑 + overlay 重放视图）
"""
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from ..common import err, ok
from ..store import (GlossaryStore, NameTombstoneStore, NamingConventionStore,
                    UserOverlayStore)

logger = logging.getLogger(__name__)

router = APIRouter()

SCENARIOS = ("extract", "accept", "naming", "general")
_CONVENTION_STATUSES = ("pending", "active", "pending_review", "disabled")


def _pid(body: Optional[dict]) -> str:
    data = body or {}
    from .semantic_assets import project_id_for
    return project_id_for(data.get("root"), data.get("project"))


# ── 命名规约 ──────────────────────────────────────────────────

def _validate_scenarios(scenarios: Any) -> Optional[str]:
    if not isinstance(scenarios, list) or not scenarios:
        return "scenarios 必填（场景标签数组，非空）"
    for s in scenarios:
        if s not in SCENARIOS:
            return f"scenario '{s}' 无效（可选: {'/'.join(SCENARIOS)}）"
    return None


def propose_convention(pid: str, rule_text: str,
                       scenarios: Optional[List[str]] = None,
                       scope: str = "project", component_id: str = "",
                       applies_kinds: Optional[List[str]] = None,
                       author: str = "agent") -> Dict[str, Any]:
    """归纳提议核心（agent 工具与 REST induce 端点共用）：建 pending 提案。

    pending 不注入 agent，设计者在界面确认（status→active）或忽略（删除）。
    """
    rule = (rule_text or "").strip()
    if not pid:
        raise ValueError("projectId 不能为空")
    if not rule:
        raise ValueError("ruleText 必填（归纳出的规约文本）")
    scen = scenarios or ["naming"]
    e = _validate_scenarios(scen)
    if e:
        raise ValueError(e)
    row = NamingConventionStore.create(
        pid, rule, scenarios=scen, scope=scope or "project",
        component_id=component_id or "", applies_kinds=applies_kinds or [],
        source="induced", author=author or "agent", status="pending")
    logger.info("[naming] induce 提议 pid=%s scenarios=%s rule=%r", pid, scen, rule)
    return row


# ── A1 经验回写（rejected 失败模式 → 归纳 pending 规约提案） ──────────

def _rejection_facts(pid: str, item_id: str) -> List[Dict[str, Any]]:
    """该条目最近一次验收报告中 L1/L2 失败/部分事实（失败模式证据）。"""
    from ..store import AcceptanceStore
    for rep in AcceptanceStore.list_reports(pid, limit=20):
        detail = AcceptanceStore.report_detail(rep.get("id", ""), pid) or {}
        hits = [f for f in detail.get("facts") or []
                if f.get("itemId") == item_id
                and f.get("verdict") in ("fail", "partial")]
        if hits:
            return hits
    return []


def _induce_rule_llm(item: Dict[str, Any], facts: List[Dict[str, Any]]
                     ) -> Optional[Dict[str, Any]]:
    """LLM（induce 角色）归纳规约；不可达/降级返回 None（调用方回退模板）。"""
    from ..agent.turns.catalog import catalog_call
    target = item.get("target") or {}
    behavior = item.get("behavior") or {}
    fact_lines = []
    for f in facts:
        ev = f.get("evidence") or {}
        notes = "; ".join(ev.get("notes") or [])
        fact_lines.append(f"- {f.get('checkLayer')} {f.get('verdict')}: "
                          f"{ev.get('detail') or ''}{' ' + notes if notes else ''}")
    prompt = (
        "你是治理规约归纳器。一个契约条目被设计者打回（rejected）。\n"
        f"条目: kind={item.get('kind')} level={item.get('level')} "
        f"target.file={target.get('file')} target.symbol={target.get('symbol')}\n"
        f"期望行为: {json.dumps(behavior, ensure_ascii=False)[:600]}\n"
        "失败事实:\n" + ("\n".join(fact_lines) or "（无验收事实）") + "\n"
        "请归纳一条可复用、可判定的治理规约（防同类失败复发）。"
        '输出 JSON {"ruleText": "…", "scenarios": ["accept"]}。'
        "scenarios 只能是 accept/extract/naming/general：行为/覆盖类失败选 accept，"
        "命名类失败选 naming 并加 extract。ruleText 一句话、可操作、不空泛。")
    res = catalog_call(
        "role:induce",
        [{"role": "user", "content": prompt}],
        schema={"type": "object", "properties": {
            "ruleText": {"type": "string"},
            "scenarios": {"type": "array", "items": {"type": "string"}}}})
    out = (res or {}).get("output") if isinstance(res, dict) else None
    if isinstance(out, dict) and (out.get("ruleText") or "").strip():
        scen = out.get("scenarios") or ["accept"]
        if not _validate_scenarios(scen):
            return {"ruleText": out["ruleText"].strip(), "scenarios": scen}
    return None


def _induce_rule_template(item: Dict[str, Any],
                          facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """LLM 降级兜底：从条目+失败事实生成确定性规约（保证闭环不断）。"""
    target = item.get("target") or {}
    sym = target.get("symbol") or ""
    kind = item.get("kind") or "条目"
    head = f"验收 {kind}" + (f"（{sym}）" if sym else "")
    if facts:
        layers = "/".join(sorted({f.get("checkLayer") for f in facts if f.get("checkLayer")}))
        detail = next(((f.get("evidence") or {}).get("detail") for f in facts
                       if (f.get("evidence") or {}).get("detail")), "")
        rule = f"{head} 时，{layers or 'L1/L2'} 层须复核：{detail or '期望与实际的一致性'}，不一致即打回并给出差异。"
    else:
        rule = f"{head} 时，须逐条核对该条目声明的行为期望，未满足即打回。"
    return {"ruleText": rule, "scenarios": ["accept"]}


def induce_from_rejection(pid: str, item_id: str,
                          author: str = "induce") -> Optional[Dict[str, Any]]:
    """A1 经验回写核心：rejected 条目 → 归纳 pending 规约提案（设计者确认后生效）。

    归纳结果按场景（accept）注入后续验收（见 asset_skill.skill_docs），防同类失败复发。
    条目非 rejected → 返回 None；归纳失败不抛（调用方安全）。
    """
    from ..store import ContractItemStore
    item = ContractItemStore.get(item_id, pid or None)
    if not item or item.get("status") != "rejected":
        return None
    facts = _rejection_facts(pid, item_id)
    rule_info = _induce_rule_llm(item, facts) or _induce_rule_template(item, facts)
    row = propose_convention(pid, rule_info["ruleText"],
                             scenarios=rule_info["scenarios"], author=author)
    logger.info("[naming] A1 经验回写 pid=%s item=%s scenarios=%s rule=%r",
                pid, item_id, rule_info["scenarios"], rule_info["ruleText"])
    return row


@router.post("/naming/conventions/induce-from-rejection")
async def api_conventions_induce_from_rejection(request: Request):
    """A1 经验回写：从 rejected 契约条目归纳 pending 规约提案（设计者确认后生效）。"""
    body = await request.json() or {}
    pid = _pid(body)
    item_id = (body.get("itemId") or "").strip()
    if not pid:
        return err(400, "projectId 不能为空")
    if not item_id:
        return err(400, "itemId 必填")
    row = induce_from_rejection(pid, item_id, author=body.get("author") or "induce")
    if not row:
        return err(400, "条目非 rejected 或归纳失败（未生成提案）")
    return ok(row)


@router.get("/naming/conventions")
async def api_conventions_list(project: Optional[str] = None,
                               root: Optional[str] = None,
                               scenario: str = "", status: str = "active",
                               limit: int = 200):
    from .semantic_assets import project_id_for
    pid = project_id_for(root, project)
    if not pid:
        return ok([])
    # status 缺省 active（agent 注入口径）；管理视图可传 all
    st = "" if status == "all" else (status or "active")
    return ok(NamingConventionStore.list(pid, scenario=scenario, status=st,
                                         limit=limit) if st
              else _conventions_all(pid, scenario, limit))


def _conventions_all(pid: str, scenario: str, limit: int) -> List[dict]:
    """status=all：全状态列表（管理视图；场景过滤仍在 store 层按标签匹配）。"""
    out: List[dict] = []
    for st in ("active", "pending", "pending_review", "disabled"):
        out.extend(NamingConventionStore.list(pid, scenario=scenario, status=st,
                                              limit=limit))
    out.sort(key=lambda c: c.get("updatedAt") or 0, reverse=True)
    return out


@router.post("/naming/conventions")
async def api_conventions_create(request: Request):
    body = await request.json() or {}
    pid = _pid(body)
    if not pid:
        return err(400, "projectId 不能为空")
    rule = (body.get("ruleText") or "").strip()
    if not rule:
        return err(400, "ruleText 必填")
    e = _validate_scenarios(body.get("scenarios"))
    if e:
        return err(400, e)
    row = NamingConventionStore.create(
        pid, rule, scenarios=body["scenarios"],
        scope=body.get("scope") or "project",
        component_id=body.get("componentId") or "",
        applies_kinds=body.get("appliesKinds") or [],
        source=body.get("source") or "manual",
        author=body.get("author") or "",
        framework_version=int(body.get("frameworkVersion") or 0),
        status=body.get("status") or "active")
    return ok(row)


@router.put("/naming/conventions/{row_id}")
async def api_conventions_update(row_id: str, request: Request):
    body = await request.json() or {}
    pid = _pid(body)
    row = NamingConventionStore.get(row_id, pid or None)
    if not row:
        return err(404, "命名规约不存在")
    patch: Dict[str, Any] = {}
    for k_api, k_field in (("ruleText", "ruleText"), ("scope", "scope"),
                           ("componentId", "componentId"),
                           ("appliesKinds", "appliesKinds"),
                           ("author", "author")):
        if k_api in body:
            patch[k_field] = body[k_api]
    if "scenarios" in body:
        e = _validate_scenarios(body["scenarios"])
        if e:
            return err(400, e)
        patch["scenarios"] = body["scenarios"]
    if "status" in body:
        st = body["status"]
        if st not in _CONVENTION_STATUSES:
            return err(400, f"status 无效（可选: {'/'.join(_CONVENTION_STATUSES)}）")
        # pending → active = 设计者确认归纳提议（其余状态迁移自由）
        patch["status"] = st
    if not patch:
        return err(400, "无可更新字段")
    return ok(NamingConventionStore.update(row_id, patch) or row)


@router.delete("/naming/conventions/{row_id}")
async def api_conventions_delete(row_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    pid = _pid(body) if isinstance(body, dict) else ""
    if not NamingConventionStore.get(row_id, pid or None):
        return err(404, "命名规约不存在")
    NamingConventionStore.delete(row_id)
    return ok({"deleted": True})


@router.post("/naming/conventions/induce")
async def api_conventions_induce(request: Request):
    """agent 归纳提议：从用户改名重复模式中生成 pending 提案，设计者确认后 active。"""
    body = await request.json() or {}
    try:
        row = propose_convention(
            _pid(body), body.get("ruleText") or "",
            scenarios=body.get("scenarios") or None,
            scope=body.get("scope") or "project",
            component_id=body.get("componentId") or "",
            applies_kinds=body.get("appliesKinds") or None,
            author=body.get("author") or "agent")
    except ValueError as e:
        return err(400, str(e))
    return ok(row)


# ── 术语表 ────────────────────────────────────────────────────

@router.get("/naming/glossary")
async def api_glossary_list(project: Optional[str] = None,
                            root: Optional[str] = None,
                            q: str = "", limit: int = 500):
    from .semantic_assets import project_id_for
    pid = project_id_for(root, project)
    if not pid:
        return ok([])
    return ok(GlossaryStore.list(pid, q=q, limit=limit))


@router.post("/naming/glossary")
async def api_glossary_create(request: Request):
    body = await request.json() or {}
    pid = _pid(body)
    if not pid:
        return err(400, "projectId 不能为空")
    term = (body.get("term") or "").strip()
    if not term:
        return err(400, "term 必填")
    row = GlossaryStore.create(pid, term,
                               alias=body.get("alias") or [],
                               definition=body.get("definition") or "",
                               source=body.get("source") or "manual",
                               source_ref=body.get("sourceRef") or "",
                               author=body.get("author") or "")
    return ok(row)


@router.put("/naming/glossary/{row_id}")
async def api_glossary_update(row_id: str, request: Request):
    body = await request.json() or {}
    pid = _pid(body)
    if not GlossaryStore.get(row_id, pid or None):
        return err(404, "术语不存在")
    patch: Dict[str, Any] = {}
    for k in ("term", "alias", "definition", "source", "sourceRef", "author"):
        if k in body:
            patch[k] = body[k]
    if not patch:
        return err(400, "无可更新字段")
    return ok(GlossaryStore.update(row_id, patch) or {})


@router.delete("/naming/glossary/{row_id}")
async def api_glossary_delete(row_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    pid = _pid(body) if isinstance(body, dict) else ""
    if not GlossaryStore.get(row_id, pid or None):
        return err(404, "术语不存在")
    GlossaryStore.delete(row_id)
    return ok({"deleted": True})


_LINE_RE = re.compile(r"^\s*(?:[-*]\s+|\*\*)?([^:：|—\-]{1,60}?)(?:\*\*)?\s*[:：|—]\s*(.+)$")


def _parse_terms_file(text: str, path: str) -> List[Dict[str, str]]:
    """解析术语文件：JSON（数组/对象）或行式（term: definition / term | definition）。"""
    stripped = (text or "").strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            out: List[Dict[str, str]] = []
            if isinstance(data, dict):
                for term, definition in data.items():
                    out.append({"term": str(term),
                                "definition": definition if isinstance(definition, str)
                                else json.dumps(definition, ensure_ascii=False)})
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("term"):
                        out.append({"term": str(item["term"]),
                                    "definition": item.get("definition") or "",
                                    "alias": json.dumps(item["alias"], ensure_ascii=False)
                                    if item.get("alias") else ""})
            return out
        except (ValueError, TypeError):
            pass
    out = []
    for line in stripped.splitlines():
        m = _LINE_RE.match(line)
        if m:
            term = m.group(1).strip().strip("*").strip()
            definition = m.group(2).strip()
            if term:
                out.append({"term": term, "definition": definition})
    return out


@router.post("/naming/glossary/import")
async def api_glossary_import(request: Request):
    """从项目文档导入术语（source_ref 记来源文件）。"""
    body = await request.json() or {}
    pid = _pid(body)
    if not pid:
        return err(400, "projectId 不能为空")
    from .project import _resolve_project
    proj = _resolve_project(body.get("root"), body.get("project")) or {}
    root = proj.get("rootPath") or proj.get("root") or (body.get("root") or "").strip()
    rel = (body.get("path") or "").strip().lstrip("/")
    if not root or not rel:
        return err(400, "root 与 path 必填")
    full = os.path.realpath(os.path.join(root, rel))
    root_real = os.path.realpath(root)
    if not (full == root_real or full.startswith(root_real + os.sep)) \
            or not os.path.isfile(full):
        return err(400, f"文件不存在或越界: {rel}")
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(512 * 1024)
    except OSError as e:
        return err(400, f"读取失败: {e}")
    parsed = _parse_terms_file(text, rel)
    if not parsed:
        return err(400, "未解析到术语（支持 JSON 数组/对象，或行式 '术语: 定义'）")
    imported: List[dict] = []
    for t in parsed[:500]:  # 单次导入上限 500 条
        row = GlossaryStore.create(pid, t["term"],
                                   alias=json.loads(t["alias"]) if t.get("alias") else [],
                                   definition=t.get("definition") or "",
                                   source="doc_import", source_ref=rel,
                                   author=body.get("author") or "")
        imported.append(row)
    return ok({"imported": len(imported), "sourceRef": rel, "terms": imported})


# ── 墓碑参考池（管理视图） ────────────────────────────────────

@router.get("/naming/tombstones")
async def api_tombstones(project: Optional[str] = None, root: Optional[str] = None,
                         q: str = "", limit: int = 100):
    from .semantic_assets import project_id_for
    pid = project_id_for(root, project)
    if not pid:
        return ok([])
    return ok(NameTombstoneStore.search(pid, q=q, limit=limit))


# ── 资产命名历史（墓碑 + overlay 改名重放视图） ────────────────

@router.get("/semantic/assets/{asset_id}/names")
async def api_asset_names(asset_id: str,
                          project: Optional[str] = None,
                          root: Optional[str] = None):
    from .. import store as _store
    from .semantic_assets import project_id_for
    asset = _store.SemanticAssetsStore.get(asset_id)
    if not asset:
        return err(404, "资产不存在")
    # 以资产行自身 projectId 为准（无 root/project 上下文时也能正确路由）
    pid = asset.get("projectId") or project_id_for(root, project) or ""
    history: List[Dict[str, Any]] = []
    # 1) 墓碑（标准不变的代码变更生命周期：旧名参考池）
    for ref in (asset.get("astRefs") or [])[:3]:
        for tomb in NameTombstoneStore.lookup(
                pid or "", ref.get("file") or "", ref.get("symbol") or "", limit=10):
            history.append({"type": "tombstone", "at": tomb.get("createdAt") or 0,
                            "name": tomb.get("name"), "symbol": tomb.get("symbol"),
                            "file": tomb.get("filePath"),
                            "reason": tomb.get("reason"), "source": tomb.get("source")})
    # 2) overlay 改名重放（用户编辑层，seq 有序）
    for ov in UserOverlayStore.list_active(pid or ""):
        if ov.get("op") == "rename" and asset_id in (ov.get("targetAssetIds") or []):
            payload = ov.get("payload") or {}
            history.append({"type": "overlay", "at": ov.get("createdAt") or 0,
                            "seq": ov.get("seq"), "name": payload.get("newName"),
                            "author": ov.get("author"), "reason": ov.get("reason")})
    # 3) 资产行内溯源（renamedFrom + nameAlias 历史名列表）
    history.append({"type": "asset_row", "at": asset.get("updatedAt") or 0,
                    "renamedFrom": asset.get("renamedFrom") or "",
                    "nameAlias": asset.get("nameAlias") or []})
    history.sort(key=lambda h: (h.get("at") or 0, h.get("type") or ""))
    return ok({"assetId": asset_id, "currentName": asset.get("name"),
               "renamedFrom": asset.get("renamedFrom") or "",
               "nameAlias": asset.get("nameAlias") or [],
               "history": history})
