"""逻辑级提取（批3）：两段式第二段的链式归纳层（需求 3.1-3.4）。

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


def induce_chains(root: str, assets: List[dict], rev: str,
                  model_id: Optional[str] = None) -> List[dict]:
    """LLM 归纳链条 → 结构化(成员实现级资产对齐 + IO 锚点构造+校验)。

    锚点解析失败的端点：尝试按 symbol 在成员资产 astRefs 中对齐重建；仍失败则
    丢弃该端点(宁缺勿错——3-D「不能以文字代替代码」)。
    """
    from ..agent.cognition.llm import llm_sync
    by_symbol: Dict[str, dict] = {}
    for a in assets:
        for r in (a.get("astRefs") or []):
            by_symbol[(r.get("symbol") or r.get("name") or "")] = a
    prompt = _PROMPT.replace("{assets}", _assets_brief(assets))
    res = llm_sync([{"role": "user", "content": prompt}],
                   mode="chat", model_id=model_id, max_tokens=4000)
    content = ((res or {}).get("content") or "").strip()
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        logger.warning("[logic] LLM 未返回 JSON")
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        logger.warning("[logic] LLM JSON 解析失败")
        return []
    chains: List[dict] = []
    for ch in (data.get("chains") or [])[:12]:
        kind = ch.get("kind") if ch.get("kind") in LOGIC_KINDS else "process_chain"
        members: List[str] = []
        for sym in (ch.get("members") or []):
            a = by_symbol.get(sym)
            if a is not None and a.get("id"):
                members.append(a["id"])
        inputs = _endpoints(ch.get("inputs"), "in", by_symbol, root, rev)
        outputs = _endpoints(ch.get("outputs"), "out", by_symbol, root, rev)
        if not inputs and not outputs:
            continue   # 无可锚定 IO 的链条不落库(纯文字链条=3-D 禁止形态)
        chains.append({
            "name": (ch.get("name") or kind)[:80], "kind": kind,
            "summary": (ch.get("summary") or "")[:400],
            "inputs": inputs, "outputs": outputs, "members": members,
        })
    return chains


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

    # stage 1: LLM 链条归纳
    ctx.progress(total=1, done=0, stage=1)
    chains = induce_chains(rid, impl, rev, model_id)
    saved_ids: List[str] = []
    from .engine import _save_assets
    from ..store import SemanticAssetsStore
    existing = {a.get("canonicalKey"): a
                for a in SemanticAssetsStore.search(pid, level="logic", limit=2000, rev=rev or "")
                if a.get("canonicalKey")}
    for ch in chains:
        detail = {"iospec": {"inputs": ch["inputs"], "outputs": ch["outputs"]},
                  "members": ch["members"], "summary": ch["summary"]}
        payload = [{"name": ch["name"], "kind": ch["kind"], "level": "logic",
                    "desc": ch["summary"], "astRefs": [], "detail": detail}]
        canonical = json.dumps(sorted(ch["members"]), ensure_ascii=False) + ch["name"]
        import hashlib
        ck = hashlib.sha1(f"{ch['kind']}|logic|{canonical}".encode()).hexdigest()[:24]
        old = existing.get(ck)
        sctx = {"root": rid, "project": sc.get("project"), "source": "logic_extract",
                "rev": rev, "files": [], "srcHash": rev, "table": {}}
        assets = _save_assets(pid, "files", sc.get("scopeKey") or "", payload, sctx)
        if assets:
            SemanticAssetsStore.update(assets[0]["id"], {"canonicalKey": ck})
            saved_ids.append(assets[0]["id"])
    return {"saved": len(saved_ids), "ids": saved_ids[:20],
            "summary": f"逻辑链 {len(saved_ids)} 条(候选 {len(chains)})"}


def resolve_members(logic_asset: dict) -> List[dict]:
    """组成关系动态解析（3-C）：成员 id → 成员实现级资产当前状态。

    成员已被删除/失效时如实携带其当前 status（前端可标灰），不做静默过滤。
    """
    from ..store import SemanticAssetsStore
    members = ((logic_asset.get("detail") or {}).get("members") or [])
    out: List[dict] = []
    for mid in members:
        a = SemanticAssetsStore.get(mid)
        if a:
            out.append({"id": a.get("id"), "name": a.get("name"), "kind": a.get("kind"),
                        "status": a.get("status"), "rev": a.get("rev"),
                        "astRefs": (a.get("astRefs") or [])[:1]})
        else:
            out.append({"id": mid, "status": "missing"})
    return out


from . import job_runner as _job_runner  # noqa: E402
_job_runner.register("extract_logic", _job_extract_logic)  # noqa: E305


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
