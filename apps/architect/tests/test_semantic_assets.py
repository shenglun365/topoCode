"""Semantic Data Assets 单元测试。

覆盖:
  - SemanticAssetsStore CRUD / search / find_by_scope / mark_scope_stale
  - _save_assets 增量 change 判定(added → same → modified)
  - resolve_ast_refs 符号引用 → 真实 AST 锚点
  - context_block_for / websocket._task_prompt 上下文展开
  - extract_scope 启发式(无 codegraph/LLM)降级路径

Run:  cd <repo> && python -m pytest plugins/architect/tests/test_semantic_assets.py -q
"""
import os
import sqlite3
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.store as store
_SEM_MODULE_NAMES = ("taxonomy", "paths", "codegraph", "scope", "incremental", "context", "anchors", "engine")


def _patch_all(monkeypatch, name, value):
    """A1 拆分后名字可能绑定在 facade 或任一 sem 模块 —— 全部绑定位统一 patch。"""
    import importlib
    import topoone_app_architect.arch_routes.semantic_assets as _sa
    if hasattr(_sa, name):
        monkeypatch.setattr(_sa, name, value)
    for _mn in _SEM_MODULE_NAMES:
        _mod = importlib.import_module(f"topoone_app_architect.arch_routes.sem.{_mn}")
        if hasattr(_mod, name):
            monkeypatch.setattr(_mod, name, value)


from topoone_app_architect.arch_routes import semantic_assets as S
from topoone_app_architect.arch_routes.sem import context as _sem_context
from topoone_app_architect.arch_routes.sem import engine as _sem_engine
from topoone_app_architect.arch_routes.sem import scope as _sem_scope
from topoone_app_architect.arch_routes.sem import incremental as _sem_incremental
from topoone_app_architect.arch_routes.sem import codegraph as _sem_codegraph


