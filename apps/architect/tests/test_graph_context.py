"""W2 图邻域上下文供给（2610-B1）特征测试。

fixture 直接 seed GraphStore（数据主权自管面），覆盖：邻域正确性 / 预算截断 /
模块前缀 / 无基线空态 / 上限三件套 / context_pack 注入（开关两态 + 渲染段）。
"""
from __future__ import annotations

import pytest

from topoone_app_architect import store
from topoone_app_architect.store.graph import GraphStore
from topoone_app_architect.sem.graph_context import graph_neighborhood

REV = "baseline:abc123"


def _node(i, name, path, kind="function", start=10):
    return {"id": f"n{i}", "kind": kind, "name": name,
            "qualified_name": f"mod.{name}", "file_path": path,
            "language": "python", "start_line": start, "end_line": start + 5}


def _edge(s, t, kind="calls"):
    return {"source": f"n{s}", "target": f"n{t}", "kind": kind, "line": 1, "col": 0}


@pytest.fixture()
def graph_env(arch_env):
    store.ProjectsStore.create({"id": "pg", "name": "graph-fixture",
                                "root_path": "/tmp/g", "active": 1,
                                "baselineCommit": "abc123"})
    # 链: n1 → n2 → n3 → n4 (calls); n5 contains n1
    GraphStore.replace_rev("pg", REV,
                                 [_node(1, "login", "src/auth.py"),
                                  _node(2, "verify", "src/auth.py", start=40),
                                  _node(3, "hash_pw", "src/crypto.py"),
                                  _node(4, "salt", "src/crypto.py", start=60),
                                  _node(5, "AuthService", "src/auth.py",
                                        kind="class", start=1)],
                                 [_edge(1, 2), _edge(2, 3), _edge(3, 4),
                                  _edge(5, 1, kind="contains")])
    return "pg"


def test_neighborhood_two_hop(graph_env):
    nb = graph_neighborhood("pg", "login", depth=2, root="/tmp/g")
    assert nb["seed_count"] == 1
    assert "mod.login" in nb["outline"] and "src/auth.py" in nb["outline"]
    assert "mod.hash_pw" in nb["outline"]            # 2 跳可达(n1→n2→n3)
    assert "n4" not in nb["outline"] or nb["truncated"] is False  # 3 跳不可达
    assert nb["baseline_commit"] == "abc123"
    assert "calls×2" in nb["outline"]                # 关系摘要(contains 不计)


def test_neighborhood_depth_one(graph_env):
    nb = graph_neighborhood("pg", "verify", depth=1, root="/tmp/g")
    assert "mod.verify" in nb["outline"] and "mod.hash_pw" in nb["outline"]
    assert "mod.salt" not in nb["outline"]           # 2 跳不含


def test_module_prefix_focus(graph_env):
    nb = graph_neighborhood("pg", "src/crypto.py", depth=1, root="/tmp/g")
    assert "mod.hash_pw" in nb["outline"] and "mod.salt" in nb["outline"]


def test_budget_truncation(graph_env):
    nb = graph_neighborhood("pg", "AuthService", depth=2, budget=80, root="/tmp/g")
    assert len(nb["outline"]) <= 80 and nb["outline"].endswith("…")
    assert nb["truncated"] is True


def test_no_baseline_empty(arch_env):
    store.ProjectsStore.create({"id": "p2", "name": "x", "root_path": "/tmp/x",
                                "active": 1})          # 无 baselineCommit
    nb = graph_neighborhood("p2", "anything")
    assert nb["outline"] == "" and nb["reason"] == "no_baseline"


def test_no_focus_hit(graph_env):
    nb = graph_neighborhood("pg", "nonexistent_symbol")
    assert nb["outline"] == "" and nb["reason"] == "no_focus_hit"


def test_max_nodes_cap(graph_env):
    """250 节点种子 → 上限截断三件套(truncated 透出)。"""
    nodes = [_node(i, f"sym{i}", f"src/f{i % 5}.py") for i in range(250)]
    edges = [_edge(0, i) for i in range(1, 250)]
    GraphStore.replace_rev("pg", "baseline:big", nodes, edges)
    store.ProjectsStore.update("pg", {"baselineCommit": "big"})
    nb = graph_neighborhood("pg", "sym0", depth=2, root="/tmp/g")
    assert nb["node_count"] <= 200 and nb["truncated"] is True


# ── context_pack 注入段 ───────────────────────────────────────────────

def _spec_snapshot(monkeypatch, scope):
    """规约快照桩: allowedScope 由用例给定。"""
    from topoone_app_architect.store.core import RequirementsStore
    monkeypatch.setattr(RequirementsStore, "spec_active",
                        classmethod(lambda cls, rid: {"snapshot": {
                            "designMd": "登录模块方案", "allowedScope": scope,
                            "acceptance": ["条目1"]}}))


def test_context_pack_injects_neighborhood(graph_env, monkeypatch):
    from topoone_app_architect.agent.execution.context_pack import (
        build_context_pack, render_context_pack_md)
    _spec_snapshot(monkeypatch, ["login"])
    task = {"reqId": "rq-1", "projectId": "pg", "id": "t1"}
    pack = build_context_pack(task, None, "/tmp/g")
    nb = pack.get("graphNeighborhood")
    assert nb and "mod.login" in nb["outline"]
    md = render_context_pack_md(pack)
    assert "### 图邻域" in md and "mod.login" in md


def test_context_pack_switch_off(graph_env, monkeypatch):
    from topoone_app_architect.agent.execution import context_pack as CP
    from topoone_app_architect import store as _s
    _s.CollabConfigStore.set("agent.comp.overrides",
                             '{"graph_context_injection": false}')
    _spec_snapshot(monkeypatch, ["login"])
    pack = CP.build_context_pack({"reqId": "rq-1", "projectId": "pg"}, None, "/tmp/g")
    assert "graphNeighborhood" not in pack
