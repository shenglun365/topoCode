"""资产图 —— asset-diagram(实体类图/状态图)。

确定性建图：图结构来自资产 detail(entity 字段/方法、state 状态/迁移)。
mermaid 生成优先经 reports diagram_tools(build_from_ir)，不可达时内置 emitter 兜底。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ── mermaid 生成(reports 优先，内置兜底) ───────────────────────


def _build_mermaid(ir: dict) -> str:
    """IR → mermaid 代码。reports 服务可达时走 build_from_ir(带语法校验)。"""
    try:
        from .diagram import call_build
        res = call_build(ir)
        code = (res or {}).get("code") or ""
        if code.strip():
            return code
    except Exception as e:
        logger.warning("[asset_diagram] build_from_ir 不可用(用内置 emitter): %s", e)
    d = ir.get("diagram")
    if d == "class":
        return _inline_class(ir)
    if d == "state":
        return _inline_state(ir)
    return _inline_flowchart(ir)


_REL_SYMS = {
    "extension": "<|--", "composition": "*--", "aggregation": "o--",
    "association": "-->", "dependency": "..>", "realization": "<|..",
}


def _inline_class(ir: dict) -> str:
    """classDiagram 兜底 emitter(与 reports _class.build_class_diagram 输出同构)。"""
    lines = ["classDiagram"]
    if ir.get("title"):
        lines.append(f"    title {ir['title']}")
    for c in ir.get("classes") or []:
        name = c.get("name") or "?"
        members = c.get("members") or []
        if members:
            lines.append(f"    class {name} {{")
            for m in members:
                parts = []
                if m.get("is_static"):
                    parts.append("{static}")
                if m.get("is_abstract"):
                    parts.append("{abstract}")
                parts.append(m.get("visibility") or "+")
                parts.append(m.get("name") or "")
                if m.get("is_method"):
                    parts.append(f"({m.get('params', '')})")
                if m.get("type"):
                    parts.append(f" : {m['type']}")
                line = "".join(parts).strip()
                if line:
                    lines.append(f"        {line}")
            lines.append("    }")
        else:
            lines.append(f"    class {name}")
    for r in ir.get("relations") or []:
        sym = _REL_SYMS.get(r.get("type", "association"), "-->")
        label = r.get("label", "")
        frm, to = r.get("from", ""), r.get("to", "")
        if label:
            lines.append(f"    {frm} {sym} {to} : {label}")
        else:
            lines.append(f"    {frm} {sym} {to}")
    return "\n".join(lines)


def _inline_state(ir: dict) -> str:
    """stateDiagram-v2 兜底 emitter(与 reports _state.build_state 输出同构)。"""
    lines = ["stateDiagram-v2"]
    if ir.get("title"):
        lines.append(f"    title {ir['title']}")
    for s in ir.get("states") or []:
        sid = s.get("id") or ""
        text = s.get("text") or sid
        if text != sid:
            lines.append(f'    state "{text}" as {sid}')
        else:
            lines.append(f"    state {sid}")
    for t in ir.get("transitions") or []:
        frm, to = t.get("from", ""), t.get("to", "")
        label = t.get("label", "")
        if label:
            lines.append(f"    {frm} --> {to} : {label}")
        else:
            lines.append(f"    {frm} --> {to}")
    return "\n".join(lines)


def _inline_flowchart(ir: dict) -> str:
    """极简 flowchart emitter(与 build_flowchart 输出同构子集)。"""
    lines = [f"flowchart {ir.get('direction', 'TB')}"]
    for sg in ir.get("subgraphs") or []:
        lines.append(f"  subgraph {sg.get('id')} [{sg.get('title') or sg.get('id')}]")
        for nid in sg.get("nodes") or []:
            n = next((x for x in ir.get("nodes") or [] if x.get("id") == nid), None)
            if n:
                lines.append("    " + _node_line(n))
        lines.append("  end")
    sg_ids = {nid for sg in ir.get("subgraphs") or [] for nid in sg.get("nodes") or []}
    for n in ir.get("nodes") or []:
        if n.get("id") not in sg_ids:
            lines.append("  " + _node_line(n))
    for e in ir.get("edges") or []:
        arrow = "-->>" if e.get("style") == "dashed" else "-->"
        if e.get("label"):
            lines.append(f"  {e.get('from')} {arrow}|{e['label']}| {e.get('to')}")
        else:
            lines.append(f"  {e.get('from')} {arrow} {e.get('to')}")
    return "\n".join(lines)


_SHAPE = {
    "rect": ("[", "]"), "round": ("(", ")"), "stadium": ("([", "])"),
    "diamond": ("{", "}"), "hexagon": ("{{", "}}"), "parallelogram": ("[/", "/]"),
}


def _node_line(n: dict) -> str:
    l, r = _SHAPE.get(n.get("shape", "rect"), ("[", "]"))
    text = (n.get("text") or n.get("id") or "").replace('"', "'")
    return f"{n.get('id')} {l}{text}{r}"


# ── asset-diagram(实体类图/状态图) ─────────────────────────────


def build_asset_diagrams(assets: List[dict]) -> Dict[str, Any]:
    """按资产 kind 生成图：entity → classDiagram，state → stateDiagram。"""
    out: List[dict] = []
    for a in assets[:20]:
        kind = a.get("kind")
        detail = a.get("detail") or {}
        name = a.get("name") or "?"
        if kind == "entity":
            members = []
            for f in detail.get("fields") or []:
                members.append({"visibility": "+", "name": f.get("name") or "",
                                "type": f.get("type") or "", "is_method": False})
            for m in detail.get("methods") or []:
                members.append({"visibility": "+", "name": m.get("name") or "",
                                "type": m.get("returnType") or "", "is_method": True})
            ir = {"diagram_type": "mermaid", "lang": "mermaid", "diagram": "class",
                  "title": name, "classes": [{"name": name, "members": members}],
                  "relations": []}
            code = _build_mermaid(ir)
            out.append({"assetId": a.get("id"), "name": name, "type": "class",
                        "mermaid": code})
        elif kind == "state":
            states = [{"id": s.get("name") or f"s{i}", "text": s.get("name") or f"s{i}"}
                      for i, s in enumerate(detail.get("states") or [])]
            trans = []
            for t in detail.get("transitions") or []:
                label = " ".join(x for x in (t.get("event"), t.get("condition")) if x)
                trans.append({"from": t.get("from") or "", "to": t.get("to") or "",
                              "label": label})
            ir = {"diagram_type": "mermaid", "lang": "mermaid", "diagram": "state",
                  "title": name, "states": states, "transitions": trans}
            code = _build_mermaid(ir)
            out.append({"assetId": a.get("id"), "name": name, "type": "state",
                        "mermaid": code})
    return {"diagrams": out}
