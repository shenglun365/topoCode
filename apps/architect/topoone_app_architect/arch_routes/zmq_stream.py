"""ZMQ SUB bridge — architect 订阅主后端 `llm.*` PUB，按 requestId 过滤逐字 chunk。

主后端(backend-core) `streaming_chat` 发起 `llm.chat` 后立即返回 requestId，
随后把 chunk 经 ZMQ PUB(topic `llm`，event_type `chunk`/`done`/`error`/`tool_call`/
`tool_result`)推送到 `tcp://127.0.0.1:{ZMQ_PUB_PORT}`(默认 5680)。
本模块在 architect 进程内建 SUB socket，订阅 `llm` 前缀并按 requestId 过滤，
把流式事件转成 async 迭代器供 WS 处理器转发给前端。

帧格式与主后端 `zmq_server._publish_worker` 一致：
    [topic(bytes), event_type(bytes), payload(bytes)]
"""
import asyncio
import json
import logging
import os
from typing import AsyncIterator, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_PUB_PORT = 5680
# P3：llm 事件改由独立 llm 服务 PUB :5682 发布；architect 订阅优先指向它
# （兼容旧 core :5680，env 可配）。
DEFAULT_LLM_PUB_PORT = 5682


def pub_port() -> int:
    try:
        return int(os.environ.get("LLM_PUB_PORT", str(DEFAULT_LLM_PUB_PORT)))
    except ValueError:
        return DEFAULT_LLM_PUB_PORT


async def iter_llm_events(request_id: str, timeout: float = 0.5,
                          idle_timeout: Optional[float] = None) -> AsyncIterator[Tuple[str, dict]]:
    """订阅主后端 llm.* PUB，产出 (event_type, payload)，按 requestId 过滤。

    产出 chunk/done/error/tool_call/tool_result 全部事件；流结束时由调用方
    依 done/error 退出循环。连接失败/超时不阻塞：每轮空转后重试。
    idle_timeout: 连续这么久收不到本 requestId 的任何事件则停止产出(流中断检测，
    供调用方降级 llm.sync)；None=不限时(默认，向后兼容)。
    """
    import time
    import zmq
    import zmq.asyncio

    ctx = zmq.asyncio.Context.instance()
    sock = ctx.socket(zmq.SUB)
    try:
        sock.setsockopt(zmq.SUBSCRIBE, b"llm")
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(f"tcp://127.0.0.1:{pub_port()}")
        last_relevant = time.monotonic()
        while True:
            try:
                frames = await asyncio.wait_for(sock.recv_multipart(), timeout=timeout)
            except asyncio.TimeoutError:
                if idle_timeout and (time.monotonic() - last_relevant) >= idle_timeout:
                    return
                continue
            except Exception:
                await asyncio.sleep(0.2)
                if idle_timeout and (time.monotonic() - last_relevant) >= idle_timeout:
                    return
                continue
            if len(frames) < 3:
                continue
            event_type = frames[1].decode("utf-8", "replace")
            try:
                payload = json.loads(frames[2].decode("utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict) or payload.get("requestId") != request_id:
                continue
            last_relevant = time.monotonic()
            yield event_type, payload
    finally:
        try:
            sock.close(linger=0)
        except Exception:
            pass


async def drain_stream_text(request_id: str) -> Optional[str]:
    """非流式降级用：消费完整个 requestId 的流，返回完整文本(done 时)。"""
    full = ""
    async for event_type, payload in iter_llm_events(request_id):
        if event_type == "chunk":
            full += payload.get("text", "") or ""
        elif event_type == "done":
            return payload.get("content") or full or None
        elif event_type == "error":
            logger.warning("[zmq_stream] request %s error: %s", request_id, payload.get("message", ""))
            return full or None
    return full or None
