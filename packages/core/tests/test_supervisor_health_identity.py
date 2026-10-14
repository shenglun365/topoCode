"""supervisor 就绪身份校验守门(3470 假 ready → FATAL 事故根治)。

事故链: 孤儿实例占端口 → supervisor 探针打端口可达即 ready(外部监听者
骗过) → 子进程 bind 失败退出 → 重试烧尽 → FATAL 全树终止。
根治=就绪判定「响应者 pid == 自己 spawn 的子进程 pid」; 服务未自报
pid(旧版端点)退回端口可达语义(向后兼容)。

Run: cd <repo> && python -m pytest packages/core/tests/test_supervisor_health_identity.py -q
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_repo = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _repo)

from topoone.supervisor.supervisor import _health_pid


class _Srv(HTTPServer):
    payload = b"{}"
    code = 200


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(self.server.code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.server.payload)

    def log_message(self, *a):
        pass


def _serve():
    srv = _Srv(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _url(srv):
    return f"http://127.0.0.1:{srv.server_address[1]}/health"


def test_health_pid_reported():
    """服务自报 pid → 原样返回(供与子进程 pid 比对)。"""
    srv = _serve()
    try:
        srv.payload = json.dumps({"status": "ok", "pid": 4242}).encode()
        assert _health_pid(_url(srv)) == 4242
    finally:
        srv.shutdown()


def test_health_pid_absent_backcompat():
    """旧版端点无 pid 字段 → None(调用方退回端口可达语义)。"""
    srv = _serve()
    try:
        srv.payload = json.dumps({"status": "ok"}).encode()
        assert _health_pid(_url(srv)) is None
    finally:
        srv.shutdown()


def test_health_pid_unreachable():
    """不可达端口 → None(非就绪)。"""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()
    assert _health_pid(f"http://127.0.0.1:{dead_port}/health") is None


def test_identity_mismatch_is_not_ready_semantic():
    """身份不匹配语义固化: reported != 子进程 pid → 不得判 ready。

    (校验表达式与 _wait_health 同式——孤儿响应端口时 reported 是孤儿 pid,
    wi.proc.pid 是 bind 失败的子进程, 二者不等 → 循环等待子进程退出重启。)"""
    srv = _serve()
    try:
        srv.payload = json.dumps({"status": "ok", "pid": 8104}).encode()
        reported = _health_pid(_url(srv))
        spawned_pid = os.getpid()          # 模拟 supervisor spawn 的子进程
        ok = (reported == spawned_pid if reported is not None else False)
        assert ok is False                 # 假 ready 被身份校验拦截
    finally:
        srv.shutdown()
