import pytest
from fastapi.testclient import TestClient

from ._harness import create_app
from .conftest import PLANTUML_JAR as VENDOR_JAR

pytestmark = pytest.mark.skipif(not VENDOR_JAR.exists(), reason="plantuml jar not present")
from topoone.diagram.diagrams import DiagramSettings

CODE_OK = "@startuml\nAlice -> Bob: hello\n@enduml"
CODE_BAD = "@startuml\nfoo bar baz qux\n@enduml"


@pytest.fixture(scope="module")
def client():
    # render_pool_size=0: keep this module browser-free (see test_render_pool.py for integration).
    diag = DiagramSettings(plantuml_jar=VENDOR_JAR, render_pool_size=0)
    with TestClient(create_app(diag=diag)) as c:
        yield c


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["plantuml"] is True
    assert body["render"]["available"] is False


def test_render_svg(client: TestClient):
    r = client.post("/topo/render/plantuml", json={"code": CODE_OK})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in r.text
    assert "data-entity-uid" in r.text


def test_render_png(client: TestClient):
    r = client.post("/topo/render/plantuml", json={"code": CODE_OK, "format": "png"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_svg_kroki_alias(client: TestClient):
    """POST /topo/plantuml/svg: raw body -> image/svg+xml (engine post-raw protocol)."""
    r = client.post("/topo/plantuml/svg", content=CODE_OK.encode(), headers={"Content-Type": "text/plain"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in r.text
    assert "data-entity-uid" in r.text


def test_render_syntax_error_returns_400(client: TestClient):
    r = client.post("/topo/render/plantuml", json={"code": CODE_BAD})
    assert r.status_code == 400
    assert "Syntax Error" in str(r.json()["detail"])


def test_validate(client: TestClient):
    r = client.post("/topo/validate/plantuml", json={"code": CODE_OK})
    assert r.json() == {"valid": True, "error": None}
    r = client.post("/topo/validate/plantuml", json={"code": CODE_BAD})
    body = r.json()
    assert body["valid"] is False
    assert "Syntax Error" in body["error"]


def test_topo_health(client: TestClient):
    body = client.get("/topo/health").json()
    assert body["plantuml"] is True
    assert body["render"]["available"] is False
