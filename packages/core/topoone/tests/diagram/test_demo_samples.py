"""Live render of the demo flowchart sample (schema + animation block) through a fresh
pool, i.e. the CURRENT bundle. Run: python3 -m pytest tests/test_demo_samples.py -q"""

import json
import pytest
from fastapi.testclient import TestClient

from ._harness import create_app
from topoone.diagram.diagrams import DiagramSettings

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

FLOWCHART_SAMPLE = {
    "version": 1,
    "type": "flowchart",
    "title": "Order flow",
    "direction": "TB",
    "nodes": [
        {"id": "start", "label": "Submit order", "kind": "stadium"},
        {"id": "pay", "label": "Pay", "kind": "rect"},
        {"id": "ok", "label": "Paid?", "kind": "diamond"},
        {"id": "retry", "label": "Retry", "kind": "round"},
        {"id": "stock", "label": "Pick & pack", "kind": "rect"},
        {"id": "ship", "label": "Ship", "kind": "rect"},
        {"id": "done", "label": "Done", "kind": "stadium"},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "pay"},
        {"id": "e2", "from": "pay", "to": "ok"},
        {"id": "e3", "from": "ok", "to": "stock", "label": "yes"},
        {"id": "e4", "from": "ok", "to": "retry", "label": "no", "kind": "dashed"},
        {"id": "e5", "from": "retry", "to": "pay", "kind": "dashed"},
        {"id": "e6", "from": "stock", "to": "ship"},
        {"id": "e7", "from": "ship", "to": "done"},
    ],
    "groups": [{"id": "g1", "label": "Fulfillment", "contains": ["stock", "ship"]}],
    "animation": {
        "mode": "reveal",
        "stepMs": 650,
        "steps": [
            {"label": "entry", "nodes": ["start", "pay"]},
            {"label": "payment decision", "nodes": ["ok", "retry"]},
            {"label": "fulfillment", "nodes": ["stock", "ship"]},
            {"label": "done", "nodes": ["done"]},
        ],
    },
}


@pytest.fixture(scope="module")
def client():
    diag = DiagramSettings(plantuml_jar=VENDOR_JAR, render_pool_size=1)
    with TestClient(create_app(diag=diag)) as c:
        yield c


def test_flowchart_sample_with_animation_renders(client: TestClient):
    r = client.post("/topo/render/schema", json={"schema": FLOWCHART_SAMPLE, "engine": "auto"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "<svg" in body["svg"]
    # the animation block must not produce degradation warnings
    assert body["warnings"] == []


def test_flowchart_sample_passes_validate(client: TestClient):
    r = client.post("/topo/validate", json={"schema": FLOWCHART_SAMPLE})
    assert r.status_code == 200
    assert r.json()["ok"] is True, r.text
