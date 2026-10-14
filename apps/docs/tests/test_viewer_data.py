"""docs 数据路径深测（MS1 §4.1）——种子数据上的兜底形状 + D6 回归锚点。"""
import json


def test_community_doc_fallback_content(client, seeded_db):
    """无 LLM 结果时的兜底文档结构（viewer.py:92-103）。"""
    tid, pid = seeded_db["task_id"], seeded_db["project_id"]
    r = client.get("/api/community-doc", params={"task_id": tid, "community_id": "c1"})
    assert r.status_code == 200
    data = r.json()
    assert data["taskId"] == tid and data["projectId"] == pid
    assert data["title"] == "c1" and "暂无 LLM 分析结果" in data["content"]


def test_community_files_and_graph_on_graph_doc(client, seeded_db):
    """graph_doc 行 → community-files 路径解析 / community-graph 200。"""
    tid, pid = seeded_db["task_id"], seeded_db["project_id"]
    pdb = seeded_db["project_db"]
    pdb.execute(
        "INSERT INTO graph_doc (task_id, edge_type, comm_lv, comm_id, node_list, node_count) "
        "VALUES (?, 'UNIFIED', 'L0', 'c-L0-1', ?, 2)",
        (tid, json.dumps(["pkg/mod_a.py", "README.md"])),  # node_list 约定为根相对裸路径
    )
    pdb.commit()

    r_files = client.get("/api/community-files", params={"task_id": tid, "community_id": "c-L0-1"})
    assert r_files.status_code == 200
    files = r_files.json()["files"]
    paths = {f["path"] for f in files}
    assert "pkg/mod_a.py" in paths and "README.md" in paths

    r_graph = client.get("/api/community-graph", params={"task_id": tid, "comm_id": "c-L0-1"})
    assert r_graph.status_code != 500

    r_fg = client.get("/api/file-graph", params={"task_id": tid, "comm_id": "__all__"})
    assert r_fg.status_code == 200
    body = r_fg.json()
    assert body["nodes"] == [] and body["edges"] == []  # 无 graph_node 时空图兜底(viewer.py:343)


def test_heatmap_cascade_external_seeded(client, seeded_db):
    """种子项目上三只读路由均为业务 JSON（非 500）。"""
    for path in ("/api/heatmap", "/api/cascade-levels", "/api/external-stats", "/api/external-graph"):
        r = client.get(path, params={"task_id": seeded_db["task_id"]})
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
        assert isinstance(r.json(), dict)


def test_diagram_editor_process_with_model(client, seeded_db, monkeypatch):
    """D6 回归锚点：模型就绪时端点必须走通 web_tools 工具装配（悬空 import 修复前必 500）。

    LLM 经 requests.post 打桩（无 tool_calls → 单轮即终）；断言 200 + 单轮收口。
    """
    main_db = client.app.state.multi_db.main_db
    main_db.execute(
        "INSERT INTO model_configs (id, name, provider, model, url, status, is_default) "
        "VALUES ('m-fix1', 'stub', 'custom-local', 'stub-model', 'http://127.0.0.1:9', 'connected', 1)"
    )
    main_db.commit()

    import requests

    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "编辑完成：无改动"}}], "usage": {}}

    monkeypatch.setattr(requests, "post", lambda *a, **kw: _Resp())

    r = client.post("/api/diagram-editor/process", json={
        "code": "graph TD\n A[\"A\"] --> B[\"B\"]\n",
        "instruction": "no-op",
        "lang": "mermaid",
    })
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    body = r.json()
    assert body["rounds"] == 1 and body["code_changed"] is False


def test_diagram_editor_no_model_400(client, seeded_db):
    """无可用模型 → 业务 400（非 500/502），viewer.py:844。"""
    # 会话级共享库：清掉其他用例种下的默认模型，保证「无模型」前提
    main_db = client.app.state.multi_db.main_db
    main_db.execute("DELETE FROM model_configs")
    main_db.commit()

    r = client.post("/api/diagram-editor/process", json={
        "code": "graph TD\n A --> B\n", "instruction": "x",
    })
    assert r.status_code == 400
