"""docs 全路由 smoke（MS1 §4.1）——36 条业务路由三层断言 + 路由数守卫。

G0 路由数守卫：viewer 26 / web_root 10——MS5 拆 viewer/ 子包时路由不得意外丢失。
G1 可达性：路由存在且不 404/405。
G2 参数与兜底：GET 空参不得 422；POST 最小 body 的失败必须是业务 4xx/503，不得 500。
"""
import os

import pytest

from topoone_app_docs.viewer import router as viewer_router
from topoone_app_docs.web_root import router as web_root_router

# viewer.py:46-1219 逐条核对的 POST 最小请求（G2 用；task 系 GET 见用例内构造）
VIEWER_POSTS = [
    ("/api/plantuml/rebuild", {"code": "@startuml\nA -> B\n@enduml", "type": "auto"}),
    ("/api/mermaid/rebuild", {"code": "graph TD\n A[\"A\"] --> B[\"B\"]\n", "type": "auto"}),
    ("/api/diagram/build", {"ir": {
        "lang": "mermaid", "diagram_type": "flowchart", "direction": "TB",
        "nodes": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
        "edges": [{"from": "a", "to": "b"}], "subgraphs": [],
    }}),
    ("/api/diagram/validate", {"code": "graph TD\n A[\"A\"] --> B[\"B\"]\n", "lang": "mermaid"}),
    ("/api/diagram-editor/process", {"code": "graph TD\n A --> B\n", "instruction": "add a node"}),
    ("/api/diagram-tools/apply", {"code": "graph TD\n A --> B\n", "msg_id": "m1", "diag_id": "d1"}),
]


def _viewer_gets(task_id):
    return [
        ("/api/community-children", {"task_id": task_id}),
        ("/api/community-graph", {"task_id": task_id}),
        ("/api/file-graph", {"task_id": task_id}),
        ("/api/cascade-levels", {"task_id": task_id}),
        ("/api/heatmap", {"task_id": task_id}),
        ("/api/external-graph", {"task_id": task_id}),
        ("/api/external-stats", {"task_id": task_id}),
        ("/api/diagram/ir-docs", {}),
    ]


def test_g0_route_inventory_guard():
    """路由数守卫：viewer 26 / web_root 10（0905 的「27」系笔误，见 MS1 F1）。"""
    assert len(viewer_router.routes) == 26, \
        f"viewer 路由数意外变化: {sorted(r.path for r in viewer_router.routes)}"
    assert len(web_root_router.routes) == 10, \
        f"web_root 路由数意外变化: {sorted(r.path for r in web_root_router.routes)}"


def test_g0_scaffold_routes(client):
    """create_service_app 脚手架：/health 与 /zmq/status 可达。"""
    assert client.get("/health").status_code == 200
    assert client.get("/zmq/status").status_code == 200


def test_g1_pages(client):
    """页面路由：dist 产物存在才断 200（构建产物非 pytest 职责，缺省 skip 语义）。"""
    from topoone_app_docs.viewer._shared import STATIC_DIR

    r_doc = client.get("/doc")
    if os.path.isfile(os.path.join(STATIC_DIR, "viewer.html")):
        assert r_doc.status_code == 200
    else:
        assert r_doc.status_code == 404  # dist 未构建时的既定兜底（viewer.py:55）

    r_code = client.get("/code")
    assert r_code.status_code in (200, 404)  # code.html 当前缺位是已知状态


def test_g1_g2_viewer_gets(client, seeded_db):
    for path, params in _viewer_gets(seeded_db["task_id"]):
        r = client.get(path, params=params)
        assert r.status_code not in (404, 405, 500), f"{path} -> {r.status_code}: {r.text[:200]}"
        # 空参不得 5xx（handler 自检缺参走业务 422，如 community-children viewer.py:187）
        r_noargs = client.get(path)
        assert r_noargs.status_code in (200, 400, 422), \
            f"{path} 空参 -> {r_noargs.status_code}"


def test_g2_viewer_posts(client, seeded_db):
    for path, body in VIEWER_POSTS:
        r = client.post(path, json=body)
        assert r.status_code != 500, f"{path} -> {r.status_code}: {r.text[:300]}"


def test_g2_empty_object_posts_not_500(client, seeded_db):
    """POST 空对象 body 不得 500（业务校验给 400/422）。

    已知缺口（MS1 记档，MS5 加固候选）：viewer 各 handler 裸 `await request.json()`
    且外层 except 兜底为 500——完全无 body（非 JSON）时 FastAPI Request.json()
    抛 JSONDecodeError → 500。属系统性健壮性缺口，不在 MS1 修复面内。
    """
    for path, _ in VIEWER_POSTS:
        r = client.post(path, json={})
        assert r.status_code != 500, f"{path} 空对象 -> {r.status_code}: {r.text[:200]}"


def test_g2_missing_required_params_422(client, seeded_db):
    """显式必填参数缺失 → 422（handler 内自检的必填项）。"""
    cases = [
        ("GET", "/api/community-doc", {}),          # task_id+community_id 必填(viewer.py:75)
        ("GET", "/api/community-files", {}),        # 同上(:117)
        ("GET", "/api/file-summary", {"task_id": seeded_db["task_id"]}),  # file_path 必填(:399)
        ("GET", "/api/file", {}),                   # project_id+path 必填(Query(...))
        ("GET", "/api/tasks", {}),                  # project_id 必填(Query(...))
        ("GET", "/api/plantuml", {}),               # code 必填(Query(...))
        ("GET", "/api/graph-layout", {}),           # taskId 必填(:1173)
        ("DELETE", "/api/graph-layout", {}),        # 同上(:1204)
    ]
    for method, path, params in cases:
        r = client.request(method, path, params=params)
        assert r.status_code == 422, f"{method} {path} -> {r.status_code}, 期望 422"


