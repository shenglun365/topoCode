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
→ create_implement 经 build_adapter() 构造。缺省/未知类型显式报错(无静默降级)。
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

    async def steer(self, job, text: str) -> bool:
        """运行中会话注入转向提示（P4）；执行器不支持时返回 False（回退排队）。"""
        return False

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


def _opencode_headless_config(permission: str = "",
                              mcp_servers: Optional[dict] = None) -> str:
    """opencode 无头 serve 内联配置（OPENCODE_CONFIG_CONTENT, 不落 worktree）。

    社区坑对策:
    - 权限 "ask" 在无头模式无人应答 → 无限挂起: 一律显式 allow 白名单
      （worktree 隔离 + 验收越界检测兜底; opencode 无 deny 语义, readOnly
      由协作协议约束 + 验收简报把关）
    - MCP 冷启动超时: 每 server timeout 强制 >=60s
    """
    cfg: Dict[str, Any] = {
        "permission": {
            "*": "allow",
            "doom_loop": "allow",
            "external_directory": "allow",
        },
    }
    if permission and permission not in ("auto", "allow", ""):
        logger.info("[opencode] 权限配置 %r 在无头模式下强制为 allow（避免挂起）",
                    permission)
    if mcp_servers:
        mcp: Dict[str, Any] = {}
        for name, conf in mcp_servers.items():
            if isinstance(conf, dict):
                entry = dict(conf)
                try:
                    entry["timeout"] = max(int(entry.get("timeout") or 0), 60000)
                except (TypeError, ValueError):
                    entry["timeout"] = 60000
                mcp[str(name)] = entry
        if mcp:
            cfg["mcp"] = mcp
    return json.dumps(cfg, ensure_ascii=False)


