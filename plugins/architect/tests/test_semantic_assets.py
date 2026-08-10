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
        "id": "sa-d-1", "projectId": "proj-1", "kind": "data_structure",
        "name": "订单聚合", "desc": "订单核心数据结构", "detail": {"fields": []},
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
    assert store.SemanticAssetsStore.search("proj-1", text="订单")[0]["id"] == "sa-d-1"
    assert store.SemanticAssetsStore.search("proj-1", kind="processing_flow") == []
    assert len(store.SemanticAssetsStore.find_by_scope("proj-1", "comm", "L0-0001")) == 1


def test_save_assets_change_detection(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    assets = [{
        "kind": "data_structure", "name": "订单聚合", "desc": "订单核心结构",
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
    assets2 = [{"kind": "processing_flow", "name": "下单流程", "desc": "流程"}]
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
        "id": "sa-d-9", "projectId": "proj-1", "kind": "data_structure",
        "name": "订单聚合", "desc": "订单核心结构", "detail": {},
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
        "id": "sa-f-2", "projectId": "proj-1", "kind": "processing_flow",
        "name": "下单流程", "desc": "下单处理链路", "detail": {"steps": []},
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
    res = S.extract_scope(str(proj), None, scope_type="files", scope_key="order",
                          files=["order.py"], kinds=["data_structure", "processing_flow"],
                          use_llm=False)
    assert res["count"] >= 2
    kinds = {a["kind"] for a in res["assets"]}
    assert "data_structure" in kinds and "processing_flow" in kinds
    ds = next(a for a in res["assets"] if a["kind"] == "data_structure")
    assert ds["astRefs"][0]["file"] == "order.py"
    assert ds["name"] == "Order"
    assert "订单核心结构" in ds["desc"]
