"""执行器统筹调度——资源注册表 + 同 root 仲裁 + 并发上限 + FIFO 排队。

2026-10 子会话模型裁决: 多个执行器会话并行时避免同工作区互踩/资源竞争。

规则(用户裁决: isolated 并行 + inplace 排队):
- 同一会话重复启动 → reject(已在执行);
- isolated 会话(runner worktree 独立目录) → 并行放行(天然隔离);
- inplace 会话 → 同 root 已有 running 时排队(FIFO), 前序终态自动续跑;
- 执行器级并发上限(config.maxConcurrent, 默认 2) + 全局上限, 超出排队。

注册表为进程内存态(architect 单进程); 重启丢失=仅失去排队记忆, 安全侧
(下次启动重新仲裁)。终态释放经 pumps/proxy_stop 调 release()。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("arch.execution.scheduler")

_MAX_GLOBAL = 8
_MAX_PER_EXECUTOR_DEFAULT = 2

_LOCK = threading.Lock()
# root → [slot]; slot = {jobId, executorId, convId, status: running|queued, ts, ...}
_REG: Dict[str, List[Dict[str, Any]]] = {}
# root → [queued entry]; entry 携带 relaunch 闭包(见 enqueue)
_QUEUE: Dict[str, List[Dict[str, Any]]] = {}
_LOOP: Optional[asyncio.AbstractEventLoop] = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """SSE/续跑需要主事件循环(pumps 已有同款 bind 模式)。"""
    global _LOOP
    _LOOP = loop


def _max_per_executor(executor_cfg: dict) -> int:
    n = (executor_cfg or {}).get("maxConcurrent")
    try:
        return max(1, int(n)) if n else _MAX_PER_EXECUTOR_DEFAULT
    except (TypeError, ValueError):
        return _MAX_PER_EXECUTOR_DEFAULT


def _slots(root: str) -> List[Dict[str, Any]]:
    return _REG.setdefault(root, [])


def _running(root: str) -> List[Dict[str, Any]]:
    return [s for s in _slots(root) if s.get("status") == "running"]


def snapshot() -> Dict[str, Any]:
    """调度全貌(管理面/测试): {root: {running: [...], queued: n}}。"""
    with _LOCK:
        return {root: {"running": [dict(s) for s in _running(root)],
                       "queued": len(_QUEUE.get(root, []))}
                for root, slots in _REG.items() if slots}


def admit(root: str, conv_id: str, executor_id: str,
          isolated: bool, executor_cfg: Optional[dict] = None) -> Dict[str, Any]:
    """启动前仲裁: {"action": "run"|"queue"|"reject", ...}。"""
    with _LOCK:
        running = _running(root)
        if any(s.get("convId") == conv_id for s in running):
            return {"action": "reject", "reason": "该会话执行器作业进行中——请先停止"}
        if len(running) >= _MAX_GLOBAL:
            return {"action": "queue", "position": len(_QUEUE.get(root, [])) + 1,
                    "reason": "全局执行器并发已满"}
        per = [s for s in running if s.get("executorId") == executor_id]
        if len(per) >= _max_per_executor(executor_cfg):
            return {"action": "queue", "position": len(_QUEUE.get(root, [])) + 1,
                    "reason": f"执行器 {executor_id} 并发已满({_max_per_executor(executor_cfg)})"}
        if not isolated and running:
            return {"action": "queue", "position": len(_QUEUE.get(root, [])) + 1,
                    "reason": f"工作区被 {len(running)} 个执行器会话占用(inplace 串行)"
                              "——可开启会话隔离开关并行"}
        return {"action": "run"}


def register(root: str, conv_id: str, executor_id: str, job_id: str = "",
             executor_cfg: Optional[dict] = None) -> None:
    """执行器会话启动成功 → 登记 running 槽。"""
    with _LOCK:
        _slots(root).append({"jobId": job_id, "executorId": executor_id,
                             "convId": conv_id, "status": "running",
                             "ts": time.time(),
                             "maxConcurrent": _max_per_executor(executor_cfg)})


def enqueue(root: str, entry: Dict[str, Any],
            relaunch: Optional[Callable[[Dict[str, Any]], Any]] = None) -> int:
    """排队项入队(FIFO)。entry 携带续跑所需载荷; relaunch=续跑协程函数。

    释放时机由 release() 驱动: 队首在 root 空闲(或项本身 isolated)时经
    _LOOP 调度 relaunch(entry)。"""
    with _LOCK:
        q = _QUEUE.setdefault(root, [])
        q.append({**entry, "relaunch": relaunch, "queuedAt": time.time()})
        pos = len(q)
    logger.info("[scheduler] queued root=%s conv=%s pos=%s", root,
                entry.get("convId"), pos)
    return pos


def _dequeue_locked(root: str) -> Optional[Dict[str, Any]]:
    q = _QUEUE.get(root) or []
    while q:
        head = q[0]
        busy_inplace = bool(_running(root)) and not head.get("isolated")
        if busy_inplace:
            return None                      # 队首仍需等待 → 保持队序
        return q.pop(0)
    return None


def _fire_relaunch(entry: Dict[str, Any]) -> None:
    """队首续跑调度(relaunch 闭包经主循环执行; 与 release 共用)。"""
    if entry and _LOOP is not None and callable(entry.get("relaunch")):
        relaunch, payload = entry["relaunch"], {
            k: v for k, v in entry.items() if k != "relaunch"}
        try:
            asyncio.run_coroutine_threadsafe(relaunch(payload), _LOOP)
            logger.info("[scheduler] relaunched root=%s conv=%s",
                        payload.get("root"), payload.get("convId"))
        except Exception:  # noqa: BLE001
            logger.exception("[scheduler] relaunch 调度失败 root=%s",
                             payload.get("root"))
        return
    if entry:
        logger.warning("[scheduler] 队首缺 relaunch/loop, 丢弃 root=%s",
                       entry.get("root"))


def release(root: str, conv_id: str = "", job_id: str = "") -> Optional[Dict[str, Any]]:
    """终态释放: 摘除槽位 → 队首满足条件则调度续跑。返回被续跑的 entry。"""
    with _LOCK:
        slots = _slots(root)
        slots[:] = [s for s in slots
                    if not ((conv_id and s.get("convId") == conv_id)
                            or (job_id and s.get("jobId") == job_id))]
        entry = _dequeue_locked(root)
    if entry:
        _fire_relaunch(entry)
    return entry


def release_conv(conv_id: str) -> Optional[Dict[str, Any]]:
    """idle 让坑(2610 F5a 裁决A): 等待输入的保活会话释放槽位——

    直通会话 turn 制保活(input_required)无终态事件, 此前槽位直到
    proxy_finish 才释放 → 同 root inplace 会话永久排队无反馈。改为
    回合收束(idle)即让坑, 队首自动续跑; 本会话下一回合重新 admit
    (活跃会话经 /input 分支仲裁, 见 proxy.proxy_turn)。root 未知 → 全
    root 扫描(convId 全局唯一定位, 与 stop_conv 同款兜底)。"""
    with _LOCK:
        for root in list(_REG.keys()):
            slots = _REG.get(root) or []
            if any(s.get("convId") == conv_id for s in slots):
                slots[:] = [s for s in slots if s.get("convId") != conv_id]
                entry = _dequeue_locked(root)
                break
        else:
            return None
    if entry:
        _fire_relaunch(entry)
    return entry


def busy_by_other(root: str, conv_id: str) -> Optional[Dict[str, Any]]:
    """同 root 是否有**其它**会话的 running 槽(占用检查, 供 /input 仲裁)。

    返回占用槽 {convId, jobId, executorId} / None。"""
    with _LOCK:
        for s in _running(root):
            if s.get("convId") != conv_id:
                return dict(s)
    return None


def state_of_conv(conv_id: str) -> Dict[str, Any]:
    """会话调度态(全 root 扫描): running / queued(position) / idle。"""
    with _LOCK:
        for root in list(_REG.keys()):
            for s in _running(root):
                if s.get("convId") == conv_id:
                    return {"state": "running", "root": root,
                            "executorId": str(s.get("executorId") or "")}
            q = _QUEUE.get(root) or []
            for i, e in enumerate(q):
                if e.get("convId") == conv_id:
                    ex = e.get("executor") or {}
                    return {"state": "queued", "position": i + 1, "root": root,
                            "executorId": str(ex.get("id") or "") if
                            isinstance(ex, dict) else ""}
    return {"state": "idle"}
    if entry:
        logger.warning("[scheduler] 队首缺 relaunch/loop, 丢弃 root=%s", root)
    return None


def stop_conv(root: str, conv_id: str) -> None:
    """用户主动停止 → 释放槽位且**不**自动续跑下一位(人为干预优先)。

    root 空串=未知 → 全 root 扫描按 convId 匹配。"""
    with _LOCK:
        roots = [root] if root else list(_REG.keys())
        for r in roots:
            slots = _REG.get(r) or []
            slots[:] = [s for s in slots if s.get("convId") != conv_id]
            q = _QUEUE.get(r) or []
            q[:] = [e for e in q if e.get("convId") != conv_id]


def state_of(root: str, conv_id: str) -> Dict[str, Any]:
    """会话执行器会话的调度态: running/queued(n)/idle。"""
    with _LOCK:
        for s in _running(root):
            if s.get("convId") == conv_id:
                return {"state": "running"}
        q = _QUEUE.get(root) or []
        for i, e in enumerate(q):
            if e.get("convId") == conv_id:
                return {"state": "queued", "position": i + 1}
    return {"state": "idle"}
