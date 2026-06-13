"""
AgentMemory — 上下文窗口管理。

在 plan 阶段收集所有必要上下文（项目概览、社区列表、分析历史），
在 exec 阶段渐进式填入每次工具调用的结果。
控制上下文总量在 LLM 的 max_tokens 范围内。
"""

from typing import Any, Optional


class AgentMemory:
    """滑动上下文窗口，按优先级保留信息"""

    def __init__(self, max_context_chars: int = 40000):
        self._max_chars = max_context_chars
        self._entries: list[tuple[str, Any]] = []   # (key, value)
        self._key_chars: dict[str, int] = {}          # key → estimated char count

    def put(self, key: str, value: Any) -> None:
        """写入一条上下文，自动驱逐旧条目以确保不超限"""
        text = str(value)
        size = len(text)
        if key in self._key_chars:
            self._remove_key(key)
        self._entries.append((key, value))
        self._key_chars[key] = size
        self._trim()

    def get(self, key: str) -> Any:
        """读取指定 key 的上下文"""
        for k, v in self._entries:
            if k == key:
                return v
        return None

    def get_all(self) -> dict[str, Any]:
        """返回所有上下文的 dict"""
        return {k: v for k, v in self._entries}

    def format_context(self) -> str:
        """将所有上下文格式化为适合 LLM 的文本"""
        parts = []
        for key, value in self._entries:
            parts.append(f"## {key}\n{value}")
        return "\n\n".join(parts)

    @property
    def total_chars(self) -> int:
        return sum(self._key_chars.values())

    def _remove_key(self, key: str):
        self._entries = [(k, v) for k, v in self._entries if k != key]
        self._key_chars.pop(key, None)

    def _trim(self):
        """FIFO 驱逐最旧的条目直到总大小在限制内"""
        while self.total_chars > self._max_chars and len(self._entries) > 1:
            oldest_key = self._entries[0][0]
            self._remove_key(oldest_key)

    def clear(self):
        self._entries.clear()
        self._key_chars.clear()

    def __repr__(self):
        return f"AgentMemory(entries={len(self._entries)}, chars={self.total_chars}/{self._max_chars})"
