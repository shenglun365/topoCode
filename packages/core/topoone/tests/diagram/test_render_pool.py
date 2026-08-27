"""Integration: real chromium render pool against a live uvicorn app.

Skipped when playwright/chromium or the built web bundle is unavailable.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import urllib.request
import pytest
import uvicorn

from ._harness import create_app
from topoone.diagram.diagrams import DiagramServices, DiagramSettings

from .conftest import PLANTUML_JAR as VENDOR_JAR
from .conftest import WEB_BUNDLE as BUNDLE


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_chromium_available() and BUNDLE.exists()),
    reason="needs playwright chromium + built web bundle (pnpm build:browser)",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    port = _free_port()
    diag = DiagramSettings(render_pool_size=1, render_bundle=BUNDLE, plantuml_jar=VENDOR_JAR)
    services = DiagramServices(diag)
    app = create_app(services=services)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    body: dict = {}
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as r:
                body = json.load(r)
            if body.get("render", {}).get("available"):
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not body.get("render", {}).get("available"):
        pytest.fail(f"render pool did not start: {body.get('render')}")

    yield url
    srv.should_exit = True
    thread.join(timeout=15)


def _post(url: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{url}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def _post_error(url: str, path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{url}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_render_mermaid_flowchart(server_url):
    body = _post(server_url, "/topo/render/mermaid", {"code": "flowchart TD\n  A[Start] --> B{ok?}\n  B -->|yes| C[Done]"})
    assert "<svg" in body["svg"]
    assert "Start" in body["svg"]


def test_render_mermaid_sequence(server_url):
    body = _post(server_url, "/topo/render/mermaid", {"code": "sequenceDiagram\n  A->>B: hello\n  B-->>A: hi"})
    assert "<svg" in body["svg"]


def test_render_mermaid_gantt(server_url):
    code = "gantt\n  title R\n  section S\n  Task A :a, 2024-01-01, 10d\n  Task B :b, after a, 5d"
    body = _post(server_url, "/topo/render/mermaid", {"code": code})
    assert "Task A" in body["svg"]


def test_render_schema_auto_flowchart(server_url):
    schema = {
        "version": 1,
        "type": "flowchart",
        "nodes": [{"id": "a", "label": "Start"}, {"id": "b", "label": "Done"}],
        "edges": [{"from": "a", "to": "b"}],
    }
    body = _post(server_url, "/topo/render/schema", {"schema": schema, "engine": "auto"})
    assert body["engine"] in ("mermaid", "plantuml")
    assert "<svg" in body["svg"]


def test_render_schema_plantuml_sequence(server_url):
    schema = {
        "version": 1,
        "type": "sequence",
        "participants": [
            {"id": "u", "label": "User", "type": "actor"},
            {"id": "s", "label": "Server", "type": "participant"},
        ],
        "messages": [
            {"from": "u", "to": "s", "label": "GET /api", "kind": "sync"},
            {"from": "s", "to": "u", "label": "200 OK", "kind": "return"},
        ],
    }
    body = _post(server_url, "/topo/render/schema", {"schema": schema, "engine": "plantuml"})
    assert body["engine"] == "plantuml"
    assert "data-entity-uid" in body["svg"]
    assert "GET /api" in body["svg"]


def test_render_schema_gantt_picks_mermaid(server_url):
    schema = {
        "version": 1,
        "type": "gantt",
        "title": "R",
        "sections": [{"id": "s1", "label": "Core"}],
        "tasks": [{"id": "t1", "title": "Alpha", "section": "s1", "start": "2024-01-01", "duration": 5}],
    }
    body = _post(server_url, "/topo/render/schema", {"schema": schema, "engine": "auto"})
    assert body["engine"] == "mermaid"
    assert "Alpha" in body["svg"]


def test_render_bad_mermaid_code_returns_400(server_url):
    status, body = _post_error(server_url, "/topo/render/mermaid", {"code": "flowchart TD\n  A[unclosed"})
    assert status == 400
    assert "detail" in body


def test_export_report_full_html(server_url):
    payload = {
        "title": "M7 check",
        "diagrams": [
            {"title": "Flow", "engine": "mermaid", "code": "flowchart TD\n  A[Start] --> B[Done]"},
            {
                "title": "Seq",
                "engine": "plantuml",
                "schema": {
                    "version": 1,
                    "type": "sequence",
                    "participants": [
                        {"id": "u", "label": "User", "type": "actor"},
                        {"id": "s", "label": "Server", "type": "participant"},
                    ],
                    "messages": [
                        {"from": "u", "to": "s", "label": "GET /api", "kind": "sync"},
                        {"from": "s", "to": "u", "label": "200 OK", "kind": "return"},
                    ],
                },
            },
        ],
    }
    req = urllib.request.Request(
        f"{server_url}/topo/export/report",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        html_text = r.read().decode()
        ctype = r.headers["Content-Type"]

    assert ctype.startswith("text/html")
    assert "<h1>M7 check</h1>" in html_text
    assert "2 diagram(s)" in html_text
    assert html_text.count("<svg") >= 2
    assert 'class="td-badge">mermaid' in html_text
    assert 'class="td-badge">plantuml' in html_text
    # animation plans were captured and embedded (sequence has participants + 2 messages)
    assert "data-anim-mode=" in html_text
    assert "data-td-anim-step=" in html_text
    # the plantuml diagram rendered through the sidecar
    assert "data-entity-uid" in html_text
    assert "GET /api" in html_text
    # playback controller embedded
    assert "td-btn-play" in html_text


class _NeverRetrievedCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if "exception was never retrieved" in record.getMessage():
            self.records.append(record.getMessage())


def _quiet_stop(services: DiagramServices, kill_driver_first: bool) -> None:
    """Run start -> (kill driver) -> stop and assert no dangling-future noise."""
    import asyncio
    import gc

    capture = _NeverRetrievedCapture()
    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.addHandler(capture)
    try:
        async def scenario() -> None:
            await services.start()
            pool = services.pool
            assert pool is not None and pool.available, f"pool down: {pool.error if pool else None}"
            if kill_driver_first:
                # Terminal Ctrl+C SIGINTs the whole foreground process group: the
                # playwright node driver (a grandchild) dies before graceful stop.
                proc = pool._pw._impl_obj._connection._transport._proc
                proc.kill()
                await asyncio.sleep(0.5)
            await services.stop()

        asyncio.run(scenario())
        gc.collect()
        gc.collect()
    finally:
        asyncio_logger.removeHandler(capture)
    assert not capture.records, capture.records


def test_stop_after_driver_death_is_quiet():
    diag = DiagramSettings(render_pool_size=1, render_bundle=BUNDLE, plantuml_enabled=False)
    _quiet_stop(DiagramServices(diag), kill_driver_first=True)


def test_normal_stop_is_quiet():
    diag = DiagramSettings(render_pool_size=1, render_bundle=BUNDLE, plantuml_enabled=False)
    _quiet_stop(DiagramServices(diag), kill_driver_first=False)
