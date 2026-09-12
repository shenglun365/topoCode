"""TurnAdapter — 执行器回合适配层（多类型 coding agent 统一回合语义）。

背景：implement.py 作业宿主原硬编码 opencode serve。本层把「会话/回合/活动
感知/中断/变更」抽象为 TurnAdapter 协议，各执行器按自身通信机制实现：

  OpenCodeTurnAdapter   opencode serve(本地/远程) — REST + SSE /event 推送
  ClineTurnAdapter      cline SDK node sidecar — JSON-RPC + subscribe 回调
  CodexTurnAdapter      codex app-server — 双向 JSON-RPC(stdio) + notifications
  (remote-agent         分支协作型远端模式, 作业宿主暂不支持, 工厂显式报错)

统一探测语义(看门狗唯一依赖面)：
  probe(job) -> TurnProbe{status: busy|idle|error, last_activity_ts, last_error}
  - last_activity_ts 由各 adapter 在收到任意会话进展时刷新(epoch 秒)
  - status=error 表示执行器通道级故障(进程退出/SSE 断流/鉴权失败), 看门狗立即终止

配置来源：architect 侧 load_executors()(arch_collab_config["agent.executors"],
系统管理 UI 可编辑) → POST /api/implement 透传 executorId/executorType/executorConfig
→ create_implement 经 build_adapter() 构造。缺省回退 opencode(现网兼容)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_SSE_RECONNECT_SEC = 1.0


@dataclass
class TurnProbe:
    """执行器回合探测快照(看门狗判定输入)。"""
    status: str = "unknown"            # busy | idle | error | unknown
    last_activity_ts: float = 0.0      # 最近会话进展(epoch 秒; 0=未知)
    last_error: str = ""


@dataclass
class TurnOutcome:
    """一回合的产物。"""
    output: str = ""
    changed_files: list = field(default_factory=list)


class TurnAdapter:
    """执行器回合适配协议。job: implement.ImplementJob(承载 root/wt/session_id)。"""

    executor_id: str = ""
    executor_type: str = ""

    async def start_session(self, job) -> None:
        raise NotImplementedError

    async def run_turn(self, job, text: str) -> TurnOutcome:
        raise NotImplementedError

    async def probe(self, job) -> TurnProbe:
        raise NotImplementedError

    async def abort(self, job) -> bool:
        return False

    def dispose(self, job) -> None:  # noqa: B027
        """作业结束释放资源(serve/sidecar 等); 默认无需。"""


# ─────────────────────────── opencode serve ───────────────────────────


class OpenCodeTurnAdapter(TurnAdapter):
    """opencode serve 会话适配(本地托管或外部 baseUrl)。

    活动信号: 常驻 SSE GET /event(全局流, 按 properties.sessionID 过滤),
    message.*/session.* 事件刷新 last_activity_ts; 断流自动重连, 重连间隙
    由 GET /session/status 快照兜底。
    """

    def __init__(self, base_port: int = 3478, auto_start: bool = True,
                 base_url: str = "", opencode_bin: str = "", executor_id: str = "opencode"):
        from .executors.opencode import OpenCodeServeManager
        self.executor_id = executor_id
        self.executor_type = "opencode"
        self._mgr = OpenCodeServeManager(base_port=base_port, auto_start=auto_start,
                                         opencode_bin=opencode_bin)
        self._base_url = (base_url or "").rstrip("/")
        self._sse_tasks: Dict[str, asyncio.Task] = {}   # job.id → task

    async def _serve_url(self, job) -> str:
        if self._base_url:
            return self._base_url
        sp = await self._mgr.ensure(job.wt)
        return sp.url

    async def start_session(self, job) -> None:
        job.serve_url = await self._serve_url(job)
        headers = {"Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as c:
            r = await c.post(f"{job.serve_url}/session", json={"title": job.id})
            r.raise_for_status()
            job.session_id = (r.json() or {}).get("id") or ""
        if not job.session_id:
            raise RuntimeError("opencode session 创建失败")
        self._start_sse(job)

    def _start_sse(self, job) -> None:
        old = self._sse_tasks.get(job.id)
        if old and not old.done():
            return
        job.sse_stop = getattr(job, "sse_stop", None) or asyncio.Event()
        self._sse_tasks[job.id] = asyncio.create_task(self._sse_loop(job))

    async def _sse_loop(self, job) -> None:
        """常驻 SSE 订阅: 任意会话事件刷新 job.last_activity_ts; 错误记 job.last_error。"""
        stop: asyncio.Event = job.sse_stop
        url = job.serve_url
        async for client in _persist_client():
            try:
                async with client.stream(
                        "GET", f"{url}/event",
                        headers={"Accept": "text/event-stream"},
                        timeout=httpx.Timeout(10.0, read=None)) as resp:
                    async for line in resp.aiter_lines():
                        if stop.is_set():
                            return
                        if not line.startswith("data:"):
                            continue
                        try:
                            ev = json.loads(line[5:].strip())
                        except Exception:  # noqa: BLE001
                            continue
                        props = ev.get("properties") or {}
                        sid = props.get("sessionID") or props.get("sessionId") or ""
                        if job.session_id and sid and sid != job.session_id:
                            continue
                        ptype = str(props.get("type") or "")
                        if "error" in ptype:
                            job.last_error = str(props.get("error") or ptype)[:400]
                        if ptype.startswith(("message.", "session.", "permission.")):
                            job.last_activity_ts = time.time()
            except asyncio.CancelledError:
                return
            except Exception as e:  # noqa: BLE001
                logger.debug("[opencode-adapter] sse %s: %s", job.id, e)
            if stop.is_set():
                return
            await asyncio.sleep(_SSE_RECONNECT_SEC)

    async def run_turn(self, job, text: str) -> TurnOutcome:
        body: Dict[str, Any] = {"parts": [{"type": "text", "text": text}]}
        if job.model:
            if "/" in job.model:
                pid, mid = job.model.split("/", 1)
                body["model"] = {"providerID": pid, "modelID": mid}
            else:
                body["model"] = {"modelID": job.model}
        job.last_activity_ts = time.time()
        async with httpx.AsyncClient(
                timeout=job.turn_timeout,
                headers={"Content-Type": "application/json"}) as c:
            r = await c.post(
                f"{job.serve_url}/session/{job.session_id}/message", json=body)
            r.raise_for_status()
            data = r.json() or {}
        job.last_activity_ts = time.time()
        output = ""
        for part in (data.get("parts") or [])[::-1]:
            if part.get("type") == "text" and part.get("text"):
                output = part["text"]
                break
        return TurnOutcome(output=output, changed_files=_git_changed_files(job.wt))

    async def probe(self, job) -> TurnProbe:
        try:
            async with httpx.AsyncClient(timeout=4.0) as c:
                st = await c.get(f"{job.serve_url}/session/status")
            if st.status_code == 200:
                info = ((st.json() or {}).get(job.session_id)) or {}
                s = str(info.get("status") or "").lower()
                if s == "error":
                    return TurnProbe("error", job.last_activity_ts,
                                     str(info.get("message") or "session error"))
                if s in ("busy", "idle"):
                    return TurnProbe(s, job.last_activity_ts)
        except Exception as e:  # noqa: BLE001
            return TurnProbe("unknown", job.last_activity_ts, str(e)[:200])
        return TurnProbe("unknown", job.last_activity_ts)

    async def abort(self, job) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                await c.post(f"{job.serve_url}/session/{job.session_id}/abort")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[opencode-adapter] abort %s: %s", job.id, e)
            return False

    def dispose(self, job) -> None:
        stop = getattr(job, "sse_stop", None)
        if stop:
            stop.set()
        t = self._sse_tasks.pop(job.id, None)
        if t and not t.done():
            t.cancel()
        try:
            self._mgr.dispose_root(job.wt)
        except Exception:  # noqa: BLE001
            pass


async def _persist_client():
    """SSE 长连接客户端工厂(async for 语义, 供断流重连)。"""
    yield httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))


# ─────────────────────────── cline SDK (embedded) ───────────────────────────


class ClineTurnAdapter(TurnAdapter):
    """cline SDK node sidecar 适配。

    活动信号: sidecar 事件回调(set_event_handler)——sidecar 为单例, 事件可能
    不区分任务, 活动时间戳为近似值(多作业并发时取全局最近活动, 偏保守不误杀)。
    """

    def __init__(self, config: Dict[str, Any], executor_id: str = "cline"):
        from .executors.cline import _SidecarProcess, _default_token
        self.executor_id = executor_id
        self.executor_type = "cline-sdk"
        self._node = str(config.get("node_bin") or "node")
        self._script = str(config.get("sidecar_script") or "")
        self._provider_id = str(config.get("provider_id") or "")
        self._model_id = str(config.get("model_id") or "")
        self._api_key = str(config.get("api_key") or "")
        self._base_url = str(config.get("base_url") or "")
        self._max_iterations = int(config.get("max_iterations") or 40)
        self._arch_url = str(config.get("arch_url")
                             or os.environ.get("ARCH_BASE_URL", "http://127.0.0.1:3470"))
        self._arch_token = str(config.get("arch_token") or _default_token())
        self._sc: Optional[_SidecarProcess] = None
        self._turn_inflight: Dict[str, bool] = {}   # job.id → 回合进行中

    def _sidecar(self):
        if self._sc is None:
            self._sc = _SidecarProcess(self._node, self._script)
        return self._sc

    async def start_session(self, job) -> None:
        sc = self._sidecar()

        def _on_event(params: dict) -> None:
            job.last_activity_ts = time.time()
            t = str(params.get("type") or "")
            if t in ("status", "done", "tool"):
                logger.debug("[cline-adapter] %s %s", job.id, t)

        sc.set_event_handler(_on_event)
        await sc.call("ping", timeout=40.0)   # sidecar 就绪
        job.session_id = job.id               # cline 语义: taskId 即会话
        job.serve_url = f"sidecar://{self.executor_id}"

    async def run_turn(self, job, text: str) -> TurnOutcome:
        self._turn_inflight[job.id] = True
        job.last_activity_ts = time.time()
        try:
            sc = self._sidecar()
            params: Dict[str, Any] = {
                "taskId": job.id, "prompt": text, "cwd": job.wt,
                "maxIterations": self._max_iterations,
                "archUrl": self._arch_url, "archToken": self._arch_token,
                "projectId": getattr(job, "project_id", "") or "",
            }
            if self._provider_id:
                params["providerId"] = self._provider_id
            if self._model_id:
                params["modelId"] = self._model_id
            if self._api_key:
                params["apiKey"] = self._api_key
            if self._base_url:
                params["baseUrl"] = self._base_url
            result = await sc.call("run", params, timeout=job.turn_timeout)
            job.last_activity_ts = time.time()
            if not result.get("success"):
                raise RuntimeError(str(result.get("error") or "cline 执行失败"))
            return TurnOutcome(output=str(result.get("output") or ""),
                               changed_files=list(result.get("changedFiles") or []))
        finally:
            self._turn_inflight[job.id] = False

    async def probe(self, job) -> TurnProbe:
        sc = self._sc
        if sc is not None and getattr(sc, "_proc", None) is not None \
                and sc._proc.poll() is not None:
            return TurnProbe("error", job.last_activity_ts, "cline sidecar 进程已退出")
        status = "busy" if self._turn_inflight.get(job.id) else "idle"
        return TurnProbe(status, job.last_activity_ts)

    async def abort(self, job) -> bool:
        try:
            await self._sidecar().call("stop", {"taskId": job.id}, timeout=15.0)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[cline-adapter] abort %s: %s", job.id, e)
            return False

    def dispose(self, job) -> None:
        self._turn_inflight.pop(job.id, None)


# ─────────────────────────── codex app-server ───────────────────────────

_CODEX_SERVERS: Dict[str, "_AppServerProxy"] = {}


class _AppServerProxy:
    """codex app-server 共享代理: (bin, codex_home) → 进程 + 通道状态。

    在 _AppServerProcess 之上补看门狗所需信号:
      dead/dead_reason — read loop 退出(通道断流) → probe error
    """

    def __init__(self, codex_bin: str, codex_home: str = ""):
        from .executors.codex_server import _AppServerProcess
        self.proc = _AppServerProcess(codex_bin, cwd=os.getcwd(),
                                      codex_home=codex_home)
        self.dead = False
        self.dead_reason = ""


def _codex_server(codex_bin: str, codex_home: str) -> _AppServerProxy:
    key = f"{codex_bin}:{codex_home}"
    if key not in _CODEX_SERVERS:
        _CODEX_SERVERS[key] = _AppServerProxy(codex_bin, codex_home)
    return _CODEX_SERVERS[key]


class CodexTurnAdapter(TurnAdapter):
    """codex app-server 适配(双向 JSON-RPC over stdio + notifications)。

    活动信号: run_turn 聚合循环内每收到任意 notification 刷新 last_activity_ts;
    通道断流(read loop 退出)与 error 事件(!willRetry/反复失败) → probe error。
    """

    _DONE_HINTS = ("turn/completed", "turn/failed", "turn/cancelled")

    def __init__(self, config: Dict[str, Any], executor_id: str = "codex"):
        self.executor_id = executor_id
        self.executor_type = "codex-server"
        self._codex_bin = str(config.get("codex_bin") or "codex")
        self._codex_home = str(config.get("codex_home") or "")
        self._approval_policy = str(config.get("approval_policy") or "never")
        self._sandbox_mode = str(config.get("sandbox_mode") or "workspace-write")
        self._model = str(config.get("model") or "")
        self._aborting: Dict[str, bool] = {}
        self._turn_inflight: Dict[str, bool] = {}
        self._thread_of: Dict[str, str] = {}   # job.id → threadId

    async def start_session(self, job) -> None:
        proxy = _codex_server(self._codex_bin, self._codex_home)
        th = await proxy.proc.call("thread/start", {}, timeout=60.0)
        thread_id = ((th or {}).get("thread") or {}).get("id") or ""
        if not thread_id:
            raise RuntimeError("codex thread 创建失败")
        self._thread_of[job.id] = thread_id
        job.session_id = thread_id
        job.serve_url = f"codex-appserver://{self._codex_bin}"
        job.last_activity_ts = time.time()

    async def run_turn(self, job, text: str) -> TurnOutcome:
        proxy = _codex_server(self._codex_bin, self._codex_home)
        server = proxy.proc
        thread_id = self._thread_of.get(job.id) or job.session_id
        self._turn_inflight[job.id] = True
        self._aborting[job.id] = False
        job.last_activity_ts = time.time()
        try:
            idx0 = len(server.events)
            params: Dict[str, Any] = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": text}],
                "cwd": job.wt,
                "approvalPolicy": self._approval_policy,
                "sandbox": {"mode": self._sandbox_mode},
            }
            if self._model:
                params["model"] = self._model
            await server.call("turn/start", params, timeout=60.0)

            deadline = asyncio.get_event_loop().time() + job.turn_timeout
            err_msg, err_count = "", 0
            completed: Optional[dict] = None
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(1.5)
                if self._aborting.get(job.id):
                    raise RuntimeError("回合已被看门狗中止")
                if proxy.dead:
                    raise RuntimeError(f"codex 通道断流: {proxy.dead_reason}")
                for ev in server.events_since(idx0):
                    m = ev.get("method") or ""
                    job.last_activity_ts = time.time()   # 任意 notification 即活动
                    if m in self._DONE_HINTS:
                        completed = ev
                        break
                    if m == "error":
                        p = ev.get("params") or {}
                        e = p.get("error") or {}
                        err_msg = str(e.get("message") or json.dumps(e, ensure_ascii=False))
                        if not p.get("willRetry", True) or err_count >= 3:
                            raise RuntimeError(
                                f"codex 执行失败: {err_msg}（检查 codex login / 网络）")
                        err_count += 1
                if completed:
                    break
            else:
                raise RuntimeError(f"codex turn 未在 {job.turn_timeout:.0f}s 内完成")
            t = ((completed or {}).get("params") or {}).get("turn") or {}
            if (t.get("status") or "completed") != "completed":
                raise RuntimeError(str(t.get("error") or "turn 未完成")[:500])
            output = self._collect_text(server.events_since(idx0))
            return TurnOutcome(output=output, changed_files=_git_changed_files(job.wt))
        finally:
            self._turn_inflight[job.id] = False

    @staticmethod
    def _collect_text(events: list) -> str:
        """agentMessage/assistant 类 item 文本收集(排除回显 userMessage)。"""
        texts: list[str] = []
        for ev in events:
            p = ev.get("params") or {}
            item = p.get("item") or {}
            itype = item.get("type") or ""
            if "agent" not in itype and "assistant" not in itype:
                continue
            for c in item.get("content") or []:
                if isinstance(c, dict) and isinstance(c.get("text"), str):
                    texts.append(c["text"])
        return "".join(texts)[-8000:]

    async def probe(self, job) -> TurnProbe:
        proxy = _codex_server(self._codex_bin, self._codex_home)
        if proxy.dead:
            return TurnProbe("error", job.last_activity_ts, f"codex 通道断流: {proxy.dead_reason}")
        status = "busy" if self._turn_inflight.get(job.id) else "idle"
        return TurnProbe(status, job.last_activity_ts)

    async def abort(self, job) -> bool:
        self._aborting[job.id] = True
        thread_id = self._thread_of.get(job.id)
        if not thread_id:
            return False
        try:
            proxy = _codex_server(self._codex_bin, self._codex_home)
            await proxy.proc.call("turn/interrupt", {"threadId": thread_id}, timeout=15.0)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[codex-adapter] abort %s: %s", job.id, e)
            return False

    def dispose(self, job) -> None:
        self._turn_inflight.pop(job.id, None)
        self._aborting.pop(job.id, None)
        self._thread_of.pop(job.id, None)


# ─────────────────────────── 工厂 ───────────────────────────


def build_adapter(executor_type: str = "", executor_id: str = "",
                  config: Optional[Dict[str, Any]] = None) -> TurnAdapter:
    """executorType + 配置 → TurnAdapter; 未知/缺省回退 opencode(现网兼容)。"""
    cfg = dict(config or {})
    etype = (executor_type or "").strip()
    eid = (executor_id or "").strip()
    if etype == "cline-sdk":
        return ClineTurnAdapter(cfg, executor_id=eid or "cline")
    if etype == "codex-server":
        return CodexTurnAdapter(cfg, executor_id=eid or "codex")
    if etype == "remote-agent":
        raise RuntimeError(
            "remote-agent(远端分支协作模式)暂不支持交互式实施作业——该模式无本地 "
            "worktree 语义, 请使用本地执行器(opencode/cline/codex)。")
    cfg.setdefault("base_port", cfg.get("basePort") or 3478)
    return OpenCodeTurnAdapter(
        base_port=int(cfg.get("base_port") or 3478),
        auto_start=bool(cfg.get("auto_start", cfg.get("autoStart", True))),
        base_url=str(cfg.get("base_url") or cfg.get("baseUrl") or ""),
        opencode_bin=str(cfg.get("opencode_bin") or ""),
        executor_id=eid or "opencode")


def _git_changed_files(wt: str) -> list:
    """worktree 变更文件清单(git status 口径, adapter 共用)。"""
    import subprocess
    try:
        r = subprocess.run(["git", "add", "-A", "-N"], cwd=wt,
                           capture_output=True, text=True, check=False)
        if r.returncode != 0:
            return []
        r = subprocess.run(["git", "status", "--porcelain"], cwd=wt,
                           capture_output=True, text=True, check=False)
        return [ln[3:].strip() for ln in r.stdout.splitlines() if ln.strip()]
    except Exception:  # noqa: BLE001
        return []