class OpenCodeServeManager:
    """项目根 → serve 实例注册表（进程内单例，端口探活分配）。"""

    def __init__(self, opencode_bin: str = "", base_port: int = 3478, auto_start: bool = True,
                 permission: str = "", mcp_servers: Optional[dict] = None,
                 idle_timeout_ms: int = 3_600_000):
        self._bin = opencode_bin or shutil.which("opencode") or "opencode"
        self._base_port = base_port
        self._auto_start = auto_start
        self._permission = permission
        self._mcp_servers = mcp_servers if isinstance(mcp_servers, dict) else None
        # 空闲实例自动回收（社区坑: InstanceStore 永不释放; SDK 最低 1h）
        self._idle_timeout_ms = max(3_600_000, int(idle_timeout_ms))
        self._by_root: dict[str, ServeProc] = {}

    def _log_path(self, port: int) -> str:
        d = os.path.join(os.path.expanduser("~"), ".topocode", "runner")
        os.makedirs(d, exist_ok=True)
        # 按天切分（P4: 防 append 无限增长）
        return os.path.join(d, f"opencode-serve-{port}-{time.strftime('%Y%m%d')}.log")

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
        env = dict(os.environ)
        # 无头权限显式化（社区坑: serve 模式 "ask" 权限无人应答 → 无限挂起）:
        # 经 OPENCODE_CONFIG_CONTENT 内联注入, 不落 worktree 文件（不污染 git diff）
        cfg_content = _opencode_headless_config(self._permission, self._mcp_servers)
        if cfg_content:
            env["OPENCODE_CONFIG_CONTENT"] = cfg_content
        # 实例空闲回收（社区坑: serve 为每个访问目录建 InstanceStore 且永不释放）
        env.setdefault("OPENCODE_EXPERIMENTAL_INSTANCE_IDLE_TIMEOUT_MS",
                       str(int(self._idle_timeout_ms)))
        proc = subprocess.Popen(
            [self._bin, "serve", "--port", str(port), "--hostname", "127.0.0.1"],
            cwd=root, stdout=log, stderr=subprocess.STDOUT,
            env=env,
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
            stderr=open(os.path.join(run_dir,
                                     f"codex-appserver-{time.strftime('%Y%m%d')}.log"),
                        "ab"),  # noqa: SIM115
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

    无头化对策（spawn 时注入, 不落 worktree）:
    - 权限显式化: "ask" 权限在无头模式无人应答 → 无限挂起, 一律 allow 白名单
      （worktree 隔离 + 验收越界检测兜底）。
    - ⚠️ readOnly 边界降级: opencode 无 deny 语义——readOnly 作业靠协作协议
      提示词约束 + 验收简报越界把关（cline 用 toolPolicies 硬阻断、codex 用
      read-only 沙箱, 均强于此路径; 严格只读场景建议调度到 cline/codex）。
    - 会话丢失(404)自动重建重发; 实例空闲自动回收(InstanceStore 泄漏对策)。
    """

    def __init__(self, base_port: int = 3478, auto_start: bool = True,
                 base_url: str = "", opencode_bin: str = "", executor_id: str = "opencode",
                 permission: str = "", mcp_servers: Optional[dict] = None,
                 idle_timeout_ms: int = 3_600_000):
        self.executor_id = executor_id
        self.executor_type = "opencode"
        self._mgr = OpenCodeServeManager(base_port=base_port, auto_start=auto_start,
                                         opencode_bin=opencode_bin,
                                         permission=permission,
                                         mcp_servers=mcp_servers,
                                         idle_timeout_ms=idle_timeout_ms)
        self._base_url = (base_url or "").rstrip("/")
        self._sse_tasks: Dict[str, asyncio.Task] = {}   # job.id → task
        # 流式游标（P2: 全作业共享, 以 message:part 键隔离; 上限裁剪防膨胀）
        self._text_cursor: Dict[str, int] = {}
        self._tool_seen: set = set()

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
        流式(P2): text part 增量 diff → emit("text"); tool part 首见 → emit("tool")。
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
                        # ── 执行进展 + 流式(P2) ──
                        if ptype.startswith("message."):
                            msg = props.get("message") or props
                            mid = str(msg.get("id") or "") or f"_{len(msg_tools)}"
                            self._on_message_parts(job, mid, msg.get("parts") or [],
                                                   msg_tools)
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

    def _on_message_parts(self, job, mid: str, parts: list,
                          msg_tools: Dict[str, int]) -> None:
        """message parts 全量 → 工具计数 + 流式事件（text 增量/tool 首见）。

        独立方法便于单测：delta 以 (message.id, part 下标) 为游标键，
        parts 全量重放只发新增片段（幂等）。
        """
        for idx, p in enumerate(parts):
            if not isinstance(p, dict):
                continue
            ptype = str(p.get("type") or "")
            key = f"{mid}:{idx}"
            if ptype == "text":
                full = str(p.get("text") or "")
                seen = self._text_cursor.get(key, 0)
                if len(full) > seen:
                    job.emit("text", full[seen:])
                    self._text_cursor[key] = len(full)
            elif ptype == "tool":
                tools = msg_tools.get(mid, 0)
                # 工具计数峰值（原 progress 面保持）
                if idx + 1 > tools:
                    msg_tools[mid] = idx + 1
                if key not in self._tool_seen:
                    self._tool_seen.add(key)
                    name = str(p.get("tool") or p.get("toolName") or ptype)
                    job.emit("tool", f"▶ {name}".strip(), toolName=name)
        # 游标防膨胀：会话级键上限裁剪（保留最近）
        if len(self._text_cursor) > 4000:
            for k in list(self._text_cursor)[:2000]:
                self._text_cursor.pop(k, None)
        if len(self._tool_seen) > 4000:
            self._tool_seen = set(list(self._tool_seen)[-2000:])

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
            if r.status_code == 404:
                # 会话丢失（serve 重启/内存态清空）→ 重建 session 并重发当前指令
                logger.warning("[opencode-adapter] %s 会话丢失(404), 重建重发",
                               job.id)
                job.session_id = ""
                await self.start_session(job)
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

    # ── 内省（P3: 与 cline 内省面对齐; runner 能力分派自动生效）──

    async def read_messages(self, job, display: bool = True):
        """会话转写：GET /session/{id}/message → [{role, content}] 归一。

        opencode 消息形状可能是 {role, parts} 或 {info:{role}, parts}——双兼容。
        """
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(f"{job.serve_url}/session/{job.session_id}/message")
            r.raise_for_status()
            data = r.json() or []
        out = []
        for m in data if isinstance(data, list) else []:
            if not isinstance(m, dict):
                continue
            info = m.get("info") if isinstance(m.get("info"), dict) else {}
            role = str(m.get("role") or info.get("role") or "user")
            texts = []
            for p in (m.get("parts") or []):
                if isinstance(p, dict) and str(p.get("type") or "") == "text" \
                        and p.get("text"):
                    texts.append(str(p["text"]))
            out.append({"role": role, "content": "\n".join(texts)})
        return out

    async def update_model(self, job, model_id: str) -> bool:
        """会话内换模：记 job.model，下一回合 body.model 生效。"""
        job.model = model_id
        return True

    async def get_usage(self, job):
        """用量聚合：message tokens 字段（有则聚合，无则 None——能力分派兼容）。"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.get(f"{job.serve_url}/session/{job.session_id}/message")
                if r.status_code != 200:
                    return {"usage": None}
                data = r.json() or []
        except Exception:  # noqa: BLE001
            return {"usage": None}
        inp = out = 0
        found = False
        for m in data if isinstance(data, list) else []:
            if not isinstance(m, dict):
                continue
            info = m.get("info") if isinstance(m.get("info"), dict) else {}
            tk = m.get("tokens") or info.get("tokens")
            if isinstance(tk, dict):
                found = True
                inp += int(tk.get("input") or tk.get("inputTokens") or 0)
                out += int(tk.get("output") or tk.get("outputTokens") or 0)
        return {"usage": {"inputTokens": inp, "outputTokens": out} if found else None}


async def _persist_client():
    """SSE 长连接客户端工厂(async for 语义, 供断流重连)。"""
    yield httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))


