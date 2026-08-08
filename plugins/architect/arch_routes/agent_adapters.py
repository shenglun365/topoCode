"""Coding-agent 适配器层(通用成交契约 + 注册表)。

设计目标: 让 `AgentInstancePool`(agent_server.py)、连接配置(agent_config.py)、
适配清单(agent.py)、WS 任务流(websocket.py) 不再硬编码某个引擎, 而是通过
`AgentAdapter` 抽象接入。当前仅实现 **opencode**(server 模式), 其余引擎
(cline/codex/...) 后续注册新类即可, 接口侧无需改动。

每个 adapter 提供六类能力:
  - 安装/适配探测   env_check()   (本机可执行 + 版本 + 配置)
  - 连通性探测       probe(cfg)    (真实 HTTP 探测 + 模型/连接提供商列表)
  - 进程面           spawn/env     (managed 启动命令 -> opencode serve)
                    health(base)   (健康探测)
  - 会话面           make_client → AgentSession(create/send/abort)
  - 流式面           event_stream(...) → 归一化「前端 WS」事件
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4096
DEFAULT_USERNAME = "opencode"


def _b64(x: str) -> str:
    return base64.b64encode(x.encode()).decode()


def json_loads(s):
    try:
        return json.loads(s) if s else None
    except (TypeError, ValueError):
        return None


def json_dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def http_json(url: str, timeout: float = 3.0, username: str = None, password: str = "",
              method: str = "GET", body=None) -> tuple:
    """HTTP JSON 请求。返回 (data, error)。成功 data 为解析后的 dict。"""
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = (body if isinstance(body, str) else json_dumps(body)).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    if username:
        req.add_header("Authorization", f"Basic {_b64(f'{username}:{password}')}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json_loads(raw) if raw else None, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"无法连接: {getattr(e, 'reason', e)}"
    except Exception as e:
        return None, str(e)


class AgentSession(ABC):
    """会话客户端: 创建/发送/中止。实现见各 adapter。"""

    @abstractmethod
    def create_session(self, title: str = "", parent_id: str = "") -> dict: ...

    @abstractmethod
    def send_message(self, session_id: str, text: str, model: str = "", no_reply: bool = False) -> dict: ...

    @abstractmethod
    def abort(self, session_id: str) -> bool: ...


class ProcessSession(AgentSession):
    """进程会话基类: CLI 一次性引擎(codex/cline/...)的会话客户端。

    `create_session` 原样返回(action=run); 真正的进程由 IterEvents 启动。
    不关心 host/port, `cfg` 携带运行参数(binary 路径、模型、cwd)。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def create_session(self, title: str = "", parent_id: str = "") -> dict:
        return {"id": "proc"}

    def send_message(self, session_id: str, text: str, model: str = "",
                     no_reply: bool = False) -> dict:
        # cli 型消息由 process_events 一次性下发; 本方法仅保留契约兼容。
        return {"id": "proc"}

    def abort(self, session_id: str) -> bool:
        return True

    # ---- 需子类实现 ----

    def build_argv(self, prompt: str, model: str = "", resume: str = "") -> list[str]:
        raise NotImplementedError

    def map_line(self, line: dict) -> Optional[dict]:
        """stdout JSONL 行 → 归一化事件(None = 忽略)。"""
        raise NotImplementedError


class AgentAdapter(ABC):
    id: str = ""
    name: str = ""
    desc: str = ""
    default_host: str = DEFAULT_HOST
    default_port: int = DEFAULT_PORT
    supports_stream: bool = False
    # ── 运行形态 ────────────────────────────────────────────────
    # daemon: HTTP/SSE 常驻(类 opencode/qwen serve); cli: 每任务一次子进程。
    mode: str = "server"

    # ── 元信息 ───────────────────────────────────────────────

    def capabilities(self) -> dict:
        return {
            "id": self.id, "name": self.name, "desc": self.desc,
            "supports_stream": self.supports_stream,
        }

    # ── 安装/适配验证 ─────────────────────────────────────────

    @abstractmethod
    def env_check(self) -> dict:
        """{ status: ok|partial|fail, installed, binary, version, config, detail, checks }"""

    # ── 连通性探测 ────────────────────────────────────────────

    @abstractmethod
    def probe(self, cfg: dict) -> dict:
        """{ status: ok|fail, detail, version, models, connected }"""

    @abstractmethod
    def addr(self, cfg: dict, instance: Optional[dict] = None) -> str:
        """cfg(及可选实例) → agent server 访问地址(如 http://host:port)。"""

    # ── 进程面 (managed spawn / health) ───────────────────────

    @abstractmethod
    def spawn(self, base: dict) -> list[str]:
        """managed 模式下在工程根目录启动 agent server 的完整 argv。"""

    @abstractmethod
    def health(self, addr: str, username: str) -> bool:
        """健康探测: 返回是否就绪。"""

    def required_env(self, addr: str) -> Optional[dict]:
        """managed spawn 额外注入的环境变量。默认无。"""
        return None

    # ── 会话面 ────────────────────────────────────────────────

    @abstractmethod
    def make_client(self, addr: str, username: str, password: str) -> AgentSession: ...

    # ── 流式面 ────────────────────────────────────────────────
    # daemon 型: iter_events(client, session_id) 订阅 HTTP SSE(见 opencode/qwen)。
    # cli 型:    iter_events 迭代子进程 stdout JSONL(见 process_events)。

    async def iter_events(self, client: AgentSession, session_id: str) -> AsyncIterator[dict]:
        """驱动一次结果的事件归一化 → 前端 WS 语义事件。

        yield 形状(与前端 WS 契约 §5 对齐):
          {"type":"status","status":"planning|working|testing|done|failed|stopped"}
          {"type":"message","role":"assistant","content","time"}
          {"type":"tool_call","tool":{ type,label,detail,ok }}
        """
        if False:
            yield {}
        return

    async def process_events(self, client: ProcessSession, prompt: str, model: str = "",
                             resume: str = "", workdir: str = "") -> AsyncIterator[dict]:
        """cli 型: 启动一次性子进程并流式消费 stdout JSONL → 归一化事件。

        yield 语义 on ProcessSession.map_line(line)。
        """
        if False:
            yield {}
        return


