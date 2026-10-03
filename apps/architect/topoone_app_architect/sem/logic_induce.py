"""逻辑链条 LLM 归纳域(自 logic_extract 拆分, 行数门禁 §8.2 纪律：纯移动)。

IO 规约基础设施(_norm/_read_lines/build_code_anchor/validate_iospec——3-D
「不能以文字代替代码」的锚点强制) + LLM 归纳(induce_chains：候选构造/截断
恢复/诊断透传)。作业编排(_job_extract_logic 等)留 logic_extract.py。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LOGIC_KINDS = ("process_chain", "validation_chain", "aggregation_chain", "orchestration_chain")


# ── IO 规约（3-D 结构定义 + 校验） ────────────────────────────

def _norm(p: str) -> str:
    return (p or "").strip().replace("\\", "/").lstrip("./")


def _read_lines(root: str, rel: str, rev: str = "workspace") -> List[str]:
    """按 rev 读源码行（workspace=磁盘；其余 git show）。"""
    try:
        if rev == "workspace" or not rev:
            full = root.rstrip("/") + "/" + rel
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                return f.readlines()
        r = subprocess.run(["git", "-C", root, "show", f"{rev}:{rel}"],
                           capture_output=True, timeout=30)
        if r.returncode != 0:
            return []
        return r.stdout.decode("utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        return []


def build_code_anchor(root: str, ref: dict, rev: str, lang: str = "") -> Optional[dict]:
    """AstNodeRef → CodeAnchor（snippet 快照；行区间无效/文件不可读 → None 拒绝）。"""
    rel = _norm(ref.get("file") or "")
    start = int(ref.get("startLine") or 0)
    end = int(ref.get("endLine") or 0)
    if not rel or start <= 0 or end < start:
        return None
    lines = _read_lines(root, rel, rev)
    if not lines or start > len(lines):
        return None
    end_c = min(end, len(lines))
    snippet = "".join(lines[start - 1:end_c]).rstrip("\n")
    if not snippet.strip():
        return None
    return {"file": rel, "rev": rev or "workspace",
            "symbol": ref.get("symbol") or ref.get("name") or "",
            "lines": [start, end_c], "snippet": snippet[:4000],
            "lang": lang or ref.get("lang") or ""}


def validate_iospec(iospec: dict, root: str, rev: str) -> tuple:
    """IO 规约校验（3-D 校验规则）：每端点 code 锚点 ≥1 且全部可解析。

    → (ok: bool, errors: [str])。锚点不可解析=拒绝落库（不静默）。
    """
    errors: List[str] = []
    for side in ("inputs", "outputs"):
        for i, ep in enumerate((iospec or {}).get(side) or []):
            label = f"{side}[{i}] {ep.get('name') or ''}"
            codes = ep.get("code") or []
            if not codes:
                errors.append(f"{label}: 缺少代码锚点(不能以文字代替代码)")
                continue
            for c in codes:
                if build_code_anchor(root, {"file": c.get("file"),
                                            "startLine": (c.get("lines") or [0])[0],
                                            "endLine": (c.get("lines") or [0, 0])[1],
                                            "symbol": c.get("symbol")},
                                     c.get("rev") or rev) is None:
                    errors.append(f"{label}: 锚点不可解析 {c.get('file')}:{c.get('lines')}")
    return (not errors), errors


# ── LLM 链条归纳 ─────────────────────────────────────────────

_PROMPT = """你是资深软件架构分析师。下面是一批实现级语义资产(函数/类型骨架，含控制流步骤与字段)。
请归纳出其中的「数据处理链条」——一条链条 = 从输入到输出的一段完整数据加工路径。

要求：
1. 只依据给出的实现级事实归纳，不臆造；
2. 每条链条标注类型: process_chain(主处理链) | validation_chain(校验链) | aggregation_chain(聚合链) | orchestration_chain(编排链)；
3. 每条链条给出 inputs/outputs —— 每个端点必须有 code 引用(引用实现级资产的符号名与文件，禁止纯文字描述)；
4. members 列出该链条由哪些实现级资产组成，用清单中的「资产名」或「符号」逐字原文引用(不得改写/缩写/加注释/翻译)；跨文件/跨组件的完整链条通常 ≥2 个成员。

输出 JSON(不要多余文本)：
{"chains":[{"name":"链条名","kind":"process_chain","summary":"一句话",
  "inputs":[{"name":"输入名","symbol":"实现级符号名","file":"文件相对路径","note":"文字辅助"}],
  "outputs":[{"name":"输出名","symbol":"...","file":"...","note":"..."}],
  "members":["符号名1","符号名2"]}]}
