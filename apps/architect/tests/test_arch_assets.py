"""K2 知识资产基座回归（arch_assets 表 + 沉淀 + 工具面 + REST）。

Run: cd <repo> && python -m pytest apps/architect/tests/test_arch_assets.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_exec_implement import _mk_v2_fixture  # noqa: E402

from topoone_app_architect.arch_routes import store  # noqa: E402
from topoone_app_architect.arch_routes.store import AssetsStore  # noqa: E402


# ── Store CRUD ──────────────────────────────────────────────────────

def _setup_env(tmp_path, monkeypatch):
    import topoone_app_architect.arch_routes.ctx as C
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    return C.setup(data_dir=data)


def test_store_crud_kind_filter_and_search(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    a = AssetsStore.create({"conversationId": "cv1", "kind": "todo",
                            "title": "补文档", "content": "补 README 用法",
                            "source": "llm", "meta": {"p": 1}})
    b = AssetsStore.create({"conversationId": "cv1", "kind": "analysis",
                            "title": "里程碑", "content": "改动文件: a.py"})
    AssetsStore.create({"conversationId": "cv2", "kind": "todo",
                        "title": "别会话", "content": ""})
    assert a["id"].startswith("asset-") and a["meta"]["p"] == 1
    ids = {r["id"] for r in AssetsStore.of_conv("cv1")}
    assert ids == {a["id"], b["id"]}
    assert [r["id"] for r in AssetsStore.of_conv("cv1", kind="todo")] == [a["id"]]
    assert [r["id"] for r in AssetsStore.of_conv("cv1", q="readme")] == [a["id"]]
    upd = AssetsStore.update(a["id"], {"title": "补文档 v2"})
    assert upd["title"] == "补文档 v2"
    assert AssetsStore.delete(a["id"]) is True
    assert AssetsStore.get(a["id"]) is None


def test_store_invalid_kind_rejected(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    try:
        AssetsStore.create({"conversationId": "cv1", "kind": "nope"})
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("非法 kind 未拒绝")


# ── 沉淀接线（任务回执 / 里程碑报告）────────────────────────────────

def test_done_receipt_sedimented_as_plan_asset(tmp_path, monkeypatch):
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "沉淀 E2E", "x")
    assert eb.confirm_task(task["id"])["ok"]
    eb._handle_task_event({"kind": "done",
                           "text": "[[IMPLEMENT_DONE]] 完成实现",
                           "changedFiles": ["src/a.py"]},
                          eb._task_ctx(conv["id"], task["id"], "job-v2-1",
                                       "", "opencode"))
    assets = AssetsStore.of_conv(conv["id"], kind="plan")
    assert assets and assets[-1]["source"] == "task_receipt"
    row = assets[-1]
    assert "沉淀 E2E" in row["title"] and "done" in row["title"]
    assert row["meta"]["changedFiles"] == ["src/a.py"]
    assert row["meta"]["taskId"] == task["id"]


def test_milestone_report_sedimented_as_analysis_asset(tmp_path, monkeypatch):
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "MS", "x")
    assert eb.confirm_task(task["id"])["ok"]
    eb._handle_task_event({"kind": "input_required",
                           "text": "里程碑 1 完成\n改动文件: src/m1.py, src/m2.py"},
                          eb._task_ctx(conv["id"], task["id"], "job-v2-1",
                                       "", "opencode"))
    assets = AssetsStore.of_conv(conv["id"], kind="analysis")
    assert assets and assets[-1]["source"] == "milestone"
    assert assets[-1]["meta"]["files"] == ["src/m1.py", "src/m2.py"]


# ── 工具面（asset.upsert / list / delete）──────────────────────────

def test_asset_tools_roundtrip(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import req_agent
    _setup_env(tmp_path, monkeypatch)
    up = req_agent.run_arch_tool(
        "asset.upsert", {"kind": "analysis", "title": "结论",
                         "content": "缓存必须失效", "conversationId": "cv9"},
        None, None)
    assert up["ok"] and up["asset"]["source"] == "llm"
    lst = req_agent.run_arch_tool(
        "asset.list", {"conversationId": "cv9", "q": "缓存"}, None, None)
    assert lst["ok"] and lst["count"] == 1
    del_res = req_agent.run_arch_tool(
        "asset.delete", {"assetId": lst["assets"][0]["id"]}, None, None)
    assert del_res["ok"] is True
    assert req_agent.run_arch_tool(
        "asset.list", {"conversationId": "cv9"}, None, None)["count"] == 0


def test_tools_registered_in_catalog():
    from topoone_app_architect.agent.tools.registry import architect_tools
    names = {t["name"] for t in architect_tools()}
    assert {"asset.upsert", "asset.list", "asset.delete"} <= names
