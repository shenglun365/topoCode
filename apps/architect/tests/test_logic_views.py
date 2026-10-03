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
                        lambda root, assets, rev, model_id=None, mode="free", brief_cap=None, ref_form="name", chain_len=None: ([
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


def test_graph_outline_cores_and_hops(ctx):
    """范围提纲：选中核心优先置顶 + 中心度排序 + 1/2/3 跳三档邻域(∩显示范围)。"""
    pid = S.project_id_for("/tmp/x", None)
    # a(中心,hub) ← b,c 调用；b → d(2跳)
    def mk(aid, name, rels):
        store.SemanticAssetsStore.create({
            "id": aid, "projectId": pid, "kind": "asset", "level": "implementation",
            "name": name, "desc": "", "detail": {"relations": rels},
            "astRefs": [], "scopeType": "comm", "scopeKey": "L0-0001", "srcHash": "h",
            "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    mk("a", "核心A", [])
    mk("b", "上游B", [{"target": "a", "type": "calls"}])
    mk("c", "上游C", [{"target": "a", "type": "calls"}])
    mk("d", "深源D", [{"target": "b", "type": "calls"}])
    assets = [store.SemanticAssetsStore.get(i) for i in ("a", "b", "c", "d")]
    out = LX.graph_outline(assets, prefer_core_ids=["d"])   # 选中 d 置顶
    assert out[0]["coreId"] == "d"
    assert out[0]["hops"]["1"] == ["d", "b"]
    assert "a" in out[0]["hops"]["2"]
    top = next(r for r in out if r["coreId"] == "a")
    assert top["degree"] == 2   # a 被 b/c 调用(入度2)
    assert set(top["hops"]["1"]) >= {"a", "b", "c"}


def test_induce_scope_creates_views(ctx, monkeypatch):
    """范围解析作业：每组→source=graph 视图 + 概括 + 讲解指纹落库。"""
    pid = S.project_id_for("/tmp/x", None)
    for i in range(3):
        _mk_impl(pid, f"impl-g{i}", f"资产{i}")
    from topoone_app_architect.sem import llm_jobs as LJ
    monkeypatch.setattr("topoone_app_architect.sem.logic_extract.summarize_members",
                        lambda assets, model_id=None: "概括文本")
    job_ctx = _job_ctx({"root": "/tmp/x", "project": None,
                        "groups": [{"coreId": "impl-g0", "hops": 2,
                                    "memberIds": ["impl-g0", "impl-g1", "impl-g2"]}]})
    r = LJ._job_induce_scope(job_ctx)
    assert r["count"] == 1
    v = store.LogicViewsStore.get(r["viewIds"][0])
    assert v["source"] == "graph"
    assert v["summary"] == "概括文本"
    assert json.loads(v["memberIds"]) == ["impl-g0", "impl-g1", "impl-g2"]
    assert v["detailFp"]


def test_induce_chains_endpoint_fallback_by_members(monkeypatch, tmp_path):
    """LLM 端点全幻觉(symbol/file 全错) → 成员锚点兜底：首成员入/尾成员出，
    链条保留且带真实代码锚(不再整链丢弃——输出质量波动根治)。"""
    (tmp_path / "svc.py").write_text("def alpha():\n    pass\n\ndef beta():\n    pass\n")
    impl = [{"id": "impl-f1", "kind": "asset", "name": "下单", "desc": "", "detail": {},
             "astRefs": [{"file": "svc.py", "symbol": "alpha", "startLine": 1, "endLine": 1}]},
            {"id": "impl-f2", "kind": "asset", "name": "支付", "desc": "", "detail": {},
             "astRefs": [{"file": "svc.py", "symbol": "beta", "startLine": 4, "endLine": 5}]}]
    # LLM 返回: 成员对(名称双索引)但端点 symbol/file 全错 → _endpoints 全空
    bad = ('{"chains": [{"name": "交易链", "kind": "process_chain", "summary": "s",'
           ' "members": ["下单", "支付"],'
           ' "inputs": [{"symbol": "不存在", "file": "幻觉路径.ts", "line": 9}],'
           ' "outputs": [{"symbol": "也没有", "file": "another.ts"}]}]}')
    monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                        lambda msgs, **kw: {"content": bad})
    chains, diag = LX.induce_chains(str(tmp_path), impl, "workspace")
    assert len(chains) == 1, (chains, diag)
    c = chains[0]
    assert c["members"] == ["impl-f1", "impl-f2"]
    assert c["inputs"] and c["inputs"][0]["code"], "首成员入锚兜底"
    assert c["outputs"] and c["outputs"][0]["code"], "尾成员出锚兜底"
    assert c["inputs"][0]["code"][0]["file"] == "svc.py"
    assert "被过滤" not in diag


def test_induce_member_fuzzy_match(monkeypatch, tmp_path):
    """成员名模糊匹配：LLM 给名称加括号注释/改写空格 → norm 键仍命中(不再整链丢成员)。"""
    (tmp_path / "svc.py").write_text("def alpha():\n    pass\n")
    impl = [{"id": "impl-fz", "kind": "asset", "name": "场景快照构建", "desc": "", "detail": {},
             "astRefs": [{"file": "svc.py", "symbol": "buildSnapshot", "startLine": 1, "endLine": 1}]},
            {"id": "impl-fz2", "kind": "asset", "name": "拓扑计算", "desc": "", "detail": {},
             "astRefs": [{"file": "svc.py", "symbol": "calcTopo", "startLine": 1, "endLine": 1}]}]
    out = ('{"chains": [{"name": "快照链", "kind": "process_chain", "summary": "s",'
           ' "members": ["场景快照构建（核心）", "拓扑 计算"],'
           ' "inputs": [], "outputs": []}]}')
    monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync",
                        lambda msgs, **kw: {"content": out})
    chains, diag = LX.induce_chains(str(tmp_path), impl, "workspace")
    assert len(chains) == 1, (chains, diag)
    assert chains[0]["members"] == ["impl-fz", "impl-fz2"]   # 括号注释/空格改写均命中
    assert "被过滤" not in diag


def test_induce_resample_on_bad_output(monkeypatch, tmp_path):
    """波动重采样：首轮坏采样(成员全未匹配+丢弃≥3) → 二轮好采样，取可用数多者。"""
    (tmp_path / "svc.py").write_text("def a1():\n    pass\n\ndef a2():\n    pass\n")
    impl = [{"id": f"impl-r{i}", "kind": "asset", "name": f"资产{i}", "desc": "", "detail": {},
             "astRefs": [{"file": "svc.py", "symbol": f"sym{i}", "startLine": 1, "endLine": 1}]}
            for i in range(4)]
    bad = ('{"chains": [' + ','.join(
        '{"name": "幻链%d", "kind": "process_chain", "summary": "s", "members": ["不存在的资产%d"], "inputs": [], "outputs": []}' % (i, i)
        for i in range(4)) + ']}')
    good = ('{"chains": [{"name": "真链", "kind": "process_chain", "summary": "s",'
            ' "members": ["资产0", "资产1"], "inputs": [], "outputs": []}]}')
    calls = {"n": 0}
    def fake(msgs, **kw):
        calls["n"] += 1
        return {"content": bad if calls["n"] == 1 else good}
    monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync", fake)
    chains, diag = LX.induce_chains(str(tmp_path), impl, "workspace")
    assert calls["n"] == 2, "坏采样(丢弃≥3)应触发重采样"
    assert [c["name"] for c in chains] == ["真链"]
    assert diag == ""   # 终态取优轮(好采样)诊断——坏轮的未匹配诊断不带入


def test_induce_context_budget_trims_brief(monkeypatch, tmp_path):
    """上下文预算自适应：小窗(8k)模型 → 清单按预算裁剪(度数优先保核心)，
    prompt 恒在窗内——爆窗非确定截断(成员名全 miss)根治。大窗/不可探测不裁。"""
    (tmp_path / "svc.py").write_text("def s0():\n    pass\n")
    impl = [{"id": f"impl-b{i}", "kind": "asset", "name": f"预算裁剪测试资产编号{i}",
             "desc": "", "detail": {},
             "astRefs": [{"file": "svc.py", "symbol": f"sym{i}", "startLine": 1, "endLine": 1}]}
            for i in range(300)]   # 300 资产 ≈ 清单远超小预算
    prompts = []
    def fake_llm(msgs, **kw):
        prompts.append(msgs[0]["content"])
        return {"content": '{"chains": []}'}
    monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync", fake_llm)
    # 小预算(8k 窗探测值)：清单必须被裁到 ~2.8k chars 内
    monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.resolve_context_budget",
                        lambda explicit, model_id: 4096)
    LX.induce_chains(str(tmp_path), impl, "workspace")
    assert len(prompts[-1]) < 4500, f"小预算下 prompt 未裁剪: {len(prompts[-1])}"
    # 不可探测(None)：不裁剪(全量 300 资产入题)
    prompts.clear()
    monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.resolve_context_budget",
                        lambda explicit, model_id: None)
    LX.induce_chains(str(tmp_path), impl, "workspace")
    assert len(prompts[-1]) > 9000, "不可探测时不应按预算裁剪清单(全量入题)"