def _ctx(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    # 重置模块级 ctx 单例，确保隔离
    C._db = None
    C._kb = None
    db = C.setup(data_dir=data)
    return db


def _run_coro(coro):
    import asyncio
    import json as _json
    from fastapi.responses import JSONResponse
    out = asyncio.run(coro)
    if isinstance(out, JSONResponse):
        return _json.loads(out.body.decode("utf-8"))
    return out


def _assets(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    return S


def test_store_crud_and_search(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    now = 1
    store.SemanticAssetsStore.create({
        "id": "sa-s-l-e-1", "projectId": "proj-1", "kind": "entity",
        "level": "logic", "name": "订单聚合", "desc": "订单核心数据结构", "detail": {"fields": []},
        "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                     "startLine": 1, "endLine": 10}],
        "scopeType": "comm", "scopeKey": "L0-0001", "source": "live",
        "srcHash": "h1", "change": "added", "status": "active",
        "createdAt": now, "updatedAt": now,
    })
    got = store.SemanticAssetsStore.get("sa-s-l-e-1")
    assert got["name"] == "订单聚合"
    assert got["astRefs"][0]["file"] == "src/order.py"          # JSON 列解码
    assert got["detail"] == {"fields": []}                      # JSON 列解码
    assert got["level"] == "logic"                             # 粒度列
    assert store.SemanticAssetsStore.search("proj-1", text="订单")[0]["id"] == "sa-s-l-e-1"
    assert store.SemanticAssetsStore.search("proj-1", kind="process") == []
    assert len(store.SemanticAssetsStore.find_by_scope("proj-1", "comm", "L0-0001")) == 1


def test_store_search_scope_filter(tmp_path, monkeypatch):
    """search/count 按 scope_key 精确过滤；__other__ 哨兵选非 comm 范围资产。"""
    _ctx(tmp_path, monkeypatch)
    for i, (scope_type, scope_key) in enumerate([
        ("comm", "L0-0001"), ("comm", "L0-0002"), ("files", "src/a.py"),
    ]):
        store.SemanticAssetsStore.create({
            "id": f"sa-d-{i}", "projectId": "proj-s", "kind": "asset",
            "level": "logic", "name": f"资产{i}", "desc": f"d{i}", "detail": {},
            "astRefs": [{"file": f"src/{i}.py", "symbol": "S", "kind": "class",
                         "startLine": 1, "endLine": 2}],
            "scopeType": scope_type, "scopeKey": scope_key, "source": "live",
            "srcHash": f"h{i}", "change": "added", "status": "active",
            "createdAt": 1, "updatedAt": 1,
        })
    # 单个 scope_key
    got = store.SemanticAssetsStore.search("proj-s", scopes=["L0-0001"])
    assert [a["id"] for a in got] == ["sa-d-0"]
    assert store.SemanticAssetsStore.count("proj-s", scopes=["L0-0001"]) == 1
    # 多个 scope_key
    got = store.SemanticAssetsStore.search("proj-s", scopes=["L0-0001", "L0-0002"])
    assert len(got) == 2
    # 仅「其它」→ 非 comm 范围
    got = store.SemanticAssetsStore.search("proj-s", scopes=["__other__"])
    assert [a["id"] for a in got] == ["sa-d-2"]
    # 组件 + 其它(OR)
    got = store.SemanticAssetsStore.search("proj-s", scopes=["L0-0001", "__other__"])
    assert len(got) == 2
    assert store.SemanticAssetsStore.count("proj-s", scopes=["L0-0001", "__other__"]) == 2
    # 空 scopes → 全部
    assert len(store.SemanticAssetsStore.search("proj-s")) == 3


def test_cross_partition_dedup_and_membership(tmp_path, monkeypatch):
    """INCLUDE/CALL 两套组件对同一代码提取 → 归一为一条资产，归属合并。"""
    _ctx(tmp_path, monkeypatch)
    # 同一文件被 INCLUDE(A) 与 CALL(B) 两套组件同时拥有(两口径互不隶属)
    _patch_all(monkeypatch, "_file_to_components", lambda root, project: {
        "src/order.py": ["A", "B"]})
    # 同一代码(同一锚点)先后在 INCLUDE(A) 与 CALL(B) 组件下提取
    a1 = S._save_assets("proj-n", "comm", "A", [
        {"kind": "asset", "level": "logic", "name": "订单聚合", "desc": "d",
         "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                      "startLine": 1, "endLine": 10}]},
    ], {"table": {}, "source": "live", "srcHash": "h1", "root": "/x"})[0]
    a2 = S._save_assets("proj-n", "comm", "B", [
        {"kind": "asset", "level": "logic", "name": "订单聚合", "desc": "d",
         "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                      "startLine": 1, "endLine": 10}]},
    ], {"table": {}, "source": "live", "srcHash": "h1", "root": "/x"})[0]
    # 同一代码 → 同一 id(身份=代码锚点，与组件口径无关)
    assert a1["id"] == a2["id"]
    got = store.SemanticAssetsStore.get(a1["id"])
    assert got["status"] == "active"
    scopes = (got.get("meta") or {}).get("scopes")
    assert isinstance(scopes, list) and set(scopes) == {"A", "B"}   # 归属合并
    # 两种组件口径检索都能命中同一资产(meta.scopes 多归属)
    assert store.SemanticAssetsStore.count("proj-n", scopes=["A"]) == 1
    assert store.SemanticAssetsStore.count("proj-n", scopes=["B"]) == 1
    assert store.SemanticAssetsStore.count("proj-n", scopes=["A", "B"]) == 1


def test_file_scope_extraction_multi_component_scopes(tmp_path, monkeypatch):
    """任务路径(逐文件 files scope 落库)：资产归属到所有拥有该文件的组件。

    文件级去重(跳过的组件不重复提取)不丢失归属 —— 被跳过的组件视角
    (列表检索/关系图同条件)也能看到该资产。"""
    _ctx(tmp_path, monkeypatch)
    _patch_all(monkeypatch, "_file_to_components", lambda root, project: {
        "src/shared.py": ["comp-A", "comp-B", "comp-C"]})
    saved = S._save_assets("proj-f", "files", "src/shared.py", [
        {"kind": "process", "level": "implementation", "name": "共享流程", "desc": "d",
         "astRefs": [{"file": "src/shared.py", "symbol": "run", "kind": "func",
                      "startLine": 1, "endLine": 9}]},
    ], {"table": {}, "source": "codegraph", "srcHash": "h1", "root": "/x",
        "project": "proj-f", "files": ["src/shared.py"]})
    got = store.SemanticAssetsStore.get(saved[0]["id"])
    assert (got.get("meta") or {}).get("scopes") == ["comp-A", "comp-B", "comp-C"]
    for cid in ("comp-A", "comp-B", "comp-C"):
        assert store.SemanticAssetsStore.count("proj-f", scopes=[cid]) == 1


def test_component_file_map_ttl_cache(tmp_path, monkeypatch):
    """组件文件映射短 TTL 缓存：提取任务逐文件落库不再每文件打一次 KB。"""
    _ctx(tmp_path, monkeypatch)
    S._comp_file_map_cache.clear()
    calls = {"n": 0}

    def _fake_catalog(root, project):
        calls["n"] += 1
        return {"components": [
            {"id": "c1", "owns": ["a/x.py"]},
            {"id": "c2", "owns": ["a/x.py", "a/y.py"]},
        ]}

    monkeypatch.setattr("topoone_app_architect.arch_routes.common.build_component_catalog",
                        _fake_catalog)
    m1 = S._component_file_map("/root-cachetest", "proj-cache")
    m2 = S._component_file_map("/root-cachetest", "proj-cache")
    try:
        assert calls["n"] == 1                       # TTL 内二次命中缓存
        assert m1 == m2
        assert m1["c2"] == {"a/x.py", "a/y.py"}
        assert m1["c1"] == {"a/x.py"}
    finally:
        S._comp_file_map_cache.clear()


def test_component_file_map_model_fallback(tmp_path, monkeypatch):
    """组件目录为空(降级/无基线) → 回退架构模型装配组件文件映射(与 _comm_files 口径一致)。"""
    _ctx(tmp_path, monkeypatch)
    S._comp_file_map_cache.clear()
    monkeypatch.setattr("topoone_app_architect.arch_routes.common.build_component_catalog",
                        lambda root, project: {"components": []})
    monkeypatch.setattr("topoone_app_architect.arch_routes.common.build_architecture_model",
                        lambda root, project: {"components": [
                            {"id": "m1", "owns": ["b/z.py"]}
                        ]})
    try:
        m = S._component_file_map("/root-fb", "proj-fb")
        assert m == {"m1": {"b/z.py"}}
    finally:
        S._comp_file_map_cache.clear()


def test_save_assets_change_detection(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    assets = [{
        "kind": "asset", "level": "logic", "name": "订单聚合", "desc": "订单核心结构",
        "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                     "startLine": 1, "endLine": 10}],
    }]
    ctx = {"table": {}, "source": "live", "srcHash": "hash-v1"}
    saved1 = S._save_assets("proj-1", "comm", "L0-0001", assets, ctx)
    assert saved1[0]["change"] == "added"

    saved2 = S._save_assets("proj-1", "comm", "L0-0001", assets, ctx)
    assert saved2[0]["change"] == "same"
    assert saved2[0]["id"] == saved1[0]["id"]

    ctx3 = {"table": {}, "source": "live", "srcHash": "hash-v2"}  # 源码变化 → modified
    saved3 = S._save_assets("proj-1", "comm", "L0-0001", assets, ctx3)
    assert saved3[0]["change"] == "modified"

    # 删除的旧资产 → stale
    assets2 = [{"kind": "process", "level": "logic", "name": "下单流程", "desc": "流程"}]
    S._save_assets("proj-1", "comm", "L0-0001", assets2, ctx3)
    old = store.SemanticAssetsStore.get(saved1[0]["id"])
    assert old["status"] == "stale"


def test_resolve_ast_refs(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    table = {
        "Order": {"id": "n1", "kind": "class", "name": "Order",
                  "qualified_name": "src::Order", "file_path": "src/order.py",
                  "start_line": 1, "end_line": 10},
        "checkout": {"id": "n2", "kind": "method", "name": "checkout",
                     "qualified_name": "Order::checkout", "file_path": "src/order.py",
                     "start_line": 20, "end_line": 25},
    }
    refs = S.resolve_ast_refs(["Order", "checkout", "MISSING"], table)
    by_sym = {r["symbol"]: r for r in refs}
    assert set(by_sym) == {"src::Order", "Order::checkout"}
    assert by_sym["src::Order"]["kind"] == "class"
    assert by_sym["src::Order"]["startLine"] == 1
    assert by_sym["Order::checkout"]["kind"] == "method"


def test_context_block_for(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    store.SemanticAssetsStore.create({
        "id": "sa-s-l-e-9", "projectId": "proj-1", "kind": "entity",
        "level": "logic", "name": "订单聚合", "desc": "订单核心结构", "detail": {},
        "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                     "startLine": 1, "endLine": 10}],
        "scopeType": "comm", "scopeKey": "k", "source": "live",
        "srcHash": "h", "change": "added", "status": "active",
        "createdAt": 1, "updatedAt": 1,
    })
    block = S.context_block_for("/tmp/x", None, ["实现下单", "sa-s-l-e-9"])
    assert "订单聚合" in block
    assert "src/order.py:L1-L10" in block
    assert S.context_block_for("/tmp/x", None, ["无资产上下文"]) == ""


def test_extract_scope_heuristic(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "order.py").write_text(
        "class Order:\n    \"\"\"订单核心结构\"\"\"\n    pass\n\n"
        "def checkout(order):\n    pass\n", encoding="utf-8")
    # 使测试确定走 live 扫描(KB 兜底路径可能被本机运行中的 KB 命中)。
    _patch_all(monkeypatch, "_kb_parse_file", lambda *a, **k: None)
    # ensure_synced 现在会对无索引项目自动 codegraph init(真实 CLI)，打桩隔离。
    _patch_all(monkeypatch, "ensure_synced", lambda *a, **k: False)
    res = S.extract_scope(str(proj), None, scope_type="files", scope_key="order",
                          files=["order.py"], kinds=["entity", "process"],
                          use_llm=False)
    assert res["count"] >= 2
    kinds = {a["kind"] for a in res["assets"]}
    assert "entity" in kinds and "process" in kinds
    ds = next(a for a in res["assets"] if a["kind"] == "entity")
    assert ds["astRefs"][0]["file"] == "order.py"
    assert ds["name"] == "Order"
    assert "订单核心结构" in ds["desc"]
    # 锚定文件哈希签名(要求①)
    assert ds["anchorHashes"] == {"order.py": S._file_md5(str(proj), "order.py")}
    assert ds["needsUpdate"] == 0


def _mk_asset(project_id, asset_id="sa-s-i-e-99", anchors=None, **kw):
    store.SemanticAssetsStore.create({
        "id": asset_id, "projectId": project_id, "kind": "entity",
        "level": "logic", "name": "订单聚合", "desc": "订单核心结构", "detail": {},
        "astRefs": [{"file": f, "symbol": "Order", "kind": "class",
                     "startLine": 1, "endLine": 10} for f in (anchors or ["order.py"])],
        "anchorHashes": anchors or {"order.py": "oldhash"},
        "scopeType": "comm", "scopeKey": "L0-0001", "source": "live",
        "srcHash": "h", "change": "added", "status": "active",
        "needsUpdate": 0, "createdAt": 1, "updatedAt": 1,
    })


def test_reconcile_invalidates_on_file_change(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "order.py").write_text("class Order:\n    pass\n", encoding="utf-8")
    root = str(proj)
    pid = S.project_id_for(root, None)
    # 锚定哈希 = 旧内容 → 与当前 md5 不同 → 应失效
    _mk_asset(pid, anchors={"order.py": "0000000000000000"})
    _patch_all(monkeypatch, "changed_files", lambda r, project: {
        "added": [], "modified": ["order.py"], "deleted": []})
    res = S.reconcile_semantic(root, None, force=True)
    assert res["invalidated"] == ["sa-s-i-e-99"]
    a = store.SemanticAssetsStore.get("sa-s-i-e-99")
    assert a["status"] == "stale" and a["needsUpdate"] == 1


def test_reconcile_skips_when_anchor_hash_unchanged(tmp_path, monkeypatch):
    """git 报 modified 但 anchor 哈希与当前一致(刚刷新) → 不重复失效。"""
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "order.py").write_text("class Order:\n    pass\n", encoding="utf-8")
    root = str(proj)
    pid = S.project_id_for(root, None)
    _mk_asset(pid, anchors={"order.py": S._file_md5(root, "order.py")})
    _patch_all(monkeypatch, "changed_files", lambda r, project: {
        "added": [], "modified": ["order.py"], "deleted": []})
    res = S.reconcile_semantic(root, None, force=True)
    assert res["invalidated"] == []
    assert store.SemanticAssetsStore.get("sa-s-i-e-99")["status"] == "active"


def test_reconcile_deleted_file(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    _mk_asset(pid, asset_id="sa-s-i-e-98", anchors={"order.py": "oldhash"})
    _patch_all(monkeypatch, "changed_files", lambda root, project: {
        "added": [], "modified": [], "deleted": ["order.py"]})
    S.reconcile_semantic("/tmp/x", None, force=True)
    assert store.SemanticAssetsStore.get("sa-s-i-e-98")["change"] == "deleted"


def test_reconcile_new_file_reverse_probe(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    _mk_asset(pid, asset_id="sa-s-i-e-97", anchors={"dep.py": "h"})
    _patch_all(monkeypatch, "changed_files", lambda root, project: {
        "added": ["new_mod.py"], "modified": [], "deleted": []})
    _patch_all(monkeypatch, "probe_impact", lambda root, project, files: {
        "dependents": ["dep.py"], "deps": [], "affectedFiles": ["new_mod.py", "dep.py"]})
    res = S.reconcile_semantic("/tmp/x", None, force=True)
    assert res["newFiles"] == ["new_mod.py"]
    assert "sa-s-i-e-97" in res["invalidated"]
    assert store.SemanticAssetsStore.get("sa-s-i-e-97")["needsUpdate"] == 1


def test_soft_delete_and_regenerate(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    _mk_asset(pid)
    # refresh 成功路径(同 scope 重新生成)
    from topoone_app_architect.arch_routes import semantic_assets as SM
    store.SemanticAssetsStore.mark_deleted("sa-s-i-e-99")
    assert store.SemanticAssetsStore.get("sa-s-i-e-99")["status"] == "deleted"
    # 重新提取同名资产 → 恢复 active(软删后重新生成)
    assets = [{"kind": "asset", "level": "logic", "name": "订单聚合", "desc": "新描述",
               "astRefs": [{"file": "order.py", "symbol": "Order", "kind": "class",
                            "startLine": 1, "endLine": 10}]}]
    ctx = {"table": {}, "source": "live", "srcHash": "h2", "root": "/tmp/x"}
    saved = SM._save_assets(pid, "comm", "L0-0001", assets, ctx)
    assert saved[0]["status"] == "active"
    assert saved[0]["change"] == "modified"


def test_batch_clear_by_comm_scope(tmp_path, monkeypatch):
    """clear 仅作用于选定组件范围(comm scope)，其他组件不受影响。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    store.SemanticAssetsStore.create({
        "id": "sa-d-11", "projectId": pid, "kind": "asset", "level": "logic",
        "name": "A1", "desc": "", "detail": {}, "astRefs": [{"file": "a.py"}],
        "scopeType": "comm", "scopeKey": "L0-0001", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    store.SemanticAssetsStore.create({
        "id": "sa-d-12", "projectId": pid, "kind": "asset", "level": "logic",
        "name": "B1", "desc": "", "detail": {}, "astRefs": [{"file": "b.py"}],
        "scopeType": "comm", "scopeKey": "L0-0002", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    res = S.batch_manage("/tmp/x", None, "clear", comp_ids=["L0-0001"])
    assert res["action"] == "clear"
    assert "sa-d-11" in res["cleared"]
    assert store.SemanticAssetsStore.get("sa-d-11") is None      # 物理删除
    assert store.SemanticAssetsStore.get("sa-d-12") is not None  # 其他组件不受影响


def test_batch_clear_no_selection_clears_all(tmp_path, monkeypatch):
    """无任何选择时清除 → 全部语义资产(含无锚点 H 级聚合)都被物理删除。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    assets = [
        {"id": "sa-d-41", "kind": "asset", "level": "logic", "name": "A",
         "astRefs": [{"file": "svc/a.py"}], "scopeType": "comm", "scopeKey": "L0-0001"},
        {"id": "sa-f-42", "kind": "process", "level": "logic", "name": "B",
         "astRefs": [{"file": "tmp/b.py"}], "scopeType": "files", "scopeKey": "_"},
        {"id": "sa-hb-43", "kind": "process", "level": "business", "name": "H",
         "astRefs": [], "scopeType": "project", "scopeKey": "business"},
    ]
    for a in assets:
        a.update({"projectId": pid, "desc": "", "detail": {}, "srcHash": "h",
                  "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
        store.SemanticAssetsStore.create(a)
    # 空选 + 其它(前端「不做任何选项操作」) → scopes=None → 全部清除
    res = S.batch_manage("/tmp/x", None, "clear", comp_ids=[], include_other=True)
    assert sorted(res["cleared"]) == ["sa-d-41", "sa-f-42", "sa-hb-43"]
    for aid in assets:
        assert store.SemanticAssetsStore.get(aid["id"]) is None  # 物理删除


def test_batch_clear_other_only_keeps_components(tmp_path, monkeypatch):
    """仅「其它」范围清除 → 非组件文件/无锚点资产删除，组件资产保留。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    assets = [
        {"id": "sa-d-51", "kind": "asset", "level": "logic", "name": "A",
         "astRefs": [{"file": "svc/a.py"}], "scopeType": "comm", "scopeKey": "L0-0001"},
        {"id": "sa-f-52", "kind": "process", "level": "logic", "name": "B",
         "astRefs": [{"file": "tmp/b.py"}], "scopeType": "files", "scopeKey": "_"},
    ]
    for a in assets:
        a.update({"projectId": pid, "desc": "", "detail": {}, "srcHash": "h",
                  "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
        store.SemanticAssetsStore.create(a)
    # 真实场景：组件目录把 svc/a.py 归入 L0-0001。
    _patch_all(monkeypatch, "_component_file_map", lambda root, project: {"L0-0001": {"svc/a.py"}})
    # 仅「其它」范围(scopes=['__other__'])
    res = S.batch_manage("/tmp/x", None, "clear", comp_ids=[], include_other=True,
                         scopes=["__other__"])
    assert res["cleared"] == ["sa-f-52"]
    assert store.SemanticAssetsStore.get("sa-d-51") is not None  # 组件资产保留
    assert store.SemanticAssetsStore.get("sa-f-52") is None       # 物理删除


def test_batch_clear_by_file_with_include_other(tmp_path, monkeypatch):
    """clear 按文件归属匹配；include_other 覆盖未列组件的文件资产。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    store.SemanticAssetsStore.create({
        "id": "sa-d-21", "projectId": pid, "kind": "asset", "level": "logic",
        "name": "X", "desc": "", "detail": {}, "astRefs": [{"file": "svc/x.py"}],
        "scopeType": "files", "scopeKey": "_", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    store.SemanticAssetsStore.create({
        "id": "sa-d-22", "projectId": pid, "kind": "asset", "level": "logic",
        "name": "Y", "desc": "", "detail": {}, "astRefs": [{"file": "tmp/y.py"}],
        "scopeType": "project", "scopeKey": "_", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    _patch_all(monkeypatch, "_component_file_map", lambda root, project: {
        "L0-0001": {"svc/x.py"}})
    # 仅选 L0-0001 → 命中 svc/x.py，不命中 tmp/y.py
    res = S.batch_manage("/tmp/x", None, "clear", comp_ids=["L0-0001"])
    assert "sa-d-21" in res["cleared"]
    assert store.SemanticAssetsStore.get("sa-d-22") is not None   # 其他文件保留
    assert store.SemanticAssetsStore.get("sa-d-21") is None       # 物理删除
    # 追加 include_other → tmp/y.py(未列组件的文件)也被清除
    res2 = S.batch_manage("/tmp/x", None, "clear",
                          comp_ids=["L0-0001"], include_other=True)
    assert "sa-d-22" in res2["cleared"]
    assert store.SemanticAssetsStore.get("sa-d-22") is None       # 物理删除


def test_batch_no_separate_update_action(tmp_path, monkeypatch):
    """不存在独立的 update 概念：update action 不再执行任何更新。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    store.SemanticAssetsStore.create({
        "id": "sa-d-31", "projectId": pid, "kind": "asset", "level": "logic",
        "name": "S", "desc": "", "detail": {}, "astRefs": [{"file": "a.py"}],
        "scopeType": "comm", "scopeKey": "L0-0001", "srcHash": "h",
        "change": "modified", "status": "stale", "needsUpdate": 1,
        "createdAt": 1, "updatedAt": 1})
    calls = {"n": 0}
    def fake_handle(asset_id, root, project, model_id=None):
        calls["n"] += 1
        return {"status": "refreshed"}
    _patch_all(monkeypatch, "handle_stale_asset", fake_handle)
    res = S.batch_manage("/tmp/x", None, "update", comp_ids=["L0-0001"])
    assert res["count"] == 0
    assert calls["n"] == 0
    # 更新路径 = clear(删除) 后再 extract(重跑提取)
    assert store.SemanticAssetsStore.get("sa-d-31") is not None


def test_comm_files_falls_back_to_catalog(tmp_path, monkeypatch):
    """模型(INCLUDE·L1)查不到的组件 id(如 CALL/L0) → 回退组件目录解析文件。"""
    _ctx(tmp_path, monkeypatch)
    import topoone_app_architect.arch_routes.common as common
    monkeypatch.setattr(common, "build_architecture_model", lambda *a, **k: {
        "components": [{"id": "L1-0001", "owns": ["svc/model.py"]}]})
    monkeypatch.setattr(common, "build_component_catalog", lambda *a, **k: {
        "components": [{"id": "L0-0009", "owns": ["svc/call.py", "svc/util.py"]}]})
    # 模型内组件 → 走模型
    assert S._comm_files("/tmp/x", "L1-0001") == ["svc/model.py"]
    # 目录独有组件(CALL/L0) → 走目录回退
    assert S._comm_files("/tmp/x", "L0-0009") == ["svc/call.py", "svc/util.py"]
    # 都不存在 → 空
    assert S._comm_files("/tmp/x", "nope") == []


def test_extract_comm_unresolved_returns_empty(tmp_path, monkeypatch):
    """comm 组件未命中目录/模型(文件为空)时，不得退化为全项目扫描。"""
    _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr("topoone_app_architect.arch_routes.common.build_component_catalog",
                        lambda root, project: {"components": []})
    monkeypatch.setattr("topoone_app_architect.arch_routes.common.build_architecture_model",
                        lambda *a, **k: {"components": []})
    # 即使存在 codegraph 节点，未解析文件的 comm 范围也不应扫全项目。
    _patch_all(monkeypatch, "_query_nodes", lambda conn, files=None, symbols=None, limit=400: [
        {"id": "n1", "kind": "class", "name": "Other", "qualified_name": "Other",
         "file_path": "other/thing.py", "start_line": 1, "end_line": 1,
         "start_column": 0, "end_column": 0, "signature": "", "docstring": "",
         "return_type": ""}])
    res = S.extract_scope("/tmp/x", None, scope_type="comm", scope_key="MISSING-1",
                          kinds=["asset"], use_llm=False)
    assert res["count"] == 0
    assert res["source"] == "none"
    # 未命中必须显式带失败原因（不再静默空结果）
    assert res.get("error")
    assert res.get("candidates") == []


def test_comm_files_ex_matching(tmp_path, monkeypatch):
    """comm 解析匹配链：精确 id → 精确名称 → 忽略大小写 → 唯一子串；多义/全未命中返回候选。"""
    _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr("topoone_app_architect.arch_routes.common.build_component_catalog",
                        lambda root, project: {"components": [
                            {"id": "comm-1", "name": "拓扑图渲染引擎", "owns": ["a/x.ts"]},
                            {"id": "comm-2", "name": "PlantUML渲染引擎", "owns": ["b/y.ts"]},
                            {"id": "comm-3", "name": "图表转译引擎", "owns": ["c/z.ts"]},
                        ]})
    monkeypatch.setattr("topoone_app_architect.arch_routes.common.build_architecture_model",
                        lambda *a, **k: {"components": []})
    # 1) 精确 id
    files, err = S._comm_files_ex("/r", "comm-1")
    assert files == ["a/x.ts"] and err is None
    # 2) 精确名称（组件中文名，非 id）
    files, err = S._comm_files_ex("/r", "拓扑图渲染引擎")
    assert files == ["a/x.ts"] and err is None
    # 3) 唯一子串（"plantuml" 仅命中 comm-2）
    files, err = S._comm_files_ex("/r", "plantuml")
    assert files == ["b/y.ts"] and err is None
    # 4) 项目名当 key（全未命中）→ error + 全量候选清单
    files, err = S._comm_files_ex("/r", "topoOne-animation")
    assert files == [] and err and len(err["candidates"]) == 3
    assert "未命中" in err["error"]
    # 5) 多义子串（"渲染引擎" 命中 comm-1/comm-2）→ 不猜，返回候选
    files, err = S._comm_files_ex("/r", "渲染引擎")
    assert files == [] and err and len(err["candidates"]) == 2


def test_extract_comm_miss_carries_candidates(tmp_path, monkeypatch):
    """comm 未命中 → extract_scope 返回 error+候选清单（agent 可如实报告并请用户重选）。"""
    _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr("topoone_app_architect.arch_routes.common.build_component_catalog",
                        lambda root, project: {"components": [
                            {"id": "comm-1", "name": "拓扑图渲染引擎", "owns": ["a/x.ts"]},
                            {"id": "comm-2", "name": "PlantUML渲染引擎", "owns": ["b/y.ts"]},
                        ]})
    monkeypatch.setattr("topoone_app_architect.arch_routes.common.build_architecture_model",
                        lambda *a, **k: {"components": []})
    res = S.extract_scope("/tmp/x", None, scope_type="comm", scope_key="topoOne-animation",
                          kinds=["asset"], use_llm=False)
    assert res["count"] == 0
    assert "未命中" in (res.get("error") or "")
    assert [c["id"] for c in res.get("candidates") or []] == ["comm-1", "comm-2"]


def test_source_snippet_window(tmp_path, monkeypatch):
    """锚点前后源码窗口：默认 ±10 行 + 符号体展开 + 上限裁剪。"""
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    src = proj / "a.py"
    lines = [f"line-{i:02d}" for i in range(1, 81)]
    src.write_text("\n".join(lines), encoding="utf-8")
    res = _run_coro(S.api_source_snippet(root=str(proj), project=None,
                                         file="a.py", line=20, symbol="", before=10, after=10))
    assert res["code"] == 0
    data = res["data"]
    assert data["anchorLine"] == 20
    assert data["lines"][0]["line"] == 10          # 20-10
    assert data["lines"][-1]["line"] == 30         # 20+10
    assert len(data["lines"]) == 21
    assert data["lines"][10]["code"] == "line-20"  # 锚点行本身
    assert data["highlight"] == []


def test_source_snippet_symbol_expand_and_cap(tmp_path, monkeypatch):
    """符号体展开（AST 缓存有行段 → 覆盖整段）+ 超长上限裁剪。"""
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    src = proj / "b.py"
    src.write_text("\n".join(f"code-{i}" for i in range(1, 201)), encoding="utf-8")
    pid = S.project_id_for(str(proj), None)
    store.AstCacheStore.upsert(pid, "b.py", {
        "contentHash": "h", "language": "py",
        "symbols": [{"name": "fn", "startLine": 30, "endLine": 90}],
        "imports": [], "refs": [], "source": "kb"})
    # 默认窗口 ±10 行内，符号体 30-90 超限 → 上限裁剪到 60 行，起点仍为 anchor 前 10
    res = _run_coro(S.api_source_snippet(root=str(proj), project=None,
                                         file="b.py", line=30, symbol="fn"))
    data = res["data"]
    assert data["lines"][0]["line"] == 20          # 30-10
    assert len(data["lines"]) == 60                # limit 上限
    # 高亮覆盖符号体在窗口内的行段
    assert data["highlight"] and data["highlight"][0] == 30
    # 小符号体：整段显示
    store.AstCacheStore.upsert(pid, "b.py", {
        "contentHash": "h", "language": "py",
        "symbols": [{"name": "fn", "startLine": 30, "endLine": 33}],
        "imports": [], "refs": [], "source": "kb"})
    res2 = _run_coro(S.api_source_snippet(root=str(proj), project=None,
                                          file="b.py", line=30, symbol="fn"))
    d2 = res2["data"]
    assert d2["lines"][0]["line"] == 20            # 30-10（before 默认）
    assert d2["lines"][-1]["line"] == 43           # 33+10（after 默认尾部余量）
    assert d2["highlight"] == [30, 31, 32, 33]


def test_source_snippet_path_safety(tmp_path, monkeypatch):
    """越界路径拒绝。"""
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    res = _run_coro(S.api_source_snippet(root=str(proj), project=None,
                                         file="../etc/passwd", line=1))
    assert res["code"] != 0


def test_ast_cache_store(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    AstCache = store.AstCacheStore
    AstCache.upsert("proj-1", "a.py", {"contentHash": "c1", "language": "py",
                                       "symbols": [{"name": "A"}], "imports": ["b"],
                                       "refs": [], "source": "kb"})
    row = AstCache.get("proj-1", "a.py")
    assert row["contentHash"] == "c1"
    assert row["symbols"][0]["name"] == "A"
    AstCache.upsert("proj-1", "a.py", {"contentHash": "c2", "language": "py",
                                       "symbols": [], "imports": [], "refs": [],
                                       "source": "kb"})
    assert AstCache.get("proj-1", "a.py")["contentHash"] == "c2"
    assert AstCache.invalidate("proj-1", ["a.py"]) == 1
    assert AstCache.get("proj-1", "a.py") is None


def test_probe_impact_cache_fallback(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    # 无 codegraph → cache 反向索引(imports 解析)
    pid = S.project_id_for("/tmp/x", None)
    store.AstCacheStore.upsert(pid, "consumer.py", {
        "contentHash": "h", "language": "py",
        "symbols": [{"name": "use"}], "imports": ["services/new_mod"],
        "refs": [], "source": "kb"})
    res = S.probe_impact("/tmp/x", None, ["services/new_mod.py"])
    assert "consumer.py" in res["dependents"]
    assert set(res["affectedFiles"]) == {"services/new_mod.py", "consumer.py"}


def test_norm_cache_symbol(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    n = S._norm_cache_symbol("a.py", "python", {
        "name": "Order", "kind": "class", "qualifiedName": "Order",
        "startLine": 3, "endLine": 12, "signature": "()", "docstring": "d"})
    assert n["start_line"] == 3 and n["kind"] == "class"
    assert S._norm_cache_symbol("a.py", "python", {"name": ""}) is None


def test_normalize_kind_aliases():
    """kind/type 中文、驼峰、带空格变体 → 规范枚举(新六类：静态4+动态2)。"""
    assert S._normalize_kind("data_structure") == "entity"
    assert S._normalize_kind("数据结构") == "entity"
    assert S._normalize_kind("DataStructure") == "entity"
    assert S._normalize_kind("data structure") == "entity"
    assert S._normalize_kind("asset") == "entity"
    assert S._normalize_kind("静态资产") == "entity"
    assert S._normalize_kind("处理流程") == "process"
    assert S._normalize_kind("processingFlow") == "process"
    assert S._normalize_kind("processing_flow") == "process"
    assert S._normalize_kind("控制逻辑") == "decision"
    assert S._normalize_kind("control-logic") == "decision"
    assert S._normalize_kind("contract") == "contract"
    assert S._normalize_kind("接口") == "contract"
    assert S._normalize_kind("rule") == "rule"
    assert S._normalize_kind("业务规则") == "rule"
    assert S._normalize_kind("policy") == "rule"
    assert S._normalize_kind("state") == "state"
    assert S._normalize_kind("状态机") == "state"
    assert S._normalize_kind("unknown-kind") is None
    assert S._normalize_kind("") is None


def test_normalize_level_aliases():
    """level 中/英/概念变体 → 规范枚举(新三档)。"""
    assert S._normalize_level("high") == "business"
    assert S._normalize_level("概念") == "business"
    assert S._normalize_level("intent") == "business"
    assert S._normalize_level("业务") == "business"
    assert S._normalize_level("medium") == "logic"
    assert S._normalize_level("逻辑") == "logic"
    assert S._normalize_level("interaction") == "logic"
    assert S._normalize_level("low") == "implementation"
    assert S._normalize_level("代码") == "implementation"
    assert S._normalize_level("algorithm") == "implementation"
    assert S._normalize_level(None) is None


def _anchored(name, file="src/order.py", symbol="Order"):
    return {"kind": "asset", "level": "logic", "name": name, "desc": "d",
            "astRefs": [{"file": file, "symbol": symbol, "kind": "class",
                         "startLine": 1, "endLine": 10}]}


def test_save_assets_canonical_key_stable_across_rename(tmp_path, monkeypatch):
    """LLM 改语义名但锚点不变 → canonicalKey 命中，复用 id，仅记 renamed 溯源。"""
    _ctx(tmp_path, monkeypatch)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    s1 = S._save_assets("proj-1", "comm", "L0-0001",
                        [_anchored("订单聚合")], ctx)[0]
    assert s1["change"] == "added"
    assert s1["canonicalKey"]

    s2 = S._save_assets("proj-1", "comm", "L0-0001",
                        [_anchored("订单根实体")], ctx)[0]   # 改名
    assert s2["id"] == s1["id"]                               # id 复用(引用不断链)
    assert s2["canonicalKey"] == s1["canonicalKey"]           # 锚点指纹稳定
    assert s2["renamedFrom"] == "订单聚合"
    assert "订单聚合" in (s2.get("nameAlias") or [])           # 历史名溯源

    s3 = S._save_assets("proj-1", "comm", "L0-0001",
                        [_anchored("订单根实体")], ctx)[0]
    assert s3["id"] == s1["id"] and s3["change"] == "same"    # 再提取无漂移


def test_save_assets_canonical_key_anchor_move_new_id(tmp_path, monkeypatch):
    """锚点迁移(代码重构到新符号/文件) → 视为新资产，旧资产 stale。"""
    _ctx(tmp_path, monkeypatch)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    s1 = S._save_assets("proj-1", "comm", "L0-0001",
                        [_anchored("订单聚合", "src/order.py", "Order")], ctx)[0]
    s2 = S._save_assets("proj-1", "comm", "L0-0001",
                        [_anchored("订单聚合", "src/order_v2.py", "OrderV2")], ctx)[0]
    assert s2["id"] != s1["id"]                               # 新锚点 → 新 id
    assert store.SemanticAssetsStore.get(s1["id"])["status"] == "stale"


def test_semantic_graph_nodes_edges_anchors(tmp_path, monkeypatch):
    """图谱接口：节点/边(relations 名→id 解析)/锚点。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-g")          # 与 extract_scope 同一解析口径
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "entity", "level": "logic", "name": "订单", "desc": "d",
         "detail": {"relations": [{"target": "用户", "type": "1:N"}]},
         "astRefs": [{"file": "src/order.py", "symbol": "Order",
                      "kind": "class", "startLine": 1, "endLine": 10}]},
        {"kind": "entity", "level": "logic", "name": "用户", "desc": "d",
         "detail": {"relations": []},
         "astRefs": [{"file": "src/user.py", "symbol": "User",
                      "kind": "class", "startLine": 1, "endLine": 8}]},
        {"kind": "process", "level": "logic", "name": "下单流程", "desc": "d",
         "detail": {"inputs": [{"target": "订单", "type": "reads"}],
                    "outputs": [{"target": "用户", "type": "writes"}]},
         "astRefs": [{"file": "src/order.py", "symbol": "checkout",
                      "kind": "func", "startLine": 20, "endLine": 25}]},
    ], ctx)
    g = S.semantic_graph("/tmp/x", "proj-g")
    assert g["count"] == 3
    assert {n["name"] for n in g["nodes"]} == {"订单", "用户", "下单流程"}
    order = next(n for n in g["nodes"] if n["name"] == "订单")
    user = next(n for n in g["nodes"] if n["name"] == "用户")
    proc = next(n for n in g["nodes"] if n["name"] == "下单流程")
    edge = next(e for e in g["edges"] if e["from"] == order["id"])
    assert edge["resolved"] is True and edge["to"] == user["id"]
    # Process 三段端点 → 类型化边(uses/reads/writes)。
    inp = next(e for e in g["edges"] if e["from"] == proc["id"] and e["to"] == order["id"])
    assert inp["type"] == "reads" and inp["resolved"] is True
    out = next(e for e in g["edges"] if e["from"] == proc["id"] and e["to"] == user["id"])
    assert out["type"] == "writes" and out["resolved"] is True
    assert any(a["assetId"] == order["id"] and a["file"] == "src/order.py"
               for a in g["anchors"])


def test_derive_relations_from_ast_edges(tmp_path, monkeypatch):
    """AST 调用/包含边确定性派生资产间 relations(不依赖 LLM 产出)。"""
    _ctx(tmp_path, monkeypatch)
    nodes = [
        {"id": "n1", "kind": "class", "name": "Order", "qualified_name": "Order",
         "file_path": "src/order.py", "start_line": 1, "end_line": 10,
         "start_column": 0, "end_column": 0, "signature": "", "docstring": "", "return_type": ""},
        {"id": "n2", "kind": "function", "name": "checkout", "qualified_name": "checkout",
         "file_path": "src/order.py", "start_line": 20, "end_line": 30,
         "start_column": 0, "end_column": 0, "signature": "(o)", "docstring": "", "return_type": ""},
        {"id": "n3", "kind": "class", "name": "User", "qualified_name": "User",
         "file_path": "src/user.py", "start_line": 1, "end_line": 8,
         "start_column": 0, "end_column": 0, "signature": "", "docstring": "", "return_type": ""},
    ]
    assets = [
        {"kind": "asset", "level": "logic", "name": "订单实体", "desc": "",
         "detail": {}, "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class"}]},
        {"kind": "process", "level": "logic", "name": "下单流程", "desc": "",
         "detail": {}, "astRefs": [{"file": "src/order.py", "symbol": "checkout", "kind": "func"}]},
        {"kind": "asset", "level": "logic", "name": "用户实体", "desc": "",
         "detail": {}, "astRefs": [{"file": "src/user.py", "symbol": "User", "kind": "class"}]},
    ]
    ctx = {"nodes": nodes,
           "edges": [{"source": "n2", "target": "n1", "kind": "calls"},
                     {"source": "n2", "target": "n3", "kind": "calls"}]}
    S._derive_relations_from_edges(assets, ctx)
    checkout = next(a for a in assets if a["name"] == "下单流程")
    rels = {r["target"]: r["type"] for r in checkout["detail"].get("relations", [])}
    assert rels == {"订单实体": "calls", "用户实体": "calls"}
    # 无锚点关系的资产不受影响；同名 target+type 去重
    order = next(a for a in assets if a["name"] == "订单实体")
    assert "relations" not in order["detail"] or order["detail"]["relations"] == []
    assets[0]["detail"]["relations"] = [{"target": "用户实体", "type": "calls"}]
    S._derive_relations_from_edges(assets, ctx)
    assert len(order["detail"]["relations"]) == 1


def test_extract_scope_low_level_paused_and_impl_fallback(tmp_path, monkeypatch):
    """非实现层(level=algorithm)暂停再生返回空；实现层 tAgent 无输出→种子地板兜底。"""
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "order.py").write_text(
        "class Order:\n    pass\n\ndef checkout(o):\n    pass\n", encoding="utf-8")
    _patch_all(monkeypatch, "_kb_parse_file", lambda *a, **k: None)
    # 非实现层：统一暂停再生，返回空(不再整包自由识别)
    res = S.extract_scope(str(proj), None, scope_type="files", scope_key="order",
                          files=["order.py"], kinds=["process"],
                          use_llm=True, level="algorithm")
    assert res["assets"] == [] and res["count"] == 0
    assert res.get("source") == "paused"
    # 实现层：tAgent 无结构化输出 → 种子地板兜底，层级 implementation
    import topoone_app_architect.arch_routes.tagent_extract as TE
    monkeypatch.setattr(TE, "run_extraction_agentic",
                        lambda **k: {"content": "", "output": None})
    res2 = S.extract_scope(str(proj), None, scope_type="files", scope_key="order",
                           files=["order.py"], kinds=["entity", "process"],
                           use_llm=True, level="implementation")
    assert res2["count"] >= 1
    assert all((a.get("level") or "logic") == "implementation" for a in res2["assets"])


def test_store_level_filter(tmp_path, monkeypatch):
    """search/count 支持 level 过滤。"""
    _ctx(tmp_path, monkeypatch)
    store.SemanticAssetsStore.create({
        "id": "sa-s-b-e-1", "projectId": "proj-l", "kind": "entity", "level": "business",
        "name": "领域聚合", "desc": "", "detail": {}, "astRefs": [], "scopeType": "project",
        "scopeKey": "business", "srcHash": "h", "change": "added", "status": "active",
        "createdAt": 1, "updatedAt": 1})
    store.SemanticAssetsStore.create({
        "id": "sa-s-i-e-1", "projectId": "proj-l", "kind": "entity", "level": "implementation",
        "name": "Order 类型", "desc": "", "detail": {}, "astRefs": [], "scopeType": "project",
        "scopeKey": "implementation", "srcHash": "h", "change": "added", "status": "active",
        "createdAt": 1, "updatedAt": 1})
    assert store.SemanticAssetsStore.search("proj-l", level="business")[0]["id"] == "sa-s-b-e-1"
    assert store.SemanticAssetsStore.count("proj-l", level="implementation") == 1
    assert len(store.SemanticAssetsStore.search("proj-l", level="logic")) == 0


def test_aggregate_high_links_parent(tmp_path, monkeypatch):
    """H 级聚合：mock LLM 归纳业务资产并回填下级 parentId。"""
    _ctx(tmp_path, monkeypatch)
    _patch_all(monkeypatch, "_postorder_component_nodes", lambda root, project: [{
        "id": "comm-c1", "name": "订单组件", "desc": "订单域", "owns": ["src/order.py"],
        "direct": ["src/order.py"]}])
    pid = S.project_id_for("/tmp/x", None)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    saved = S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "process", "level": "logic", "name": "下单流程", "desc": "d",
         "astRefs": [{"file": "src/order.py", "symbol": "checkout",
                      "kind": "func", "startLine": 20, "endLine": 30}]},
        {"kind": "entity", "level": "logic", "name": "订单聚合", "desc": "d",
         "astRefs": [{"file": "src/order.py", "symbol": "Order",
                      "kind": "class", "startLine": 1, "endLine": 10}]},
    ], ctx)
    # 给子资产补 scopes，使业务聚合后能推导组件归属
    for a in saved:
        store.SemanticAssetsStore.update(a["id"], {"meta": {"scopes": ["comm-c1"]}})
    child_id = saved[0]["id"]
    import topoone_app_architect.arch_routes.req_agent as RA
    monkeypatch.setattr(RA, "llm_sync", lambda *a, **k: {"output": {"assets": [
        {"kind": "process", "name": "订单创建与结算", "desc": "端到端业务过程",
         "aggregates": [{"assetId": child_id, "role": "core"}]},
    ]}})
    res = S._aggregate_high("/tmp/x", None)
    assert res["count"] == 1
    high = res["assets"][0]
    assert high["level"] == "business"
    assert high["detail"]["aggregates"][0]["assetId"] == child_id
    # 下级资产回填 parentId(组合链)
    child = store.SemanticAssetsStore.get(child_id)
    assert child["parentId"] == high["id"]
    # business 资产聚合下级组件的组件归属(meta.scopes) → 不再归「其它」。
    got_high = store.SemanticAssetsStore.get(high["id"])
    assert got_high is not None
    assert got_high["detail"]["aggregates"][0]["assetId"] == child_id
    assert "comm-c1" in (got_high.get("meta") or {}).get("scopes") or []


def test_leaf_components_resolves_leaves_only(tmp_path, monkeypatch):
    """叶子解析：父组件(有子)不参与聚合，仅叶子被返回且父先子后保序。"""
    _ctx(tmp_path, monkeypatch)
    # mock 组件目录：父 c1 有子 c1-1/c1-2，独立叶子 c2
    from topoone_app_architect.arch_routes import common as CM
    monkeypatch.setattr(CM, "build_component_catalog",
                        lambda root=None, project=None: {"components": [
                            {"id": "c1", "name": "父", "parentId": None, "owns": ["a.py"]},
                            {"id": "c1-1", "name": "子1", "parentId": "c1", "owns": ["a1.py"]},
                            {"id": "c1-2", "name": "子2", "parentId": "c1", "owns": ["a2.py"]},
                            {"id": "c2", "name": "独立", "parentId": None, "owns": ["b.py"]},
                        ]})
    leaves = S._leaf_components("/tmp/x", None)
    ids = [l["id"] for l in leaves]
    assert ids == ["c1-1", "c1-2", "c2"]   # 父 c1 被剔除，子先于独立叶子


def test_postorder_component_nodes_direct_files(tmp_path, monkeypatch):
    """后序遍历：子先于父；中间节点独有文件(未被叶子覆盖)归入其 direct。"""
    _ctx(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import common as CM
    monkeypatch.setattr(CM, "build_component_catalog",
                        lambda root=None, project=None: {"components": [
                            {"id": "c1", "name": "父", "parentId": None,
                             "owns": ["shared.py", "a.py"]},
                            {"id": "c1-1", "name": "子1", "parentId": "c1", "owns": ["a.py"]},
                            {"id": "c2", "name": "独立", "parentId": None, "owns": ["b.py"]},
                        ]})
    nodes = S._postorder_component_nodes("/tmp/x", None)
    ids = [n["id"] for n in nodes]
    assert ids == ["c1-1", "c1", "c2"] or ids == ["c1-1", "c2", "c1"]
    # 子先于父
    assert ids.index("c1-1") < ids.index("c1")
    by_id = {n["id"]: n for n in nodes}
    # c1 的 direct = 自身文件 − 子覆盖(a.py) → 仅 shared.py(中间节点独有文件)
    assert by_id["c1"]["direct"] == ["shared.py"]
    assert by_id["c1-1"]["direct"] == ["a.py"]
    assert by_id["c2"]["direct"] == ["b.py"]


def test_aggregate_high_includes_intermediate_direct(tmp_path, monkeypatch):
    """业务聚合包含中间节点：仅中间节点独有文件产出的逻辑资产也进入 business 聚合。"""
    _ctx(tmp_path, monkeypatch)
    # 中间节点 c1(direct=[shared.py]) + 子 c1-1(direct=[a.py])
    _patch_all(monkeypatch, "_postorder_component_nodes", lambda root, project: [
        {"id": "c1-1", "name": "子", "desc": "子", "owns": ["a.py"], "parentId": "c1",
         "direct": ["a.py"]},
        {"id": "c1", "name": "父", "desc": "父", "owns": ["shared.py", "a.py"], "parentId": None,
         "direct": ["shared.py"]},
    ])
    pid = S.project_id_for("/tmp/x", None)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    # shared.py 只属于中间节点 c1(不属任何叶子)。
    saved = S._save_assets(pid, "files", "shared.py", [
        {"kind": "process", "level": "logic", "name": "共享配置流程", "desc": "d",
         "astRefs": [{"file": "shared.py", "symbol": "sc", "kind": "func",
                      "startLine": 1, "endLine": 2}]}], ctx)
    store.SemanticAssetsStore.update(saved[0]["id"], {"meta": {"scopes": ["c1"]}})
    shared_id = saved[0]["id"]
    import topoone_app_architect.arch_routes.req_agent as RA
    monkeypatch.setattr(RA, "llm_sync", lambda *a, **k: {"output": {"assets": [
        {"kind": "process", "name": "共享配置业务", "desc": "d",
         "aggregates": [{"assetId": shared_id}]}]}})
    res = S._aggregate_high("/tmp/x", None)
    assert res["count"] == 1
    assert res["assets"][0]["name"] == "共享配置业务"
    assert res["assets"][0]["detail"]["aggregates"][0]["assetId"] == shared_id


def test_aggregate_high_per_leaf_batching_and_merge(tmp_path, monkeypatch):
    """按叶子聚合：候选分批完整覆盖(>BATCH 循环)、跨叶子同名 business 合并去重。"""
    _ctx(tmp_path, monkeypatch)
    _patch_all(monkeypatch, "_AGG_BATCH", 2)
    _patch_all(monkeypatch, "_postorder_component_nodes", lambda root, project: [
        {"id": "comm-leafA", "name": "叶子A", "desc": "A", "owns": ["f1.py"], "direct": ["f1.py"]},
        {"id": "comm-leafB", "name": "叶子B", "desc": "B", "owns": ["f2.py"], "direct": ["f2.py"]},
    ])
    pid = S.project_id_for("/tmp/x", None)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    # 4 条 interaction 候选(> BATCH=2 触发分批)，归属叶子A；2 条归属叶子B
    saved = S._save_assets(pid, "files", "f1.py", [
        {"kind": "process", "level": "logic", "name": f"流程{i}", "desc": "d",
         "astRefs": [{"file": f"f{i}.py", "symbol": f"s{i}", "kind": "func",
                      "startLine": 1, "endLine": 2}]} for i in range(4)
    ], ctx)
    savedB = S._save_assets(pid, "files", "f2.py", [
        {"kind": "process", "level": "logic", "name": "共享流程", "desc": "d",
         "astRefs": [{"file": "f2.py", "symbol": "sx", "kind": "func",
                      "startLine": 1, "endLine": 2}]},
    ], ctx)
    for a in saved + savedB:
        scopes = "comm-leafA" if a["id"] in [x["id"] for x in saved] else "comm-leafB"
        store.SemanticAssetsStore.update(a["id"], {"meta": {"scopes": [scopes]}})
    a_ids = [x["id"] for x in saved]
    b_id = savedB[0]["id"]
    import topoone_app_architect.arch_routes.req_agent as RA
    calls = {"n": 0}
    def fake_llm(*a, **k):
        calls["n"] += 1
        body = a[0]
        user = next((m["content"] for m in body if m["role"] == "user"), "")
        # 批次1含 f1 前 2 条；批次2含 f1 后 2 条；批次3含 f2 共享
        if "流程0" in user or "流程1" in user:
            assets = [{"kind": "process", "name": "批次A1", "desc": "d",
                       "aggregates": [{"assetId": a_ids[0]}]}]
        elif "流程2" in user or "流程3" in user:
            assets = [{"kind": "process", "name": "批次A2", "desc": "d",
                       "aggregates": [{"assetId": a_ids[2]}]}]
        else:
            assets = [{"kind": "process", "name": "共享流程聚合", "desc": "d",
                       "aggregates": [{"assetId": b_id}]}]
        return {"output": {"assets": assets}}
    monkeypatch.setattr(RA, "llm_sync", fake_llm)
    res = S._aggregate_high("/tmp/x", None)
    assert res["reason"] == "ok"
    assert res["count"] == 3                       # 批次A1 + 批次A2 + 共享流程聚合
    names = sorted(a["name"] for a in res["assets"])
    assert names == ["共享流程聚合", "批次A1", "批次A2"]
    assert calls["n"] == 3                         # 3 次 LLM 调用(2批A + 1批B)
    # 共享流程聚合只出现在叶子B下(经 _link_parent 从子资产 scopes 聚合)
    shared = next(a for a in res["assets"] if a["name"] == "共享流程聚合")
    shared_db = store.SemanticAssetsStore.get(shared["id"])
    assert (shared_db.get("meta") or {}).get("scopes") == ["comm-leafB"]


def test_aggregate_high_leaf_failure_isolated(tmp_path, monkeypatch):
    """叶子失败隔离：某叶子 LLM 不可达产出 0，其它叶子仍正常产出 business。"""
    _ctx(tmp_path, monkeypatch)
    _patch_all(monkeypatch, "_postorder_component_nodes", lambda root, project: [
        {"id": "comm-bad", "name": "坏叶子", "desc": "B", "owns": ["f_bad.py"], "direct": ["f_bad.py"]},
        {"id": "comm-ok", "name": "好叶子", "desc": "G", "owns": ["f_ok.py"], "direct": ["f_ok.py"]},
    ])
    pid = S.project_id_for("/tmp/x", None)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    bad = S._save_assets(pid, "files", "f_bad.py", [
        {"kind": "process", "level": "logic", "name": "坏流程", "desc": "d",
         "astRefs": [{"file": "f_bad.py", "symbol": "sb", "kind": "func",
                      "startLine": 1, "endLine": 2}]}], ctx)
    ok = S._save_assets(pid, "files", "f_ok.py", [
        {"kind": "process", "level": "logic", "name": "好流程", "desc": "d",
         "astRefs": [{"file": "f_ok.py", "symbol": "sg", "kind": "func",
                      "startLine": 1, "endLine": 2}]}], ctx)
    store.SemanticAssetsStore.update(bad[0]["id"], {"meta": {"scopes": ["comm-bad"]}})
    store.SemanticAssetsStore.update(ok[0]["id"], {"meta": {"scopes": ["comm-ok"]}})
    import topoone_app_architect.arch_routes.req_agent as RA
    ok_id = ok[0]["id"]
    def fake_llm(*a, **k):
        body = a[0]
        user = next((m["content"] for m in body if m["role"] == "user"), "")
        if "f_bad" in user:
            return None   # 坏叶子 LLM 不可达
        return {"output": {"assets": [
            {"kind": "process", "name": "好业务", "desc": "d",
             "aggregates": [{"assetId": ok_id}]}]}}
    monkeypatch.setattr(RA, "llm_sync", fake_llm)
    res = S._aggregate_high("/tmp/x", None)
    assert res["reason"] == "ok"
    assert res["count"] == 1
    assert res["assets"][0]["name"] == "好业务"    # 坏叶子失败未影响好叶子


def test_save_assets_same_batch_dedup_merges_aggregates(tmp_path, monkeypatch):
    """_save_assets 同批内重复 canonicalKey(跨叶子同名 business)：
    复用同一 id、aggregates 并集、scopes 合并，不产生重复行。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    assets = [
        {"kind": "process", "level": "business", "name": "认证服务", "desc": "d",
         "detail": {"aggregates": [{"assetId": "sa-m-p-100"}]}, "astRefs": [], "parentId": ""},
        {"kind": "process", "level": "business", "name": "认证服务", "desc": "d",
         "detail": {"aggregates": [{"assetId": "sa-m-p-200"}]}, "astRefs": [], "parentId": ""},
    ]
    saved = S._save_assets(pid, "project", "business", assets, ctx)
    ids = {a["id"] for a in saved}
    assert len(ids) == 1, "同批同名 business 应复用同一 id"
    row = store.SemanticAssetsStore.get(list(ids)[0])
    aggs = sorted((x.get("assetId") or "") for x in (row.get("detail") or {}).get("aggregates") or [])
    assert aggs == ["sa-m-p-100", "sa-m-p-200"], f"aggregates 应并集, got {aggs}"


def test_aggregate_high_best_effort_retries_on_llm_failure(tmp_path, monkeypatch):
    """聚合失败(LLM 瞬时不可达)时同任务内重试：首次失败后重试成功产出 business 资产。"""
    _ctx(tmp_path, monkeypatch)
    _patch_all(monkeypatch, "_postorder_component_nodes", lambda root, project: [{
        "id": "comm-c1", "name": "订单组件", "desc": "订单域", "owns": ["src/order.py"],
        "direct": ["src/order.py"]}])
    pid = S.project_id_for("/tmp/x", None)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    saved = S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "process", "level": "logic", "name": "下单流程", "desc": "d",
         "astRefs": [{"file": "src/order.py", "symbol": "checkout",
                      "kind": "func", "startLine": 20, "endLine": 30}]},
    ], ctx)
    store.SemanticAssetsStore.update(saved[0]["id"], {"meta": {"scopes": ["comm-c1"]}})
    child_id = saved[0]["id"]
    import topoone_app_architect.arch_routes.req_agent as RA
    calls = {"n": 0}
    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # 首次 LLM 服务不可达 → reason=llm
        return {"output": {"assets": [
            {"kind": "process", "name": "订单创建与结算", "desc": "d",
             "aggregates": [{"assetId": child_id}]},
        ]}}
    monkeypatch.setattr(RA, "llm_sync", flaky)
    # 缩短重试间隔，避免测试慢
    monkeypatch.setattr(S, "time", __import__("time"))
    res = S._aggregate_high_best_effort("/tmp/x", None)
    assert calls["n"] == 2          # 首次失败 + 重试成功
    assert res["count"] == 1        # 重试后产出
    assert res["reason"] == "ok"

def test_aggregate_high_best_effort_failure_visible_after_retries(tmp_path, monkeypatch):
    """聚合持续失败(LLM 不可达)时：重试耗尽后返回失败 reason，不吞掉失败。"""
    _ctx(tmp_path, monkeypatch)
    _patch_all(monkeypatch, "_postorder_component_nodes", lambda root, project: [{
        "id": "comm-c1", "name": "订单组件", "desc": "订单域", "owns": ["src/order.py"],
        "direct": ["src/order.py"]}])
    # 制造一条候选资产(归属该叶子)，使聚合走到 LLM 调用
    pid = S.project_id_for("/tmp/x", None)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    saved = S._save_assets(pid, "files", "src/order.py", [
        {"kind": "process", "level": "logic", "name": "下单流程", "desc": "d",
         "astRefs": [{"file": "src/order.py", "symbol": "checkout",
                      "kind": "func", "startLine": 20, "endLine": 30}]},
    ], ctx)
    store.SemanticAssetsStore.update(saved[0]["id"], {"meta": {"scopes": ["comm-c1"]}})
    import topoone_app_architect.arch_routes.req_agent as RA
    monkeypatch.setattr(RA, "llm_sync", lambda *a, **k: None)
    res = S._aggregate_high_best_effort("/tmp/x", None)
    assert res["count"] == 0
    assert res["reason"] == "llm"


def test_link_parent_propagates_component_membership(tmp_path, monkeypatch):
    """business 聚合资产应继承下级资产的组件归属(meta.scopes)，出现在被聚合组件下。"""
    _ctx(tmp_path, monkeypatch)
    _patch_all(monkeypatch, "_file_to_components", lambda root, project: {
        "src/order.py": ["c-order", "c-pay"]})
    pid = S.project_id_for("/tmp/x", None)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    saved = S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "process", "level": "logic", "name": "下单流程", "desc": "d",
         "astRefs": [{"file": "src/order.py", "symbol": "checkout",
                      "kind": "func", "startLine": 20, "endLine": 30}]},
    ], ctx)
    child_id = saved[0]["id"]
    assert (store.SemanticAssetsStore.get(child_id)["meta"] or {}).get("scopes") == ["c-order", "c-pay"]
    # 直接构造 business 资产并调用 _link_parent(避免走 LLM)
    intent = {"id": "sa-i-t-1", "kind": "asset", "level": "business", "name": "订单域业务功能",
              "desc": "d", "detail": {"aggregates": [{"assetId": child_id}]},
              "astRefs": [], "meta": {}, "status": "active",
              "projectId": pid, "scopeType": "project", "scopeKey": "business"}
    store.SemanticAssetsStore.create(intent)
    S._link_parent(pid, [intent])
    got = store.SemanticAssetsStore.get(intent["id"])
    assert (got["meta"] or {}).get("scopes") == ["c-order", "c-pay"]
    child = store.SemanticAssetsStore.get(child_id)
    assert child["parentId"] == intent["id"]
    # business 资产经 scope 检索能命中 c-order
    got_ids = [a["id"] for a in store.SemanticAssetsStore.search(
        pid, text="", kind="", scopes=["c-order"], limit=20)]
    assert intent["id"] in got_ids


def test_purge_semantic_assets(tmp_path, monkeypatch):
    """物理清理：stale/deleted 行全部删除(不再软删保留)；active 保留。"""
    _ctx(tmp_path, monkeypatch)
    pid = pid_for("/tmp/x", None)
    base = {"projectId": pid, "srcHash": "h", "change": "removed", "status": "deleted",
            "createdAt": 1, "updatedAt": 1, "desc": "", "detail": {}}
    rows = [
        {"id": "sa-d-1", "kind": "asset", "level": "logic", "name": "legacy-del",
         "astRefs": [], "canonicalKey": ""},
        {"id": "sa-f-2", "kind": "process", "level": "logic", "name": "legacy-stale",
         "astRefs": [], "canonicalKey": "", "status": "stale", "change": "removed"},
        # 有 ck 的 stale 旧版本 → 也物理删除(清除=全删)
        {"id": "sa-f-3", "kind": "process", "level": "logic", "name": "ck-stale",
         "astRefs": [{"file": "a.py", "symbol": "A", "kind": "func", "startLine": 1, "endLine": 2}],
         "canonicalKey": "ck-123"},
        # active → 保留
        {"id": "sa-d-4", "kind": "asset", "level": "logic", "name": "active",
         "astRefs": [], "canonicalKey": "ck-456", "status": "active", "change": "added"},
    ]
    for r in rows:
        store.SemanticAssetsStore.create({**base, **r, "status": r.get("status", "deleted")})

    # dry-run 不删除，仅返回影响
    dry = S.purge_semantic_assets("/tmp/x", None, stale_days=7, confirm=False)
    assert dry["dryRun"] is True and dry["purged"] == 0
    assert dry["candidates"] == 3

    # 确认后真正物理删除全部 stale/deleted
    res = S.purge_semantic_assets("/tmp/x", None, stale_days=7, confirm=True)
    assert res["purged"] == 3
    assert store.SemanticAssetsStore.get("sa-d-1") is None
    assert store.SemanticAssetsStore.get("sa-f-2") is None
    assert store.SemanticAssetsStore.get("sa-f-3") is None   # 清除=全删
    assert store.SemanticAssetsStore.get("sa-d-4") is not None   # active → 保留


def test_purge_impact_and_mark(tmp_path, monkeypatch):
    """清理影响识别：需求池引用与未完成任务被识别并标记为需重新生成方案。"""
    _ctx(tmp_path, monkeypatch)
    pid = pid_for("/tmp/x", None)
    base = {"projectId": pid, "srcHash": "h", "change": "removed", "status": "deleted",
            "createdAt": 1, "updatedAt": 1, "desc": "", "detail": {}}
    store.SemanticAssetsStore.create({**base, "id": "sa-d-l-p-9", "kind": "process", "level": "logic",
                                      "name": "flow", "astRefs": [], "canonicalKey": ""})
    # 需求池需求引用 sa-d-l-p-9(assetScope)
    store.RequirementsStore.create({
        "id": "RQ-1", "title": "下单流程", "kind": "user-story", "priority": "P1",
        "location": "pool", "status": "analyzed",
        "analysis": {"assetScope": [{"assetId": "sa-d-l-p-9", "role": "core", "source": "auto"}]},
        "updatedAt": 1,
    })
    # 未完成任务(exec reqIds 关联 RQ-1)
    store.ExecutionTasksStore.create({
        "id": "EX-1", "planId": "PL-1", "reqIds": ["RQ-1"],
        "status": "running", "createdAt": 1, "updatedAt": 1,
    })
    # 草稿需求(proposal 且未分析) → 不在影响范围
    store.RequirementsStore.create({
        "id": "RQ-2", "title": "草稿", "kind": "user-story", "priority": "P2",
        "location": "proposal", "status": "raw",
        "analysis": {"assetScope": [{"assetId": "sa-d-l-p-9", "role": "related", "source": "auto"}]},
        "updatedAt": 1,
    })

    dry = S.purge_semantic_assets("/tmp/x", None, confirm=False)
    imp = dry["impact"]
    assert imp["reqCount"] == 1 and imp["reqCount"] <= 1
    assert any(r["id"] == "RQ-1" for r in imp["requirements"])
    assert all(r["id"] != "RQ-2" for r in imp["requirements"])   # 草稿不纳入
    assert imp["taskCount"] == 1
    assert imp["tasks"][0]["id"] == "EX-1"

    res = S.purge_semantic_assets("/tmp/x", None, confirm=True)
    assert res["purged"] == 1
    assert res["marked"] == {"req": 1, "task": 1}
    assert store.RequirementsStore.get("RQ-1")["assetInvalidated"] == 1
    assert store.ExecutionTasksStore.get("EX-1")["assetInvalidated"] == 1
    # 草稿需求未标记
    assert store.RequirementsStore.get("RQ-2").get("assetInvalidated", 0) == 0


def pid_for(root, project):
    return S.project_id_for(root, project)


def test_semantic_graph_derived_edges_not_persisted(tmp_path, monkeypatch):
    """图谱接口程序化合成 codegraph 派生边(同层平级关系)，且不持久化。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-g2")
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "process", "level": "logic", "name": "下单流程", "desc": "d",
         "detail": {},
         "astRefs": [{"file": "src/order.py", "symbol": "checkout", "kind": "func",
                      "startLine": 20, "endLine": 30}]},
        {"kind": "asset", "level": "logic", "name": "订单实体", "desc": "d",
         "detail": {},
         "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                      "startLine": 1, "endLine": 10}]},
    ], ctx)
    cg = sqlite3.connect(":memory:")
    cg.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, qualified_name TEXT, name TEXT, file_path TEXT DEFAULT '')")
    cg.execute("CREATE TABLE edges (source TEXT, target TEXT, kind TEXT, line INTEGER DEFAULT 0, metadata TEXT DEFAULT '')")
    cg.execute("INSERT INTO nodes VALUES ('n1','checkout','checkout','src/order.py')")
    cg.execute("INSERT INTO nodes VALUES ('n2','Order','Order','src/order.py')")
    cg.execute("INSERT INTO edges VALUES ('n1','n2','calls',22,'{\"confidence\":0.9,\"resolvedBy\":\"exact-match\"}')")
    cg.commit()
    _patch_all(monkeypatch, "_open_cg", lambda root: cg)
    g = S.semantic_graph("/tmp/x", "proj-g2")
    derived = [e for e in g["edges"] if e.get("derived")]
    assert derived, "应从 codegraph 边程序化合成资产边"
    assert {e["from"] for e in derived} <= {n["id"] for n in g["nodes"]}
    assert {e["to"] for e in derived} <= {n["id"] for n in g["nodes"]}
    # 派生边不持久化
    beh = next(n for n in g["nodes"] if n["name"] == "下单流程")
    a = store.SemanticAssetsStore.get(beh["id"])
    assert not (a.get("detail") or {}).get("relations")


def test_derive_edges_evidence_and_contains_expand(tmp_path, monkeypatch):
    """codegraph 派生边：证据字段(line/file/confidence) + contains 闭包展开。"""
    _ctx(tmp_path, monkeypatch)
    cg = sqlite3.connect(":memory:")
    cg.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, qualified_name TEXT, name TEXT, file_path TEXT DEFAULT '')")
    cg.execute("CREATE TABLE edges (source TEXT, target TEXT, kind TEXT, line INTEGER DEFAULT 0, metadata TEXT DEFAULT '')")
    # Order 类资产，其方法 checkout 调 helper —— 关系上卷到 Order
    cg.execute("INSERT INTO nodes VALUES ('n-order','Order','Order','src/order.py')")
    cg.execute("INSERT INTO nodes VALUES ('n-checkout','Order::checkout','checkout','src/order.py')")
    cg.execute("INSERT INTO nodes VALUES ('n-helper','helper','helper','src/util.py')")
    cg.execute("INSERT INTO edges VALUES ('n-order','n-checkout','contains',1,'')")
    cg.execute("INSERT INTO edges VALUES ('n-checkout','n-helper','calls',22,'{\"confidence\":0.9,\"resolvedBy\":\"exact-match\"}')")
    cg.commit()
    _patch_all(monkeypatch, "_open_cg", lambda root: cg)
    assets = [
        {"id": "A", "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class"}]},
        {"id": "B", "astRefs": [{"file": "src/util.py", "symbol": "helper", "kind": "func"}]},
    ]
    edges = S._derive_project_edges("/tmp/x", None, assets)
    ev = [e for e in edges if e["from"] == "A" and e["to"] == "B" and e["type"] == "calls"]
    assert ev, f"contains 展开后应产出 A→B calls 边: {edges}"
    e = ev[0]
    assert e["line"] == 22 and e["file"] == "src/order.py"
    assert e.get("confidence") == "0.9" and e.get("resolvedBy") == "exact-match"


def test_derive_edges_kb_fallback(tmp_path, monkeypatch):
    """无 codegraph → KB 兜底(arch_ast_cache)派生边，与 codegraph 口径同构。"""
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    (proj / "b.py").write_text("def runner():\n    helper()\n", encoding="utf-8")
    _patch_all(monkeypatch, "_open_cg", lambda root: None)
    _patch_all(monkeypatch, "_cache_content_hash", lambda root, rel: "h")
    pid = S.project_id_for(str(proj), None)
    store.AstCacheStore.upsert(pid, "a.py", {
        "contentHash": "h", "language": "py",
        "symbols": [{"name": "helper", "startLine": 1, "endLine": 2}],
        "imports": [], "refs": [], "source": "kb"})
    store.AstCacheStore.upsert(pid, "b.py", {
        "contentHash": "h", "language": "py",
        "symbols": [{"name": "runner", "startLine": 1, "endLine": 2}],
        "imports": [],
        "refs": [{"name": "helper", "kind": "calls", "line": 2, "col": 4}],
        "source": "kb"})
    assets = [
        {"id": "R", "astRefs": [{"file": "b.py", "symbol": "runner", "kind": "func"}]},
        {"id": "H", "astRefs": [{"file": "a.py", "symbol": "helper", "kind": "func"}]},
    ]
    edges = S._derive_project_edges_kb(str(proj), None, assets)
    ev = [e for e in edges if e["from"] == "R" and e["to"] == "H"]
    assert ev, f"KB 兜底应产出 R→H 边: {edges}"
    assert ev[0]["type"] == "calls" and ev[0].get("line") == 2


def test_derive_indirect_edges(tmp_path, monkeypatch):
    """间接边(1 跳中转)：无直接边才产出，via 记录中转，低置信过滤。"""
    _ctx(tmp_path, monkeypatch)
    dbp = tmp_path / "cg.db"
    cg = sqlite3.connect(str(dbp))
    cg.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, qualified_name TEXT, name TEXT, file_path TEXT DEFAULT '')")
    cg.execute("CREATE TABLE edges (source TEXT, target TEXT, kind TEXT, line INTEGER DEFAULT 0, metadata TEXT DEFAULT '')")
    cg.execute("INSERT INTO nodes VALUES ('na','fa','fa','a.py')")
    cg.execute("INSERT INTO nodes VALUES ('nb','fb','fb','b.py')")
    cg.execute("INSERT INTO nodes VALUES ('nm','mid','mid','m.py')")
    cg.execute("INSERT INTO nodes VALUES ('nlow','flow','flow','l.py')")
    # fa → mid(高置信) → fb：A⇝B 间接；mid → flow(低置信) 不参与
    cg.execute("INSERT INTO edges VALUES ('na','nm','calls',3,'{\"confidence\":0.9}')")
    cg.execute("INSERT INTO edges VALUES ('nm','nb','calls',8,'{\"confidence\":0.8}')")
    cg.execute("INSERT INTO edges VALUES ('nm','nlow','calls',9,'{\"confidence\":0.4}')")
    cg.commit()
    cg.close()
    _patch_all(monkeypatch, "_open_cg", lambda root: sqlite3.connect(str(dbp)))
    assets = [
        {"id": "A", "astRefs": [{"file": "a.py", "symbol": "fa", "kind": "func"}]},
        {"id": "B", "astRefs": [{"file": "b.py", "symbol": "fb", "kind": "func"}]},
        {"id": "L", "astRefs": [{"file": "l.py", "symbol": "flow", "kind": "func"}]},
    ]
    edges = S._derive_indirect_edges("/tmp/x", None, assets)
    ab = [e for e in edges if e["from"] == "A" and e["to"] == "B"]
    assert ab and ab[0].get("indirect") and ab[0].get("via") == "mid"
    # 低置信中转不产出 A⇝L
    assert not any(e["to"] == "L" for e in edges), f"低置信边泄漏: {edges}"
    # 已有直接边时不产间接
    cg2 = sqlite3.connect(str(dbp))
    cg2.execute("INSERT INTO edges VALUES ('na','nb','calls',1,'')")
    cg2.commit()
    cg2.close()
    edges2 = S._derive_indirect_edges("/tmp/x", None, assets)
    assert not any(e["from"] == "A" and e["to"] == "B" for e in edges2)


def test_semantic_graph_symbol_target_resolution(tmp_path, monkeypatch):
    """存库基础关系 target 为符号名时，经全量资产索引解析为资产 id。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-s")
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "process", "level": "logic", "name": "下单流程", "desc": "d",
         "detail": {"relations": [{"target": "Order", "type": "calls"}]},
         "astRefs": [{"file": "src/order.py", "symbol": "checkout", "kind": "func",
                      "startLine": 20, "endLine": 30}]},
        {"kind": "asset", "level": "logic", "name": "订单实体", "desc": "d",
         "detail": {},
         "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                      "startLine": 1, "endLine": 10}]},
    ], ctx)
    g = S.semantic_graph("/tmp/x", "proj-s")
    order = next(n for n in g["nodes"] if n["name"] == "订单实体")
    edge = next(e for e in g["edges"] if e["type"] == "calls")
    assert edge["resolved"] is True and edge["to"] == order["id"]


def test_grouped_search_items_contiguous_by_component(tmp_path, monkeypatch):
    """分页检索按「所属组件」分组排序：同一组件资产连续，不跨页分散，「其它」排最后。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-grp")
    for i, (cid, name) in enumerate([
        ("c2", "B1"), ("c1", "A1"), ("c2", "B2"), ("c1", "A2"), ("__other__", "O1"),
    ]):
        store.SemanticAssetsStore.create({
            "id": f"sa-g-{i}", "projectId": pid, "kind": "asset", "level": "logic",
            "name": name, "desc": "", "detail": {}, "astRefs": [],
            "scopeType": "comm", "scopeKey": cid, "source": "live", "srcHash": "h",
            "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1 + i,
        })
    monkeypatch.setattr(_sem_engine, "_component_order_map",
                        lambda *a, **k: ({"c1": 0, "c2": 1}, {}))
    items = S._grouped_search_items("/tmp/x", "proj-grp", "", "", 100, 0, None, "")
    assert [a["scopeKey"] for a in items] == ["c1", "c1", "c2", "c2", "__other__"]
    # 组件内按 updated_at 倒序
    assert [a["name"] for a in items] == ["A2", "A1", "B2", "B1", "O1"]
    # 分页(limit=3)不把同一组件拆散
    page = S._grouped_search_items("/tmp/x", "proj-grp", "", "", 3, 0, None, "")
    assert [a["scopeKey"] for a in page] == ["c1", "c1", "c2"]


def test_semantic_graph_node_detail(tmp_path, monkeypatch):
    """图谱节点附带精简 detail(供类图/ER/序列/状态/聚合图生成)，并做体积裁剪。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-d")
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "asset", "level": "logic", "name": "订单实体", "desc": "d",
         "detail": {"fields": [{"name": "id", "type": "str"}, {"name": "total", "type": "float"}],
                    "relations": [{"target": "用户", "type": "1:N"}]},
         "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                      "startLine": 1, "endLine": 10}]},
        {"kind": "process", "level": "logic", "name": "下单流程", "desc": "d",
         "detail": {"trigger": "create",
                    "steps": [{"order": 1, "semantic": "校验"}, {"order": 2, "semantic": "落库"}]},
         "astRefs": [{"file": "src/order.py", "symbol": "checkout", "kind": "func",
                      "startLine": 20, "endLine": 30}]},
    ], ctx)
    g = S.semantic_graph("/tmp/x", "proj-d")
    order = next(n for n in g["nodes"] if n["name"] == "订单实体")
    assert order["detail"]["fields"][0]["name"] == "id"
    flow = next(n for n in g["nodes"] if n["name"] == "下单流程")
    assert flow["detail"]["trigger"] == "create"
    assert len(flow["detail"]["steps"]) == 2
    long = S._graph_node_detail({
        "detail": {"steps": [{"order": i, "semantic": "s"} for i in range(60)],
                   "fields": [{"name": f"f{i}"} for i in range(80)]}})
    assert len(long["steps"]) == 40
    assert len(long["fields"]) == 60


def test_resolve_symbol_node_route_and_class_method():
    """宽容锚点解析: 路由字符串(file::GET:/path)与 Class::method → 真实 AST 节点。"""
    table = {
        "api_get_profile": {"id": "n1", "kind": "function", "name": "api_get_profile",
                            "qualified_name": "api_get_profile", "file_path": "app/routes/user.py",
                            "start_line": 49, "end_line": 70, "start_column": 0, "end_column": 0,
                            "signature": "", "docstring": "", "return_type": ""},
        "Database": {"id": "n2", "kind": "class", "name": "Database",
                     "qualified_name": "app.database.Database", "file_path": "app/database.py",
                     "start_line": 1, "end_line": 50, "start_column": 0, "end_column": 0,
                     "signature": "", "docstring": "", "return_type": ""},
        "execute": {"id": "n3", "kind": "method", "name": "execute",
                    "qualified_name": "Database.execute", "file_path": "app/database.py",
                    "start_line": 20, "end_line": 30, "start_column": 0, "end_column": 0,
                    "signature": "", "docstring": "", "return_type": ""},
    }
    idx = S._node_index(table)
    # 路由格式: startLine 指向装饰器行(@router.get), 应解析到其后函数
    node = S._resolve_symbol_node("GET:/profile", "app/routes/user.py", 48, table, idx)
    assert node and node["name"] == "api_get_profile"
    # Class::method 尾段
    node2 = S._resolve_symbol_node("Database::execute", "app/database.py", 0, table, idx)
    assert node2 and node2["name"] == "execute"
    # 尾段非唯一但文件命中
    node3 = S._resolve_symbol_node("app/database.py::Database", "app/database.py", 0, table, idx)
    assert node3 and node3["name"] == "Database"
    # 无符号也无文件 → None(不会误锚)
    assert S._resolve_symbol_node("no_such_symbol", "", 0, table, idx) is None
    # 符号与文件都不在表中 → None
    assert S._resolve_symbol_node("ghost", "app/other.py", 0, table, idx) is None


def test_norm_cache_symbol_roundtrip_snake_case():
    """KB 符号经 _norm_cache_symbol 落库后，读回再归一化保持行号/return_type(双路径兼容)。

    _collect_via_cache 把归一化后的 snake_case 节点写回 arch_ast_cache，读回再归一化一次，
    必须保留 start_line/end_line/return_type(否则行区间归属与 Rule 信号在 KB 路径失效)。
    """
    raw = {"name": "get_config", "kind": "function", "qualifiedName": "get_config",
           "startLine": 10, "endLine": 14, "signature": "(key, default='')",
           "docstring": "", "returnType": "str"}
    once = S._norm_cache_symbol("a.py", "python", raw)
    assert once["return_type"] == "str"
    assert once["start_line"] == 10 and once["end_line"] == 14
    # 落库形状(snake_case)再归一化 → 字段不丢失。
    twice = S._norm_cache_symbol("a.py", "python", once)
    assert twice["start_line"] == 10 and twice["end_line"] == 14
    assert twice["return_type"] == "str"
    assert twice["qualified_name"] == "get_config"
    assert twice["id"] == once["id"]
    # 兼容 camelCase returnType 与 snake_case return_type。
    assert S._norm_cache_symbol("a.py", "p", {"name": "x", "return_type": "int"})["return_type"] == "int"


def test_rebuild_edges_from_refs_calls_attribution():
    """refs 行区间归属到符号 → 调用边(source=符号id,target=目标符号id或名)。"""
    syms = [
        {"id": "cache:a.py::register::1", "kind": "function", "name": "register",
         "qualified_name": "register", "file_path": "a.py",
         "start_line": 1, "end_line": 20, "start_column": 0, "end_column": 0},
        {"id": "cache:a.py::_ip_limit::30", "kind": "function", "name": "_ip_limit",
         "qualified_name": "_ip_limit", "file_path": "a.py",
         "start_line": 30, "end_line": 35, "start_column": 0, "end_column": 0},
    ]
    refs = [
        {"name": "get_config", "kind": "calls", "line": 12, "col": 9},
        {"name": "get_threshold", "kind": "calls", "line": 32, "col": 5},
        {"name": "get_config", "kind": "calls", "line": 5, "col": 3},
        {"name": "Unknown", "kind": "type_of", "line": 15, "col": 1},
    ]
    edges = S._rebuild_edges_from_refs(syms, refs)
    calls = [e for e in edges if e["kind"] == "calls"]
    # 2 个独立配置调用：register 两次 get_config → 去重 1 条；_ip_limit 一次 get_threshold。
    assert sorted((e["source"], e["target"]) for e in calls) == [
        ("cache:a.py::_ip_limit::30", "get_threshold"),
        ("cache:a.py::register::1", "get_config"),
    ]
    assert all(e.get("line") for e in calls)
    # type_of 不属于统一边类型集。
    assert not any(e["kind"] == "type_of" for e in edges)


def test_rebuild_edges_contains_nesting():
    """contains 由行区间嵌套推导：类包含其方法，模块级函数不被误含。"""
    syms = [
        {"id": "cache:c.py::Config::1", "kind": "class", "name": "Config",
         "qualified_name": "Config", "file_path": "c.py",
         "start_line": 1, "end_line": 40, "start_column": 0, "end_column": 0},
        {"id": "cache:c.py::get_config::5", "kind": "method", "name": "get_config",
         "qualified_name": "Config.get_config", "file_path": "c.py",
         "start_line": 5, "end_line": 10, "start_column": 0, "end_column": 0},
        {"id": "cache:c.py::set_config::12", "kind": "method", "name": "set_config",
         "qualified_name": "Config.set_config", "file_path": "c.py",
         "start_line": 12, "end_line": 18, "start_column": 0, "end_column": 0},
        {"id": "cache:c.py::module_fn::50", "kind": "function", "name": "module_fn",
         "qualified_name": "module_fn", "file_path": "c.py",
         "start_line": 50, "end_line": 55, "start_column": 0, "end_column": 0},
    ]
    edges = S._rebuild_edges_from_refs(syms, [])
    contains = [(e["source"], e["target"]) for e in edges if e["kind"] == "contains"]
    assert ("cache:c.py::Config::1", "cache:c.py::get_config::5") in contains
    assert ("cache:c.py::Config::1", "cache:c.py::set_config::12") in contains
    assert not any(t == "cache:c.py::module_fn::50" for _, t in contains)


def test_collect_via_cache_kb_path_rebuilds_edges(tmp_path, monkeypatch):
    """无 codegraph 时 KB 兜底路径产出统一边(不再是空边列表)。"""
    _ctx(tmp_path, monkeypatch)
    root = str(tmp_path / "proj")
    os.makedirs(root)
    src = ("class Config:\n"
           "    def get_config(self, key, default=''):\n"
           "        return default\n"
           "def register_success(user):\n"
           "    cfg = Config()\n"
           "    return cfg.get_config('ttl', '10')\n")
    with open(os.path.join(root, "a.py"), "w", encoding="utf-8") as fh:
        fh.write(src)
    pid = S.project_id_for(root, None)
    kb_symbols = [
        {"name": "Config", "kind": "class", "qualifiedName": "Config",
         "startLine": 1, "endLine": 3, "signature": "", "docstring": "", "returnType": ""},
        {"name": "get_config", "kind": "method", "qualifiedName": "Config.get_config",
         "startLine": 2, "endLine": 3, "signature": "(key, default='')", "docstring": "", "returnType": "str"},
        {"name": "register_success", "kind": "function", "qualifiedName": "register_success",
         "startLine": 4, "endLine": 6, "signature": "(user)", "docstring": "", "returnType": ""},
    ]
    kb_refs = [
        {"name": "get_config", "kind": "calls", "line": 6, "col": 11},
        {"name": "Config", "kind": "instantiates", "line": 5, "col": 8},
    ]

    def _fake_kb(root, rel, impl=False):
        res = {"symbols": kb_symbols, "refs": kb_refs, "language": "python"}
        if impl:
            res["implDetails"] = {
                "statements": [{"type": "if", "condition": "a > 0",
                                "startLine": 4, "endLine": 5, "enclosing": "register_success"}],
                "routes": [], "constants": [
                    {"name": "TTL", "value": "10", "line": 6}],
            }
        return res

    _patch_all(monkeypatch, "_kb_parse_file", _fake_kb)
    nodes, edges, source, impl_by_file = S._collect_via_cache(root, None, ["a.py"], [])
    assert source == "kb"
    # impl details 随 KB 路径收集并回写缓存
    assert impl_by_file["a.py"]["statements"][0]["condition"] == "a > 0"
    row = store.AstCacheStore.get(pid, "a.py")
    assert row["statements"][0]["condition"] == "a > 0"
    assert row["constants"][0]["value"] == "10"
    assert {n["name"] for n in nodes} == {"Config", "get_config", "register_success"}
    assert nodes[0]["start_line"] >= 1  # 行号不丢失
    call_kinds = {e["kind"] for e in edges}
    assert "calls" in call_kinds and "instantiates" in call_kinds
    calls = [e for e in edges if e["kind"] == "calls"]
    # register_success 内 calls get_config(行区间归属到符号 id)。
    assert any(e["source"] == "cache:a.py::register_success::4" and e["target"] == "cache:a.py::get_config::2"
               for e in calls)
    # contains: Config 包含 get_config。
    contains = [e for e in edges if e["kind"] == "contains"]
    assert any(e["source"] == "cache:a.py::Config::1" and e["target"] == "cache:a.py::get_config::2"
               for e in contains)


def test_fields_from_source(tmp_path):
    """源码回读扫描实体字段：注解式 + self. 实例属性。"""
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "m.py").write_text(
        "class UpdateRequest:\n"
        "    email: str\n"
        "    code: str = ''\n"
        "    def __init__(self):\n"
        "        self.user_id = 0\n", encoding="utf-8")
    n = {"kind": "class", "name": "UpdateRequest", "file_path": "m.py",
         "start_line": 1, "end_line": 5}
    f = S._fields_from_source(str(proj), n)
    names = {x["name"] for x in f}
    assert {"email", "code", "user_id"} <= names
    email = next(x for x in f if x["name"] == "email")
    assert email["type"] == "str"
    # 文件缺失 → 空。
    assert S._fields_from_source(str(proj), {"kind": "class", "name": "X",
                                             "file_path": "missing.py", "start_line": 1}) == []


def test_inherit_ast_refs_from_aggregates(tmp_path, monkeypatch):
    """business 资产继承 aggregates 子资产的 astRefs(并集去重)。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-inh")
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    child = S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "process", "level": "logic", "name": "下单", "desc": "d",
         "astRefs": [
             {"file": "a.py", "symbol": "checkout", "kind": "func", "startLine": 1, "endLine": 5},
             {"file": "a.py", "symbol": "pay", "kind": "func", "startLine": 8, "endLine": 12},
         ]}], ctx)
    child_id = child[0]["id"]
    store.SemanticAssetsStore.create({
        "id": "sa-d-b-p-1", "projectId": pid, "kind": "process", "level": "business",
        "name": "下单支付", "desc": "d", "detail": {"aggregates": [{"assetId": child_id}]},
        "astRefs": [], "scopeType": "project", "scopeKey": "business", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    biz = [{"id": "sa-d-b-p-1", "kind": "process", "level": "business", "name": "下单支付",
            "desc": "d", "detail": {"aggregates": [{"assetId": child_id}]}, "astRefs": [],
            "scopeType": "project", "scopeKey": "business"}]
    S._inherit_ast_refs_from_aggregates(pid, biz)
    got = store.SemanticAssetsStore.get("sa-d-b-p-1")
    syms = {r["symbol"] for r in got["astRefs"]}
    assert syms == {"checkout", "pay"}


def test_business_derived_edges_from_inherited_astrefs(tmp_path, monkeypatch):
    """business 资产经继承 astRefs 后，派生边能覆盖 business 层(无自环)。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-bizedge")
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    l1 = S._save_assets(pid, "comm", "c1", [
        {"kind": "process", "level": "logic", "name": "鉴权", "desc": "d",
         "astRefs": [{"file": "a.py", "symbol": "auth", "kind": "func", "startLine": 1, "endLine": 5}]}], ctx)
    l2 = S._save_assets(pid, "comm", "c2", [
        {"kind": "process", "level": "logic", "name": "下单", "desc": "d",
         "astRefs": [{"file": "b.py", "symbol": "order", "kind": "func", "startLine": 1, "endLine": 5}]}], ctx)
    b1 = [{"id": "sa-d-b-p-1", "kind": "process", "level": "business", "name": "认证域", "desc": "d",
           "detail": {"aggregates": [{"assetId": l1[0]["id"]}]}, "astRefs": [], "scopeType": "project",
           "scopeKey": "business"}]
    b2 = [{"id": "sa-d-b-p-2", "kind": "process", "level": "business", "name": "交易域", "desc": "d",
           "detail": {"aggregates": [{"assetId": l2[0]["id"]}]}, "astRefs": [], "scopeType": "project",
           "scopeKey": "business"}]
    for b in b1 + b2:
        store.SemanticAssetsStore.create({**b, "projectId": pid, "srcHash": "h",
                                          "change": "added", "status": "active",
                                          "createdAt": 1, "updatedAt": 1})
    S._inherit_ast_refs_from_aggregates(pid, b1 + b2)
    # mock 派生边：auth 与 order 存在 codegraph calls 边 → 两个 business 资产应相连。
    def fake_derive(root, project, assets):
        node_to_assets = {}
        sym_to_node = {"auth": "n-auth", "order": "n-order"}
        for a in assets:
            for r in (a.get("astRefs") or []):
                nid = sym_to_node.get(r.get("symbol"))
                if nid:
                    node_to_assets.setdefault(nid, set()).add(a.get("id"))
        out = []
        for s, t, k in (("n-auth", "n-order", "calls"),):
            for a in node_to_assets.get(s, ()):
                for b in node_to_assets.get(t, ()):
                    if a != b:
                        out.append({"from": a, "to": b, "type": k})
        return out

    _patch_all(monkeypatch, "_derive_project_edges", fake_derive)
    edges = S._cached_derived_edges("/tmp/x", "proj-bizedge",
                                    store.SemanticAssetsStore.all_status(pid, limit=100))
    pairs = {(e["from"], e["to"]) for e in edges}
    assert ("sa-d-b-p-1", "sa-d-b-p-2") in pairs  # business↔business 有边
    assert not any(e["from"] == e["to"] for e in edges)  # 无自环


def test_semantic_graph_focus_one_hop_default(tmp_path, monkeypatch):
    """focus 参数：默认 1 跳，仅返回焦点资产及其直接邻居；无 focus 返回全部。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-focus")
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "entity", "level": "logic", "name": "订单", "desc": "d", "detail": {}},
        {"kind": "entity", "level": "logic", "name": "用户", "desc": "d", "detail": {}},
        {"kind": "entity", "level": "logic", "name": "账户", "desc": "d", "detail": {}},
    ], ctx)
    # 构造链：订单 → 用户 → 账户(订单关联用户、用户关联账户)。
    rows = store.SemanticAssetsStore.search(pid, text="")
    ids = {r["name"]: r["id"] for r in rows}
    for name, rel in (("订单", "用户"), ("用户", "账户")):
        a = store.SemanticAssetsStore.get(ids[name])
        d = a.get("detail") or {}
        d["relations"] = [{"target": rel, "type": "references"}]
        store.SemanticAssetsStore.update(ids[name], {"detail": d})

    g_all = S.semantic_graph("/tmp/x", "proj-focus")
    assert g_all["count"] == 3

    # 1 跳(默认)：订单只带直接邻居 用户。
    g1 = S.semantic_graph("/tmp/x", "proj-focus", focus=ids["订单"])
    assert {n["name"] for n in g1["nodes"]} == {"订单", "用户"}
    # 2 跳：订单 → 用户 → 账户。
    g2 = S.semantic_graph("/tmp/x", "proj-focus", focus=ids["订单"], hops=2)
    assert {n["name"] for n in g2["nodes"]} == {"订单", "用户", "账户"}
    # 边的两端必须都在子图内。
    assert all(e["from"] in {n["id"] for n in g1["nodes"]}
               and e["to"] in {n["id"] for n in g1["nodes"]} for e in g1["edges"])


