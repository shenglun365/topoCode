"""受限 LLM 意图分类(GU-L2) + 误路由遥测(#5, goal-understanding-2609)。

GU-5 归位(2026-09-22): 本模块收敛为 GU 的 L2 理解器——turns/goal.build_goal_profile
在 escalation.llmFallback(缺省关)开启且 L0 无信号时调用 classify_intent 尝试升格;
原 intent_hint 软提示路径由 GU 决策表回合指引取代(propose-task 指引)。

形态约束:
- 先遥测后兜底: intent_misroute 事件恒开(只观测, D6 同款); L2 由
  policy.goal.escalation.llmFallback 控制**缺省关闭**(原 overrides 键
  intent_llm_fallback 已被取代, 不再读取)。
- LLM 意图只建议: 分类结果仅参与 GoalProfile 升格 → 回合指引仍走决策表;
  绝不直接触发不可逆动作(cv-152 防线); 相位硬闸只消费确定性匹配器(防守线①)。
- 受限触发与缓存: 文本指纹缓存(负结果同缓存); 分类失败返回 None(fail-soft)。
- LLM 通道经 turns.catalog(light:intent; Purpose 复用 PROBE——D10 词表冻结),
  D12 门禁合规。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

_CLASSIFY_SYSTEM = (
    "你是意图分类器。判断用户消息是否为「通用执行意图」——检测/统计/编译/构建/"
    "运行/安装/部署/写脚本/批量处理等不需要项目知识库即可动手的任务。"
    "输出 JSON: {\"intent\": \"generic_exec|kb_analysis|other\", "
    "\"confidence\": 0~1}。只输出 JSON, 不要解释。")

_INTENTS = ("generic_exec", "kb_analysis", "other")

# 进程内有界缓存(文本指纹 → 分类结果; 负结果同样缓存防重复调用)
_CACHE: Dict[str, Tuple[int, bool, Optional[dict]]] = {}
_CACHE_MAX = 128


def misroute_telemetry(question: str, reply: str) -> None:
    """误路由遥测(#5 先行半, 恒开): 回复推诿 ∧ 问题正则未命中 → 记样本。

    只观测不改行为; 数据供「何时启用 L2」的决策。永不抛出。"""
    try:
        from ..perception.intent import DEFLECT_RE, GENERIC_EXEC_RE
        from ..reflection import dataset as _ds
        q, r = str(question or ""), str(reply or "")
        if not q or not r or GENERIC_EXEC_RE.search(q) \
                or not DEFLECT_RE.search(r):
            return
        _ds.record("intent_misroute", matched=False, question=q[:120],
                   replySample=r[:120])
    except Exception:  # noqa: BLE001 — 遥测不碍主链
        pass


def classify_intent(question: str, context: str = "") -> Optional[Dict[str, Any]]:
    """一次受限 LLM 意图分类(GU-L2 理解器): 结构化输出 + 确定性校验 + 缓存。

    context=近期对话摘要(GU 装配, 有界截断; 拼入请求辅助歧义消解,
    并入缓存键——不同上下文可得出不同分类)。
    返回 {intent, confidence}(ok)或 None(失败/未产出); 负结果同样缓存。
    调用方(GU)负责开关与置信门槛——本函数只做分类。"""
    q = str(question or "").strip()
    if not q:
        return None
    import hashlib as _h
    ctx = str(context or "")[:400]
    key = _h.sha1(f"{q}\n{ctx[:200]}".encode("utf-8")).hexdigest()[:16]
    found, payload = _cache_get(key)
    if not found:
        payload = _classify(q, ctx)
        _cache_put(key, payload)
    return payload


def _cache_get(key: str) -> Tuple[bool, Optional[dict]]:
    ent = _CACHE.get(key)
    if ent is None:
        return False, None
    return True, ent[2]


def _cache_put(key: str, payload: Optional[dict]) -> None:
    import time
    if len(_CACHE) >= _CACHE_MAX:
        oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
        _CACHE.pop(oldest, None)
    _CACHE[key] = (int(time.time()), payload is not None, payload)


def _classify(q: str, context: str = "") -> Optional[dict]:
    """一次隔离分类调用(轻任务 intent; 结构化输出; 确定性校验; 无兜底产出)。"""
    from ..reflection import dataset as _ds
    from .catalog import catalog_call
    user = q if not context else f"{q}\n\n[近期对话]\n{context}"
    schema = {"type": "object",
              "properties": {"intent": {"type": "string", "enum": list(_INTENTS)},
                             "confidence": {"type": "number"}},
              "required": ["intent"]}

    def _valid(p: Any) -> Tuple[bool, str]:
        if not isinstance(p, dict) or str(p.get("intent") or "") not in _INTENTS:
            return False, "intent 非法"
        c = p.get("confidence")
        if isinstance(c, bool) or not isinstance(c, (int, float)) \
                or not (0 <= float(c) <= 1):
            return False, "confidence 非法"
        return True, ""

    res = catalog_call("light:intent",
                       [{"role": "system", "content": _CLASSIFY_SYSTEM},
                        {"role": "user", "content": user}],
                       schema=schema, max_tokens=100, validate=_valid,
                       fallback=lambda: None)
    out = res.get("output") if isinstance(res.get("output"), dict) else {}
    try:
        _ds.record("intent_llm", ok=bool(res.get("ok")),
                   intent=str(out.get("intent") or ""),
                   confidence=float(out.get("confidence") or 0),
                   contextChars=len(context or ""))
    except Exception:  # noqa: BLE001
        pass
    return out if res.get("ok") else None
