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
from topoone_app_architect.sem import logic_induce as LI
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
                        lambda root, assets, rev, model_id=None: ([
                            {"name": "下单链", "kind": "process_chain",
                             "summary": "从下单到支付", "members": ["impl-0", "impl-1"],
                             "inputs": [], "outputs": []}], ""))
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


def test_induce_chains_truncation_recovery(monkeypatch):
    """输出触碰 maxTokens 截断：整体 parse 必败 → 逐条恢复救回完整链条 + diag 透传。"""
    impl = [{"id": f"impl-{i}", "kind": "asset", "name": f"资产{i}", "desc": "",
             "detail": {}, "astRefs": [{"file": "a.py", "symbol": f"sym{i}"}]}
            for i in range(4)]

    def good(ep_sym):
        return {"name": ep_sym, "symbol": ep_sym, "file": "a.py"}

    # 2 条完整 + 第 3 条截断(无闭合)——历史事故形态
    truncated = ('前言 {"chains": ['
                 + json.dumps({"name": "链A", "kind": "process_chain", "summary": "s",
                               "members": ["sym0", "sym1"],
                               "inputs": [good("sym0")], "outputs": [good("sym1")]},
                              ensure_ascii=False)
                 + ", "
                 + json.dumps({"name": "链B", "kind": "validation_chain", "summary": "s",
                               "members": ["sym2"],
                               "inputs": [good("sym2")], "outputs": []},
                              ensure_ascii=False)
                 + ', {"name": "链C", "summary": "残')
    monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                        lambda msgs, **kw: {"content": truncated})
    monkeypatch.setattr(LI, "build_code_anchor",   # induce_chains 内部绑定位在归纳域模块
                        lambda root, ref, rev, lang="": {"file": ref.get("file")})
    chains, diag = LX.induce_chains("/tmp/x", impl, "workspace")
    assert [c["name"] for c in chains] == ["链A", "链B"]
    assert chains[0]["members"] == ["impl-0", "impl-1"]
    assert "截断" in diag and "恢复 2 条" in diag

    # 完全无 JSON → diag 指明且不抛
    monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                        lambda msgs, **kw: {"content": "模型闲聊没有结构化输出"})
    chains, diag = LX.induce_chains("/tmp/x", impl, "workspace")
    assert chains == []
    assert "未返回 JSON" in diag


class _ExplainReq:
    def __init__(self, body=None):
        self._b = body or {}

    async def json(self):
        return self._b


def test_logic_view_explain_cache_and_invalidation(ctx, monkeypatch):
    """AI 讲解三态：指纹一致缓存秒回 / 成员 srcHash 变化自动失效 / force 强制重生成。"""
    import asyncio
    from topoone_app_architect.sem import logic_induce as LI
    pid = S.project_id_for("/tmp/x", None)
    _mk_impl(pid, "impl-e1", "订单入口")
    _mk_impl(pid, "impl-e2", "状态同步")
    # 成员 srcHash 预置 h1
    for aid in ("impl-e1", "impl-e2"):
        store.SemanticAssetsStore.update(aid, {"srcHash": "h1"})
    v = store.LogicViewsStore.create(pid, "下单链", ["impl-e1"], ["impl-e1", "impl-e2"],
                                     summary="从下单到支付", source="extract")

    calls = {"n": 0}

    def fake_explain(view, assets, model_id=None):
        calls["n"] += 1
        return f"讲解v{calls['n']}(引用 订单入口 (impl-e1))"

    monkeypatch.setattr(LI, "explain_view", fake_explain)

    async def _call(body=None):
        return await LV.api_logic_views_explain(v["id"], _ExplainReq(body))

    # ① 首次：无缓存 → 生成并落库
    r1 = asyncio.run(_call())
    assert r1["data"]["cached"] is False and "讲解v1" in r1["data"]["detail"]
    assert calls["n"] == 1
    # ② 再次：成员未变 → 指纹一致 → 缓存秒回(不调 LLM)
    r2 = asyncio.run(_call())
    assert r2["data"]["cached"] is True and calls["n"] == 1
    # ③ 成员 srcHash 变化(重提取) → 指纹失效 → 自动重生成
    store.SemanticAssetsStore.update("impl-e2", {"srcHash": "h2"})
    r3 = asyncio.run(_call())
    assert r3["data"]["cached"] is False and "讲解v2" in r3["data"]["detail"]
    assert calls["n"] == 2
    # ④ force：缓存命中仍强制重生成
    r4 = asyncio.run(_call({"force": True}))
    assert r4["data"]["cached"] is False and "讲解v3" in r4["data"]["detail"]
    assert calls["n"] == 3
    # 讲解落库可查
    got = store.LogicViewsStore.get(v["id"])
    assert "讲解v3" in (got.get("detail") or "")