无链条时输出 {"chains":[]}。

实现级资产：
{assets}"""


def _pick_assets(assets: List[dict], cap: int = 400) -> List[dict]:
    """归纳入题资产选择：关系密度优先 + 文件多样性(替代 search 的 updated_at 随机序截断)。

    排序键 = (关系度数 desc, 文件路径 asc, 起始行 asc)：
    - 度数 = detail.relations 出边+入边计数(O(n)，与 _edges_brief 同源)——
      调用链枢纽(被多方调用的核心函数)必入题，孤立叶子让位；
    - 同文件相邻 + 行号序 → LLM 组装同文件/跨文件链条更容易，结果稳定可复现。
    """
    deg: Dict[str, int] = {}
    for a in assets:
        aid = a.get("id") or ""
        if aid:
            deg[aid] = deg.get(aid, 0) + len((a.get("detail") or {}).get("relations") or [])
    def _key(a: dict) -> tuple:
        r0 = (a.get("astRefs") or [{}])[0] or {}
        return (-deg.get(a.get("id") or "", 0),
                str(r0.get("file") or ""), int(r0.get("startLine") or 0))
    return sorted(assets, key=_key)[:cap]


def _assets_brief(assets: List[dict]) -> str:
    lines: List[str] = []
    for a in assets[:200]:      # 探测深度：LLM 可见资产广度(原 60，files 口径数百条时链条跨文件组合受限)
        d = a.get("detail") or {}
        refs = a.get("astRefs") or []
        f0 = (refs[0] or {}) if refs else {}
        steps = [st.get("semantic") or "" for st in (d.get("steps") or [])[:8]]
        fields = [fl.get("name") or "" for fl in (d.get("fields") or [])[:12]]
        body = f"  文件:{f0.get('file') or ''} 符号:{f0.get('symbol') or ''} 行:{f0.get('startLine')}-{f0.get('endLine')}"
        if steps:
            body += f"\n  控制流: {'; '.join(steps)}"
        if fields:
            body += f"\n  字段: {', '.join(fields)}"
        # 名称后内联资产 ID——explain 讲解引用「资产名 (sa-xxx)」的数据源(缺 ID 时 LLM 只能臆造)
        lines.append(f"- [{a.get('kind')}] {a.get('name')} ({a.get('id') or ''}): {(a.get('desc') or '')[:120]}\n{body}")
    return "\n".join(lines)


"""资产间关系摘要(归纳输入增厚)：detail.relations 的 from→to 行。"""
def _edges_brief(assets: List[dict]) -> str:
    names = {a.get("id"): (a.get("name") or "") for a in assets}
    lines: List[str] = []
    for a in assets:
        d = a.get("detail") or {}
        for rel in (d.get("relations") or [])[:10]:
            tgt = rel.get("target") or rel.get("name") or ""
            if not tgt:
                continue
            tgt_name = names.get(tgt, tgt)
            lines.append(f"- {a.get('name')} --{rel.get('type') or 'relates'}--> {tgt_name}")
    return "\n".join(lines[:120])


def _recover_chains(content: str) -> List[dict]:
    """截断恢复：自 `"chains"` 数组逐个抽取**花括号平衡的完整对象**独立解析。

    输出触碰 maxTokens 上限被截断时整体 json.loads 必败；逐条恢复可救回
    截断点之前的完整链条(尾部残条自然丢弃——宁缺勿错)。
    """
    i = content.find('"chains"')
    if i < 0:
        return []
    j = content.find("[", i)
    if j < 0:
        return []
    out: List[dict] = []
    depth, start = 0, -1
    in_str = esc = False
    for k in range(j + 1, len(content)):
        c = content[k]
        if in_str:
            if esc:
                esc = False
            elif c == chr(92):
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            if depth == 0:
                start = k
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    out.append(json.loads(content[start:k + 1]))
                except Exception:
                    return out   # 首个坏对象即止(其后更不可信)
                start = -1
        elif c == "]" and depth == 0:
            break
    return out


def _norm_key(s: str) -> str:
    """模糊匹配键：剥括号注释(全/半角) + 去空白 + 小写。
    LLM 常给名称加「(注释)」「（中文注）」或微调空格——归一后仍可命中。"""
    t = re.sub(r"[（(【\[《<].*?[)）\]》>]", "", s or "")
    return re.sub(r"\s+", "", t).lower()


def _member_index(assets: List[dict]) -> tuple:
    """成员解析双索引：by_symbol(资产名/符号精确) + by_norm(归一键)。"""
    by_symbol: Dict[str, dict] = {}
    by_norm: Dict[str, dict] = {}
    for a in assets:
        nm = (a.get("name") or "").strip()
        if nm:
            by_symbol.setdefault(nm, a)   # LLM 常以清单行首的资产名引用成员
            by_norm.setdefault(_norm_key(nm), a)
        for r in (a.get("astRefs") or []):
            sym = (r.get("symbol") or "").strip()
            if sym:
                by_symbol.setdefault(sym, a)   # 符号名索引(prompt 主口径)
                by_norm.setdefault(_norm_key(sym), a)
    return by_symbol, by_norm


def induce_chains(root: str, assets: List[dict], rev: str,
                  model_id: Optional[str] = None, mode: str = "free",
                  brief_cap: Optional[int] = None) -> tuple:
    """LLM 归纳链条 → 结构化(成员实现级资产对齐 + IO 锚点构造+校验)。

    返回 (chains, diag)：diag 为空=完全正常；非空=降级/过滤诊断(透传作业
    result，消除「候选 0」不可排查问题)。
    max_tokens 不写死——回退 arch_collab_config 偏好 → 主后端模型配置
    (禁止代码写死 maxtoken 的既有裁决；写死 4000 曾致输出截断候选恒 0)。

    输出质量波动治理(events.jsonl 实证同输入时好时坏)：单次采样可用链条少
    且丢弃多(可用<3 且丢弃≥3)时自动重采样一次，取可用数较多的一轮——
    不再让一次坏采样直接产出「0-1 条」的退化结果。

    mode(参数化策略, 2026-10-03): free=LLM 自由归纳(默认, 现路径);
    structural=结构化构链(图算法找链+LLM 仅命名——成员 100% 命中,
    回引不稳模型的兜底路径, 详见 logic_structural)。
    """
    if mode == "structural":
        from .logic_structural import structural_induce
        return structural_induce(root, assets, rev, model_id,
                                 anchor_fn=build_code_anchor)
    # B 方案分批(B 方案, 2026-10-03): briefCap 参数(chars)——清单超限时按文件簇
    # 分批归纳、跨批去重合并, 广度不丢(替代单次裁剪丢尾); cap 来自 asset profile
    # 探测参数/手动覆盖, None=不分批(单次全量, 现行为)。
    cap = brief_cap or 0
    picked = _pick_assets(assets)
    full_len = len(_assets_brief(picked)) + len(_edges_brief(picked))
    if cap > 0 and full_len > cap and len(picked) > 40:
        batches = _split_batches(picked, cap)
        merged: List[dict] = []
        seen: set = set()
        diags: List[str] = []
        for b in batches:
            chains, diag = _induce_free(root, assets, b, rev, model_id)
            for c in chains:
                key = frozenset(c.get("members") or [])
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(c)
            if diag:
                diags.append(diag)
        head = f"分批归纳 {len(batches)} 批(单批 ≤{cap} 字符)合并 {len(merged)} 条"
        return merged, "；".join([head] + diags) if diags else head
    return _induce_free(root, assets, picked, rev, model_id)


def _split_batches(assets: List[dict], cap: int) -> List[List[dict]]:
    """文件簇装箱: 同文件聚簇(簇内链天然完整), 簇按累计 chars 装箱(每箱 ≤ cap;
    单簇超 cap 再按资产逐个切)。保持 _pick_assets 度数优先序的簇间顺序。"""
    clusters: Dict[str, List[dict]] = {}
    order: List[str] = []
    for a in assets:
        f = ((a.get("astRefs") or [{}])[0].get("file")) or "_"
        if f not in clusters:
            clusters[f] = []
            order.append(f)
        clusters[f].append(a)
    batches: List[List[dict]] = []
    cur: List[dict] = []
    cur_chars = 0
    for f in order:
        cluster = clusters[f]
        c_len = len(_assets_brief(cluster))
        if cur and cur_chars + c_len > cap:
            batches.append(cur)
            cur, cur_chars = [], 0
        if c_len > cap and not cur:
            for a in cluster:   # 单簇超 cap: 簇内逐资产切(保文件内聚优先)
                a_len = len(_assets_brief([a]))
                if cur and cur_chars + a_len > cap:
                    batches.append(cur)
                    cur, cur_chars = [], 0
                cur.append(a)
                cur_chars += a_len
        else:
            cur.extend(cluster)
            cur_chars += c_len
    if cur:
        batches.append(cur)
    return batches


def _induce_free(root: str, assets: List[dict], picked: List[dict],
                 rev: str, model_id: Optional[str]) -> tuple:
    """单批自由归纳(原 induce_chains 主体): 索引/预算裁剪/采样重试。"""
    from ..agent.cognition.llm import llm_sync, resolve_context_budget
    by_symbol, by_norm = _member_index(assets)

    # 上下文预算自适应：31k chars 清单塞 8k 窗模型 = 爆窗→LM Studio 非确定截断
    # → 清单残缺成员名全 miss + 输出截断(实测 2026-10-02 六次同输入好坏随机)。
    # 按探测窗口裁剪 picked(度数优先序保核心枢纽)，清单恒在窗内——小窗模型
    # 归纳范围变浅但稳定可出链；大窗模型(262k)自动全量。
    budget = resolve_context_budget(None, model_id or "") or 0
    if budget > 0:
        max_brief = max(2000, int(budget * 0.85) - 600)   # 600=题头+关系边预留(chars≈tok)
        for _ in range(12):
            brief = _assets_brief(picked)
            edges = _edges_brief(picked)
            if len(brief) + len(edges) <= max_brief or len(picked) <= 40:
                break
            picked = picked[:max(40, int(len(picked) * 0.7))]   # 逐次收缩 30%
    brief = _assets_brief(picked)
    edges = _edges_brief(picked)
    if edges:
        brief = brief + "\n\n资产间调用/依赖关系:\n" + edges
    prompt = _PROMPT.replace("{assets}", brief)

    def _resolve(sym: str) -> Optional[dict]:
        """成员/端点符号解析：精确(资产名/符号) → norm(剥括号注释+空白归一)
        → 唯一前缀匹配。LLM 常给名称加注释/微改写，模糊二级显著提高命中率。"""
        a = by_symbol.get(sym)
        if a is not None:
            return a
        k = _norm_key(sym)
        if not k:
            return None
        a = by_norm.get(k)
        if a is not None:
            return a
        hits = [x for key, x in by_norm.items()
                if len(k) >= 4 and (key.startswith(k) or k.startswith(key))]
        return hits[0] if len(hits) == 1 else None

    best: tuple = ([], "")
    for attempt in (1, 2):
        res = llm_sync([{"role": "user", "content": prompt}],
                       mode="chat", model_id=model_id)
        content = ((res or {}).get("content") or "").strip()
        chains, diag, dropped = _filter_chains(
            content, by_symbol, _resolve, assets, root, rev)
        if attempt == 1 or len(chains) > len(best[0]):
            best = (chains, diag)
        if dropped < 3 or len(chains) >= 3:
            break   # 质量可接受(或无丢弃)——不浪费第二次采样
        logger.info("[logic] 归纳采样质量低(可用 %d/丢弃 %d)→ 重采样",
                    len(chains), dropped)
    return best[0], best[1]


def _filter_chains(content: str, by_symbol: Dict[str, dict], resolve,
                   assets: List[dict], root: str, rev: str) -> tuple:
    """单次采样输出 → 解析(JSON/截断恢复) → 成员对齐+锚点过滤(返回 chains,diag,dropped)。"""
    raw: List[dict] = []
    diag = ""
    m = re.search(r"\{.*\}", content, re.S)
    if m:
        try:
            raw = list(json.loads(m.group(0)).get("chains") or [])
        except Exception:
            raw = []
    if not raw:
        if not m:
            diag = f"LLM 未返回 JSON(content {len(content)} 字符)"
            logger.warning("[logic] %s", diag)
        else:
            raw = _recover_chains(content)
            diag = (f"JSON 截断，恢复 {len(raw)} 条完整链条(尾部残条丢弃)"
                    if raw else "JSON 解析失败且截断恢复未救回任何链条")
            logger.warning("[logic] %s", diag)
    chains: List[dict] = []
    dropped = 0
    degraded = 0
    miss_member = 0
    for ch in raw[:12]:
        kind = ch.get("kind") if ch.get("kind") in LOGIC_KINDS else "process_chain"
        members: List[str] = []
        for sym in (ch.get("members") or []):
            a = resolve(sym)
            if a is not None and a.get("id"):
                members.append(a["id"])
        inputs = _endpoints(ch.get("inputs"), "in", by_symbol, root, rev)
        outputs = _endpoints(ch.get("outputs"), "out", by_symbol, root, rev)
        # 端点解析失败兜底：LLM 偶发把 inputs/outputs 的 symbol/file 全写错(输出质量
        # 波动,同输入时好时坏)→ 整链锚点尽失被丢弃。用成员资产的真实代码锚补齐
        # 缺失侧(首成员=入,尾成员=出)——链条保持代码锚定(3-D)，不再赌 LLM 端点质量。
        if members:
            by_id = {a.get("id"): a for a in assets}
            def _member_anchor(mid: str, direction: str) -> list:
                a = by_id.get(mid)
                for r in (a.get("astRefs") or []):
                    an = build_code_anchor(root, r, rev)
                    if an:
                        return [{"id": f"io-fb-{direction}", "name": (a.get("name") or mid)[:60],
                                 "direction": direction, "code": [an],
                                 "note": "成员锚点兜底(LLM 端点未解析)"}]
                return []
            if not inputs:
                inputs = _member_anchor(members[0], "in")
            if not outputs:
                outputs = _member_anchor(members[-1], "out")
        if not inputs and not outputs and len(members) < 2:
            dropped += 1
            if not members and (ch.get("members") or []):
                miss_member += 1   # LLM 成员名全部未匹配(未按清单原文引用)
            continue   # 无成员且无可锚定 IO = 纯文字链条(3-D 禁止形态)
        if not inputs and not outputs:
            degraded += 1   # 极端兜底后仍无锚(成员行号/文件均不可读)降级保留
        chains.append({
            "name": (ch.get("name") or kind)[:80], "kind": kind,
            "summary": (ch.get("summary") or "")[:400],
            "inputs": inputs, "outputs": outputs, "members": members,
        })
    if dropped:
        diag = (diag + "；" if diag else "") + f"{dropped} 条无 IO 锚点被过滤"
        if miss_member:
            diag += f"(其中 {miss_member} 条成员名全部未匹配——LLM 未按清单原文引用)"
    if degraded:
        diag = (diag + "；" if diag else "") + f"{degraded} 条缺 IO 端点降级保留(成员锚定充分)"
    return chains, diag, dropped



def _endpoints(raw_eps: Any, direction: str, by_symbol: Dict[str, dict],
               root: str, rev: str) -> List[dict]:
    out: List[dict] = []
    for ep in (raw_eps or [])[:8]:
        sym = (ep.get("symbol") or ep.get("name") or "").strip()   # name 兜底: LLM 可能把资产名放 name 字段
        a = by_symbol.get(sym)
        anchor: Optional[dict] = None
        if a is not None:
            for r in (a.get("astRefs") or []):
                anchor = build_code_anchor(root, r, rev)
                if anchor:
                    break
        else:
            # symbol 不在成员集中 → 尝试按 ep.file 定位(锚点格式最小构造)
            anchor = build_code_anchor(root, {"file": ep.get("file"),
                                              "symbol": sym,
                                              "startLine": ep.get("line") or 0,
                                              "endLine": ep.get("line") or 0}, rev)
        if anchor is None:
            continue
        out.append({"id": f"io-{len(out) + 1}", "name": (ep.get("name") or sym)[:60],
                    "direction": direction,
                    "code": [anchor], "note": (ep.get("note") or "")[:200]})
    return out


# ── 逻辑视图详细语义讲解(手动触发, 缓存+指纹失效联动) ───────────────

_EXPLAIN_PROMPT = """你是资深软件架构分析师。下面是一条业务逻辑链(逻辑视图)的成员实现资产清单。
请生成这条逻辑链的**详细语义讲解**，要求：

