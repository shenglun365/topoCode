"""守卫组件(反思层) — 防编造/守卫文案/意图空承诺检测。

P5 自 req_agent.py 机械迁入(逐字节保真)。消费方: orchestrator 回合末反思管道、
guard-repair REST、MCP 面。策略开关(guard/intent_followup)由 cognition.strategy
策略矩阵驱动(orchestrator 接线)。
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Optional

logger = logging.getLogger("arch.reflection.guards")


def _store():
    from ...arch_routes import store
    return store


# ── 防编造守卫: 声称的落库/执行动作必须有本回合真实工具调用佐证 ──────────

_FABRIC_RULES = [
    # (完成语正则, 佐证工具集, 描述)。提案类规则遇「提及已存在的 RQ 编号」视为
    # 历史回顾不触发(真实回顾必然引用既有编号)；自造编号由下方 ID 存在性检查兜住。
    (re.compile(r"(已生成|已创建|已产出|已形成|已落库|已保存)[^。\n]{0,24}提案|提案已(生成|创建|落库|保存)"),
     ("req.propose",), "已生成/落库需求提案"),
    (re.compile(r"已定稿|定稿成功|已转入待执行|已存入待执行|已固化[^。\n]{0,10}待执行"),
     ("req.finalize",), "定稿入池(转入待执行)"),
    # v2 任务域(cv-150 实证): 声称任务已创建/开始执行、输出假执行进度报告
    (re.compile(r"(已创建|已生成|已发起|已启动)[^。\n]{0,16}(实施)?任务(卡)?|任务(卡)?已(正式)?(创建|生成|发起|启动|开始执行)"),
     ("task.propose",), "已创建/启动任务"),
    (re.compile(r"执行进度报告|Phase\s*1\s*[:：]|正在检查当前项目.+构建环境与"),
     ("task.propose",), "编造任务执行进度"),
]


def fabricated_claim(text: str, tools_used) -> tuple:
    """判定文本是否编造了未执行的动作。

    返回 (动作描述, 佐证工具名串) 或 (None, None)。
    - 动作完成语 + 佐证工具不在本回合调用集合 → 编造(提案类带既有 RQ 编号=回顾, 放行)
    - 引用的 RQ- 编号在需求库不存在 → 编造(自造编号, 如 RQ-WS-REDIS-001)
    """
    if not text:
        return None, None
    used = tools_used or set()
    mentioned = set(re.findall(r"\bRQ-[A-Za-z0-9][A-Za-z0-9_-]*", text))
    existing = {rid for rid in mentioned if _store().RequirementsStore.get(rid)}
    for rx, tools, label in _FABRIC_RULES:
        if not rx.search(text) or any(t in used for t in tools):
            continue
        if "提案" in label and (mentioned & existing):
            continue  # 引用既有提案编号 → 历史回顾而非本轮产出声称
        return label, "|".join(tools)
    for rid in mentioned - existing:
        return f"引用不存在的需求编号 {rid}", "req.propose"
    return None, None


def guard_notice(claim: str, need: str, tools_used=None,
                 tool_errors: Optional[Dict[str, str]] = None) -> str:
    """守卫通知文案(纯函数，供 WS 层与单测共用)。

    - 所需工具已真实调用但执行失败 → 「执行失败(非编造)」+ 失败摘要：
      模型可能没错(参数形状/存储故障)，编造指控会误导用户与模型
    - 未调用 → 原编造文案
    """
    primary = (need or "").split("|")[0]
    errs = tool_errors or {}
    if primary and primary in set(tools_used or ()) and errs.get(primary):
        return (f"\n\n> ⚠️ 系统守卫：「{claim}」的动作已尝试执行但失败——非编造。"
                f"失败原因：{errs[primary][:180]} 请修正参数后重试，"
                "或改用界面操作（方案生成按钮）。")
    return (f"\n\n> ⚠️ 系统守卫：上述回复中「{claim}」的表述未经实际工具调用，"
            "不成立。请重试，或改用界面操作（方案生成按钮/任务执行页）。")


def guard_suggestions(claim: str, need: str, tool_failed: bool = False,
                      has_spec_json: bool = False) -> list:
    """守卫卡片可点击指令(suggestions)——简洁 label, action 供 guard-repair 路由。

    冗长说明由前端非点击文字区承载; 这里只产 指令集。
    has_spec_json: 消息含规约形状 JSON → 「按原文落库」排最前(确定性路径优先)。
    """
    sugs = []
    if has_spec_json:
        sugs.append({"action": "apply_json", "label": "按原文落库"})
    tools = (need or "").split("|")
    if "req.amend" in tools:
        sugs.append({"action": "repair_amend", "label": "修正落库"})
    if "req.finalize" in tools and "req.amend" not in tools:
        sugs.append({"action": "repair_finalize", "label": "确认定稿"})
    if "req.propose" in tools:
        sugs.append({"action": "repair_propose", "label": "创建提案"})
    # T6: repair_task(创建任务卡)已撤——任务域自动建卡会产出幽灵卡(cv-153),
    # 守卫触发后引导重新整理 + /执行 直通链。
    if tool_failed:
        sugs.append({"action": "repair_retry", "label": "修正参数重试"})
    if not sugs:
        sugs.append({"action": "repair_amend", "label": "修正落库"})
    sugs.append({"action": "correct", "label": "更正声明"})
    return sugs


_INTENT_PATTERNS = [
    re.compile(r"请等待我完成"),
    re.compile(r"我将(立即)?(执行|检索|调用|读取|开始|编写|创建)"),
    re.compile(r"(我|让我)先(检索|查看|读取|调用|确认)"),
    re.compile(r"即将(调用|执行|检索)"),
    re.compile(r"正在(调用|执行|检索)以下工具"),
    # 提案/落库完成语宣布(cv-88~102 实证主病灶): 宣称已创建而未调工具 →
    # 追问轮逼出真实 [TOOL_CALL](先于防编造守卫, 成功则无需卡片)
    re.compile(r"已(创建|生成|落库|提交|新建)(需求)?(提案|规约|需求)"),
    re.compile(r"需求(提案)?(已经)?(创建|生成|落库)(完成|成功)"),
]


def announced_tool_intent(text: str) -> str:
    """检测『宣布要调工具却没有 [TOOL_CALL] 就结束回合』的空承诺文本。

    命中返回意图短语(供守卫纠正提示引用)，否则 None。供 WS 层在
    本回合零工具调用时判定是否追问一轮。
    """
    if not text:
        return ""
    for rx in _INTENT_PATTERNS:
        m = rx.search(text)
        if m:
            return m.group(0)
    return ""