# ── opencode ───────────────────────────────────────────────────

class OpenCodeSession(AgentSession):
    """opencode serve HTTP 会话客户端。"""

    def __init__(self, addr: str, username: str = DEFAULT_USERNAME, password: str = ""):
        self.addr = addr.rstrip("/")
        self.username = username
        self.password = password

    def _req(self, path: str, method: str = "GET", body=None, timeout: float = 10.0) -> dict:
        res, _ = http_json(f"{self.addr}{path}", method=method, body=body,
                           timeout=timeout, username=self.username, password=self.password)
        return res or {}

    def create_session(self, title: str = "", parent_id: str = "") -> dict:
        body = {}
        if title:
            body["title"] = title
        if parent_id:
            body["parentID"] = parent_id
        return self._req("/session", method="POST", body=body, timeout=6.0)

    def send_message(self, session_id: str, text: str, model: str = "", no_reply: bool = False) -> dict:
        body = {"parts": [{"type": "text", "text": text}]}
        if model:
            parts = model.split("/", 1)
            p = parts[0] if len(parts) > 1 else ""
            m = parts[1] if len(parts) > 1 else model
            if p:
                body["model"] = {"providerID": p, "modelID": m}
        if no_reply:
            body["noReply"] = True
        return self._req(f"/session/{session_id}/message", method="POST",
                         body=body, timeout=180.0)

    def abort(self, session_id: str) -> bool:
        res = self._req(f"/session/{session_id}/abort", method="POST", timeout=6.0)
        return not res.get("_error")


