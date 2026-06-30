"""
StateStore — 全局状态统一存储接口

Phase 0 过渡期架构:
  "dict"  mode: 仅写内存 dict（Phase 0 前原始行为，已废弃）
  "dual"  mode: 同时写内存 dict + CacheStore（当前阶段，双写保证一致性）
  "cache" mode: 仅写 CacheStore（后续 Phase，通过 Bus → DB Service）

双写期间读取优先 CacheStore，未命中时 fallback 内存 dict。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_NS_STOP = "stop_flags"
_NS_PS_FAILED = "ps_failed"
_NS_RANKS = "ranks"
_NS_EXECUTING = "executing_tasks"
_NS_SUBAGENT_FAILED = "subagent_failed"


class StateStore:
    def __init__(self, cache_store=None, mode: str = "dual"):
        self._cache = cache_store
        self._mode = mode
        self._lock = threading.Lock()

        self._stops: dict[str, bool] = {}
        self._ps_failed: dict[str, int] = {}
        self._subagent_failed: dict[str, int] = {}
        self._executing: set[str] = set()

    # ── 模式切换 ────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    def switch_to_cache(self):
        with self._lock:
            self._mode = "cache"
            self._stops.clear()
            self._ps_failed.clear()
            self._subagent_failed.clear()
            self._executing.clear()

    def switch_to_dual(self):
        self._mode = "dual"

    # ── 辅助 ─────────────────────────────────────────────────────────

    def _cache_get(self, namespace: str, key: str, default=None):
        if self._cache is None:
            return default
        try:
            return self._cache.get(f"{namespace}:{key}", default)
        except Exception:
            return default

    def _cache_set(self, namespace: str, key: str, value):
        if self._cache is None:
            return
        try:
            self._cache.set(f"{namespace}:{key}", value)
        except Exception as e:
            logger.warning(f"[StateStore] cache set error {namespace}:{key}: {e}")

    def _cache_delete(self, namespace: str, key: str):
        if self._cache is None:
            return
        try:
            self._cache.delete(f"{namespace}:{key}")
        except Exception:
            pass

    def _cache_incr(self, namespace: str, key: str, delta: int = 1) -> int:
        if self._cache is None:
            return 0
        try:
            return self._cache.incr(f"{namespace}:{key}", delta)
        except KeyError:
            self._cache_set(namespace, key, delta)
            return delta
        except Exception:
            return 0

    # ── stop_flags (analyst_runner hot path — 优先读内存) ────────────

    def set_stop(self, task_id: str):
        with self._lock:
            self._stops[task_id] = True
            if self._mode in ("dual", "cache"):
                self._cache_set(_NS_STOP, task_id, True)

    def clear_stop(self, task_id: str):
        with self._lock:
            self._stops.pop(task_id, None)
            if self._mode in ("dual", "cache"):
                self._cache_delete(_NS_STOP, task_id)

    def should_stop(self, task_id: str) -> bool:
        with self._lock:
            val = self._stops.get(task_id)
            if val is not None:
                return val
        if self._mode in ("dual", "cache"):
            cached = self._cache_get(_NS_STOP, task_id)
            if cached is not None:
                with self._lock:
                    self._stops[task_id] = cached
                return cached
        return False

    # ── executing_tasks ──────────────────────────────────────────────

    def add_executing(self, task_id: str):
        with self._lock:
            self._executing.add(task_id)
            if self._mode in ("dual", "cache"):
                self._cache_set(_NS_EXECUTING, task_id, True)

    def remove_executing(self, task_id: str):
        with self._lock:
            self._executing.discard(task_id)
            if self._mode in ("dual", "cache"):
                self._cache_delete(_NS_EXECUTING, task_id)

    def is_executing(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._executing:
                return True
        if self._mode in ("dual", "cache"):
            val = self._cache_get(_NS_EXECUTING, task_id)
            if val:
                with self._lock:
                    self._executing.add(task_id)
                return True
        return False

    # ── ps_failed (task_manager) ────────────────────────────────────

    def get_ps_failed(self, task_id: str) -> int:
        with self._lock:
            v = self._ps_failed.get(task_id)
            if v is not None:
                return v
        cached = self._cache_get(_NS_PS_FAILED, task_id, 0)
        if cached:
            with self._lock:
                self._ps_failed[task_id] = cached
        return cached

    def set_ps_failed(self, task_id: str, count: int):
        with self._lock:
            self._ps_failed[task_id] = count
            if self._mode in ("dual", "cache"):
                self._cache_set(_NS_PS_FAILED, task_id, count)

    def incr_ps_failed(self, task_id: str, delta: int = 1) -> int:
        with self._lock:
            old = self._ps_failed.get(task_id, 0)
            new = old + delta
            self._ps_failed[task_id] = new
            if self._mode in ("dual", "cache"):
                return self._cache_incr(_NS_PS_FAILED, task_id, delta)
            return new

    def reset_ps_failed(self, task_id: str):
        with self._lock:
            self._ps_failed.pop(task_id, None)
            if self._mode in ("dual", "cache"):
                self._cache_delete(_NS_PS_FAILED, task_id)

    # ── rank cache (task_manager) ───────────────────────────────────

    def get_ranks(self, task_id: str) -> dict | None:
        if self._cache is None:
            return None
        return self._cache_get(_NS_RANKS, task_id)

    def set_ranks(self, task_id: str, ranks: dict, ttl: int = 3600):
        if self._cache is None:
            return
        self._cache_set(_NS_RANKS, task_id, ranks)
        if ttl and self._cache:
            try:
                self._cache.set(f"{_NS_RANKS}:{task_id}", ranks, expire=ttl)
            except Exception:
                pass

    def delete_ranks(self, task_id: str):
        if self._cache is None:
            return
        self._cache_delete(_NS_RANKS, task_id)

    # ── SubAgent._task_failed ───────────────────────────────────────

    def get_subagent_failed(self, task_id: str) -> int:
        with self._lock:
            v = self._subagent_failed.get(task_id)
            if v is not None:
                return v
        cached = self._cache_get(_NS_SUBAGENT_FAILED, task_id, 0)
        if cached:
            with self._lock:
                self._subagent_failed[task_id] = cached
        return cached

    def set_subagent_failed(self, task_id: str, count: int):
        with self._lock:
            self._subagent_failed[task_id] = count
            if self._mode in ("dual", "cache"):
                self._cache_set(_NS_SUBAGENT_FAILED, task_id, count)

    def reset_subagent_failed(self, task_id: str):
        with self._lock:
            self._subagent_failed.pop(task_id, None)
            if self._mode in ("dual", "cache"):
                self._cache_delete(_NS_SUBAGENT_FAILED, task_id)


# ==================== 模块级单例 ====================
_store: StateStore | None = None


def get_store() -> StateStore:
    global _store
    if _store is None:
        _store = StateStore()
    return _store
