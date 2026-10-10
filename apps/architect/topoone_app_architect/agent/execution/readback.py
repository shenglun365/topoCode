"""解读回环(readback handshake, 意图空间一期 D4, 裁决 2026-10-09)——零 runner 协议改动。

防语义污染的最后闸口: 下发指令附「先解读后开工」段, 执行器首回合按自身
理解输出解读(目标复述/代码坐标/计划要点/冲突点/疑问)并主动等待输入
(input_required); architect 在 input_required 到达时规则校验——

裁决方式(用户决策): 规则可判的自动裁决(代码坐标对账/验收点覆盖比对),
语义偏差以建议呈现、用户终裁(经既有输入通道放行/纠偏, 一次循环不往复)。
开启策略: 安全等级 high-stakes 默认开, 其余默认关; task.readback
("on"|"off")显式覆盖(挡位默认之上的手动开关)。
"""
from __future__ import annotations

import re
from typing import Dict, List

# 指令注入段: 要求执行器先输出「我的理解」再等确认(与冲突约定总则呼应——
# 描述与代码冲突以代码为准, 冲突点在解读中明确指出)
READBACK_INSTRUCTION = (
    "\n\n## 开工前解读（readback）\n"
    "正式动手前，先输出你对本任务的**解读**，然后停下来等待确认（不要开始修改代码）：\n"
    "1. **目标复述**：用你自己的话说明这个任务要达成什么；\n"
    "2. **涉及代码**：列出你定位到的具体文件/符号（代码坐标）；\n"
    "3. **计划要点**：打算分几步做、每步做什么；\n"
    "4. **冲突点**：上文描述与代码事实不一致之处（如有——以代码为准并在此指出）；\n"
    "5. **疑问**：需要人澄清的问题（如有）。\n"
    "输出解读后即等待输入；得到确认（如「理解正确，开工」）后再开始执行，"
    "有偏差则按纠正意见调整解读后开工。")

# 任务行显式覆盖挡位默认: "on" | "off" | ""(空=按挡位)
_READBACK_ON = "on"
_READBACK_OFF = "off"


def readback_enabled(task: dict) -> bool:
    """开启判定(单源): task.readback 显式覆盖 > 安全等级挡位默认。"""
    task = task or {}
    flag = str(task.get("readback") or "").strip().lower()
    if flag == _READBACK_ON:
        return True
    if flag == _READBACK_OFF:
        return False
    return str(task.get("safetyClass") or "").strip().lower() == "high-stakes"


# ── 规则校验(纯函数): 代码坐标对账 + 验收点覆盖 ─────────────────────────────

_PATH_RE = re.compile(r"(?:[\w.\-]+/)*[\w.\-]+\.[A-Za-z]{1,6}\b")
_CODE_EXT = {".ts", ".tsx", ".js", ".jsx", ".vue", ".py", ".go", ".rs",
             ".java", ".kt", ".c", ".h", ".cpp", ".cs", ".rb", ".php",
             ".swift", ".sql", ".json", ".yaml", ".yml", ".toml", ".css",
             ".scss", ".html", ".sh", ".md"}


def _extract_paths(text: str) -> List[str]:
    out, seen = [], set()
    for m in _PATH_RE.findall(text or ""):
        low = m.lower()
        if ("." + low.rsplit(".", 1)[-1]) not in _CODE_EXT:
            continue
        if low not in seen:
            seen.add(low)
            out.append(m)
    return out[:20]


def _tokens(text: str) -> set:
    """关键词集: ASCII 词(≥2)小写化 + 中文 2-gram(覆盖比对的粗粒度信号)。"""
    out = set()
    for m in re.findall(r"[A-Za-z0-9_\-./]+|[\u4e00-\u9fff]+", text or ""):
        if m.isascii():
            if len(m) >= 2:
                out.add(m.lower())
        else:
            out |= {m[i:i + 2] for i in range(len(m) - 1)}
    return out


