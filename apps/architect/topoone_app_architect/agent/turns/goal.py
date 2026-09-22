"""目标理解层(GU) — GoalProfile 产出器 + 决策表解析(goal-understanding-2609.md)。

定位(2026-09-22 定稿): 对「非指令直通」输入统一产出理解产物 GoalProfile,
经 flow_policy.goal 决策表生成**回合指引**注入(教学=决策)。两层分界:
- 人格层(恒定): 能力文档静态单源(cognition/prompt.py posture 块, GU-3 统一)——
  防多轮目标转换的人格抖动;
- 指引层(每回合): 决策表动态生成, 只判定本回合路线, 不定义人格。

- 理解器梯度: L0 确定性(指令正则/显式指令判定/策略库/意图词表) → L1 会话上下文
  (绑定需求/相位); L2 受限 LLM(turns.intent_llm)GU-5 并入; L3 问用户是决策出口
  (clarify-first/ask-one-question), 是正当行为而非失败。
- 理解器代码单源(可测试=防双源); 决策与文案走 policy.goal(规则推展非硬编码,
  缺省+深合并+写侧校验+fail-soft 同款基座)。
- 保守边界: 本模块零 arch_routes 依赖(纯函数+policy 注入); 不触碰确定性层
  (指令直通/相位硬闸在其之前, 仍只吃确定性意图词——防守线①)。
"""
from __future__ import annotations

import re

from typing import Any, Dict, List, Optional

from ..governance.flow_policy import DEFAULT_FLOW_POLICY, GOAL_ACTIONS

__all__ = ["build_goal_profile", "resolve_goal_directive", "apply_goal_directive"]

# kind 级候选菜单(present-options): 策略×执行词弱撞 → 性质未定, 请用户定性。
# 候选条目为代码单源数据; 菜单如何呈现走 policy.goal.directives.present-options。
_KIND_CANDIDATES = [
    {"id": "requirement", "label": "需求规约（立卡，纳入迭代）",
     "hint": "要做成项目里的功能，长期迭代维护"},
    {"id": "operation", "label": "一次性操作（单卡直达）",
     "hint": "跑一次就完事，不留需求卡"},
]

# 构建标记(弱撞菜单的第三判据): 「写个脚本统计文件数」(构建意图)出菜单,
# 「帮我跑个脚本看看」(纯执行框架)维持操作单判——防菜单滥用回归僵硬。
_BUILD_MARK_RE = re.compile(
    r"(做一个|做个|写个|写一个|开发|实现|封装|新建|新增|加一个|添加|搭一个)")


