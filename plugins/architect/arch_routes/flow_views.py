"""图视图 —— flow-view(业务流程活动图) + asset-diagram(实体类图/状态图)。

确定性建图：图结构来自 implDetails 语句清单 + calls 边(行序)；
节点标签优先取验收后资产业务名(按符号匹配)，退化取符号名。
mermaid 生成优先经 reports diagram_tools(build_from_ir)，不可达时内置 emitter 兜底。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_FLOW_NODES = 24


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
        logger.warning("[flow_views] build_from_ir 不可用(用内置 emitter): %s", e)
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


# ── 单入口流图构建 ─────────────────────────────────────────────


def _path_in_text(path: str, text: str) -> bool:
    """path 在文本中的边界匹配(防 /login 误中 /login-with-code)。"""
    if not path:
        return False
    import re as _re
    return _re.search(_re.escape(path) + r"(?![\w-])", text or "") is not None


def _asset_index(assets: List[dict]) -> Dict[str, dict]:
    """符号 → 资产(业务名匹配表)。"""
    idx: Dict[str, dict] = {}
    for a in assets:
        for r in a.get("astRefs") or []:
            sym = (r.get("symbol") or "").strip()
            if sym:
                idx.setdefault(sym, a)
                idx.setdefault(sym.split("::")[-1], a)
    return idx


def _entry_flow(entry: dict, ctx: dict, asset_idx: Dict[str, dict],
                subgraph_by: str) -> Optional[dict]:
    """入口(路由 handler) → 行序事件流 → 图节点/边/步骤文字。"""
    from .asset_rules import RuleContext
    nodes = ctx.get("nodes") or []
    node_by_id = {n.get("id"): n for n in nodes}
    impl_by_file = ctx.get("implDetails") or {}
    impl = impl_by_file.get(entry["file"]) or {}
    rc = RuleContext(ctx.get("edges") or [], impl_by_file, node_by_id)

    handler = entry["symbol"]
    hnode = next((n for n in nodes
                  if (n.get("file_path") or "") == entry["file"]
                  and (n.get("name") == handler
                       or (n.get("qualified_name") or "").endswith(handler))), None)
    if hnode is None:
        return None
    file_ = entry["file"]

    events: List[tuple] = []  # (line, order, etype, payload)
    for i, s in enumerate(impl.get("statements") or []):
        if s.get("enclosing") != handler:
            continue
        if s.get("type") not in ("if", "loop"):
            continue
        ln = int(s.get("startLine") or 0)
        events.append((ln, i, s.get("type"), (s.get("condition") or "").strip()))
    for ln, _i, t in rc.callees_of(hnode):
        if t is None:
            continue
        events.append((ln if isinstance(ln, int) and ln < (1 << 29) else 1 << 29,
                       (1 << 29) - 1, "call", t))
    if not events:
        return None
    events.sort(key=lambda x: (x[0], 0 if x[2] in ("if", "loop") else 1, x[1]))

    # 节点/边
    gnodes: List[dict] = []
    gedges: List[dict] = []
    steps: List[str] = []
    label0 = f"{'/'.join(entry.get('methods') or ['GET'])} {entry.get('path', '')}"
    if entry.get("name") and entry["name"] != handler and entry["name"] not in label0:
        label0 += f" · {entry['name']}"
    start_id = "s0"
    gnodes.append({"id": start_id, "text": label0, "shape": "stadium"})
    prev = start_id
    steps.append(f"入口 {label0}")
    used: set = set()
    for i, (ln, _o, etype, payload) in enumerate(events):
        nid = f"n{i + 1}"
        if etype == "if":
            gnodes.append({"id": nid, "text": payload or "分支判定",
                           "shape": "diamond", "line": ln})
            steps.append(f"[判定] {payload or '分支'} (L{ln})")
        elif etype == "loop":
            gnodes.append({"id": nid, "text": payload or "循环",
                           "shape": "hexagon", "line": ln})
            steps.append(f"[循环] {payload or '循环'} (L{ln})")
        else:
            t: dict = payload
            tname = t.get("name") or "?"
            tfile = t.get("file_path") or ""
            a = asset_idx.get(t.get("qualified_name") or "") or asset_idx.get(tname)
            label = a.get("name") if (a and a.get("name") != tname) else tname
            external = bool(tfile) and tfile != file_
            shape = "parallelogram" if external else "rect"
            if external:
                mod = tfile.split("/")[0] if "/" in tfile else ""
                label = f"{mod}.{tname}" if mod and not label.startswith(mod) else label
            gnodes.append({"id": nid, "text": f"{label} (L{ln})", "shape": shape,
                           "line": ln, "symbol": tname, "file": tfile})
            step = f"调用 {label}"
            if external:
                step += f" → {tfile}"
            steps.append(step + f" (L{ln})")
            if tname in used:  # 重复调用：不新建节点，指向首个(避免自环)
                first = next(g for g in gnodes if g.get("symbol") == tname and g["id"] != nid)
                gnodes.pop()
                if first["id"] != prev:
                    gedges.append({"from": prev, "to": first["id"]})
                prev = first["id"]
                continue
            used.add(tname)
        gedges.append({"from": prev, "to": nid})
        prev = nid
        if len(gnodes) - 1 >= _MAX_FLOW_NODES:
            break
    end_id = "z1"
    gnodes.append({"id": end_id, "text": "结束", "shape": "stadium"})
    gedges.append({"from": prev, "to": end_id})
    steps.append("结束")

    ir: Dict[str, Any] = {"diagram_type": "mermaid", "lang": "mermaid",
                          "diagram": "flowchart", "direction": "TB",
                          "nodes": gnodes, "edges": gedges}
    if subgraph_by == "file":
        by_file: Dict[str, List[str]] = {}
        for g in gnodes:
            if g["id"] in (start_id, end_id):
                continue
            by_file.setdefault(g.get("file") or file_, []).append(g["id"])
        if len(by_file) > 1:
            ir["subgraphs"] = [{"id": f"f{i + 1}", "title": f, "nodes": ids}
                               for i, (f, ids) in enumerate(sorted(by_file.items()))]
    return {"entry": entry, "ir": ir, "mermaid": _build_mermaid(ir),
            "steps": steps,
            "nodes": [{"id": g["id"], "label": g.get("text", ""), "shape": g.get("shape"),
                       "line": g.get("line") or 0, "symbol": g.get("symbol", ""),
                       "file": g.get("file", "")} for g in gnodes]}


def _augment_cross_file_targets(root: str, ctx: dict, ents: List[dict]) -> None:
    """入口函数的跨文件调用目标补名字/文件(codegraph 查询)。

    文件范围上下文的 nodes 只含范围内节点，calls 边目标常在其它文件 →
    图里会丢调用；此处从 codegraph 按节点 id 补最小节点信息。
    """
    if (ctx.get("source") or "") != "codegraph" or not root:
        return
    from .semantic_assets import _open_cg
    node_by_id = {n.get("id"): n for n in ctx.get("nodes") or []}
    # 入口 handler 节点 id
    handler_ids = set()
    for e in ents:
        for n in ctx.get("nodes") or []:
            if (n.get("file_path") or "") == e.get("file") and (
                    n.get("name") == e.get("symbol")
                    or (n.get("qualified_name") or "").endswith(e.get("symbol"))):
                handler_ids.add(n.get("id"))
    missing = {ed.get("target") for ed in ctx.get("edges") or []
               if ed.get("source") in handler_ids and ed.get("kind") == "calls"
               and ed.get("target") and ed.get("target") not in node_by_id}
    if not missing:
        return
    conn = _open_cg(root)
    if conn is None:
        return
    try:
        ph = ",".join("?" * len(missing))
        rows = conn.execute(
            f"SELECT id, name, qualified_name, file_path, signature, docstring "
            f"FROM nodes WHERE id IN ({ph})", tuple(missing)).fetchall()
        for r in rows:
            node_by_id[r["id"]] = {"id": r["id"], "name": r["name"],
                                   "qualified_name": r["qualified_name"],
                                   "file_path": r["file_path"],
                                   "signature": r["signature"] or "",
                                   "docstring": r["docstring"] or "",
                                   "start_line": 0, "end_line": 0}
        ctx["nodes"] = list(node_by_id.values())
    except Exception as ex:
        logger.warning("[flow_views] 跨文件目标补全失败: %s", ex)
    finally:
        conn.close()


# ── flow-view 入口 ─────────────────────────────────────────────


def build_flow_view(root: Optional[str], project: Optional[str],
                    entries: Optional[List[dict]] = None,
                    files: Optional[List[str]] = None,
                    subgraph_by: str = "file") -> Dict[str, Any]:
    """按设定范围生成流程/活动图。

    entries: [{file?, symbol?, path?, methods?, name?, assetId?}]；
    缺省 = 项目内全部 contract 资产(http 关系)作为入口。
    """
    from . import store
    from .semantic_assets import collect_context, project_id_for
    pid = project_id_for(root, project)
    if not pid:
        return {"flows": [], "error": "project 未找到"}
    assets = [a for a in store.SemanticAssetsStore.all(pid, "", limit=400)
              if (a.get("level") or "implementation") == "implementation"
              and (a.get("status") or "active") == "active"]
    asset_idx = _asset_index(assets)

    # 入口解析
    ents: List[dict] = []
    if entries:
        for e in entries[:12]:
            if not isinstance(e, dict):
                continue
            path = str(e.get("path") or "")
            file_ = str(e.get("file") or "")
            sym = str(e.get("symbol") or "")
            a = None
            if e.get("assetId"):
                a = next((x for x in assets if x.get("id") == e.get("assetId")), None)
            if not (path or sym) and a:
                for r in (a.get("detail") or {}).get("relations") or []:
                    if r.get("type") == "http":
                        path = r.get("target") or ""
                        break
                for ref in a.get("astRefs") or []:
                    file_ = file_ or ref.get("file") or ""
                    sym = sym or ref.get("symbol") or ""
            if not (path or sym):
                continue
            ents.append({"file": file_, "symbol": sym.split("::")[-1], "path": path,
                         "methods": e.get("methods") or [],
                         "name": (a or {}).get("name") or e.get("name") or ""})
    else:
        for a in assets:
            if a.get("kind") != "contract":
                continue
            for r in (a.get("detail") or {}).get("relations") or []:
                if r.get("type") != "http":
                    continue
                file_ = (a.get("astRefs") or [{}])[0].get("file") or ""
                sym = (a.get("astRefs") or [{}])[0].get("symbol") or ""
                ents.append({"file": file_, "symbol": sym.split("::")[-1],
                             "path": r.get("target") or "",
                             "methods": r.get("methods") or [],
                             "name": a.get("name") or ""})
                break
    if not ents:
        return {"flows": [], "entries": [], "note": "无 contract 路由入口"}

    # 上下文(涉及文件)
    fset = sorted({e["file"] for e in ents if e["file"]}) or (files or [])
    ctx = collect_context(root, "files", "_", files=fset or None, project=project)
    _augment_cross_file_targets(root, ctx, ents)
    impl_by_file = ctx.get("implDetails") or {}
    # 入口文件无 implDetails 时，用其 contract 路由清单兜底
    for e in ents:
        if e["file"] and e["file"] not in impl_by_file:
            impl_by_file[e["file"]] = {"statements": [], "routes": [], "constants": []}

    # handler 解析：route 节点的 symbol 是路由名(POST:/x) → 反查 handler 函数
    # ① implDetails 路由清单按 path 匹配；② route 节点 references 边兜底。
    node_names = {n.get("name") for n in ctx.get("nodes") or []}
    node_by_id = {n.get("id"): n for n in ctx.get("nodes") or []}
    for e in ents:
        if e.get("symbol") and e["symbol"] in node_names:
            continue
        impl = impl_by_file.get(e.get("file") or "") or {}
        handler = ""
        if e.get("path"):
            for r in impl.get("routes") or []:
                if r.get("path") == e["path"]:
                    handler = r.get("handler") or ""
                    break
        if not handler:
            # route 节点按 文件+path 匹配(节点名形如 "POST /x")，取 references 目标为 handler
            for n in ctx.get("nodes") or []:
                if (n.get("kind") or "").lower() != "route":
                    continue
                if (n.get("file_path") or "") != (e.get("file") or ""):
                    continue
                ntext = f"{n.get('name') or ''} {n.get('qualified_name') or ''}"
                if e.get("path") and _path_in_text(e["path"], ntext):
                    for ed in ctx.get("edges") or []:
                        if ed.get("source") == n.get("id") and ed.get("kind") == "references":
                            t = node_by_id.get(ed.get("target"))
                            if t and (t.get("kind") or "").lower() in ("function", "method"):
                                handler = t.get("name") or ""
                                break
                    break
        if handler and handler in node_names:
            e["symbol"] = handler
        elif e.get("symbol") and e["symbol"].split("::")[-1] in node_names:
            e["symbol"] = e["symbol"].split("::")[-1]

    flows: List[dict] = []
    for e in ents:
        if not e.get("file") or not e.get("symbol"):
            continue
        try:
            fl = _entry_flow(e, ctx, asset_idx, subgraph_by)
        except Exception as ex:
            logger.warning("[flow_views] 入口 %s.%s 建图失败: %s",
                           e.get("file"), e.get("symbol"), ex)
            continue
        if fl:
            flows.append(fl)
    logger.info("[flow_views] flow-view: entries=%d flows=%d files=%d",
                len(ents), len(flows), len(fset))
    return {"flows": flows, "entries": ents}


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