def verdict_of(readback_text: str, boundary_files: List[str],
               acceptance: List[str]) -> Dict[str, object]:
    """规则校验: 解读中的代码坐标是否落在边界内 + 验收条目是否被呼应。

    - 界内判定: 相等或以边界路径(含目录前缀)开头;
    - 验收覆盖: 条目 token(去重前 8)过半出现在解读 token 集即算呼应;
    - pass = 无疑似越界 且 无未呼应验收。粗规则信号, 偏差人工终裁。
    """
    boundary = [str(f).strip().lower().rstrip("/") for f in (boundary_files or []) if f]

    def _in_scope(p: str) -> bool:
        low = p.lower()
        for b in boundary:
            if low == b or low.startswith(b + "/") or b.startswith(low + "/"):
                return True
        return False

    paths = _extract_paths(readback_text)
    out_scope = [p for p in paths if not _in_scope(p)]

    rb_tokens = _tokens(readback_text)
    missing: List[str] = []
    for acc in (acceptance or [])[:12]:
        toks = list(dict.fromkeys(_tokens(str(acc))))[:8]
        if not toks:
            continue
        hit = sum(1 for t in toks if t in rb_tokens)
        if hit * 2 < len(toks):
            missing.append(str(acc))

    return {"paths": paths, "outScope": out_scope,
            "acceptanceTotal": min(len(acceptance or []), 12),
            "missingAcceptance": missing,
            "pass": not out_scope and not missing}


def render_verdict(v: Dict[str, object]) -> str:
    """校验结果 → 落卡建议文本(附注在解读消息尾部; 用户裁决)。"""
    n_paths = len(v.get("paths") or [])
    out_scope = v.get("outScope") or []
    missing = v.get("missingAcceptance") or []
    total = int(v.get("acceptanceTotal") or 0)
    lines = ["", "---", "🔍 **解读校验（规则自动，供你裁决）**"]
    lines.append(f"- 代码坐标 {n_paths} 处，边界对账 "
                 + ("✅ 全部在界内" if not out_scope
                    else f"⚠️ 疑似越界 {len(out_scope)} 处：{', '.join(out_scope[:6])}"))
    if total:
        lines.append(f"- 验收呼应 {total - len(missing)}/{total} "
                     + ("✅" if not missing else
                        f"⚠️ 未呼应：{'；'.join(m[:3] for m in missing[:3])}"))
    lines.append("✅ 规则校验通过——可回复「理解正确，开工」放行。"
                 if v.get("pass") else
                 "⚠️ 存在上述信号——请核对后放行（回复确认）或纠偏（指出问题）。"
                 "语义层面的偏差以你的判断为准。")
    return "\n".join(lines)


# ── 语义偏差评估(LLM 增强, 遗留#1): 规则校验之上, 建议仍由用户终裁 ──────────

# LLM 通道钩子(装配点注入, 遗留#1): execution 域层序不引 turns——由
# arch_routes 装配层接线 catalog_call(补偿管线); 未注入时作业诚实降级。
_LLM_CALL = None


def set_llm_call(fn) -> None:
    global _LLM_CALL
    _LLM_CALL = fn


_REVIEW_SYSTEM = (
    "你是架构评审助手。给定「执行器的开工解读」与「任务规约上下文」，判断解读的"
    "语义理解是否有偏差（目标理解偏移/方案意图曲解/验收标准误读/边界误解）。\n"
    "输出格式（Markdown，简洁）：\n"
    "- 第一行结论：`结论：对齐` 或 `结论：疑似偏差` 或 `结论：无法判断`\n"
    "- 随后最多 5 条要点：偏在哪/证据（引用解读与规约原文短语）/建议纠偏说法；"
    "对齐时列出解读做对了的关键理解（最多 3 条）。\n"
    "只基于给定材料判断，不虚构；材料不足直接「无法判断」。")