class OpenCodeAdapter(AgentAdapter):
    """opencode(server 模式)。

    契约见 docs/opencode/server(HTTP REST + SSE):
      GET  /global/health → { healthy, version }; GET /provider → all/connected
      POST /session ; GET /event (SSE: data 行 JSON {id,type,properties})
    """

    id = "opencode"
    name = "OpenCode"
    desc = "OpenCode CLI(server 模式)"
    default_host = DEFAULT_HOST
    default_port = DEFAULT_PORT
    supports_stream = True

    # ── 安装/适配验证 ───────────

    def env_check(self) -> dict:
        binary = self._which("opencode")
        version = self._run_version(binary) if binary else ""
        home = os.path.expanduser("~")
        configs = [
            os.path.join(home, ".config", "opencode", "opencode.json"),
            os.path.join(home, ".config", "opencode", "opencode.jsonc"),
            os.path.join(os.getcwd(), "opencode.json"),
        ]
        exist = [p for p in configs if os.path.isfile(p)]
        installed = bool(binary and version)
        complete = installed and bool(exist)
        status = "ok" if complete else ("partial" if installed else "fail")
        if not binary:
            detail = "未检测到 opencode 可执行文件(PATH 中无 opencode)"
        elif not version:
            detail = "opencode 可执行文件存在，但 `opencode --version` 无法运行"
        elif not exist:
            detail = "opencode 已安装，但未找到配置文件(如 ~/.config/opencode/opencode.json)"
        else:
            detail = f"opencode {version} 已完整安装并适配"
        return {
            "status": status, "installed": installed, "binary": binary or "",
            "version": version, "config": exist, "detail": detail,
            "checks": {"binary": bool(binary), "version": bool(version), "config": bool(exist)},
        }

    @staticmethod
    def _which(cmd: str) -> Optional[str]:
        import shutil
        return shutil.which(cmd)

    @staticmethod
    def _run_version(binary: str) -> str:
        try:
            r = subprocess.run([binary, "--version"], capture_output=True,
                               text=True, timeout=15)
            return (r.stdout or r.stderr or "").strip() if r.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""

    # ── 连通性 ───────────────────

    def addr(self, cfg: dict, instance: Optional[dict] = None) -> str:
        url = (cfg.get("url") or "").strip()
        if url:
            return url.rstrip("/")
        host = (instance or {}).get("host") or cfg.get("host") or self.default_host
        port = int((instance or {}).get("port") or cfg.get("port") or self.default_port)
        return f"http://{host}:{port}"

    def probe(self, cfg: dict) -> dict:
        addr = self.addr(cfg)
        username = cfg.get("username") or DEFAULT_USERNAME
        health, herr = http_json(f"{addr}/global/health", username=username)
        if herr or not health or not health.get("healthy"):
            return {"status": "fail",
                    "detail": herr or "opencode 服务未就绪(healthy != true)",
                    "version": (health or {}).get("version") or "", "models": [], "connected": []}
        providers, perr = http_json(f"{addr}/provider", username=username)
        models, connected = [], []
        if perr is None and isinstance(providers, dict):
            connected = providers.get("connected") or []
            for p in providers.get("all") or []:
                if p.get("id") not in connected:
                    continue
                pm = p.get("models")
                items = list(pm.values()) if isinstance(pm, dict) else (pm or [])
                for m in items:
                    if isinstance(m, dict):
                        models.append({"id": m.get("id"), "name": m.get("name") or m.get("id")})
        return {"status": "ok", "detail": "opencode 服务连通",
                "version": health.get("version") or "", "models": models, "connected": connected}

    # ── 进程面 ───────────────────

    def spawn(self, base: dict) -> list[str]:
        port = int(base.get("port") or self.default_port)
        return ["opencode", "serve", "--port", str(port), "--hostname", self.default_host]

    def health(self, addr: str, username: str) -> bool:
        health, _ = http_json(f"{addr}/global/health", username=username)
        return bool(health and health.get("healthy"))

    def required_env(self, addr: str) -> Optional[dict]:
        env = {"OPENCODE_CLIENT": "architect"}
        password = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
        username = os.environ.get("OPENCODE_SERVER_USERNAME", DEFAULT_USERNAME)
        env["OPENCODE_SERVER_USERNAME"] = username
        if password:
            env["OPENCODE_SERVER_PASSWORD"] = password
        return env

    # ── 会话面 ───────────────────

    def make_client(self, addr: str, username: str, password: str = "") -> AgentSession:
        return OpenCodeSession(addr, username=username, password=password)

    # ── 流式面 ───────────────────

    def _label(self, part: dict) -> dict:
        """tool part → 前端 tool 卡片字段(label/detail)。"""
        tool = part.get("tool")
        state = part.get("state") or {}
        name = tool.get("tool") if isinstance(tool, dict) else str(tool or "")
        input_ = state.get("input") or {}
        label = input_.get("filePath") or input_.get("command") or input_.get("path") or name
        output = state.get("output") or ""
        if isinstance(output, (dict, list)):
            try:
                output = json_dumps(output)[:240]
            except Exception:
                output = ""
        return str(label), str(output)

    def _tool_type(self, name: str) -> str:
        if name in ("write", "edit", "apply_patch", "patch", "write_file"):
            return "write-file"
        if name in ("test", "run-test"):
            return "run-test"
        return "run-command"

    async def iter_events(self, client: AgentSession, session_id: str) -> AsyncIterator[dict]:
        """订阅 /event → 归一化前端 WS 事件。仅转发本 session 的事件。

        SSE 读取是阻塞 IO, 放到独立线程 → asyncio.Queue, async 侧消费,
        避免卡住事件循环。
        """
        if not isinstance(client, OpenCodeSession):
            return
        from concurrent.futures import ThreadPoolExecutor
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _pump():
            try:
                for frame in _iter_sse_sync(f"{client.addr}/event", client.username):
                    loop.call_soon_threadsafe(q.put_nowait, frame)
            except Exception:
                pass
            finally:
                try:
                    loop.call_soon_threadsafe(q.put_nowait, None)
                except Exception:
                    pass

        executor = ThreadPoolExecutor(max_workers=1)
        fut = loop.run_in_executor(executor, _pump)
        try:
            while True:
                if stop.is_set():
                    break
                try:
                    frame = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if frame is None:
                    break
                ev = frame.get("data") or {}
                etype = frame.get("event") or ev.get("type") or ""
                props = ev.get("properties") or {}
                sid = props.get("sessionID") or (props.get("part") or {}).get("sessionID") or ""
                if sid and sid != session_id:
                    continue
                if etype == "session.status":
                    st = (props.get("status") or {}).get("type", "")
                    if st in ("busy", "idle"):
                        yield {"type": "status", "status": "working" if st == "busy" else "idle"}
                elif etype == "session.error":
                    yield {"type": "status", "status": "failed"}
                elif etype == "message.part.updated":
                    part = props.get("part") or {}
                    ptype = part.get("type")
                    if ptype == "text":
                        text = (part.get("text") or "").strip()
                        if text:
                            yield {"type": "message", "role": "assistant", "content": text}
                    elif ptype == "tool":
                        tool = part.get("tool")
                        tool_name = tool.get("tool") if isinstance(tool, dict) else str(tool or "")
                        state = part.get("state") or {}
                        status = state.get("status", "")
                        label, detail = self._label(part)
                        if status == "running":
                            yield {"type": "tool_call", "tool": {
                                "type": self._tool_type(tool_name),
                                "label": label, "detail": "", "ok": False}}
                        elif status in ("completed", "error"):
                            yield {"type": "tool_call", "tool": {
                                "type": self._tool_type(tool_name),
                                "label": label,
                                "detail": detail if status == "error" else "",
                                "ok": status == "completed"}}
        finally:
            stop.set()
            fut.cancel()
            executor.shutdown(wait=False)
        return


