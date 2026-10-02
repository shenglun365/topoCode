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
4. members 列出该链条由哪些实现级资产(符号名)组成。

输出 JSON(不要多余文本)：
{"chains":[{"name":"链条名","kind":"process_chain","summary":"一句话",
  "inputs":[{"name":"输入名","symbol":"实现级符号名","file":"文件相对路径","note":"文字辅助"}],
  "outputs":[{"name":"输出名","symbol":"...","file":"...","note":"..."}],
  "members":["符号名1","符号名2"]}]}
无链条时输出 {"chains":[]}。

实现级资产：
{assets}"""


def _assets_brief(assets: List[dict]) -> str:
    lines: List[str] = []
    for a in assets[:60]:
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
        lines.append(f"- [{a.get('kind')}] {a.get('name')}: {(a.get('desc') or '')[:120]}\n{body}")
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


def induce_chains(root: str, assets: List[dict], rev: str,
                  model_id: Optional[str] = None) -> tuple:
    """LLM 归纳链条 → 结构化(成员实现级资产对齐 + IO 锚点构造+校验)。

    返回 (chains, diag)：diag 为空=完全正常；非空=降级/过滤诊断(透传作业
    result，消除「候选 0」不可排查问题)。
    max_tokens 不写死——回退 arch_collab_config 偏好 → 主后端模型配置
    (禁止代码写死 maxtoken 的既有裁决；写死 4000 曾致输出截断候选恒 0)。

    锚点解析失败的端点：尝试按 symbol 在成员资产 astRefs 中对齐重建；仍失败则
    丢弃该端点(宁缺勿错——3-D「不能以文字代替代码」)。
    """
    from ..agent.cognition.llm import llm_sync
    by_symbol: Dict[str, dict] = {}
    for a in assets:
        for r in (a.get("astRefs") or []):
            by_symbol[(r.get("symbol") or r.get("name") or "")] = a
    brief = _assets_brief(assets)
    edges = _edges_brief(assets)
    if edges:
        brief = brief + "\n\n资产间调用/依赖关系:\n" + edges
    prompt = _PROMPT.replace("{assets}", brief)
    res = llm_sync([{"role": "user", "content": prompt}],
                   mode="chat", model_id=model_id)
    content = ((res or {}).get("content") or "").strip()
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
    for ch in raw[:12]:
        kind = ch.get("kind") if ch.get("kind") in LOGIC_KINDS else "process_chain"
        members: List[str] = []
        for sym in (ch.get("members") or []):
            a = by_symbol.get(sym)
            if a is not None and a.get("id"):
                members.append(a["id"])
        inputs = _endpoints(ch.get("inputs"), "in", by_symbol, root, rev)
        outputs = _endpoints(ch.get("outputs"), "out", by_symbol, root, rev)
        if not inputs and not outputs:
            dropped += 1
            continue   # 无可锚定 IO 的链条不落库(纯文字链条=3-D 禁止形态)
        chains.append({
            "name": (ch.get("name") or kind)[:80], "kind": kind,
            "summary": (ch.get("summary") or "")[:400],
            "inputs": inputs, "outputs": outputs, "members": members,
        })
    if dropped:
        diag = (diag + "；" if diag else "") + f"{dropped} 条无 IO 锚点被过滤"
    return chains, diag


def _endpoints(raw_eps: Any, direction: str, by_symbol: Dict[str, dict],
               root: str, rev: str) -> List[dict]:
    out: List[dict] = []
    for ep in (raw_eps or [])[:8]:
        sym = ep.get("symbol") or ""
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
