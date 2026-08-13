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
sys.path.insert(0, os.path.join(_repo, "backend-core"))

import plugins.architect.arch_routes.ctx as C
import plugins.architect.arch_routes.store as store
from plugins.architect.arch_routes import semantic_assets as S
from plugins.architect.arch_routes import websocket as W


def _ctx(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    # 重置模块级 ctx 单例，确保隔离
    C._db = None
    C._kb = None
    db = C.setup(data_dir=data)
    return db


def _assets(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    return S


def test_store_crud_and_search(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    now = 1
    store.SemanticAssetsStore.create({
        "id": "sa-d-1", "projectId": "proj-1", "kind": "asset",
        "level": "interaction", "name": "订单聚合", "desc": "订单核心数据结构", "detail": {"fields": []},
        "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                     "startLine": 1, "endLine": 10}],
        "scopeType": "comm", "scopeKey": "L0-0001", "source": "live",
        "srcHash": "h1", "change": "added", "status": "active",
        "createdAt": now, "updatedAt": now,
    })
    got = store.SemanticAssetsStore.get("sa-d-1")
    assert got["name"] == "订单聚合"
    assert got["astRefs"][0]["file"] == "src/order.py"          # JSON 列解码
    assert got["detail"] == {"fields": []}                      # JSON 列解码
    assert got["level"] == "interaction"                             # 粒度列
    assert store.SemanticAssetsStore.search("proj-1", text="订单")[0]["id"] == "sa-d-1"
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
            "level": "interaction", "name": f"资产{i}", "desc": f"d{i}", "detail": {},
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
    monkeypatch.setattr(S, "_file_to_components", lambda root, project: {
        "src/order.py": ["A", "B"]})
    # 同一代码(同一锚点)先后在 INCLUDE(A) 与 CALL(B) 组件下提取
    a1 = S._save_assets("proj-n", "comm", "A", [
        {"kind": "asset", "level": "interaction", "name": "订单聚合", "desc": "d",
         "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                      "startLine": 1, "endLine": 10}]},
    ], {"table": {}, "source": "live", "srcHash": "h1", "root": "/x"})[0]
    a2 = S._save_assets("proj-n", "comm", "B", [
        {"kind": "asset", "level": "interaction", "name": "订单聚合", "desc": "d",
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


def test_save_assets_change_detection(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    assets = [{
        "kind": "asset", "level": "interaction", "name": "订单聚合", "desc": "订单核心结构",
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
    assets2 = [{"kind": "process", "level": "interaction", "name": "下单流程", "desc": "流程"}]
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
        "id": "sa-d-9", "projectId": "proj-1", "kind": "asset",
        "level": "interaction", "name": "订单聚合", "desc": "订单核心结构", "detail": {},
        "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                     "startLine": 1, "endLine": 10}],
        "scopeType": "comm", "scopeKey": "k", "source": "live",
        "srcHash": "h", "change": "added", "status": "active",
        "createdAt": 1, "updatedAt": 1,
    })
    block = S.context_block_for("/tmp/x", None, ["实现下单", "sa-d-9"])
    assert "订单聚合" in block
    assert "src/order.py:L1-L10" in block
    assert S.context_block_for("/tmp/x", None, ["无资产上下文"]) == ""


def test_task_prompt_expands_semantic(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    store.SemanticAssetsStore.create({
        "id": "sa-f-2", "projectId": "proj-1", "kind": "process",
        "level": "interaction", "name": "下单流程", "desc": "下单处理链路", "detail": {"steps": []},
        "astRefs": [{"file": "src/order.py", "symbol": "checkout", "kind": "func",
                     "startLine": 20, "endLine": 25}],
        "scopeType": "comm", "scopeKey": "k", "source": "live",
        "srcHash": "h", "change": "added", "status": "active",
        "createdAt": 1, "updatedAt": 1,
    })
    prompt = W._task_prompt({"title": "实现下单", "context": ["sa-f-2"]}, "/tmp/x")
    assert "下单流程" in prompt
    assert "src/order.py:L20-L25" in prompt


def test_extract_scope_heuristic(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "order.py").write_text(
        "class Order:\n    \"\"\"订单核心结构\"\"\"\n    pass\n\n"
        "def checkout(order):\n    pass\n", encoding="utf-8")
    # 使测试确定走 live 扫描(KB 兜底路径可能被本机运行中的 KB 命中)。
    monkeypatch.setattr(S, "_kb_parse_file", lambda *a, **k: None)
    res = S.extract_scope(str(proj), None, scope_type="files", scope_key="order",
                          files=["order.py"], kinds=["asset", "process"],
                          use_llm=False)
    assert res["count"] >= 2
    kinds = {a["kind"] for a in res["assets"]}
    assert "asset" in kinds and "process" in kinds
    ds = next(a for a in res["assets"] if a["kind"] == "asset")
    assert ds["astRefs"][0]["file"] == "order.py"
    assert ds["name"] == "Order"
    assert "订单核心结构" in ds["desc"]
    # 锚定文件哈希签名(要求①)
    assert ds["anchorHashes"] == {"order.py": S._file_md5(str(proj), "order.py")}
    assert ds["needsUpdate"] == 0


def _mk_asset(project_id, asset_id="sa-d-99", anchors=None, **kw):
    store.SemanticAssetsStore.create({
        "id": asset_id, "projectId": project_id, "kind": "asset",
        "level": "interaction", "name": "订单聚合", "desc": "订单核心结构", "detail": {},
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
    monkeypatch.setattr(S, "changed_files", lambda r, project: {
        "added": [], "modified": ["order.py"], "deleted": []})
    res = S.reconcile_semantic(root, None, force=True)
    assert res["invalidated"] == ["sa-d-99"]
    a = store.SemanticAssetsStore.get("sa-d-99")
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
    monkeypatch.setattr(S, "changed_files", lambda r, project: {
        "added": [], "modified": ["order.py"], "deleted": []})
    res = S.reconcile_semantic(root, None, force=True)
    assert res["invalidated"] == []
    assert store.SemanticAssetsStore.get("sa-d-99")["status"] == "active"


def test_reconcile_deleted_file(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    _mk_asset(pid, asset_id="sa-d-98", anchors={"order.py": "oldhash"})
    monkeypatch.setattr(S, "changed_files", lambda root, project: {
        "added": [], "modified": [], "deleted": ["order.py"]})
    S.reconcile_semantic("/tmp/x", None, force=True)
    assert store.SemanticAssetsStore.get("sa-d-98")["change"] == "deleted"


def test_reconcile_new_file_reverse_probe(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    _mk_asset(pid, asset_id="sa-d-97", anchors={"dep.py": "h"})
    monkeypatch.setattr(S, "changed_files", lambda root, project: {
        "added": ["new_mod.py"], "modified": [], "deleted": []})
    monkeypatch.setattr(S, "probe_impact", lambda root, project, files: {
        "dependents": ["dep.py"], "deps": [], "affectedFiles": ["new_mod.py", "dep.py"]})
    res = S.reconcile_semantic("/tmp/x", None, force=True)
    assert res["newFiles"] == ["new_mod.py"]
    assert "sa-d-97" in res["invalidated"]
    assert store.SemanticAssetsStore.get("sa-d-97")["needsUpdate"] == 1


def test_soft_delete_and_regenerate(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    _mk_asset(pid)
    # refresh 成功路径(同 scope 重新生成)
    from plugins.architect.arch_routes import semantic_assets as SM
    store.SemanticAssetsStore.mark_deleted("sa-d-99")
    assert store.SemanticAssetsStore.get("sa-d-99")["status"] == "deleted"
    # 重新提取同名资产 → 恢复 active(软删后重新生成)
    assets = [{"kind": "asset", "level": "interaction", "name": "订单聚合", "desc": "新描述",
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
        "id": "sa-d-11", "projectId": pid, "kind": "asset", "level": "interaction",
        "name": "A1", "desc": "", "detail": {}, "astRefs": [{"file": "a.py"}],
        "scopeType": "comm", "scopeKey": "L0-0001", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    store.SemanticAssetsStore.create({
        "id": "sa-d-12", "projectId": pid, "kind": "asset", "level": "interaction",
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
        {"id": "sa-d-41", "kind": "asset", "level": "interaction", "name": "A",
         "astRefs": [{"file": "svc/a.py"}], "scopeType": "comm", "scopeKey": "L0-0001"},
        {"id": "sa-f-42", "kind": "process", "level": "interaction", "name": "B",
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
        {"id": "sa-d-51", "kind": "asset", "level": "interaction", "name": "A",
         "astRefs": [{"file": "svc/a.py"}], "scopeType": "comm", "scopeKey": "L0-0001"},
        {"id": "sa-f-52", "kind": "process", "level": "interaction", "name": "B",
         "astRefs": [{"file": "tmp/b.py"}], "scopeType": "files", "scopeKey": "_"},
    ]
    for a in assets:
        a.update({"projectId": pid, "desc": "", "detail": {}, "srcHash": "h",
                  "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
        store.SemanticAssetsStore.create(a)
    # 真实场景：组件目录把 svc/a.py 归入 L0-0001。
    monkeypatch.setattr(S, "_component_file_map", lambda root, project: {"L0-0001": {"svc/a.py"}})
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
        "id": "sa-d-21", "projectId": pid, "kind": "asset", "level": "interaction",
        "name": "X", "desc": "", "detail": {}, "astRefs": [{"file": "svc/x.py"}],
        "scopeType": "files", "scopeKey": "_", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    store.SemanticAssetsStore.create({
        "id": "sa-d-22", "projectId": pid, "kind": "asset", "level": "interaction",
        "name": "Y", "desc": "", "detail": {}, "astRefs": [{"file": "tmp/y.py"}],
        "scopeType": "project", "scopeKey": "_", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    monkeypatch.setattr(S, "_component_file_map", lambda root, project: {
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
        "id": "sa-d-31", "projectId": pid, "kind": "asset", "level": "interaction",
        "name": "S", "desc": "", "detail": {}, "astRefs": [{"file": "a.py"}],
        "scopeType": "comm", "scopeKey": "L0-0001", "srcHash": "h",
        "change": "modified", "status": "stale", "needsUpdate": 1,
        "createdAt": 1, "updatedAt": 1})
    calls = {"n": 0}
    def fake_handle(asset_id, root, project, model_id=None):
        calls["n"] += 1
        return {"status": "refreshed"}
    monkeypatch.setattr(S, "handle_stale_asset", fake_handle)
    res = S.batch_manage("/tmp/x", None, "update", comp_ids=["L0-0001"])
    assert res["count"] == 0
    assert calls["n"] == 0
    # 更新路径 = clear(删除) 后再 extract(重跑提取)
    assert store.SemanticAssetsStore.get("sa-d-31") is not None


def test_batch_extract_all_components(tmp_path, monkeypatch):
    """extract 未指定组件时解析组件目录(完整来源)，文件并集去重后逐文件单次提取。"""
    _ctx(tmp_path, monkeypatch)
    import plugins.architect.arch_routes.common as common
    # INCLUDE/CALL 两套组件，重叠 shared.py → 每文件只提取一次
    monkeypatch.setattr(common, "build_component_catalog", lambda *a, **k: {
        "components": [
            {"id": "L0-0001", "owns": ["a.py", "shared.py"]},
            {"id": "L0-0002", "owns": ["shared.py", "b.py"]},
        ]})
    calls = []
    def fake_extract(root, project, scope_type, scope_key, **kw):
        calls.append((scope_type, scope_key))
        return {"assets": [{"id": f"sa-{scope_key}-1"}, {"id": f"sa-{scope_key}-2"}],
                "count": 2}
    monkeypatch.setattr(S, "extract_scope", fake_extract)
    res = S.batch_manage("/tmp/x", None, "extract", comp_ids=[])
    assert res["components"] == 2
    assert res["count"] == 6                       # 3 个唯一文件 × 2
    # 每文件单次提取(scope_type=files)，重叠文件不重复
    assert sorted(calls) == [("files", "a.py"), ("files", "b.py"), ("files", "shared.py")]
    assert calls.count(("files", "shared.py")) == 1


def test_comm_files_falls_back_to_catalog(tmp_path, monkeypatch):
    """模型(INCLUDE·L1)查不到的组件 id(如 CALL/L0) → 回退组件目录解析文件。"""
    _ctx(tmp_path, monkeypatch)
    import plugins.architect.arch_routes.common as common
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
    import plugins.architect.arch_routes.common as common
    common.build_component_catalog = lambda root, project: {"components": []}
    common.build_architecture_model = lambda *a, **k: {"components": []}
    # 即使存在 codegraph 节点，未解析文件的 comm 范围也不应扫全项目。
    monkeypatch.setattr(S, "_query_nodes", lambda conn, files=None, symbols=None, limit=400: [
        {"id": "n1", "kind": "class", "name": "Other", "qualified_name": "Other",
         "file_path": "other/thing.py", "start_line": 1, "end_line": 1,
         "start_column": 0, "end_column": 0, "signature": "", "docstring": "",
         "return_type": ""}])
    res = S.extract_scope("/tmp/x", None, scope_type="comm", scope_key="MISSING-1",
                          kinds=["asset"], use_llm=False)
    assert res["count"] == 0
    assert res["source"] == "none"


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
    """kind/type 中文、驼峰、带空格变体 → 规范枚举(新四类)。"""
    assert S._normalize_kind("data_structure") == "asset"
    assert S._normalize_kind("数据结构") == "asset"
    assert S._normalize_kind("DataStructure") == "asset"
    assert S._normalize_kind("data structure") == "asset"
    assert S._normalize_kind("处理流程") == "process"
    assert S._normalize_kind("processingFlow") == "process"
    assert S._normalize_kind("processing_flow") == "process"
    assert S._normalize_kind("控制逻辑") == "decision"
    assert S._normalize_kind("control-logic") == "decision"
    assert S._normalize_kind("contract") == "contract"
    assert S._normalize_kind("接口") == "contract"
    assert S._normalize_kind("unknown-kind") is None
    assert S._normalize_kind("") is None


def test_normalize_level_aliases():
    """level 中/英/概念变体 → 规范枚举。"""
    assert S._normalize_level("high") == "business"
    assert S._normalize_level("概念") == "business"
    assert S._normalize_level("intent") == "business"
    assert S._normalize_level("业务") == "business"
    assert S._normalize_level("medium") == "interaction"
    assert S._normalize_level("逻辑") == "interaction"
    assert S._normalize_level("low") == "algorithm"
    assert S._normalize_level("代码") == "algorithm"
    assert S._normalize_level(None) is None


def test_norm_llm_asset_type_field_and_steps():
    """LLM 用 type 字段、steps.symbol 单数 → 归一化为 kind/steps.symbols。"""
    table = {
        "create_order": {"id": "n1", "kind": "function", "name": "create_order",
                         "qualified_name": "create_order", "file_path": "svc/order.py",
                         "start_line": 3, "end_line": 5, "start_column": 0, "end_column": 0,
                         "signature": "", "docstring": "", "return_type": ""},
        "_consume": {"id": "n2", "kind": "function", "name": "_consume",
                     "qualified_name": "_consume", "file_path": "svc/order.py",
                     "start_line": 10, "end_line": 14, "start_column": 0, "end_column": 0,
                     "signature": "", "docstring": "", "return_type": ""},
    }
    a = {
        "name": "订单生命周期管理", "type": "processing_flow",
        "desc": "订单创建到过期清理的完整流程。",
        "steps": [{"symbol": "create_order", "action": "初始化新订单", "condition": "库存充足"},
                  {"step": 2, "symbol": "_consume", "action": "资源扣减"}],
        "source_symbols": ["create_order", "_consume", "missing_sym"],
    }
    norm = S._norm_llm_asset(a, table)
    assert norm["kind"] == "process"
    assert norm["level"] == "interaction"
    assert norm["detail"]["steps"][0] == {"order": None, "semantic": "初始化新订单",
                                          "condition": "库存充足", "symbols": ["create_order"]}
    assert norm["detail"]["steps"][1]["order"] == 2
    assert norm["detail"]["steps"][1]["condition"] == ""
    # source_symbols → astRefs(可解析的真实节点；无法解析的记警告跳过)
    files = {r["file"] for r in norm["astRefs"]}
    assert files == {"svc/order.py"}
    assert len(norm["astRefs"]) == 2


def test_norm_llm_asset_relations_branches():
    """relations {from,to,via} 与 branches {condition,then,else,result_symbol} 归一化。"""
    a = {
        "name": "用户认证鉴权", "type": "control_logic",
        "desc": "登录鉴权分支逻辑。",
        "relations": [{"from": "user", "to": "session", "via": "token"},
                      {"target": "balance", "type": "1:1"}],
        "branches": [{"condition": "未登录", "then": ["return 401"], "result_symbol": "err"}],
    }
    norm = S._norm_llm_asset(a, {})
    assert norm["kind"] == "decision"
    assert norm["detail"]["relations"] == [
        {"target": "session", "type": "token", "semantic": ""},
        {"target": "balance", "type": "1:1", "semantic": ""},
    ]
    b = norm["detail"]["branches"][0]
    assert b["condition"] == "未登录"
    assert b["then"] == "return 401"
    assert b["semantic"] == "err"


def test_norm_llm_asset_rejects_missing_kind_name():
    """缺 kind/name → 返回 None(丢弃)。"""
    assert S._norm_llm_asset({"name": "x", "type": "未知"}, {}) is None
    assert S._norm_llm_asset({"kind": "asset"}, {}) is None
    assert S._norm_llm_asset("not-dict", {}) is None


def test_llm_extract_normalizes_chinese_type(tmp_path, monkeypatch):
    """mock llm_sync 返回中文 type 的资产 → 归一化后有效 > 0。"""
    _ctx(tmp_path, monkeypatch)
    import plugins.architect.arch_routes.req_agent as RA
    monkeypatch.setattr(RA, "llm_sync", lambda *a, **k: {
        "output": {"assets": [
            {"name": "订单流程", "type": "处理流程", "desc": "d",
             "steps": [{"symbol": "create_order", "action": "init"}]},
            {"name": "用户模型", "type": "数据结构", "desc": "d",
             "fields": [{"name": "id", "type": "int"}]},
        ]}})
    table = {"create_order": {"id": "n1", "kind": "function", "name": "create_order",
                              "qualified_name": "create_order", "file_path": "svc/order.py",
                              "start_line": 1, "end_line": 2, "start_column": 0,
                              "end_column": 0, "signature": "", "docstring": "", "return_type": ""}}
    out = S._llm_extract("/tmp/x", None, "ctx-text", None, table=table)
    assert len(out) == 2
    kinds = {a["kind"] for a in out}
    assert kinds == {"process", "asset"}


def test_llm_extract_drops_empty_detail_but_keeps_all_empty(tmp_path, monkeypatch):
    """detail 完整性强制：behavior 缺 steps/trigger、rule 缺 branches 时丢弃(仅当存在完整资产)。"""
    _ctx(tmp_path, monkeypatch)
    import plugins.architect.arch_routes.req_agent as RA
    calls = {"n": 0}

    def fake_llm(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"output": {"assets": [
                {"kind": "process", "level": "interaction", "name": "好流程", "desc": "d",
                 "trigger": "触发", "steps": [{"semantic": "s", "symbols": ["f"]}]},
                {"kind": "process", "level": "interaction", "name": "空流程", "desc": "d"},
                {"kind": "decision", "level": "interaction", "name": "空规则", "desc": "d"},
            ]}}
        # 重试仍空 detail → 不级联丢空(保留业务命名资产)
        return {"output": {"assets": [
            {"kind": "process", "level": "interaction", "name": "空流程", "desc": "d"},
            {"kind": "decision", "level": "interaction", "name": "空规则", "desc": "d"},
        ]}}

    monkeypatch.setattr(RA, "llm_sync", fake_llm)
    out = S._llm_extract("/tmp/x", None, "ctx-text", None, table={})
    assert calls["n"] == 2
    # 首轮存在完整资产 → 丢弃 2 个空 detail
    assert [a["name"] for a in out] == ["好流程"]


def test_llm_extract_keeps_when_all_empty_detail(tmp_path, monkeypatch):
    """全部资产缺 detail 时保留(避免丢弃整批触发启发式兜底)。"""
    _ctx(tmp_path, monkeypatch)
    import plugins.architect.arch_routes.req_agent as RA
    monkeypatch.setattr(RA, "llm_sync", lambda *a, **k: {"output": {"assets": [
        {"kind": "process", "level": "interaction", "name": "空流程", "desc": "d"},
        {"kind": "decision", "level": "interaction", "name": "空规则", "desc": "d"},
    ]}})
    out = S._llm_extract("/tmp/x", None, "ctx-text", None, table={})
    assert sorted(a["name"] for a in out) == ["空流程", "空规则"]


def _anchored(name, file="src/order.py", symbol="Order"):
    return {"kind": "asset", "level": "interaction", "name": name, "desc": "d",
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
        {"kind": "asset", "level": "interaction", "name": "订单", "desc": "d",
         "detail": {"relations": [{"target": "用户", "type": "1:N"}]},
         "astRefs": [{"file": "src/order.py", "symbol": "Order",
                      "kind": "class", "startLine": 1, "endLine": 10}]},
        {"kind": "asset", "level": "interaction", "name": "用户", "desc": "d",
         "detail": {"relations": []},
         "astRefs": [{"file": "src/user.py", "symbol": "User",
                      "kind": "class", "startLine": 1, "endLine": 8}]},
    ], ctx)
    g = S.semantic_graph("/tmp/x", "proj-g")
    assert g["count"] == 2
    assert {n["name"] for n in g["nodes"]} == {"订单", "用户"}
    order = next(n for n in g["nodes"] if n["name"] == "订单")
    user = next(n for n in g["nodes"] if n["name"] == "用户")
    edge = next(e for e in g["edges"] if e["from"] == order["id"])
    assert edge["resolved"] is True and edge["to"] == user["id"]
    assert any(a["assetId"] == order["id"] and a["file"] == "src/order.py"
               for a in g["anchors"])


def test_heuristic_extract_low_level_deterministic(tmp_path, monkeypatch):
    """L 级确定性提取：concrete_type/call_chain/branch_logic/message_contract 零 LLM。"""
    _ctx(tmp_path, monkeypatch)
    nodes = [
        {"id": "n1", "kind": "class", "name": "Order", "qualified_name": "Order",
         "file_path": "src/order.py", "start_line": 1, "end_line": 10,
         "start_column": 0, "end_column": 0, "signature": "", "docstring": "订单", "return_type": ""},
        {"id": "n2", "kind": "function", "name": "checkout", "qualified_name": "checkout",
         "file_path": "src/order.py", "start_line": 20, "end_line": 30,
         "start_column": 0, "end_column": 0, "signature": "(o)", "docstring": "", "return_type": ""},
    ]
    ctx = {"nodes": nodes, "edges": [{"source": "n2", "target": "n1", "kind": "calls"}]}
    for kind in ("asset", "process", "decision", "contract"):
        got = S._heuristic_extract(kind, ctx, level="algorithm")
        assert got, kind
        for a in got:
            assert a["level"] == "algorithm"
            assert a["astRefs"], f"{kind} 应有真实 AST 锚点"
    # 同一函数在行为/规则下不再二义性重复(行为是 call_chain，规则是 branch_logic)
    beh = S._heuristic_extract("process", ctx, level="algorithm")
    rul = S._heuristic_extract("decision", ctx, level="algorithm")
    assert beh[0]["detail"].get("kind") == "call_chain"
    assert rul[0]["detail"].get("kind") == "branch_logic"
    assert {a["name"] for a in beh} == {"checkout"}


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
        {"kind": "asset", "level": "interaction", "name": "订单实体", "desc": "",
         "detail": {}, "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class"}]},
        {"kind": "process", "level": "interaction", "name": "下单流程", "desc": "",
         "detail": {}, "astRefs": [{"file": "src/order.py", "symbol": "checkout", "kind": "func"}]},
        {"kind": "asset", "level": "interaction", "name": "用户实体", "desc": "",
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


def test_extract_scope_low_level_uses_llm_with_heuristic_fallback(tmp_path, monkeypatch):
    """level=low 走 LLM(代码事实层)并统一为 low 层级；LLM 不可用回退增强启发式。"""
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "order.py").write_text(
        "class Order:\n    pass\n\ndef checkout(o):\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(S, "_kb_parse_file", lambda *a, **k: None)
    # LLM 可用 → 使用 LLM 资产且层级统一为 low
    monkeypatch.setattr(S, "_llm_extract", lambda *a, **k: [
        {"kind": "process", "level": "algorithm", "name": "checkout 调用链", "desc": "d",
         "detail": {"steps": [{"order": 1, "semantic": "调用 Order", "symbols": ["Order"]}]},
         "astRefs": [{"file": "order.py", "symbol": "checkout", "kind": "func",
                      "startLine": 1, "endLine": 5}]}])
    res = S.extract_scope(str(proj), None, scope_type="files", scope_key="order",
                          files=["order.py"], kinds=["asset", "process"],
                          use_llm=True, level="algorithm")
    assert res["assets"]
    assert all((a.get("level") or "interaction") == "algorithm" for a in res["assets"])
    assert res["assets"][0]["name"] == "checkout 调用链"
    # LLM 返回空 → 启发式兜底，层级仍 low
    monkeypatch.setattr(S, "_llm_extract", lambda *a, **k: [])
    res2 = S.extract_scope(str(proj), None, scope_type="files", scope_key="order",
                           files=["order.py"], kinds=["asset", "process"],
                           use_llm=True, level="algorithm")
    assert res2["degraded"] is True
    assert res2["count"] >= 2
    assert all((a.get("level") or "interaction") == "algorithm" for a in res2["assets"])


def test_store_level_filter(tmp_path, monkeypatch):
    """search/count 支持 level 过滤。"""
    _ctx(tmp_path, monkeypatch)
    store.SemanticAssetsStore.create({
        "id": "sa-hs-1", "projectId": "proj-l", "kind": "asset", "level": "business",
        "name": "领域聚合", "desc": "", "detail": {}, "astRefs": [], "scopeType": "project",
        "scopeKey": "business", "srcHash": "h", "change": "added", "status": "active",
        "createdAt": 1, "updatedAt": 1})
    store.SemanticAssetsStore.create({
        "id": "sa-ls-1", "projectId": "proj-l", "kind": "asset", "level": "algorithm",
        "name": "Order 类型", "desc": "", "detail": {}, "astRefs": [], "scopeType": "project",
        "scopeKey": "algorithm", "srcHash": "h", "change": "added", "status": "active",
        "createdAt": 1, "updatedAt": 1})
    assert store.SemanticAssetsStore.search("proj-l", level="business")[0]["id"] == "sa-hs-1"
    assert store.SemanticAssetsStore.count("proj-l", level="algorithm") == 1
    assert len(store.SemanticAssetsStore.search("proj-l", level="interaction")) == 0


def test_aggregate_high_links_parent(tmp_path, monkeypatch):
    """H 级聚合：mock LLM 归纳业务资产并回填下级 parentId。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", None)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    saved = S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "process", "level": "interaction", "name": "下单流程", "desc": "d",
         "astRefs": [{"file": "src/order.py", "symbol": "checkout",
                      "kind": "func", "startLine": 20, "endLine": 30}]},
        {"kind": "asset", "level": "interaction", "name": "订单聚合", "desc": "d",
         "astRefs": [{"file": "src/order.py", "symbol": "Order",
                      "kind": "class", "startLine": 1, "endLine": 10}]},
    ], ctx)
    child_id = saved[0]["id"]
    import plugins.architect.arch_routes.req_agent as RA
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
    # 子资产在 comm/L0-0001 下提取，无 _file_to_components 归属 → 子 meta.scopes 为空，
    # 此时 business 资产也不应凭空获得归属；验证父资产存在且可检索即可。
    got_high = store.SemanticAssetsStore.get(high["id"])
    assert got_high is not None
    assert got_high["detail"]["aggregates"][0]["assetId"] == child_id


def test_link_parent_propagates_component_membership(tmp_path, monkeypatch):
    """business 聚合资产应继承下级资产的组件归属(meta.scopes)，出现在被聚合组件下。"""
    _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(S, "_file_to_components", lambda root, project: {
        "src/order.py": ["c-order", "c-pay"]})
    pid = S.project_id_for("/tmp/x", None)
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    saved = S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "process", "level": "interaction", "name": "下单流程", "desc": "d",
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


def test_extract_task_runs_and_terminates(tmp_path, monkeypatch):
    """提取任务在后台线程执行并正常结束(不产生死循环)：状态/进度/消息持久化可读。"""
    _ctx(tmp_path, monkeypatch)
    calls = []

    def fake_comm_files(root, comm_key, project=None):
        # 组件 → 文件(带重叠：shared.py 属于 c1/c2，任务级去重只提取一次)
        return {
            "c1": ["a.py", "shared.py"],
            "c2": ["b.py", "shared.py"],
            "bad": ["x.py"],
        }.get(comm_key, [])

    monkeypatch.setattr(S, "_comm_files", fake_comm_files)

    def fake_extract_scope(root, project, scope_type, scope_key, kinds=None,
                           model_id=None, use_llm=True, level="interaction", files=None):
        calls.append((scope_type, scope_key, level))
        if scope_key == "x.py":
            raise RuntimeError("boom")
        return {"assets": [{"id": f"sa-{scope_key}-{level}"}], "count": 2,
                "degraded": False, "source": "codegraph"}

    monkeypatch.setattr(S, "extract_scope", fake_extract_scope)
    monkeypatch.setattr(S, "_aggregate_high_best_effort",
                        lambda *a, **k: {"count": 0})
    import time
    res = S.start_extract_task("/tmp/x", None, ["c1", "c2", "bad"], kinds=["asset"])
    tid = res["taskId"]
    assert tid
    # 轮询直到任务结束(有界等待，避免死循环)
    st = None
    for _ in range(200):
        st = S.extract_task_status(tid)
        if not st["running"]:
            break
        time.sleep(0.02)
    assert st is not None and st["found"] is True
    assert st["status"] == "partial"
    assert st["done"] == 2 and st["total"] == 3
    # 进度项: 逐组件
    assert {p["compId"] for p in st["progress"]} == {"c1", "c2", "bad"}
    assert next(p for p in st["progress"] if p["compId"] == "bad")["status"] == "failed"
    # 消息持久化为 JSON(非字符串), 含开始/完成/失败各阶段
    assert isinstance(st["messages"], list) and len(st["messages"]) >= 6
    for m in st["messages"]:
        assert isinstance(m, dict) and m.get("content")
    # 每文件每级单次提取(scope_type=files)；shared.py 跨组件去重只取一次文件
    assert calls.count(("files", "shared.py", "algorithm")) == 1
    assert calls.count(("files", "shared.py", "interaction")) == 1
    assert ("files", "a.py", "algorithm") in calls
    assert ("files", "b.py", "interaction") in calls
    assert ("files", "x.py", "algorithm") in calls
    # 最近任务可读(刷新后恢复用)
    latest = S.extract_task_status(store.ExtractTaskStore.latest(pid_for("/tmp/x", None))["id"])
    assert latest["id"] == tid


def test_purge_semantic_assets(tmp_path, monkeypatch):
    """物理清理：stale/deleted 行全部删除(不再软删保留)；active 保留。"""
    _ctx(tmp_path, monkeypatch)
    pid = pid_for("/tmp/x", None)
    base = {"projectId": pid, "srcHash": "h", "change": "removed", "status": "deleted",
            "createdAt": 1, "updatedAt": 1, "desc": "", "detail": {}}
    rows = [
        {"id": "sa-d-1", "kind": "asset", "level": "interaction", "name": "legacy-del",
         "astRefs": [], "canonicalKey": ""},
        {"id": "sa-f-2", "kind": "process", "level": "interaction", "name": "legacy-stale",
         "astRefs": [], "canonicalKey": "", "status": "stale", "change": "removed"},
        # 有 ck 的 stale 旧版本 → 也物理删除(清除=全删)
        {"id": "sa-f-3", "kind": "process", "level": "interaction", "name": "ck-stale",
         "astRefs": [{"file": "a.py", "symbol": "A", "kind": "func", "startLine": 1, "endLine": 2}],
         "canonicalKey": "ck-123"},
        # active → 保留
        {"id": "sa-d-4", "kind": "asset", "level": "interaction", "name": "active",
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
    store.SemanticAssetsStore.create({**base, "id": "sa-d-9", "kind": "process", "level": "interaction",
                                      "name": "flow", "astRefs": [], "canonicalKey": ""})
    # 需求池需求引用 sa-d-9(assetScope)
    store.RequirementsStore.create({
        "id": "RQ-1", "title": "下单流程", "kind": "user-story", "priority": "P1",
        "location": "pool", "status": "analyzed",
        "analysis": {"assetScope": [{"assetId": "sa-d-9", "role": "core", "source": "auto"}]},
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
        "analysis": {"assetScope": [{"assetId": "sa-d-9", "role": "related", "source": "auto"}]},
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
        {"kind": "process", "level": "interaction", "name": "下单流程", "desc": "d",
         "detail": {},
         "astRefs": [{"file": "src/order.py", "symbol": "checkout", "kind": "func",
                      "startLine": 20, "endLine": 30}]},
        {"kind": "asset", "level": "interaction", "name": "订单实体", "desc": "d",
         "detail": {},
         "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                      "startLine": 1, "endLine": 10}]},
    ], ctx)
    cg = sqlite3.connect(":memory:")
    cg.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, qualified_name TEXT, name TEXT)")
    cg.execute("CREATE TABLE edges (source TEXT, target TEXT, kind TEXT)")
    cg.execute("INSERT INTO nodes VALUES ('n1','checkout','checkout')")
    cg.execute("INSERT INTO nodes VALUES ('n2','Order','Order')")
    cg.execute("INSERT INTO edges VALUES ('n1','n2','calls')")
    cg.commit()
    monkeypatch.setattr(S, "_open_cg", lambda root: cg)
    g = S.semantic_graph("/tmp/x", "proj-g2")
    derived = [e for e in g["edges"] if e.get("derived")]
    assert derived, "应从 codegraph 边程序化合成资产边"
    assert {e["from"] for e in derived} <= {n["id"] for n in g["nodes"]}
    assert {e["to"] for e in derived} <= {n["id"] for n in g["nodes"]}
    # 派生边不持久化
    beh = next(n for n in g["nodes"] if n["name"] == "下单流程")
    a = store.SemanticAssetsStore.get(beh["id"])
    assert not (a.get("detail") or {}).get("relations")


def test_semantic_graph_symbol_target_resolution(tmp_path, monkeypatch):
    """存库基础关系 target 为符号名时，经全量资产索引解析为资产 id。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-s")
    ctx = {"table": {}, "source": "live", "srcHash": "h1"}
    S._save_assets(pid, "comm", "L0-0001", [
        {"kind": "process", "level": "interaction", "name": "下单流程", "desc": "d",
         "detail": {"relations": [{"target": "Order", "type": "calls"}]},
         "astRefs": [{"file": "src/order.py", "symbol": "checkout", "kind": "func",
                      "startLine": 20, "endLine": 30}]},
        {"kind": "asset", "level": "interaction", "name": "订单实体", "desc": "d",
         "detail": {},
         "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                      "startLine": 1, "endLine": 10}]},
    ], ctx)
    g = S.semantic_graph("/tmp/x", "proj-s")
    order = next(n for n in g["nodes"] if n["name"] == "订单实体")
    edge = next(e for e in g["edges"] if e["type"] == "calls")
    assert edge["resolved"] is True and edge["to"] == order["id"]


def test_llm_extract_forces_requested_level(tmp_path, monkeypatch):
    """LLM 混级输出统一规整为请求层级(层级权威)。"""
    _ctx(tmp_path, monkeypatch)
    import plugins.architect.arch_routes.req_agent as ra
    monkeypatch.setattr(ra, "llm_sync", lambda *a, **k: {
        "output": {"assets": [
            {"kind": "process", "level": "algorithm", "name": "x", "desc": "d",
             "trigger": "触发", "steps": [{"semantic": "s", "symbols": ["f"]}]},
            {"kind": "asset", "level": "business", "name": "y", "desc": "d",
             "fields": [{"name": "id", "type": "int"}]},
            {"type": "decision", "name": "z", "desc": "d",
             "branches": [{"condition": "c", "then": "t", "else": "e"}]},
        ]}})
    got = S._llm_extract(None, None, "ctx", None, table={}, level="interaction")
    assert got and [a["level"] for a in got] == ["interaction", "interaction", "interaction"]


def test_heuristic_low_fields_and_call_chain_symbols():
    """低粒度启发式增强：contains 边派生字段、calls 边用符号名。"""
    nodes = [
        {"id": "n1", "kind": "class", "name": "Order", "qualified_name": "Order",
         "file_path": "src/order.py", "start_line": 1, "end_line": 10,
         "start_column": 0, "end_column": 0, "signature": "", "docstring": "", "return_type": ""},
        {"id": "n2", "kind": "function", "name": "checkout", "qualified_name": "checkout",
         "file_path": "src/order.py", "start_line": 20, "end_line": 30,
         "start_column": 0, "end_column": 0, "signature": "(o)", "docstring": "", "return_type": ""},
        {"id": "n3", "kind": "variable", "name": "total", "qualified_name": "Order::total",
         "file_path": "src/order.py", "start_line": 5, "end_line": 5,
         "start_column": 0, "end_column": 0, "signature": "", "docstring": "", "return_type": "float"},
        {"id": "n4", "kind": "function", "name": "calc", "qualified_name": "calc",
         "file_path": "src/other.py", "start_line": 1, "end_line": 5,
         "start_column": 0, "end_column": 0, "signature": "(o)", "docstring": "", "return_type": ""},
    ]
    edges = [
        {"source": "n1", "target": "n3", "kind": "contains"},
        {"source": "n2", "target": "n4", "kind": "calls"},
    ]
    ctx = {"nodes": nodes, "edges": edges}
    st = S._heuristic_extract("asset", ctx, level="algorithm")
    order = next(a for a in st if a["name"] == "Order")
    assert any(f["name"] == "total" and f["type"] == "float"
               for f in order["detail"]["fields"])
    beh = S._heuristic_extract("process", ctx, level="algorithm")
    ch = next(a for a in beh if a["name"] == "checkout")
    steps = ch["detail"]["steps"]
    assert steps and steps[0]["symbols"] == ["calc"]


def test_extract_all_runs_all_levels_and_aggregates_high(tmp_path, monkeypatch):
    """extract_all 缺省 level 同时产出 low+medium 并聚合 high(三档粒度都有数据)。"""
    _ctx(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")

    def fake_catalog(root, project=None):
        return {"components": [{"id": "c1", "owns": ["a.py"]}]}

    import plugins.architect.arch_routes.common as common
    monkeypatch.setattr(common, "build_component_catalog", fake_catalog)
    monkeypatch.setattr(S, "_kb_parse_file", lambda *a, **k: None)
    seen = []

    def fake_extract_scope(root, project, scope_type, scope_key, kinds=None,
                           model_id=None, use_llm=True, level="interaction", files=None):
        seen.append(level)
        return {"assets": [{"id": f"sa-{level}-{scope_key}"}], "count": 1,
                "degraded": False, "source": "codegraph"}

    monkeypatch.setattr(S, "extract_scope", fake_extract_scope)
    agg = {"n": 0}
    monkeypatch.setattr(S, "_aggregate_high_best_effort",
                        lambda *a, **k: (agg.__setitem__("n", agg["n"] + 1) or {"count": 1}))
    res = S.extract_all(str(proj), None, kinds=["asset"], max_components=12, level="")
    assert seen.count("algorithm") == 1 and seen.count("interaction") == 1
    assert agg["n"] == 1
    assert res.get("high") == 1
    # 显式层级只产该级
    seen.clear()
    agg["n"] = 0
    res = S.extract_all(str(proj), None, kinds=["asset"], max_components=12, level="algorithm")
    assert seen == ["algorithm"] and agg["n"] == 0


def test_grouped_search_items_contiguous_by_component(tmp_path, monkeypatch):
    """分页检索按「所属组件」分组排序：同一组件资产连续，不跨页分散，「其它」排最后。"""
    _ctx(tmp_path, monkeypatch)
    pid = S.project_id_for("/tmp/x", "proj-grp")
    for i, (cid, name) in enumerate([
        ("c2", "B1"), ("c1", "A1"), ("c2", "B2"), ("c1", "A2"), ("__other__", "O1"),
    ]):
        store.SemanticAssetsStore.create({
            "id": f"sa-g-{i}", "projectId": pid, "kind": "asset", "level": "interaction",
            "name": name, "desc": "", "detail": {}, "astRefs": [],
            "scopeType": "comm", "scopeKey": cid, "source": "live", "srcHash": "h",
            "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1 + i,
        })
    monkeypatch.setattr(S, "_component_order_map",
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
        {"kind": "asset", "level": "interaction", "name": "订单实体", "desc": "d",
         "detail": {"fields": [{"name": "id", "type": "str"}, {"name": "total", "type": "float"}],
                    "relations": [{"target": "用户", "type": "1:N"}]},
         "astRefs": [{"file": "src/order.py", "symbol": "Order", "kind": "class",
                      "startLine": 1, "endLine": 10}]},
        {"kind": "process", "level": "interaction", "name": "下单流程", "desc": "d",
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


def test_backfill_anchors_from_relations():
    """无锚点资产兜底: 从 detail.relations[].target 反查真实节点。"""
    table = {
        "admin_blacklist_add": {"id": "n1", "kind": "function", "name": "admin_blacklist_add",
                                "qualified_name": "admin_blacklist_add", "file_path": "app/routes/admin.py",
                                "start_line": 40, "end_line": 60, "start_column": 0, "end_column": 0,
                                "signature": "", "docstring": "", "return_type": ""},
    }
    assets = [{"kind": "process", "level": "infra", "name": "高频限流",
               "desc": "集成 `check_rate_limit`",  # 反引号符号不在表内
               "detail": {"relations": [{"target": "admin_blacklist_add", "type": "calls"}]},
               "astRefs": []}]
    S._backfill_anchors(assets, table)
    assert assets[0]["astRefs"][0]["symbol"] == "admin_blacklist_add"
    # 找不到明确符号 → 不硬补(宁缺毋滥)
    assets2 = [{"kind": "process", "level": "infra", "name": "跨模块行为",
                "desc": "集成 `remote_func`", "detail": {}, "astRefs": []}]
    S._backfill_anchors(assets2, table)
    assert assets2[0]["astRefs"] == []