1. 讲清楚这条链的业务职责、触发入口、数据如何流转、关键分支与外部 IO；
2. 讲解必须**逐环节引用成员实现资产**，引用格式一律为「资产名 (资产ID)」——
   例如：订单校验 (sa-d-i-p-16746) 负责入口过滤…；禁止只写名称不写 ID；
3. 按处理顺序组织段落(Markdown)，成员间调用/依赖关系要显式说明；
4. 只依据给出的资产事实，不臆造；结尾用 2-3 句总结这条链在系统中的位置。

逻辑视图：{view} ({kind})
已有概括：{summary}
成员实现资产清单：
{assets}
"""


def explain_view(view: dict, assets: List[dict], model_id: Optional[str] = None) -> str:
    """逻辑视图详细语义讲解：结合成员实现资产(名称+ID 引用)的 LLM 讲解文本。"""
    from ..agent.cognition.llm import llm_sync
    from ..agent.cognition.roles import resolve_role_model
    brief = _assets_brief(assets)
    prompt = (_EXPLAIN_PROMPT
              .replace("{view}", (view.get("name") or "")[:80])
              .replace("{kind}", view.get("source") or "extract")
              .replace("{summary}", (view.get("summary") or "暂无")[:500])
              .replace("{assets}", brief))
    res = llm_sync([{"role": "user", "content": prompt}],
                   mode="chat",
                   model_id=resolve_role_model("induce", model_id or ""))
    return (((res or {}).get("content") or "").strip())[:6000]
