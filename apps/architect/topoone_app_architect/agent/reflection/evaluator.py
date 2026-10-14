"""WS4 评估器: 变更足迹(plan/diff × 语义资产锚点) + 执行偏差(plan × 实际 diff)。

设计:
- 统一评估对象 = 变更意图(plan 契约) 或 变更事实(执行 diff)——两者都归一为
  file_spans [{path, lines:[{start,end}]}] → 锚点行重叠匹配受影响资产;
- 图文报告: Markdown 表格 + ```diagram IR 围栏(前端确定性渲染) + 资产卡列表
  (经 tool_result 事件透传, 点击联动资产地图图谱/资产卡);
- 偏差检测: 执行 diff 的实际 file_spans × 会话最近 plan 契约 →
  计划外文件/计划外行段/未履约文件, 供用户决策 处理/接纳。
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_FOOT_ASSET_CAP = 40          # 足迹资产上限(报告体量)
_DIAGRAM_NODE_CAP = 14        # 图文节点上限
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


# ── 基础: unified diff → 每文件新增侧行段 ─────────────────────────────

def parse_diff_spans(diff_text: str) -> Dict[str, List[Dict[str, int]]]:
    """unified diff → {path: [{start,end}]}(新侧行段; 新文件段含全部行)。"""
    spans: Dict[str, List[Dict[str, int]]] = {}
    path = ""
    for line in (diff_text or "").splitlines():
        m = _HUNK_RE.match(line)
        if m:
            # hunk 头已给新侧行段 [+start, +start+count-1]; 纯删除(count=0)无新侧足迹
            start = int(m.group(1))
            count = int(m.group(2) or "1")
            if count > 0 and path:
                spans.setdefault(path, []).append(
                    {"start": start, "end": start + count - 1})
            continue
        if line.startswith("+++ b/"):
            path = line[6:].strip() or path
    return spans


def _spans_overlap(a: Dict[str, int], b: Dict[str, int]) -> bool:
    return int(a.get("start", 0)) <= int(b.get("end", 0)) and \
        int(a.get("end", 0)) >= int(b.get("start", 0))


# ── 变更足迹: file_spans × 资产锚点 ────────────────────────────────────

def change_footprint(root: Optional[str], project: Optional[str],
                     file_spans: List[Dict[str, Any]]) -> Dict[str, Any]:
    """file_spans → 受影响语义资产(锚点行重叠) + 资产关系子图(经 semantic_graph)。"""
    from ...sem.engine import project_id_for, semantic_graph
    from ... import store
    pid = project_id_for(root, project)
    if not pid:
        return {"assets": [], "edges": [], "note": "项目未绑定(无语义资产)"}
    by_file: Dict[str, List[Dict[str, int]]] = {}
    for fs in file_spans or []:
        p = str(fs.get("path") or "").strip()
        if p:
            by_file[p] = [{"start": int(l.get("start", 0)), "end": int(l.get("end", 0))}
                          for l in (fs.get("lines") or [])
                          if l.get("start") and l.get("end")] or \
                         [{"start": 1, "end": 10 ** 9}]   # 无行段=整文件命中
    if not by_file:
        return {"assets": [], "edges": [], "note": "无变更范围"}
    hits: List[dict] = []
    for a in store.SemanticAssetsStore.all_status(pid, limit=4000) or []:
        if (a.get("status") or "active") == "deleted":
            continue
        matched: List[str] = []
        for ref in (a.get("astRefs") or []):
            rf = str(ref.get("file") or "")
            rs, re_ = int(ref.get("startLine") or 0), int(ref.get("endLine") or 0)
            for p, spans in by_file.items():
                if rf != p and not rf.endswith("/" + p) and not p.endswith("/" + rf):
                    continue
                if rs <= 0 or re_ <= 0 or any(_spans_overlap({"start": rs, "end": re_}, sp) for sp in spans):
                    matched.append(f"{p}:L{rs}-L{re_}")
                    break
            if matched and len(matched) >= 2:
                break
        if matched:
            hits.append({"id": a.get("id"), "name": a.get("name"), "kind": a.get("kind"),
                         "level": a.get("level") or "", "file": (a.get("astRefs") or [{}])[0].get("file", ""),
                         "status": a.get("status") or "active", "anchors": matched[:3]})
    hits = hits[:_FOOT_ASSET_CAP]
    # 关系子图: 变更文件范围圈子图(semantic_graph files 口径), 节点裁剪到命中集+直接邻居
    edges: List[dict] = []
    try:
        g = semantic_graph(root, project, files=",".join(by_file.keys())) or {}
        hit_ids = {h["id"] for h in hits}
        keep = set(hit_ids)
        for e in (g.get("edges") or []):
            if e.get("from") in hit_ids or e.get("to") in hit_ids:
                edges.append(e)
                keep.add(e.get("from"))
                keep.add(e.get("to"))
        edges = edges[:_DIAGRAM_NODE_CAP * 2]
        for n in (g.get("nodes") or []):
            if n.get("id") in keep and n.get("id") not in hit_ids:
                hits.append({"id": n.get("id"), "name": n.get("name"), "kind": n.get("kind"),
                             "level": n.get("level") or "", "file": "", "status": "active",
                             "anchors": [], "neighbor": True})
    except Exception as e:  # noqa: BLE001
        logger.warning("[evaluator] 子图装配失败: %s", e)
    return {"assets": hits, "edges": edges}


# ── 执行 diff 提取 ────────────────────────────────────────────────────

def execution_diff(root: str, base_commit: str, task_branch: str) -> str:
    """基线→任务分支 diff(unified=0)。分支未创建/无差异 → 抛 ValueError 给上层如实报。"""

    def _git(args: list) -> subprocess.CompletedProcess:
        return subprocess.run(["git"] + args, cwd=root, capture_output=True, text=True)

    def _exists(rev: str) -> bool:
        return _git(["rev-parse", "--verify", "-q", rev]).returncode == 0

    base = base_commit or ""
    if base and not _exists(base):
        raise ValueError(f"基线提交 {base[:12]} 不存在(仓库已重写?)")
    if not _exists(task_branch):
        raise ValueError(f"任务分支 {task_branch} 尚未创建——执行任务未运行或未产生分支")
    r = _git(["diff", "--unified=0", f"{base}...{task_branch}" if base else task_branch])
    if r.returncode != 0:
        raise ValueError(f"git diff 失败: {r.stderr.strip()[:200]}")
    return r.stdout


# ── 偏差检测: 实际 file_spans × plan 契约 ─────────────────────────────

def detect_deviation(plan: Optional[dict], actual: Dict[str, List[Dict[str, int]]]) -> Dict[str, Any]:
    """执行实际变更 × plan 契约 → 偏差集。plan 为空 → 仅事实陈述。"""
    dev: Dict[str, Any] = {"unplannedFiles": [], "outOfSpanLines": [],
                           "untouchedPlannedFiles": [], "matchedFiles": []}
    if not plan:
        dev["note"] = "会话无 plan 契约——仅做事实足迹, 无偏差对照"
        return dev
    planned: Dict[str, List[Dict[str, int]]] = {}
    for f in (plan.get("files") or []):
        p = str(f.get("path") or "").strip()
        if p:
            planned[p] = [{"start": int(l.get("start", 0)), "end": int(l.get("end", 0))}
                          for l in (f.get("lines") or []) if l.get("start") and l.get("end")]
    for p in actual:
        if p not in planned:
            dev["unplannedFiles"].append(p)
            continue
        spans = planned[p]
        if not spans:
            dev["matchedFiles"].append(p)   # 计划整文件级(无行段) → 全算履约
            continue
        out = [sp for sp in actual[p] if not any(_spans_overlap(sp, ps) for ps in spans)]
        if out:
            dev["outOfSpanLines"].append({"file": p, "spans":
                                          [f"L{sp['start']}-L{sp['end']}" for sp in out]})
        else:
            dev["matchedFiles"].append(p)
    for p in planned:
        if p not in actual:
            dev["untouchedPlannedFiles"].append(p)
    return dev


# ── 报告装配 ──────────────────────────────────────────────────────────

def _diagram_ir(foot: Dict[str, Any]) -> str:
    import json
    assets = [a for a in (foot.get("assets") or []) if not a.get("neighbor")][:_DIAGRAM_NODE_CAP]
    if not assets:
        return ""
    ids = {a["id"] for a in assets}
    nodes = [{"id": a["id"], "label": f"{a['name']}({a['kind']})"} for a in assets]
    edges = [{"from": e["from"], "to": e["to"], "label": e.get("type") or ""}
             for e in (foot.get("edges") or [])
             if e.get("from") in ids and e.get("to") in ids]
    ir = {"version": 1, "type": "flowchart", "direction": "LR", "nodes": nodes, "edges": edges}
    return "```diagram\n" + json.dumps(ir, ensure_ascii=False) + "\n```"


def _footprint_md(target_label: str, file_spans, foot: Dict[str, Any]) -> List[str]:
    out = [f"## 变更足迹({target_label})", "",
           "| 文件 | 行区间 |", "|---|---|"]
    for fs in (file_spans or [])[:20]:
        spans = "; ".join(f"L{l.get('start')}-L{l.get('end')}" for l in (fs.get("lines") or [])[:6]) or "整文件"
        out.append(f"| `{fs.get('path')}` | {spans} |")
    assets = foot.get("assets") or []
    out += ["", f"**受影响语义资产 {len(assets)} 个**", "",
            "| 资产 | 类别/粒度 | 锚点 | 状态 |", "|---|---|---|---|"]
    for a in assets[:24]:
        mark = "◦" if a.get("neighbor") else "●"
        out.append(f"| {mark} `{a.get('id')}` {a.get('name')} | {a.get('kind')}/{a.get('level')} "
                   f"| {', '.join(a.get('anchors') or []) or a.get('file', '')} | {a.get('status')} |")
    return out


def _deviation_md(dev: Dict[str, Any]) -> List[str]:
    if dev.get("note"):
        return ["", f"偏差对照: {dev['note']}"]
    parts = ["", "## 偏差(实际执行 × plan 契约)", ""]
    if dev.get("matchedFiles"):
        parts.append(f"- ✅ 履约文件: {', '.join(f'`{p}`' for p in dev['matchedFiles'][:10])}")
    if dev.get("unplannedFiles"):
        parts.append(f"- ⚠️ 计划外文件: {', '.join(f'`{p}`' for p in dev['unplannedFiles'][:10])}")
    if dev.get("outOfSpanLines"):
        for x in dev["outOfSpanLines"][:10]:
            parts.append(f"- ⚠️ 计划外行段: `{x['file']}` {', '.join(x['spans'][:6])}")
    if dev.get("untouchedPlannedFiles"):
        parts.append(f"- ⏸ 未履约文件(plan 有但未改): {', '.join(f'`{p}`' for p in dev['untouchedPlannedFiles'][:10])}")
    if not (dev.get("unplannedFiles") or dev.get("outOfSpanLines") or dev.get("untouchedPlannedFiles")):
        parts.append("- ✅ 与方案一致, 无偏差")
    parts += ["", "**处理 / 接纳由你决策**: 计划外变更若属必要可补一轮 plan 对齐; 未履约项可追问执行 agent 或重新执行。"]
    return parts


def run_evaluate(conv_id: str, target: str = "plan",
                 root: Optional[str] = None, project: Optional[str] = None) -> Dict[str, Any]:
    """评估入口: 方案评估(变更足迹×语义资产影响面)。返回 {markdown, assets}; 出错 {error}。

    target: plan(默认)——重构曾丢失此参数致 NameError(cv-157 同类幻影引用)。"""
    from ... import store
    from ...sem.engine import project_id_for
    pid = project_id_for(root, project)

    def _latest_plan() -> Optional[dict]:
        import json as _json
        units = store.ContextUnitsStore.all(conversation_id=conv_id, limit=50) or []
        for u in sorted(units, key=lambda x: x.get("createdAt") or "", reverse=True):
            if (u.get("type") or "") == "plan" and u.get("content"):
                try:
                    return _json.loads(u.get("content"))
                except Exception:
                    continue
        return None

    plan = _latest_plan()
    if (target or "plan") == "plan":
        if not plan:
            return {"error": "会话无 plan 契约——无方案可供评估"}
        file_spans = plan.get("files") or []
        foot = change_footprint(root, project, file_spans)
        md_lines = [f"# 方案评估", "", f"**方案**: {plan.get('summary') or '-'}", ""]
        md_lines += _footprint_md("方案意图", file_spans, foot)
        risks = plan.get("risks") or []
        if risks:
            md_lines += ["", "**方案自述风险**: " + "; ".join(risks[:5])]
        ir = _diagram_ir(foot)
        if ir:
            md_lines += ["", "受影响资产关系子图:", "", ir]
        md_lines += ["", "评估要点: 上述资产的行为/契约若被触碰, 执行后应做结果评估核对偏差。"]
        return {"markdown": "\n".join(md_lines),
                "assets": [a for a in foot["assets"] if not a.get("neighbor")][:12]}

def _read_disposition(task: Optional[dict]) -> Optional[dict]:
    raw = (task or {}).get("deviationDisposition") or ""
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else None
    except Exception:
        return None



def register_evaluator_tools() -> None:
    """注册 capability.evaluate 会话 agent 工具(WS4)。"""
    from ...agent.tools.req_agent import register_architect_tool

    @register_architect_tool(
        "capability.evaluate",
        "图文评估: 评估会话最新方案(变更足迹×语义资产影响面+关系子图)。"
        "报告内资产卡可点击联动资产地图。方案确认前调用",
    brief='图文评估——target=plan 评估会话最新方案(变更足迹×语义资产影响面+关系子图图)；target=execution 评估执行结果(实际 diff 足迹 + 与方案的偏差集)。报告内资产卡可点击联动资产地图。方案确认前/执行完成后调用',
    params_doc='{"target": "plan|execution"}',
    )
    def _capability_evaluate(project: Optional[str] = None,
                             root: Optional[str] = None,
                             target: str = "plan") -> dict:
        from ... import ctx as _ctx
        conv_id = _ctx.get_conv() or ""
        if not conv_id:
            return {"error": "评估需在会话中执行(读取会话 plan 契约)"}
        try:
            return run_evaluate(conv_id, target=target, root=root, project=project)
        except Exception as e:  # noqa: BLE001
            logger.exception("[evaluator] 评估失败")
            return {"error": f"评估失败: {e}"}