# ── 子进程 JSONL 流式读取(cli 型引擎通用) ─────────────────────
# 在 worker 线程逐行读 stdout, async 侧消费; 进程退出自然结束迭代。

async def iter_process_jsonl(argv: list[str], workdir: str = "", env_extra: Optional[dict] = None) -> AsyncIterator[str]:
    """运行一次性子进程, 逐行 async 产出 stdout 文本行(含容错 stderr 标记)。"""
    import asyncio as _asyncio
    from concurrent.futures import ThreadPoolExecutor

    loop = _asyncio.get_running_loop()
    env = {**os.environ}
    if env_extra:
        env.update(env_extra)
    q: _asyncio.Queue = _asyncio.Queue(maxsize=1024)
    stop = _asyncio.Event()

    def _pump():
        try:
            proc = subprocess.Popen(
                argv, cwd=workdir or ".", env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
            )
        except (FileNotFoundError, OSError) as e:
            loop.call_soon_threadsafe(q.put_nowait, f"__stderr__:无法启动: {e}")
            return
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if line:
                    loop.call_soon_threadsafe(q.put_nowait, line)
        finally:
            proc.wait()
            try:
                err = (proc.stderr.read() or "").strip() if proc.stderr else ""
            except Exception:
                err = ""
            if err and not stop.is_set():
                loop.call_soon_threadsafe(q.put_nowait, f"__stderr__:{err[:400]}")
            try:
                loop.call_soon_threadsafe(q.put_nowait, None)
            except Exception:
                pass

    executor = ThreadPoolExecutor(max_workers=1)
    fut = loop.run_in_executor(executor, _pump)
    try:
        while True:
            if stop.is_set():
                break
            try:
                line = await _asyncio.wait_for(q.get(), timeout=1.0)
            except _asyncio.TimeoutError:
                continue
            if line is None:
                break
            yield line
    finally:
        stop.set()
        fut.cancel()
        executor.shutdown(wait=False)
    return

def _iter_sse_sync(url: str, username: str = DEFAULT_USERNAME, timeout: float = 90.0):
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    if username:
        req.add_header("Authorization", f"Basic {_b64(username + ':')}")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except Exception:
        return
    try:
        event = ""
        data = ""
        for line in resp:
            line = line.decode("utf-8", errors="replace").strip()
            if line == "":
                payload = json_loads(data) if data else None
                if payload or data:
                    yield {"event": event, "data": payload}
                event = ""
                data = ""
            elif line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
    finally:
        try:
            resp.close()
        except Exception:
            pass


# ── qwen code(daemon) ───────────────────────────────────────────

class QwenSession(AgentSession):
    """Qwen Code `serve --http-bridge`(ACP 协议)会话客户端。

    契约(实测 qwen 0.20.1):
      GET  /health               → { status:"ok" }
      POST /session              → { sessionId, clientId, workspaceCwd }
      POST /session/:id/prompt  → { prompt, promptId, lastEventId }
      GET  /session/:id/events  → SSE: event session_update/turn_complete
      POST /session/:id/cancel  → 204
    """

    def __init__(self, addr: str, username: str = "", password: str = ""):
        self.addr = addr.rstrip("/")
        self.username = username
        self.password = password

    def _req(self, path: str, method: str = "GET", body=None, timeout: float = 10.0) -> tuple:
        return http_json(f"{self.addr}{path}", method=method, body=body,
                         timeout=timeout, username=self.username or None, password=self.password)

    def create_session(self, title: str = "", parent_id: str = "") -> dict:
        body = {}
        if title:
            body["session"] = {"name": title}
        data, _ = self._req("/session", method="POST", body=body, timeout=8.0)
        return data or {}

    def send_message(self, session_id: str, text: str, model: str = "", no_reply: bool = False) -> dict:
        payload = {"prompt": [{"type": "text", "text": text}]}
        if model:
            payload["model"] = model
        data, _ = self._req(f"/session/{session_id}/prompt", method="POST", body=payload, timeout=90.0)
        if data is None:
            return {"_error": f"prompt 无响应({session_id})"}
        return data or {}

    def abort(self, session_id: str) -> bool:
        data, err = self._req(f"/session/{session_id}/cancel", method="POST", body={}, timeout=8.0)
        return err is None or "204" in str(err)


