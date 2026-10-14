"""
Worker 信令 — 子进程通过 stdout JSON lines 向 Supervisor 报告状态

每个 worker 进程在启动时和运行中调用此模块的函数。
Supervisor 通过读取 stdout 解析这些信号。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

_HAS_STDOUT = not bool(os.environ.get("TOPO_NO_SIGNAL", ""))


def _write(msg: dict):
    if not _HAS_STDOUT:
        return
    try:
        sys.stdout.write(json.dumps(msg, default=str) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def signal_ready():
    """进程初始化完成，可以接受任务"""
    _write({"type": "ready", "pid": os.getpid(), "ts": time.time()})


def signal_heartbeat():
    """发送心跳"""
    _write({"type": "heartbeat", "pid": os.getpid(), "ts": time.time()})


def signal_error(message: str):
    """报告错误"""
    _write({"type": "error", "pid": os.getpid(), "msg": message, "ts": time.time()})


def start_heartbeat_thread(interval: float = 5.0):
    """启动心跳线程（daemon，进程退出自动终止）"""
    th = threading.Thread(target=_heartbeat_loop, args=(interval,), daemon=True)
    th.start()
    return th


def _heartbeat_loop(interval: float):
    while True:
        time.sleep(interval)
        signal_heartbeat()
