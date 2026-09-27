"""执行器过程流单源(cv-268)——text/tool/usage 事件 → 过程态(progress dict)。

统一任务链与直通的执行过程感知:
- 任务链: persist 写 TasksStore(持久, 刷新可见) + SSE progress(taskId 键)
- 直通:   纯内存环形(瞬态, 用户裁定) + SSE progress(conversationId 键, 无 taskId)
           → FE 消息区尾部 ExecutorProcessStrip

事件形状单源: runner events.EventBus(make_event 校验)。非过程事件返回 None,
调用方跳过(交回原分支处理)。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import time

# SSE 文本节流登记(键: task_id 或 f"proxy:{conv_id}")
_SSE_LAST: Dict[str, float] = {}
_PROXY_PROGRESS: Dict[str, Dict[str, Any]] = {}
_TEXT_THROTTLE = 0.5
_RING_MAX = 30


def _ts() -> int:
    return int(time.time() * 1000)


def apply_event(prev: Dict[str, Any], ev: dict) -> Optional[Dict[str, Any]]:
    """单事件 → 更新后的 progress dict(纯函数); 非过程事件返回 None。

    形状(与任务链存量字段等价): toolCount/msgCount/lastText/lastTool/
    process(环形尾)/inputTokens/outputTokens/at。"""
    kind = ev.get("kind") or ""
    text = (ev.get("text") or "").strip()
    prog = {**(prev or {}), "at": _ts()}
    if kind == "progress":
        prog["toolCount"] = max(int(ev.get("toolCount") or 0),
                                int(prev.get("toolCount") or 0))
        prog["msgCount"] = int(ev.get("msgCount") or 0)
        return prog
    if kind == "text":
        # 准流式执行预览: 滚动文本尾(600 字符), UI 过程面板实时变化
        prog["lastText"] = ((prev.get("lastText") or "") + text)[-600:]
        return prog
    if kind == "tool":
        name = str(ev.get("toolName") or text or "")
        trail = [*((prev.get("process") or [])),
                 {"at": prog["at"], "s": f"▸ {name}"}][-_RING_MAX:]
        prog["lastTool"] = name
        prog["process"] = trail
        # cv-270 自计数: cline 只发 tool 不发 progress(progress 报数恒缺)
        # → 取 max(自计数, progress 报数), 两种口径并存不回退
        prog["toolCount"] = max(int(prev.get("toolCount") or 0) + 1,
                                int(prev.get("_toolSelf") or 0) + 1)
        prog["_toolSelf"] = int(prev.get("_toolSelf") or 0) + 1
        return prog
    if kind == "usage":
        prog["inputTokens"] = int(ev.get("inputTokens") or 0)
        prog["outputTokens"] = int(ev.get("outputTokens") or 0)
        return prog
    return None


def publish(conv_id: str, key: str, prog: Dict[str, Any],
            throttle: float = 0.0, **extra: Any) -> None:
    """SSE progress 单一出口(键级节流: 文本高频 0.5s 一拍, 工具/终态不节流)。"""
    if throttle > 0:
        now = time.time()
        if now - _SSE_LAST.get(key, 0.0) < throttle:
            return
        _SSE_LAST[key] = now
    try:
        from ...agent.collab.sse import emit
        payload = {k: v for k, v in prog.items() if not str(k).startswith("_")}
        emit("progress", conv_id, **extra, **payload)
    except Exception:  # noqa: BLE001
        pass


def sse_throttle(kind: str) -> float:
    """事件类别的 SSE 节流秒(text 高频节流; 其余不节流保关键帧)。"""
    return _TEXT_THROTTLE if kind == "text" else 0.0


# ── 直通会话过程态(纯内存, 用户裁定瞬态——终态正文卡即产物) ──────────────

def proxy_progress(conv_id: str) -> Dict[str, Any]:
    return _PROXY_PROGRESS.get(conv_id) or {}


def proxy_store(conv_id: str, prog: Dict[str, Any]) -> None:
    _PROXY_PROGRESS[conv_id] = prog


def proxy_clear(conv_id: str) -> None:
    _PROXY_PROGRESS.pop(conv_id, None)
    _SSE_LAST.pop(f"proxy:{conv_id}", None)


def proxy_fold_snapshot(conv_id: str) -> Dict[str, Any]:
    """turn_done 折叠快照(cv-270): toolCount=本轮环长, 然后清空过程态——
    下一轮从零开始; 快照经 SSE 交 FE 折叠显示(纯内存瞬态不变)。"""
    prog = _PROXY_PROGRESS.pop(conv_id, None) or {}
    _SSE_LAST.pop(f"proxy:{conv_id}", None)
    return {"folded": True, "toolCount": len(prog.get("process") or []),
            "at": _ts()}


def proxy_finish(conv_id: str, note: str = "") -> None:
    """终态: 清过程态 + 下发 finished 帧(FE 据此撤过程条)。"""
    proxy_clear(conv_id)
    try:
        from ...agent.collab.sse import emit
        emit("progress", conv_id, finished=True, note=note, at=_ts())
    except Exception:  # noqa: BLE001
        pass


def task_persist_factory():
    """任务链持久回调: TasksStore.set_progress(闭包 task_id)。"""
    from ... import store as _st

    def _persist(task_id: str, prog: Dict[str, Any]) -> None:
        _st.TasksStore.set_progress(task_id, prog)
    return _persist