# ─────────────────────────── cline SDK (embedded) ───────────────────────────


class _SidecarProcess:
    """cline sidecar v2（ClineCore 会话宿主）：共享单例、懒拉起、崩溃自动重启、
    请求-响应关联、按 sessionId 多路分发事件。"""

    def __init__(self, node_bin: str, script: str):
        self._node = node_bin or "node"
        self._script = script
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._session_handlers: Dict[str, Any] = {}  # sessionId → callable(params)
        self._global_handler = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def set_event_handler(self, handler) -> None:
        """全局兜底 handler（无 sessionId 的事件，如 ready）。"""
        self._global_handler = handler

    def set_session_handler(self, session_id: str, handler) -> None:
        self._session_handlers[session_id] = handler

    def clear_session_handler(self, session_id: str) -> None:
        self._session_handlers.pop(session_id, None)

    async def _start_locked(self) -> None:
        if self._proc and self._proc.returncode is None:
            return
        run_dir = os.path.join(os.path.expanduser("~"), ".topocode", "runner")
        os.makedirs(run_dir, exist_ok=True)
        self._proc = await asyncio.create_subprocess_exec(
            self._node, self._script,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=open(os.path.join(run_dir, f"cline-sidecar-{time.strftime('%Y%m%d')}.log"),
                        "ab"),  # noqa: SIM115
            limit=16 * 1024 * 1024,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
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
                elif msg.get("method") == "event":
                    params = msg.get("params") or {}
                    sid = str(params.get("sessionId") or "")
                    handler = self._session_handlers.get(sid) if sid else None
                    if handler is not None:
                        try:
                            handler(params)
                        except Exception:  # noqa: BLE001
                            pass
                    elif self._global_handler:
                        try:
                            self._global_handler(params)
                        except Exception:  # noqa: BLE001
                            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("[cline] sidecar read loop died: %s", e)
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("cline sidecar exited"))
        self._pending.clear()

    async def call(self, method: str, params: dict | None = None, timeout: float = 3600.0):
        async with self._lock:
            await self._start_locked()
        return await self._send_and_wait(method, params, timeout=timeout)


_CLINE_SIDECARS: Dict[str, _SidecarProcess] = {}   # (node:script) → 共享 sidecar


