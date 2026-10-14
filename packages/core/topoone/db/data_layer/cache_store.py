"""
CacheStore — 统一键值持久化缓存

基于 diskcache，提供：
  - 线程安全的键值存储
  - TTL 自动过期
  - LRU 自动淘汰
  - 重启不丢失

替代模块级 dict:  _rank_cache, _ps_failed_counts, _executing_tasks
替代表记化 JSON:  AgentTaskManager JSON 持久化
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CacheStore:
    """
    统一键值缓存，封装 diskcache.Cache。

    命名空间规则:
        namespace:key → diskcache key  -> "{namespace}:{key}"
    """

    def __init__(self, cache_dir: str):
        from diskcache import Cache
        self._cache = Cache(cache_dir)
        self._lock = threading.Lock()
        logger.info(f"[CacheStore] initialized at {cache_dir}")

    # ── 通用 KV ────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def set(self, key: str, value: Any, expire: Optional[int] = None):
        with self._lock:
            self._cache.set(key, value, expire=expire)

    def delete(self, key: str):
        with self._lock:
            self._cache.delete(key)

    def incr(self, key: str, delta: int = 1) -> int:
        """原子递增。"""
        with self._lock:
            try:
                val = self._cache.incr(key, delta)
            except KeyError:
                val = delta
                self._cache.set(key, val)
        return val

    # ── 文件排名缓存 ───────────────────────────────────────────────────

    def get_file_ranks(self, task_id: str) -> Optional[dict]:
        key = f"ranks:{task_id}"
        return self.get(key)

    def set_file_ranks(self, task_id: str, ranks: dict, ttl: int = 3600):
        key = f"ranks:{task_id}"
        self.set(key, ranks, expire=ttl)

    def delete_file_ranks(self, task_id: str):
        self.delete(f"ranks:{task_id}")

    # ── 预摘要失败计数 ───────────────────────────────────────────────

    def get_ps_failed(self, task_id: str) -> int:
        return self.get(f"ps_failed:{task_id}", 0)

    def incr_ps_failed(self, task_id: str, delta: int = 1) -> int:
        return self.incr(f"ps_failed:{task_id}", delta)

    def reset_ps_failed(self, task_id: str):
        self.delete(f"ps_failed:{task_id}")

    def set_ps_failed(self, task_id: str, count: int):
        self.set(f"ps_failed:{task_id}", count)

    # ── 执行中任务 ─────────────────────────────────────────────────────

    def get_executing_tasks(self) -> set:
        data = self.get("executing_tasks")
        return set(data) if isinstance(data, list) else set()

    def add_executing_task(self, task_id: str):
        with self._lock:
            tasks = self.get_executing_tasks()
            tasks.add(task_id)
            self.set("executing_tasks", list(tasks))

    def remove_executing_task(self, task_id: str):
        with self._lock:
            tasks = self.get_executing_tasks()
            tasks.discard(task_id)
            self.set("executing_tasks", list(tasks))

    def is_task_executing(self, task_id: str) -> bool:
        return task_id in self.get_executing_tasks()

    # ── Agent 任务队列 ──────────────────────────────────────────────────

    def get_agent_tasks(self) -> list[dict]:
        data = self.get("agent_tasks")
        return data if isinstance(data, list) else []

    def set_agent_tasks(self, tasks: list[dict]):
        self.set("agent_tasks", tasks)

    def get_agent_task(self, agent_id: str) -> Optional[dict]:
        tasks = self.get_agent_tasks()
        for t in tasks:
            if t.get("agent_id") == agent_id:
                return t
        return None

    def set_agent_task(self, task_dict: dict):
        """插入或更新单个 agent 任务。"""
        with self._lock:
            tasks = self.get_agent_tasks()
            aid = task_dict.get("agent_id")
            found = False
            for i, t in enumerate(tasks):
                if t.get("agent_id") == aid:
                    tasks[i] = task_dict
                    found = True
                    break
            if not found:
                tasks.append(task_dict)
            self.set_agent_tasks(tasks)

    def delete_agent_task(self, agent_id: str):
        with self._lock:
            tasks = [t for t in self.get_agent_tasks()
                     if t.get("agent_id") != agent_id]
            self.set_agent_tasks(tasks)

    def clear_agent_tasks(self):
        self.delete("agent_tasks")

    # ── 生命周期 ────────────────────────────────────────────────────────

    def close(self):
        self._cache.close()

    def clear(self):
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)
