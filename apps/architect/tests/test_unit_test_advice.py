"""W5 单测建议层（2610-B1）端点测试：缺口建议 / 事实对账 / approval 位。

fixture：项目 + 图(含测试文件符号) + 扫描 KV + K2 回执主张。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from topoone_app_architect import store
from topoone_app_architect.store.graph import GraphStore
from topoone_app_architect.store.tracking import TrackingItemsStore
from topoone_app_architect.server import build_app

REV = "baseline:ad1"


def _node(i, name, path, kind="function", start=10):
    return {"id": f"n{i}", "kind": kind, "name": name,
            "qualified_name": f"m.{name}", "file_path": path,
            "language": "python", "start_line": start, "end_line": start + 3}


def _edge(s, t, kind="calls"):
    return {"source": f"n{s}", "target": f"n{t}", "kind": kind, "line": 1, "col": 0}


@pytest.fixture()
def advice_env(arch_env, tmp_path):
    pid = "padv"
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "a.test.ts").write_text("test", encoding="utf-8")
    store.ProjectsStore.create({"id": pid, "name": "adv", "root_path": str(root),
                                "active": 1, "baselineCommit": "ad1"})
    # 图: 测试符号 n9(tests/a.test.ts) → n1; n1→n2→n3→n6; n5 contains n1
    GraphStore.replace_rev(pid, REV,
                           [_node(1, "login", "src/auth.py"),
                            _node(2, "verify", "src/auth.py", start=40),
                            _node(3, "hash_pw", "src/crypto.py"),
                            _node(5, "AuthService", "src/auth.py", kind="class"),
                            _node(6, "Bank", "src/bank.py", kind="class"),
                            _node(7, "Report", "src/report.py", kind="class"),
                            _node(9, "login_test", "tests/a.test.ts")],
                           [_edge(9, 1), _edge(1, 2), _edge(2, 3), _edge(3, 6),
                            _edge(5, 7), _edge(5, 1, kind="contains")])
    from topoone_app_architect.sem.test_reach import record_test_scan
    record_test_scan(pid, str(root))
    client = TestClient(build_app(data_dir=arch_env))
    return {"pid": pid, "root": str(root), "client": client}


def _get(client, path, **params):
    r = client.get(f"/api/architect{path}", params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_advice_gaps_weighted(advice_env):
    d = _get(advice_env["client"], "/unit-tests/advice",
             root=advice_env["root"], top_n=10)
    assert d["projectId"] == advice_env["pid"]
    assert d["approval"] == {"mode": "none"}                    # D-4 缺省无行为
    syms = [g["symbol"] for g in d["items"]]
    assert "m.Report" in syms                                    # 闭包外且有扇入(n5→n7 不可达)
    assert "m.verify" not in syms and "m.hash_pw" not in syms   # 测试可达链上
    assert "m.login" not in syms                                # 测试可达(n9→n1)
    assert "m.AuthService" not in syms                          # contains 不计扇入→孤岛
    top = d["items"][0]
    assert top["weight"] >= top["fan_in"] >= 1
    assert top["evidence"]["neighborhood"]                      # 最小证据视图


def test_advice_no_project(arch_env):
    client = TestClient(build_app(data_dir=arch_env))
    d = _get(client, "/unit-tests/advice")
    assert d["reason"] == "no_project" and d["items"] == []


def test_advice_top_n_clamped(advice_env):
    d = _get(advice_env["client"], "/unit-tests/advice",
             root=advice_env["root"], top_n=1)
    assert len(d["items"]) == 1


def test_facts_reconcile_emits_tracking_once(advice_env):
    # K2 主张: 声称 tests/claimed.test.ts(扫描未见)
    conv = store.ConversationsStore.create({"projectId": advice_env["pid"],
                                            "title": "t", "meta": {}})
    store.ContextUnitsStore.create({
        "conversationId": conv["id"], "projectId": advice_env["pid"],
        "type": "execution_report", "title": "回执", "content": "x",
        "refs": {"taskId": "tk-1",
                 "tests": {"files": [{"path": "tests/claimed.test.ts"}],
                           "run_result": "not_run"}}})
    d = _get(advice_env["client"], "/unit-tests/facts", root=advice_env["root"])
    assert d["scannedCount"] == 1 and d["claimedCount"] == 1
    assert d["claimedOnly"] == ["tests/claimed.test.ts"]
    assert d["scannedOnly"] == ["tests/a.test.ts"]
    items = [t for t in TrackingItemsStore.all(project_id=advice_env["pid"])
             if t.get("refType") == "test_claim"]
    assert len(items) == 1 and items[0]["state"] == "waiting"
    # 幂等: 再对账不重复挂账
    _get(advice_env["client"], "/unit-tests/facts", root=advice_env["root"])
    items2 = [t for t in TrackingItemsStore.all(project_id=advice_env["pid"])
              if t.get("refType") == "test_claim"]
    assert len(items2) == 1


def test_scan_diff_recorded(advice_env):
    from topoone_app_architect.sem.test_reach import read_test_scan, record_test_scan
    import pathlib
    root = pathlib.Path(advice_env["root"])
    (root / "tests" / "b_test.py").write_text("t", encoding="utf-8")
    out = record_test_scan(advice_env["pid"], root)
    assert out["diff"]["added"] == ["tests/b_test.py"]
    assert read_test_scan(advice_env["pid"])["count"] == 2


# ── L-3 组件域乘数(deferred-2610): 层级 1.0/1.5/2.0 + component 字段 ──

def test_component_level_multiplier(advice_env):
    from topoone_app_architect.store.component import ComponentStore
    pid = advice_env["pid"]
    d = _get(advice_env["client"], "/unit-tests/advice", root=advice_env["root"])
    base_weight = next(g["weight"] for g in d["items"] if g["symbol"] == "m.Report")
    assert base_weight == 3 and d["items"][0]["component"] == ""   # 无组件=1.0

    # Report 归属 L2 核心域组件 → 乘 2.0
    ComponentStore.replace_rev(pid, REV,
                               [{"id": "core", "name": "CoreDomain",
                                 "owns": ["src/report.py"], "source": "community"}],
                               [{"childId": "core", "parentId": "root", "level": 2}])
    d2 = _get(advice_env["client"], "/unit-tests/advice", root=advice_env["root"])
    top = next(g for g in d2["items"] if g["symbol"] == "m.Report")
    assert top["weight"] == 6                                   # 1×3×2.0
    assert top["component"] == "CoreDomain"

    # L0 归属 → 乘 1.0(与无组件一致)
    ComponentStore.replace_rev(pid, REV,
                               [{"id": "c0", "name": "Atom",
                                 "owns": ["src/report.py"], "source": "community"}],
                               [{"childId": "c0", "parentId": "root", "level": 0}])
    d3 = _get(advice_env["client"], "/unit-tests/advice", root=advice_env["root"])
    assert next(g for g in d3["items"] if g["symbol"] == "m.Report")["weight"] == 3