class QwenAdapter(AgentAdapter):
    """Qwen Code(daemon 模式): 本地 `qwen serve --http-bridge` HTTP 会话。"""

    id = "qwen"
    name = "Qwen Code"
    desc = "Qwen Code(daemon 模式)"
    default_host = DEFAULT_HOST
    default_port = 4170
    supports_stream = True
    mode = "server"

    # ── 安装/适配验证 ───────────

    def env_check(self) -> dict:
        binary = self._which("qwen")
        version = self._run_version(binary) if binary else ""
        home = os.path.expanduser("~")
        configs = [
            os.path.join(home, ".qwen", "settings.json"),
        ]
        exist = [p for p in configs if os.path.isfile(p)]
        installed = bool(binary and version)
        complete = installed and bool(exist)
        status = "ok" if complete else ("partial" if installed else "fail")
        if not binary:
            detail = "未检测到 qwen 可执行文件(PATH 中无 qwen)"
        elif not version:
            detail = "qwen 可执行文件存在，但 `qwen --version` 无法运行"
        elif not exist:
            detail = "qwen 已安装，但未找到配置文件(如 ~/.qwen/settings.json)"
        else:
            detail = f"qwen {version} 已完整安装并适配"
        return {
            "status": status, "installed": installed, "binary": binary or "",
            "version": version, "config": exist, "detail": detail,
            "checks": {"binary": bool(binary), "version": bool(version), "config": bool(exist)},
        }

    @staticmethod
    def _which(cmd: str) -> Optional[str]:
        import shutil
        return shutil.which(cmd)

    @staticmethod
    def _run_version(binary: str) -> str:
        try:
            r = subprocess.run([binary, "--version"], capture_output=True,
                               text=True, timeout=15)
            return (r.stdout or r.stderr or "").strip() if r.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""

    # ── 连通性 ───────────────────

    def addr(self, cfg: dict, instance: Optional[dict] = None) -> str:
        url = (cfg.get("url") or "").strip()
        if url:
            return url.rstrip("/")
        host = (instance or {}).get("host") or cfg.get("host") or self.default_host
        port = int((instance or {}).get("port") or cfg.get("port") or self.default_port)
        return f"http://{host}:{port}"

    def probe(self, cfg: dict) -> dict:
        addr = self.addr(cfg)
        health, herr = http_json(f"{addr}/health", timeout=3.0)
        if herr or not self._healthy(health):
            return {"status": "fail",
                    "detail": herr or "qwen serve 未就绪(health != ok)",
                    "version": "", "models": [], "connected": []}
        return {"status": "ok", "detail": f"qwen serve 连通({addr})",
                "version": "", "models": [], "connected": []}

    @staticmethod
    def _healthy(h: Optional[dict]) -> bool:
        return bool(h and (h.get("status") == "ok" or h.get("ok") is True))

    # ── 进程面 ───────────────────

    def spawn(self, base: dict) -> list[str]:
        port = int(base.get("port") or self.default_port)
        argv = ["qwen", "serve", "--no-web", "--hostname", self.default_host, "--port", str(port)]
        ws = (base.get("cwd") or "").strip()
        if ws:
            argv += ["--workspace", ws]
        return argv

    def health(self, addr: str, username: str) -> bool:
        h, _ = http_json(f"{addr}/health", timeout=3.0)
        return self._healthy(h)

    def required_env(self, addr: str) -> Optional[dict]:
        return None

    # ── 会话面 ───────────────────

    def make_client(self, addr: str, username: str, password: str = "") -> AgentSession:
        return QwenSession(addr, username=username, password=password)

    # ── 流式面 ───────────────────

    async def iter_events(self, client: AgentSession, session_id: str) -> AsyncIterator[dict]:
        """订阅 /session/:id/events SSE → 归一化前端 WS 事件。"""
        if not isinstance(client, QwenSession):
            return
        from concurrent.futures import ThreadPoolExecutor
        import asyncio as _asyncio

        q: _asyncio.Queue = _asyncio.Queue(maxsize=512)
        stop = _asyncio.Event()
        loop = _asyncio.get_running_loop()

        def _pump():
            try:
                for frame in _iter_sse_sync(f"{client.addr}/session/{session_id}/events",
                                            username=client.username or DEFAULT_USERNAME, timeout=120.0):
                    loop.call_soon_threadsafe(q.put_nowait, frame)
            except Exception:
                pass
            finally:
                try:
                    loop.call_soon_threadsafe(q.put_nowait, None)
                except Exception:
                    pass

        executor = ThreadPoolExecutor(max_workers=1)
        fut = loop.run_in_executor(executor, _pump)
        try:
            while True:
                if stop.is_set():
                    break
                try:
                    frame = await _asyncio.wait_for(q.get(), timeout=1.0)
                except _asyncio.TimeoutError:
                    continue
                if frame is None:
                    break
                ev = frame.get("data") or {}
                etype = frame.get("event") or ev.get("type") or ""
                if etype == "session_update":
                    for item in self._session_update(ev):
                        yield item
                elif etype == "turn_complete":
                    result = ev.get("data") or {}
                    reason = result.get("stopReason") or result.get("stop_reason") or ""
                    yield {"type": "status",
                           "status": "done" if not reason or reason == "end_turn" else "failed"}
        finally:
            stop.set()
            fut.cancel()
            executor.shutdown(wait=False)
        return

    def _session_update(self, ev: dict, yield_all: bool = False):
        data = ev.get("data") or {}
        update = data.get("update") or {}
        stype = update.get("sessionUpdate") or ""
        content = update.get("content") or {}
        text = content.get("text") if isinstance(content, dict) else (content if isinstance(content, str) else "")
        items = []
        if stype == "agent_message_chunk" and text:
            items.append({"type": "message", "role": "assistant", "content": text})
        return items