def test_g1_unknown_task_404(client, docs_env):
    """引用不存在的 task → 业务 404（非 500）。"""
    r = client.get("/api/community-children", params={"task_id": "task-nope"})
    assert r.status_code == 404
    r = client.get("/api/community-graph", params={"task_id": "task-nope"})
    assert r.status_code == 404


def test_plantuml_render_routes(client, docs_env, monkeypatch):
    """渲染端点打桩（离线确定性）：GET/POST 200 + 走缓存 + clear-cache。"""
    import topoone.engine.plantuml_service as pu_svc

    calls = {"n": 0}

    def fake_render(code, format="svg", use_remote=True):
        calls["n"] += 1
        return f"<svg>{len(code)}</svg>".encode("utf-8")

    monkeypatch.setattr(pu_svc, "render_plantuml", fake_render)

    code = "@startuml\nA -> B\n@enduml"
    r1 = client.get("/api/plantuml", params={"code": code})
    assert r1.status_code == 200 and b"<svg>" in r1.content
    assert calls["n"] == 1
    # 第二次命中缓存，不再触发渲染
    r2 = client.get("/api/plantuml", params={"code": code})
    assert r2.status_code == 200 and calls["n"] == 1

    r3 = client.post("/api/plantuml", content=code, headers={"Content-Type": "text/plain"})
    assert r3.status_code == 200 and b"<svg>" in r3.content

    r4 = client.post("/api/plantuml", content="   ", headers={"Content-Type": "text/plain"})
    assert r4.status_code == 400  # 空 code 业务 400（viewer.py:604）

    assert client.get("/api/plantuml/clear-cache").json() == {"status": "ok"}


def test_graph_layout_roundtrip(client, seeded_db):
    """布局持久化三连：save → load 回读一致 → delete 后为空。"""
    tid = seeded_db["task_id"]
    key = {"task_id": tid, "comm_id": "c1", "edge_type": "UNIFIED"}
    layout = {"n1": {"x": 12.5, "y": -3}, "n2": {"x": 0, "y": 0}}

    r_save = client.post("/api/graph-layout", json={**key, "nodes": layout})
    assert r_save.status_code == 200 and r_save.json() == {"ok": True}

    r_load = client.get("/api/graph-layout", params=key)
    assert r_load.status_code == 200
    assert r_load.json()["nodes"] == layout

    assert client.delete("/api/graph-layout", params=key).json() == {"ok": True}
    assert client.get("/api/graph-layout", params=key).json() == {"nodes": {}}


def test_file_endpoint(client, seeded_db):
    """/api/file：命中文件 200 + 语言识别；越界 403；缺失 404。"""
    pid = seeded_db["project_id"]
    r = client.get("/api/file", params={"project_id": pid, "path": "pkg/mod_a.py"})
    assert r.status_code == 200
    data = r.json()
    assert data["language"] == "python" and "def fa" in data["content"]

    r_missing = client.get("/api/file", params={"project_id": pid, "path": "pkg/nope.py"})
    assert r_missing.status_code == 404

    r_trav = client.get("/api/file", params={"project_id": pid, "path": "../../etc/passwd"})
    assert r_trav.status_code == 403

    r_noproj = client.get("/api/file", params={"project_id": "proj-nope", "path": "x.py"})
    assert r_noproj.status_code == 404


def test_web_root_read_routes(client, seeded_db):
    r_projects = client.get("/api/projects")
    assert r_projects.status_code == 200
    items = [p for p in r_projects.json() if p["id"] == seeded_db["project_id"]]
    assert len(items) == 1 and items[0]["rootPath"].endswith("projroot")

    r_tasks = client.get("/api/tasks", params={"project_id": seeded_db["project_id"]})
    assert r_tasks.status_code == 200
    tasks = r_tasks.json()
    assert len(tasks) == 1 and tasks[0]["id"] == seeded_db["task_id"] and tasks[0]["hasDoc"] is False

    assert client.get("/api/docs/doc-nope").status_code == 404

    r_empty = client.get("/api/tasks", params={"project_id": "proj-nope"})
    assert r_empty.status_code == 200 and r_empty.json() == []  # list_tasks 空集兜底(web_root.py:70)


def test_web_root_async_jobs(client, seeded_db):
    r_export = client.post("/api/export", json={"projectId": seeded_db["project_id"]})
    assert r_export.status_code == 200 and r_export.json().get("exportId")

    assert client.get("/api/export/export-nope/status").status_code == 404
    assert client.get("/api/export/export-nope/download").status_code == 404

    r_import = client.post("/api/import", data={})
    assert r_import.status_code == 422  # file 必填(web_root.py:159)

    r_verify = client.post(f"/api/projects/{seeded_db['project_id']}/verify-files")
    assert r_verify.status_code == 200 and r_verify.json().get("verifyId")
    assert client.get("/api/verify/verify-nope/status").status_code == 404
