"""流程驱动配置(agent.flow.policy) — 状态/规则/策略数据驱动基座(采纳文档 §三)。

边界裁决(2026-09-21 定稿留痕, docs/architect/agent-arch-gap-adoption-2609.md):
- 配置化的是**行为面**(每相位的 note/guard/hint/overlay + 注入限额 + 聚合窗口),
  不是**迁移面**——derive 派生语义是防双源根基, 配置化它=制造第二真相源
  (架构红线, meta.jobs 教训); 词表(states.FLOW_*)同样冻结在代码。
- 单源缺省: DEFAULT_FLOW_POLICY 为代码缺省(版本受控); CollabConfigStore 键
  `agent.flow.policy` 深合并覆盖; 读侧坏值整体回落缺省(fail-soft),
  写侧 REST 严格校验(fail-fast, arch_routes/flow_policy.py)。
- 意图按名引用(防守线①): 守卫规则引用 INTENT 注册名(匹配器=确定性代码单源),
  配置不内嵌正则; 自定义 regex 写入时 compile 校验, 读侧坏正则静默跳过。
  LLM 意图永不进入硬闸——本模块全部匹配器确定性, 无 LLM 通道。
- 注入面规则(repairNotes/overflowDigest/assemblyBudget)与聚合规则
  (aggregation)同置此表; 行为开关并入 agent.comp.overrides
  (repair_note_injection/overflow_digest/swallow_counters, 缺省启用)。
"""
from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...arch_routes.store.states import FLOW_PHASES
from .goal_defaults import DEFAULT_GOAL_STRATEGIES
from ..turns.help_docs import DEFAULT_HELP_TOPICS

logger = logging.getLogger("arch.flow_policy")

POLICY_KEY = "agent.flow.policy"

# 守卫补充意图词(相位守卫专用: 建卡/启动类; 单源随本模块, 不污染路由纠偏面)
_DISPATCH_EXTRA_RE = re.compile(
    r"(建卡|创建任务|新建任务|任务卡|task\.propose|开始执行|启动任务|下发)")


def _re_generic_exec() -> Any:
    from ..perception.intent import GENERIC_EXEC_RE  # G1 裁决: 单源复用
    return GENERIC_EXEC_RE


# 守卫意图注册表(名→匹配器工厂; 惰性解析防循环导入)。配置只引用名。
_INTENT_MATCHERS: Dict[str, Callable[[], Any]] = {
    "generic_exec": _re_generic_exec,
    "dispatch_extra": lambda: _DISPATCH_EXTRA_RE,
}
INTENT_NAMES = tuple(sorted(_INTENT_MATCHERS))


def intent_pattern(name: str) -> Optional[Any]:
    fn = _INTENT_MATCHERS.get(str(name or ""))
    if fn is None:
        return None
    try:
        return fn()
    except Exception:  # noqa: BLE001 — 匹配器解析故障不炸守卫
        return None


