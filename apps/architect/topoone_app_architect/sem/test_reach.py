"""W5 测试可达性与缺口建议（2610-B1）——图加权 Top-N 高风险无测试符号。

- 事实层：scan_test_files（测试文件模式 glob）→ record/read_test_scan
  （自管 KV `arch.testScan.<pid>`，含与上轮 diff）；
- 缺口：图上从测试文件符号出发的可达闭包之外的符号，加权（扇入 × kind
  权重）取 Top-N；证据 = 扇入/文件/行 + 一跳邻域摘要（graph_neighborhood
  depth=1，D-5 多角度呈现的最小落地）；
- 对账：K2 execution_report refs.tests.files（主张）∩ 扫描集（事实）→
  差异（tracking 挂账，ref 定位去重幂等）。

基调：**建议视角，无强制步骤**（adoption-batch1 §1.4）——本模块只产出
供人参考的清单与状态，不构成任何阻断或工单。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from .graph_context import graph_neighborhood
from ..store.graph import GraphStore
from .. import store as _store_mod

TEST_FILE_RE = re.compile(
    r"(test_[^/]*\.py$|[^/]*_test\.py$|[^/]*\.test\.(ts|tsx|js|jsx|mjs)$"
    r"|[^/]*\.spec\.(ts|tsx|js|jsx|mjs)$|[^/]*_test\.go$|[^/]*\.rb$"
    r"|[^/]*Test\.java$|[^/]*Tests\.cs$)", re.IGNORECASE)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", "build",
              ".venv", "venv", ".topo", ".idea", ".vscode"}
_KIND_WEIGHT = {"class": 3, "interface": 3, "struct": 2, "function": 1,
                "method": 1}
# L-3 组件域乘数(deferred-2610): 聚合层(架构核心域)组件内符号权重更高;
# 无组件归属/L0 原子层 = 1.0(查不到恒 1, 行为与无乘数时一致——回退位)
_LEVEL_MULT = {0: 1.0, 1: 1.5, 2: 2.0}
_SCAN_CAP = 20000   # 防御性文件数上限


def _kv_key(pid: str) -> str:
    return f"arch.testScan.{pid}"


def scan_test_files(root: str) -> List[str]:
    """工作区测试文件清单（相对路径，按序；walk 剪枝常见无关目录）。"""
    out: List[str] = []
    r = root or ""
    if not os.path.isdir(r):
        return out
    for dirpath, dirnames, filenames in os.walk(r):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if TEST_FILE_RE.search(fn):
                rel = os.path.relpath(os.path.join(dirpath, fn), r)
                out.append(rel.replace(os.sep, "/"))
        if len(out) >= _SCAN_CAP:
            break
    return sorted(out)


def record_test_scan(pid: str, root: str) -> Dict[str, Any]:
    """扫描 + KV 落档（含与上轮 diff）。纯事实层，失败容错返回 error 字段。"""
    files = scan_test_files(root)
    prev = read_test_scan(pid)
    prev_files = set(prev.get("files") or [])
    cur = set(files)
    out = {"files": files, "count": len(files),
           "diff": {"added": sorted(cur - prev_files),
                    "removed": sorted(prev_files - cur)},
           "at": _now_ms()}
    try:
        from .. import ctx
        from .codegraph import ensure_arch_settings_table
        ensure_arch_settings_table()
        ctx.db().execute(
            "INSERT INTO arch_settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_kv_key(pid), json.dumps(out, ensure_ascii=False)))
    except Exception:  # noqa: BLE001 — 事实层失败不阻塞编排
        out["error"] = "kv_write_failed"
    return out


def read_test_scan(pid: str) -> Dict[str, Any]:
    try:
        from .. import ctx
        from .codegraph import ensure_arch_settings_table
        ensure_arch_settings_table()
        row = ctx.db().execute(
            "SELECT value FROM arch_settings WHERE key=?", (_kv_key(pid),)
        ).fetchone()
        return json.loads(row[0]) if row and row[0] else {}
    except Exception:  # noqa: BLE001
        return {}


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


def _component_index(pid: str, rev: str) -> Dict[str, tuple]:
    """文件 → (组件名, 层级乘数)。无组件数据 → {}(乘数恒 1)。"""
    out: Dict[str, tuple] = {}
    try:
        from ..store.component import ComponentStore
        for c in ComponentStore.list_rev(pid, rev):
            mult = _LEVEL_MULT.get(int(c.get("level") or 0), 1.0)
            for f in c.get("owns") or []:
                out[str(f)] = (str(c.get("name") or c.get("id") or ""), mult)
    except Exception:  # noqa: BLE001 — 组件目录不可用 → 乘数退 1
        pass
    return out


def test_reach_gaps(pid: str, top_n: int = 10, root: str = "") -> List[Dict[str, Any]]:
    """图加权缺口清单：无测试可达符号 × (扇入 × kind 权重) Top-N（建议视角）。"""
    from .graph_context import baseline_rev
    info = baseline_rev(pid)
    rev = info["rev"]
    if not rev:
        return [{"reason": "no_baseline"}]
    nodes = GraphStore.nodes(pid, rev, limit=10000)
    if not nodes:
        return [{"reason": "no_graph"}]
    edges = GraphStore.edges(pid, rev, limit=50000)
    by_id = {n["id"]: n for n in nodes}
    test_files = {f for f in (read_test_scan(pid).get("files") or [])}
    in_test = {n["id"] for n in nodes
               if str(n.get("file_path") or "") in test_files}
    # 可达闭包: 测试文件符号沿**出边**扩散(calls/imports 前向 + contains 父→子)
    # ——测试能触碰到的都算"有测试可达"; 反向边(被谁调用)不扩散(否则全图可达)
    adj: Dict[str, List[str]] = {}
    for e in edges:
        adj.setdefault(e["source"], []).append(e["target"])
    reach = set(in_test)
    frontier = list(in_test)
    while frontier:
        nxt = []
        for nid in frontier:
            for tgt in adj.get(nid, []):
                if tgt not in reach and tgt in by_id:
                    reach.add(tgt)
                    nxt.append(tgt)
        frontier = nxt
    fan_in: Dict[str, int] = {}
    for e in edges:
        if str(e.get("kind") or "").lower() not in ("contains",):
            fan_in[e["target"]] = fan_in.get(e["target"], 0) + 1
    comp_idx = _component_index(pid, rev)
    gaps = []
    for n in nodes:
        if n["id"] in reach or n["id"] in in_test:
            continue
        fi = fan_in.get(n["id"], 0)
        if fi <= 0:
            continue                              # 孤岛符号不进建议(无影响面)
        kind = str(n.get("kind") or "?")
        comp, mult = comp_idx.get(str(n.get("file_path") or ""), ("", 1.0))
        weight = int(round(fi * _KIND_WEIGHT.get(kind, 1) * mult))
        gaps.append({"symbol": str(n.get("qualified_name") or n.get("name")),
                     "kind": kind, "file": str(n.get("file_path") or ""),
                     "line": int(n.get("start_line") or 0),
                     "fan_in": fi, "weight": weight, "component": comp})
    gaps.sort(key=lambda g: -g["weight"])
    top = gaps[:max(1, int(top_n))]
    for g in top:                                  # 最小证据视图(一跳邻域)
        nb = graph_neighborhood(pid, g["symbol"], depth=1, budget=400, root=root)
        g["evidence"] = {"neighborhood": nb.get("outline") or "",
                         "truncated": bool(nb.get("truncated")),
                         "baseline_stale": bool(nb.get("baseline_stale"))}
    return top


def reconcile_tests(pid: str) -> Dict[str, Any]:
    """主张(K2 回执 tests.files) ∩ 事实(扫描集) 对账——差异 tracking 挂账(幂等)。

    只观测不阻断(基调修正①); 挂账去重: 同 ref_id+state 已有 open 项不重复。
    """
    scan = read_test_scan(pid)
    scanned = set(scan.get("files") or [])
    claimed: Dict[str, Dict[str, str]] = {}        # file → taskId
    for u in _store_mod.ContextUnitsStore.all(project_id=pid,
                                              type_="execution_report",
                                              limit=200) or []:
        tests = ((u.get("refs") or {}).get("tests")) or {}
        for f in tests.get("files") or []:
            claimed[str(f.get("path") or "")] = str((u.get("refs") or {})
                                                    .get("taskId") or "")
    claimed_only = sorted(f for f in claimed if f and f not in scanned)
    scanned_only = sorted(f for f in scanned if f not in claimed)
    from ..store.tracking import TRACK_WAITING, TrackingItemsStore, emit
    for f in claimed_only:                          # 主张未落地 → 待核验挂账
        dup = [t for t in (TrackingItemsStore.all(project_id=pid) or [])
               if t.get("refType") == "test_claim" and t.get("refId") == f
               and t.get("state") not in ("done", "cancelled")]
        if dup:
            continue
        emit(category="对账", title=f"回执声称测试未落盘: {f}",
             content="主张该测试文件的任务回执存在, 但事实层扫描未见"
                     "(可能被删除/改名)",
             action_type="核对", creator_role="architect", creator_id="reconcile",
             state=TRACK_WAITING, ref_type="test_claim", ref_id=f, project_id=pid)
    return {"scanned_count": len(scanned), "claimed_count": len(claimed),
            "claimed_only": claimed_only, "scanned_only": scanned_only,
            "scan_at": scan.get("at") or 0}
