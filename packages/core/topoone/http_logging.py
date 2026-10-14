"""uvicorn access 日志过滤：丢弃心跳探测行。

supervisor 就绪/存活探针（GET /health）与前端轮询（GET /api/health）会产生
大量 200 access 日志行，淹没调试信息 —— 在 uvicorn.access logger 层直接丢弃，
其余 access 日志保持不变。
"""
import logging

_PATTERNS = ('"GET /health HTTP', '"GET /api/health HTTP')


class _HeartbeatFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.INFO:
            return True
        msg = record.getMessage()
        return not any(p in msg for p in _PATTERNS)


def install_heartbeat_filter() -> None:
    """在 uvicorn.access logger 上安装心跳过滤器（幂等）。"""
    lg = logging.getLogger("uvicorn.access")
    if any(isinstance(f, _HeartbeatFilter) for f in lg.filters):
        return
    lg.addFilter(_HeartbeatFilter())
