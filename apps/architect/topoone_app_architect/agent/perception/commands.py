"""会话指令直通(感知层) — 意图原语分类器 + 直通动作执行器(批戊收编)。

三层判别模型的本层职责: **词表定意图**——match_imperative 把整条消息分类为
五原语(execute/confirm/continue/retry/extract); 指代消解归焦点栈
(memory/focus.resolve_intent), 动作执行为下方 run_* 执行器。
v2 流程(无草稿态)：需求卡按需出现——开发类需求由模型/围栏 req.propose
直接落 ready 卡；系统未识别时用户点工具栏「提取需求」(或发 /提取需求)。
非开发类需求(分析型问答等)不产需求卡, 纯对话回答。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# 意图原语词表(整条消息恰为该词, 可带 @执行器 前缀——确定性直通不经 LLM,
# 弱模型自由轮会输出"(调用xx工具)"占位文本而不真调, cv-181 实证)。
_IMPERATIVE_RE = re.compile(
    r"^(?:@(?P<executor>\S+)\s+)?"
    r"(?:(?:/(?P<extract>提取需求)|/(?P<execute>执行))|"
    r"(?P<confirm>确认执行|确认任务|确认|同意|开始执行|开始吧|开始|ok|OK|好的?)|"
    r"(?P<cont>继续执行|继续)|(?P<retry>重试))[。.!！]?\s*$")

_INTENT_OF = {"extract": "extract", "execute": "execute",
              "confirm": "confirm", "cont": "continue", "retry": "retry"}


def match_imperative(question: str) -> Optional[Dict[str, str]]:
    """意图原语分类(整条消息恰为指令/确认/继续/重试语): {intent, executor}。

    只分类**意图**, 不裁决指代/动作——"继续执行"在计划步骤待确认场景=确认
    该步(cv-241), 在无焦点场景=回落 GU; 指代由 focus.resolve_intent 就近消解。
    @cline /执行 → {"intent": "execute", "executor": "cline"}。
    (2026-09-20 处置: 直通链保留为前端按钮通道+确定性兜底(cv-152/181), 用户面
    收敛到自然语言+按钮——回执/引导文案不再宣传斜杠语法。)"""
    m = _IMPERATIVE_RE.match((question or "").strip())
    if not m:
        return None
    intent = next((v for g, v in _INTENT_OF.items() if m.group(g)), "")
    if not intent:
        return None
    return {"intent": intent, "executor": (m.group("executor") or "").strip()}


def run_extract_req(conv: Dict[str, Any], on_phase=None) -> Dict[str, Any]:
    """直通 /提取需求：从对话历史 LLM 结构化提取需求 → 确定性落库(需求卡 ready)。

    系统未自动识别需求类型时的用户主动通道; 已绑定需求 → 走 amend 更新(新 ver)。"""
    from ...arch_routes import req_agent, store
    msgs = store.ConversationsStore.messages(conv["id"], limit=40) or []
    # 指令消息本身不进材料(否则 "/提取需求" 一条也算内容)
    _CMD_ONLY = re.compile(r"^(?:@\S+\s+)?/(?:提取需求|执行|定稿)\s*$")
    transcript = "\n".join(
        f"[{'用户' if m.get('role') == 'user' else '助手'}] {(m.get('content') or '').strip()[:500]}"
        for m in msgs
        if (m.get("content") or "").strip() and not _CMD_ONLY.match((m.get("content") or "").strip()))
    if not transcript.strip():
        return {"ok": False, "receipt": "会话还没有内容，无法提取需求。"}
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "requirementMd": {"type": "string"},
            "designMd": {"type": "string"},
            "allowedScopeMd": {"type": "string"},
            "forbiddenScopeMd": {"type": "string"},
            "acceptanceMd": {"type": "string"},
        },
        "required": ["title", "requirementMd"],
    }
    # R3.1 链3收编(D7-①): /提取需求 迁 CallTurn——分目的脚手架(T2)/按挡重试/
    # 确定性兜底(解析失败→澄清问询, 不再直接失败)。T0/T1 行为等价(仅重试增量)。
    from ...agent.compensation.ctx import Purpose
    from ...agent.governance.gears import resolve_gear
    from ...agent.turns import call as _call_turn
    tier = resolve_gear(str((conv or {}).get("analysisMode") or "")).tier

    def _validate(p):
        if not isinstance(p, dict) or not (p.get("title") or "").strip():
            return False, "输出非 JSON 对象或缺少有效 title"
        return True, ""

    def _fallback():
        # §5.4 兜底: 解析失败 → 回落澄清问询(列缺失要素请用户补全)
        return {"__clarify__": True}

    r = _call_turn.call(
        Purpose.EXTRACTION,
        [{"role": "system",
          "content": "你是需求分析师。从对话记录提取开发类需求规约：title 简短；"
                     "requirementMd=需求目标；designMd=技术方案要点(可从讨论归纳)；"
                     "allowedScopeMd/forbiddenScopeMd=允许/禁止改动范围(逐条行)；"
                     "acceptanceMd=验收标准(逐条行)。只输出结构化结果，不要发明讨论中没有的约束。"},
         {"role": "user", "content": f"对话记录:\n{transcript[:12000]}"}],
        tier=tier, schema=schema, max_tokens=2048,
        validate=_validate, fallback=_fallback)
    if r.get("degraded"):
        return {"ok": False, "receipt":
                "未能从对话中自动提取出完整需求——请补充以下要点后重试 /提取需求，"
                "或直接描述任务让我建卡(/执行)：\n"
                "- 目标(要达成什么)\n- 范围(可改哪些文件/模块)\n- 验收(如何算完成)"}
    payload = r.get("output")
    if not isinstance(payload, dict) or not (payload.get("title") or "").strip():
        return {"ok": False, "receipt":
                "未能从对话中提取出有效需求——请补充说明目标/范围后重试,"
                "或直接描述任务让我建卡(/执行)。"}
    from ..planning.req_spec import apply_spec_payload
    land = apply_spec_payload(payload, project=str(conv.get("projectId") or ""))
    if not land.get("ok"):
        return {"ok": False, "receipt": str(land.get("error") or "需求落库失败")}
    # 需求卡(specReady)由 apply_spec_payload→propose/amend 路径统一落流;
    # 此处不再重复发卡(cv-177 实证: 双卡片+文本回执三连发)
    rid = str(land.get("requirementId") or land.get("reqId") or "")
    return {"ok": True, "receipt": f"需求卡 {rid} 已提取(ready)，可 `/执行`。"}


def run_execute(conv: Dict[str, Any], executor_id: str = "",
                skip_plan: bool = False, on_phase=None,
                auto_start: bool = False) -> Dict[str, Any]:
    """直通 /执行：绑定 ready 规约 → 服务端建任务卡(待用户卡片确认)。

    executor_id(@cline 前缀)显式指定执行器——查注册表, 查不到显式失败不降级。"""
    from ...arch_routes import exec_bridge, store
    executor_id = (executor_id or "").strip()
    hint = None
    if executor_id:
        hint = exec_bridge.executor_hint_by_id(executor_id, conv)
        if not hint:
            return {"ok": False, "receipt":
                    f"执行器 `{executor_id}` 不在注册表中——请检查「执行器配置」"
                    "(支持: " + ", ".join(_registered_ids()) + ")。"}
    req_id = (conv.get("reqId") or "").strip()
    if not req_id:
        return {"ok": False, "receipt":
                "当前会话未绑定需求：开发类需求请先描述目标(系统会生成需求卡)，"
                "或直接描述任务让我建卡；也可点工具栏「提取需求」。"}
    row = store.RequirementsStore.get(req_id)
    if not row:
        return {"ok": False, "receipt": f"需求 {req_id} 不存在。"}
    active = store.RequirementsStore.spec_active(req_id) or {}
    snap = active.get("snapshot") or {}
    if (active.get("state") or "") != "confirmed":
        # 历史 draft 需求(旧流程产物) → 就地确认, 不再要求 /定稿
        c = store.RequirementsStore.spec_confirm(req_id)
        if not c.get("ok"):
            return {"ok": False, "receipt": str(c.get("error") or "规约确认失败")}
        snap = ((store.RequirementsStore.spec_active(req_id) or {}).get("snapshot")) or snap
    title = (snap.get("title") or row.get("title") or "实施任务").strip()[:120]
    instruction = _instruction_from_snapshot(snap)
    if not instruction.strip():
        return {"ok": False, "receipt": "规约内容为空，无法建卡。请 `/调整` 完善后重试。"}
    # 任务计划(环节十四): T2+ 挡位生成/续发有序计划; None = 单卡路径。
    # cv-199: 拆步是 LLM 长调用(LLM_SYNC_TIMEOUT 上限 300s)——按钮合成路径
    # (skip_plan)直接单卡; 带相位回调供直通链状态透出。
    if skip_plan:
        pass
    else:
        if on_phase:
            on_phase("plan")
        from ..planning.task_plan import maybe_plan_and_propose
        plan_res = maybe_plan_and_propose(
            conv, req_id,
            "\n".join(str(x) for x in (title, snap.get("desc"),
                                       snap.get("designMd")) if x),
            title, instruction, executor_hint=hint,
            spec_ver=int(active.get("ver") or 1))   # cv-248: 版本对齐记账
        if plan_res is not None:
            return plan_res
    if on_phase:
        on_phase("card")
    # P0 审计修复(A1): 直通单卡路径豁免图门禁——本路径无 LLM 在环,
    # "回炉 nudge architect"无从发生; 图门禁仅适用于 chat task.propose 路径
    # (architect LLM 可收到拒绝错误并补图重发)。
    task = exec_bridge.propose_task(conv, title, instruction, executor_hint=hint,
                                    gate_diagram=False)
    if not task.get("id"):
        # 无可用执行器等建卡失败: 原文显式返回(不降级不吞错)
        return {"ok": False, "receipt": str(task.get("error") or "建卡失败")}
    # cv-200: 按钮路径(auto_start)建卡即启动——「运行」语义 = 直接开跑,
    # 不再要求二次点「开始执行」; 失败时任务停在建卡态, 错误如实透出。
    if auto_start:
        if on_phase:
            on_phase("start")
        c = exec_bridge.confirm_task(task["id"])
        if not c.get("ok"):
            return {"ok": False,
                    "receipt": str(c.get("error") or "任务启动失败"),
                    "task": task}
        task["status"] = "running"
    return {"ok": True, "task": task}


def _registered_ids() -> list:
    try:
        from ...arch_routes.agent_executors import load_executors
        return [str(e.get("id") or "") for e in load_executors() if e.get("enabled", True)]
    except Exception:  # noqa: BLE001
        return []


def _instruction_from_snapshot(snap: Dict[str, Any]) -> str:
    """规约快照 → 任务卡 instruction(目标/方案/边界/验收，与 req.propose 分节对齐)。"""
    sections = []
    desc = str(snap.get("desc") or "").strip()
    # 防御: 存量数据的 desc 可能已内嵌分节标题(源头已在 _spec_snapshot 剥离)
    desc = re.sub(r"^(?:#{1,6}\s*)?(?:需求目标|目标|需求描述|需求)[:：]?\s*\n+",
                  "", desc)
    if desc:
        sections.append(f"## 需求目标\n\n{desc}")
    if str(snap.get("designMd") or "").strip():
        sections.append(f"## 方案\n\n{snap['designMd']}")
    allowed = [str(x) for x in (snap.get("allowedScope") or []) if str(x).strip()]
    forbidden = [str(x) for x in (snap.get("forbiddenScope") or []) if str(x).strip()]
    if allowed:
        sections.append("## 允许改动范围\n\n" + "\n".join(f"- {x}" for x in allowed))
    if forbidden:
        sections.append("## 禁止改动\n\n" + "\n".join(f"- {x}" for x in forbidden))
    acceptance = [str(x) for x in (snap.get("acceptance") or []) if str(x).strip()]
    if acceptance:
        sections.append("## 验收标准\n\n" + "\n".join(f"- {x}" for x in acceptance))
    est = int(snap.get("estMin") or 0)
    if est > 0:
        sections.append(f"预估工作量：{est} 分钟")
    return "\n\n".join(sections)
