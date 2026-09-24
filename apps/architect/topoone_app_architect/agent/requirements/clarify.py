"""需求澄清引擎(cv-190) — 策略库/缺口矩阵/显式指令判定, 全确定性规则。

裁决(2026-09-20):
- 澄清为会话**挡位按钮**: auto(自动, 有缺口才问) | forced(强制, 每需求回合先问);
- 策略库按**具体目标**切分(环境搭建/脚本工具/UI组件/缺陷修复/接口服务/重构优化/
  数据分析), 命中 → 用切合目标的标准化问题集; **未命中 → 模型自由提问**(五要素
  框架兜底, 不强行套库);
- **明确指令免澄清**(如「按钮UI 修改为 xxx」)——正则判定, 强制挡同样跳过;
- 全部规则零 LLM 依赖; 精度边界: 自动挡在需求卡未建时仍靠模型路由判断。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ── 策略库(按目标切分; kws 命中计分, questions 即该目标的澄清问题集) ──

# 融合形态: 动作+连接词一体(改为/改成/换成/设为…), 后接宾语
_EXPLICIT_FUSED_RE = re.compile(
    r"(修改为|更改为|改为|改成|换成|更新为|设置为|设为|换到|迁移到)[^。！？;；]{0,40}\S")
# 纯动作形态: 整句短指令(删除 X / 新增 X), 无疑问/开放式目标词
_EXPLICIT_ACTION_RE = re.compile(r"^(删除|移除|去掉|新增|添加|加上|更名|重命名)\s*\S.{0,27}$")
# 明确指令兜底形态: 「X 改为 Y」「删除 X」「新增 X」——动作 + 具体宾语, 无开放式目标词
_OPEN_GOAL_RE = re.compile(
    r"(搭建|开发|设计|实现|做一个|建一个|封装|规划|方案|怎么|如何|建议)")


def is_explicit_instruction(text: str) -> bool:
    """明确指令判定(确定性): 修改类动作 + 明确目标值(为/成 X) → True。

    例: 「按钮UI 修改为 xxx」✓ /「标题改成 XX」✓ /「删除导出按钮」✓;
    「搭建开发环境」✗(开放式目标词)。
    """
    t = (text or "").strip()
    if not t:
        return False
    if _OPEN_GOAL_RE.search(t):
        return False
    if _EXPLICIT_FUSED_RE.search(t):
        return True
    if len(t) <= 30 and _EXPLICIT_ACTION_RE.match(t):
        return True
    return False


def load_strategies() -> List[Dict[str, Any]]:
    """澄清策略库(D5 配置化偿还, 2026-09-22): 单源 = flow_policy.goal.strategies
    (代码缺省 + CollabConfigStore 配置深合并, 坏值回落缺省)。

    改一条澄清问题 = PUT /flow-policy, 零发版。引擎测试不依赖具体条目。"""
    try:
        from ... import store as _s
        from ..governance.flow_policy import load_flow_policy
        pol = load_flow_policy(_s.CollabConfigStore.get)
    except Exception:  # noqa: BLE001
        from ..governance.flow_policy import DEFAULT_FLOW_POLICY
        pol = DEFAULT_FLOW_POLICY
    rows = (pol.get("goal") or {}).get("strategies") or []
    return [dict(r) for r in rows
            if isinstance(r, dict) and str(r.get("key") or "")]


def match_strategy(text: str, strategies: Optional[List[Dict[str, Any]]] = None
                   ) -> Optional[Dict[str, Any]]:
    """按目标关键词命中策略(确定性计分: 命中词数最多且 ≥1)。未命中 → None。

    strategies 注入(测试/定制); 缺省读配置库。返回 dict 附带 score(命中词数):
    供 GU 边界裁决(单词撞车执行词表 → 操作类, 多词 topical 命中 → 需求类,
    goal-understanding-2609)。
    """
    t = (text or "").lower()
    best, best_score = None, 0
    for s in (strategies if strategies is not None else load_strategies()):
        kws = s.get("kws") or ()
        score = sum(1 for kw in kws if kw in t)
        if score > best_score:
            best, best_score = s, score
    if best is None:
        return None
    out = dict(best)
    out["score"] = best_score
    return out


def match_strategy_candidates(text: str, n: int = 2,
                              strategies: Optional[List[Dict[str, Any]]] = None
                              ) -> List[Dict[str, Any]]:
    """策略候选 top-n(确定性记分, 分数降序, score≥1)——供 GU 候选菜单。

    与 match_strategy 同源记分(逐词命中计数); 平分按库内原序(稳定排序,
    确定性)。返回 [{'key','label','questions','score'}, …]。"""
    t = (text or "").lower()
    rows = (strategies if strategies is not None else load_strategies())
    scored = []
    for s in rows:
        score = sum(1 for kw in (s.get("kws") or ()) if kw in t)
        if score > 0:
            entry = dict(s)
            entry["score"] = score
            scored.append(entry)
    scored.sort(key=lambda x: -int(x.get("score") or 0))
    return scored[:max(1, int(n))]


def gap_matrix(snapshot: Dict[str, Any]) -> List[str]:
    """要素缺口矩阵(确定性): 五要素缺失/单薄判定, 返回缺口要素名列表。

    判据: 验收标准空 / 方案要点(designMd) <30 字 / 允许范围空 /
    需求目标(functionalScope)空 / 需求目标正文(desc) <15 字。
    """
    a = snapshot or {}
    gaps: List[str] = []
    if not (a.get("desc") or "").strip() or len(str(a.get("desc") or "")) < 15:
        gaps.append("①目标(需求正文)")
    if len(str(a.get("designMd") or "")) < 30:
        gaps.append("②方案要点")
    if not (a.get("allowedScope") or []):
        gaps.append("③允许范围")
    if not (a.get("functionalScope") or []):
        gaps.append("④需求目标清单")
    if not (a.get("acceptance") or []):
        gaps.append("⑤验收标准")
    return gaps


def clarify_directive(mode: str, question: str,
                      req_snapshot: Optional[Dict[str, Any]] = None) -> str:
    """会话内澄清指令段(系统消息; 空串=本回合不注入)。

    GU 归位后的职责(2026-09-22, goal-understanding-2609): 本函数只保留
    「已建需求」的缺口驱动面(auto/forced 同款, 答复→amend 回填→缺口缩→收敛)。
    **立卡前的目标理解与澄清前置已归 GU 决策表**(turns/goal clarify-first,
    clarifyMode 感知)——原 forced 无需求分支的死路由此解锁并退役。
    - 明确指令(任意挡) → ""(免澄清);
    - 已建需求: 缺口矩阵驱动集中提问。
    """
    from ..compensation.providers import builtin as _bt
    if is_explicit_instruction(question):
        return ""
    if req_snapshot:
        gaps = gap_matrix(req_snapshot)
        if gaps:
            tag = "强制挡" if mode == "forced" else "自动"
            return _bt.clarify_gap_text(tag, "、".join(gaps))
    return ""
