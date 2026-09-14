"""兼容 shim: 实现迁至 agent.collab.sse(P1 纵切抽取)。

存量 `from . import ws_events` 路径保持可用; 新代码请用 agent.collab.sse。
"""
from ..agent.collab.sse import bind_loop, publish, subscribe, unsubscribe  # noqa: F401
