"""逻辑视图（批1 BE）：存储 CRUD/指纹 upsert + 拓展纯函数 + 图谱 assets 口径 + 清除连带。

逻辑资产 = 视图类型存在：跨组件业务逻辑链条（core 种子 + agent 拓展成员 + LLM 概括），
不再作为提取产出的 level='logic' 资产行。
"""
import asyncio
import json
import sys

import pytest

sys.path.insert(0, ".")

import topoone_app_architect.ctx as C
import topoone_app_architect.store as store
from topoone_app_architect.arch_routes import semantic_assets as S
from topoone_app_architect.arch_routes import logic_views as LV
from topoone_app_architect.sem import logic_extract as LX
from topoone_app_architect.sem.logic_extract import expand_members


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    """单例重置 + 临时库(与 test_semantic_assets._ctx 同款)。"""
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C.setup(data_dir=data)
    yield
    C._db = None
    C._kb = None


def _mk_impl(pid, aid, name, level="implementation"):
    store.SemanticAssetsStore.create({
        "id": aid, "projectId": pid, "kind": "asset", "level": level,
        "name": name, "desc": "", "detail": {}, "astRefs": [{"file": "a.py"}],
        "scopeType": "comm", "scopeKey": "L0-0001", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})


def test_store_crud_and_fingerprint(ctx):
    pid = S.project_id_for("/tmp/x", None)
    v = store.LogicViewsStore.create(pid, "下单链", ["a1", "a2"], ["a1", "a2", "a3"])
    assert v["name"] == "下单链"
    # members = core ∪ member(去重保序)
    assert json.loads(v["memberIds"]) == ["a1", "a2", "a3"]
    assert json.loads(v["coreIds"]) == ["a1", "a2"]
    hit = store.LogicViewsStore.by_fingerprint(pid, v["fingerprint"])
    assert hit and hit["id"] == v["id"]
    store.LogicViewsStore.update(v["id"], {"summary": "概括"})
    assert store.LogicViewsStore.get(v["id"])["summary"] == "概括"
    assert store.LogicViewsStore.list(pid)[0]["id"] == v["id"]
    assert store.LogicViewsStore.delete(v["id"]) is True
    assert store.LogicViewsStore.get(v["id"]) is None


def test_expand_members_hops_and_cap(ctx):
    edges = [("a", "b"), ("b", "c"), ("c", "d"), ("x", "y")]
    assert expand_members(edges, ["a"], 0) == ["a"]              # 仅核心
    assert expand_members(edges, ["a"], 1) == ["a", "b"]         # 1 跳
    assert expand_members(edges, ["a"], 2) == ["a", "b", "c"]    # 2 跳
    assert expand_members(edges, ["a"], 99) == ["a", "b", "c", "d"]  # 连通闭包
    assert "x" not in expand_members(edges, ["a"], 99)           # 不连通不纳入
    assert len(expand_members(edges, ["a"], 99, cap=2)) == 2     # cap 截断


def test_extract_logic_saves_views_not_assets(ctx, monkeypatch):
    """extract_logic 作业落库为逻辑视图(非 level='logic' 资产行)；同指纹重跑 upsert。"""
    pid = S.project_id_for("/tmp/x", None)
    for i in range(3):
        _mk_impl(pid, f"impl-{i}", f"资产{i}")
    monkeypatch.setattr(LX, "induce_chains",
                        lambda root, assets, rev, model_id=None: [
                            {"name": "下单链", "kind": "process_chain",
                             "summary": "从下单到支付", "members": ["impl-0", "impl-1"],
                             "inputs": [], "outputs": []}])
    job_ctx = _job_ctx({"root": "/tmp/x", "files": [], "rev": "workspace",
                        "skipImpl": True})
    r = LX._job_extract_logic(job_ctx)
    assert r["saved"] == 1
    views = store.LogicViewsStore.list(pid)
    assert len(views) == 1
    assert views[0]["source"] == "extract"
    assert json.loads(views[0]["memberIds"]) == ["impl-0", "impl-1"]
    # 资产行不产生 level=logic
    assert not store.SemanticAssetsStore.search(pid, level="logic", limit=10)
    # 同指纹重跑 → upsert 不重复建
    r2 = LX._job_extract_logic(_job_ctx({"root": "/tmp/x", "files": [], "rev": "workspace",
                                         "skipImpl": True}))
    assert r2["saved"] == 1
    assert len(store.LogicViewsStore.list(pid)) == 1


def test_graph_assets_param(ctx):
    """semantic_graph assets= 资产集口径：节点=指定成员(边为其间关系)。"""
    pid = S.project_id_for("/tmp/x", None)
    for i in range(3):
        _mk_impl(pid, f"impl-{i}", f"资产{i}")
    g = S.semantic_graph("/tmp/x", None, assets="impl-0,impl-1")
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"impl-0", "impl-1"}


def test_batch_clear_cascades_logic_views(ctx):
    """files 口径清除：成员实现资产被清 → 逻辑视图连带删除；无关视图保留。"""
    pid = S.project_id_for("/tmp/x", None)
    _mk_impl(pid, "impl-a", "A")
    from topoone_app_architect.store import SemanticAssetsStore
    SemanticAssetsStore.create({
        "id": "impl-b", "projectId": pid, "kind": "asset", "level": "implementation",
        "name": "B", "desc": "", "detail": {}, "astRefs": [{"file": "b.py"}],
        "scopeType": "comm", "scopeKey": "L0-0001", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    store.LogicViewsStore.create(pid, "链A", ["impl-a"], ["impl-a"])
    store.LogicViewsStore.create(pid, "链B", ["impl-b"], ["impl-b"])
    res = S.batch_manage("/tmp/x", None, "clear", files=["a.py"])
    assert "impl-a" in res["cleared"]
    names = {v["name"] for v in store.LogicViewsStore.list(pid)}
    assert names == {"链B"}   # 链A 成员被清 → 连带删除


def _job_ctx(scope):
    """JobCtx 轻量替身(progress/cancelled 无操作)。"""
    class _Ctx:
        def __init__(self, sc):
            self.scope = sc
        def progress(self, **kw):
            pass
        def cancelled(self):
            return False
    return _Ctx(scope)