def build_goal_profile(question: str, conv: Optional[dict] = None,
                       escalation: Optional[dict] = None,
                       context: str = "",
                       focus: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """L0→L1(→L2) 理解: 输入 → GoalProfile(纯数据, 可遥测)。

    L0 优先序: 指令正则 > 显式修改指令(目标值明确) > 目标策略库(记分裁决)
    > 通用执行意图词表。L1 不改写 L0 的 kind, 只补 target/boundReq/conflict
    与兜底 kind; 同时携带 clarifyMode/explicit 决策面事实。
    候选面(present-options): 信号弱撞时不强行单判——
      策略+执行词弱撞(score<2)且策略词独立于执行词表 → kind 级候选
      (需求 vs 操作, 性质未定; 词全被覆盖则维持操作单判, 不僵硬);
      无执行词 + 策略 top-2 分差≤1 → 策略级候选(目标类别未定)。
      决策表 {candidates:true} → present-options 请用户定性, 下回合重判收敛。
    L2(escalation.llmFallback, 缺省关): L0 无信号或低置信时的受限 LLM 分类
    (intent_llm.classify_intent, 缓存+fail-soft, 携带 context 近期对话摘要)
    ——只升格 operation, 不改写确定性命中(防守线①)。
    """
    q = str(question or "").strip()
    conv = conv or {}
    # inquiry 兜底置信 0.6(≥决策表卫兵线): 未检出任何行动信号时,「这是咨询」
    # 本身是高概率判定——先答后看, 不宜反问(反问=新的僵硬)
    prof: Dict[str, Any] = {"kind": "inquiry", "target": "new",
                            "strategy": None, "strategyLabel": "",
                            "strategyQuestions": [], "boundReq": "",
                            "conflict": None, "confidence": 0.6, "sources": [],
                            "explicit": False, "candidates": [],
                            "focusTop": "",
                            "contextChars": len(str(context or "")),
                            "clarifyMode": str((conv or {}).get("clarifyMode")
                                               or "auto")}
    # L0-1 确定性指令/确认(编排层②通常已拦; 此处恒等守护——批戊: 意图原语单源)
    from ..perception.commands import match_imperative
    if match_imperative(q):
        prof.update(kind="command", confidence=1.0)
        prof["sources"].append("command")
        return prof
    # L0-2 显式修改指令(「X 修改为 Y」目标值明确 → 需求, 免澄清路径)
    from ..requirements.clarify import is_explicit_instruction
    if is_explicit_instruction(q):
        prof.update(kind="requirement", confidence=0.85, explicit=True)
        prof["sources"].append("explicit-instruction")
    else:
        # L0-3/L0-4 边界裁决 + 候选面: 策略库(需求知识) vs 通用执行词表
        # (操作原型)。强命中/单信号 → 现状单判; 独立弱撞 → 双候选菜单。
        from ..requirements.clarify import match_strategy, \
            match_strategy_candidates
        from ..perception.intent import GENERIC_EXEC_RE
        strat = match_strategy(q)
        exec_spans = [m.group(0) for m in GENERIC_EXEC_RE.finditer(q)]
        exec_hit = bool(exec_spans)
        score = int(strat.get("score") or 0) if strat else 0
        # 策略信号独立性: 命中词全被执行词覆盖(如「统计一下文件数」的 统计)
        # → 执行信号已完全解释文本, 维持操作单判(不僵硬); 存在词表外独立词
        # (如「写个脚本统计文件数」的 脚本) → 真混合信号, 候选菜单。
        hit_kws = [kw for kw in ((strat or {}).get("kws") or ()) if kw in q.lower()]
        indep = any(kw not in exec_spans for kw in hit_kws)
        if strat and exec_hit and score < 2 and indep \
                and _BUILD_MARK_RE.search(q):
            # kind 级弱撞: 独立策略词 + 构建意图, 性质未定 → 需求 vs 操作
            prof.update(kind="requirement", confidence=0.6,
                        candidates=_KIND_CANDIDATES)
            prof["sources"].append("boundary-ambiguous")
        else:
            cands = match_strategy_candidates(q) \
                if (strat and not exec_hit) else []
            if len(cands) >= 2 and \
                    int(cands[0].get("score") or 0) - \
                    int(cands[1].get("score") or 0) <= 1:
                # 策略级近平: 「搭建环境顺便封装组件」类别未定 → 双问题集候选
                top = cands[0]
                prof.update(kind="requirement", confidence=0.75,
                            strategy=top.get("key"),
                            strategyLabel=top.get("label") or "",
                            strategyQuestions=[f"{el}: {t}" for el, t
                                               in top.get("questions") or []],
                            candidates=[{"id": f"strategy:{c.get('key')}",
                                         "label": str(c.get("label")
                                                      or c.get("key")),
                                         "hint": "按该目标给出标准澄清问题集"}
                                        for c in cands[:2]])
                prof["sources"].append("strategy-ambiguous")
            elif strat and (not exec_hit or score >= 2):
                prof.update(kind="requirement", strategy=strat.get("key"),
                            strategyLabel=strat.get("label") or "",
                            strategyQuestions=[f"{el}: {t}"
                                               for el, t in strat.get("questions") or []],
                            confidence=0.9)
                prof["sources"].append("strategy")
            elif exec_hit:
                prof.update(kind="operation", confidence=0.7)
                prof["sources"].append("generic-exec")
    # L1 会话上下文: 绑定需求 → 续接面(kind 不被上下文改写, 只补 target/兜底)
    rid = str((conv or {}).get("reqId") or "")
    if rid:
        prof["boundReq"] = rid
        if prof["sources"] == []:
            prof.update(kind="continuation", target=f"req:{rid}",
                        confidence=0.5)
            prof["sources"].append("context")
        elif prof["kind"] == "requirement":
            prof["target"] = f"req:{rid}"
    # L1 相位冲突(咨询面; 硬拦截仍归相位硬闸——防守线①)
    # 批戊: 相位事实面优先取焦点栈(派生单源), conv.flowState 为兼容回退
    phase = str((focus or {}).get("phase")
                or (conv or {}).get("flowState") or "")
    if phase == "interrupted" \
            and prof["kind"] in ("requirement", "operation"):
        prof["conflict"] = "phase:interrupted"
    # 焦点摘要(遥测/决策面; 第一版只透传不加 when 键)
    prof["focusTop"] = str(((focus or {}).get("top") or {}).get("kind") or "")
    # L2 受限 LLM 分类(GU-5): 开关 escalation.llmFallback(缺省关)——仅当 L0
    # 无行动信号(inquiry 兜底)且文本 ≤ maxTextChars 时, 用轻任务分类尝试升格
    # operation(携带 context 近期对话摘要); LLM 失败/低置信 → 原样
    # (正则结果永不因兜底改变)。
    if escalation and escalation.get("llmFallback") \
            and prof["kind"] == "inquiry" and q \
            and len(q) <= int(escalation.get("maxTextChars") or 200):
        try:
            from .intent_llm import classify_intent
            res = classify_intent(q, context=str(context or ""))
            min_conf = float(escalation.get("minConfidence") or 0.7)
            if isinstance(res, dict) \
                    and res.get("intent") == "generic_exec" \
                    and float(res.get("confidence") or 0) >= min_conf:
                prof.update(kind="operation",
                            confidence=float(res.get("confidence") or 0))
                prof["sources"].append("llm")
        except Exception:  # noqa: BLE001 — 兜底失败不碍主链
            pass
    return prof


def resolve_goal_directive(profile: Dict[str, Any], pol: Dict[str, Any]) -> Dict[str, Any]:
    """决策表顺序匹配首中即停 → {action, text, tools}(text 可为空=不注入)。

    tools=命中规则的写类工具限定(未配置/未命中 → None=不限面);
    读类面由 toolClasses.read 恒供(消费方 orchestrator fnmatch 解析)。
    坏规则跳过(fail-soft; 写侧已校验, 读侧兜底); 全不命中 → answer 兜底。
    """
    cfg = (pol.get("goal") or {})
    for rule in (cfg.get("decision") or []):
        if not isinstance(rule, dict):
            continue
        try:
            if _when_hit(rule.get("when") or {}, profile):
                action = str(rule.get("then") or "")
                if action not in GOAL_ACTIONS:
                    continue
                tools = rule.get("tools")
                tools = [str(t) for t in tools] \
                    if isinstance(tools, list) else None
                text = _directive_text(pol, action, profile,
                                       str(rule.get("with") or ""))
                return {"action": action, "text": text, "tools": tools}
        except Exception:  # noqa: BLE001 — 单规则故障不碍决策
            continue
    return {"action": "answer",
            "text": _directive_text(pol, "answer", profile, ""),
            "tools": None}


def _when_hit(when: Dict[str, Any], p: Dict[str, Any]) -> bool:
    for k, v in (when or {}).items():
        if k == "kind":
            if p.get("kind") != v:
                return False
        elif k == "strategy":
            if v == "*":
                if not p.get("strategy"):
                    return False
            elif p.get("strategy") != v:
                return False
        elif k == "confidence<":
            if not (float(p.get("confidence") or 0) < float(v)):
                return False
        elif k == "clarifyMode":
            if str(p.get("clarifyMode") or "auto") != v:
                return False
        elif k == "explicit":
            if bool(p.get("explicit")) != bool(v):
                return False
        elif k == "candidates":
            if bool(p.get("candidates")) != bool(v):
                return False
        else:
            return False          # 未知条件键 → 规则不命中
    return True


def _directive_text(pol: dict, action: str, p: Dict[str, Any],
                    with_strategy: str) -> str:
    """动作 → 指引文案(policy.directives 可覆盖; 坏模板回落缺省)。"""
    templates = (pol.get("goal") or {}).get("directives") or {}
    defaults = (DEFAULT_FLOW_POLICY.get("goal") or {}).get("directives") or {}
    key = action
    if action == "clarify-first" and with_strategy == "strategy" \
            and p.get("strategyQuestions"):
        key = "clarify-first"
    elif action == "clarify-first":
        key = "clarify-first-generic"
    tpl = str(templates.get(key) if templates.get(key) is not None
              else defaults.get(key, ""))
    if action == "clarify-first" and with_strategy == "strategy" \
            and not p.get("strategyQuestions"):
        tpl = str(templates.get("clarify-first-generic")
                  or defaults.get("clarify-first-generic", ""))
    kw = {"label": str(p.get("strategyLabel") or "开发"),
          "questions": "\n".join(f"  · {x}" for x in p.get("strategyQuestions") or []),
          "reqId": str(p.get("boundReq") or "(无)"),
          "options": "\n".join(f"  {i}. {c.get('label')}——{c.get('hint')}"
                               for i, c in enumerate(p.get("candidates") or [], 1))}
    try:
        return tpl.format(**kw) if tpl else ""
    except (KeyError, IndexError, ValueError):
        try:
            return str(defaults.get(key, "")).format(**kw)
        except (KeyError, IndexError, ValueError):
            return ""


def _recent_user_context(msgs: List[dict], question: str, limit: int = 2,
                         per_char: int = 80) -> str:
    """L2 上下文携带面: msgs 里最近 limit 条用户消息摘要(排除本回合 question)。

    纯 msgs 派生, 零 store 依赖(goal.py 边界); 供 classify_intent 消歧。
    """
    out: List[str] = []
    for m in reversed(msgs or []):
        if str((m or {}).get("role") or "") != "user":
            continue
        c = str(m.get("content") or "").strip()
        if not c or c == str(question or "").strip():
            continue            # 本回合问题本身不进上下文
        out.append(c[:per_char])
        if len(out) >= limit:
            break
    return "\n".join(f"- {x}" for x in reversed(out))


def plan_goal_directive(question: str, conv: Optional[dict],
                        pol: Optional[dict] = None,
                        msgs: Optional[List[dict]] = None,
                        focus: Optional[Dict[str, Any]] = None) -> Optional[dict]:
    """编排接线(③.5 前半, 批丁拆分): 产出 profile → 决策 → 遥测。

    在上下文装配**之前**调用——tools 限定须参与 system 渲染(工具子集面);
    msgs/history 可选传入(L2 上下文携带面: 最近用户消息摘要)。
    返回 {profile, action, text, tools}; 故障回退 None(无指引不限面)。
    """
    try:
        if pol is None:
            try:
                from ...arch_routes import store as _s
                from ..governance.flow_policy import load_flow_policy
                pol = load_flow_policy(_s.CollabConfigStore.get)
            except Exception:  # noqa: BLE001
                import copy as _copy
                pol = _copy.deepcopy(DEFAULT_FLOW_POLICY)
        esc = ((pol or {}).get("goal") or {}).get("escalation")
        ctx = _recent_user_context(msgs or [], question)
        prof = build_goal_profile(question, conv, escalation=esc, context=ctx,
                                  focus=focus)
        res = resolve_goal_directive(prof, pol or {})
        # 上下文感知限面(先于遥测: 记录实际生效面)——规则声明的 req.amend
        # 依赖「会话已绑定需求」, 未绑定时必败(模型会拿它挣扎落卡), 剔除降纯读。
        if res.get("tools") and "req.amend" in (res.get("tools") or []) \
                and not str(prof.get("boundReq") or ""):
            res["tools"] = [t for t in res["tools"] if t != "req.amend"]
        try:
            from ..reflection import dataset as _ds
            # 注意: record 首参名为 kind, 判定种类改用 goalKind 键(防撞名)
            _ds.record("goal_profile", goalKind=str(prof.get("kind") or ""),
                       strategy=str(prof.get("strategy") or ""),
                       confidence=prof.get("confidence"),
                       action=res.get("action"),
                       conflict=str(prof.get("conflict") or ""),
                       candidates=len(prof.get("candidates") or []),
                       tools=",".join(res.get("tools") or []) or "",
                       focusTop=str(prof.get("focusTop") or ""),
                       contextChars=len(ctx))
        except Exception:  # noqa: BLE001 — 遥测不碍主链
            pass
        return {"profile": prof, "action": res.get("action"),
                "text": res.get("text") or "", "tools": res.get("tools")}
    except Exception:  # noqa: BLE001 — GU 故障回退无指引(正则词表面仍在)
        return None


def inject_goal_directive(msgs: List[dict], plan: Optional[dict]) -> None:
    """编排接线(③.5 后半): 指引文案注入 msgs(index 1)。失败不碍主链。"""
    try:
        if plan and plan.get("text"):
            msgs.insert(1, {"role": "system", "content": plan["text"]})
    except Exception:  # noqa: BLE001
        pass


def apply_goal_directive(msgs: List[dict], question: str, conv: Optional[dict],
                         pol: Optional[dict] = None) -> Optional[dict]:
    """组合入口(= plan + inject; 兼容既有调用面/测试)。"""
    plan = plan_goal_directive(question, conv, pol, msgs=msgs)
    inject_goal_directive(msgs, plan)
    return plan