def test_semantic_graph_focus_unknown_id_returns_all(tmp_path, monkeypatch):
    """focus 指向不存在的资产时回退为返回全部(不误伤图谱)。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-focus-unknown")
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "entity", "level": "logic", "name": "订单", "desc": "d", "detail": {}},
    ], ctx)
    g = S.semantic_graph("/tmp/x", "proj-focus-unknown", focus="sa-x-0")
    assert g["count"] == 1


def test_primary_kind_allocation_no_cross_kind_dup(tmp_path, monkeypatch):
    """实现层单趟主类别分配：每个符号只产一个资产(消除跨类别重复)。

    一个函数(非路由/api 边界、非配置载体)只产 process；配置载体产 rule；
    类产 entity；路由节点产 contract(处理函数归 process，不重复产契约)。
    """
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "m.py").write_text(
        "class Order:\n    pass\n"
        "def helper(o):\n    pass\n"
        "def get_config(key, default):\n    return default\n",
        encoding="utf-8")
    _patch_all(monkeypatch, "_kb_parse_file", lambda *a, **k: None)
    res = S.extract_scope(str(proj), None, scope_type="files", scope_key="m",
                          files=["m.py"], kinds=None, use_llm=False,
                          level="implementation")
    by_name: Dict[str, str] = {}
    for a in res["assets"]:
        syms = tuple(sorted(r["symbol"] for r in a["astRefs"]))
        by_name.setdefault(a["name"], a["kind"])
    # 类 → entity；普通函数 → process；配置读写 → rule。无跨类别重复。
    assert by_name.get("Order") == "entity"
    assert by_name.get("helper") == "process"
    assert by_name.get("get_config") == "rule"
    # 每个符号至多一个资产(实现层无 contract/process/decision 并存)。
    kinds_for = {}
    for a in res["assets"]:
        for r in a["astRefs"]:
            kinds_for.setdefault(r["symbol"], set()).add(a["kind"])
    assert all(len(v) == 1 for v in kinds_for.values())


def test_primary_kind_route_contract_and_handler_process(tmp_path, monkeypatch):
    """路由节点产 contract，其处理函数产 process(不重复产契约)。"""
    _ctx(tmp_path, monkeypatch)
    nodes = [
        {"id": "r1", "kind": "route", "name": "GET /profile", "qualified_name": "u.py::GET:/profile",
         "file_path": "u.py", "start_line": 1, "end_line": 1,
         "signature": "", "docstring": "", "return_type": ""},
        {"id": "f1", "kind": "function", "name": "api_get_profile", "qualified_name": "api_get_profile",
         "file_path": "u.py", "start_line": 3, "end_line": 8,
         "signature": "(request: Request)", "docstring": "", "return_type": ""},
    ]
    edges = [{"source": "r1", "target": "f1", "kind": "references"}]
    ctx = {"nodes": nodes, "edges": edges, "root": str(tmp_path)}
    got = S._heuristic_extract_primary(ctx, list(S.SEMANTIC_KINDS))
    kinds = {a["name"]: a["kind"] for a in got}
    assert kinds.get("GET /profile") == "contract"   # 路由节点 → 契约
    assert kinds.get("api_get_profile") == "process"  # 处理函数 → 过程(不重复产契约)


def test_impl_asset_phantom_and_anchor_kind_rejected(tmp_path, monkeypatch):
    """实现层幻影(0 锚点)与锚点类别不符(entity 锚到函数)资产被 _save_assets 丢弃。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-phantom")
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    # 0 锚点实现层资产 → 丢弃；有真实 class 锚点的 entity → 保留。
    saved = S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "process", "level": "implementation", "name": "幻影流程", "desc": "d",
         "detail": {}, "astRefs": []},
        {"kind": "entity", "level": "implementation", "name": "Order", "desc": "d",
         "detail": {}, "astRefs": [{"file": "o.py", "symbol": "Order", "kind": "class",
                                    "startLine": 1, "endLine": 5}]},
    ], ctx)
    assert {a["name"] for a in saved} == {"Order"}
    # entity 锚到函数(类别不符) → 丢弃
    saved2 = S._save_assets(pid, "comm", "L0-0002", [
        {"kind": "entity", "level": "implementation", "name": "伪实体", "desc": "d",
         "detail": {}, "astRefs": [{"file": "o.py", "symbol": "checkout", "kind": "func",
                                    "startLine": 10, "endLine": 15}]},
    ], ctx)
    assert saved2 == []


