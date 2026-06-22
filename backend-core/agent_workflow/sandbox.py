"""
安全沙箱 — 对 Agent 的所有操作施加硬约束。

组件:
  PathSandbox    — 读写路径白名单
  ContentGuard   — LLM 输出安全过滤
  RateLimiter    — 调用频率控制
  BudgetTracker  — Token / 时间预算
  AgentSandbox   — 组合以上四者的统一入口
"""

import time
import re
from typing import Optional


class PathSandbox:
    """路径沙箱：读操作仅限项目根目录，写操作仅限 .topocode/"""

    def __init__(self, project_root: str):
        import os
        self._root = os.path.abspath(project_root)
        self._topocode_dir = os.path.join(self._root, ".topocode")

    def allow_read(self, path: str) -> bool:
        import os
        abs_path = os.path.abspath(path)
        return abs_path.startswith(self._root)

    def allow_write(self, path: str) -> bool:
        import os
        abs_path = os.path.abspath(path)
        return abs_path.startswith(self._topocode_dir)

    def validate_read(self, path: str) -> str:
        if not self.allow_read(path):
            raise PermissionError(f"PathSandbox: read outside project_root: {path}")
        return path

    def validate_write(self, path: str) -> str:
        if not self.allow_write(path):
            raise PermissionError(f"PathSandbox: write outside .topocode: {path}")
        return path

    @property
    def project_root(self) -> str:
        return self._root

    @property
    def topocode_dir(self) -> str:
        return self._topocode_dir


class ContentGuard:
    """LLM 输出安全过滤：剔除可执行指令、shell 命令、URL"""

    _BLOCK_PATTERNS = [
        r"```(?:bash|sh|zsh|shell)\s[\s\S]*?```",   # shell code blocks
        r"```(?:python|js|javascript)\s[\s\S]*?```",  # code blocks
        r"`[^`]{1,200}`",                              # inline code
        r"https?://[^\s]{5,}",                         # URLs
        r"(?:sudo|chmod|chown|rm\s+-rf|mkfs|dd\s+if=)",  # dangerous commands
        r"<\?php[\s\S]*?\?>",                          # PHP tags
        r"<script[\s\S]*?</script>",                   # script tags
    ]
    _PATTERNS = [re.compile(p, re.IGNORECASE) for p in _BLOCK_PATTERNS]

    @classmethod
    def sanitize(cls, text: str) -> str:
        """移除敏感内容，返回安全文本"""
        result = text
        for pattern in cls._PATTERNS:
            result = pattern.sub("[content filtered]", result)
        result = result.strip()
        if not result:
            result = "(output sanitized)"
        return result

    @classmethod
    def is_safe(cls, text: str) -> bool:
        """检查文本是否包含敏感内容"""
        sanitized = cls.sanitize(text)
        return sanitized == text


class RateLimiter:
    """调用频率控制"""

    def __init__(self, max_concurrent: int = 3, min_interval_ms: int = 200, max_per_second: float = 1.0):
        self._max_concurrent = max_concurrent
        self._min_interval = min_interval_ms / 1000.0
        self._max_per_second = max_per_second
        self._running = 0
        self._last_call: float = 0.0
        self._calls_in_window: list[float] = []

    def acquire(self) -> bool:
        """尝试获取执行槽位，返回是否允许"""
        now = time.monotonic()

        self._calls_in_window = [t for t in self._calls_in_window if now - t < 1.0]

        if self._running >= self._max_concurrent:
            return False
        if self._last_call and (now - self._last_call) < self._min_interval:
            return False
        if len(self._calls_in_window) >= self._max_per_second:
            return False

        self._running += 1
        self._last_call = now
        self._calls_in_window.append(now)
        return True

    def release(self):
        self._running = max(0, self._running - 1)

    @property
    def running(self) -> int:
        return self._running


class BudgetTracker:
    """Token / 时间预算管理"""

    def __init__(self, max_tokens: int = 50000, timeout_seconds: int = 1800):
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        self._tokens_used: int = 0
        self._started_at: Optional[float] = None
        self._finished_at: Optional[float] = None

    def start(self):
        self._started_at = time.monotonic()

    def consume_tokens(self, count: int):
        self._tokens_used += count

    def tokens_exceeded(self) -> bool:
        return self._tokens_used >= self._max_tokens

    def time_exceeded(self) -> bool:
        if not self._started_at:
            return False
        return (time.monotonic() - self._started_at) >= self._timeout

    def exhausted(self) -> bool:
        if self._max_tokens <= 0 or self._timeout <= 0:
            return False
        return self.tokens_exceeded() or self.time_exceeded()

    def reset(self):
        """重置预算（每组件独立使用）"""
        self._tokens_used = 0
        self._started_at = None
        self._finished_at = None

    def finish(self):
        self._finished_at = time.monotonic()

    @property
    def elapsed(self) -> float:
        if not self._started_at:
            return 0
        end = self._finished_at or time.monotonic()
        return end - self._started_at

    @property
    def tokens_used(self) -> int:
        return self._tokens_used

    @property
    def tokens_remaining(self) -> int:
        if self._max_tokens <= 0:
            return 999_999_999
        return max(0, self._max_tokens - self._tokens_used)

    @property
    def time_remaining(self) -> float:
        if self._timeout <= 0:
            return 999_999.0
        if not self._started_at:
            return self._timeout
        return max(0, self._timeout - (time.monotonic() - self._started_at))

    @property
    def status(self) -> dict:
        return {
            "tokens_used": self._tokens_used,
            "tokens_limit": self._max_tokens,
            "time_elapsed_sec": round(self.elapsed, 1),
            "time_limit_sec": self._timeout,
        }


class AgentSandbox:
    """统一沙箱入口，组合 PathSandbox + ContentGuard + RateLimiter + BudgetTracker"""

    def __init__(
        self,
        project_root: str,
        max_tokens: int = 50000,
        timeout_seconds: int = 1800,
        max_concurrent: int = 3,
        min_interval_ms: int = 200,
        cloud_max_per_second: float = 1.0,
    ):
        self.path = PathSandbox(project_root)
        self.content = ContentGuard()
        self.llm_rate = RateLimiter(max_concurrent=max_concurrent, min_interval_ms=min_interval_ms)
        self.cloud_rate = RateLimiter(max_concurrent=1, min_interval_ms=0, max_per_second=cloud_max_per_second)
        self.budget = BudgetTracker(max_tokens=max_tokens, timeout_seconds=timeout_seconds)