DEFAULT_FLOW_POLICY: Dict[str, Any] = {
    "version": 1,
    "phases": {
        "clarifying": {
            "note": ("【流程相位：澄清中】存在未兑现的规约草稿卡——聚焦补全要素"
                     "(目标/方案要点/允许范围/禁止改动/验收)，用户确认后再落卡。"),
            "elementHints": "high",
        },
        "armed": {
            "note": ("【流程相位：待执行】存在待执行任务卡——用户确认即启动；"
                     "可继续对话调整卡片内容。"),
        },
        "executing": {
            "note": ("【流程相位：执行中】有任务正在执行——回答侧重转达与进展解读，"
                     "不复述回执；需求变更走版本链(amend 产生新版本，不影响运行中契约)；"
                     "新提案排队为建议，不打断执行。"),
        },
        "reviewing": {
            "note": ("【流程相位：待验收】有已完成回执待处理——引导用户合并/验收"
                     "或标记已阅；确认后自然进入下一步。"),
        },
        "interrupted": {
            "note": ("【流程相位：异常中断】存在未能自动恢复的任务——引导用户先处理"
                     "中断任务(恢复/停止)，暂勿下发新任务。"),
            "guards": [{
                "intents": ["generic_exec", "dispatch_extra"],
                "reply": ("⛔ 会话处于**异常中断**态：存在未能自动恢复的任务，"
                          "新任务下发已暂停。\n请先在会话处理中断任务（工具栏「恢复」"
                          "自动核对执行器实际状态，或「停止」终态化保留 worktree），"
                          "恢复后再下发。"),
            }],
        },
    },
    "hintTemplates": {
        "armed": "有 {n} 张任务卡待执行——可「开始执行」或继续对话调整",
        "reviewing": "有 {n} 份完成回执待处理——合并/验收/标记已阅",
        "reqDone": "绑定需求已完结——继续迭代请新建需求",
    },
    "injections": {
        # 修复经验注入(S1): maxPerTurn=每回合上限; weakTierMax=最弱挡收紧;
        # keepLatest=每会话保留单元数(写侧修剪)
        "repairNotes": {"enabled": True, "maxPerTurn": 3, "keepLatest": 5,
                        "weakTierMax": 1},
        # 溢出摘要注入(S3): 历史非空消息数超 overflowTrigger → 溢出段摘要;
        # windowCap=保留原文条数; maxChars=摘要注入上限
        "overflowDigest": {"enabled": True, "windowCap": 20,
                           "overflowTrigger": 30, "maxChars": 1200},
        # 统一装配预算(防守线③): baseChars×挡位系数=注入段总字数上限
        "assemblyBudget": {"baseChars": 4000, "floorChars": 200,
                           "coefMin": 0.2, "coefMax": 2.0},
    },
    # 失败聚合窗口(S2; #3 tierSuggested 数据地基)
    "aggregation": {"windowDays": 14},
    # 挡位建议(#3, 建议值+人审; 纯读永不写档案——防守线②):
    # 采样门槛与失败率阈值(高失败→建议升档/低失败→建议降档省算力)
    "tierSuggestion": {"minCalls": 10, "failHigh": 0.35, "failLow": 0.1},
    # 目标理解决策表(GU, goal-understanding-2609): 规则顺序匹配首中即停;
    # then 动作词注册制(代码单源执行器), 配置只选择; 文案模板可覆盖;
    # 批丁: rules.tools 按路线限定写类工具(读类经 toolClasses.read 恒可用)——
    # 工具面 5K 全量 → 本轮路线子集(提示面+执行面双重收敛, 中小模型注意力聚焦)
    "goal": {
        "decision": [
            {"when": {"kind": "command"}, "then": "passthrough"},
            # 低置信卫兵前置: 理解不可靠 → 先问(合法出口); 正常档位均 ≥0.5 不触发
            {"when": {"confidence<": 0.5}, "then": "ask-one-question",
             "tools": []},
            # 候选菜单(优先于单判规则; kind 级在前=先定性质再谈澄清):
            # 策略+执行词弱撞 / 策略 top-2 分差≤1 → 请用户定性(GU 重判收敛)
            {"when": {"candidates": True}, "then": "present-options",
             "tools": []},
            {"when": {"kind": "requirement", "strategy": "*"},
             "then": "clarify-first", "with": "strategy", "tools": ["req.amend"]},
            {"when": {"kind": "requirement"}, "then": "propose-requirement",
             "tools": ["req.propose", "req.amend"]},
            {"when": {"kind": "operation"}, "then": "propose-task",
             "tools": ["task.propose"]},
            {"when": {"kind": "continuation"}, "then": "continue",
             "tools": ["req.amend", "req.propose"]},
            {"when": {"kind": "help"}, "then": "provide-help",
             "tools": ["help.lookup"]},
            # cv-242: 兜底轮纯读(零写面)——落卡权=确定性意图命中的专属权利;
            # 诉求收敛靠下一回合重判(每回合重判原则), 不靠兜底轮脑补
            {"when": {"kind": "inquiry"}, "then": "answer", "tools": []},
            # 可配置扩展位(缺省不启用): forced 全量先问(含策略未命中)由运营按需加
            # {"when": {"kind": "inquiry", "clarifyMode": "forced"},
            #  "then": "clarify-first"}——when 支持 clarifyMode/explicit 键。
        ],
        # 读类工具类(pattern, fnmatch): GU 限面时恒可用(取证/检索面不设限)
        "toolClasses": {
            "read": ["kb.*", "map.*", "ctx.*", "conv.*", "code.*",
                     "project.ctx", "asset.semantic.search",
                     "asset.semantic.detail", "asset.semantic.stats",
                     "asset.semantic.mappings", "asset.semantic.reconcile",
                     "capability.evaluate", "probe.run", "help.*"],
        },
        # 澄清策略库(D5 偿还, 2026-09-22 配置化): 引擎在 requirements/clarify.py
        # (match/gap/directive), 条目在此单源——改一条澄清问题 = PUT /flow-policy,
        # 零发版。写侧校验: key 唯一/questions 二元组/要素词表。
        "strategies": DEFAULT_GOAL_STRATEGIES,
        "directives": {
            "passthrough": "",
            "clarify-first": (
                "【目标理解(本回合)】判定为「{label}」类开发诉求，关键要素待明确"
                "——本回合先澄清后落卡：按以下问题集中编号提问，每问先给出你基于"
                "上下文的推断默认值请用户确认或补全，禁止开放式泛问：\n{questions}\n"
                "用户答复后用 req.propose/req.amend 回填再建卡；首轮禁止直接落需求卡。"),
            "clarify-first-generic": (
                "【目标理解(本回合)】开发类诉求但要素待明确——本回合先澄清后落卡："
                "按五要素框架(①目标 ②方案要点 ③允许范围 ④禁止改动 ⑤验收标准)"
                "逐项给出推断默认值请用户确认，禁止开放式泛问；用户答复后 "
                "req.propose/req.amend 回填再建卡，首轮禁止直接落需求卡。"),
            "propose-requirement": (
                "【目标理解(本回合)】判定为明确的开发类需求——收敛为需求规约"
                "(req.propose: title/requirementMd/designMd)；"
                "既有需求({reqId})的补充调整走 req.amend 新版本"),
            "propose-task": (
                "【目标理解(本回合)】判定为一次性工具操作——task.propose 单卡"
                "直达(默认保存)，勿绕需求流程"),
            "continue": (
                "【目标理解(本回合)】续接既有需求({reqId})——补充/调整按 "
                "req.amend 收敛为新版本；用户提问直接回答"),
            "answer": (
                "【目标理解(本回合)】咨询/讨论——直接回答；本回合不落任何卡"
                "(用户后续表达开发诉求时系统会自动识别并放开建卡工具)"),
            "provide-help": (
                "【目标理解(本回合)】产品使用咨询——调用 help.lookup 检索使用文档"
                "主题并基于内容回答；文档内容可能滞后于当前版本，以系统实际行为为准；"
                "本回合不落任何卡。"),
            "ask-one-question": (
                "【目标理解】意图不确定——先向用户提一个最关键的澄清问题，"
                "本回合不落任何卡"),
            "present-options": (
                "【目标理解(本回合)】用户诉求的路径存在歧义——本回合先请用户定性，"
                "禁止落任何卡：把下列候选编号列出请用户选择，或请用户直接补充一句描述；"
                "用户答复后按其选择推进(需求→req.propose/req.amend；"
                "操作→task.propose)。\n{options}"),
        },
        "escalation": {"llmFallback": False, "minConfidence": 0.7,
                       "maxTextChars": 200},
        # 帮助主题缺省表(批戊补: 产品使用咨询内容供给)——非最终版, 随迭代
        # 更新(配置全量覆盖: PUT /flow-policy 零发版); 校验见 _validate_help_topics
        "helpTopics": DEFAULT_HELP_TOPICS,
    },
}

