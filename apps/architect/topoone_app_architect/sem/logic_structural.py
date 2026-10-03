"""语义资产·结构化构链(C 方案, 批1) — 零 LLM 图算法构链 + 每链轻量命名。

背景(批0 实测 2026-10-03): 名称/编号回引不稳定的模型(nex-n2.5-mini/
minicpm5-2b/qwen3.6-27b 等, num 命中率 0-0.5)无法可靠完成「清单→回引」
式归纳。本模块把「找链」交给确定性图算法(detail.relations 边集), LLM 只
做单链命名概括(≤15 成员的短 prompt, 批0 实测 len@15 几乎全稳)——成员
100% 系统构链命中, LLM 在所有模型舒适区。

策略参数化(2026-10-03 裁决: 无硬性档位): 链长区间/条数由调用方传入
(asset profile 探测参数或手动覆盖), 本模块不内置档位。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("arch.logic_structural")

_NAME_PROMPT = (
    "你是资深软件架构分析师。下列成员序列(含各自职责描述)协作完成一个数据加工过程，"
    "请: 1) 判断这条链在语义上是否构成一段合理/完整的数据加工路径(score 0-1, "
    "1=成员连贯构成完整加工流, 0.5=结构连通但语义牵强, 0=明显是调用图巧合"
    "(如工具函数被多方调用拼成的伪链)); 2) 合理的链起一个业务名并概括一句话"
    "(贴着成员做什么说, 不臆造)。"
    '只输出 JSON：{"name":"链名(≤14字)","summary":"一句话概括(≤50字)","score":0.8}。\n'
    "成员序列:\n{seq}\n成员职责:\n{duties}"
)
REVIEW_DROP = 0.5   # 语义评审丢弃线(2026-10-03 先宽松: score<0.5 丢; 缺失/解析失败保留不误伤)


def _norm_key(s: str) -> str:
    t = re.sub(r"[（(【\[].*?[)）\]】]", "", s or "")
    return re.sub(r"\s+", "", t).lower()


def _index(assets: List[dict]) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    """成员解析双索引: 精确(资产名/符号) + norm(剥括号注释归一)。"""
    by_symbol: Dict[str, dict] = {}
    by_norm: Dict[str, dict] = {}
    for a in assets:
        nm = (a.get("name") or "").strip()
        if nm:
            by_symbol.setdefault(nm, a)
            by_norm.setdefault(_norm_key(nm), a)
        for r in (a.get("astRefs") or []):
            sym = (r.get("symbol") or "").strip()
            if sym:
                by_symbol.setdefault(sym, a)
                by_norm.setdefault(_norm_key(sym), a)
    return by_symbol, by_norm


def structural_chains(assets: List[dict], *, min_len: int = 3, max_len: int = 15,
                      top_n: int = 10) -> List[List[str]]:
    """relations 边集 → 简单路径链(确定性, 零 LLM)。

    - 起点: 无入边或入度<出度的节点(数据流上游优先);
    - DFS 最长路径(访问集防环, 深度 ≤ max_len, 全局节点访问预算防爆炸);
    - 链长 < min_len 丢弃; 成员集 Jaccard ≥ 0.6 视为重复链去重;
    - 按路径累计度数权重排序取 top_n。
    """
    by_symbol, by_norm = _index(assets)
    by_id = {a.get("id"): a for a in assets}
    edges: Dict[str, Set[str]] = {}
    indeg: Dict[str, int] = {}
    outdeg: Dict[str, int] = {}
    for a in assets:
        for rel in (a.get("detail") or {}).get("relations") or []:
            tgt_raw = (rel.get("target") or "").strip()
            if not tgt_raw:
                continue
            t = (by_symbol.get(tgt_raw) or by_norm.get(_norm_key(tgt_raw)) or {}).get("id")
            src = a.get("id")
            if not t or not src or t == src or t not in by_id:
                continue
            edges.setdefault(src, set()).add(t)
            indeg[t] = indeg.get(t, 0) + 1
            outdeg[src] = outdeg.get(src, 0) + 1

    def weight(mid: str) -> int:
        return indeg.get(mid, 0) + outdeg.get(mid, 0)

    starts = [a["id"] for a in assets
              if a.get("id") in edges and indeg.get(a["id"], 0) < outdeg.get(a["id"], 0)]
    if not starts:
        starts = list(edges)

    paths: List[List[str]] = []
    budget = [8000]   # 全局 DFS 节点访问预算(525 资产稀疏图足够)

    def dfs(node: str, path: List[str], seen: Set[str]) -> None:
        if budget[0] <= 0:
            return
        budget[0] -= 1
        extended = False
        for nxt in edges.get(node) or ():
            if nxt in seen:
                continue
            extended = True
            if len(path) + 1 <= max_len:
                dfs(nxt, path + [nxt], seen | {nxt})
        if not extended and len(path) >= min_len:
            paths.append(path)

    for s in starts:
        dfs(s, [s], {s})

    paths.sort(key=lambda p: -sum(weight(m) for m in p))
    picked: List[List[str]] = []
    for p in paths:
        ps = set(p)
        if any(len(ps & set(q)) / len(ps | set(q)) >= 0.6 for q in picked):
            continue
        picked.append(p)
        if len(picked) >= top_n:
            break
    return picked


def name_chain(members: List[dict], model_id: Optional[str] = None) -> Optional[dict]:
    """单链命名+概括+语义评审(每链一次轻调用; ≤15 成员短 prompt, LLM 舒适区)。

    score<REVIEW_DROP 判伪链返回 {"drop": True}(调用方丢弃); score 缺失/
    解析失败默认保留(误伤率未知, 宽容先行)。调用失败重采样 1 次; 仍失败
    返回 None(调用方降级命名, 不丢链)。
    """
    from ..agent.cognition.llm import llm_sync
    seq = " → ".join(f"{m.get('name') or m.get('id')}({(m.get('astRefs') or [{}])[0].get('symbol') or ''})"
                     for m in members)
    duties = "\n".join(f"- {m.get('name') or m.get('id')}: {(m.get('desc') or '')[:80]}" for m in members)
    prompt = _NAME_PROMPT.replace("{seq}", seq).replace("{duties}", duties)
    for attempt in (1, 2):
        try:
            res = llm_sync([{"role": "user", "content": prompt}],
                           mode="chat", model_id=model_id)
        except Exception:  # noqa: BLE001 — 调用失败重试一次
            continue
        raw = ((res or {}).get("content") or "").strip()
        try:
            d = json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}", raw, re.S)
            if not m:
                continue
            try:
                d = json.loads(m.group(0))
            except Exception:
                continue
        d = d or {}
        name = str(d.get("name") or "").strip()[:14]
        summary = str(d.get("summary") or "").strip()[:50]
        try:
            score = float(d.get("score"))
        except (TypeError, ValueError):
            score = None
        if score is not None and score < REVIEW_DROP and name:
            return {"drop": True, "score": score}
        if name:
            return {"name": name, "summary": summary, "score": score}
    return None


def structural_induce(root: str, assets: List[dict], rev: str,
                      model_id: Optional[str] = None, *,
                      min_len: int = 3, max_len: int = 15, top_n: int = 10,
                      anchor_fn=None) -> tuple:
    """结构化构链主入口: 图算法构链 → 逐链 LLM 命名 → 锚点兜底组装。

    anchor_fn(root, ref, rev) -> anchor|None: 代码锚构造器由调用方注入
    (依赖倒置——logic_induce 接线时传自身 build_code_anchor, 避免循环
    import; 测试可注入 mock)。返回 (chains, diag), 与 induce_chains 同构。
    """
    by_id = {a.get("id"): a for a in assets}
    raw_chains = structural_chains(assets, min_len=min_len, max_len=max_len, top_n=top_n)
    chains: List[dict] = []
    unnamed = 0
    dropped = 0
    for members_ids in raw_chains:
        members = [by_id[m] for m in members_ids if by_id.get(m)]
        if len(members) < min_len:
            continue
        nm = name_chain(members, model_id)
        if nm and nm.get("drop"):
            dropped += 1   # 语义评审判伪链(调用图巧合): 丢弃
            continue
        if not nm:
            unnamed += 1
            nm = {"name": f"{members[0].get('name') or '链'}→{members[-1].get('name') or ''}",
                  "summary": ""}   # 降级命名: 首尾成员拼接, 不丢链
        # 锚点兜底(与归纳主路径同口径): 首成员入/尾成员出, 恒保代码锚定(3-D)
        def _anchor(a: dict, direction: str) -> list:
            if anchor_fn is None:
                return []
            for r in (a.get("astRefs") or []):
                an = anchor_fn(root, r, rev)
                if an:
                    return [{"id": f"io-st-{direction}", "name": (a.get("name") or "")[:60],
                             "direction": direction, "code": [an],
                             "note": "结构化构链成员锚点"}]
            return []
        chains.append({
            "name": nm["name"], "kind": "process_chain",
            "summary": nm["summary"],
            "inputs": _anchor(members[0], "in"), "outputs": _anchor(members[-1], "out"),
            "members": [m.get("id") for m in members],
        })
    diag = (f"结构化构链 {len(chains)} 条(图算法确定性成员"
            + (f"；{unnamed} 条命名降级" if unnamed else "")
            + (f"；{dropped} 条未通过语义评审(伪链)丢弃" if dropped else "") + ")")
    return chains, diag
