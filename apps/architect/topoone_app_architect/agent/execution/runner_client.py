"""类型化 runner 访问端 — /api/implement 作业面的统一封装。

P3: JobEvent schema(packages/core plugins/runner/events)类型化消费;
transport 经调用时注入(默认 exec_bridge._runner)——保留既有 monkeypatch
接缝(测试经 eb._runner 拦截)。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("arch.execution.runner_client")

# JobEvent schema(core 单源; 缺失时降级为裸 dict——老 runner 兼容)
try:
    from topoone.plugins.runner.events import parse_event, is_valid_kind  # type: ignore
    _SCHEMA = True
except Exception:  # noqa: BLE001 — 老环境无 core 事件模块
    _SCHEMA = False

    def parse_event(raw):  # type: ignore
        return raw

    def is_valid_kind(kind):  # type: ignore
        return True

TERMINAL_JOB_STATES = ("done", "failed", "stopped", "lost")
JOB_TERMINAL = ("done", "failed", "stopped")


@dataclass
class StartResult:
    ok: bool
    job_id: str = ""
    branch: str = ""
    worktree: str = ""
    session_id: str = ""
    base_commit: str = ""
    error: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Snapshot:
    """GET /api/implement/{id} 归一快照。"""
    ok: bool
    status: str = ""
    session_id: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InputResult:
    ok: bool
    queued: bool = False
    error: str = ""


class RunnerClient:
    """runner /api/implement* 访问端(类型化)。

    transport: callable(path, payload=None, timeout=...) → dict|None。
    每次操作调用时注入(exec_bridge 传 _runner, 保持 monkeypatch 接缝)。
    """

    def __init__(self, transport: Callable[..., Optional[dict]]):
        self._transport = transport

    def _t(self, path: str, payload: Optional[dict] = None,
           timeout: float = 12.0) -> Optional[dict]:
        """统一传输调用形状: payload/timeout 恒以关键字传递——匹配 _runner(path,
        payload=None, timeout=...) 契约, 兼容测试桩的最小签名(lambda path, **kw)。"""
        fn = self._transport
        return fn(path, payload=payload, timeout=timeout)

    # ── 作业生命周期 ──

    def start_implement(self, payload: Dict[str, Any], timeout: float = 20.0) -> StartResult:
        res = self._t("/api/implement", payload, timeout) or {}
        out = StartResult(
            ok=bool(res.get("ok")),
            job_id=str(res.get("jobId") or ""),
            branch=str(res.get("branch") or ""),
            worktree=str(res.get("worktree") or ""),
            session_id=str(res.get("sessionId") or ""),
            base_commit=str(res.get("baseCommit") or ""),
            error=str(res.get("error") or ("" if res.get("ok") else "runner 服务不可达(:3458)")),
            raw=res)
        return out

    def snapshot(self, job_id: str, since: int = 0, timeout: float = 12.0) -> Optional[Snapshot]:
        raw = self._t(f"/api/implement/{job_id}?since={since}", None, timeout)
        if raw is None:
            return None                      # runner 不可达(调用方区分 连续不可达/句柄丢失)
        if not raw.get("ok"):
            return Snapshot(ok=False, error=str(raw.get("error") or "job-not-found"), raw=raw)
        events = []
        for ev in raw.get("events") or []:
            try:
                events.append(parse_event(ev))
            except Exception:  # noqa: BLE001 — 单事件畸形不拖垮快照
                logger.debug("[runner-client] 畸形事件丢弃: %r", ev)
        return Snapshot(ok=True, status=str(raw.get("status") or ""),
                        session_id=str(raw.get("sessionId") or ""),
                        events=events, raw=raw)

    def input(self, job_id: str, text: str, steer: bool = False,
              timeout: float = 15.0) -> InputResult:
        payload: Dict[str, Any] = {"text": text}
        if steer:                                # P4: running 态 steer 直达(cline 优先投递)
            payload["steer"] = True              # runner 侧不支持的执行器自动回退排队
        res = self._t(f"/api/implement/{job_id}/input", payload, timeout) or {}
        return InputResult(ok=bool(res.get("ok")), queued=bool(res.get("queued")),
                           error=str(res.get("error") or ""))

    def finish(self, job_id: str, keep_worktree: bool = True, timeout: float = 30.0) -> Dict[str, Any]:
        return self._t(f"/api/implement/{job_id}/finish",
                               {"keepWorktree": keep_worktree}, timeout) or {}

    def running(self, timeout: float = 8.0) -> Dict[str, Any]:
        return self._t("/api/implement/running", None, timeout) or {}

    def diff(self, job_id: str, timeout: float = 30.0) -> Dict[str, Any]:
        return self._t(f"/api/implement/{job_id}/diff", None, timeout) or {}

    # ── cline v2 内省面（透传 runner；非 cline 执行器由 runner 报不支持）──

    def messages(self, job_id: str, display: bool = True,
                 timeout: float = 30.0) -> Dict[str, Any]:
        return self._t(
            f"/api/implement/{job_id}/messages?display={'true' if display else 'false'}",
            None, timeout) or {}

    def usage(self, job_id: str, timeout: float = 15.0) -> Dict[str, Any]:
        return self._t(f"/api/implement/{job_id}/usage", None, timeout) or {}

    def checkpoints(self, job_id: str, run_count: int = 1,
                    timeout: float = 60.0) -> Dict[str, Any]:
        return self._t(
            f"/api/implement/{job_id}/checkpoints?runCount={int(run_count)}",
            None, timeout) or {}

    def restore(self, job_id: str, run_count: int, options: Optional[Dict[str, Any]] = None,
                timeout: float = 120.0) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"runCount": int(run_count)}
        if options:
            payload["options"] = options
        return self._t(f"/api/implement/{job_id}/restore", payload, timeout) or {}

    def update_model(self, job_id: str, model_id: str,
                     timeout: float = 15.0) -> Dict[str, Any]:
        return self._t(f"/api/implement/{job_id}/model",
                               {"modelId": model_id}, timeout) or {}

    def approval(self, job_id: str, request_id: str, approved: bool,
                 reason: str = "", timeout: float = 15.0) -> Dict[str, Any]:
        return self._t(f"/api/implement/{job_id}/approval",
                               {"requestId": request_id, "approved": approved,
                                "reason": reason}, timeout) or {}

    def pending(self, job_id: str, timeout: float = 15.0) -> Dict[str, Any]:
        return self._t(f"/api/implement/{job_id}/pending", None, timeout) or {}

    def proceed(self, job_id: str, tool_call_id: str = "",
                timeout: float = 30.0) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if tool_call_id:
            payload["toolCallId"] = tool_call_id
        return self._t(f"/api/implement/{job_id}/proceed",
                               payload or None, timeout) or {}

    def events_ws_url(self, base: str, job_id: str, since: int) -> str:
        url = base.replace("https://", "wss://").replace("http://", "ws://")
        return f"{url}/api/implement/{job_id}/events?since={since}"