_TOP_KEYS = ("version", "phases", "hintTemplates", "injections", "aggregation",
             "tierSuggestion", "goal")

GOAL_KINDS = ("command", "requirement", "operation", "inquiry", "continuation",
              "help")
GOAL_ACTIONS = ("passthrough", "clarify-first", "propose-requirement",
                "propose-task", "continue", "answer", "ask-one-question",
                "present-options", "provide-help")
_PHASE_KEYS = ("note", "elementHints", "guards")
_ELEMENTS = ("low", "mid", "high")   # phases.elementHints 档位词表


def validate_flow_policy(p: Any) -> Tuple[bool, List[str]]:
    """写侧严格校验(fail-fast): 相位名∈词表/意图名∈注册表/正则可编译/数字钳界。
    返回 (ok, errors)。"""
    errs: List[str] = []
    if not isinstance(p, dict):
        return False, ["policy 必须是对象"]
    errs += [f"未知顶层键: {k}" for k in p if k not in _TOP_KEYS]
    if "version" in p and not isinstance(p["version"], int):
        errs.append("version 须为整数")
    phases = p.get("phases")
    if phases is not None:
        if not isinstance(phases, dict):
            errs.append("phases 须为对象")
        else:
            for name, ph in phases.items():
                if name not in FLOW_PHASES:
                    errs.append(f"未知相位: {name}")
                    continue
                if not isinstance(ph, dict):
                    errs.append(f"phases.{name} 须为对象")
                    continue
                errs += [f"phases.{name} 未知键: {k}"
                         for k in ph if k not in _PHASE_KEYS]
                note = ph.get("note")
                if note is not None and not isinstance(note, str):
                    errs.append(f"phases.{name}.note 须为字符串或 null")
                eh = ph.get("elementHints")
                if eh is not None and eh not in _ELEMENTS:
                    errs.append(f"phases.{name}.elementHints 须为 low/mid/high/null")
                guards = ph.get("guards")
                if guards is not None:
                    errs += _validate_guards(name, guards)
    hints = p.get("hintTemplates")
    if hints is not None and (not isinstance(hints, dict)
                              or any(not isinstance(v, str)
                                     for v in hints.values())):
        errs.append("hintTemplates 须为字符串映射")
    errs += _validate_injections(p.get("injections"))
    agg = p.get("aggregation")
    if agg is not None:
        if not isinstance(agg, dict):
            errs.append("aggregation 须为对象")
        else:
            wd = agg.get("windowDays")
            if wd is not None and (not isinstance(wd, int)
                                   or not (1 <= wd <= 365)):
                errs.append("aggregation.windowDays 须为 1..365 整数")
            errs += [f"aggregation 未知键: {k}" for k in agg
                     if k not in ("windowDays",)]
    _validate_num_obj(p.get("tierSuggestion"), "tierSuggestion",
                      (("minCalls", 1, 100000, True),
                       ("failHigh", 0.0, 1.0, False),
                       ("failLow", 0.0, 1.0, False)), errs)
    ts = p.get("tierSuggestion")
    if isinstance(ts, dict) and isinstance(ts.get("failLow"), (int, float)) \
            and isinstance(ts.get("failHigh"), (int, float)) \
            and ts["failLow"] >= ts["failHigh"]:
        errs.append("tierSuggestion.failLow 须小于 failHigh")
    errs += _validate_goal(p.get("goal"))
    return (not errs, errs)