# ── codex(cli) ────────────────────────────────────────────────

class CodexSession(ProcessSession):
    def build_argv(self, prompt: str, model: str = "", resume: str = "") -> list[str]:
        argv = ["codex", "exec", "--json"]
        if model:
            argv += ["--model", model]
        argv += ["--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox"]
        argv.append(prompt)
        return argv

    def build_env(self) -> Optional[dict]:
        """LD 本地服务: 若配置带 baseUrl(openai 兼容), 生成临时 CODEX_HOME 指向它。"""
        base = ((self.cfg or {}).get("baseUrl") or "").strip()
        key = (self.cfg or {}).get("apiKey") or ""
        if not base:
            return None
        import tempfile
        home = tempfile.mkdtemp(prefix="codex-")
        provider = "local"
        cfg_text = (
            f'model_provider = "{provider}"\n'
            f'model = "{((self.cfg or {}).get("model") or "") .strip() or "default"}"\n\n'
            f'[model_providers.{provider}]\n'
            f'name = "local"\n'
            f'base_url = "{base}"\n'
            f'wire_api = "responses"\n'
            f'env_key = "CODEX_LOCAL_KEY"\n'
        )
        with open(os.path.join(home, "config.toml"), "w") as f:
            f.write(cfg_text)
        env = {"CODEX_HOME": home}
        if key := (key or ""):
            env["CODEX_LOCAL_KEY"] = key
        elif not key:
            env["CODEX_LOCAL_KEY"] = "dummy"
        return env


