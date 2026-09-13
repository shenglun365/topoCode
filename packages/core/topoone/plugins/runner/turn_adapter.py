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
import shutil
import subprocess
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



# ────────────────── 执行器进程管理(自包含, executors/ 已退役) ──────────────────

HEALTH_PATH = "/global/health"


class ServeProc:
    """按项目根托管的 opencode serve 进程。"""

    def __init__(self, root: str, url: str, port: int):
        self.root = os.path.abspath(root)
        self.url = url
        self.port = port
        self.proc: Optional[subprocess.Popen] = None  # None = 外部已起的 serve
        self.created_at = time.time()


class OpenCodeServeManager:
    """项目根 → serve 实例注册表（进程内单例，端口探活分配）。"""

    def __init__(self, opencode_bin: str = "", base_port: int = 3478, auto_start: bool = True):
        self._bin = opencode_bin or shutil.which("opencode") or "opencode"
        self._base_port = base_port
        self._auto_start = auto_start
        self._by_root: dict[str, ServeProc] = {}

    def _log_path(self, port: int) -> str:
        d = os.path.join(os.path.expanduser("~"), ".topocode", "runner")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"opencode-serve-{port}.log")

    async def _healthy(self, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(f"{url}{HEALTH_PATH}")
                return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def _find_port(self) -> int:
        for off in range(0, 24):
            port = self._base_port + off
            if await self._healthy(f"http://127.0.0.1:{port}"):
                continue  # 已被占用（可能是别的项目的 serve）
            return port
        return self._base_port

    async def ensure(self, root: str) -> ServeProc:
        root = os.path.abspath(root or os.getcwd())
        sp = self._by_root.get(root)
        if sp and await self._healthy(sp.url):
            return sp
        if sp and sp.proc is not None and sp.proc.poll() is None:
            # 进程在但健康检查未过：给一次等待
            for _ in range(10):
                if await self._healthy(sp.url):
                    return sp
                await asyncio.sleep(1.0)
        # 拉起（或复用已健康的外部 serve）；候选端口被占/启动失败自动换下一个
        port = await self._find_port()
        url = f"http://127.0.0.1:{port}"
        if not await self._healthy(url) and self._auto_start:
            last_err = ""
            for off in range(0, 24):
                port = self._base_port + off
                url = f"http://127.0.0.1:{port}"
                if await self._healthy(url):
                    continue  # 已被占用（可能是别的项目的 serve）
                try:
                    return await self._spawn(root, port, url)
                except Exception as e:  # noqa: BLE001
                    last_err = f"port {port}: {e}"
            raise RuntimeError(f"opencode serve 启动失败 root={root}: {last_err}")
        if not await self._healthy(url):
            raise RuntimeError(f"opencode serve 不可达 {url} 且未启用自动拉起")
        # 外部 serve 可能属于别的项目根——复用会串工作区。注册表未命中(或旧条目
        # 进程已死)时一律不复用未知 serve, 走自动拉起换端口
        if (sp is None or (sp.proc is not None and sp.proc.poll() is not None)) \
                and self._auto_start:
            for off in range(0, 24):
                port2 = self._base_port + off
                url2 = f"http://127.0.0.1:{port2}"
                if await self._healthy(url2):
                    continue
                return await self._spawn(root, port2, url2)
            raise RuntimeError(f"opencode serve 无可用端口 root={root}")
        sp = sp or ServeProc(root, url, port)
        self._by_root[root] = sp
        return sp

    async def _spawn(self, root: str, port: int, url: str) -> ServeProc:
        log = open(self._log_path(port), "ab")  # noqa: SIM115
        proc = subprocess.Popen(
            [self._bin, "serve", "--port", str(port), "--hostname", "127.0.0.1"],
            cwd=root, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        sp = ServeProc(root, url, port)
        sp.proc = proc
        for _ in range(30):
            if await self._healthy(url):
                self._by_root[root] = sp
                logger.info("[opencode] serve started pid=%s port=%s root=%s",
                            proc.pid, port, root)
                return sp
            if proc.poll() is not None:
                break
            await asyncio.sleep(1.0)
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"opencode serve 启动失败 port={port} root={root}（见 {self._log_path(port)}）")

    def dispose_root(self, root: str) -> None:
        """释放该根的 serve 实例(probe worktree 用完即清，防实例堆积)。"""
        sp = self._by_root.pop(root, None)
        if sp is None:
            return
        proc = getattr(sp, "proc", None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        logger.info("[opencode] serve disposed root=%s", root)


_MANAGER: Optional[OpenCodeServeManager] = None


def _default_token() -> str:
    for p in (os.environ.get("TOPOCODE_TOKEN_FILE"),
              os.path.join(os.path.expanduser("~"), ".topocode", "token")):
        if p and os.path.isfile(p):
            try:
                return open(p).read().strip()
            except Exception:  # noqa: BLE001
                pass
    return ""


def _default_sidecar_script() -> str:
    """sidecar 脚本默认路径: turn_adapter → runner → plugins → topoone → core
    → packages → 仓库根/packages/agent-sidecar/dist/index.js。
    config 未显式携带时回退(architect 侧注册表默认值为空串)。"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
    return os.path.join(root, "agent-sidecar", "dist", "index.js")


class _SidecarProcess:
    """单例 sidecar 进程：懒拉起、崩溃自动重启、请求-响应关联。"""

    def __init__(self, node_bin: str, script: str):
        self._node = node_bin or "node"
        self._script = script
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._event_handler = None  # callable(params)

    def set_event_handler(self, handler) -> None:
        self._event_handler = handler

    async def _start_locked(self) -> None:
        if self._proc and self._proc.returncode is None:
            return
        run_dir = os.path.join(os.path.expanduser("~"), ".topocode", "runner")
        os.makedirs(run_dir, exist_ok=True)
        self._proc = await asyncio.create_subprocess_exec(
            self._node, self._script,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=open(os.path.join(run_dir, "cline-sidecar.log"), "ab"),  # noqa: SIM115
            limit=16 * 1024 * 1024,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        # 等 ready 事件（直接内发，避免与 ensure 的锁重入死锁）
        try:
            await asyncio.wait_for(self._send_and_wait("ping"), timeout=30.0)
        except Exception as e:  # noqa: BLE001
            await self.kill()
            raise RuntimeError(
                f"cline sidecar 启动失败: {str(e) or type(e).__name__} "
                f"(script={self._script})") from e
        logger.info("[cline] sidecar started pid=%s", self._proc.pid)

    async def _send_and_wait(self, method: str, params: dict | None = None,
                             timeout: float = 3600.0):
        """假定进程已就绪的裸请求（不经过 ensure/锁）。"""
        if not self._proc or self._proc.returncode is not None or not self._proc.stdin:
            raise RuntimeError("sidecar not running")
        self._req_id += 1
        rid = self._req_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        payload = {"id": rid, "method": method, "params": params or {}}
        self._proc.stdin.write((json.dumps(payload) + "\n").encode())
        await self._proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=timeout)

    async def ensure(self) -> None:
        async with self._lock:
            await self._start_locked()

    async def kill(self) -> None:
        proc, self._proc = self._proc, None
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("sidecar restarting"))
        self._pending.clear()
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    async def _read_loop(self) -> None:
        proc = self._proc
        try:
            while proc and proc.returncode is None:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if "id" in msg and (msg.get("result") is not None or msg.get("error") is not None):
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if msg.get("error"):
                            fut.set_exception(RuntimeError(msg["error"].get("message", "error")))
                        else:
                            fut.set_result(msg.get("result"))
                elif msg.get("method") == "event" and self._event_handler:
                    try:
                        self._event_handler(msg.get("params") or {})
                    except Exception:  # noqa: BLE001
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("[cline] sidecar read loop died: %s", e)
        # 进程退出：使所有挂起请求失败，触发上层重启
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("cline sidecar exited"))
        self._pending.clear()

    async def call(self, method: str, params: dict | None = None, timeout: float = 3600.0):
        async with self._lock:
            await self._start_locked()
        return await self._send_and_wait(method, params, timeout=timeout)


_EVENT_DONE_HINTS = ("turn/completed", "turn/failed", "turn/cancelled")


class _AppServerProcess:
    """常驻 codex app-server 子进程（行分隔 JSON-RPC）。"""

    def __init__(self, codex_bin: str, cwd: str, codex_home: str = ""):
        self._bin = codex_bin
        self._cwd = cwd
        self._codex_home = os.path.expanduser(codex_home) if codex_home else ""
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.events: list[dict] = []  # 最近事件（ring）
        self._waiters: list[tuple[str, asyncio.Event]] = []
        # 通道状态(看门狗/适配层探测): read loop 退出即断流
        self.dead: bool = False
        self.dead_reason: str = ""

    async def _start_locked(self) -> None:
        if self._proc and self._proc.returncode is None:
            return
        env = dict(os.environ)
        if self._codex_home:
            os.makedirs(self._codex_home, exist_ok=True)
            env["CODEX_HOME"] = self._codex_home  # 多实例隔离（各自 config.toml 指向不同模型）
        run_dir = os.path.join(os.path.expanduser("~"), ".topocode", "runner")
        os.makedirs(run_dir, exist_ok=True)
        self._proc = await asyncio.create_subprocess_exec(
            self._bin, "app-server",
            cwd=self._cwd, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=open(os.path.join(run_dir, "codex-appserver.log"), "ab"),  # noqa: SIM115
            limit=16 * 1024 * 1024,
        )
        self._reader = asyncio.create_task(self._read_loop())
        try:
            await asyncio.wait_for(self._send_and_wait("initialize", {
                "clientInfo": {"name": "topoone-runner", "title": "TopoOne Runner",
                               "version": "0.1.0"}}), timeout=30.0)
        except Exception as e:  # noqa: BLE001
            await self.kill()
            raise RuntimeError(f"codex app-server 启动失败: {e}") from e
        logger.info("[codex] app-server started pid=%s", self._proc.pid)

    async def _send_and_wait(self, method: str, params: dict | None = None,
                             timeout: float = 3600.0):
        if not self._proc or self._proc.returncode is not None or not self._proc.stdin:
            raise RuntimeError("codex app-server not running")
        self._req_id += 1
        rid = self._req_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        self._proc.stdin.write((json.dumps(payload) + "\n").encode())
        await self._proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=timeout)

    async def call(self, method: str, params: dict | None = None,
                   timeout: float = 3600.0):
        async with self._lock:
            await self._start_locked()
        return await self._send_and_wait(method, params, timeout=timeout)

    async def _read_loop(self) -> None:
        proc = self._proc
        try:
            while proc and proc.returncode is None:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if msg.get("id") is not None and ("result" in msg or "error" in msg):
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(RuntimeError(
                                str((msg["error"] or {}).get("message") or msg["error"])))
                        else:
                            fut.set_result(msg.get("result"))
                elif msg.get("method"):
                    ev = {"method": msg["method"], "params": msg.get("params") or {}}
                    self.events.append(ev)
                    if len(self.events) > 4000:
                        del self.events[:2000]
                    for m, w in self._waiters:
                        if m == ev["method"]:
                            w.set()
        except asyncio.CancelledError:
            self.dead = True
            self.dead_reason = "read loop cancelled"
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[codex] read loop died: %s", e)
            self.dead = True
            self.dead_reason = str(e)[:300] or "read loop died"
        else:
            # while 正常退出(stdout EOF/进程结束) → 通道断流
            self.dead = True
            self.dead_reason = "app-server stdout EOF"
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("codex app-server exited"))
        self._pending.clear()

    def wait_event(self, method: str, start_idx: int) -> asyncio.Event:
        """注册等待某事件（从 start_idx 之后的新事件）。"""
        ev = asyncio.Event()
        self._waiters.append((method, ev))
        return ev

    def events_since(self, idx: int) -> list[dict]:
        return self.events[idx:]

    async def kill(self) -> None:
        proc, self._proc = self._proc, None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("codex app-server restarting"))
        self._pending.clear()
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass



# ─────────────────────────── opencode serve ───────────────────────────


class OpenCodeTurnAdapter(TurnAdapter):
    """opencode serve 会话适配(本地托管或外部 baseUrl)。

    活动信号: 常驻 SSE GET /event(全局流, 按 properties.sessionID 过滤),
    message.*/session.* 事件刷新 last_activity_ts; 断流自动重连, 重连间隙
    由 GET /session/status 快照兜底。
    """

    def __init__(self, base_port: int = 3478, auto_start: bool = True,
                 base_url: str = "", opencode_bin: str = "", executor_id: str = "opencode"):
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
        if job.session_id:
            # 子会话复活: 复用执行器原生 session(消息历史在执行器侧保持)
            self._start_sse(job)
            return
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
        """常驻 SSE 订阅: 任意会话事件刷新 job.last_activity_ts; 错误记 job.last_error。

        执行进展(工具调用计数): message.updated 事件携带消息全量 parts——
        按 message.id 记每条消息的工具 part 峰值, 汇总为作业级工具数;
        30s 或新工具时 emit("progress") → 事件环 → architect 泵 → 前端进展 chip。
        解析防御: 字段缺失时降级为事件活动计数, 不影响看门狗。
        """
        stop: asyncio.Event = job.sse_stop
        url = job.serve_url
        msg_tools: Dict[str, int] = {}      # message.id → 该消息工具 part 峰值
        last_emit_ts = 0.0
        last_tool_count = -1
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
                        # ── 执行进展: 工具调用计数(每消息 parts 全量, 按 id 取峰值去重) ──
                        if ptype.startswith("message."):
                            msg = props.get("message") or props
                            mid = str(msg.get("id") or "") or f"_{len(msg_tools)}"
                            tools = 0
                            for p in (msg.get("parts") or []):
                                if str(p.get("type") or "") == "tool":
                                    tools += 1
                            if tools > msg_tools.get(mid, 0):
                                msg_tools[mid] = tools
                            now = time.time()
                            total = sum(msg_tools.values())
                            if total != last_tool_count and \
                                    (total > last_tool_count + 4 or now - last_emit_ts > 30):
                                last_tool_count = total
                                last_emit_ts = now
                                job.emit("progress", "", toolCount=total,
                                         msgCount=len(msg_tools))
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
        self.executor_id = executor_id
        self.executor_type = "cline-sdk"
        self._node = str(config.get("node_bin") or "node")
        self._script = (str(config.get("sidecar_script") or "").strip()
                        or _default_sidecar_script())
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
        # cline 语义: taskId 即会话; 预置 session_id(复活)=续用既有任务上下文
        job.session_id = job.session_id or job.id
        job.serve_url = f"sidecar://{self.executor_id}"

    async def run_turn(self, job, text: str) -> TurnOutcome:
        self._turn_inflight[job.id] = True
        job.last_activity_ts = time.time()
        try:
            sc = self._sidecar()
            params: Dict[str, Any] = {
                "taskId": job.session_id or job.id, "prompt": text, "cwd": job.wt,
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
        if job.session_id:
            # 子会话复活: 复用既有 threadId 续线程(turn 会续在该线程上)
            self._thread_of[job.id] = job.session_id
        else:
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