def _validate_goal(goal: Any) -> List[str]:
    """GU 决策表校验: when 条件键/ kind/then 词表/策略条目/文案键钳界(fail-fast)。"""
    if goal is None:
        return []
    if not isinstance(goal, dict):
        return ["goal 须为对象"]
    errs: List[str] = []
    errs += [f"goal 未知键: {k}" for k in goal
             if k not in ("decision", "directives", "escalation", "strategies",
                          "toolClasses", "helpTopics")]
    decision = goal.get("decision")
    if decision is not None:
        if not isinstance(decision, list):
            errs.append("goal.decision 须为数组")
        else:
            for i, rule in enumerate(decision):
                if not isinstance(rule, dict):
                    errs.append(f"goal.decision[{i}] 须为对象")
                    continue
                errs += [f"goal.decision[{i}] 未知键: {k}"
                         for k in rule if k not in ("when", "then", "with",
                                                    "tools")]
                when = rule.get("when")
                if not isinstance(when, dict) or not when:
                    errs.append(f"goal.decision[{i}].when 须为非空对象")
                else:
                    errs += [f"goal.decision[{i}].when 未知条件键: {k}"
                             for k in when
                             if k not in ("kind", "strategy", "confidence<",
                                          "clarifyMode", "explicit",
                                          "candidates")]
                    if "kind" in when and when["kind"] not in GOAL_KINDS:
                        errs.append(f"goal.decision[{i}].when.kind 非法: "
                                    f"{when['kind']}(可用: {','.join(GOAL_KINDS)})")
                    if "candidates" in when and \
                            not isinstance(when["candidates"], bool):
                        errs.append(f"goal.decision[{i}].when.candidates 须为布尔")
                    if "explicit" in when and not isinstance(when["explicit"], bool):
                        errs.append(f"goal.decision[{i}].when.explicit 须为布尔")
                    if "clarifyMode" in when and \
                            when["clarifyMode"] not in ("auto", "forced"):
                        errs.append(f"goal.decision[{i}].when.clarifyMode 非法: "
                                    f"{when['clarifyMode']}(可用: auto,forced)")
                    if "confidence<" in when and \
                        (not isinstance(when["confidence<"], (int, float))
                         or not (0 <= when["confidence<"] <= 1)):
                        errs.append(f"goal.decision[{i}].when.confidence< 须为 0..1")
                act = rule.get("then")
                if act not in GOAL_ACTIONS:
                    errs.append(f"goal.decision[{i}].then 非法动作: {act}"
                                f"(可用: {','.join(GOAL_ACTIONS)})")
                if "with" in rule and rule["with"] not in ("", "strategy"):
                    errs.append(f"goal.decision[{i}].with 非法: {rule['with']}")
                if "tools" in rule and (
                        not isinstance(rule["tools"], list)
                        or any(not isinstance(t, str) or not t.strip()
                               for t in rule["tools"])):
                    errs.append(f"goal.decision[{i}].tools 须为非空字符串数组")
    directives = goal.get("directives")
    if directives is not None:
        if not isinstance(directives, dict):
            errs.append("goal.directives 须为对象")
        else:
            errs += [f"goal.directives 未知动作键: {k}" for k in directives
                     if k not in GOAL_ACTIONS + ("clarify-first-generic",)]
            errs += [f"goal.directives.{k} 须为字符串"
                     for k, v in directives.items() if not isinstance(v, str)]
    esc = goal.get("escalation")
    if esc is not None:
        if not isinstance(esc, dict):
            errs.append("goal.escalation 须为对象")
        else:
            errs += [f"goal.escalation 未知键: {k}" for k in esc
                     if k not in ("llmFallback", "minConfidence", "maxTextChars")]
            if "llmFallback" in esc and not isinstance(esc["llmFallback"], bool):
                errs.append("goal.escalation.llmFallback 须为布尔")
            mc = esc.get("minConfidence")
            if mc is not None and (not isinstance(mc, (int, float))
                                   or not (0 <= mc <= 1)):
                errs.append("goal.escalation.minConfidence 须为 0..1")
            mtc = esc.get("maxTextChars")
            if mtc is not None and (not isinstance(mtc, int)
                                    or not (20 <= mtc <= 4000)):
                errs.append("goal.escalation.maxTextChars 须为 20..4000 整数")
    errs += _validate_strategies(goal.get("strategies"))
    errs += _validate_tool_classes(goal.get("toolClasses"))
    errs += _validate_help_topics(goal.get("helpTopics"))
    return errs