# ── P0: 调用链行序恢复(边 line/col 透传) ──────────────────────

def test_query_edges_includes_line_col(tmp_path, monkeypatch):
    """codegraph 路径 _query_edges 透传 line/col(调用顺序数据源)。"""
    _ctx(tmp_path, monkeypatch)
    cg = sqlite3.connect(":memory:")
    cg.row_factory = sqlite3.Row  # 与 _open_cg 一致
    cg.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, name TEXT, "
               "qualified_name TEXT, file_path TEXT, start_line INTEGER, end_line INTEGER, "
               "start_column INTEGER, end_column INTEGER, signature TEXT, docstring TEXT, "
               "return_type TEXT)")
    cg.execute("CREATE TABLE edges (source TEXT, target TEXT, kind TEXT, "
               "line INTEGER, col INTEGER)")
    cg.execute("INSERT INTO nodes VALUES ('fn1','function','checkout','checkout','a.py',10,20,0,0,'','','')")
    cg.execute("INSERT INTO nodes VALUES ('fn2','function','validate','validate','b.py',1,5,0,0,'','','')")
    cg.execute("INSERT INTO nodes VALUES ('fn3','function','save','save','c.py',1,5,0,0,'','','')")
    cg.execute("INSERT INTO edges VALUES ('fn1','fn3','calls',18,4)")
    cg.execute("INSERT INTO edges VALUES ('fn1','fn2','calls',12,4)")
    cg.commit()
    rows = S._query_edges(cg, ["fn1"])
    assert len(rows) == 2
    by_target = {r["target"]: r for r in rows}
    assert by_target["fn2"]["line"] == 12 and by_target["fn2"]["col"] == 4
    assert by_target["fn3"]["line"] == 18


