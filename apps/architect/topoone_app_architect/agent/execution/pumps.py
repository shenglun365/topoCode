"""单一事件泵 — runner 作业事件的实时订阅 + 轮询校准(唯一实现)。

P3 双泵合一: 旧 jobs 路径 _pump/_handle_pump_event 清退, 任务泵(_task_pump)
的「WS 实时订阅优先, snapshot 轮询校准兜底」骨架收拢为 run_event_pump,
事件处理/终态决策经回调注入(exec_bridge 任务域接线)。

通道语义:
  - 订阅模式: runner 事件即产即推(opencode SSE/codex notifications 端到端即时)
  - 校准/降级: 订阅不可达或空闲超时 → snapshot 轮询(补漏+终态确认+连续不可达 lost)
  - 去重: seq 单调, 两侧共用
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from ..governance.timeouts import get as _timeout_of
logger = logging.getLogger("arch.execution.pumps")

POLL_INTERVAL = 2.5
WS_IDLE_SEC = 10.0         # 订阅空闲窗口(超时→snapshot 校准一轮, 保留 lost/终态判定)
WS_RETRY_GAP = 4           # 订阅失败后的重试间隔(轮询轮)
# 8 次(每次 snapshot 12s 超时 + poll 间隔) ≈ 2 分钟 runner 不可达容错——
# runner 重启/滚动升级窗口内不误杀 running 任务为 lost(重启后 recover_sweep 重挂)
MAX_CONSECUTIVE_ERR = 8

SendFn = Callable[[dict], Any]
OnEvent = Callable[[dict], None]
OnSnapshot = Callable[[dict], None]
OnLost = Callable[[str], None]


async def ws_connect(base: str, job_id: str, since: int,
                     timeout: float = 4.0):
    """连接 runner 作业事件实时订阅面(失败返回 None——泵降级轮询)。"""
    try:
        import websockets
        url = (base.replace("https://", "wss://").replace("http://", "ws://")
               + f"/api/implement/{job_id}/events?since={since}")
        return await asyncio.wait_for(
            websockets.connect(url, open_timeout=_timeout_of("pump_ws_open"), max_size=4 * 1024 * 1024), timeout)
    except Exception:  # noqa: BLE001
        return None


def _persist(job_id: str, ev: dict, conv_id: str = "") -> None:
    """B1 事件留痕(architect 自持): 会话浏览器/审计数据源, 失败不阻塞。

    2610 B1: conv_id 注入 extra——事件行自带会话锚点, job↔conv 映射单源
    (此前 exec_sessions 需任务行/session_ref/启动卡三层回退推断)。"""
    try:
        from ...store import exec_events
        if conv_id:
            ev = {**ev, "conversationId": conv_id}
        exec_events.record_event(job_id, ev)
    except Exception:  # noqa: BLE001
        pass


async def run_event_pump(*, base: str, job_id: str,
                         runner,                       # callable(path, payload, timeout) → dict|None
                         on_event: OnEvent,
                         on_snapshot: OnSnapshot,
                         on_lost: OnLost,
                         on_terminal: Optional[Callable[[str], bool]] = None,
                         on_finished: Optional[Callable[[str], None]] = None,
                         poll_interval: float = POLL_INTERVAL,
                         conv_id: str = "",
                         ) -> None:
    """泵主循环(订阅优先 + 校准兜底), 终态返回。

    on_event(ev)            事件处理(seq 去重后; 回调内同步执行)
    on_snapshot(snap)       每轮校准补充(sessionRef 回写等; raw dict)
    on_lost(reason)         runner 连续不可达/句柄丢失(回调后泵退出)
    on_terminal(kind)       事件流终态判定; 返回 True → 泵退出(默认 done/failed)
    on_finished(status)     runner 侧 snapshot 终态(done/failed/stopped)退出前回调
    """
    if on_terminal is None:
        on_terminal = lambda kind: kind in ("done", "failed")  # noqa: E731
    errs = 0
    last_seq = 0
    ws = None
    ws_gap = 0
    try:
        while True:
            # ① 实时订阅优先
            if ws is None and ws_gap <= 0:
                ws = await ws_connect(base, job_id, last_seq)
                if ws is None:
                    ws_gap = WS_RETRY_GAP
                    await asyncio.sleep(poll_interval)
            if ws is not None:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=WS_IDLE_SEC)
                    ev = json.loads(raw)
                    if int(ev.get("seq") or 0) <= last_seq:
                        continue
                    last_seq = int(ev.get("seq") or 0)
                    _persist(job_id, ev, conv_id)
                    on_event(ev)
                    if on_terminal(ev.get("kind") or ""):
                        return
                    continue
                except Exception:  # noqa: BLE001
                    try:
                        await ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                    ws = None
                    ws_gap = 1     # 空闲超时/断流 → 校准一轮后再重连
            else:
                ws_gap = max(0, ws_gap - 1)
                await asyncio.sleep(poll_interval)

            # ② snapshot 校准(订阅空闲/降级共用): 补漏 + 终态确认 + lost
            snap = await asyncio.to_thread(
                runner, f"/api/implement/{job_id}?since={last_seq}", None, 12.0)
            if snap is None:
                errs += 1
                if errs >= MAX_CONSECUTIVE_ERR:
                    on_lost("runner 连续不可达")
                    return
                continue
            errs = 0
            if not snap.get("ok"):
                on_lost("作业句柄丢失(runner 重启?)")
                return
            on_snapshot(snap)
            for ev in snap.get("events") or []:
                if int(ev.get("seq") or 0) <= last_seq:
                    continue
                last_seq = max(last_seq, int(ev.get("seq") or 0))
                _persist(job_id, ev, conv_id)
                on_event(ev)
            status = snap.get("status") or ""
            if status in ("done", "failed", "stopped"):
                if on_finished:
                    on_finished(status)
                return
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("[pumps] pump crashed job=%s: %s", job_id, e)
        raise   # cv-264: 静默吞掉=僵尸泵(句柄存续+后续输出黑洞), 交调用方收尾