def _validate_help_topics(rows: Any) -> List[str]:
    """帮助主题校验(批戊补): key 唯一/title/kws 数组/body 非空/updated 日期串。"""
    if rows is None:
        return []
    if not isinstance(rows, list) or not rows:
        return ["goal.helpTopics 须为非空数组"]
    errs: List[str] = []
    seen = set()
    for i, t in enumerate(rows):
        if not isinstance(t, dict):
            errs.append(f"goal.helpTopics[{i}] 须为对象")
            continue
        errs += [f"goal.helpTopics[{i}] 未知键: {k}" for k in t
                 if k not in ("key", "title", "kws", "body", "updated")]
        key = str(t.get("key") or "")
        if not key:
            errs.append(f"goal.helpTopics[{i}].key 不能为空")
        elif key in seen:
            errs.append(f"goal.helpTopics[{i}].key 重复: {key}")
        seen.add(key)
        if not str(t.get("title") or "").strip():
            errs.append(f"goal.helpTopics[{i}].title 不能为空")
        kws = t.get("kws")
        if not isinstance(kws, list) or not kws \
                or any(not isinstance(x, str) or not x for x in kws):
            errs.append(f"goal.helpTopics[{i}].kws 须为非空字符串数组")
        if not str(t.get("body") or "").strip():
            errs.append(f"goal.helpTopics[{i}].body 不能为空")
    return errs