def test_callee_names_sorted_by_line(tmp_path, monkeypatch):
    """_callee_names 按边 line 升序返回(无 line 边排末尾，保持相对序)。"""
    _ctx(tmp_path, monkeypatch)
    edges = [
        {"source": "fn1", "target": "t_late", "kind": "calls", "line": 30},
        {"source": "fn1", "target": "t_noline", "kind": "calls"},
        {"source": "fn1", "target": "t_early", "kind": "calls", "line": 12},
        {"source": "fn1", "target": "t_mid", "kind": "calls", "line": 20},
        {"source": "fn2", "target": "other", "kind": "calls", "line": 1},
        {"source": "fn1", "target": "notcall", "kind": "references", "line": 2},
    ]
    out = S._callee_names("fn1", edges, None)
    assert out == ["t_early", "t_mid", "t_late", "t_noline"]


def test_ordered_call_lines_block(tmp_path, monkeypatch):
    """_ordered_call_lines 产出按函数分组的行序调用序列；无 line 边时为空。"""
    _ctx(tmp_path, monkeypatch)
    nodes = [{"id": "fn1", "kind": "function", "name": "checkout",
              "qualified_name": "checkout", "file_path": "a.py",
              "start_line": 10, "end_line": 25}]
    table = S.build_symbol_table(nodes)
    edges = [
        {"source": "fn1", "target": "save", "kind": "calls", "line": 18},
        {"source": "fn1", "target": "validate", "kind": "calls", "line": 12},
        {"source": "fn1", "target": "charge", "kind": "calls", "line": 22},
        {"source": "fn1", "target": "validate", "kind": "calls", "line": 24},  # 重复目标去重
    ]
    out = S._ordered_call_lines(nodes, edges, table)
    assert out == "- checkout: L12 validate → L18 save → L22 charge"
    # 无 line 信息 → 空(调用方回退普通边清单)
    edges_noline = [{"source": "fn1", "target": "save", "kind": "calls"}]
    assert S._ordered_call_lines(nodes, edges_noline, table) == ""


