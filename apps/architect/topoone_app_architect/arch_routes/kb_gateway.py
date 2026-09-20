"""KbGateway — architect 与 KB 的唯一接触点(拓扑无关)。

双通道：
- `call(method, **params)`   → `POST {base}/zmq/{method}` (data_api RPC，操作/数据)
- `query(tool, **params)`    → `POST {mcp}/v1/tools/{tool}/call` (MCP，开放检索/LLM 工具)

约定(kb-contract.md §1)：
- KB 响应业务对象，不套包络；`call` 解出 `{"result": …}`。
- KB HTTP 500/detail 即业务错误 → 映射为 `KbError`(message 可读)。
- 连接失败/超时 → 返回 None(调用方降级 mock)，与旧 `_kb_call` 语义一致。
- 时间戳/字段口径转换由调用方(路由)负责。

> MCP 方向说明(2026-08)：当前 architect→KB 的 MCP 出向(`query()`)为**预留接口**，
> 尚无路由消费。当前生效的 MCP 方向是**入向**：KB 侧 `plugins/mcp_server`(3460)
> 把外部 agent 的 `/v1/tools/*` 调用转发进 architect 的 `/mcp/calls`(经 `mcp_collab` 记录)。
"""
import json
import logging
import os
import socket
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_KB_TOKEN_CACHE = ""   # serve token 进程内缓存(读一次)


class KbError(Exception):
    """KB 侧业务错误(HTTP 4xx/5xx，detail 即 message)。"""


class KbGateway:
    def __init__(self, base_url: str = None, mcp_url: str = None,
                 timeout: float = None):
        from ..agent.governance.timeouts import get as _timeout_of
        self.base_url = (base_url or os.environ.get("KB_BASE_URL") or "http://127.0.0.1:3459").rstrip("/")
        self.mcp_url = (mcp_url or os.environ.get("MCP_BASE_URL") or "http://127.0.0.1:3460").rstrip("/")
        # cv-199: 默认超时走统一单源(TOPO_TIMEOUT_KB_RPC 可覆盖)
        self.timeout = float(timeout) if timeout is not None else _timeout_of("kb_rpc")

    @staticmethod
    def _internal_token() -> str:
        """读本机 serve token(与 gateway/data_api 同源)——/zmq 内部面凭据。

        KB data_api 的 /zmq/{method} 双面鉴权：带 X-KB-Internal 的内部面全放行，
        外部面仅 EXTERNAL_METHODS 白名单。architect 属内部链路(llm.sync/
        analysis.parseFileAst 等)，不带令牌会被 403 拒绝(LLM 通道静默断链)。
        """
        global _KB_TOKEN_CACHE
        if _KB_TOKEN_CACHE:
            return _KB_TOKEN_CACHE
        base = os.environ.get("TOPOCODE_DB_DIR") or os.path.join(
            os.path.expanduser("~"), ".topocode")
        p = os.path.join(base, "token")
        try:
            with open(p) as f:
                _KB_TOKEN_CACHE = (f.read().strip() or "")
        except Exception:
            _KB_TOKEN_CACHE = ""
        return _KB_TOKEN_CACHE

    # ── RPC(API)通道 ─────────────────────────────────────────────

    def call(self, kb_method: str, timeout: float = None, **params):
        """调用 KB 方法。返回业务对象；KB 不可达/超时返回 None；KB 业务失败抛 KbError。

        timeout 为 None 时用实例默认(self.timeout)；LLM 等耗时调用方应显式传更长超时。
        """
        t = self.timeout if timeout is None else float(timeout)
        url = f"{self.base_url}/zmq/{kb_method}"
        token = self._internal_token()
        req = urllib.request.Request(
            url,
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json",
                     **({"X-KB-Internal": token} if token else {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=t) as resp:
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
        except (socket.timeout, TimeoutError, urllib.error.URLError) as e:
            if isinstance(e, urllib.error.URLError) and e.reason and not isinstance(e.reason, socket.timeout):
                logger.info("[KbGateway] %s unreachable (%s): %s", kb_method, url, e.reason)
            else:
                logger.warning("[KbGateway] %s timeout after %.0fs (%s)", kb_method, t, url)
            return None
        except Exception:
            logger.info("[KbGateway] %s unreachable (%s)", kb_method, url)
            return None

    # ── MCP 通道 ─────────────────────────────────────────────────

    def query(self, tool: str, timeout: float = None, **params):
        """调用 MCP 工具。返回 `{ok, tool, ...}` 原样；不可达/超时返回 None。"""
        t = self.timeout if timeout is None else float(timeout)
        url = f"{self.mcp_url}/v1/tools/{tool}/call"
        req = urllib.request.Request(
            url,
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=t) as resp:
                return json.loads(resp.read().decode())
        except (socket.timeout, TimeoutError, urllib.error.URLError) as e:
            if isinstance(e, urllib.error.URLError) and e.reason and not isinstance(e.reason, socket.timeout):
                logger.info("[KbGateway] mcp %s unreachable (%s): %s", tool, url, e.reason)
            else:
                logger.warning("[KbGateway] mcp %s timeout after %.0fs (%s)", tool, t, url)
            return None
        except Exception:
            logger.info("[KbGateway] mcp %s unreachable (%s)", tool, url)
            return None


    def tools(self, timeout: float = None) -> list:
        """列出 MCP 可用工具(`GET /v1/tools`)。不可达/超时返回 []。"""
        t = (self.timeout if timeout is None else float(timeout))
        url = f"{self.mcp_url}/v1/tools"
        try:
            with urllib.request.urlopen(url, timeout=min(t, 5)) as resp:
                body = json.loads(resp.read().decode())
            return body.get("tools") or []
        except Exception as e:
            logger.info("[KbGateway] mcp tools list unreachable (%s): %s", url, e)
            return []


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