def _validate_tool_classes(tc: Any) -> List[str]:
    """GU 工具类校验(批丁): 键 ⊆ {read}, 值为非空字符串数组(fnmatch pattern)。"""
    if tc is None:
        return []
    if not isinstance(tc, dict):
        return ["goal.toolClasses 须为对象"]
    errs = [f"goal.toolClasses 未知键: {k}" for k in tc if k != "read"]
    pats = tc.get("read")
    if pats is not None and (not isinstance(pats, list)
                             or any(not isinstance(x, str) or not x.strip()
                                    for x in pats)):
        errs.append("goal.toolClasses.read 须为非空字符串数组")
    return errs


_STRATEGY_ELEMENTS = ("目标", "方案要点", "允许范围", "禁止改动", "验收标准")


def _validate_strategies(rows: Any) -> List[str]:
    """澄清策略条目校验(D5 配置化): key 唯一/kws 字符串数组/questions 二元组
    且要素词 ∈ D10 词表(冻结)。"""
    if rows is None:
        return []
    if not isinstance(rows, list) or not rows:
        return ["goal.strategies 须为非空数组"]
    errs: List[str] = []
    seen = set()
    for i, s in enumerate(rows):
        if not isinstance(s, dict):
            errs.append(f"goal.strategies[{i}] 须为对象")
            continue
        errs += [f"goal.strategies[{i}] 未知键: {k}" for k in s
                 if k not in ("key", "label", "kws", "questions")]
        key = str(s.get("key") or "")
        if not key:
            errs.append(f"goal.strategies[{i}].key 不能为空")
        elif key in seen:
            errs.append(f"goal.strategies[{i}].key 重复: {key}")
        seen.add(key)
        kws = s.get("kws")
        if not isinstance(kws, list) or not kws \
                or any(not isinstance(x, str) or not x for x in kws):
            errs.append(f"goal.strategies[{i}].kws 须为非空字符串数组")
        qs = s.get("questions")
        if not isinstance(qs, list) or not qs:
            errs.append(f"goal.strategies[{i}].questions 须为非空数组")
            continue
        for j, pair in enumerate(qs):
            if not isinstance(pair, (list, tuple)) or len(pair) != 2 \
                    or any(not isinstance(x, str) or not x for x in pair):
                errs.append(f"goal.strategies[{i}].questions[{j}] 须为 [要素, 问题] "
                            "二元字符串组")
            elif pair[0] not in _STRATEGY_ELEMENTS:
                errs.append(f"goal.strategies[{i}].questions[{j}] 要素非法: "
                            f"{pair[0]}(可用: {','.join(_STRATEGY_ELEMENTS)})")
    return errs


