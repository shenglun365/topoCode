"""上下文包契约(重定位 P2 核心建设, 裁决 2026-09-26; 三通道分层 C3)。

执行器输入从 instruction 自由文本升级为结构化 brief——主 agent 的
「信息交互与上下文管理」职责落成显式契约:
  specMd(规约: 目标+方案) / assetRefs(资产引用: 允许范围+边界文件) /
  constraints(约束: 明确不做+安全等级) / acceptance(验收判据: 资产比对, 非单测)。

三通道分层(C3, 防语义污染): 事实(代码坐标, 可解析)/意图(用户需求语义)/
推断(架构师方案, 头注「以代码为准」)分节渲染, 冲突约定总则随行——
语义资产名降级为导航别名, 定位以边界文件为准, 执行器被授权质疑描述。

缺字段显式标记 incomplete+missing, 不虚构不静默(定位三原则之「不强硬保底」):
quick 挡直出任务卡无规约属合法形态 → WARN 留痕照常执行, 契约透明降级。
渲染为指令尾部的规范 markdown 段; 结构化 dict 同入 payload 供原生消费。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arch_routes.exec_bridge")


def build_context_pack(task: dict, conv: Optional[dict], root: str,
                       boundary_files: Optional[List[str]] = None) -> Dict[str, Any]:
    """装配上下文包。数据经 store 层(RequirementsStore 规约快照), 不裸写 SQL。

    缺失字段收集进 missing(不虚构缺省值); incomplete=True 时调用方照常下发,
    契约内显式声明缺什么——执行器与用户都看得到。
    """
    task = task or {}
    rid = str(task.get("reqId") or "")
    missing: List[str] = []
    spec_md = ""
    req_md = ""      # 意图通道: 用户需求原文(requirementMd/desc)
    design_md = ""   # 推断通道: 架构师方案(designMd)——渲染带「以代码为准」头注
    allowed_scope: List[str] = []
    scope_out = ""
    acceptance_items: List[str] = []
    milestones_items: List[Dict[str, str]] = []
    if rid:
        try:
            from ...store.core import RequirementsStore
            active = RequirementsStore.spec_active(rid) or {}
            snap = active.get("snapshot") or {}
            req_md = str(snap.get("requirementMd") or "").strip()                 or str(snap.get("desc") or "").strip()
            design_md = str(snap.get("designMd") or "").strip()
            spec_md = design_md or req_md
            allowed_scope = [str(x) for x in (snap.get("allowedScope") or [])][:30]
            scope_out = str(snap.get("scopeOut") or "").strip()
            acc = snap.get("acceptance")
            if isinstance(acc, list):
                acceptance_items = [str(x) for x in acc[:12]]
            ms = snap.get("milestones")
            if isinstance(ms, list):
                milestones_items = [
                    {"id": str(m.get("id") or ""), "title": str(m.get("title") or ""),
                     "doneWhen": str(m.get("doneWhen") or "")}
                    for m in ms[:12] if isinstance(m, dict)
                    and m.get("id") and m.get("title")]
        except Exception as e:  # noqa: BLE001
            logger.warning("[context-pack] 规约读取失败 rid=%s: %s", rid, e)
    if not spec_md:
        missing.append("specMd(规约目标/方案——任务卡未绑定需求规约)")

    safety = str(task.get("safetyClass") or "mutating").strip().lower()
    constraints: List[str] = []
    if scope_out:
        constraints.append(f"明确不做: {scope_out}")
    if allowed_scope:
        constraints.append("改动范围限定: " + ", ".join(allowed_scope[:10]))
    if safety and safety != "mutating":
        constraints.append(f"安全等级: {safety}")

    pack: Dict[str, Any] = {
        "reqId": rid,
        "specMd": spec_md,
        "reqMd": req_md,
        "designMd": design_md,
        "assetRefs": {
            "allowedScope": allowed_scope,
            "boundaryFiles": [str(f) for f in (boundary_files or [])][:50],
        },
        "constraints": constraints,
        "acceptance": (acceptance_items
                       or ["交付后进行资产比对验收(规约声明资产 vs 交付资产)；"
                           "构建/单测由执行器侧自查"]),
        "milestones": milestones_items,
    }
    if missing:
        pack["incomplete"] = True
        pack["missing"] = missing
        logger.warning("[context-pack] 契约不完整 task=%s missing=%s",
                       task.get("id"), missing)
    # W2 图邻域摘要(2610-B1): 焦点=规约 allowedScope 首符号; 开关缺省开可回退;
    # outline 字数受 budget 钳制(1200), 渲染段过 ctx_budget 统一裁剪
    try:
        from ..compensation.overrides import override_enabled, read_overrides
        from ... import store as _s
        enabled = override_enabled(read_overrides(_s.CollabConfigStore.get),
                                   "graph_context_injection")
        pid_of = str(task.get("projectId") or "")
        focus = allowed_scope[0] if allowed_scope else ""
        if enabled and pid_of and focus:
            from ...sem.graph_context import graph_neighborhood
            nb = graph_neighborhood(pid_of, focus, depth=2,
                                    budget=1200, root=root)
            if nb.get("outline"):
                pack["graphNeighborhood"] = {
                    "outline": nb["outline"],
                    "truncated": bool(nb.get("truncated")),
                    "baselineCommit": nb.get("baseline_commit") or "",
                    "baselineStale": bool(nb.get("baseline_stale")),
                }
    except Exception as e:  # noqa: BLE001 — 邻域失败不阻塞契约装配
        logger.warning("[context-pack] 图邻域注入失败: %s", e)
    return pack


# 冲突约定总则(C3 三通道分层): 语义描述降级为导航线索而非事实声明
_CONFLICT_RULE = (
    "> 📌 **事实优先约定**：以上「允许范围/资产」名称为语义导航别名(可能滞后), "
    "修改定位一律以「边界文件」坐标为准; 本契约描述与代码事实冲突时, "
    "以代码为准, 并在开工解读环节明确指出冲突点——你有权且被期望质疑描述。")


def render_context_pack_md(pack: Dict[str, Any]) -> str:
    """上下文包 → 规范 markdown 段(指令尾部追加; 执行器按段取材)。"""
    lines: List[str] = ["## 上下文包(执行契约)"]
    if pack.get("incomplete"):
        lines.append(f"⚠️ 规约要素缺失: {'; '.join(pack.get('missing') or [])}"
                     "——按现有信息执行, 遇歧义先提问。")
    req_md = str(pack.get("reqMd") or "").strip()
    design_md = str(pack.get("designMd") or "").strip()
    spec = str(pack.get("specMd") or "").strip()
    if req_md or design_md:
        # W1-2: 规约含用户可控需求文本 → <request> 数据信封(防执行器指令注入)
        from ..cognition.prompt import wrap_user_request
        if req_md:
            lines.append("### 需求（用户意图）\n" + wrap_user_request(req_md[:1500]))
        if design_md:
            lines.append("### 方案（架构师推断——以代码为准）\n"
                         + wrap_user_request(design_md[:2200]))
    elif spec:
        from ..cognition.prompt import wrap_user_request
        lines.append("### 规约\n" + wrap_user_request(spec[:3000]))
    refs = pack.get("assetRefs") or {}
    scope = refs.get("allowedScope") or []
    boundary = refs.get("boundaryFiles") or []
    if scope or boundary:
        ref_lines = ([f"- 允许范围(语义别名): {', '.join(scope[:10])}"] if scope else [])
        if boundary:
            ref_lines.append(f"- 边界文件(代码坐标): {', '.join(boundary[:15])}")
        lines.append("### 资产引用\n" + "\n".join(ref_lines))
    cons = pack.get("constraints") or []
    if cons:
        lines.append("### 约束\n" + "\n".join(f"- {c}" for c in cons))
    acc = pack.get("acceptance") or []
    if acc:
        lines.append("### 验收判据\n" + "\n".join(f"- [ ] {a}" for a in acc))
    ms = pack.get("milestones") or []
    if ms:
        lines.append("### 关键节点(到达时输出 [[MILESTONE:id 标题]] 标记行)\n"
                     + "\n".join(f"- {m.get('id')}: {m.get('title')}"
                                  + (f"（判据: {m.get('doneWhen')}）"
                                     if m.get("doneWhen") else "")
                                  for m in ms))
    nb = pack.get("graphNeighborhood") or {}
    if nb.get("outline"):
        stale = "（⚠️ 基线可能过期：工作区 HEAD 已前移）" if nb.get("baselineStale") else ""
        lines.append(f"### 图邻域（架构师推断, 以代码为准{stale}）\n{nb['outline']}")
    lines.append(_CONFLICT_RULE)
    return "\n\n".join(lines)


def render_context_pack_slim(pack: Dict[str, Any],
                             docs_dir: str = "") -> str:
    """契约要点版(cv-272): 边界+验收(红线常在)+文档强指引——全文进
    `.topo/docs/`(req_docs.project_docs 投影), 指令瘦身 ~80%。

    无验收判据时保留缺失声明(契约诚实); 指针缺失(docs_dir 空)回落全量渲染
    责任在调用方——本函数假定投影已成功。冲突约定总则随行(C3)。"""
    lines: List[str] = ["## 上下文包(执行契约)"]
    if pack.get("incomplete"):
        lines.append(f"⚠️ 规约要素缺失: {'; '.join(pack.get('missing') or [])}"
                     "——按现有信息执行, 遇歧义先提问。")
    acc = pack.get("acceptance") or []
    if acc:
        lines.append("### 验收判据(红线)\n"
                     + "\n".join(f"- [ ] {a}" for a in acc[:12]))
    cons = pack.get("constraints") or []
    if cons:
        lines.append("### 约束\n" + "\n".join(f"- {c}" for c in cons[:6]))
    if docs_dir:
        lines.append(f"### 需求文档(执行前必读)\n"
                     f"先完整阅读 `{docs_dir}/` 下全部文档(SPEC 规约全文/"
                     "DESIGN 设计方案/ACCEPTANCE 验收判据/BOUNDARY 修改边界)，"
                     "以上述文档为准执行；本文档目录为本任务运行期快照。")
    lines.append(_CONFLICT_RULE)
    return "\n\n".join(lines)
