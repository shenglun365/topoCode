"""批 3 测试：逻辑级提取(IO 规约/锚点/成员解析) + 组件聚合视图存取。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import topoone_app_architect.ctx as C
from topoone_app_architect.store import SemanticAssetsStore

PID = ""


@pytest.fixture(autouse=True)
def _ctx_env(tmp_path, monkeypatch):
    global PID
    monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path / "data"))
    C._db = None
    C._kb = None
    if hasattr(C, "_project_dbs"):
        C._project_dbs.clear()
    C.setup(data_dir=str(tmp_path / "data"))
    PID = "proj-b3test"
    yield


# ── CodeAnchor / IO 规约（3-D） ──────────────────────────────

def test_build_code_anchor_and_validate(tmp_path):
    from topoone_app_architect.sem.logic_extract import build_code_anchor, validate_iospec
    src = tmp_path / "m.py"
    src.write_text("line1\nline2\ndef create():\n    pass\n", encoding="utf-8")
    root = str(tmp_path)
    a = build_code_anchor(root, {"file": "m.py", "symbol": "create",
                                 "startLine": 3, "endLine": 4}, "workspace", lang="py")
    assert a and a["snippet"].startswith("def create") and a["rev"] == "workspace"
    # 行区间无效 → None
    assert build_code_anchor(root, {"file": "m.py", "startLine": 99, "endLine": 100},
                             "workspace") is None
    # 规约校验：缺锚点/坏锚点拒绝；好锚点通过
    ok1, errs = validate_iospec({"inputs": [{"name": "x", "code": []}], "outputs": []},
                                root, "workspace")
    assert not ok1 and "缺少代码锚点" in errs[0]
    ok2, _ = validate_iospec({"inputs": [{"name": "x", "code": [a]}], "outputs": []},
                             root, "workspace")
    assert ok2


# ── 逻辑链落库 + 成员动态解析（3-C） ─────────────────────────


def test_component_view_lifecycle_and_stale(tmp_path):
    from topoone_app_architect.sem.component_view import (
        save_view, _load, clear_view, mark_stale_for_assets)
    view = save_view(PID, "comp-1", "workspace",
                     {"capability": {"summary": "订单能力",
                                     "entries": [{"name": "创建订单", "summary": "..."}]}},
                     ["sa-impl-1"], model_id="m")
    got = _load(PID, "comp-1", "workspace")
    assert got and got["facets"]["capability"]["entries"][0]["name"] == "创建订单"
    assert got["status"] == "active"
    # 成员资产失效 → 视图 stale
    assert mark_stale_for_assets(PID, ["sa-impl-1"]) == 1
    assert _load(PID, "comp-1", "workspace")["status"] == "stale"
    # 无关资产不影响
    assert mark_stale_for_assets(PID, ["sa-other"]) == 0
    # 清除重生成
    assert clear_view(PID, "comp-1", "workspace") == 1
    assert _load(PID, "comp-1", "workspace") is None
