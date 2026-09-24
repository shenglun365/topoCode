"""知识单元沉淀回归（存储归一：回执/里程碑/错误 → arch_context_units + 工具面 + REST）。

arch_assets 已退役（L4 降级，用户裁决 2026-09-17）：任务回执 → execution_report 单元、
里程碑报告 → analysis 单元、回合错误 → error 单元；asset.* 工具落 artifact 单元。

Run: cd <repo> && python -m pytest apps/architect/tests/test_units_sediment.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_exec_implement import _mk_v2_fixture  # noqa: E402

from topoone_app_architect import store  # noqa: E402
from topoone_app_architect.agent.memory.units import record_turn_error  # noqa: E402


def _setup_env(tmp_path, monkeypatch):
    import topoone_app_architect.ctx as C
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    return C.setup(data_dir=data)


# ── 沉淀接线（任务回执 / 里程碑报告 → 单元）──────────────────────────

def test_done_receipt_sedimented_as_execution_report_unit(tmp_path, monkeypatch):
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "沉淀 E2E", "x")
    assert eb.confirm_task(task["id"])["ok"]
    eb._handle_task_event({"kind": "done",
                           "text": "[[IMPLEMENT_DONE]] 完成实现",
                           "changedFiles": ["src/a.py"]},
                          eb._task_ctx(conv["id"], task["id"], "job-v2-1",
                                       "", "opencode"))
    units = store.ContextUnitsStore.all(conversation_id=conv["id"],
                                        type_="execution_report")
    assert units
    row = units[-1]
    assert "沉淀 E2E" in row["title"] and "done" in row["title"]
    assert row["refs"]["files"] == ["src/a.py"]
    assert row["refs"]["taskId"] == task["id"]
    assert row["importance"] == 1


def test_failed_receipt_sedimented_too(tmp_path, monkeypatch):
    """失败回执同样入单元(P1 distill 材料来源)。"""
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "失败沉淀", "x")
    assert eb.confirm_task(task["id"])["ok"]
    eb._handle_task_event({"kind": "failed", "text": "构建失败: cannot find module"},
                          eb._task_ctx(conv["id"], task["id"], "job-v2-1",
                                       "", "opencode"))
    units = store.ContextUnitsStore.all(conversation_id=conv["id"],
                                        type_="execution_report")
    assert units and "failed" in units[-1]["title"]
    assert "cannot find module" in units[-1]["content"]


def test_milestone_report_sedimented_as_analysis_unit(tmp_path, monkeypatch):
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "MS", "x")
    assert eb.confirm_task(task["id"])["ok"]
    eb._handle_task_event({"kind": "input_required",
                           "text": "里程碑 1 完成\n改动文件: src/m1.py, src/m2.py"},
                          eb._task_ctx(conv["id"], task["id"], "job-v2-1",
                                       "", "opencode"))
    units = store.ContextUnitsStore.all(conversation_id=conv["id"],
                                        type_="analysis")
    assert units
    assert units[-1]["refs"]["files"] == ["src/m1.py", "src/m2.py"]


# ── 回合错误 → error 单元 ──────────────────────────────────────────

def test_turn_error_lands_error_unit(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    record_turn_error("cv-err", "LLM 未返回内容；回合耗时 30s", project_id="pj1")
    units = store.ContextUnitsStore.all(conversation_id="cv-err", type_="error")
    assert len(units) == 1
    assert "LLM 未返回内容" in units[0]["content"]
    assert units[0]["projectId"] == "pj1"
    # 检索面可捞
    hits = store.ContextUnitsStore.search("未返回内容", conversation_id="cv-err")
    assert hits and hits[0]["type"] == "error"


def test_turn_error_empty_conv_noop(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    record_turn_error("", "x")
    assert store.ContextUnitsStore.all(type_="error") == []


# ── 工具面（asset.upsert / list / delete → 单元）───────────────────

def test_asset_tools_roundtrip_on_units(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import req_agent
    _setup_env(tmp_path, monkeypatch)
    up = req_agent.run_arch_tool(
        "asset.upsert", {"title": "结论", "content": "缓存必须失效",
                         "conversationId": "cv9"},
        None, None)
    assert up["ok"] and up["unit"]["type"] == "artifact"
    lst = req_agent.run_arch_tool(
        "asset.list", {"conversationId": "cv9", "q": "缓存"}, None, None)
    assert lst["ok"] and lst["count"] == 1
    upd = req_agent.run_arch_tool(
        "asset.upsert", {"unitId": lst["units"][0]["id"], "title": "结论 v2",
                         "content": "缓存必须失效(修订)", "conversationId": "cv9"},
        None, None)
    assert upd["ok"] and upd["unit"]["title"] == "结论 v2"
    del_res = req_agent.run_arch_tool(
        "asset.delete", {"unitId": lst["units"][0]["id"]}, None, None)
    assert del_res["ok"] is True
    assert req_agent.run_arch_tool(
        "asset.list", {"conversationId": "cv9"}, None, None)["count"] == 0


def test_tools_registered_in_catalog():
    from topoone_app_architect.agent.tools.registry import architect_tools
    names = {t["name"] for t in architect_tools()}
    assert {"asset.upsert", "asset.list", "asset.delete"} <= names


# ── arch_assets 退役确认 ───────────────────────────────────────────

def test_arch_assets_store_removed():
    import topoone_app_architect.store as s
    assert not hasattr(s, "AssetsStore")
    assert not hasattr(s, "ASSET_KINDS")
