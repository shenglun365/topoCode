"""BusClient — architect 与 agent-bus broker(:3486) 的唯一接触点(拓扑无关)。

broker 是独立进程(agent 间持久化消息总线，见 topoone_app_architect.agent_bus)。
architect 侧的 agent(plan agent / 指派入口)经本网关向 broker 发布消息：

- `publish(src, dst, topic, payload)` → POST /api/agent-bus/publish → {id}；
  不可达/超时返回 None(调用方降级报错，不静默丢消息)。
- `health()` → bool(GET /health)。

契约(见 agent_bus.py)：
- topic: interaction.clarify / interaction.answer /
  plan.revise / execution.progress / execution.result / execution.amend
- src/dst: plan | coding | runner | mcp | monitor | user | *

环境变量：BROKER_BASE_URL(默认 http://127.0.0.1:3486)。
"""
import json
import logging
import os
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_BROKER_URL = "http://127.0.0.1:3486"


class BusClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0):
        self.base_url = (
            base_url
            or os.environ.get("BROKER_BASE_URL")
            or _DEFAULT_BROKER_URL
        ).rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: Optional[dict] = None,
                 timeout: Optional[float] = None) -> Optional[dict]:
        """返回解析后的 JSON；不可达/超时返回 None。broker 侧业务错误亦返回 None。"""
        t = self.timeout if timeout is None else float(timeout)
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=t) as resp:
                body = resp.read().decode()
                return json.loads(body) if body else {}
        except (socket.timeout, TimeoutError, urllib.error.URLError) as e:
            if isinstance(e, urllib.error.URLError) and e.reason \
                    and not isinstance(e.reason, socket.timeout):
                logger.info("[BusClient] %s %s unreachable (%s)", method, path, e.reason)
            else:
                logger.warning("[BusClient] %s %s timeout after %.0fs", method, path, t)
            return None
        except Exception:  # noqa: BLE001
            logger.info("[BusClient] %s %s unreachable", method, path)
            return None

    def publish(self, src: str, dst: str, topic: str,
                payload: Optional[Dict[str, Any]] = None) -> Optional[dict]:
        """发布消息。返回 broker 响应 {code,data:{id,status}}；不可达返回 None。"""
        res = self._request("POST", "/api/agent-bus/publish", {
            "from": src, "to": dst, "topic": topic, "payload": payload or {},
        })
        if isinstance(res, dict) and res.get("code") == 0:
            return res.get("data")
        return None

    def health(self) -> bool:
        res = self._request("GET", "/health", timeout=3)
        return bool(isinstance(res, dict) and res.get("status") == "ok")


_default: Optional[BusClient] = None


def get_bus() -> BusClient:
    """进程级默认 broker 客户端(懒创建)。"""
    global _default
    if _default is None:
        _default = BusClient()
    return _default