def _validate_num_obj(obj: Any, name: str, fields: tuple,
                      errs: List[str]) -> None:
    """小对象数值校验(就地追加 errs): fields=(key, lo, hi, is_int)。"""
    if obj is None:
        return
    if not isinstance(obj, dict):
        errs.append(f"{name} 须为对象")
        return
    errs += [f"{name} 未知键: {k}" for k in obj
             if k not in tuple(f[0] for f in fields)]
    for key, lo, hi, is_int in fields:
        v = obj.get(key)
        if v is None:
            continue
        if is_int and (not isinstance(v, int) or not (lo <= v <= hi)):
            errs.append(f"{name}.{key} 须为 {lo}..{hi} 整数")
        elif not is_int and (not isinstance(v, (int, float))
                             or not (lo <= v <= hi)):
            errs.append(f"{name}.{key} 须为 {lo}..{hi}")


def _validate_guards(phase: str, guards: Any) -> List[str]:
    errs: List[str] = []
    if not isinstance(guards, list):
        return [f"phases.{phase}.guards 须为数组"]
    for i, g in enumerate(guards):
        if not isinstance(g, dict):
            errs.append(f"phases.{phase}.guards[{i}] 须为对象")
            continue
        errs += [f"phases.{phase}.guards[{i}] 未知键: {k}"
                 for k in g if k not in ("intents", "regex", "reply")]
        intents = g.get("intents")
        if intents is not None:
            if not isinstance(intents, list):
                errs.append(f"phases.{phase}.guards[{i}].intents 须为数组")
            else:
                errs += [f"未知守卫意图名: {n}(可用: {','.join(INTENT_NAMES)})"
                         for n in intents if n not in _INTENT_MATCHERS]
        rx = g.get("regex")
        if rx is not None:
            try:
                re.compile(str(rx))
            except re.error as e:
                errs.append(f"phases.{phase}.guards[{i}].regex 编译失败: {e}")
        if not str(g.get("reply") or "").strip():
            errs.append(f"phases.{phase}.guards[{i}].reply 不能为空")
    return errs


def _validate_injections(inj: Any) -> List[str]:
    if inj is None:
        return []
    if not isinstance(inj, dict):
        return ["injections 须为对象"]
    errs: List[str] = []
    errs += [f"injections 未知键: {k}" for k in inj
             if k not in ("repairNotes", "overflowDigest", "assemblyBudget")]
    spec = (("repairNotes", {"enabled": bool, "maxPerTurn": (0, 10),
                             "keepLatest": (1, 50), "weakTierMax": (0, 3)}),
            ("overflowDigest", {"enabled": bool, "windowCap": (5, 200),
                                "overflowTrigger": (6, 500),
                                "maxChars": (200, 8000)}),
            ("assemblyBudget", {"baseChars": (500, 20000),
                                "floorChars": (50, 1000),
                                "coefMin": (0.05, 1.0), "coefMax": (1.0, 5.0)}))
    for key, fields in spec:
        cfg = inj.get(key)
        if cfg is None:
            continue
        if not isinstance(cfg, dict):
            errs.append(f"injections.{key} 须为对象")
            continue
        errs += [f"injections.{key} 未知键: {k}" for k in cfg
                 if k not in fields]
        for f, rule in fields.items():
            if f not in cfg:
                continue
            v = cfg[f]
            if rule is bool:
                if not isinstance(v, bool):
                    errs.append(f"injections.{key}.{f} 须为布尔")
                continue
            lo, hi = rule
            if not isinstance(v, (int, float)) or not (lo <= v <= hi):
                errs.append(f"injections.{key}.{f} 须为 {lo}..{hi}")
    od = inj.get("overflowDigest")
    if isinstance(od, dict) and isinstance(od.get("windowCap"), int) \
            and isinstance(od.get("overflowTrigger"), int) \
            and od["overflowTrigger"] <= od["windowCap"]:
        errs.append("overflowTrigger 须大于 windowCap")
    return errs