def test_heuristic_process_steps_ordered_by_line(tmp_path, monkeypatch):
    """实现层启发式 process.steps 按调用行序编号(order=1..n)。"""
    _ctx(tmp_path, monkeypatch)
    nodes = [
        {"id": "fn1", "kind": "function", "name": "checkout", "qualified_name": "checkout",
         "file_path": "a.py", "start_line": 10, "end_line": 25, "signature": "(order)",
         "docstring": "", "return_type": ""},
    ]
    edges = [
        {"source": "fn1", "target": "save", "kind": "calls", "line": 18},
        {"source": "fn1", "target": "validate", "kind": "calls", "line": 12},
        {"source": "fn1", "target": "charge", "kind": "calls", "line": 22},
    ]
    ctx = {"nodes": nodes, "edges": edges, "root": str(tmp_path)}
    got = S._heuristic_extract_primary(ctx, ["process"])
    assert len(got) == 1
    steps = got[0]["detail"]["steps"]
    assert [s["order"] for s in steps] == [1, 2, 3]
    assert [s["symbols"][0] for s in steps] == ["validate", "save", "charge"]


# ── implDetails(KB 实现细节)消费 ─────────────────────────────────


def _impl_fixture():
    return {
        "a.py": {
            "statements": [
                {"type": "if", "condition": "user.age >= 18", "startLine": 8,
                 "endLine": 10, "enclosing": "register"},
                {"type": "loop", "condition": "item in items", "startLine": 14,
                 "endLine": 15, "enclosing": "batch"},
                {"type": "if", "condition": "x == 1", "startLine": 20,
                 "endLine": 21, "enclosing": "check_age"},
            ],
            "routes": [
                {"path": "/register", "methods": ["POST"], "handler": "register",
                 "framework": "fastapi", "line": 5},
            ],
            "constants": [
                {"name": "MAX_AGE", "value": "150", "line": 2},
            ],
        },
    }


