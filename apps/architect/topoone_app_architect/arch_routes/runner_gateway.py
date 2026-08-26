"""RunnerGateway — architect 与 runner 服务(:3458)的唯一接触点(拓扑无关)。

runner 是独立进程(任务树执行宿主: TaskTreeScheduler + ExecutorPool)。architect
把 SE 大脑产出的任务树经本网关提交给 runner 执行，并查询/控制树状态。

契约(见 runner server.py)：
- `submit_tree(tree_dict, context)` → POST /api/trees {tree, context} → tree_id
- `get_tree(tree_id)`               → GET  /api/trees/{id}            → {tree, progress}
- `update_tree(tree_id, tree_dict)` → PUT  /api/trees/{id} {tree}      (rejudge 换树)
- `rejudge(tree_id, task_ids)`      → POST /api/trees/{id}/rejudge     (刷新基线)
- `run(tree_id)`                    → POST /api/trees/{id}/run         (非阻塞执行)
- `skip/retry/pause/resume/cancel`  → POST /api/trees/{id}/...
- 连接失败/超时 → 返回 None/False(调用方降级报错)，与 KbGateway 语义一致。

进度事件不经本网关：前端直连 runner WS `/api/trees/{id}/events` 渲染进度。
"""
import json
import logging
import os
import socket
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_RUNNER_URL = "http://127.0.0.1:3458"


class RunnerGateway:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0):
        self.base_url = (
            base_url
            or os.environ.get("RUNNER_BASE_URL")
            or _DEFAULT_RUNNER_URL
        ).rstrip("/")
        self.timeout = timeout

    # ── 底层 ────────────────────────────────────────────────────

    def _request(self, method: str, path: str, payload: Optional[dict] = None,
                 timeout: Optional[float] = None):
        """返回解析后的 JSON；不可达/超时返回 None；HTTP 4xx/5xx 抛 RunnerError。"""
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
        except urllib.error.HTTPError as e:
            detail = str(e)
            try:
                detail = json.loads(e.read().decode()).get("detail", detail)
            except Exception:
                pass
            logger.warning("[RunnerGateway] %s %s -> HTTP %s: %s",
                           method, path, e.code, detail)
            raise RunnerError(detail)
        except (socket.timeout, TimeoutError, urllib.error.URLError) as e:
            if isinstance(e, urllib.error.URLError) and e.reason and not isinstance(e.reason, socket.timeout):
                logger.info("[RunnerGateway] %s %s unreachable (%s)", method, path, e.reason)
            else:
                logger.warning("[RunnerGateway] %s %s timeout after %.0fs", method, path, t)
            return None
        except Exception:  # noqa: BLE001
            logger.info("[RunnerGateway] %s %s unreachable", method, path)
            return None

    # ── 任务树 ──────────────────────────────────────────────────

    def submit_tree(self, tree_dict: dict, context: Optional[dict] = None) -> Optional[str]:
        """提交任务树。返回 tree_id；runner 不可达返回 None。"""
        res = self._request("POST", "/api/trees",
                            {"tree": tree_dict, "context": context or {}})
        if not isinstance(res, dict):
            return None
        return res.get("tree_id")

    def get_tree(self, tree_id: str) -> Optional[dict]:
        """树详情 + 进度 → {tree, progress}；不可达返回 None。"""
        res = self._request("GET", f"/api/trees/{tree_id}")
        return res if isinstance(res, dict) else None

    def update_tree(self, tree_id: str, tree_dict: dict) -> bool:
        res = self._request("PUT", f"/api/trees/{tree_id}", {"tree": tree_dict})
        return bool(isinstance(res, dict) and res.get("ok"))

    def rejudge(self, tree_id: str, task_ids: list) -> bool:
        res = self._request("POST", f"/api/trees/{tree_id}/rejudge",
                            {"task_ids": list(task_ids or [])})
        return bool(isinstance(res, dict) and res.get("ok"))

    def run(self, tree_id: str) -> Optional[dict]:
        """触发执行(非阻塞)→ {progress}；不可达返回 None。"""
        res = self._request("POST", f"/api/trees/{tree_id}/run")
        return res if isinstance(res, dict) else None

    def skip(self, tree_id: str, task_id: str) -> bool:
        res = self._request("POST", f"/api/trees/{tree_id}/skip", {"task_id": task_id})
        return bool(isinstance(res, dict) and res.get("ok"))

    def retry(self, tree_id: str, task_id: str) -> bool:
        res = self._request("POST", f"/api/trees/{tree_id}/retry", {"task_id": task_id})
        return bool(isinstance(res, dict) and res.get("ok"))

    def pause(self, tree_id: str) -> bool:
        res = self._request("POST", f"/api/trees/{tree_id}/pause")
        return bool(isinstance(res, dict) and res.get("ok"))

    def resume(self, tree_id: str) -> bool:
        res = self._request("POST", f"/api/trees/{tree_id}/resume")
        return bool(isinstance(res, dict) and res.get("ok"))

    def cancel(self, tree_id: str) -> bool:
        res = self._request("POST", f"/api/trees/{tree_id}/cancel")
        return bool(isinstance(res, dict) and res.get("ok"))

    def health(self) -> bool:
        res = self._request("GET", "/healthz", timeout=3)
        return bool(isinstance(res, dict) and res.get("ok"))


class RunnerError(Exception):
    """runner 侧业务错误(HTTP 4xx/5xx，detail 即 message)。"""


_default = None


def get_runner() -> RunnerGateway:
    """进程级默认 runner 网关(懒创建)。"""
    global _default
    if _default is None:
        _default = RunnerGateway()
    return _default
