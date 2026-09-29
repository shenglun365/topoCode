"""异步渲染任务层(render_jobs)特征测试 —— 用户契约:
后台异步 CLI / 支持缓存 / 不阻塞 / 页面刷新不中断(幂等恢复)。
"""
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from topoone.diagram.diagrams.render_jobs import RenderJobManager, render_job_key


SVG_A = "<svg>A</svg>"
SVG_B = "<svg>B</svg>"


class FakeRenderer:
    """可控渲染器: 手动放行/失败, 记录调用。"""

    def __init__(self):
        self.calls: list[str] = []
        self.gate: dict[str, list] = {}   # code -> [event, result|exc]

    def __call__(self, code: str, fmt: str = "svg") -> bytes:
        self.calls.append(code)
        gate = self.gate.get(code)
        if gate:
            evt, result = gate
            evt.set()
            if isinstance(result, Exception):
                raise result
            return result.encode("utf-8")
        return f"<svg>{code}</svg>".encode("utf-8")


def test_submit_returns_immediately_and_job_completes():
    r = FakeRenderer()
    m = RenderJobManager(r)
    out = m.submit("graph A")
    assert out["status"] in ("queued", "running", "done")
    for _ in range(100):
        if m.status(out["jobId"])["status"] == "done":
            break
        time.sleep(0.01)
    st = m.status(out["jobId"])
    assert st["status"] == "done" and st["svg"] == "<svg>graph A</svg>"


def test_idempotent_same_source_same_job_and_cached():
    r = FakeRenderer()
    m = RenderJobManager(r)
    j1 = m.submit("dup")
    for _ in range(100):
        if m.status(j1["jobId"])["status"] == "done":
            break
        time.sleep(0.01)
    j2 = m.submit("dup")
    assert j2["jobId"] == j1["jobId"]
    assert j2["status"] == "done" and j2["cached"] is True
    assert j2["svg"] == "<svg>dup</svg>"
    assert r.calls.count("dup") == 1  # 渲染只执行一次


def test_queue_dedup_while_pending():
    r = FakeRenderer()
    evt = threading.Event()
    r.gate["slow"] = [evt, SVG_A]
    m = RenderJobManager(r)
    j1 = m.submit("slow")
    j2 = m.submit("slow")          # 仍在队列/运行中 → 幂等同 jobId
    assert j2["jobId"] == j1["jobId"]
    evt.set()


def test_error_job_retriable():
    r = FakeRenderer()
    evt = threading.Event()
    r.gate["bad"] = [evt, RuntimeError("syntax error at line 2")]
    m = RenderJobManager(r)
    j1 = m.submit("bad")
    evt.set()
    for _ in range(100):
        if m.status(j1["jobId"])["status"] == "error":
            break
        time.sleep(0.01)
    st = m.status(j1["jobId"])
    assert st["status"] == "error" and "syntax error" in st["error"]
    # 重试: 重新入队(清门闩 → 第二次渲染成功)
    del r.gate["bad"]
    j2 = m.submit("bad")
    assert j2["jobId"] == j1["jobId"]
    for _ in range(100):
        if m.status(j1["jobId"])["status"] == "done":
            break
        time.sleep(0.01)
    assert m.status(j1["jobId"])["status"] == "done"


def test_persistent_cache_hit_across_managers():
    """刷新不中断的 BE 侧语义: 进程重启(新 manager)后同源文持久缓存直接命中。"""
    r1 = FakeRenderer()
    store: dict = {}
    m1 = RenderJobManager(r1,
                          cache_get=lambda k: store.get(k),
                          cache_put=lambda k, code, svg: store.__setitem__(k, svg))
    j1 = m1.submit("cached-src")
    for _ in range(100):
        if m1.status(j1["jobId"])["status"] == "done":
            break
        time.sleep(0.01)
    r2 = FakeRenderer()
    m2 = RenderJobManager(r2,
                          cache_get=lambda k: store.get(k),
                          cache_put=lambda k, code, svg: store.__setitem__(k, svg))
    j2 = m2.submit("cached-src")
    assert j2["status"] == "done" and j2["cached"] is True
    assert j2["svg"] == "<svg>cached-src</svg>"
    assert r2.calls == []  # 零渲染


def test_job_key_stable():
    assert render_job_key("x", "svg") == render_job_key("x", "svg")
    assert render_job_key("x", "svg") != render_job_key("x", "png")


def test_router_endpoints_submit_and_poll():
    """/topo/plantuml/jobs 端到端: 提交 → 轮询 → done; unknown → 404。"""
    from topoone.diagram.diagrams.router import create_topo_router

    class _Svc:
        class _Side:
            def is_up(self):
                return True

            def render(self, code, fmt="svg"):
                return f"<svg>{code}</svg>".encode("utf-8")

        sidecar = _Side()
        pool = None
        jobs = None

        def status(self):
            return {"plantuml": "up"}

    app = FastAPI()
    app.include_router(create_topo_router(_Svc(), prefix="/topo"))
    c = TestClient(app)
    sub = c.post("/topo/plantuml/jobs", json={"code": "@startuml\nA->B\n@enduml"})
    assert sub.status_code == 200
    body = sub.json()
    assert body["status"] in ("queued", "running", "done")
    job_id = body["jobId"]
    st = {"status": None}
    for _ in range(100):
        st = c.get(f"/topo/plantuml/jobs/{job_id}").json()
        if st["status"] == "done":
            break
        time.sleep(0.01)
    assert st["status"] == "done" and "<svg>" in st["svg"]
    assert c.get("/topo/plantuml/jobs/nonexistent").status_code == 404
    # 同源文重提交 → 幂等 done+cached
    again = c.post("/topo/plantuml/jobs", json={"code": "@startuml\nA->B\n@enduml"}).json()
    assert again["jobId"] == job_id and again["cached"] is True


def test_router_png_rejected_and_empty_rejected():
    from topoone.diagram.diagrams.router import create_topo_router

    class _Svc:
        sidecar = None
        pool = None
        jobs = None

        def status(self):
            return {}

    app = FastAPI()
    app.include_router(create_topo_router(_Svc(), prefix="/topo"))
    c = TestClient(app)
    assert c.post("/topo/plantuml/jobs", json={"code": "x", "format": "png"}).status_code == 400
    assert c.post("/topo/plantuml/jobs", json={"code": "   "}).status_code == 400
