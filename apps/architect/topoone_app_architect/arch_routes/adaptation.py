"""适配管道 (Adaptation Pipeline) — repair_loop 统一执行器 + 策略矩阵。

收编既有散点修复外循环(guard-repair/arg-repair/spec-format), 统一六要素:
  隔离上下文构造 / 单次小 max_tokens 调用 / 确定性校验链 / 产物执行 /
  失败降级 / llm_dataset 观测; 新增回灌锚定(修复产物以系统回执消息注入
  主会话, 根治「外循环成功但主上下文仍残留幻觉内容」的后续漂移)。

策略矩阵: tier → 启用策略集(真相源)。P1 挂矩阵与查询接口, 策略消费者
(草稿卡收敛/意图追问分级/宽容解析分级)在 P2/P3 渐进接线。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import model_profile, store

logger = logging.getLogger("arch.adaptation")


# ── 策略矩阵(真相源) ──────────────────────────────────────────────────

_DEFAULT_STRATEGIES: Dict[str, Any] = {
    "arg_coerce": True,            # 参数类型强转(所有档开启)
    "arg_repair": True,            # LLM 参数修复外循环
    "guard": True,                 # 防编造守卫
    "guard_extract_first": True,   # guard 修复确定性提取前置
    "intent_followup": False,      # 意图追问(小模型开)
    "draft_card": False,           # 草稿卡确定性收敛【A】(t2+ 开)
    "postprocess": False,          # 输出后处理: 编号回填/重复声明去噪(t3+)
    "single_focus": False,         # 极简 system/单轮单任务(t4)
    "lenient_parse": "base",       # 工具块宽容解析级别 base|high|max
}

STRATEGY_MATRIX: Dict[int, Dict[str, Any]] = {
    0: {**_DEFAULT_STRATEGIES},
    1: {**_DEFAULT_STRATEGIES},
    2: {**_DEFAULT_STRATEGIES, "intent_followup": True, "draft_card": True,
        "lenient_parse": "high"},
    3: {**_DEFAULT_STRATEGIES, "intent_followup": True, "draft_card": True,
        "postprocess": True, "lenient_parse": "high"},
    4: {**_DEFAULT_STRATEGIES, "intent_followup": True, "draft_card": True,
        "postprocess": True, "single_focus": True, "lenient_parse": "max"},
}


def strategies_for_tier(tier: int) -> Dict[str, Any]:
    return STRATEGY_MATRIX.get(max(0, min(4, int(tier)))) or dict(_DEFAULT_STRATEGIES)


def strategies_for_model(model_id: str) -> Dict[str, Any]:
    return strategies_for_tier(model_profile.tier_of(model_id or ""))


# ── repair_loop 统一执行器 ────────────────────────────────────────────

@dataclass
class RepairTask:
    """一次隔离修复任务(外循环)。

    parse: 产物解析(返回 None=无效, 触发降级)
    execute: 产物执行(返回 dict, 需含 ok 字段); None=仅解析(spec_format 场景)
    anchor_conv: 回灌锚定会话 id(空=不锚定)——成功后向该会话追加系统回执消息,
      主上下文获得真实事实锚点, 防后续回合继续复述幻觉内容。
    dataset_kind: llm_dataset 事件类型(空=记 repair_loop 通用事件)
    """
    task_id: str
    system: str
    user: str
    parse: Callable[[str], Any]
    execute: Optional[Callable[[Any], Dict[str, Any]]] = None
    max_tokens: int = 900
    model_id: str = ""
    anchor_conv: str = ""
    anchor_text: str = ""          # 锚定文案(缺省用执行结果 summary)
    dataset_kind: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


def anchor_back(conv_id: str, text: str, kind: str = "system_receipt") -> bool:
    """回灌锚定: 向会话追加系统回执消息(不进 LLM 上下文, 前端渲染为回执卡)。

    主会话历史中模型可能残留幻觉声明(如编造的 RQ 编号), 外循环真实落库后
    以系统回执落库——下轮模型上下文含真实编号, 后续引用自然锚定。
    """
    if not (conv_id and text):
        return False
    try:
        store.ConversationsStore.append_message({
            "id": store.next_id("sr"), "conversationId": conv_id,
            "role": "assistant", "time": int(time.time() * 1000),
            "content": text, "meta": json_dumps({"kind": kind}),
        })
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[repair-loop] 锚定失败 conv=%s: %s", conv_id, e)
        return False


def json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def run_repair_loop(task: RepairTask) -> Dict[str, Any]:
    """执行一次修复外循环: 隔离调用 → 解析 → 校验执行 → 观测 → 锚定。

    返回 {ok, action, summary, parsed?, result?}; 失败 action=failed,
    调用方回落既有路径(绝不抛出)。
    """
    from . import llm_dataset
    from .req_agent import llm_sync, _now_ms
    t0 = _now_ms()
    ok = False
    action = "failed"
    summary = ""
    parsed: Any = None
    result: Optional[Dict[str, Any]] = None
    try:
        res = llm_sync([{"role": "system", "content": task.system},
                        {"role": "user", "content": task.user}],
                       mode="chat", model_id=task.model_id or None,
                       max_tokens=task.max_tokens)
        raw = (res or {}).get("content") or ""
        parsed = task.parse(raw) if raw else None
        if parsed is not None:
            if task.execute is not None:
                result = task.execute(parsed) or {}
                ok = bool(result.get("ok"))
                action = str(result.get("action") or ("ok" if ok else "failed"))
                summary = str(result.get("summary") or "")
            else:
                ok = True
                action = "parsed"
                result = {"ok": True, "parsed": parsed}
        else:
            summary = "修复器未产出可解析产物"
    except Exception as e:  # noqa: BLE001
        summary = f"修复外循环异常: {e}"
        logger.warning("[repair-loop] %s 异常: %s", task.task_id, e)
    latency = _now_ms() - t0
    out = {"ok": ok, "action": action, "summary": summary, "latencyMs": latency}
    if parsed is not None:
        out["parsed"] = parsed
    if result is not None:
        out["result"] = result
    try:
        llm_dataset.record(task.dataset_kind or "repair_loop", task=task.task_id,
                           ok=ok, model=task.model_id or "",
                           latencyMs=latency, summary=summary[:200],
                           **({"parsedOut": parsed} if parsed is not None else {}),
                           **(task.meta or {}))
    except Exception:  # noqa: BLE001
        pass
    # 回灌锚定: 成功(或已有 summary 文案)时向主会话落系统回执
    if task.anchor_conv:
        text = task.anchor_text or (summary if ok else "")
        if text:
            anchor_back(task.anchor_conv, text)
    return out
