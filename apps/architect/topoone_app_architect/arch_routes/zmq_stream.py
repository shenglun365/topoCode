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


def _pub_ports() -> list:
    """候选 PUB 端口集合：LLM 独立服务(5682) + KB 引擎(5681) + 旧 core(5680)。

    llm.chat 的路由因部署形态而异——独立 llm 服务时事件发布在 5682；经 KB 引擎
    (gateway 默认路由 llm.* → engine)时发布在 KB PUB 5681。实测单端口订阅会在
    后一种形态下收不到任何事件 → 对话退化为「idle 超时 + llm.sync 重复生成」。
    双端口并订(谁有事件听谁的)对两种形态都成立；env 可覆盖。
    """
    env_overrides = {p.strip() for p in
                     (os.environ.get("LLM_PUB_PORT", ""),
                      os.environ.get("KB_PUB_PORT", "")) if p.strip()}
    return sorted(env_overrides | {str(DEFAULT_LLM_PUB_PORT), "5681", "5680"})


async def iter_llm_events(request_id: str, timeout: float = 0.5,
                          idle_timeout: Optional[float] = None) -> AsyncIterator[Tuple[str, dict]]:
    """订阅主后端 llm.* PUB(多候选端口)，产出 (event_type, payload)，按 requestId 过滤。

    产出 chunk/done/error/tool_call/tool_result 全部事件；流结束时由调用方
    依 done/error 退出循环。连接失败/超时不阻塞：每轮空转后重试。
    idle_timeout: 连续这么久收不到本 requestId 的任何事件则停止产出(流中断检测，
    供调用方降级 llm.sync)；None=不限时(默认，向后兼容)。
    """
    import time
    import zmq
    import zmq.asyncio

    ctx = zmq.asyncio.Context.instance()
    socks = []
    poller = zmq.asyncio.Poller()
    try:
        for p in _pub_ports():
            try:
                s = ctx.socket(zmq.SUB)
                s.setsockopt(zmq.SUBSCRIBE, b"llm")
                s.setsockopt(zmq.LINGER, 0)
                s.connect(f"tcp://127.0.0.1:{int(p)}")
                socks.append(s)
                poller.register(s, zmq.POLLIN)
            except Exception:
                continue
        if not socks:
            return
        last_relevant = time.monotonic()
        while True:
            try:
                events = await asyncio.wait_for(poller.poll(timeout * 1000),
                                                timeout=timeout + 0.2)
            except asyncio.TimeoutError:
                events = []
            if not events:
                if idle_timeout and (time.monotonic() - last_relevant) >= idle_timeout:
                    return
                continue
            for s, _flags in events:
                try:
                    frames = await s.recv_multipart()
                except Exception:
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
        for s in socks:
            try:
                s.close(linger=0)
            except Exception:
                pass
