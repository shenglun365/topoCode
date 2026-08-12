"""设计方案 / 范围圈定 / 对比 单元测试(方向1/2/3)。

覆盖:
  - synthesize_after_model: create/alter/drop/extend 确定性合成
  - diff_models: 表级 + 列级差异
  - scope_diff: 迭代范围增删/升降级
  - compare_requirement: planned 计划态 / actual 实施后实际对比(偏差)

Run:  cd <repo> && python -m pytest plugins/architect/tests/test_design.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)
sys.path.insert(0, os.path.join(_repo, "backend-core"))

import plugins.architect.arch_routes.ctx as C
from plugins.architect.arch_routes import design as D


def _ctx(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    return C.setup(data_dir=data)


def _table(tid, name, cols, rels=None):
    return {"id": tid, "name": name, "level": "logical", "change": "same",
            "desc": "", "columns": cols, "relations": rels or [],
            "invariants": [], "ast": {}}


def _col(name, typ="string", pk=False, fk=""):
    return {"name": name, "type": typ, "nullable": True, "pk": pk,
            "fk": fk, "desc": "", "ast": {}}


def test_synthesize_after_model(tmp_path, monkeypatch):
    """create → added；alter → modified(列级替换)；drop → removed。"""
    _ctx(tmp_path, monkeypatch)
    before = [_table("order", "订单", [_col("id", pk=True), _col("amount", "int")]),
              _table("legacy", "旧表", [_col("id", pk=True)])]
    changes = [
        {"action": "create", "name": "payment", "detail": {
            "columns": [_col("id", pk=True), _col("order_id", fk="order")],
            "relations": [{"from": "order", "to": "payment", "type": "1:N", "key": "order_id"}]}},
        {"action": "alter", "assetId": "order", "detail": {
            "columns": [_col("id", pk=True), _col("amount", "int"),
                        _col("status", "string")]}},
        {"action": "drop", "assetId": "legacy", "detail": {}},
    ]
    after = D.synthesize_after_model(before, changes)
    by_id = {t["id"]: t for t in after}
    assert by_id["payment"]["change"] == "added"
    assert by_id["order"]["change"] == "modified"
    assert {c["name"] for c in by_id["order"]["columns"]} == {"id", "amount", "status"}
    assert by_id["legacy"]["change"] == "removed"
    # before 未被原地污染(纯函数深拷贝)
    assert by_id["order"]["change"] == "modified"


def test_diff_models_column_diff(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    before = [_table("order", "订单", [_col("id", pk=True), _col("amount", "int")])]
    after = [
        {"id": "order", "name": "订单", "change": "modified",
         "columns": [_col("id", pk=True), _col("amount", "int"), _col("status")]},
        {"id": "payment", "name": "支付", "change": "added", "columns": [_col("id")]},
        {"id": "legacy", "name": "旧表", "change": "removed", "columns": []},
    ]
    diff = D.diff_models(before, after)
    assert diff["summary"] == {"added": 1, "removed": 1, "modified": 1, "same": 0}
    cd = diff["columnDiffs"]["order"]
    assert [c["name"] for c in cd["added"]] == ["status"]
    assert cd["removed"] == []
    assert cd["modified"] == []


def test_scope_diff(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    prev = [{"assetId": "a", "assetType": "er", "role": "core", "businessReason": ""},
            {"assetId": "b", "assetType": "er", "role": "related", "businessReason": ""},
            {"assetId": "gone", "assetType": "er", "role": "related", "businessReason": ""}]
    proposal = [{"assetId": "a", "assetType": "er", "role": "core", "businessReason": ""},
                {"assetId": "b", "assetType": "er", "role": "core", "businessReason": ""},
                {"assetId": "c", "assetType": "er", "role": "related", "businessReason": ""}]
    diff = D.scope_diff(prev, proposal)
    assert [x["assetId"] for x in diff["added"]] == ["c"]
    assert [x["assetId"] for x in diff["removed"]] == ["gone"]
    assert [x["assetId"] for x in diff["promoted"]] == ["b"]
    assert diff["demoted"] == []


def test_compare_planned_and_actual(tmp_path, monkeypatch):
    _ctx(tmp_path, monkeypatch)
    req = {"id": "RQ-1", "title": "t", "desc": "d", "design": {
        "dataChanges": [{"action": "create", "name": "payment", "detail": {
            "columns": [_col("id", pk=True)]}}],
        "semanticChanges": [{"assetId": "sa-d-1", "name": "支付单", "action": "create",
                             "reason": "新增支付结构"}],
        "beforeTables": [_table("order", "订单", [_col("id", pk=True)])],
        "afterTables": [_table("order", "订单", [_col("id", pk=True)]),
                        {"id": "payment", "name": "支付", "change": "added",
                         "columns": [_col("id", pk=True)], "relations": [],
                         "invariants": [], "ast": {}, "level": "logical", "desc": ""}],
    }}
    planned = D.compare_requirement(req, mode="planned")
    assert planned["mode"] == "planned"
    assert planned["summary"]["added"] == 1
    assert planned["semanticDiff"]["summary"]["create"] == 1

    # actual：payment 未落地 → 偏差；额外出现 fee 表 → 额外变更
    monkeypatch.setattr(D, "build_architecture_model", lambda *a, **k: {
        "erTables": [
            {"id": "order", "name": "订单", "columns": [_col("id", pk=True)]},
            {"id": "fee", "name": "费用", "columns": [_col("id", pk=True)]},
        ]})
    actual = D.compare_requirement(req, mode="actual")
    kinds = [d["kind"] for d in actual["deviations"]]
    assert "未落地(表未创建)" in kinds
    assert "额外变更" in kinds
