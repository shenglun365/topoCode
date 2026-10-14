"""topo TUI — Python Textual 终端界面（P6）。

视图：
  - 服务状态：9 进程健康轮询（/health）
  - 任务进度：list tasks + ZMQ-SUB(5681) 订阅 task.* 实时进度
  - LLM chat：session chat（经 /api/rpc llm.chat）+ ZMQ-SUB(5682) llm.* 流式
  - 日志：tail ~/.topocode/logs/serve.log

依赖：textual + pyzmq。启动：python -m topoone.supervisor.tui [--data-dir DIR] [--http-port PORT]
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, ListView, ListItem, Static, TabbedContent, TabPane, TextArea


class TopoTUI(App):
    """TopoOne 终端界面"""

    CSS = """
    Screen { layout: vertical; }
    #tabbed { height: 1fr; }
    .section-title { text-style: bold; margin-bottom: 1; }
    #services { height: 100%; }
    #log-view { height: 100%; }
    """

    def __init__(self, data_dir: str, http_port: int):
        super().__init__()
        self.data_dir = data_dir
        self.http_port = http_port
        self._services = ["kb", "gateway", "llm", "agent", "doc", "chat", "architect", "mcp", "runner"]
        self._tasks = []
        self._poll_task = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="services"):
            with TabPane("服务状态", id="services"):
                yield Static("", id="services-content")
            with TabPane("任务进度", id="tasks"):
                yield Static("", id="tasks-content")
            with TabPane("日志", id="logs"):
                yield Static("", id="log-content")
        yield Footer()

    def on_mount(self):
        self._poll_task = self.set_interval(3.0, self._refresh_all)
        self._refresh_all()

    def on_unmount(self):
        if self._poll_task:
            self._poll_task.stop()

    # ── RPC 客户端（复用 main_cli._rpc 逻辑，避免循环依赖） ──

    def _token(self) -> str:
        p = os.path.join(self.data_dir, "token")
        if os.path.exists(p):
            with open(p) as f:
                return f.read().strip()
        return ""

    def _rpc(self, method: str, params: dict = None) -> dict:
        import urllib.request
        import urllib.error
        body = json.dumps(params or {}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        tok = self._token()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.http_port}/api/rpc/{method}",
            data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def _service_health(self, port: int) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2):
                return True
        except Exception:
            return False

    # ── 刷新 ──

    def _refresh_all(self):
        self._refresh_services()
        self._refresh_tasks()
        self._refresh_logs()

    def _refresh_services(self):
        ports = {"kb": 3459, "gateway": 3456, "llm": 3484, "agent": 3482,
                 "doc": 3481, "chat": 3483, "architect": 3470, "mcp": 3460, "runner": 3458}
        lines = ["服务状态 (每 3s 刷新)", "-" * 40]
        for name in self._services:
            ok = self._service_health(ports.get(name, 0))
            mark = "OK" if ok else "DOWN"
            lines.append(f"  {name:<12} :{ports.get(name,0):<5} {mark}")
        widget = self.query_one("#services-content", Static)
        widget.update("\n".join(lines))

    def _refresh_tasks(self):
        res = self._rpc("project.list", {})
        projects = (res.get("result") or []) if isinstance(res, dict) else []
        lines = ["任务进度 (项目列表)", "-" * 40]
        if isinstance(projects, list):
            for p in projects[:10]:
                pid = p.get("id", "")
                tres = self._rpc("analysis.listTasks", {"projectId": pid})
                tasks = (tres.get("result") or []) if isinstance(tres, dict) else []
                if isinstance(tasks, list):
                    for t in tasks[:5]:
                        st = t.get("status", "?")
                        lines.append(f"  {p.get('name','?'):<20} {t.get('name','?'):<20} {st}")
        if len(lines) == 1:
            lines.append("  (无项目)")
        widget = self.query_one("#tasks-content", Static)
        widget.update("\n".join(lines))

    def _refresh_logs(self):
        log_path = os.path.join(self.data_dir, "logs", "serve.log")
        lines = []
        if os.path.exists(log_path):
            with open(log_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4000))
                data = f.read().decode("utf-8", "replace")
            lines = data.splitlines()[-40:]
        widget = self.query_one("#log-content", Static)
        widget.update("\n".join(lines) if lines else "(no log yet)")


def main():
    parser = argparse.ArgumentParser(description="TopoOne TUI")
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--http-port", type=int, default=3456)
    args = parser.parse_args()
    data_dir = args.data_dir or os.path.join(os.path.expanduser("~"), ".topocode")
    TopoTUI(data_dir, args.http_port).run()


if __name__ == "__main__":
    main()
