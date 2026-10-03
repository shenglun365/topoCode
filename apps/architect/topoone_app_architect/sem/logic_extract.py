"""逻辑级提取作业编排（批3）：两段式第二段的链式归纳层（需求 3.1-3.4）。

归纳纯函数域(IO 规约+LLM 归纳)已拆至 logic_induce.py(行数门禁纪律)；此处
保留作业编排(_job_extract_logic/_job_analyze_logic/expand_members)与
re-export 接缝(component_view._norm / b3 测试 build_code_anchor 等既有绑定)。

在实现级骨架之上动态按需提取「数据处理链条」资产（LLM 主导 + native 边辅助，
spike-2 实证数据流边链条语义弱，故 LLM 归纳为主、结构化事实做接地校验）：

- 逻辑级类型（需求 1-B 裁决）：process_chain / validation_chain /
  aggregation_chain / orchestration_chain
- IO 规约（需求 3-D）：代码锚点强制（CodeAnchor 必须可解析到 rev+file+lines
  且带提取时 snippet 快照），文字说明仅辅助——「不能以文字代替代码」；
- 级联前置（需求 3-E）：范围内无实现级骨架 → 自动先跑 extract_structural；
- 组成关系（需求 3-C）：detail.members 记成员资产 id 快照，下钻时运行时
  动态解析成员当前状态（不落关联表，成员变更自然反映）。

落库：level='logic'，canonicalKey=kind|logic|scope 指纹（无 AST 锚点退化为
名称派生——_canonical_key 已支持）。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .logic_induce import (  # noqa: F401  re-export 接缝(纯移动兼容)
    LOGIC_KINDS, _assets_brief, _edges_brief, _endpoints, _norm, _PROMPT,
    _read_lines, _recover_chains, build_code_anchor, induce_chains,
    validate_iospec,
)


# ── 作业执行体 ───────────────────────────────────────────────

def _impl_assets_for(pid: str, rev: str, files: Optional[List[str]] = None) -> List[dict]:
    """范围内实现级骨架资产（active；rev 底座∪该视角）。"""
    from ..store import SemanticAssetsStore
    rows = SemanticAssetsStore.search(pid, level="implementation", limit=2000, rev=rev or "")
    if files:
        want = {_norm(f) for f in files}
        rows = [a for a in rows
                if _norm(((a.get("astRefs") or [{}])[0].get("file")) or "") in want]
    return [a for a in rows if a.get("status") == "active"]


def _job_extract_logic(ctx) -> dict:
    """extract_logic 作业（stages 级联：impl 缺失自动先跑结构化提取）。"""
    from . import job_runner
    from .paths import project_id_for, resolve_root
    sc = ctx.scope or {}
    rid = (resolve_root(sc.get("root") or "", sc.get("project")) or "").strip()
    if not rid:
        return {"error": "项目 root 解析失败"}
    pid = project_id_for(rid, sc.get("project"))
    rev = sc.get("rev") or "workspace"
    files = list(sc.get("files") or [])
    model_id = sc.get("modelId") or None

    # stage 0: 实现级前置(缺则结构化提取)
    impl = _impl_assets_for(pid, rev, files or None)
    if len(impl) < 3 and not sc.get("skipImpl"):
        from .structural_extract import extract_structural
        todo = files or [f for f in (sc.get("keys") and [] or [])]
        if not todo:
            return {"error": "范围内无实现级资产且无文件清单可前置提取",
                    "summary": "失败：无实现级前置"}
        ctx.progress(total=len(todo), done=0, saved=0, stage=0)
        extract_structural(rid, sc.get("project"), todo, rev=rev)
        impl = _impl_assets_for(pid, rev, files or None)
    if not impl:
        return {"error": "范围内无实现级资产", "summary": "失败：无实现级前置"}

    # stage 1: LLM 链条归纳 → 逻辑视图(非资产行)
    # mode: free(LLM 自由归纳默认) | structural(图算法构链, 回引不稳模型兜底)
    ctx.progress(total=1, done=0, stage=1)
    chains, diag = induce_chains(rid, impl, rev, model_id, mode=sc.get("mode") or "free",
                                 brief_cap=int(sc.get("briefCap") or 0) or None,
                                 ref_form=sc.get("refForm") or "name")
    from ..store import LogicViewsStore
    from ..store.logic_views import fingerprint_of
    saved_ids: List[str] = []
    for ch in chains:
        members = [m for m in (ch.get("members") or []) if m]
        if not members:
            continue
        fp = fingerprint_of(ch.get("name") or "", members)
        old = LogicViewsStore.by_fingerprint(pid, fp)
        if old:
            LogicViewsStore.update(old["id"], {
                "memberIds": json.dumps(members, ensure_ascii=False),
                "summary": ch.get("summary") or "", "fingerprint": fp})
            saved_ids.append(old["id"])
        else:
            view = LogicViewsStore.create(
                pid, ch.get("name") or "", members, members,
                summary=ch.get("summary") or "", source="extract")
            saved_ids.append(view["id"])
    summary = f"逻辑视图 {len(saved_ids)} 条(候选 {len(chains)})"
    if diag:
        summary += f"；{diag}"
    return {"saved": len(saved_ids), "ids": saved_ids[:20], "diag": diag,
            "summary": summary}


from . import job_runner as _job_runner  # noqa: E402
_job_runner.register("extract_logic", _job_extract_logic)  # noqa: E305


# ── 逻辑视图分析(手动新建：核心节点为种子，agent 沿调用依赖拓展 + LLM 概括) ──

def expand_members(edges: List[tuple], core_ids: List[str], hops: int, cap: int = 500) -> List[str]:
    """从核心资产沿边集无向 BFS 拓展(业务链条上下游都相关)；hops<=0 即仅核心。

    edges: [(from_id, to_id), ...]——调用/依赖关系(无向可达)。
    """
    members = list(dict.fromkeys(core_ids))
    if hops <= 0 or not edges:
        return members[:cap]
    adj: Dict[str, List[str]] = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    seen = set(members)
    frontier = list(members)
    for _ in range(hops):
        nxt: List[str] = []
        for cur in frontier:
            for nb in adj.get(cur, []):
                if nb not in seen:
                    seen.add(nb)
                    nxt.append(nb)
        if not nxt:
            break
        members.extend(nxt)
        frontier = nxt
        if len(members) >= cap:
            break
    return members[:cap]


def graph_outline(assets: List[dict], prefer_core_ids: Optional[List[str]] = None,
                  max_cores: int = 8) -> List[dict]:
    """图谱范围提纲(零 LLM)：核心(选中优先+中心度 top) × 1/2/3 跳邻域。

    边集=资产 detail.relations(与归纳输入增厚同源)；邻域=expand_members BFS
    ∩ 传入资产集(显示范围)——跳数档由 FE 呈现切换，三档成员一次算齐。
    """
    ids = {a.get("id") for a in assets if a.get("id")}
    edges: List[tuple] = []
    deg: Dict[str, int] = {}
    for a in assets:
        aid = a.get("id") or ""
        for r in (a.get("detail") or {}).get("relations") or []:
            t = str(r.get("target") or "")
            if t in ids and t != aid:
                edges.append((aid, t))
                deg[aid] = deg.get(aid, 0) + 1
                deg[t] = deg.get(t, 0) + 1
    by_id = {a.get("id"): a for a in assets}
    cores: List[str] = []
    for c in (prefer_core_ids or []):
        if c in ids and c not in cores:
            cores.append(c)   # 选中节点优先置顶
    for c, _d in sorted(deg.items(), key=lambda kv: -kv[1]):
        if c not in cores:
            cores.append(c)
        if len(cores) >= max_cores:
            break
    out: List[dict] = []
    for c in cores:
        row = {"coreId": c, "coreName": (by_id.get(c) or {}).get("name") or c,
               "degree": deg.get(c, 0), "hops": {}}
        for h in (1, 2, 3):
            row["hops"][str(h)] = expand_members(edges, [c], h, cap=500)
        out.append(row)
    return out


def summarize_members(assets: List[dict], model_id: Optional[str] = None) -> str:
    """成员全集 → LLM 文字概括(职责/流程/关键依赖，≤300 字)。"""
    from ..agent.cognition.llm import llm_sync
    brief = _assets_brief(assets)
    edges = _edges_brief(assets)
    if edges:
        brief = brief + "\n\n成员间调用/依赖关系:\n" + edges
    prompt = (
        "你是软件架构分析师。下面是一组语义资产(实现级)及其相互关系，"
        "它们组成一条跨文件/跨组件的业务逻辑链。请用不超过 300 字概括：\n"
        "1) 这条链的业务职责(系统在做什么)；2) 处理流程(从哪开始、经哪些环节、到哪结束)；"
        "\n3) 关键依赖与外部 IO。直接输出概括文字，不要列表编号。\n\n" + brief)
    res = llm_sync([{"role": "user", "content": prompt}],
                   mode="chat", model_id=model_id)
    return (((res or {}).get("content") or "").strip())[:600]


def _job_analyze_logic(ctx) -> dict:
    """analyze_logic 作业：核心节点拓展(调用依赖边集) → 成员更新 → LLM 概括。"""
    from .paths import project_id_for, resolve_root
    from ..store import LogicViewsStore, SemanticAssetsStore
    sc = ctx.scope or {}
    rid = (resolve_root(sc.get("root") or "", sc.get("project")) or "").strip()
    if not rid:
        return {"error": "项目 root 解析失败"}
    pid = project_id_for(rid, sc.get("project"))
    view = LogicViewsStore.get(sc.get("viewId") or "")
    if not view:
        return {"error": "逻辑视图不存在", "summary": "失败：视图不存在"}
    expand = sc.get("expand") or "all"
    core_ids = json.loads(view.get("coreIds") or "[]")
    hops = {"core": 0, "1": 1, "2": 2}.get(expand, 99)   # all=可达闭包(hops 大值+cap)
    # 拓展边集：全图谱 relations(存库+派生) —— semantic_graph 一次取全
    ctx.progress(total=2, done=0, stage=0)
    from .engine import semantic_graph
    g = semantic_graph(rid, sc.get("project"), limit=4000)
    id_set = {n.get("id") for n in (g.get("nodes") or [])}
    edges = [(e.get("from"), e.get("to"))
             for e in (g.get("edges") or [])
             if e.get("from") in id_set and e.get("to") in id_set]
    members = expand_members(edges, core_ids, hops)
    ctx.progress(total=2, done=1, stage=0)
    rows = [a for a in SemanticAssetsStore.search(pid, text="", limit=4000)
            if a.get("id") in set(members)]
    summary = summarize_members(rows, sc.get("modelId") or None)
    LogicViewsStore.update(view["id"], {
        "memberIds": json.dumps(members, ensure_ascii=False),
        "summary": summary})
    ctx.progress(total=2, done=2, stage=1)
    return {"saved": 1, "summary": f"成员 {len(members)}(核心 {len(core_ids)})；概括已生成",
            "viewId": view["id"]}


_job_runner.register("analyze_logic", _job_analyze_logic)  # noqa: E305


def start_extract_logic(root: str, project: Optional[str], *,
                        rev: str = "workspace", files: Optional[List[str]] = None,
                        model_id: Optional[str] = None,
                        scope_key: str = "") -> dict:
    from .paths import project_id_for, resolve_root
    from . import job_runner
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"started": False, "reason": "invalid_root"}
    return job_runner.start_job(
        project_id_for(rid, project), "extract_logic",
        scope={"type": "files", "files": files or [], "rev": rev,
               "root": rid, "project": project, "modelId": model_id,
               "scopeKey": scope_key},
        llm=True, stages=["impl", "logic"])