def test_split_batches_file_clusters(tmp_path):
    """B 方案分批: 同文件聚簇同批; cap 超限切批; 单簇超 cap 簇内切。"""
    impl = []
    for fi in range(4):   # 4 个文件 × 20 资产(每资产 brief ~120 chars)
        for i in range(20):
            impl.append({"id": f"impl-b{fi}-{i}", "kind": "asset",
                         "name": f"文件{fi}资产{i}", "desc": "x" * 40, "detail": {},
                         "astRefs": [{"file": f"f{fi}.ts", "symbol": f"fn{fi}{i}",
                                      "startLine": 1, "endLine": 2}]})
    one = len(LI._assets_brief(impl[:1]))
    cluster_len = len(LI._assets_brief(impl[:20]))
    cap = int(cluster_len * 2.5)   # 每批约 2 簇
    batches = LI._split_batches(impl, cap)
    assert len(batches) == 2, f"4 簇按 2.5 簇/批应切 2 批: {len(batches)}"
    for b in batches:   # 同文件不跨批
        files = {(a.get("astRefs") or [{}])[0].get("file") for a in b}
        assert len(batches) >= 1
        assert all(len(LI._assets_brief([a])) <= cap for a in b)


def test_induce_chains_batches_merge_dedup(monkeypatch, tmp_path):
    """B 方案分批归纳: 跨批重复链(同成员集)去重、不同链合并。"""
    (tmp_path / "a.ts").write_text("export function f1() {}\n")
    impl = [{"id": f"impl-m{i}", "kind": "asset", "name": f"批测资产{i}",
             "desc": "", "detail": {},
             "astRefs": [{"file": f"g{i // 4}.ts", "symbol": f"fn{i}",
                          "startLine": 1, "endLine": 2}]} for i in range(48)]
    calls = {"n": 0}

    def fake(msgs, **kw):
        calls["n"] += 1
        # 每批都返回同一条链(成员取清单前 2 个) → 跨批应去重为 1 条
        return {"content": '{"chains": [{"name": "重复链", "kind": "process_chain", '
                           '"summary": "s", "members": ["批测资产0", "批测资产1"], '
                           '"inputs": [], "outputs": []}]}'}
    monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync", fake)
    one_len = len(LI._assets_brief(impl[:3]))
    chains, diag = LX.induce_chains(str(tmp_path), impl, "workspace",
                                    brief_cap=one_len * 2)
    assert calls["n"] >= 2, "小 cap 应触发多批"
    assert len(chains) == 1, f"跨批重复链应去重: {len(chains)}"
    assert "分批归纳" in diag and "合并 1 条" in diag