def _impl_node(nid, name, kind="function", file_path="a.py", sig="()", doc=""):
    return {"id": nid, "kind": kind, "name": name, "qualified_name": name,
            "file_path": file_path, "start_line": 1, "end_line": 9,
            "start_column": 0, "end_column": 0,
            "signature": sig, "docstring": doc, "return_type": ""}


def test_impl_block_text():
    """impl 块: 路由清单/常量值/控制流语句清单 三段结构化文本。"""
    block = S._impl_block(_impl_fixture())
    assert "API 路由清单" in block
    assert "- [POST] /register -> register (a.py:5, fastapi)" in block
    assert "常量值清单" in block
    assert "- MAX_AGE = 150 (a.py:2)" in block
    assert "控制流语句清单" in block
    assert "- register:8 [if] user.age >= 18" in block
    assert S._impl_block({}) == ""


def test_heuristic_primary_uses_impl_details(tmp_path, monkeypatch):
    """实现层主路径: decision 分支取语句条件原文、contract 取路由 path/methods、
    process 带前置条件、路由 handler 函数在无 route 节点时判契约。"""
    _ctx(tmp_path, monkeypatch)
    nodes = [
        _impl_node("n1", "register"),
        _impl_node("n2", "check_age", doc="if x else y"),
        _impl_node("n3", "batch"),
        _impl_node("n4", "Config", kind="class"),
    ]
    ctx = {"nodes": nodes, "edges": [], "root": "", "implDetails": _impl_fixture()}
    got = S._heuristic_extract_primary(
        ctx, ["process", "decision", "contract", "rule", "entity", "state"])
    by_name = {a["name"]: a for a in got}
    # register 是路由 handler(无 route 节点) → contract，relations 含真实端点
    reg = by_name["register"]
    assert reg["kind"] == "contract"
    rels = reg["detail"]["relations"]
    assert rels[0]["target"] == "/register" and rels[0]["methods"] == ["POST"]
    assert "/register" in reg["desc"]
    # check_age 分支密集 → decision，branches.condition 为语句清单原文
    chk = by_name["check_age"]
    assert chk["kind"] == "decision"
    assert chk["detail"]["branches"][0]["condition"] == "x == 1"
    assert chk["detail"]["branches"][0]["line"] == 20
    # batch → process，conditions 含循环条件原文
    b = by_name["batch"]
    assert b["kind"] == "process"
    assert "item in items" in b["detail"]["conditions"]
    # Config 类 → entity(rule 信号优先: Config 是配置载体)
    assert by_name["Config"]["kind"] == "rule"


def test_primary_kind_route_node_suppresses_impl_handler():
    """scope 已有 route 节点时，impl handler 判定不介入(边逻辑已覆盖)。"""
    route = _impl_node("r1", "/x", kind="route", file_path="a.py")
    handler = _impl_node("n1", "register")
    edges = [{"source": "r1", "target": "n1", "kind": "references"}]
    # 有 route 节点(调用方传 impl=None) → register 非契约边界(api_ 前缀?否) → process
    assert S._primary_kind_for_node(handler, edges, None, {"r1": route}, None) == "process"
    # 无 route 节点 + impl 路由元数据 → 契约
    assert S._primary_kind_for_node(handler, edges, None, {"r1": route},
                                    _impl_fixture()) == "contract"


def test_fetch_impl_for_file_kb_and_cache(tmp_path, monkeypatch):
    """impl 取数: 缓存未命中走 KB(implDetails)回写缓存; 命中不再调 KB; 旧后端降级 None。"""
    _ctx(tmp_path, monkeypatch)
    root = str(tmp_path / "proj")
    os.makedirs(root)
    with open(os.path.join(root, "b.py"), "w", encoding="utf-8") as fh:
        fh.write("X = 1\n")
    calls = []

    def _fake_kb(root_, rel, impl=False):
        calls.append(rel)
        return {"symbols": [], "refs": [], "language": "python",
                "implDetails": {"statements": [],
                                "routes": [{"path": "/x", "methods": ["GET"],
                                            "handler": "h", "framework": "fastapi", "line": 1}],
                                "constants": []}}

    _patch_all(monkeypatch, "_kb_parse_file", _fake_kb)
    impl = S._fetch_impl_for_file(root, None, "b.py")
    assert impl["routes"][0]["path"] == "/x"
    assert calls == ["b.py"]
    # 缓存命中 → 不再调 KB
    assert S._fetch_impl_for_file(root, None, "b.py")["routes"][0]["path"] == "/x"
    assert calls == ["b.py"]
    # 旧 KB 后端(无 implDetails) → None(降级)
    _patch_all(monkeypatch, "_kb_parse_file",
                        lambda root_, rel, impl=False:
                        {"symbols": [], "refs": [], "language": "python"})
    with open(os.path.join(root, "b.py"), "a", encoding="utf-8") as fh:
        fh.write("Y = 2\n")
    assert S._fetch_impl_for_file(root, None, "b.py") is None


def test_collect_context_cache_path_impl_block(tmp_path, monkeypatch):
    """collect_context 无 codegraph 路径: ctx.text 含 impl 块, ctx.implDetails 可消费。"""
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "m.py").write_text(
        "def f(a):\n    if a > 0:\n        x()\n    return 0\n", encoding="utf-8")

    def _fake_kb(root_, rel, impl=False):
        return {"symbols": [{"name": "f", "kind": "function", "qualifiedName": "f",
                             "startLine": 1, "endLine": 4, "signature": "(a)",
                             "docstring": "", "returnType": "int"}],
                "refs": [], "imports": [], "language": "python",
                "implDetails": {
                    "statements": [{"type": "if", "condition": "a > 0",
                                    "startLine": 2, "endLine": 3, "enclosing": "f"}],
                    "routes": [], "constants": []}}

    _patch_all(monkeypatch, "_kb_parse_file", _fake_kb)
    ctx = S.collect_context(str(proj), "files", "m.py", files=["m.py"])
    assert ctx["implDetails"]["m.py"]["statements"][0]["condition"] == "a > 0"
    assert "控制流语句清单" in ctx["text"]
    assert "- f:2 [if] a > 0" in ctx["text"]


def test_migration_keeps_rule_as_first_class_kind(tmp_path, monkeypatch):
    """回归: kind/level 规范化迁移不得把 rule(新六类一级类别)并入 decision/logic。

    历史 bug: 0814 迁移含 ("rule","decision")，0815 rule 升为一级类别后，
    每次进程启动重跑迁移会把新管线提取的 rule/implementation 资产改写成
    decision/logic(id/canonical_key 仍为 rule 前缀，造成 id 与列值矛盾)。
    """
    db = _ctx(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import db_schema
    now = 1
    store.SemanticAssetsStore.create({
        "id": "sa-s-i-r-1", "projectId": "proj-1", "kind": "rule",
        "level": "implementation", "name": "阈值配置", "desc": "d", "detail": {},
        "astRefs": [{"file": "m.py", "symbol": "cfg", "kind": "func",
                     "startLine": 1, "endLine": 2}],
        "scopeType": "files", "scopeKey": "m.py", "source": "codegraph",
        "srcHash": "h1", "canonicalKey": "k1",
        "change": "added", "status": "active",
        "createdAt": now, "updatedAt": now,
    })
    # 模拟第二次进程启动(幂等迁移重跑) — 统一布局下语义表迁移作用于项目库
    pdb = C.project_db("proj-1")
    db_schema.init_architect_project_db(pdb)
    got = store.SemanticAssetsStore.get("sa-s-i-r-1")
    assert got["kind"] == "rule"
    assert got["level"] == "implementation"
    # 遗留类别仍被规范化(迁移其余项保持生效)
    store.SemanticAssetsStore.create({
        "id": "sa-s-l-e-9", "projectId": "proj-1", "kind": "data_structure",
        "level": "medium", "name": "遗留", "desc": "", "detail": {},
        "astRefs": [], "scopeType": "project", "scopeKey": "_",
        "source": "live", "srcHash": "", "change": "added", "status": "active",
        "createdAt": now, "updatedAt": now,
    })
    db_schema.init_architect_project_db(pdb)
    legacy = store.SemanticAssetsStore.get("sa-s-l-e-9")
    assert legacy["kind"] == "entity"
    assert legacy["level"] == "logic"


# ── AI 逐行解读(关键行启发式 + 术语/规约注入 + 缓存/降级) ──────────

_LN_SRC = [
    "class Order:",
    "    def total(self, items):",
    "        # 汇总金额",
    "        amount = 0",
    "        for it in items:",
    "            amount += it.price",
    "        return amount",
]


def _ln_source(root, rel="src/order.py"):
    p = os.path.join(str(root), rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(_LN_SRC) + "\n")
    return rel


def _ln_asset(pid, asset_id, rel, line_notes=""):
    store.SemanticAssetsStore.create({
        "id": asset_id, "projectId": pid, "kind": "entity",
        "level": "implementation", "name": "订单", "desc": "订单金额汇总",
        "detail": {"fields": [{"name": "amount"}]},
        "astRefs": [{"file": rel, "symbol": "Order", "kind": "class",
                     "startLine": 1, "endLine": 7}],
        "status": "active", "needsUpdate": 0, "lineNotes": line_notes,
    })


def test_key_lines_heuristic(tmp_path, monkeypatch):
    _assets(tmp_path, monkeypatch)
    # 声明/赋值/控制流/调用行皆入选；仅注释等噪声行跳过
    out = S._key_lines(_LN_SRC, 1)
    assert out == [1, 2, 4, 5, 6, 7]


def test_key_lines_type_declarations(tmp_path, monkeypatch):
    """类型/接口声明窗(无控制流无调用)也能入选；纯导入窗回退解释非空行。"""
    _assets(tmp_path, monkeypatch)
    codes = [
        "import raw from '../../../schema/capabilities.json';",
        "import type { DiagramType } from './types';",
        "",
        "export type TypeSupport = 'native' | 'emulated' | 'unsupported';",
        "",
        "export interface AnimationCapability {",
        "  sequencePlayback: boolean;",
        "  nodeHighlight: boolean;",
        "}",
    ]
    assert S._key_lines(codes, 1) == [4, 6, 7, 8]
    assert S._key_lines(codes[:2], 1) == [1, 2]


def test_generate_line_notes_llm_context_and_persist(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    _ln_asset(pid, "sa-ln-1", rel)
    store.GlossaryStore.create(pid, term="订单", definition="购买行为的数据载体")
    store.NamingConventionStore.create(pid, "实体类以业务名词命名", scenarios=["naming"])
    captured = {}

    def fake_llm(msgs, **kw):
        import json as _j
        captured["msgs"] = msgs
        return {"content": _j.dumps({"notes": [
            {"line": 2, "note": "定义订单金额汇总方法"},
            {"line": 99, "note": "越界行应被丢弃"},
        ]}, ensure_ascii=False)}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_llm)
    res = S.generate_line_notes("sa-ln-1", rel, 1, 6, root=str(root))
    assert res["degraded"] is False and res["cached"] is False
    assert res["notes"] == {2: "定义订单金额汇总方法"}
    user = captured["msgs"][1]["content"]
    assert "订单" in user and "购买行为的数据载体" in user
    assert "实体类以业务名词命名" in user
    # skill(linenote 场景) + 工具文档注入 system prompt
    assert "代码逐行解读规约" in captured["msgs"][0]["content"]
    assert "code.read_symbols" in captured["msgs"][0]["content"]
    # 成功后落库(缓存字段)
    row = store.SemanticAssetsStore.get("sa-ln-1")
    assert "订单金额汇总方法" in (row.get("lineNotes") or "")


def test_generate_line_notes_cache_hit(tmp_path, monkeypatch):
    import hashlib
    import json as _j
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    win = "\n".join(_LN_SRC[0:6])
    h = hashlib.md5(win.encode("utf-8")).hexdigest()
    _ln_asset(pid, "sa-ln-2", rel, line_notes=_j.dumps(
        {"file": rel, "start": 1, "end": 6, "hash": h,
         "notes": {"2": "缓存注解"}}, ensure_ascii=False))

    def boom(*a, **k):
        raise AssertionError("缓存命中时不应调用 LLM")

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", boom)
    res = S.generate_line_notes("sa-ln-2", rel, 1, 6, root=str(root))
    assert res["cached"] is True and res["notes"] == {2: "缓存注解"}


def test_generate_line_notes_llm_fail_degraded(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    _ln_asset(pid, "sa-ln-3", rel)

    def fail(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fail)
    res = S.generate_line_notes("sa-ln-3", rel, 1, 6, root=str(root))
    assert res["degraded"] is True and res["notes"] == {}
    # 失败不落库(可重试)
    row = store.SemanticAssetsStore.get("sa-ln-3")
    assert not (row.get("lineNotes") or "")


def test_is_ctx_overflow_marks():
    """上下文超限错误识别：各厂商措辞命中；限流/空文本不误判。"""
    assert S._is_ctx_overflow("Error: This model's maximum context length is 8192 tokens")
    assert S._is_ctx_overflow("prompt is too long: 200000 tokens > 8192 maximum")
    assert S._is_ctx_overflow("输入 tokens 超出上下文长度限制")
    assert not S._is_ctx_overflow("rate limit exceeded, retry after 5s")
    assert not S._is_ctx_overflow("")


def _ln_overflow_llm(seen, note_batches):
    """构造「第 1 次整窗超限、后续批各自返回注解」的假 llm_sync。"""
    import json as _j

    def fake(msgs, **kw):
        seen.append(list(msgs))
        if len(seen) == 1:
            if kw.get("on_error"):
                kw["on_error"]("This model's maximum context length is 8192 tokens")
            return None
        idx = min(len(seen), len(note_batches) + 1) - 2
        return {"content": _j.dumps({"notes": note_batches[idx]}, ensure_ascii=False)}
    return fake


def test_generate_line_notes_ctx_overflow_halving(tmp_path, monkeypatch):
    """整窗超限 → 1/2 分批重试：两批注解合并、视为成功并落库。"""
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    _ln_asset(pid, "sa-ln-7", rel)
    seen = []
    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync",
                        _ln_overflow_llm(seen, [
                            [{"line": 2, "note": "批一注解"}],
                            [{"line": 5, "note": "批二注解"}],
                        ]))
    res = S.generate_line_notes("sa-ln-7", rel, 1, 6, root=str(root))
    assert res["degraded"] is False and res["cached"] is False
    assert res["notes"] == {2: "批一注解", 5: "批二注解"}
    assert len(seen) == 3   # 1 次整窗 + 2 次半窗
    row = store.SemanticAssetsStore.get("sa-ln-7")
    assert "批一注解" in (row.get("lineNotes") or "")


def test_generate_line_notes_ctx_overflow_depth_exhausted(tmp_path, monkeypatch):
    """持续超限 → 1/2→1/4→1/8 封底后放弃：degraded、不落库(可重试)。"""
    import json as _j
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    _ln_asset(pid, "sa-ln-8", rel)
    calls = []

    def always_overflow(msgs, **kw):
        calls.append(1)
        if kw.get("on_error"):
            kw["on_error"]("prompt is too long: 200000 tokens > 8192 maximum")
        return None

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", always_overflow)
    res = S.generate_line_notes("sa-ln-8", rel, 1, 6, root=str(root))
    assert res["degraded"] is True and res["notes"] == {}
    assert "解读失败" in (res.get("error") or "")
    assert len(calls) == 11   # 1(整窗) + 2(1/2) + 4(1/4) + 4(1/8 叶子)；单行子段封底不再二分
    row = store.SemanticAssetsStore.get("sa-ln-8")
    assert not (row.get("lineNotes") or "")


def test_line_notes_endpoint_cached(tmp_path, monkeypatch):
    import hashlib
    import json as _j
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    win = "\n".join(_LN_SRC[0:6])
    h = hashlib.md5(win.encode("utf-8")).hexdigest()
    _ln_asset(pid, "sa-ln-4", rel, line_notes=_j.dumps(
        {"file": rel, "start": 1, "end": 6, "hash": h,
         "notes": {"6": "返回汇总金额"}}, ensure_ascii=False))
    out = _run_coro(S.api_line_notes("sa-ln-4", rel, 1, 6,
                                     root=str(root), project=None, model_id=None))
    assert out["code"] == 0
    assert out["data"]["cached"] is True
    assert out["data"]["notes"] == {6: "返回汇总金额"}


def test_generate_line_notes_tool_round_whitelist(tmp_path, monkeypatch):
    """多轮工具调用：白名单工具真执行回喂，白名单外拒绝；最终 JSON 正常解析。"""
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    _ln_asset(pid, "sa-ln-5", rel)
    seen = []

    def fake_llm(msgs, **kw):
        import json as _j
        seen.append(list(msgs))
        if len(seen) == 1:
            tc = ('[TOOL_CALL]{"tool":"asset.semantic.extract","arguments":{"scope":{"type":"project"}}}[/TOOL_CALL]\n'
                  '[TOOL_CALL]{"tool":"code.read_symbols","arguments":{"file":"%s","startLine":1,"endLine":3}}[/TOOL_CALL]' % rel)
            return {"content": tc}
        return {"content": _j.dumps({"notes": [{"line": 5, "note": "for 循环汇总"}]}, ensure_ascii=False)}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_llm)
    res = S.generate_line_notes("sa-ln-5", rel, 1, 6, root=str(root))
    assert res["degraded"] is False
    assert res["notes"] == {5: "for 循环汇总"}
    assert len(seen) == 2
    feed = seen[1][-1]["content"]
    assert "不在本任务允许列表" in feed   # extract 被白名单拒绝
    assert "class Order" in feed          # read_symbols 真执行且源码回喂


