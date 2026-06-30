"""
DB Service — 独立数据库服务进程

集中管理所有 SQLite 数据库的写操作（串行化 WriteQueue）和读操作（并发读池）。
通过 ZMQ ROUTER socket 接收来自主进程和其他 Worker 的 DB 请求。

架构:
  ┌──────────────┐
  │ Main Process │— ZMQ DEALER —┐
  └──────────────┘               │
  ┌──────────────┐               │
  │  AST Worker  │— ZMQ DEALER —├──→ DB Service (ROUTER)
  └──────────────┘               │      ├── Write Thread (×1, WriteQueue)
  ┌──────────────┐               │      ├── Read Pool (×N, 直连 SQLite)
  │ Agent Worker │— ZMQ DEALER —┘      ├── CacheStore (diskcache)
  └──────────────┘                      └── DuckDBReader (OLAP 加速)

协议: 所有消息使用 JSON 编码，首帧为目标标签
  Request:  [identity, request_id, method, params_json]
  Response: [identity, request_id, result_json]   # ROUTER 自动添加 identity
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from signal import SIGINT, SIGTERM
import sys
import time
import uuid
from typing import Any

import zmq
import zmq.asyncio

from config import DB_SERVICE_PORT
from logging_config import setup_logging
from data_layer.write_queue import WriteQueue
from data_layer.cache_store import CacheStore

setup_logging()
logger = logging.getLogger("db_service")

_WRITE_METHODS = frozenset({
    "register_db", "register_conn",
    "execute", "execute_batch", "execute_sync",
})

_READ_METHODS = frozenset({
    "read_query", "read_one", "read_all",
})

_CACHE_METHODS = frozenset({
    "cache_get", "cache_set", "cache_delete", "cache_incr",
})


class DBService:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._write_queue = WriteQueue()
        self._cache_store = CacheStore(os.path.join(data_dir, "cache"))
        self._read_conns: dict[str, Any] = {}  # label → sqlite3.Connection
        self._context: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._running = False

        # 幂等去重: remembered request_ids within TTL (60s)
        self._seen_requests: deque = deque(maxlen=10000)
        self._seen_results: dict[str, dict] = {}

        cache_dir = os.path.join(data_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        self._cache_store = CacheStore(cache_dir)

    # ── 生命周期 ──────────────────────────────────────────────────

    async def start(self):
        self._context = zmq.asyncio.Context()
        self._socket = self._context.socket(zmq.ROUTER)
        self._socket.bind(f"tcp://127.0.0.1:{DB_SERVICE_PORT}")
        self._running = True
        logger.info(f"[DBService] listening on tcp://127.0.0.1:{DB_SERVICE_PORT}")

        try:
            while self._running:
                frames = await self._socket.recv_multipart()
                asyncio.ensure_future(self._handle(frames))
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    def stop(self):
        self._running = False

    async def _shutdown(self):
        self._write_queue.shutdown(timeout=5)
        for conn in self._read_conns.values():
            try:
                conn.close()
            except Exception:
                pass
        self._read_conns.clear()
        if self._socket:
            self._socket.close(linger=0)
            self._socket = None
        if self._context:
            self._context.term()
            self._context = None
        logger.info("[DBService] shutdown complete")

    # ── 消息分发 ──────────────────────────────────────────────────

    def _get_read_conn(self, label: str):
        """获取或创建读连接（懒加载，按 label 缓存）"""
        if label not in self._read_conns:
            import sqlite3
            path = self._write_queue._db_paths.get(label)
            if not path:
                raise ValueError(f"Unknown db label: {label}")
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._read_conns[label] = conn
        return self._read_conns[label]

    async def _handle(self, frames):
        """处理一条消息请求（带幂等去重），协议格式：
        新(5帧): [identity, request_id, trace_id, method, params_json]
        旧(4帧): [identity, request_id, method, params_json] (兼容)
        """
        if len(frames) < 4:
            logger.warning(f"[DBService] invalid frames: {len(frames)}")
            return
        identity = frames[0]
        request_id = frames[1].decode("utf-8")
        if len(frames) >= 5:
            trace_id = frames[2].decode("utf-8")
            method = frames[3].decode("utf-8")
            params = json.loads(frames[4])
        else:
            trace_id = ""
            method = frames[2].decode("utf-8")
            params = json.loads(frames[3])
        _log_prefix = f"[{trace_id[:8]}]" if trace_id else ""

        # 幂等检查：写操作的 request_id 60s 内重复直接返回缓存结果
        if request_id != "__fire__" and request_id in self._seen_requests and method in _WRITE_METHODS:
            cached = self._seen_results.get(request_id)
            if cached is not None:
                logger.debug(f"[DBService] dedup hit for {method} {request_id[:8]}")
                result = cached
                await self._socket.send_multipart([
                    identity,
                    request_id.encode("utf-8"),
                    json.dumps(result, default=str).encode("utf-8"),
                ])
                return

        try:
            if method in _WRITE_METHODS:
                result = await self._handle_write(method, params)
            elif method in _READ_METHODS:
                result = await self._handle_read(method, params)
            elif method in _CACHE_METHODS:
                result = self._handle_cache(method, params)
            else:
                result = {"error": f"Unknown method: {method}"}

            # 幂等记录（仅写操作）
            if request_id != "__fire__" and method in _WRITE_METHODS:
                self._seen_requests.append(request_id)
                self._seen_results[request_id] = result
                while len(self._seen_requests) > self._seen_requests.maxlen:
                    old = self._seen_requests.popleft()
                    self._seen_results.pop(old, None)

        except Exception as e:
            logger.error(f"{_log_prefix} [DBService] error in {method}: {e}")
            result = {"error": str(e)}

        try:
            await self._socket.send_multipart([
                identity,
                request_id.encode("utf-8"),
                json.dumps(result, default=str).encode("utf-8"),
            ])
        except Exception as e:
            logger.warning(f"[DBService] send error: {e}")

    # ── 写操作 (→ WriteQueue) ────────────────────────────────────

    async def _handle_write(self, method: str, params: dict) -> dict:
        if method == "register_db":
            self._write_queue.register_db(params["label"], params["path"])
            return {"ok": True}
        if method == "register_conn":
            # 远程模式下不可用 — 连接由 DB Service 自己管理
            logger.warning(f"[DBService] register_conn ignored for {params.get('label')}")
            return {"ok": True, "warning": "ignored"}
        if method == "execute_sync":
            sql = params["sql"]
            label = params["label"]
            # 多语句 DDL（包含 ;） → 直接 executescript，绕过单语句限制
            if ';' in sql.strip().rstrip(';'):
                conn = self._get_read_conn(label)
                conn.executescript(sql)
                if params.get("commit", True):
                    conn.commit()
                return {"lastrowid": None, "rowcount": -1}
            return self._write_queue.execute_sync(
                label, sql, tuple(params.get("params", [])),
                _commit=params.get("commit", True),
                timeout=params.get("timeout", 30.0),
            )
        if method == "execute":
            self._write_queue.execute(
                params["label"], params["sql"], tuple(params.get("params", [])),
                _commit=params.get("commit", True),
            )
            return {"ok": True}
        if method == "execute_batch":
            items = [(item[0], tuple(item[1]), item[2]) if isinstance(item, (list, tuple))
                     else (item["sql"], tuple(item.get("params", [])), item.get("commit", True))
                     for item in params.get("items", [])]
            return self._write_queue.execute_batch(params["label"], items)
        return {"error": f"Unknown write method: {method}"}

    # ── 读操作 (直接 SQLite) ─────────────────────────────────────

    async def _handle_read(self, method: str, params: dict) -> dict:
        label = params.get("label", "")
        sql = params.get("sql", "")
        p = tuple(params.get("params", []))
        conn = self._get_read_conn(label)
        if method == "read_query":
            cursor = conn.execute(sql, p)
            cols = [d[0] for d in cursor.description]
            rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
            return {"rows": rows}
        if method == "read_one":
            row = conn.execute(sql, p).fetchone()
            return {"row": dict(row) if row else None}
        if method == "read_all":
            rows = conn.execute(sql, p).fetchall()
            return {"rows": [dict(r) for r in rows]}
        return {"error": f"Unknown read method: {method}"}

    # ── 缓存操作 (→ CacheStore) ──────────────────────────────────

    def _handle_cache(self, method: str, params: dict) -> dict:
        if method == "cache_get":
            return {"value": self._cache_store.get(params["key"], params.get("default"))}
        if method == "cache_set":
            self._cache_store.set(params["key"], params["value"], expire=params.get("expire"))
            return {"ok": True}
        if method == "cache_delete":
            self._cache_store.delete(params["key"])
            return {"ok": True}
        if method == "cache_incr":
            return {"value": self._cache_store.incr(params["key"], params.get("delta", 1))}
        return {"error": f"Unknown cache method: {method}"}


# ═══════════════════════════════════════════════════════════════
# 独立进程入口
# ═══════════════════════════════════════════════════════════════

import asyncio


def main():
    data_dir = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--data-dir" and i < len(sys.argv):
            data_dir = sys.argv[i + 1]
        elif arg == "--help":
            print("Usage: python -m db_service --data-dir <path>")
            return

    if not data_dir:
        data_dir = os.environ.get("TOPOCODE_DB_DIR",
                                  os.path.join(os.path.expanduser("~"), ".topocode"))

    logger.info(f"[DBService] starting (data_dir={data_dir})")
    service = DBService(data_dir)

    from messaging.worker_signal import signal_ready, start_heartbeat_thread
    signal_ready()
    start_heartbeat_thread()

    # 信号处理
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, service.stop)
            except (NotImplementedError, ValueError):
                pass
        loop.run_until_complete(service.start())
    finally:
        loop.close()
        logger.info("[DBService] exited")


if __name__ == "__main__":
    main()
