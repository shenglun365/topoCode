"""资产写操作/提案工具域(asset.semantic.save|update|merge|split + convention/contract.propose) — M3 自 req_agent 机械迁出(逐字保真, 注册随定义点)。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..registry import register_architect_tool

logger = logging.getLogger("arch_routes.req_agent")

@register_architect_tool(
    "asset.semantic.save",
    "对话式提取落库：把按规约产出的语义资产写入项目(归一化管线：框架值域校验/名称继承/墓碑承接)。"
    "资产形态 {name, kind: entity|contract|state|rule|process|decision, level?, desc?, detail?, "
    "astRefs:[{file,symbol,startLine,endLine}]}。实现层资产必须带 astRefs 锚点；"
    "canonicalKey 命中既有资产时旧名优先，LLM 提议名以 proposedNames 返回供设计者定夺。",
)
def tool_asset_semantic_save(root: Optional[str] = None,
                             project: Optional[str] = None,
                             assets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    from ....arch_routes.semantic_assets import save_agent_assets
    return save_agent_assets(root, project, assets or [], executed_by="agent")


@register_architect_tool(
    "asset.semantic.update",
    "认知层编辑既有语义资产(仅改名/描述，overlay 审计)：patch={name? 新名(旧名自动入历史), desc? 新描述}。"
    "与 asset.semantic.save(新建)互补——已提取资产的措辞修正用本工具，勿重复 save。"
    "主库关联项目会拒绝(应在主库界面编辑)，错误信息含深链。",
)
def tool_asset_semantic_update(root: Optional[str] = None,
                               project: Optional[str] = None,
                               assetId: str = "",
                               patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from ....arch_routes.semantic_assets import edit_asset_desc, rename_asset
    patch = patch or {}
    if not (assetId or "").strip():
        return {"error": "assetId 必填"}
    if not patch:
        return {"error": "patch 必填(至少含 name 或 desc)"}
    try:
        out: Dict[str, Any] = {}
        if (patch.get("name") or "").strip():
            out.update(rename_asset(assetId, patch["name"], author="agent"))
        if "desc" in patch:
            out.update(edit_asset_desc(assetId, patch.get("desc") or "", author="agent"))
        if not out:
            return {"error": "patch 无有效字段(仅支持 name/desc)"}
        return out
    except ValueError as e:
        return {"error": str(e)}


@register_architect_tool(
    "asset.semantic.merge",
    "合并语义资产：目标资产(intoId)吸收 targetIds 的锚点(并集)，目标行标记 mergedInto 留痕。"
    "用于设计者判定多个资产实为同一概念时。targetName 可选(合并后改名)。",
)
def tool_asset_semantic_merge(root: Optional[str] = None,
                              project: Optional[str] = None,
                              intoId: str = "",
                              targetIds: Optional[List[str]] = None,
                              targetName: str = "") -> Dict[str, Any]:
    from ....arch_routes.semantic_assets import merge_assets
    try:
        return merge_assets((intoId or "").strip(), list(targetIds or []),
                            (targetName or "").strip(), author="agent")
    except ValueError as e:
        return {"error": str(e)}


@register_architect_tool(
    "asset.semantic.split",
    "拆分语义资产：按锚点组拆出新资产。parts=[{name, anchorKeys:[\"file:symbol\"], desc?}]，"
    "anchorKeys 必须取自原资产 astRefs 的 file:symbol；原资产标记 splitInto 留痕。",
)
def tool_asset_semantic_split(root: Optional[str] = None,
                              project: Optional[str] = None,
                              assetId: str = "",
                              parts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    from ....arch_routes.semantic_assets import split_asset
    try:
        return split_asset((assetId or "").strip(), list(parts or []), author="agent")
    except ValueError as e:
        return {"error": str(e)}


@register_architect_tool(
    "convention.propose",
    "把对话中观察到的命名重复模式固化为命名规约『提案』(pending，待设计者确认，你无决定权)。"
    "当你多次看到设计者把资产改名为同一模式(如统一加 Service/Controller 后缀、"
    "过程用动宾结构)时调用。ruleText 要具体可判定(如『服务以 XxxService 结尾』)；"
    "scenarios 用适用场景(命名=naming/提取=extract/验收=accept/通用=general)。"
    "设计者在界面点『确认』才生效(active)，点『忽略』则删除——你只提议不生效。",
)
def tool_convention_propose(root: Optional[str] = None,
                            project: Optional[str] = None,
                            ruleText: str = "",
                            scenarios: Optional[List[str]] = None,
                            appliesKinds: Optional[List[str]] = None) -> Dict[str, Any]:
    from ....arch_routes import naming as _naming
    from ....arch_routes.semantic_assets import project_id_for
    pid = project_id_for(root, project)
    try:
        row = _naming.propose_convention(
            pid, ruleText or "", scenarios=scenarios or None,
            applies_kinds=appliesKinds or None, author="agent")
        return {"id": row.get("id"), "ruleText": row.get("ruleText"),
                "scenarios": row.get("scenarios"), "status": row.get("status")}
    except ValueError as e:
        return {"error": str(e)}


@register_architect_tool(
    "contract.propose",
    "把对话中讨论出的期望固化为契约条目草稿(draft，待设计者逐条确认，你无判定权)。"
    "items: [{kind: entity|contract|state|rule|process|decision, level?: implementation, "
    "target: {file?, symbol?}, behavior?: {steps?: [{order, semantic, condition?}], "
    "branches?: [{condition, semantic}], fields?: [{name, semantic?}], relations?: [{target, type?}]}, "
    "zAxis?: [{category: observability|resilience|config|security, text, anchor?}], "
    "acceptance?: {mode?: auto|assisted|manual, criteria?, linkedTests?}, "
    "origin: {quote: 设计者原话引用(必填证据), messageId?}, reqId?}]。"
    "kind/level 必须在当前框架值域内；target 无 file 且无 symbol 会自动标为意图级。",
)
def tool_contract_propose(root: Optional[str] = None,
                          project: Optional[str] = None,
                          items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    from ....arch_routes import ctx as _ctx
    from ....arch_routes import contracts as _contracts
    from ....arch_routes.semantic_assets import project_id_for
    pid = project_id_for(root, project)
    conv_id = _ctx.get_conv() or ""
    out: List[Dict[str, Any]] = []
    created = 0
    for it in items or []:
        if not isinstance(it, dict):
            out.append({"error": "item 必须是对象"})
            continue
        try:
            origin = it.get("origin")
            if not isinstance(origin, dict):
                origin = {}
            if not origin.get("convId"):
                origin = {**origin, "convId": conv_id}
            row = _contracts.create_item(pid, {**it, "origin": origin}, author="agent")
            created += 1
            out.append({"id": row.get("id"), "kind": row.get("kind"),
                        "intentOnly": bool(row.get("intentOnly")),
                        "status": row.get("status")})
        except ValueError as e:
            out.append({"error": str(e), "kind": it.get("kind")})
    return {"created": created, "items": out}