class CodexAdapter(AgentAdapter):
    """OpenAI Codex CLI(一次性进程模式)。支持流式--json。"""

    id = "codex"
    name = "Codex"
    desc = "OpenAI Codex CLI(进程模式)"
    default_host = "127.0.0.1"
    default_port = 0
    supports_stream = True
    mode = "cli"

    def env_check(self) -> dict:
        binary = self._which("codex")
        version = self._run_version(binary) if binary else ""
        home = os.path.expanduser("~")
        configs = [
            os.path.join(home, ".codex", "config.toml"),
            os.path.join(home, ".codex", "auth.json"),
        ]
        exist = [p for p in configs if os.path.isfile(p)]
        installed = bool(binary and version)
        status = "ok" if installed else "fail"
        if not binary:
            detail = "未检测到 codex 可执行文件"
        elif not version:
            detail = "codex 可执行文件存在，但 `codex --version` 无法运行"
        elif not exist:
            detail = "codex 已安装(CLI 模式)，未找到 ~/.codex/config.toml 或 auth.json(可能需登录)"
        else:
            detail = f"codex {version} 已安装(CLI 模式)"
        return {
            "status": status, "installed": installed, "binary": binary or "",
            "version": version, "config": exist, "detail": detail,
            "checks": {"binary": bool(binary), "version": bool(version), "config": bool(exist)},
        }

    @staticmethod
    def _which(cmd: str) -> Optional[str]:
        import shutil
        return shutil.which(cmd)

    @staticmethod
    def _run_version(binary: str) -> str:
        try:
            r = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15)
            return (r.stdout or r.stderr or "").strip() if r.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""

    def addr(self, cfg: dict, instance: Optional[dict] = None) -> str:
        return f"{(cfg.get('url') or '').strip() or 'cli:'}"

    def spawn(self, base: dict) -> list[str]:
        return ["codex", "exec", "--json"]

    def health(self, addr: str, username: str) -> bool:
        return self._which("codex") is not None

    def make_client(self, addr: str, username: str, password: str = "") -> AgentSession:
        return CodexSession({})

    def probe(self, cfg: dict) -> dict:
        if not self._which("codex"):
            return {"status": "fail", "detail": "codex 未安装", "version": "", "models": [], "connected": []}
        return {"status": "ok", "detail": "codex CLI 就绪", "version": self._run_version(self._which("codex")),
                "models": [], "connected": []}

    async def iter_events(self, client: AgentSession, session_id: str) -> AsyncIterator[dict]:
        if not isinstance(client, CodexSession):
            return
        # cli 型: 实际由 process_events 处理, 本处 no-op。
        if False:
            yield {}
        return

    async def process_events(self, client: ProcessSession, prompt: str, model: str = "",
                            resume: str = "", workdir: str = "") -> AsyncIterator[dict]:
        argv = client.build_argv(prompt, model, resume)
        env_extra = client.build_env() if hasattr(client, "build_env") else None
        closed = False
        async for line in iter_process_jsonl(argv, workdir=workdir, env_extra=env_extra):
            if line.startswith("__stderr__:"):
                err = line[len("__stderr__:"):]
                if not (err.startswith("WARNING") or "Reading additional input" in err):
                    yield {"type": "message", "role": "assistant", "content": err}
                continue
            data = json_loads(line)
            if not data:
                continue
            t = data.get("type", "")
            if t == "thread.started" or t == "turn.started":
                yield {"type": "status", "status": "working"}
            elif t == "item.started":
                item = data.get("item") or {}
                if item.get("type") == "command_execution":
                    cmd = item.get("command") or ""
                    if cmd:
                        yield {"type": "tool_call", "tool": {
                            "type": "run-command", "label": cmd[:80], "detail": "", "ok": False}}
            elif t == "item.completed":
                item = data.get("item") or {}
                itype = item.get("type") or ""
                if itype == "agent_message":
                    text = item.get("text") or item.get("content") or ""
                    if isinstance(text, list):
                        text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))
                    if text:
                        yield {"type": "message", "role": "assistant", "content": str(text)}
                elif itype == "command_execution":
                    status = item.get("status") or ""
                    if status in ("completed", "error"):
                        cmd = item.get("command") or ""
                        out = item.get("aggregated_output") or ""
                        detail = str(out)[:160] if status == "error" else (str(out)[:160] or "完成")
                        yield {"type": "tool_call", "tool": {
                            "type": "run-command", "label": (cmd or "")[:80],
                            "detail": detail, "ok": status == "completed"}}
                elif itype == "tool_use":
                    name = item.get("name") or item.get("tool") or "run-command"
                    label = item.get("command") or item.get("filePath") or None
                    yield {"type": "tool_call", "tool": {
                        "type": self._tool_type(name), "label": str(label or name)[:80],
                        "detail": "", "ok": False}}
            elif t in ("turn.completed", "session.completed"):
                yield {"type": "status", "status": "done"}
                closed = True
            elif t in ("turn.failed", "turn.interrupted"):
                yield {"type": "status", "status": "failed"}
                closed = True
            elif t == "error":
                msg = (data.get("message") or "").strip()
                if msg and not msg.startswith("WARNING"):
                    yield {"type": "message", "role": "assistant",
                           "content": f"codex 错误: {msg[:240]}"}
                yield {"type": "status", "status": "failed"}
                closed = True
        if not closed:
            yield {"type": "status", "status": "failed"}

    def _tool_type(self, name: str) -> str:
        if name in ("write", "edit", "apply_patch", "write_file", "file_edit"):
            return "write-file"
        if name in ("test", "run_test", "run-test"):
            return "run-test"
        return "run-command"


# ── cline(cli) ───────────────────────────────────────────────

class ClineSession(ProcessSession):
    def build_argv(self, prompt: str, model: str = "", resume: str = "") -> list[str]:
        argv = ["cline", "--json"]
        if model:
            argv += ["--model", model]
        if resume:
            argv += ["--resume", resume]
        argv.append(prompt)
        return argv


