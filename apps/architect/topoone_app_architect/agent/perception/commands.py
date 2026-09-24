"""会话指令直通(感知层) — 意图原语分类器 + 直通动作执行器(批戊收编)。

三层判别模型的本层职责: **词表定意图**——match_imperative 把整条消息分类为
四原语(execute/confirm/continue/retry); 指代消解归焦点栈
(memory/focus.resolve_intent), 动作执行为下方 run_* 执行器。
v2 流程(无草稿态)：需求卡按需出现——开发类需求由模型/围栏 req.propose
直接落 ready 卡(GU 每回合意图重判 + spec 载荷围栏代落 + 澄清挡收敛,
提取链已退役: 自然语言即兜底, "把上面的需求落成卡"→GU requirement 面)。
非开发类需求(分析型问答等)不产需求卡, 纯对话回答。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# 意图原语词表(整条消息恰为该词, 可带 @执行器 前缀——确定性直通不经 LLM,
# 弱模型自由轮会输出"(调用xx工具)"占位文本而不真调, cv-181 实证)。
# extract 退役(cv-254): 需求卡产出三路全覆盖(GU 指引/围栏代落/澄清挡),
# 手动提取按钮+指令已从 UI/词表/直通链全删, 自然语言为兜底出口。
_IMPERATIVE_RE = re.compile(
    r"^(?:@(?P<executor>\S+)\s+)?"
    r"(?:(?:/(?P<execute>执行))|"
    r"(?P<confirm>确认执行|确认任务|确认|同意|开始执行|开始吧|开始|ok|OK|好的?)|"
    r"(?P<cont>继续执行|继续)|(?P<retry>重试))[。.!！]?\s*$")

_INTENT_OF = {"execute": "execute",
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
                "或直接描述任务让我建卡。"}
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
