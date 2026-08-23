"""Gateway — 统一端口 3456 的入口（P1；M06 manifest 驱动）。

职责：
- 反向代理：各 app `api_prefixes` → 127.0.0.1:<port>（含 WS upgrade），
  目标地址由 `apps/*/manifest.toml` 生成（env 覆盖优先）。
- RPC 路由：`/api/rpc/{method}` 按命名空间前缀路由（核心默认表 + 各 app
  `rpc_namespaces` 合并，冲突即启动失败），并做 method 黑名单拦截。
- 事件桥：`/ws/events` → ZMQ-SUB（kb 5681 + llm 5682 + doc 5683 + agent 5684，
  env `EVENT_PUB_PORTS` 可覆盖），转发 `{topic, eventType, data}`。
- 聚合健康：`GET /api/health` 探各服务 health 端点。
- 鉴权：除 /health、/api/health 与静态 SPA 外，要求 `Authorization: Bearer <token>`
  或 `?token=`；token 存 `~/.topocode/token`。默认绑定 127.0.0.1。

服务拓扑对浏览器透明：manifest 改 port 后重启 gateway 即切换反代目标。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter()

# 仓库根（topoone/gateway/gateway.py → parents[4]）
_REPO_ROOT = str(Path(__file__).resolve().parents[4])

# ── Manifest 驱动服务表（M06） ─────────────────────────────────────
# 核心固定服务（非 apps/manifest 成员）：
#   kb    = 核心进程 data_api（3459）
#   llm   = LLM 模型网关（3484，topoone.llm）
#   agent = Agent harness（3482，topoone.agent）
# env 覆盖优先级高于 manifest（现状保留）。
_KB_URL = os.environ.get("KB_API_URL", "http://127.0.0.1:3459")
_LLM_URL = os.environ.get("LLM_API_URL", "http://127.0.0.1:3484")
_AGENT_URL = os.environ.get("AGENT_API_URL", "http://127.0.0.1:3482")

_ENV_URL_OVERRIDES = {
    "architect": "ARCHITECT_URL",
    "docs": "DOC_API_URL",
    "chat": "CHAT_API_URL",
}

# 核心固定 RPC 路由表：核心进程（kb）与 llm/agent 服务持有的命名空间。
# app manifest 的 rpc_namespaces（docs: render/doc；chat: chat；
# workbench[kind=core]: knowledge → 经 kb 进程）在此表上合并。
# M11: report.* 保留在核心（report_service + task_manager subdoc 写方法，docs 只读无法承载），
# 故 report 仍路由 kb；仅 render.* 移入 docs 服务（:3481）。
_CORE_RPC_ROUTES = {
    "project": "kb", "analysis": "kb", "group": "kb",
    "version": "kb", "module": "kb", "system": "kb", "plugin": "kb",
    "dir": "kb", "settings": "kb", "report": "kb", "model": "kb", "graph": "kb",
    "llm": "llm", "session": "llm", "analysisSession": "llm", "promptTemplate": "llm",
    "agent": "agent", "skill": "agent", "tool": "agent",
}


def _load_registry(root: str | None = None):
    """manifest → (service_urls, rpc_routes, prefix_targets, health_targets, event_pub_ports)。

    冲突（rpc_namespace 重复 / 前缀包含关系）即抛 ManifestError → gateway 启动失败。
    """
    from topoone.manifest import ManifestError, discover_apps, validate_registry

    apps = discover_apps(root or _REPO_ROOT)
    # 跨 app 冲突（api_prefix 包含 / static_mount / port）→ 启动失败
    reg_errors = validate_registry(apps)
    if reg_errors:
        raise ManifestError("gateway registry validation failed:\n  " + "\n  ".join(reg_errors))

    service_urls = {"kb": _KB_URL, "llm": _LLM_URL, "agent": _AGENT_URL}
    health_targets = {"kb": _KB_URL}
    rpc_routes = dict(_CORE_RPC_ROUTES)
    prefix_targets: list[tuple[str, str]] = []

    for name, m in sorted(apps.items()):
        if m.kind != "service" or not m.service_url:
            # kind=core（workbench 等）：rpc_namespaces 经 kb 进程
            for ns in m.rpc_namespaces:
                if ns in rpc_routes:
                    raise ManifestError(
                        f"rpc_namespace '{ns}' claimed by app '{name}' conflicts with core routing table")
                rpc_routes[ns] = "kb"
            continue
        env_key = _ENV_URL_OVERRIDES.get(name)
        url = (os.environ.get(env_key) if env_key and os.environ.get(env_key) else m.service_url)
        service_urls[name] = url
        health_targets[name] = url
        for ns in m.rpc_namespaces:
            if ns in rpc_routes:
                raise ManifestError(
                    f"rpc_namespace '{ns}' claimed by app '{name}' conflicts with core routing table "
                    f"or an earlier app")
            rpc_routes[ns] = name
        for p in m.api_prefixes:
            prefix_targets.append((p, name))

    # 最长前缀优先（保持现状精确前缀清单语义；匹配算法不变）
    prefix_targets.sort(key=lambda t: len(t[0]), reverse=True)

    # 事件桥 PUB 端口：kb + llm + agent 固定 env + app manifest pub_port（docs=5683 等）
    env_ports = os.environ.get("EVENT_PUB_PORTS")
    if env_ports:
        event_ports = tuple(int(p) for p in env_ports.split(",") if p)
    else:
        event_ports = [
            int(os.environ.get("KB_PUB_PORT", "5681")),
            int(os.environ.get("LLM_PUB_PORT", "5682")),
            int(os.environ.get("AGENT_PUB_PORT", "5684")),
        ]
        for m in apps.values():
            if m.pub_port:
                event_ports.append(m.pub_port)
        event_ports = tuple(dict.fromkeys(event_ports))

    return service_urls, rpc_routes, prefix_targets, health_targets, event_ports


_SERVICE_URLS, _RPC_ROUTES, _PREFIX_TARGETS, _HEALTH_TARGETS, EVENT_PUB_PORTS = _load_registry()

EVENT_TOPICS = ("task", "project", "backend", "llm", "agent")

# method 黑名单：进程控制命名空间不对 Web 暴露（进程由 supervisor/CLI 管理）。
# plugin.* 在 kb 服务真实提供（服务端模块管理），Web 模式放行。
_BLOCKED_METHODS = ("backend",)

# ── 鉴权 ────────────────────────────────────────────────────────────

def _token_path(data_dir: str = None) -> str:
    base = data_dir or os.environ.get("TOPOCODE_DB_DIR") or os.path.join(
        os.path.expanduser("~"), ".topocode")
    return os.path.join(base, "token")


def _read_token() -> str | None:
    try:
        p = _token_path()
        if os.path.isfile(p):
            with open(p) as f:
                tok = f.read().strip()
                return tok or None
    except Exception:
        pass
    return None


def _is_static_path(path: str) -> bool:
    """SPA/静态资源路径不鉴权（浏览器直载 HTML/CSS/JS 无法带 header）。
    业务 API（/api/*）与 /ws/events 一律鉴权。"""
    if path == "/" or path == "/health" or path == "/api/health":
        return True
    if path.startswith("/web/") or path.startswith("/static/") or path.startswith("/app/"):
        return True
    if path in ("/architect", "/architect/", "/viewer", "/chat", "/web-root", "/doc", "/code",
                "/projects", "/home", "/app"):
        return True
    return False


def _check_auth(request: Request):
    if _is_static_path(request.url.path):
        return
    token = _read_token()
    if not token:
        # 未生成 token 时放行（首次启动/开发模式）；生成后即强制
        return
    header = request.headers.get("authorization", "")
    q_token = request.query_params.get("token", "")
    if header == f"Bearer {token}" or q_token == token:
        return
    raise HTTPException(401, "unauthorized: missing or invalid token")


async def auth_middleware(request: Request, call_next):
    """全局鉴权中间件：业务 API 与 /ws/events 一律校验 token（静态/健康除外）。"""
    path = request.url.path
    if (path.startswith("/api/") and not _is_static_path(path)) or path == "/ws/events":
        try:
            _check_auth(request)
        except HTTPException as e:
            return Response(content=json.dumps({"detail": e.detail}),
                            status_code=e.status_code,
                            media_type="application/json")
    return await call_next(request)


# ── 反向代理助手（httpx 流式，支持 chat SSE text/event-stream） ──────

_PROXY_TIMEOUT = 120.0
_STRIP_REQ_HEADERS = ("host", "content-length", "connection", "upgrade")
# httpx 已透明解压（aiter_bytes）；这些头若透传会让客户端二次解压/长度错配
_STRIP_RESP_HEADERS = ("content-encoding", "content-length", "transfer-encoding", "connection")


async def _proxy(target: str, request: Request,
                 path_override: str | None = None):
    """把当前请求**流式**转发到 target（保留 method/query/body/headers）。

    用 httpx streaming：chat 的 SSE（text/event-stream）逐块透传不被缓冲；
    普通 JSON 响应同样正确（单块）。client 在流结束前保持打开（生成器 finally 关闭）。
    """
    _check_auth(request)
    import httpx
    from fastapi.responses import StreamingResponse

    body = await request.body()
    url = target + (path_override or request.url.path)
    if request.query_params:
        url += "?" + str(request.query_params)
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in _STRIP_REQ_HEADERS}
    client = httpx.AsyncClient(timeout=httpx.Timeout(_PROXY_TIMEOUT, read=None))
    try:
        req = client.build_request(request.method, url, content=body or None, headers=headers)
        upstream = await client.send(req, stream=True)
    except httpx.RequestError as e:
        await client.aclose()
        logger.warning(f"[gateway] proxy {url} failed: {e}")
        return Response(content=json.dumps({"error": str(e)}), status_code=502,
                        media_type="application/json")

    async def _iter():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    resp_headers = {k: v for k, v in upstream.headers.items()
                    if k.lower() not in _STRIP_RESP_HEADERS}
    return StreamingResponse(_iter(), status_code=upstream.status_code, headers=resp_headers)


# ── 聚合健康（manifest 内全部 service app + kb + gateway 自身） ─────

def _probe_service(url: str) -> dict:
    """同步探测（requests 阻塞）；经 asyncio.to_thread 调用以免阻塞事件循环。"""
    import requests
    import time as _time
    t0 = _time.monotonic()
    try:
        resp = requests.get(url + "/health", timeout=2)
        return {"status": "ok" if resp.status_code < 500 else "degraded",
                "latency_ms": int((_time.monotonic() - t0) * 1000)}
    except Exception:
        return {"status": "down", "latency_ms": None}


@router.get("/api/health", include_in_schema=False)
async def api_health():
    """网关聚合健康端点（免鉴权，见 _is_static_path）。
    前端 `backend.getStatus` 轮询此端点判断后端存活（顶层 status = gateway 自身存活）。"""
    results = await asyncio.gather(
        *(asyncio.to_thread(_probe_service, url) for url in _HEALTH_TARGETS.values()))
    services = {name: res for name, res in zip(_HEALTH_TARGETS, results)}
    return {"status": "ok", "service": "gateway", "services": services}


# ── RPC 路由 ────────────────────────────────────────────────────────

@router.post("/api/rpc/{method}")
async def rpc(method: str, request: Request):
    """`/api/rpc/{method}` — 命名空间路由 + method 黑名单"""
    _check_auth(request)
    ns = method.split(".")[0] if "." in method else method
    if ns in _BLOCKED_METHODS:
        raise HTTPException(403, f"method '{method}' is not exposed to web")
    svc = _RPC_ROUTES.get(ns)
    if not svc:
        raise HTTPException(404, f"method namespace '{ns}' not found")
    target = _SERVICE_URLS[svc]
    # 服务端 data_api/zmq 执行端点为 POST /zmq/{method}
    return await _proxy(target, request, path_override=f"/zmq/{method}")


# ── 上传：结构分析包（浏览器上传到服务器） ─────────────────────────

@router.post("/api/upload/archive", include_in_schema=False)
async def upload_archive(file: UploadFile = File(...)):
    """接收结构分析包上传（multipart），存入服务端 uploads 目录，返回服务器路径。

    供 Web 端「导入结构分析包」使用：浏览器无本地文件系统访问权，需先上传到
    服务器再由 system.importProjectArchive 导入。返回 {"path": <服务器绝对路径>}。
    """
    import time as _time
    base = os.environ.get("TOPOCODE_DB_DIR") or os.path.join(os.path.expanduser("~"), ".topocode")
    uploads_dir = os.path.join(base, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    name = os.path.basename(file.filename or "archive.zip")
    if not name:
        name = "archive.zip"
    dest = os.path.join(uploads_dir, f"{int(_time.time() * 1000)}_{name}")

    def _copy():
        # 同步磁盘 IO 必须放线程池：大文件上传若直接在事件循环线程拷贝会阻塞整个网关
        import shutil
        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out)

    try:
        await asyncio.to_thread(_copy)
    finally:
        try:
            file.file.close()
        except Exception:
            pass
    return {"path": dest, "name": name, "size": os.path.getsize(dest)}


# ── 反向代理：manifest api_prefixes（动态注册，M06） ─────────────────
# 每个 app 前缀注册：精确路由 + （前缀下无其它 manifest 前缀时）子路径路由，
# 保持现状精确前缀清单语义（最长前缀优先）。

_ALL_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


def _make_prefix_proxy(svc_name: str):
    async def _proxy_handler(request: Request, path: str = ""):
        return await _proxy(_SERVICE_URLS[svc_name], request)
    return _proxy_handler


for _prefix, _svc in _PREFIX_TARGETS:
    _has_child = any(p != _prefix and p.startswith(_prefix + "/")
                     for p, _ in _PREFIX_TARGETS)
    router.add_api_route(_prefix, _make_prefix_proxy(_svc),
                         methods=_ALL_METHODS, include_in_schema=False)
    if not _has_child:
        router.add_api_route(_prefix + "/{path:path}", _make_prefix_proxy(_svc),
                             methods=_ALL_METHODS, include_in_schema=False)


# ── WebSocket 代理：architect（/api/architect/ws/*） ─────────────────

async def _ws_proxy(websocket: WebSocket, path: str):
    """把 /api/architect/ws/* 转发到 architect 服务（双向）。"""
    _check_auth_ws(websocket)
    target = _SERVICE_URLS["architect"].replace("http", "ws") + f"/api/architect/ws/{path}"
    try:
        import websockets
    except ImportError:
        await websocket.close(code=1011)
        return
    await websocket.accept()
    try:
        async with websockets.connect(target) as upstream:
            async def _up():
                try:
                    while True:
                        msg = await upstream.recv()
                        await websocket.send_text(msg)
                except Exception:
                    pass
            task = asyncio.create_task(_up())
            try:
                while True:
                    msg = await websocket.receive_text()
                    await upstream.send(msg)
            except WebSocketDisconnect:
                pass
            finally:
                task.cancel()
    except Exception as e:
        logger.warning(f"[gateway] architect ws proxy failed: {e}")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


def _check_auth_ws(websocket: WebSocket):
    token = _read_token()
    if not token:
        return
    q = websocket.query_params.get("token", "")
    h = websocket.headers.get("authorization", "")
    if q == token or h == f"Bearer {token}":
        return
    raise HTTPException(401, "unauthorized")


@router.websocket("/api/architect/ws/{path:path}")
async def ws_architect(websocket: WebSocket, path: str):
    await _ws_proxy(websocket, path)


# ── 事件桥：/ws/events（ZMQ-SUB → WS，多 topic） ─────────────────────

async def _event_bridge_loop(websocket: WebSocket):
    """订阅各服务 ZMQ PUB(task/project/backend/llm/agent)，转发 {topic,eventType,data}。"""
    import zmq
    import zmq.asyncio

    ctx = zmq.asyncio.Context.instance()
    sock = ctx.socket(zmq.SUB)
    try:
        for t in EVENT_TOPICS:
            sock.setsockopt(zmq.SUBSCRIBE, t.encode())
        sock.setsockopt(zmq.LINGER, 0)
        for port in EVENT_PUB_PORTS:
            sock.connect(f"tcp://127.0.0.1:{port}")
        while True:
            try:
                frames = await asyncio.wait_for(sock.recv_multipart(), timeout=1.0)
            except asyncio.TimeoutError:
                # 心跳保活
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    return
                continue
            except Exception:
                await asyncio.sleep(0.5)
                continue
            if len(frames) < 3:
                continue
            topic = frames[0].decode("utf-8", "replace")
            event_type = frames[1].decode("utf-8", "replace")
            try:
                data = json.loads(frames[2].decode("utf-8"))
            except Exception:
                data = {}
            try:
                await websocket.send_text(json.dumps({
                    "topic": topic, "eventType": event_type, "data": data,
                }))
            except Exception:
                return
    finally:
        try:
            sock.close(linger=0)
        except Exception:
            pass


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    _check_auth_ws(websocket)
    await websocket.accept()
    try:
        await _event_bridge_loop(websocket)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[gateway] /ws/events error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
