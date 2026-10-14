"""Agent 服务 HTTP 客户端（P3e 移交）。

TOPO_MODE distributed 拓扑退役后，仅存 HttpAgentManager：
kb 进程经 agent 服务（/zmq/agent.*）执行 agent 任务。
原 RemoteWriteQueue/RemoteCacheStore/RemoteAgentManager 已随
distributed 分支一并删除。
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("topoone.messaging")


class HttpAgentManager:
    """HTTP 版 Agent 管理器 — 经 agent 服务(/zmq/agent.*)调用（P3e 移交）。

    接口与 RemoteAgentManager 对齐（dispatch/get_progress/cancel/get_history/
    clear_history/list_running_tasks/start_presummary_chain/_send），
    供 kb 进程 `_agent_mgr()` 返回，使 agent 执行归属 agent 服务。
    """

    def __init__(self, base_url: str = None):
        self._base = (base_url or os.environ.get("AGENT_API_URL")
                      or "http://127.0.0.1:3482").rstrip("/")

    def _call(self, method: str, params: dict, timeout: float = 60.0) -> dict:
        import urllib.request
        body = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base}/zmq/{method}", data=body, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
                return data.get("result", data)
        except Exception as e:
            logger.warning(f"[HttpAgent] {method} failed: {e}")
            raise

    def _send(self, action: str, params: dict, timeout: float = 60.0) -> dict:
        """兼容旧协议：action → agent.raw（agent 服务原样转发）。"""
        return self._call("agent.raw", {"action": action, **params}, timeout=timeout)

    def dispatch(self, route: str, task_id: str, context: dict,
                 project_id: str = "", project_root: str = "",
                 project_summary: str = "", **extra) -> dict:
        params = {
            "route": route, "task_id": task_id, "context": context or {},
            "project_id": project_id, "project_root": project_root,
            "project_summary": project_summary,
        }
        params.update(extra)
        return self._call("agent.dispatch", params, timeout=30.0)

    def get_progress(self, agent_id: str) -> dict:
        return self._call("agent.getProgress", {"agent_id": agent_id}, timeout=10.0)

    def cancel(self, agent_id: str) -> dict:
        return self._call("agent.cancel", {"agent_id": agent_id}, timeout=10.0)

    def get_history(self, task_id: str, offset: int = 0, limit: int = 10) -> dict:
        return self._call("agent.getHistory", {"task_id": task_id, "offset": offset, "limit": limit}, timeout=10.0)

    def clear_history(self, project_id: str, task_id: str) -> dict:
        return self._call("agent.clearHistory", {"project_id": project_id, "task_id": task_id}, timeout=10.0)

    def list_running_tasks(self) -> list[dict]:
        result = self._call("agent.listRunning", {}, timeout=10.0)
        return result.get("tasks", [])

    def start_presummary_chain(self, task_id: str, project_id: str, batches: list[str],
                                limit: int = 0, subagent_concurrency: int = 1,
                                project_root: str = "", project_summary: str = "") -> dict:
        return self._call("agent.presummaryChain", {
            "task_id": task_id, "project_id": project_id, "batches": batches,
            "limit": limit, "subagent_concurrency": subagent_concurrency,
            "project_root": project_root, "project_summary": project_summary,
        }, timeout=30.0)
