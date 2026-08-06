"""KbGateway — architect 与 KB 的唯一接触点(拓扑无关)。

双通道：
- `call(method, **params)`   → `POST {base}/zmq/{method}` (data_api RPC，操作/数据)
- `query(tool, **params)`    → `POST {mcp}/v1/tools/{tool}/call` (MCP，开放检索/LLM 工具)

约定(kb-contract.md §1)：
- KB 响应业务对象，不套包络；`call` 解出 `{"result": …}`。
- KB HTTP 500/detail 即业务错误 → 映射为 `KbError`(message 可读)。
- 连接失败/超时 → 返回 None(调用方降级 mock)，与旧 `_kb_call` 语义一致。
- 时间戳/字段口径转换由调用方(路由)负责。
"""
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class KbError(Exception):
    """KB 侧业务错误(HTTP 4xx/5xx，detail 即 message)。"""


class KbGateway:
    def __init__(self, base_url: str = None, mcp_url: str = None, timeout: float = 10.0):
        self.base_url = (base_url or os.environ.get("KB_BASE_URL") or "http://127.0.0.1:3459").rstrip("/")
        self.mcp_url = (mcp_url or os.environ.get("MCP_BASE_URL") or "http://127.0.0.1:3460").rstrip("/")
        self.timeout = timeout

    # ── RPC(API)通道 ─────────────────────────────────────────────

    def call(self, kb_method: str, **params):
        """调用 KB 方法。返回业务对象；KB 不可达返回 None；KB 业务失败抛 KbError。"""
        url = f"{self.base_url}/zmq/{kb_method}"
        req = urllib.request.Request(
            url,
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode())
            return body.get("result")
        except urllib.error.HTTPError as e:
            detail = str(e)
            try:
                detail = json.loads(e.read().decode()).get("detail", detail)
            except Exception:
                pass
            logger.warning("[KbGateway] %s -> HTTP %s: %s", kb_method, e.code, detail)
            raise KbError(detail)
        except Exception:
            logger.info("[KbGateway] %s unreachable (%s)", kb_method, url)
            return None

    # ── MCP 通道 ─────────────────────────────────────────────────

    def query(self, tool: str, **params):
        """调用 MCP 工具。返回 `{ok, tool, ...}` 原样；不可达返回 None。"""
        url = f"{self.mcp_url}/v1/tools/{tool}/call"
        req = urllib.request.Request(
            url,
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            logger.info("[KbGateway] mcp %s unreachable (%s)", tool, url)
            return None


_default = None


def get_gateway() -> KbGateway:
    """进程级默认网关(懒创建)。"""
    global _default
    if _default is None:
        _default = KbGateway()
    return _default


def call_kb(kb_method: str, **params):
    """便捷调用：走 ctx 注入网关(或默认网关)。业务错误/不可达返回 None(调用方降级)。"""
    from .ctx import kb
    gateway = kb()
    if gateway is None:
        gateway = get_gateway()
    try:
        return gateway.call(kb_method, **params)
    except KbError:
        return None