def test_generate_line_notes_resolves_project_root(tmp_path, monkeypatch):
    """只传 project id(URL 无 root) → 按注册项目 rootPath 解析，可读源码。"""
    import json as _j
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    store.ProjectsStore.create({"id": "proj-ln", "name": "t", "rootPath": str(root)})
    pid = S.project_id_for(None, "proj-ln")
    _ln_asset(pid, "sa-ln-6", rel)

    def fake_llm(msgs, **kw):
        return {"content": _j.dumps({"notes": [{"line": 5, "note": "for 循环汇总"}]},
                                    ensure_ascii=False)}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_llm)
    res = S.generate_line_notes("sa-ln-6", rel, 1, 6, root=None, project="proj-ln")
    assert res["degraded"] is False
    assert res["notes"] == {5: "for 循环汇总"}


def test_generate_line_notes_multi_window_cache(tmp_path, monkeypatch):
    """同资产多窗口缓存互不覆盖：窗口A/B 各自生成一次，重复请求均命中不再调 LLM。"""
    import json as _j
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    _ln_asset(pid, "sa-ln-7", rel)
    calls = {"n": 0}

    def fake_llm(msgs, **kw):
        calls["n"] += 1
        user = msgs[-1]["content"]
        if "5. " in user:   # 窗口 1-6：关键行 [2,5]
            notes = [{"line": 5, "note": "窗口W1注解"}]
        else:               # 窗口 1-3：关键行 [2]
            notes = [{"line": 2, "note": "窗口W2注解"}]
        return {"content": _j.dumps({"notes": notes}, ensure_ascii=False)}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_llm)
    r1 = S.generate_line_notes("sa-ln-7", rel, 1, 6, root=str(root))
    r2 = S.generate_line_notes("sa-ln-7", rel, 1, 3, root=str(root))
    assert calls["n"] == 2
    assert r1["notes"] == {5: "窗口W1注解"} and r2["notes"] == {2: "窗口W2注解"}
    # 重复请求两个窗口均命中缓存，LLM 不再被调用
    r3 = S.generate_line_notes("sa-ln-7", rel, 1, 6, root=str(root))
    r4 = S.generate_line_notes("sa-ln-7", rel, 1, 3, root=str(root))
    assert calls["n"] == 2
    assert r3["cached"] is True and r3["notes"] == {5: "窗口W1注解"}
    assert r4["cached"] is True and r4["notes"] == {2: "窗口W2注解"}


def test_generate_line_notes_full_and_segment_share_cache(tmp_path, monkeypatch):
    """确认：完整代码窗口(1..N 全文)与代码锚点片段窗口共存于同一缓存池，互不覆盖、各自命中。"""
    import json as _j
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)   # 7 行
    pid = S.project_id_for(str(root), None)
    _ln_asset(pid, "sa-ln-8", rel)
    calls = {"n": 0}

    def fake_llm(msgs, **kw):
        calls["n"] += 1
        user = msgs[-1]["content"]
        if "7. " in user:   # 全文窗口 1-7：关键行含 7
            notes = [{"line": 7, "note": "全文注解"}]
        else:               # 分段窗口 3-6：关键行 [4,5,6]
            notes = [{"line": 5, "note": "分段注解"}]
        return {"content": _j.dumps({"notes": notes}, ensure_ascii=False)}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_llm)
    full = S.generate_line_notes("sa-ln-8", rel, 1, 7, root=str(root))
    seg = S.generate_line_notes("sa-ln-8", rel, 3, 6, root=str(root))
    assert calls["n"] == 2
    assert full["notes"] == {7: "全文注解"} and seg["notes"] == {5: "分段注解"}
    # 各自重复请求 → 均命中缓存，LLM 零调用
    f2 = S.generate_line_notes("sa-ln-8", rel, 1, 7, root=str(root))
    s2 = S.generate_line_notes("sa-ln-8", rel, 3, 6, root=str(root))
    assert calls["n"] == 2
    assert f2["cached"] is True and f2["notes"] == {7: "全文注解"}
    assert s2["cached"] is True and s2["notes"] == {5: "分段注解"}


def test_generate_line_notes_force_regenerates(tmp_path, monkeypatch):
    """force=True：命中缓存也视同无缓存，重新调用 LLM 并覆盖原窗口条目。"""
    import hashlib
    import json as _j
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    win = "\n".join(_LN_SRC[0:6])
    h = hashlib.md5(win.encode("utf-8")).hexdigest()
    _ln_asset(pid, "sa-ln-9", rel, line_notes=_j.dumps(
        {"file": rel, "start": 1, "end": 6, "hash": h,
         "notes": {"2": "旧缓存注解"}}, ensure_ascii=False))
    calls = {"n": 0}

    def fake_llm(msgs, **kw):
        calls["n"] += 1
        return {"content": _j.dumps({"notes": [{"line": 5, "note": "新注解"}]}, ensure_ascii=False)}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_llm)
    # 不带 force → 命中旧缓存
    r1 = S.generate_line_notes("sa-ln-9", rel, 1, 6, root=str(root))
    assert r1["cached"] is True and r1["notes"] == {2: "旧缓存注解"} and calls["n"] == 0
    # force=True → 重新生成并覆盖
    r2 = S.generate_line_notes("sa-ln-9", rel, 1, 6, root=str(root), force=True)
    assert r2["cached"] is False and r2["notes"] == {5: "新注解"} and calls["n"] == 1
    row = store.SemanticAssetsStore.get("sa-ln-9")
    assert "新注解" in (row.get("lineNotes") or "")
    # 之后再请求 → 命中新缓存
    r3 = S.generate_line_notes("sa-ln-9", rel, 1, 6, root=str(root))
    assert r3["cached"] is True and r3["notes"] == {5: "新注解"} and calls["n"] == 1


def _mk_proc_asset(pid, asset_id, name, rels=None, file="web/src/core/capabilities.ts"):
    store.SemanticAssetsStore.create({
        "id": asset_id, "projectId": pid, "kind": "process",
        "level": "implementation", "name": name, "desc": f"过程「{name}」：模板描述",
        "detail": {"steps": [{"semantic": f"loop items of {name}"}], "relations": rels or []},
        "astRefs": [{"file": file, "symbol": name, "kind": "function",
                     "startLine": 1, "endLine": 7}],
        "status": "active", "needsUpdate": 0,
    })


def test_generate_node_brief_grounded_and_cached(tmp_path, monkeypatch):
    """简介必须引用真实符号(接地校验)，否则降级；成功后缓存命中。"""
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    _mk_proc_asset(pid, "sa-nb-1", "total", file=rel)
    a = store.SemanticAssetsStore.get("sa-nb-1")

    def fake_llm_bad(msgs, **kw):
        return {"content": "这段代码实现了一个通用的数据处理流程，结构清晰。"}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_llm_bad)
    r = S.generate_node_brief(a, str(root), None)
    assert r["degraded"] is True and "通用的数据处理" not in (a.get("nodeBrief") or "")

    def fake_llm_good(msgs, **kw):
        return {"content": "total 方法遍历 items 汇总 amount 金额并返回。"}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_llm_good)
    r2 = S.generate_node_brief(store.SemanticAssetsStore.get("sa-nb-1"), str(root), None)
    assert r2["degraded"] is False and "total" in r2["brief"]
    # 缓存命中(不再调 LLM)
    calls = {"n": 0}
    def fake_llm_count(msgs, **kw):
        calls["n"] += 1
        return {"content": "total 汇总。"}
    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_llm_count)
    r3 = S.generate_node_brief(store.SemanticAssetsStore.get("sa-nb-1"), str(root), None)
    assert r3["cached"] is True and calls["n"] == 0


def test_generate_node_briefs_batch(tmp_path, monkeypatch):
    """按文件批量：一次 LLM 调用生成同文件多个资产简介，接地校验过滤臆造项。"""
    import json as _j
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    rel = _ln_source(root)
    pid = S.project_id_for(str(root), None)
    _mk_proc_asset(pid, "sa-nb-b1", "total", file=rel)
    _mk_proc_asset(pid, "sa-nb-b2", "Order", file=rel)
    calls = {"n": 0}

    def fake_llm(msgs, **kw):
        calls["n"] += 1
        return {"content": _j.dumps({"briefs": [
            {"id": "sa-nb-b1", "brief": "total 方法汇总 items 的 amount。"},
            {"id": "sa-nb-b2", "brief": "这段代码实现了完全抽象的数据处理。"},
        ]}, ensure_ascii=False)}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_llm)
    n = S.generate_node_briefs_batch(pid, rel, [
        store.SemanticAssetsStore.get("sa-nb-b1"),
        store.SemanticAssetsStore.get("sa-nb-b2"),
    ], str(root), None)
    assert calls["n"] == 1 and n == 1   # b2 未引用真实符号被过滤
    assert "total" in (store.SemanticAssetsStore.get("sa-nb-b1").get("nodeBrief") or "")


def test_semantic_graph_skips_member_relation_edges(tmp_path, monkeypatch):
    """关系清洗：指向字段/成员的 contains 不进图边；指向真实资产的关系保留。"""
    root = tmp_path / "proj"
    root.mkdir()
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for(str(root), None)
    _ln_asset(pid, "sa-cl-1", "web/src/x.ts")
    _mk_proc_asset(pid, "sa-cl-2", "Order")
    store.SemanticAssetsStore.update("sa-cl-1", {"detail": {"relations": [
        {"target": "name", "type": "contains"},          # 字段 → 不进图
        {"target": "sa-cl-2", "type": "calls"},          # 真实资产 → 保留
    ]}})
    g = S.semantic_graph(str(root), None)
    edges = [e for e in g["edges"] if e["from"] == "sa-cl-1"]
    assert [(e["to"], e["type"]) for e in edges] == [("sa-cl-2", "calls")]


# ── ensure_synced 自动建索引(此前只检查不建，首次提取永远走降级) ──────────

class _FakeProc:
    def __init__(self, initialized: bool):
        self.returncode = 0
        self.stdout = '{"initialized": %s}' % ("true" if initialized else "false")
        self.stderr = ""


def test_ensure_synced_auto_init(tmp_path, monkeypatch):
    """未初始化 → 自动 codegraph init(首建索引) → 视为已同步。"""
    root = str(tmp_path)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[1])
        return _FakeProc(initialized="init" in calls)

    monkeypatch.setattr(S.subprocess, "run", fake_run)
    assert S.ensure_synced(root) is True
    assert calls[0] == "status" and "init" in calls


def test_ensure_synced_init_failure_degrades(tmp_path, monkeypatch):
    """init 后仍未初始化(codegraph CLI 异常等) → False，调用方走降级路径。"""
    root = str(tmp_path)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[1])
        return _FakeProc(initialized=False)

    monkeypatch.setattr(S.subprocess, "run", fake_run)
    assert S.ensure_synced(root) is False
    assert "init" in calls   # 确实尝试过自动补建


def test_ensure_synced_already_initialized(tmp_path, monkeypatch):
    """已初始化 → 不重复 init，仅 sync 保鲜。"""
    root = str(tmp_path)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[1])
        return _FakeProc(initialized=True)

    monkeypatch.setattr(S.subprocess, "run", fake_run)
    assert S.ensure_synced(root) is True
    assert calls == ["status", "sync"]


def test_source_snippet_codegraph_fallback(tmp_path, monkeypatch):
    """AST 缓存符号缺行段(如 ts 解析未记录行号) → codegraph 符号表兜底展开+高亮。"""
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    src = proj / "c.ts"
    src.write_text("\n".join(f"code-{i}" for i in range(1, 61)), encoding="utf-8")
    pid = S.project_id_for(str(proj), None)
    store.AstCacheStore.upsert(pid, "c.ts", {
        "contentHash": "h", "language": "ts",
        "symbols": [{"name": "EngineCapability", "startLine": None, "endLine": None}],
        "imports": [], "refs": [], "source": "kb"})
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nodes (file_path TEXT, name TEXT, qualified_name TEXT, start_line INT, end_line INT)")
    conn.execute("INSERT INTO nodes VALUES ('c.ts','EngineCapability','EngineCapability',12,16)")
    _patch_all(monkeypatch, "_open_cg", lambda root: conn)
    res = _run_coro(S.api_source_snippet(root=str(proj), project=None,
                                         file="c.ts", line=12, symbol="EngineCapability"))
    assert res["code"] == 0
    d = res["data"]
    assert d["highlight"] == [12, 13, 14, 15, 16]
    assert d["lines"][0]["line"] == 2     # anchor-10
    assert d["lines"][-1]["line"] == 26   # symbolEnd+10
