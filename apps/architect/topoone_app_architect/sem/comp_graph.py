"""组件/文件级图谱 + 节点 AI 解读(资产地图「组件图谱」域)。

comp_graph: 组件目录(catalog) → 组件节点/依赖边 + 变更聚合(asset-compare 同引擎)。
file_graph: 组件范围内文件节点 + imports 结构边(GraphStore) + 文件变更态/变更资产。
node_notes / file_line_notes: 组件·文件级 AI 语义解读——缓存复用 arch_symbol_notes
(symbol_key=comp:<id> / file:<path> / filelines:<file>#<start>-<end>#<md5>)。
"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from typing import List, Optional

from .paths import project_id_for, resolve_root
from .symbols import resolve_base_commit

_MAX_CTX_FILES = 30      # 解读上下文文件清单上限
_MAX_CTX_SYMBOLS = 40    # 解读上下文符号清单上限
_MAX_SNIPPET = 160       # 行解读代码窗口上限
MAX_FILE_NODES = 200     # 文件级图谱节点上限(超出经范围树筛选分批查看)


def _now() -> int:
    import time
    return int(time.time() * 1000)


def _changed_files(cmp_res: dict) -> dict:
    """对比结果 → {status: [file...]}(added/modified/deleted)。"""
    files = cmp_res.get("files") or {}
    return {st: list(files.get(st) or []) for st in ("added", "modified", "deleted")}


def _comp_change_maps(catalog: dict, cmp_res: dict) -> tuple:
    """变更聚合：组件计数表 + 组件→变更文件清单(未归属归 __other__)。"""
    file2comp = {}
    for c in catalog.get("components") or []:
        for f in (c.get("owns") or []):
            file2comp[f] = c["id"]
    counts: dict = defaultdict(lambda: {"added": 0, "modified": 0, "deleted": 0})
    files_by: dict = defaultdict(lambda: defaultdict(list))
    for st, files in _changed_files(cmp_res).items():
        for f in files:
            cid = file2comp.get(f, "__other__")
            counts[cid][st] += 1
            if len(files_by[cid][st]) < 40:
                files_by[cid][st].append(f)
    return counts, files_by


def comp_graph(root: Optional[str], project: Optional[str],
               base: str = "", target: str = "worktree") -> dict:
    """组件级图谱：组件节点(catalog) + dependsOn 边 + 变更徽标聚合。"""
    from ..common import build_component_catalog
    from . import compare as _cmp
    real_root = resolve_root(root, project)
    catalog = build_component_catalog(real_root, project)
    comps = catalog.get("components") or []
    try:
        cmp_res = _cmp.cached_compare(root, project, base, target) or {}
    except Exception:  # noqa: BLE001 — 对比不可用时图谱可用(零变更)
        cmp_res = {}
    counts, files_by = _comp_change_maps(catalog, cmp_res if isinstance(cmp_res, dict) else {})
    nodes = []
    for c in comps:
        ch = counts.get(c["id"], {"added": 0, "modified": 0, "deleted": 0})
        nodes.append({
            "id": c["id"], "name": c.get("name") or c["id"],
            "kind": c.get("kind") or "", "level": c.get("level") or "L0",
            "desc": (c.get("desc") or "")[:200],
            "fileCount": len(c.get("owns") or []),
            "dependsOn": list(c.get("dependsOn") or []),
            "parentId": c.get("parentId") or "",
            "change": ch, "changedFiles": files_by.get(c["id"], {}),
        })
    edges = [{"from": c["id"], "to": d}
             for c in comps for d in (c.get("dependsOn") or [])
             if any(x["id"] == d for x in comps)]
    return {"nodes": nodes, "edges": edges,
            "base": cmp_res.get("base") or base, "target": cmp_res.get("target") or target,
            "noChanges": bool(cmp_res.get("noChanges")),
            "compareError": (cmp_res.get("error") or "") if isinstance(cmp_res, dict) else ""}


def file_graph(root: Optional[str], project: Optional[str], components: List[str],
               base: str = "", target: str = "worktree") -> dict:
    """文件级图谱：多组件范围内的文件节点 + imports 结构边 + 文件变更态。

    边源 = 自管图谱 imports(file→file, baseline 侧)；两端都在节点集才保留。
    """
    from ..common import build_component_catalog
    from ..store.graph import GraphStore
    from . import compare as _cmp
    real_root = resolve_root(root, project)
    pid = project_id_for(real_root, project)
    catalog = build_component_catalog(real_root, project)
    want = [c for c in (components or []) if c]
    comps = [c for c in (catalog.get("components") or []) if c["id"] in want] if want else []
    file_comp: dict = {}
    comp_meta: dict = {}
    for c in comps:
        comp_meta[c["id"]] = {"name": c.get("name") or c["id"], "kind": c.get("kind") or ""}
        for f in (c.get("owns") or []):
            file_comp.setdefault(f, c["id"])
    try:
        cmp_res = _cmp.cached_compare(root, project, base, target) or {}
    except Exception:  # noqa: BLE001
        cmp_res = {}
    fstatus: dict = {}
    for st, files in _changed_files(cmp_res).items():
        for f in files:
            fstatus.setdefault(f, st)
    nodes = [{
        "id": f, "path": f, "name": (f.split("/")[-1] if f else f),
        "compId": cid, "compName": comp_meta.get(cid, {}).get("name") or "",
        "change": fstatus.get(f, ""),
    } for f, cid in sorted(file_comp.items())]
    total_files = len(nodes)
    if total_files > MAX_FILE_NODES:
        # 大范围分批查看: 数量多了看不过来——超出部分经范围树筛选分批
        nodes = nodes[:MAX_FILE_NODES]
        fset = set(n["path"] for n in nodes)
    fset = set(file_comp)
    edges: list = []
    head = resolve_base_commit(real_root, pid) if pid else ""
    if pid and head and fset:
        # 结构依赖多类归并(imports/calls/extends/implements), 去重汇总
        from ..common import normalize_file_ref
        seen_edge = set()
        for kind in ("imports", "calls", "extends", "implements"):
            for e in GraphStore.edges(pid, f"baseline:{head}", kind=kind, limit=100000):
                s = normalize_file_ref(e.get("source") or "", real_root)
                t = normalize_file_ref(e.get("target") or "", real_root)
                if s in fset and t in fset and s != t:
                    k = f"{s}|{t}"
                    if k not in seen_edge:
                        seen_edge.add(k)
                        edges.append({"from": s, "to": t})
    # 范围内变更资产(strong/weak)按文件归组
    changed_assets: dict = defaultdict(list)
    for a in (cmp_res.get("assets") or {}).get("changed") or []:
        if a.get("component") in set(want) and (a.get("files") or [None])[0] in fset:
            changed_assets[(a.get("files") or [""])[0]].append({
                "id": a.get("id"), "name": a.get("name"), "kind": a.get("kind"),
                "strong": bool(a.get("strong")), "side": a.get("side") or ""})
    return {"nodes": nodes, "edges": edges, "changedAssets": changed_assets,
            "components": [{"id": k, **v} for k, v in comp_meta.items()],
            "totalFiles": total_files, "truncated": total_files > MAX_FILE_NODES,
            "maxFileNodes": MAX_FILE_NODES,
            "base": cmp_res.get("base") or base, "target": cmp_res.get("target") or target}


# ---- 组件/文件级 AI 语义解读(arch_symbol_notes 缓存复用) ----

def _comp_ctx(real_root: str, catalog: dict, key: str, cmp_res: dict) -> str:
    from . import compare as _cmp
    comps = {c["id"]: c for c in (catalog.get("components") or [])}
    c = comps.get(key)
    if not c:
        return ""
    counts, files_by = _comp_change_maps(catalog, cmp_res if isinstance(cmp_res, dict) else {})
    ch = counts.get(key, {})
    owns = list(c.get("owns") or [])
    deps = [comps.get(d, {}).get("name") or d for d in (c.get("dependsOn") or [])]
    changed = [f for st in ("added", "modified", "deleted") for f in files_by.get(key, {}).get(st, [])]
    lines = [f"组件: {c.get('name') or key} (kind={c.get('kind') or '?'} level={c.get('level') or '?'})",
             f"描述: {(c.get('desc') or '—')[:300]}",
             f"文件数: {len(owns)}",
             "文件清单(节选):", *[f"- {f}" for f in owns[:_MAX_CTX_FILES]],
             f"依赖组件: {', '.join(deps) or '—'}",
             f"本基线对比变更: +{ch.get('added', 0)} ~{ch.get('modified', 0)} -{ch.get('deleted', 0)}"]
    if changed:
        lines += ["变更文件(节选):", *[f"- {f}" for f in changed[:15]]]
    return "\n".join(lines)


def _file_ctx(real_root: str, pid: str, key: str, cmp_res: dict) -> str:
    from ..store.graph import GraphStore
    from .symbols import resolve_base_commit
    head = resolve_base_commit(real_root, pid) if pid else ""
    symbols: list = []
    if pid and head:
        for n in GraphStore.nodes(pid, f"baseline:{head}", file_path=key, limit=_MAX_CTX_SYMBOLS):
            symbols.append(f"- {n.get('name')} ({n.get('kind')}) L{n.get('startLine')}")
    imports_in: list = []
    imports_out: list = []
    from ..common import normalize_file_ref
    if pid and head:
        for kind in ("imports", "calls", "extends", "implements"):
            for e in GraphStore.edges(pid, f"baseline:{head}", kind=kind, limit=100000):
                s = normalize_file_ref(e.get("source") or "", real_root)
                t = normalize_file_ref(e.get("target") or "", real_root)
                if t == key and s:
                    imports_in.append(s)
                if s == key and t:
                    imports_out.append(t)
    st = ""
    for s, files in _changed_files(cmp_res).items():
        if key in files:
            st = s
            break
    lines = [f"文件: {key}", f"变更态: {st or '无变更'}",
             f"被导入(入边, 节选): {', '.join(imports_in[:15]) or '—'}",
             f"导入(出边, 节选): {', '.join(imports_out[:15]) or '—'}",
             "文件内符号(节选):", *(symbols or ["- (无符号索引)"])]
    path = os.path.join(real_root, key)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                head_lines = [l.rstrip() for l in fh.readlines()[:60]]
            lines += ["文件头部(前 60 行):", "```", *head_lines, "```"]
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(lines)


def node_notes(root: Optional[str], project: Optional[str], kind: str, key: str,
               force: bool = False) -> dict:
    """组件/文件级 AI 语义解读(职责/依赖理由/变更影响)；arch_symbol_notes 缓存。"""
    from .symbol_notes import symbol_note_get, symbol_note_put
    real_root = resolve_root(root, project)
    pid = project_id_for(real_root, project)
    kind = "component" if kind == "component" else "file"
    key = (key or "").strip()
    if not key:
        return {"error": "缺少节点 key", "note": "", "cached": False}
    sk = f"comp:{key}" if kind == "component" else f"file:{key}"
    if not force:
        cached = symbol_note_get(pid, sk) if pid else ""
        if cached:
            return {"note": cached, "cached": True, "degraded": False}
    from ..common import build_component_catalog
    from . import compare as _cmp
    catalog = build_component_catalog(real_root, project)
    try:
        cmp_res = _cmp.cached_compare(root, project, "", "worktree") or {}
    except Exception:  # noqa: BLE001
        cmp_res = {}
    if kind == "component":
        ctx = _comp_ctx(real_root, catalog, key, cmp_res)
        ask = "请解读该组件：职责边界、核心文件分工、对外依赖理由、当前变更可能影响。≤200 字。"
    else:
        ctx = _file_ctx(real_root, pid, key, cmp_res)
        ask = "请解读该文件：在所属组件中的角色、关键符号职责、与导入文件的协作关系、变更影响。≤200 字。"
    if not ctx:
        return {"error": "节点不存在", "note": "", "cached": False}
    from ..agent.turns.catalog import catalog_call
    msgs = [{"role": "system", "content": "你是架构语义解读助手，基于给定的真实仓库上下文作答，不虚构。"},
            {"role": "user", "content": f"{ctx}\n\n{ask}"}]
    try:
        res = catalog_call("role:pseudo", msgs, max_tokens=500)
    except Exception as e:  # noqa: BLE001 — LLM 失败降级不落库
        return {"note": "", "cached": False, "degraded": True, "error": str(e)[:200]}
    note = ((res or {}).get("content") or "").strip()
    if not note:
        return {"note": "", "cached": False, "degraded": True, "error": (res or {}).get("error") or "空回复"}
    if pid:
        symbol_note_put(pid, sk, note)
    return {"note": note, "cached": False, "degraded": False}


def file_line_notes(root: Optional[str], project: Optional[str], file: str,
                    start: int, end: int, force: bool = False) -> dict:
    """文件级行解读(文件卡全文件模式)：无资产耦合，arch_symbol_notes 按窗口缓存。"""
    real_root = resolve_root(root, project)
    pid = project_id_for(real_root, project)
    file = (file or "").strip()
    try:
        start, end = int(start), int(end)
    except (TypeError, ValueError):
        return {"notes": {}, "cached": False, "degraded": True, "error": "行段无效"}
    if not file or start < 1 or end < start:
        return {"notes": {}, "cached": False, "degraded": True, "error": "行段无效"}
    full = os.path.join(real_root, file)
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.read().splitlines()
    except Exception:  # noqa: BLE001
        return {"notes": {}, "cached": False, "degraded": True, "error": "源码不可读"}
    end = min(end, len(all_lines), start + _MAX_SNIPPET - 1)
    codes = all_lines[start - 1:end]
    if not codes:
        return {"notes": {}, "cached": False, "degraded": True, "error": "行段为空"}
    win_hash = hashlib.md5("\n".join(codes).encode("utf-8")).hexdigest()
    from .symbol_notes import symbol_note_get, symbol_note_put
    sk = f"filelines:{file}#{start}-{end}#{win_hash}"
    if not force:
        cached = symbol_note_get(pid, sk) if pid else ""
        if cached:
            try:
                import json
                data = json.loads(cached)
                if isinstance(data, dict) and data.get("notes"):
                    return {"notes": {int(k): str(v) for k, v in data["notes"].items()},
                            "cached": True, "degraded": False}
            except Exception:  # noqa: BLE001 — 缓存损坏视同无缓存
                pass
    numbered = "\n".join(f"{start + i}: {l}" for i, l in enumerate(codes))
    from ..agent.turns.catalog import catalog_call
    msgs = [
        {"role": "system",
         "content": "你是代码逐行解读助手。对给出的代码窗口，解释关键行的用途(空行/纯括号行跳过)。"
                    "只输出 JSON 对象：{\"行号\": \"≤60字说明\"}，不要其他文字。"},
        {"role": "user", "content": f"文件: {file}\n```\n{numbered}\n```"},
    ]
    try:
        res = catalog_call("role:pseudo", msgs, max_tokens=1200)
    except Exception as e:  # noqa: BLE001
        return {"notes": {}, "cached": False, "degraded": True, "error": str(e)[:200]}
    import json
    raw = ((res or {}).get("content") or "").strip()
    notes: dict = {}
    try:
        m = raw[raw.index("{"):raw.rindex("}") + 1]
        data = json.loads(m)
        for k, v in (data or {}).items():
            if str(k).isdigit() and start <= int(k) <= end:
                notes[int(k)] = str(v)[:120]
    except Exception:  # noqa: BLE001
        return {"notes": {}, "cached": False, "degraded": True,
                "error": (res or {}).get("error") or "回复格式无效"}
    if not notes:
        return {"notes": {}, "cached": False, "degraded": True, "error": "无可解读行"}
    if pid:
        symbol_note_put(pid, sk, json.dumps({"notes": notes}, ensure_ascii=False))
    return {"notes": notes, "cached": False, "degraded": False, "at": _now()}
