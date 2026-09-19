"""回合 IO/预算原语(M1 自 orchestrator 机械搬迁, 行为等价)。"""
from __future__ import annotations

import os
from typing import Awaitable, Callable

SendFn = Callable[[dict], Awaitable[None]]

_MAX_TOOL_ROUNDS = 4

# 回合总预算(秒): 流式空闲(60s)×多轮 + 降级 sync(可达 300s)曾串联卡死 6.5 分钟
# (cv-156/162 实证, 模型 hang 时)——超预算立即终止回合落 turnError, 不再续轮。
_TURN_BUDGET_S = float(os.environ.get("ARCH_TURN_BUDGET_S", "240"))


# 默认传 None 由主后端按 model_configs.max_tokens(设置中可配，如 32000)；也可经 KB 侧 `llm.maxTokens` 覆盖。
_MIN_CHAT_MAX_TOKENS = 8192

# 自由对话流式(ZMQ SUB)空闲超时：连续这么久收不到本 requestId 的任何事件(chunk/done/error)
# 即判定流中断(主后端/llm 服务重启、任务取消、瞬时断连)，降级 llm.sync 一次性收尾，
# 避免前端「知识库检索中…」永久挂起、内容始终不返回。
_STREAM_IDLE_TIMEOUT_S = 60.0


class _TurnIO:
    """回合 IO/预算原语(A 管线拆分): 各阶段共享的安全发送/chat_start 幂等/预算。

    取代原 handle_chat 内的 send_ev/_ensure_chat_start/_budget_left 闭包——
    阶段函数经 io 参数使用, 行为与原闭包逐字节等价。"""

    def __init__(self, send: SendFn, conv_id: str, last_user_msg_id: str,
                 budget_s: float = _TURN_BUDGET_S):
        self.send = send
        self.conv_id = conv_id
        self.last_user_msg_id = last_user_msg_id
        self.budget_s = budget_s
        self.t0 = __import__("time").time()
        self.client_gone = False
        self.chat_start_sent = False

    def budget_left(self) -> float:
        return self.budget_s - (__import__("time").time() - self.t0)

    async def send_ev(self, payload: dict) -> None:
        """安全发送: 客户端断连后吞掉发送异常, 服务端继续消费流/守卫/落库。"""
        if self.client_gone:
            return
        try:
            await self.send(payload)
        except Exception:  # noqa: BLE001
            self.client_gone = True

    async def ensure_chat_start(self, request_id: str = "") -> None:
        """chat_start 幂等补发: 降级路径(llm.sync)原样不发会让前端整段等待
        拿不到 conversationId/userMessageId——补发保证会话早绑定。"""
        if self.chat_start_sent:
            return
        await self.send({"type": "chat_start", "conversationId": self.conv_id,
                         "requestId": request_id or "",
                         "userMessageId": self.last_user_msg_id})
        self.chat_start_sent = True
