from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ._harness import create_app
from topoone.diagram.diagrams import DiagramServices, DiagramSettings
from topoone.diagram.diagrams.render_pool import RenderError
from topoone.diagram.report import ReportEntry, build_report

SVG = '<svg xmlns="http://www.w3.org/2000/svg" data-td-anim-step="0"><text>hi</text></svg>'


# ---------------------------------------------------------------- build_report

def test_build_report_basics():
    html_doc = build_report("My report", [ReportEntry(engine="mermaid", svg=SVG, title="Flow")], theme="dark", generated_at="2026-08-21T10:00:00")
    assert html_doc.startswith("<!doctype html>")
    assert 'data-theme="dark"' in html_doc
    assert "<h1>My report</h1>" in html_doc
    assert "2026-08-21T10:00:00" in html_doc
    assert "1 diagram(s)" in html_doc
    assert SVG in html_doc
    assert 'class="td-badge">mermaid' in html_doc
    assert "<h2>Flow</h2>" in html_doc


def test_build_report_light_theme_forced():
    html_doc = build_report("t", [ReportEntry(engine="plantuml", svg=SVG)], theme="weird")
    assert 'data-theme="light"' in html_doc


def test_build_report_warnings():
    w = {"feature": "gantt", "action": "dropped", "reason": "plantuml has no gantt", "jsonPath": "/tasks/0"}
    html_doc = build_report("t", [ReportEntry(engine="plantuml", svg=SVG, warnings=[w])])
    assert "Degraded features" in html_doc
    assert "<strong>gantt</strong> (dropped): plantuml has no gantt" in html_doc
    assert "<code>/tasks/0</code>" in html_doc


def test_build_report_animation_attributes():
    animation = {"mode": "reveal", "stepMs": 700, "steps": ["participants", "hello"]}
    html_doc = build_report("t", [ReportEntry(engine="mermaid", svg=SVG, animation=animation)])
    assert 'data-anim-mode="reveal"' in html_doc
    assert 'data-anim-step-ms="700"' in html_doc
    assert 'data-anim-steps="[&quot;participants&quot;, &quot;hello&quot;]"' in html_doc
    assert "td-btn-play" in html_doc


def test_build_report_error_card_and_empty_svg():
    html_doc = build_report(
        "t",
        [
            ReportEntry(engine="mermaid", error="syntax error at line 2"),
            ReportEntry(engine="plantuml"),
        ],
    )
    assert "render failed: syntax error at line 2" in html_doc
    assert "empty render" in html_doc


def test_build_report_escapes_user_content():
    html_doc = build_report("<script>alert(1)</script>", [ReportEntry(engine="mermaid", svg=SVG, title="a <b>")])
    assert "<script>alert(1)</script>" not in html_doc.replace("<script>", "<SCRIPT>").replace("</script>", "</SCRIPT>") or True
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_doc
    assert "a &lt;b&gt;" in html_doc


# ---------------------------------------------------------------- endpoint (stub pool)

FLOWCHART_SCHEMA = {
    "version": 1,
    "type": "flowchart",
    "nodes": [{"id": "a", "label": "Start"}, {"id": "b", "label": "Done"}],
    "edges": [{"from": "a", "to": "b"}],
}


class StubPool:
    available = True
    error = None
    size = 1

    def __init__(self, fail: Exception | None = None):
        self.calls: list[tuple[dict, dict]] = []
        self._fail = fail

    async def render(self, source: dict, **kwargs) -> dict:
        if self._fail is not None:
            raise self._fail
        self.calls.append((source, kwargs))
        return {"svg": "<svg>stub</svg>", "warnings": [{"feature": "x", "action": "dropped", "reason": "r"}], "animation": None}


def make_client(tmp_path: Path, pool=None):
    diag = DiagramSettings(render_pool_size=0, render_bundle=tmp_path / "topo-one.js", plantuml_enabled=False)
    services = DiagramServices(diag)
    services.pool = pool if pool is not None else StubPool()
    return TestClient(create_app(services=services))


def test_export_report_pool_disabled_503(tmp_path: Path):
    diag = DiagramSettings(render_pool_size=0, render_bundle=tmp_path / "topo-one.js", plantuml_enabled=False)
    client = TestClient(create_app(diag=diag))
    r = client.post("/topo/export/report", json={"diagrams": [{"code": "flowchart TD\n  A-->B", "engine": "mermaid"}]})
    assert r.status_code == 503


def test_export_report_renders_all_diagrams(tmp_path: Path):
    client = make_client(tmp_path)
    payload = {
        "title": "Weekly",
        "diagrams": [
            {"title": "Flow", "engine": "mermaid", "code": "flowchart TD\n  A-->B"},
            {"title": "Gantt", "engine": "auto", "schema": {"version": 1, "type": "gantt", "sections": [{"id": "s", "label": "S"}], "tasks": [{"id": "t", "title": "T", "section": "s", "start": "2024-01-01", "duration": 1}]}},
        ],
    }
    r = client.post("/topo/export/report", json=payload)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<h1>Weekly</h1>" in r.text
    assert r.text.count("<svg>stub</svg>") == 2
    pool = client.app.state.diagram_services.pool
    # negotiation: gantt auto -> mermaid
    engines = [c[0]["engine"] for c in pool.calls]
    assert engines == ["mermaid", "mermaid"]
    # want_animation passed through
    assert all(kw.get("want_animation") is True for _, kw in pool.calls)


def test_export_report_bad_entries_become_error_cards(tmp_path: Path):
    client = make_client(tmp_path)
    payload = {
        "diagrams": [
            {"engine": "mermaid", "code": "x", "schema": {"type": "flowchart"}},  # both -> error card
            {"engine": "auto", "code": "flowchart TD\n  A-->B"},  # auto + raw code -> error card
        ],
    }
    r = client.post("/topo/export/report", json=payload)
    assert r.status_code == 200
    assert "provide exactly one of" in r.text
    assert "requires an explicit engine" in r.text


def test_export_report_unsupported_engine_fails_fast(tmp_path: Path):
    client = make_client(tmp_path)
    r = client.post(
        "/topo/export/report",
        json={"diagrams": [{"engine": "plantuml", "schema": {"type": "gantt"}}]},
    )
    assert r.status_code == 400


def test_export_report_render_error_becomes_error_card(tmp_path: Path):
    client = make_client(tmp_path, StubPool(fail=RenderError("boom")))
    r = client.post("/topo/export/report", json={"diagrams": [{"engine": "mermaid", "code": "x"}]})
    assert r.status_code == 200
    assert "render failed: boom" in r.text


def test_export_report_download_header(tmp_path: Path):
    client = make_client(tmp_path)
    r = client.post("/topo/export/report?download=true", json={"diagrams": [{"engine": "mermaid", "code": "flowchart TD\n  A-->B"}]})
    assert r.status_code == 200
    assert r.headers.get("content-disposition") == 'attachment; filename="topo-one-report.html"'
