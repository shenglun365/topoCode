"""内置 Git HTTP 托管（S3）— git http-backend CGI 桥。

能力：远端机器经 smart HTTP 协议 clone/fetch/push 镜像仓
  {data_dir}/git/{project}.git  ←→  http://<host>:3470/git/{project}.git

- 鉴权：Bearer ~/.topocode/token（clone 与 push 同权；GIT_COMMITTER_NAME=token）
- receive-pack：镜像仓创建时已设 http.receivepack=true（branch_service.ensure_mirror）
- 用法（远端 worker）：
    git clone http://<host>:3470/git/{project}.git
    git push http://<host>:3470/git/{project}.git  task_branch
  凭据：http://<token>@<host>:3470/... 或 credential helper。

路由挂 /git/{rest}（GET info/refs + POST upload/receive-pack）。
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

from .common import ok, err

logger = logging.getLogger(__name__)
router = APIRouter()

_GIT_BACKEND = "/usr/lib/git-core/git-http-backend"


def _git_root() -> str:
    from .ctx import data_dir
    return os.path.join(data_dir(), "git")


def _check_token(request: Request) -> bool:
    """与 architect 其余本地端点一致的 loopback 信任；非 loopback 要求 Bearer token。"""
    peer = (request.client.host if request.client else "") or ""
    if peer in ("127.0.0.1", "::1", "localhost"):
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        from .ctx import data_dir
        token_file = os.path.join(data_dir(), "token")
        try:
            return auth[7:].strip() == open(token_file).read().strip()
        except Exception:  # noqa: BLE001
            return False
    return False


def _resolve_repo(rest: str) -> Optional[str]:
    """/{project}.git/... → 本地 bare 路径（防穿越）。"""
    if not rest or ".." in rest:
        return None
    parts = rest.strip("/").split("/")
    repo = parts[0]
    if not repo.endswith(".git"):
        repo += ".git"
    repo = repo[:100]
    if any(c in repo for c in "/\\") or repo.startswith("."):
        return None
    path = os.path.join(_git_root(), repo)
    if not os.path.isdir(path):
        return None
    return path


@router.api_route("/git/{rest:path}", methods=["GET", "POST"])
async def git_http(rest: str, request: Request):
    if not _check_token(request):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    repo = _resolve_repo(rest)
    if not repo:
        return JSONResponse({"detail": "repository not found"}, status_code=404)

    subpath = "/" + rest.strip("/").split("/", 1)[1] if "/" in rest.strip("/") else "/"
    if subpath.split("?")[0] not in ("/info/refs", "/git-upload-pack",
                                     "/git-receive-pack"):
        return JSONResponse({"detail": "bad git path"}, status_code=404)

    env = dict(os.environ)
    env.update({
        "GIT_PROJECT_ROOT": _git_root(),
        "GIT_HTTP_EXPORT_ALL": "1",
        "PATH_INFO": "/" + rest.strip("/"),
        "QUERY_STRING": request.url.query,
        "REQUEST_METHOD": request.method,
        "REMOTE_USER": "topocode-agent",
        "CONTENT_TYPE": request.headers.get("Content-Type", ""),
        "GIT_HTTP_MAX_REQUEST_BUFFER": "100M",
    })
    body = b""
    if request.method == "POST":
        body = await request.body()
        env["CONTENT_LENGTH"] = str(len(body))

    try:
        proc = subprocess.Popen([_GIT_BACKEND], env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return JSONResponse({"detail": "git-http-backend 不可用"}, status_code=500)

    import asyncio

    async def _feed() -> None:
        await asyncio.to_thread(proc.stdin.write, body)
        proc.stdin.close()

    feed = asyncio.create_task(_feed())

    # 解析 CGI 头（先读完头部再流式转发 body）
    header_buf = b""

    def _read_head() -> tuple[dict, bytes]:
        nonlocal header_buf
        while b"\r\n\r\n" not in header_buf:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            header_buf += chunk
        if b"\r\n\r\n" not in header_buf:
            return {}, header_buf
        raw_head, leftover = header_buf.split(b"\r\n\r\n", 1)
        headers = {}
        for line in raw_head.decode("latin-1").split("\r\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        return headers, leftover

    headers, leftover = await asyncio.to_thread(_read_head)
    await feed

    status = int((headers.get("status") or "200").split()[0])
    resp_headers: dict[str, str] = {}
    for k in ("content-type", "cache-control", "expires", "pragma",
              "location", "content-length"):
        if k in headers:
            resp_headers[k] = headers[k]

    def _body_iter():
        if leftover:
            yield leftover
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            yield chunk
        proc.stdout.close()
        proc.wait()

    return StreamingResponse(_body_iter(), status_code=status, headers=resp_headers)


@router.get("/git")
async def git_list():
    """已托管镜像仓列表（系统管理/调试用）。"""
    root = _git_root()
    repos = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if name.endswith(".git") and os.path.isdir(os.path.join(root, name)):
                repos.append(name[:-4])
    return ok({"root": root, "repos": repos})
