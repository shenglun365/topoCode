"""确定性 LLM 外循环(反思层) — RepairTask/run_repair_loop + summarize_task。

cv-175 裁决: 参数自动修复/守卫修复外循环(anchor_back/repair_tool_args/
repair_fabricated_claim)已拆除——错误明确返回, 不静默纠偏。
LLM 通道经 req_agent 属性调用时解析——保留测试 monkeypatch 接缝(req_agent.llm_sync)。
"""
from __future__ import annotations

import inspect
import json
import logging
import re
import time
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from ..cognition.llm import ModelNotConfigured

from ..reflection import dataset as llm_dataset

logger = logging.getLogger("arch.reflection.repair")


def _store():
    from ... import store
    return store


def _now() -> int:
    return int(time.time() * 1000)


def _ra():
    from ...agent.tools import req_agent
    return req_agent




_REPAIRABLE_ERR = re.compile(
    r"TypeError|KeyError|AttributeError|unhashable|unhashable type|"
    r"missing \d+ required (positional )?argument|unexpected keyword|"
    r"invalid literal for int|执行失败|缺少|无效|无法解析", re.I)


@dataclass
class RepairTask:
    """一次隔离修复任务(外循环)。

    parse: 产物解析(返回 None=无效, 触发降级)
    execute: 产物执行(返回 dict, 需含 ok 字段); None=仅解析(spec_format 场景)
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


def json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


# ── summarize_task 摘要/中继/提取统一原语 ─────────────────────────────

def summarize_task(*, task_id: str, system: str, material: str,
                   max_tokens: int, model_id: str = "",
                   mode: str = "chat",
                   output_schema: Optional[Dict[str, Any]] = None,
                   parse: Optional[Callable[[Dict[str, Any]], Any]] = None,
                   fallback: Optional[Callable[[], Any]] = None,
                   dataset_kind: str = "summarize_task") -> Dict[str, Any]:
    """摘要/中继/提取类统一原语(P2 收编 5 处同型异构实现):
    材料 → 一次隔离 LLM(单 system+材料, 不带对话历史) → 解析校验 → 失败确定性降级。

    parse: 原始 res → 产物(返回 None 视为失败); 缺省 = content 文本。
    fallback: 失败时零 LLM 降级产物(不提供则 ok=False, 调用方自行处理)。
    统一口径: 材料截断由调用方完成 / 降级永不抛出 / llm_dataset 观测。
    返回 {ok, output, degraded}。
    """
    t0 = _now()
    out: Any = None
    ok = False
    degraded = False
    try:
        res = _ra().llm_sync([{"role": "system", "content": system},
                        {"role": "user", "content": material}],
                       mode=mode, output_schema=output_schema,
                       max_tokens=max_tokens, model_id=model_id or None)
        if parse is not None:
            out = parse(res or {}) if res else None
        else:
            out = str(((res or {}).get("content") or "")).strip() or None
        ok = out is not None
    except ModelNotConfigured:
        raise   # 模型未配置 → 明确报错(用户裁决: 禁止降级出垃圾产物)
    except Exception as e:  # noqa: BLE001
        logger.warning("[summarize-task] %s 异常: %s", task_id, e)
    if not ok and fallback is not None:
        try:
            out = fallback()
            ok = out is not None
            degraded = True
        except Exception as e:  # noqa: BLE001
            logger.warning("[summarize-task] %s 降级失败: %s", task_id, e)
    try:
        from . import dataset as llm_dataset
        llm_dataset.record(dataset_kind, task=task_id, ok=ok, degraded=degraded,
                           model=model_id or "", latencyMs=_now() - t0)
    except Exception:  # noqa: BLE001
        _swallow("repair.telemetry")
    return {"ok": ok, "output": out, "degraded": degraded}


def run_repair_loop(task: RepairTask) -> Dict[str, Any]:
    """执行一次修复外循环: 隔离调用 → 解析 → 校验执行 → 观测 → 锚定。

    返回 {ok, action, summary, parsed?, result?}; 失败 action=failed,
    调用方回落既有路径(绝不抛出)。
    """
    from . import dataset as llm_dataset
    t0 = _now()
    ok = False
    action = "failed"
    summary = ""
    parsed: Any = None
    result: Optional[Dict[str, Any]] = None
    try:
        res = _ra().llm_sync([{"role": "system", "content": task.system},
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
    latency = _now() - t0
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
        _swallow("repair.dataset_record")
    _persist_repair_note(task, out)
    return out


def _swallow(tag: str) -> None:
    """S2 吞错计数(装配路径静默降级可观测; 开关 swallow_counters)。"""
    try:
        llm_dataset.swallow(tag)
    except Exception:  # noqa: BLE001
        pass


def _persist_repair_note(task: "RepairTask", out: Dict[str, Any]) -> None:
    """S1 修复经验回填(采纳文档 2609): 成功修复 → repair_note 上下文单元。

    按错误签名去重(同签名 → 原位 update 计数+重要度, 不增行); 超 keepLatest
    修剪最旧。锚定会话: task.anchor_conv 优先, 缺省取 ctx 当前会话。
    注入侧(turns/context 装配)按 flow_policy.injections.repairNotes 消费。
    开关: agent.comp.overrides.repair_note_injection(缺省启用)。
    全程 fail-soft: 回填故障不阻塞修复主链。
    """
    try:
        from ..compensation.overrides import override_enabled, read_overrides
        from ..governance.flow_policy import load_flow_policy
        from ... import store
        _get = store.CollabConfigStore.get
        if not override_enabled(read_overrides(_get), "repair_note_injection"):
            return
        pol = load_flow_policy(_get)
        cfg = (pol.get("injections") or {}).get("repairNotes") or {}
        if cfg.get("enabled", True) is False:
            return
        conv_id = str(task.anchor_conv or "")
        if not conv_id:
            try:
                from ... import ctx as _ctx
                conv_id = str(_ctx.get_conv() or "")
            except Exception:  # noqa: BLE001
                conv_id = ""
        if not (out.get("ok") and conv_id):
            return
        content = str(task.anchor_text or out.get("summary") or "").strip()
        if not content:
            return
        conv = store.ConversationsStore.get(conv_id) or {}
        sig = __import__("hashlib").sha1(
            f"{task.task_id}|{task.user}".encode("utf-8")).hexdigest()[:12]
        units = store.ContextUnitsStore.all(
            conversation_id=conv_id, type_="repair_note", limit=100)
        dup = next((u for u in units
                    if (u.get("refs") or {}).get("sig") == sig), None)
        if dup is not None:
            refs = dict(dup.get("refs") or {})
            refs["count"] = int(refs.get("count") or 1) + 1
            refs["lastAt"] = _now()
            store.ContextUnitsStore.update(dup["id"], {
                "content": content[:500],
                "importance": min(3, int(dup.get("importance") or 1) + 1),
                "refs": refs})
            return
        store.ContextUnitsStore.create({
            "conversationId": conv_id,
            "projectId": str(conv.get("projectId") or ""),
            "type": "repair_note",
            "title": f"修复经验: {task.task_id}",
            "content": content[:500],
            "refs": {"sig": sig, "tool": task.task_id, "ok": True, "count": 1},
            "importance": 1})
        keep = int(cfg.get("keepLatest") or 5)
        if len(units) + 1 > keep:
            for u in sorted(units, key=lambda x: int(x.get("createdAt") or 0))[
                    :len(units) + 1 - keep]:
                store.ContextUnitsStore.delete(u["id"])
    except Exception:  # noqa: BLE001 — 回填失败不阻塞修复主链
        _swallow("repair.note_persist")