def deep_merge(base: dict, override: dict) -> dict:
    """深合并: 对象递归合并, 数组与标量整体替换。"""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _blank_getter(_key: str, default: str = "") -> str:
    return default


def load_flow_policy(getter: Optional[Callable[[str, Any], Any]] = None) -> dict:
    """读配置→深合并缺省→校验→坏值整体回落缺省(fail-soft)。

    getter 注入(overrides.py 同款零依赖); 缺省取 CollabConfigStore.get。
    每回合读(同 read_overrides 口径, 无缓存失效问题)。
    """
    if getter is None:
        try:
            from ...arch_routes.store import CollabConfigStore
            getter = CollabConfigStore.get
        except Exception:  # noqa: BLE001
            getter = _blank_getter
    try:
        raw = getter(POLICY_KEY, "") or ""
        data = json.loads(raw) if raw else {}
    except Exception as e:  # noqa: BLE001
        logger.debug("[flow-policy] 读取失败回落缺省: %s", e)
        return copy.deepcopy(DEFAULT_FLOW_POLICY)
    if not isinstance(data, dict) or not data:
        return copy.deepcopy(DEFAULT_FLOW_POLICY)
    merged = deep_merge(DEFAULT_FLOW_POLICY, data)
    ok, errs = validate_flow_policy(merged)
    if not ok:
        logger.warning("[flow-policy] 配置非法回落缺省: %s", "; ".join(errs[:5]))
        return copy.deepcopy(DEFAULT_FLOW_POLICY)
    return merged


# ── 生效表读取助手(合并表保证键齐全; .get 链仅为防御外部部分表) ────────

def phase_guards(pol: dict, phase: str) -> List[dict]:
    return list(((pol.get("phases") or {}).get(phase) or {}).get("guards") or [])


def guard_reply(g: dict, text: str) -> Optional[str]:
    """单条守卫匹配(纯确定性): 意图名查注册表 + 可选自定义正则;
    未知意图名/坏正则静默跳过——LLM 意图不入硬闸(防守线①)。"""
    t = str(text or "")
    for name in (g.get("intents") or []):
        pat = intent_pattern(name)
        if pat is not None and pat.search(t):
            return str(g.get("reply") or "")
    rx = g.get("regex")
    if rx:
        try:
            if re.compile(str(rx)).search(t):
                return str(g.get("reply") or "")
        except re.error:  # noqa: BLE001
            return None
    return None


def phase_note(pol: dict, phase: str) -> str:
    """相位对话面指引(note); ""=禁用, 缺省表无该相位=""。"""
    return str(((pol.get("phases") or {}).get(phase) or {}).get("note") or "")


def element_boost(pol: dict, phase: str) -> bool:
    """element_hints 上调驱动(缺省 clarifying=high; 单调只升不降在 P 轴侧保证)。"""
    return str(((pol.get("phases") or {}).get(phase) or {})
               .get("elementHints") or "") == "high"


def hint_text(pol: dict, key: str, n: int = 0) -> str:
    """hint 模板渲染({n} 占位); 坏模板/缺占位回落缺省文案(fail-soft)。"""
    tpl = str(((pol.get("hintTemplates") or {}).get(key))
              or DEFAULT_FLOW_POLICY["hintTemplates"].get(key) or "")
    default = str(DEFAULT_FLOW_POLICY["hintTemplates"].get(key) or "")
    try:
        return tpl.format(n=n) if tpl else ""
    except (KeyError, IndexError, ValueError):
        try:
            return default.format(n=n)
        except (KeyError, IndexError, ValueError):
            return ""