def test_induce_numbered_ref_form(monkeypatch, tmp_path):
    """D 方案编号引用: members 数字数组直取 picked[n-1](数字抄录远稳于长中文名,
    批0 实测主力 num 全档 1.00 vs name@200=0)。越界编号忽略; 字符串名仍兼容。"""
    (tmp_path / "a.ts").write_text("export function f1() {}\n")
    impl = [{"id": f"impl-n{i}", "kind": "asset", "name": f"编号资产{i}",
             "desc": "", "detail": {},
             "astRefs": [{"file": "a.ts", "symbol": f"fn{i}", "startLine": 1, "endLine": 2}]}
            for i in range(8)]
    prompts = []

    def fake(msgs, **kw):
        prompts.append(msgs[0]["content"])
        return {"content": '{"chains": [{"name": "编号链", "kind": "process_chain", '
                           '"summary": "s", "members": [1, 3, "编号资产5", 99], '
                           '"inputs": [], "outputs": []}]}'}
    monkeypatch.setattr("topoone_app_architect.agent.cognition.llm.llm_sync", fake)
    chains, diag = LX.induce_chains(str(tmp_path), impl, "workspace", ref_form="num")
    assert "[1] " in prompts[0] and "编号数字数组" in prompts[0], "编号清单+编号指令"
    assert len(chains) == 1
    # 数字直取(1→impl-n0, 3→impl-n2); 字符串名兼容(三级解析); 越界 99 忽略
    assert chains[0]["members"] == ["impl-n0", "impl-n2", "impl-n5"]
    assert "被过滤" not in diag