class ClineTurnAdapter(TurnAdapter):
    """cline SDK sidecar v2 适配（ClineCore 会话宿主）。

    会话语义：sessionId 即 ClineCore host 会话 id——真多回合（上下文由
    ClineCore 持久化保持），sessionRef 预置即复活。流式：sidecar 事件
    （text/tool/usage/approval/turn_outcome）逐段 job.emit 落事件环。
    sidecar 进程按 (node, script) 共享，多作业多会话复用。
    """

    _DEFAULT_SYSTEM_PROMPT = (
        "你在 TopoCode 管理的 git worktree 中工作，改动不会影响主工作区。"
        "写码前可用 topocode_asset_map 工具查询架构资产地图（如可用），确保修改符合架构边界。"
        "禁止 git push / 改动 worktree 之外的路径。"
        "回合收尾时必须调用 report_turn_outcome 工具汇报结局："
        "status=done 表示开发+单元测试+整体编译验收全部完成；"
        "status=need_input 表示需要用户操作/确认/澄清/补充。"
    )

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
        self._system_prompt = str(config.get("system_prompt") or "").strip()
        # models[]: architect 注册表 [{id,name,model,url,apiKey,maxTokens}]——按作业换模
        self._models = [m for m in (config.get("models") or [])
                        if isinstance(m, dict)]
        # 透传 per-tool 审批策略（越界确认机制：autoApprove=false → 审批桥）
        tp = config.get("tool_policies")
        self._tool_policies_extra = tp if isinstance(tp, dict) else {}
        # P5: MCP 注入（cline 侧为 list[McpServerSpec]; 与 opencode 的 dict 形状区分）
        self._mcp_servers = (config.get("mcp_servers")
                             if isinstance(config.get("mcp_servers"), list) else [])
        # P5: Teams（{enabled, teamName, agents:[{name, content}]}——agents 经
        # workspaceFiles 落盘 .cline/agents/，由 SDK workspace 加载面原生消费）
        teams = config.get("teams")
        self._teams = teams if isinstance(teams, dict) else {}
        self._arch_url = str(config.get("arch_url")
                             or os.environ.get("ARCH_BASE_URL", "http://127.0.0.1:3470"))
        self._arch_token = str(config.get("arch_token") or _default_token())
        self._turn_inflight: Dict[str, bool] = {}   # job.id → 回合进行中
        self._turn_outcome: Dict[str, dict] = {}    # job.id → 协议工具结局
        self._last_error: Dict[str, str] = {}       # job.id → 通道级错误

    # ── 共享 sidecar ──

    def _sidecar(self) -> _SidecarProcess:
        key = f"{self._node}:{self._script}"
        sc = _CLINE_SIDECARS.get(key)
        if sc is None:
            sc = _SidecarProcess(self._node, self._script)
            _CLINE_SIDECARS[key] = sc
        return sc

    # ── 模型解析（models[] 消费：按作业换模）──

    def _resolve_model(self, job) -> Dict[str, Any]:
        models = self._models
        entry: Dict[str, Any] = {}
        if job.model and models:
            for m in models:
                if job.model in (m.get("model"), m.get("name"), m.get("id")):
                    entry = m
                    break
        elif models:
            entry = models[0]
        model = str((entry or {}).get("model") or self._model_id or "")
        provider = self._provider_id
        if "/" in model:
            provider, model = model.split("/", 1)
        return {
            "providerId": provider or str((entry or {}).get("provider") or "openai-compatible"),
            "modelId": model,
            "apiKey": str((entry or {}).get("apiKey") or self._api_key or ""),
            "baseUrl": str((entry or {}).get("url") or self._base_url or ""),
        }

    # ── boundaries → toolPolicies（只读作业硬阻断写类工具）──

    @staticmethod
    def _tool_policies(job) -> Dict[str, Any]:
        policies: Dict[str, Any] = {}
        boundaries = getattr(job, "boundaries", None) or {}
        if boundaries.get("readOnly"):
            for t in ("editor", "apply_patch", "run_commands"):
                policies[t] = {"enabled": False}
        return policies

    # ── 事件流（sidecar → job.emit）──

    def _on_event(self, job, params: dict) -> None:
        sid = str(params.get("sessionId") or "")
        if sid and job.session_id and sid != job.session_id:
            return
        t = str(params.get("type") or "")
        job.last_activity_ts = time.time()
        if t == "text":
            job.emit("text", str(params.get("text") or ""))
        elif t == "text_end":
            pass
        elif t == "tool_start":
            job.emit("tool", f"▶ {params.get('toolName') or ''}".strip(),
                     toolName=params.get("toolName"))
        elif t == "tool_end":
            job.emit("tool", f"✓ {params.get('toolName') or ''}".strip(),
                     toolName=params.get("toolName"))
        elif t == "usage":
            job.emit("usage", "", inputTokens=params.get("inputTokens"),
                     outputTokens=params.get("outputTokens"),
                     cost=params.get("cost"))
        elif t == "notice":
            if params.get("reason") == "mistake_limit":
                self._last_error[job.id] = str(params.get("message") or "")[:400]
            job.emit("notice", str(params.get("message") or ""),
                     reason=params.get("reason"))
        elif t == "turn_outcome":
            self._turn_outcome[job.id] = {
                "status": params.get("status"),
                "summary": params.get("summary"),
                "changedFiles": params.get("changedFiles"),
                "notes": params.get("notes"),
            }
            job.emit("turn_outcome", str(params.get("summary") or ""),
                     status=params.get("status"))
        elif t == "approval_request":
            job.emit("approval_request",
                     f"工具 {params.get('toolName')} 等待确认",
                     requestId=params.get("requestId"),
                     toolName=params.get("toolName"),
                     toolInput=params.get("input"))
        elif t == "team":
            # P5: 团队进度（进度面汇总, 不单独落会话消息）
            payload = params.get("payload") or {}
            summary = str(payload.get("summary") or params.get("summary") or "")[:200]
            job.emit("team", summary,
                     teamName=payload.get("teamName") or params.get("teamName") or "",
                     lifecycle=params.get("lifecycle") or "")
        elif t in ("mcp_ready", "mcp_failed"):
            job.emit("mcp", f"{params.get('server')}: "
                     f"{'就绪' if t == 'mcp_ready' else '注入失败(已跳过)'}",
                     server=params.get("server"),
                     ok=t == "mcp_ready",
                     message=params.get("message") or "")
        elif t == "error":
            msg = str(params.get("message") or "")[:400]
            if msg and not params.get("recoverable", True):
                self._last_error[job.id] = msg

    # ── TurnAdapter 协议 ──

    async def start_session(self, job) -> None:
        sc = self._sidecar()
        await sc.ensure()
        sc.set_session_handler(job.session_id or job.id,
                               lambda p, _j=job: self._on_event(_j, p))
        model = self._resolve_model(job)
        model_cfg: Dict[str, Any] = {
            "providerId": model["providerId"],
            "modelId": model["modelId"],
        }
        if model["apiKey"]:
            model_cfg["apiKey"] = model["apiKey"]
        if model["baseUrl"]:
            model_cfg["baseUrl"] = model["baseUrl"]
        params: Dict[str, Any] = {
            "sessionId": job.session_id or job.id,
            "cwd": job.wt,
            "model": model_cfg,
            "maxIterations": self._max_iterations,
            "systemPrompt": self._system_prompt or self._DEFAULT_SYSTEM_PROMPT,
            "toolPolicies": {**self._tool_policies(job), **self._tool_policies_extra},
            "protocolTools": True,
            "checkpointEnabled": True,
            "archUrl": self._arch_url,
            "archToken": self._arch_token,
            "projectId": getattr(job, "project_id", "") or "",
        }
        # P5: MCP / Teams
        if self._mcp_servers:
            params["mcpServers"] = self._mcp_servers
        if self._teams.get("enabled"):
            params["teams"] = {
                "enabled": True,
                **({"teamName": str(self._teams["teamName"])}
                   if self._teams.get("teamName") else {}),
            }
        await sc.call("session/start", params, timeout=60.0)
        job.session_id = job.session_id or job.id
        job.serve_url = f"sidecar://{self.executor_id}"
        job.last_activity_ts = time.time()

    async def run_turn(self, job, text: str) -> TurnOutcome:
        self._turn_inflight[job.id] = True
        self._turn_outcome.pop(job.id, None)
        job.last_activity_ts = time.time()
        try:
            sc = self._sidecar()
            result = await sc.call(
                "turn/send",
                {"sessionId": job.session_id or job.id, "prompt": text,
                 "timeoutMs": int(job.turn_timeout * 1000)},
                timeout=job.turn_timeout + 120.0)
            job.last_activity_ts = time.time()
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error")
                                       or f"cline 回合失败(status={result.get('status')})"))
            # sidecar v2 字段: outputText（兼容 output 旧键）
            output = str(result.get("outputText") or result.get("output") or "")
            # 协议工具结局 → v1 文本标记（implement 解析兼容）
            outcome = result.get("turnOutcome") or {}
            if outcome.get("status") == "done" and "[[IMPLEMENT_DONE]]" not in output:
                output += f"\n[[IMPLEMENT_DONE]] {outcome.get('summary') or ''}".rstrip()
            elif outcome.get("status") == "need_input" and "[[NEED_INPUT]]" not in output:
                output += f"\n[[NEED_INPUT]] {outcome.get('summary') or ''}".rstrip()
            return TurnOutcome(output=output,
                               changed_files=_git_changed_files(job.wt))
        finally:
            self._turn_inflight[job.id] = False

    async def probe(self, job) -> TurnProbe:
        sc = self._sidecar()
        if not sc.alive:
            return TurnProbe("error", job.last_activity_ts,
                             self._last_error.get(job.id) or "cline sidecar 进程未运行")
        status = "busy" if self._turn_inflight.get(job.id) else "idle"
        return TurnProbe(status, job.last_activity_ts,
                         self._last_error.get(job.id, ""))

    async def abort(self, job) -> bool:
        try:
            await self._sidecar().call(
                "session/abort",
                {"sessionId": job.session_id or job.id, "reason": "aborted by runner"},
                timeout=15.0)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[cline-adapter] abort %s: %s", job.id, e)
            return False

    async def steer(self, job, text: str) -> bool:
        """P4: steer 直达——sidecar turn/steer（SDK pending 入队优先投递）。"""
        try:
            res = await self._sidecar().call(
                "turn/steer",
                {"sessionId": job.session_id or job.id, "prompt": text},
                timeout=30.0)
            return bool(res.get("ok"))
        except Exception as e:  # noqa: BLE001
            logger.warning("[cline-adapter] steer %s: %s", job.id, e)
            return False

    async def respond_approval(self, job, request_id: str, approved: bool,
                               reason: str = "") -> bool:
        """越界审批桥：批准/拒绝 sidecar approval_request。"""
        try:
            await self._sidecar().call(
                "approval/respond",
                {"requestId": request_id, "approved": approved,
                 **({"reason": reason} if reason else {})},
                timeout=15.0)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[cline-adapter] approval %s: %s", job.id, e)
            return False

    # ── 内省转发（runner 端点经 job.adapter 分派；T5）──

    async def read_messages(self, job, display: bool = True):
        sc = await self._sidecar_checked(job)
        return await sc.call("session/messages",
                             {"sessionId": job.session_id or job.id, "display": display},
                             timeout=30.0)

    async def get_usage(self, job):
        sc = await self._sidecar_checked(job)
        return await sc.call("session/usage",
                             {"sessionId": job.session_id or job.id}, timeout=15.0)

    async def update_model(self, job, model_id: str):
        sc = await self._sidecar_checked(job)
        return await sc.call("session/model",
                             {"sessionId": job.session_id or job.id, "modelId": model_id},
                             timeout=15.0)

    async def compare_checkpoint(self, job, run_count: int):
        sc = await self._sidecar_checked(job)
        return await sc.call("checkpoint/compare",
                             {"sessionId": job.session_id or job.id,
                              "runCount": int(run_count)}, timeout=60.0)

    async def restore_checkpoint(self, job, run_count: int, options: Optional[dict] = None):
        sc = await self._sidecar_checked(job)
        return await sc.call("session/restore",
                             {"sessionId": job.session_id or job.id,
                              "runCount": int(run_count),
                              **({"options": options} if options else {})},
                             timeout=120.0)

    async def list_pending_prompts(self, job):
        """挂起提示清单（queue/steer 排队面）。"""
        sc = await self._sidecar_checked(job)
        return await sc.call("session/pending",
                             {"sessionId": job.session_id or job.id}, timeout=15.0)

    async def proceed_while_running(self, job, tool_call_id: Optional[str] = None):
        """长命令放行（run_commands 执行中后台继续; 无运行中命令返回 None）。"""
        sc = await self._sidecar_checked(job)
        res = await sc.call("session/proceed",
                            {"sessionId": job.session_id or job.id,
                             **({"toolCallId": tool_call_id} if tool_call_id else {})},
                            timeout=30.0)
        return res.get("exitCode")

    async def _sidecar_checked(self, job) -> _SidecarProcess:
        sc = self._sidecar()
        await sc.ensure()
        if not sc.alive:
            raise RuntimeError("cline sidecar 未运行")
        return sc

    def dispose(self, job) -> None:
        self._turn_inflight.pop(job.id, None)
        sc = self._sidecar()
        sc.clear_session_handler(job.session_id or job.id)
        # 会话优雅终止（尽力而为，不阻塞作业收口）；sidecar 进程保留共享
        try:
            asyncio.get_event_loop().create_task(sc.call(
                "session/stop", {"sessionId": job.session_id or job.id}, timeout=10.0))
        except Exception:  # noqa: BLE001
            pass


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

    ⚠️ 能力降级标注（对比 cline 路径）:
    - 完成信号: codex turn API 无自定义工具注入——[[NEED_INPUT]]/[[IMPLEMENT_DONE]]
      文本标记契约(_COLLAB_PROTOCOL 注入 instruction)是唯一完成信号,
      守约率依赖模型; 完成判定兜底为 waiting_input。
    - stdin 挂起坑: 本适配走 app-server(非 `codex exec` CLI), 天然免疫
      "Reading additional input from stdin..." 挂起。
    - 速率限制: 错误重试窗口 2s/4s 退避 2 次, 超限快速失败交 architect 泵 lost。
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
        self._usage_of: Dict[str, Any] = {}    # job.id → 最近 turn usage（P3）
        self._thread_start: Dict[str, int] = {}  # job.id → thread 事件起点（P3 转写）

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
        self._thread_start[job.id] = len(proxy.proc.events)   # P3: 转写起点
        job.last_activity_ts = time.time()

    async def get_usage(self, job):
        """最近 turn 的 usage（turn/completed 事件采集；无则 None）。"""
        usage = self._usage_of.get(job.id)
        if not isinstance(usage, dict):
            return {"usage": None}
        inp = int(usage.get("inputTokens") or usage.get("input_tokens") or 0)
        out = int(usage.get("outputTokens") or usage.get("output_tokens") or 0)
        cost = usage.get("totalCost") or usage.get("cost")
        return {"usage": {"inputTokens": inp, "outputTokens": out,
                          **({"totalCost": cost} if cost is not None else {})}}

    async def read_messages(self, job, display: bool = True):
        """thread 转写（近似口径）：events ring 中 agent 类 item → 文本列表。"""
        proxy = _codex_server(self._codex_bin, self._codex_home)
        start = self._thread_start.get(job.id, 0)
        events = proxy.proc.events_since(start)
        out: list = []
        for ev in events:
            p = ev.get("params") or {}
            item = p.get("item") or {}
            if not isinstance(item, dict):
                continue
            itype = str(item.get("type") or "")
            if "agent" not in itype and "assistant" not in itype:
                continue
            text = "".join(
                c.get("text", "") for c in (item.get("content") or [])
                if isinstance(c, dict) and isinstance(c.get("text"), str))
            if text.strip():
                out.append({"role": "assistant", "content": text})
        return out

    async def run_turn(self, job, text: str) -> TurnOutcome:
        proxy = _codex_server(self._codex_bin, self._codex_home)
        server = proxy.proc
        thread_id = self._thread_of.get(job.id) or job.session_id
        self._turn_inflight[job.id] = True
        self._aborting[job.id] = False
        job.last_activity_ts = time.time()
        # P2: 流式游标（每回合重置）
        self._stream_cursor: Dict[str, int] = {}
        self._stream_tools: set = set()
        try:
            idx0 = len(server.events)
            # P2: readOnly 边界 → 原生沙箱只读（codex 原生支持, 硬于提示词约束）
            sandbox_mode = self._sandbox_mode
            if (getattr(job, "boundaries", None) or {}).get("readOnly"):
                sandbox_mode = "read-only"
            params: Dict[str, Any] = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": text}],
                "cwd": job.wt,
                "approvalPolicy": self._approval_policy,
                "sandbox": {"mode": sandbox_mode},
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
                        # P3: 速率限制退避（2s/4s, 最多 2 次——给服务端恢复窗口）
                        if err_count <= 2:
                            await asyncio.sleep(2.0 * err_count)
                    else:
                        self._stream_codex_item(job, ev)   # P2 流式增量
                if completed:
                    break
            else:
                raise RuntimeError(f"codex turn 未在 {job.turn_timeout:.0f}s 内完成")
            t = ((completed or {}).get("params") or {}).get("turn") or {}
            if (t.get("status") or "completed") != "completed":
                raise RuntimeError(str(t.get("error") or "turn 未完成")[:500])
            if isinstance(t.get("usage"), dict):
                self._usage_of[job.id] = t["usage"]   # P3: 用量采集
            output = self._collect_text(server.events_since(idx0))
            return TurnOutcome(output=output, changed_files=_git_changed_files(job.wt))
        finally:
            self._turn_inflight[job.id] = False

    def _stream_codex_item(self, job, ev: dict) -> None:
        """item 通知 → 流式事件（agent 文本增量 / 工具首见）。

        独立方法便于单测：以 item.id 为游标键, item 全量重放只发新增（幂等）。
        """
        p = ev.get("params") or {}
        item = p.get("item") or {}
        if not isinstance(item, dict):
            return
        iid = str(item.get("id") or "")
        itype = str(item.get("type") or "")
        if ("agent" in itype or "assistant" in itype) and iid:
            full = "".join(
                c.get("text", "") for c in (item.get("content") or [])
                if isinstance(c, dict) and isinstance(c.get("text"), str))
            seen = self._stream_cursor.get(iid, 0)
            if len(full) > seen:
                job.emit("text", full[seen:])
                self._stream_cursor[iid] = len(full)
        elif iid and any(k in itype.lower() for k in
                         ("command", "filechange", "tool", "mcp")) \
                and iid not in self._stream_tools:
            self._stream_tools.add(iid)
            name = str(item.get("command") or item.get("tool") or itype)
            job.emit("tool", f"▶ {name}".strip(), toolName=name)

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


