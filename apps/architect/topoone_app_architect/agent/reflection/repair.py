"""修复外循环(反思层) — 参数修复/守卫修复/repair_loop 统一执行器。

P5 机械迁入: req_agent(_REPAIRABLE_ERR/_is_repairable_error/_repair_param_table/
repair_tool_args/repair_fabricated_claim) + adaptation(RepairTask/anchor_back/
summarize_task/run_repair_loop)。LLM 通道经 req_agent 属性调用时解析——
保留测试 monkeypatch 接缝(req_agent.llm_sync)。
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

from ..reflection import dataset as llm_dataset

logger = logging.getLogger("arch.reflection.repair")


def _store():
    from ...arch_routes import store
    return store


def _now() -> int:
    return int(time.time() * 1000)


def _ra():
    from ...arch_routes import req_agent
    return req_agent


_GUARD_REPAIR_TOOLS = ("req.amend", "req.finalize", "req.propose")


def repair_fabricated_claim(claim: str, need: str, content: str, *,
                            req_id: str = "", project: str = "",
                            root: str = "", model_id: Optional[str] = None,
                            tool_error: str = "") -> Dict[str, Any]:
    """守卫独立外循环修复器(不经对话流): 从编造文本提取真实落库意图并执行。

    与全量补救轮(_sync_with_tools)的区别: 极简上下文(守卫判定+编造文本+
    佐证工具签名表+会话绑定 reqId)单独请求一次 LLM, 只产 [TOOL_CALL] JSON
    或更正声明; 工具执行由本函数确定性完成(run_arch_tool), 杜绝补救轮再编造。

    返回 {action: amended|finalized|proposed|corrected|failed, summary,
          toolResult?, correction?}

    前置确定性提取: content 含规约形状 JSON → 直接 apply_spec_payload 落库
    (三级降级内建), 不经 LLM; 提取失败才走下方 LLM 外循环。
    """
    payload = _ra().extract_spec_payload(content or "")
    if payload:
        r = _ra().apply_spec_payload(payload, req_id=req_id, project=project, root=root)
        if r.get("ok"):
            r.setdefault("summary", "")
            return r
        # 确定性提取失败(含 L2 修复后仍失败) → 记录后回落 LLM 外循环
    sys_prompt = (
        "你是需求落库修复器。用户看到的助手回复声称了未实际执行的动作(守卫拦截)，"
        "但回复里可能包含可用于真实落库的完整规约内容(常见为 ```json 围栏载荷)。\n"
        "任务二选一：\n"
        "① 载荷信息足以落库 → 输出一个工具调用块：\n"
        '   [TOOL_CALL]{"tool":"<工具名>","arguments":{…}}[/TOOL_CALL]\n'
        "   可用工具与签名：\n"
        + "".join(f"  - {n}: {_repair_param_table(_ra()._ARCH_TOOLS[n]['handler'])}\n"
                  for n in _GUARD_REPAIR_TOOLS if n in _ra()._ARCH_TOOLS)
        + ("   会话绑定需求(优先使用该 reqId): " + (req_id or "(无)") + "\n")
        + (f"   上次执行失败原因(修正参数规避): {tool_error[:300]}\n" if tool_error else "")
        + "② 载荷不可信/关键信息缺失 → 输出一行以【更正】开头的声明文本，"
        "说明该动作尚未发生(不编造任何编号/状态)。\n"
        "只输出 ①或② 之一，不要输出其它内容。")
    user_content = (f"守卫判定: {claim}（需要佐证工具: {need}）\n\n"
                    f"助手原文:\n{content[:6000]}")

    def _parse(raw: str):
        """产物结构统一: {calls: [...], correction: ""}；raw 空才无效。"""
        if not (raw or "").strip():
            return None
        corr = ""
        m = re.search(r"【更正】\s*(.+)", raw, re.DOTALL)
        if m:
            corr = m.group(1).strip()[:600]
        return {"calls": _ra().extract_tool_calls(raw) or [], "correction": corr}

    def _execute(parsed: Dict[str, Any]) -> Dict[str, Any]:
        for c in parsed.get("calls") or []:
            name, args = c.get("tool"), c.get("arguments")
            if name not in _GUARD_REPAIR_TOOLS or not isinstance(args, dict):
                continue
            # 确定性校验: reqId 必须真实存在(防修复器再次编造编号)
            rid = str(args.get("reqId") or "").strip()
            if rid and not _store().RequirementsStore.get(rid):
                continue
            if not rid and req_id:
                args["reqId"] = req_id          # 缺省绑定会话需求
            if name == "req.propose" and not args.get("newRequirement") and req_id:
                args["reqId"] = args.get("reqId") or req_id
            result = run_arch_tool(name, args, root=root, project=project)
            ok = not (isinstance(result, dict) and result.get("error"))
            if ok:
                rid_out = (result or {}).get("reqId") or (result or {}).get("requirementId") or req_id
                ver = (result or {}).get("ver") or ""
                action = {"req.amend": "amended", "req.finalize": "finalized",
                          "req.propose": "proposed"}.get(name, name)
                summary = (f"✅ 守卫修复完成：`{rid_out}`"
                           + (f" v{ver}" if ver else "")
                           + f"（{name} 真实落库）")
                return {"ok": True, "action": action, "summary": summary,
                        "toolResult": result}
            return {"ok": False, "action": "failed",
                    "summary": f"修复执行失败({name})：{str((result or {}).get('error'))[:200]}",
                    "toolResult": result}
        # ② 更正声明分支——复查只查自造编号(否定语境的声明天然含「已定稿」等字样,
        #    套用完成语规则会自查自纠死锁); 编号真实性仍必须保证
        text = str(parsed.get("correction") or "")
        if text:
            mentioned = set(re.findall(r"\bRQ-[A-Za-z0-9][A-Za-z0-9_-]*", text))
            fake_ids = [r for r in mentioned if not _store().RequirementsStore.get(r)]
            if not fake_ids:
                return {"ok": True, "action": "corrected", "summary": text,
                        "correction": text}
        return {"ok": False, "action": "failed",
                "summary": "修复器未能产出有效工具调用或更正声明"}

    out = run_repair_loop(RepairTask(
        task_id="guard_repair", system=sys_prompt, user=user_content,
        parse=_parse, execute=_execute, max_tokens=900,
        model_id=model_id or "", dataset_kind="guard_repair",
        meta={"claim": str(claim)[:200], "need": str(need)[:80]}))
    res2 = out.get("result") or {}
    res2.pop("ok", None)
    return res2 if res2.get("action") else {"action": "failed",
                                            "summary": out.get("summary") or "修复外循环失败"}


# ── 聚焦修复外循环(小模型参数形状不稳的 LLM 兜底) ────────────────────
# _coerce_args 是确定性第一层; 本层处理 coerce 救不了的形状/结构错误
# (缺必填参数/发明字段名/嵌套错位)。与主对话完全隔离的极简上下文单独
# 请求一次(带工具签名+错误+原始args)，产出修正 JSON 后重执行一次。
# 每次触发即一条微调样本(llm_dataset.arg_repair: 错误args→正确args)。

_REPAIRABLE_ERR = re.compile(
    r"TypeError|KeyError|AttributeError|unhashable|unhashable type|"
    r"missing \d+ required (positional )?argument|unexpected keyword|"
    r"invalid literal for int|执行失败|缺少|无效|无法解析", re.I)


def _is_repairable_error(err: str) -> bool:
    """格式/参数类错误才触发外循环；业务/策略错误(需求不存在、白名单拒绝等)不修。"""
    if not err:
        return False
    if "不存在" in err or "已归档" in err or "不在本任务允许列表" in err or "未知工具" in err:
        return False
    return bool(_REPAIRABLE_ERR.search(err))


def _repair_param_table(fn: Callable) -> str:
    """handler 签名 → 参数表文本(名: 类型)，供修复请求的极简 schema 说明。"""
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001
        hints = {}

    def _hint_name(h) -> str:
        h = _ra()._unwrap_hint(h) if h is not None else None
        if h is None:
            return "any"
        origin = typing.get_origin(h)
        if origin is None:
            return getattr(h, "__name__", str(h))
        args = typing.get_args(h)
        inner = ",".join(getattr(a, "__name__", str(a)) for a in args[:2])
        return f"{getattr(origin, '__name__', str(origin))}[{inner}]"

    names = [p for p in inspect.signature(fn).parameters if p not in ("root", "project")]
    return ", ".join(f"{p}: {_hint_name(hints.get(p))}" for p in names) or "(无参数)"


def repair_tool_args(name: str, args: Dict[str, Any], error: str, *,
                     model_id: Optional[str] = None,
                     context_hint: str = "") -> Optional[Dict[str, Any]]:
    """聚焦修复外循环(经 adaptation.repair_loop 统一执行)：极简上下文单独请求
    一次 LLM，仅修复 arguments JSON。

    与全量重试的区别：不带对话历史/工具权限/能力文档——只有 工具说明+参数表+
    原始 args+错误(+一句会话语义提示)，小模型在无干扰上下文下做纯 JSON 变换
    成功率远高于全量重试。仅一次尝试，失败返回 None(回落既有守卫路径)。
    context_hint: 可选的最小语义补充(如会话最近一条用户消息前 400 字)——
    仅当错误涉及标题/描述类字段时由调用方提供。
    """
    entry = _ra()._ARCH_TOOLS.get(name)
    if not entry:
        return None
    fn = entry["handler"]
    sys_prompt = (
        "你是 API 参数修复器。给定的工具调用参数 JSON 触发了错误，"
        "请只修复参数的结构/命名/类型以匹配工具签名，"
        "不要新增不存在的信息，不要改动原本正确的字段值；"
        "若必需信息确实缺失，将该字段留空字符串。"
        f"工具: {name}\n说明: {entry.get('description', '')[:600]}\n"
        f"参数签名: {_repair_param_table(fn)}\n"
        "只输出一个 ```json 围栏，内容为 {\"tool\": \""
        + name + "\", \"arguments\": {...}}，不要任何其他文字。")
    user_parts = [f"原始参数: {json.dumps(args, ensure_ascii=False)[:1800]}",
                  f"错误: {str(error)[:400]}"]
    if context_hint:
        user_parts.append(f"会话语义提示(仅供参考): {context_hint[:400]}")

    def _parse(raw: str):
        repaired = None
        m = re.search(r"```json\s*(\{.*?})\s*```", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, dict) and isinstance(data.get("arguments"), dict):
                    call_name = data.get("tool") or name
                    if call_name == name:
                        repaired = data["arguments"]
            except Exception:  # noqa: BLE001
                repaired = None
        if not repaired:
            fallback = _ra().extract_tool_calls(raw)
            for c in fallback:
                if c.get("tool") == name and isinstance(c.get("arguments"), dict):
                    repaired = c["arguments"]
                    break
        # 修复结果仍过一遍确定性收敛，并带 root/project 空位由 run_arch_tool 注入
        if isinstance(repaired, dict):
            repaired = _ra()._coerce_args(fn, repaired)
        return repaired

    out = run_repair_loop(RepairTask(
        task_id="arg_repair", system=sys_prompt, user="\n".join(user_parts),
        parse=_parse, max_tokens=700, model_id=model_id or "",
        dataset_kind="arg_repair",
        meta={"tool": name, "argsBefore": args, "error": str(error)[:400]}))
    repaired = out.get("parsed")
    logger.info("[arg-repair] %s ok=%s latency=%sms err=%s",
                name, bool(repaired), out.get("latencyMs"), str(error)[:120])
    return repaired if isinstance(repaired, dict) else None


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
        _store().ConversationsStore.append_message({
            "id": _store().next_id("sr"), "conversationId": conv_id,
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
        pass
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
        pass
    # 回灌锚定: 成功(或已有 summary 文案)时向主会话落系统回执
    if task.anchor_conv:
        text = task.anchor_text or (summary if ok else "")
        if text:
            anchor_back(task.anchor_conv, text)
    return out
