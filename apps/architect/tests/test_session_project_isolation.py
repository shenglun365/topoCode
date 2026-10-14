"""会话中心项目隔离(cv-187 反馈): /sessions 与 /sessions/groups 按 ?project= 过滤。

口径: project=<id> → 全库扫描后按 project_id 列过滤(历史行可能落主库,
不走单库路由); scope=all 不带 project → 跨全库统一视图(显式开启才生效)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_session_project_isolation.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store

P1, P2 = "proj-iso-1", "proj-iso-2"


def _mk_convs():
    store.ConversationsStore.create({"kind": "generic", "title": "P1 会话甲",
                                     "projectId": P1, "tags": {"groups": ["g1"], "modules": ["auth"]}})
    store.ConversationsStore.create({"kind": "generic", "title": "P1 会话乙",
                                     "projectId": P1, "tags": {"modules": ["pay"]}})
    store.ConversationsStore.create({"kind": "generic", "title": "P2 会话丙",
                                     "projectId": P2, "tags": {"groups": ["g2"], "modules": ["auth"]}})


def _client():
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    return TestClient(build_app(data_dir=os.environ["ARCH_DATA_DIR"]))


def test_sessions_project_isolation(arch_env):
    _mk_convs()
    c = _client()
    r1 = c.get(f"/api/architect/sessions?project={P1}").json()["data"]
    assert {x["title"] for x in r1} == {"P1 会话甲", "P1 会话乙"}
    r2 = c.get(f"/api/architect/sessions?project={P2}").json()["data"]
    assert {x["title"] for x in r2} == {"P2 会话丙"}
    # 显式跨库统一视图(不带 project)仍全量
    rall = c.get("/api/architect/sessions?scope=all").json()["data"]
    assert len(rall) == 3


def test_sessions_project_filter_scan_mode(arch_env):
    """store 层: summaries(project_id, all_scopes=True) 扫全库按列过滤。"""
    _mk_convs()
    rows = store.ConversationsStore.summaries(project_id=P1, all_scopes=True)
    assert all(r.get("projectId") == P1 for r in rows) and len(rows) == 2
    assert store.ConversationsStore.summaries(project_id=P2, all_scopes=True)


def test_groups_project_isolation(arch_env):
    _mk_convs()
    c = _client()
    g1 = c.get(f"/api/architect/sessions/groups?project={P1}").json()["data"]
    assert "pay" in g1["modules"] and "g1" in g1["groups"]
    g2 = c.get(f"/api/architect/sessions/groups?project={P2}").json()["data"]
    assert "pay" not in g2["modules"]
    gall = c.get("/api/architect/sessions/groups?scope=all").json()["data"]
    assert "pay" in gall["modules"] and "g2" in gall["groups"]