async def shutdown_executors() -> None:
    """runner 进程退出钩子：终止共享 sidecar/app-server（P4 防孤儿进程）。"""
    for key, sc in list(_CLINE_SIDECARS.items()):
        try:
            await sc.kill()
            logger.info("[shutdown] cline sidecar killed (%s)", key)
        except Exception:  # noqa: BLE001
            pass
    _CLINE_SIDECARS.clear()
    for key, proxy in list(_CODEX_SERVERS.items()):
        try:
            await proxy.proc.kill()
            logger.info("[shutdown] codex app-server killed (%s)", key)
        except Exception:  # noqa: BLE001
            pass
    _CODEX_SERVERS.clear()


# 执行器类型别名归一(与 architect 侧 agent_executors 单源语义一致)
_TYPE_ALIASES = {"cline": "cline-sdk", "codex": "codex-server"}
_SUPPORTED_LOCAL = ("opencode", "cline-sdk", "codex-server")


def build_adapter(executor_type: str = "", executor_id: str = "",
                  config: Optional[Dict[str, Any]] = None) -> TurnAdapter:
    """executorType + 配置 → TurnAdapter。

    无静默降级(cv-153 教训: 指定 cline 被静默换成 opencode 跑):
    - 别名归一: cline→cline-sdk / codex→codex-server;
    - 未知/空类型 → RuntimeError 显式失败(含支持清单), 由 /api/implement
      以 400 返回 → architect 任务 failed 原文回执。"""
    cfg = dict(config or {})
    etype = _TYPE_ALIASES.get((executor_type or "").strip(),
                              (executor_type or "").strip())
    eid = (executor_id or "").strip()
    if etype == "cline-sdk":
        return ClineTurnAdapter(cfg, executor_id=eid or "cline")
    if etype == "codex-server":
        return CodexTurnAdapter(cfg, executor_id=eid or "codex")
    if etype == "remote-agent":
        raise RuntimeError(
            "remote-agent(远端分支协作模式)暂不支持交互式实施作业——该模式无本地 "
            "worktree 语义, 请使用本地执行器(opencode/cline/codex)。")
    if etype != "opencode":
        raise RuntimeError(
            f"未知执行器类型: {executor_type or '(空)'}——支持: "
            f"{'/'.join(_SUPPORTED_LOCAL)}。请在「执行器配置」修正类型后重试, "
            "系统不做静默降级。")
    cfg.setdefault("base_port", cfg.get("basePort") or 3478)
    return OpenCodeTurnAdapter(
        base_port=int(cfg.get("base_port") or 3478),
        auto_start=bool(cfg.get("auto_start", cfg.get("autoStart", True))),
        base_url=str(cfg.get("base_url") or cfg.get("baseUrl") or ""),
        opencode_bin=str(cfg.get("opencode_bin") or ""),
        executor_id=eid or "opencode",
        permission=str(cfg.get("permission") or "auto"),
        mcp_servers=cfg.get("mcp_servers") if isinstance(cfg.get("mcp_servers"), dict) else None,
        idle_timeout_ms=int(cfg.get("idle_timeout_ms") or 3_600_000))


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