class ClineAdapter(AgentAdapter):
    """Cline CLI(headless --json)。"""   # noqa

    id = "cline"
    name = "Cline"
    desc = "Cline(headless CLI)"
    default_port = 0
    supports_stream = True
    mode = "cli"

    def env_check(self) -> dict:
        binary = self._which("cline")
        if not binary:
            return {"status": "fail", "installed": False, "binary": "", "version": "",
                    "config": [], "detail": "未检测到 cline 可执行文件(PATH 中无 cline)",
                    "checks": {"binary": False, "version": False, "config": False}}
        version = self._run_version(binary)
        return {"status": "ok", "installed": True, "binary": binary, "version": version,
                "config": [], "detail": f"cline {version} 已安装(headless CLI)",
                "checks": {"binary": True, "version": True, "config": True}}

    @staticmethod
    def _which(cmd: str):
        import shutil
        return shutil.which(cmd)

    @staticmethod
    def _run_version(binary: str) -> str:
        try:
            r = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15)
            return (r.stdout or r.stderr or "").strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    def addr(self, cfg: dict, instance: Optional[dict] = None) -> str:
        return "cli:"

    def spawn(self, base: dict) -> list[str]:
        return []

    def health(self, addr: str, username: str) -> bool:
        return self._which("cline") is not None

    def make_client(self, addr: str, username: str, password: str = "") -> AgentSession:
        return ClineSession({})

    def probe(self, cfg: dict) -> dict:
        if not self._which("cline"):
            return {"status": "fail", "detail": "cline 未安装", "version": "", "models": [], "connected": []}
        return {"status": "ok", "detail": "cline CLI 就绪", "version": "",
                "models": [], "connected": []}

    async def process_events(self, client: ProcessSession, prompt: str, model: str = "",
                            resume: str = "", workdir: str = "") -> AsyncIterator[dict]:
        argv = client.build_argv(prompt, model, resume)
        closed = False
        async for line in iter_process_jsonl(argv, workdir=workdir):
            if line.startswith("__stderr__:"):
                err = line[len("__stderr__:"):]
                if err and "hook dispatch failed" not in err and "Reading additional input" not in err:
                    yield {"type": "message", "role": "assistant", "content": err[:240]}
                continue
            data = json_loads(line)
            if not data:
                continue
            t = data.get("type", "")
            if t == "agent_event":
                ev = data.get("event") or {}
                et = ev.get("type", "")
                if et in ("message", "assistant_message", "thinking"):
                    text = (ev.get("message") or {}).get("content") if isinstance(ev.get("message"), dict) else ""
                    if isinstance(text, list):
                        text = " ".join(x.get("text", "") for x in text if isinstance(x, dict))
                    if text:
                        yield {"type": "message", "role": "assistant", "content": text}
                elif et in ("tool_call", "tool_use"):
                    tool = ev.get("tool") or ev.get("toolCall") or {}
                    name = tool.get("name") or tool.get("tool") or "run-command"
                    label = tool.get("command") or tool.get("filePath") or tool.get("path") or name
                    yield {"type": "tool_call", "tool": {"type": self._tool_type(name),
                                                        "label": str(label), "detail": "", "ok": False}}
            elif t == "run_result":
                text = (data.get("text") or "").strip()
                if text:
                    yield {"type": "message", "role": "assistant", "content": text}
                yield {"type": "status",
                       "status": "done" if (data.get("finishReason") or "") == "end_turn" else "failed"}
                closed = True
            elif t == "error":
                msg = (data.get("message") or "").strip()
                if msg and "hook dispatch failed" not in msg:
                    yield {"type": "message", "role": "assistant", "content": msg[:240]}
                yield {"type": "status", "status": "failed"}
                closed = True
        if not closed:
            yield {"type": "status", "status": "failed"}

    def _tool_type(self, name: str) -> str:
        if name in ("write-file", "write_file", "edit", "apply_patch"):
            return "write-file"
        if name in ("test", "run-test"):
            return "run-test"
        return "run-command"


# ── 注册表 ─────────────────────────────────────────────────────

_ADAPTERS: dict[str, AgentAdapter] = {}


def _register(adapter: AgentAdapter) -> AgentAdapter:
    _ADAPTERS[adapter.id] = adapter
    return adapter


_register(OpenCodeAdapter())
_register(QwenAdapter())
_register(CodexAdapter())
_register(ClineAdapter())


def get_adapter(adapter_id: str) -> Optional[AgentAdapter]:
    return _ADAPTERS.get((adapter_id or "").lower())


def get_agent(adapter_id: str) -> Optional[AgentAdapter]:
    """别名: get_adapter。供 agent_server/agent_config 等统一调用。"""
    return get_adapter(adapter_id)


def list_adapters() -> list[dict]:
    return [a.capabilities() for a in _ADAPTERS.values()]


def adapters_ready() -> dict[str, str]:
    """adapter_id → ok|partial|fail(本机安装/适配探测)。"""
    return {a.id: a.env_check()["status"] for a in _ADAPTERS.values()}