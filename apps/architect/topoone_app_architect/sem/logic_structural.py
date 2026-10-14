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


# ── agentic 按需读取(批7, 2026-10-03 用户方向: 必要数据+模型按需调 tool 补全) ──
# 轻量编号摘要入题, LLM 用 JSON action 协议按需查询资产详情(不依赖原生
# function calling, 本地模型友好), 信息足够后输出终答链。保底轮次防无限
# 循环(用户裁决: 资产解析场景 60 轮上限)。

_AGENTIC_SYS = (
    "你是资深软件架构分析师。下面是项目的实现级资产编号摘要(每行一个, 含职责)。"
    "请归纳「数据处理链条」(从输入到输出的完整数据加工路径)。\n"
    "信息不足时可以查询工具, 每次输出一个 JSON: "
    '{"action": {"tool": "asset.semantic.detail", "args": {"asset_id": "sa-xxx"}}} '
    '(查单个资产完整详情: steps/fields/relations) 或 '
    '{"action": {"tool": "asset.semantic.search", "args": {"text": "关键词"}}} '
    '(按关键词检索资产)。\n'
    "信息足够后输出终答(不再查询): "
    '{"chains": [{"name": "链名", "kind": "process_chain", "summary": "一句话", '
    '"members": [编号数组]}]} (4-10 条链, 每链 3-8 个成员编号)。\n'
    "资产编号摘要:\n{digest}"
)

_AGENTIC_TOOLS = ("asset.semantic.detail", "asset.semantic.search")


def _run_agentic_tool(name: str, args: dict, root: str, project: Optional[str]) -> dict:
    """白名单工具执行(直接调 tools/impl 注册实现; 出错返回错误对象不中断)。"""
    try:
        if name == "asset.semantic.detail":
            from ..agent.tools.impl.semantic import tool_semantic_detail as fn
            r = fn(str(args.get("asset_id") or ""), root, project)
            return {"ok": r is not None, "asset": r or "资产不存在"}
        if name == "asset.semantic.search":
            from ..agent.tools.impl.semantic import tool_semantic_search as fn
            rows = fn(root, project, text=str(args.get("text") or ""),
                      limit=min(int(args.get("limit") or 8), 12))
            return {"ok": True, "assets": [
                {"id": r.get("id"), "name": r.get("name"), "desc": (r.get("desc") or "")[:100]}
                for r in (rows or [])]}
        return {"ok": False, "error": f"工具不在白名单: {name}"}
    except Exception as e:  # noqa: BLE001 — 工具失败如实回给模型自行调整
        return {"ok": False, "error": str(e)[:200]}


def agentic_induce(root: str, assets: List[dict], rev: str,
                   model_id: Optional[str] = None, *,
                   max_rounds: int = 60, anchor_fn=None) -> tuple:
    """agentic 按需读取归纳: 轻摘要 → LLM 按需 tool 查询(≤60 轮) → 终答链。

    终答 members 为编号数组(直取摘要序, 与编号引用同口径); 链组装复用
    归纳过滤(锚点兜底)。超轮次返回已得结果并 diag 标注。
    """
    from ..agent.cognition.llm import llm_sync
    digest_lines = []
    order: List[str] = []
    for i, a in enumerate(assets[:200], 1):
        order.append(a.get("id") or "")
        digest_lines.append(f"[{i}] {a.get('name')} ({a.get('id')}): {(a.get('desc') or '')[:60]}")
    sys_p = _AGENTIC_SYS.replace("{digest}", "\n".join(digest_lines))
    msgs: List[dict] = [{"role": "system", "content": sys_p},
                        {"role": "user", "content": "请开始分析(可先查询再终答)。"}]
    by_id = {a.get("id"): a for a in assets}
    tool_calls = 0
    final_raw = ""
    for rnd in range(1, max_rounds + 1):
        res = llm_sync(msgs, mode="chat", model_id=model_id)
        raw = ((res or {}).get("content") or "").strip()
        final_raw = raw
        d = None
        try:
            d = json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                try:
                    d = json.loads(m.group(0))
                except Exception:
                    d = None
        if isinstance(d, dict) and (d.get("chains") is not None):
            break   # 终答
        act = (d or {}).get("action") if isinstance(d, dict) else None
        if isinstance(act, dict) and act.get("tool"):
            tool_calls += 1
            r = _run_agentic_tool(str(act.get("tool")), dict(act.get("args") or {}),
                                  root, None)
            msgs = msgs + [{"role": "assistant", "content": raw[:2000]},
                           {"role": "user", "content": "工具结果: " + json.dumps(r, ensure_ascii=False)[:4000]}]
            continue
        # 非法输出: 纠偏提示(计一轮)
        msgs = msgs + [{"role": "user", "content":
                        '输出格式不符——查询用 {"action":{...}}, 终答用 {"chains":[...]}。'}]
    else:
        pass
    # 解析终答(编号成员 → 资产 id), 锚点兜底组装
    chains: List[dict] = []
    d = None
    try:
        d = json.loads(final_raw)
    except Exception:
        m = re.search(r"\{.*\}", final_raw, re.S)
        if m:
            try:
                d = json.loads(m.group(0))
            except Exception:
                d = None
    seen: set = set()
    for ch in ((d or {}).get("chains") or [])[:12] if isinstance(d, dict) else []:
        member_ids: List[str] = []
        for n in (ch.get("members") or []):
            try:
                k = int(n)
            except (TypeError, ValueError):
                continue
            if 1 <= k <= len(order) and order[k - 1]:
                member_ids.append(order[k - 1])
        if len(member_ids) < 2:
            continue
        key = frozenset(member_ids)
        if key in seen:
            continue
        seen.add(key)

        def _anchor(a: dict, direction: str) -> list:
            if anchor_fn is None:
                return []
            for r in (a.get("astRefs") or []):
                an = anchor_fn(root, r, rev)
                if an:
                    return [{"id": f"io-ag-{direction}", "name": (a.get("name") or "")[:60],
                             "direction": direction, "code": [an],
                             "note": "agentic 成员锚点"}]
            return []
        chains.append({
            "name": (ch.get("name") or "链")[:80], "kind": "process_chain",
            "summary": (ch.get("summary") or "")[:400],
            "inputs": _anchor(by_id.get(member_ids[0]) or {}, "in"),
            "outputs": _anchor(by_id.get(member_ids[-1]) or {}, "out"),
            "members": member_ids,
        })
    diag = (f"agentic 按需读取 {len(chains)} 条(工具查询 {tool_calls} 次/轮次上限 {max_rounds})")
    return chains, diag