def review_messages(readback_text: str, spec_ctx: dict) -> list:
    """评估 prompt: 规约上下文(reqMd/designMd/acceptance/boundary) + 解读全文。"""
    lines = ["## 任务规约上下文"]
    for k, label in (("reqMd", "需求（用户意图）"), ("designMd", "方案（架构师推断）"),
                     ("scopeOut", "明确不做"), ("boundary", "边界文件")):
        v = str(spec_ctx.get(k) or "").strip()
        if v:
            lines.append(f"### {label}\n{v[:2000]}")
    acc = spec_ctx.get("acceptance") or []
    if acc:
        lines.append("### 验收标准\n" + "\n".join(f"- {a}" for a in acc[:12]))
    lines.append("## 规则校验结论（参考）\n" + str(spec_ctx.get("ruleVerdict") or "未提供"))
    lines.append("## 执行器的开工解读\n" + (readback_text or "").strip()[:6000])
    lines.append("请按系统指令输出评估。")
    return [{"role": "system", "content": _REVIEW_SYSTEM},
            {"role": "user", "content": "\n\n".join(lines)}]


def _job_readback_review(ctx) -> dict:
    """readback_review 作业体: LLM 语义偏差评估(异步, 遗留#1)。

    scope = {convId, taskId, rid, readbackMd, ruleVerdict, root, project}。
    完成落卡: 会话 assistant 消息(meta kind=readback_review) + progress
    .readbackReview(结论首行); 评估失败静默(不阻塞放行通道)。
    """
    from ... import store
    sc = ctx.scope or {}
    conv = store.ConversationsStore.get(sc.get("convId") or "")
    task_id = str(sc.get("taskId") or "")
    if not conv or not task_id:
        return {"error": "缺少会话/任务"}
    task = store.TasksStore.get(task_id) or {}
    rid = str(sc.get("rid") or task.get("reqId") or "")
    spec_ctx = {"ruleVerdict": str(sc.get("ruleVerdict") or "")}
    if rid:
        snap = (store.RequirementsStore.spec_active(rid) or {}).get("snapshot") or {}
        spec_ctx.update({
            "reqMd": snap.get("requirementMd") or snap.get("desc") or "",
            "designMd": snap.get("designMd") or "",
            "scopeOut": snap.get("scopeOut") or "",
            "acceptance": [str(x) for x in (snap.get("acceptance") or [])[:12]],
        })
    boundary = str(sc.get("boundary") or "").strip()
    if boundary:
        spec_ctx["boundary"] = boundary
    ctx.progress(total=1, done=0, current="语义评估中")
    # LLM 通道经装配点注入(层序: execution 不引 turns; 未注入→诚实降级)
    res = _LLM_CALL(review_messages(str(sc.get("readbackMd") or ""), spec_ctx)) \
        if _LLM_CALL else None
    content = str((res or {}).get("content") or "").strip() if res else ""
    if not content:
        return {"error": "评估未返回内容(LLM 通道未注入/不可达)"}
    head = content.splitlines()[0][:80]
    try:
        from . import exec_bridge as _eb
        _eb._append(str(conv["id"]), "assistant",
                    f"🧭 **解读语义评估**（任务「{task.get('title') or task_id}」）\n\n{content}\n\n"
                    "（LLM 评估建议——最终是否放行由你裁决：确认无误回复「理解正确，开工」，"
                    "有偏差请直接指出。）",
                    msg_meta={"kind": "readback_review", "taskId": task_id},
                    project_id=str(conv.get("projectId") or ""))
    except Exception as e:  # noqa: BLE001 — 落卡失败不吞评估结果
        return {"summary": content[:200], "error": f"落卡失败: {str(e)[:80]}"}
    try:
        prog = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        store.TasksStore.set_progress(task_id, {
            **prog, "readbackReview": head})
    except Exception:  # noqa: BLE001
        pass
    return {"saved": 1, "summary": head}


from ...sem import job_runner as _job_runner  # noqa: E402
_job_runner.register("readback_review", _job_readback_review)
