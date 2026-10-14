"""错误提炼(P1)回归——collect/build(轻任务)/land 去重 + REST 端点。

Run: cd <repo> && python -m pytest apps/architect/tests/test_distill_errors.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect.agent.memory import distill  # noqa: E402
from topoone_app_architect.agent.memory.units import record_turn_error  # noqa: E402
from topoone_app_architect import store  # noqa: E402


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


def _mk_conv(title="错误提炼会话"):
    conv = store.ConversationsStore.create({"title": title, "projectId": "pj-d"})
    return conv["id"]


def _fake_llm(patterns):
    """monkeypatch summarize_task 通道(经 adaptation.summarize_task 注入)。"""
    import topoone_app_architect.agent.reflection.repair as adaptation

    def fake_summarize_task(*args, **kw):
        return {"ok": True, "output": {"patterns": patterns}}
    return fake_summarize_task


def test_collect_excludes_success_receipts_and_distilled(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    conv_id = _mk_conv()
    record_turn_error(conv_id, "LLM 空返回")
    store.ContextUnitsStore.create({
        "conversationId": conv_id, "projectId": "pj-d",
        "type": "execution_report", "title": "任务回执[failed]：构建炸了",
        "content": "cannot find module 'x'", "refs": {}, "importance": 1})
    store.ContextUnitsStore.create({
        "conversationId": conv_id, "projectId": "pj-d",
        "type": "execution_report", "title": "任务回执[done]：成功",
        "content": "一切正常", "refs": {}, "importance": 1})
    material = distill.collect_error_material(conv_id)
    kinds = {m["kind"] for m in material}
    assert kinds == {"error", "execution_report"}
    assert all("成功" not in m["title"] for m in material)


def test_distill_end_to_end_and_dedup(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    conv_id = _mk_conv()
    record_turn_error(conv_id, "LLM 空返回；预算 30s")
    fake = _fake_llm([{"signature": "LLM 空返回", "cause": "模型 hang/超预算",
                       "fix": "收紧轮次预算"}])
    import topoone_app_architect.agent.reflection.repair as adapt
    monkeypatch.setattr(adapt, "summarize_task", fake)

    out1 = distill.distill_errors(conv_id)
    assert out1["ok"] and out1["count"] == 1
    units = store.ContextUnitsStore.all(project_id="pj-d", type_="error_pattern")
    assert len(units) == 1 and "LLM 空返回" in units[0]["title"]
    assert "hang" in units[0]["content"]
    assert units[0]["refs"]["occurrences"] == 1
    assert units[0]["importance"] == 2

    # 二次提炼(新错误, 同签名) → 追加场景不增行
    record_turn_error(conv_id, "又一次 LLM 空返回")
    out2 = distill.distill_errors(conv_id)
    assert out2["ok"] and out2["count"] == 1
    units2 = store.ContextUnitsStore.all(project_id="pj-d", type_="error_pattern")
    assert len(units2) == 1
    assert units2[0]["refs"]["occurrences"] == 2
    assert conv_id in (units2[0]["refs"]["convs"] or [])


def test_distill_no_material_and_unknown_conv(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    assert distill.distill_errors("no-such")["ok"] is False
    conv_id = _mk_conv()
    out = distill.distill_errors(conv_id)
    assert out["ok"] and out["materialCount"] == 0


def test_build_failure_returns_error(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    conv_id = _mk_conv()
    record_turn_error(conv_id, "boom")

    import topoone_app_architect.agent.reflection.repair as adapt

    def fake_fail(*a, **kw):
        return {"ok": False, "detail": "model down"}
    monkeypatch.setattr(adapt, "summarize_task", fake_fail)
    out = distill.distill_errors(conv_id)
    assert out["ok"] is False and out["error"] == "distill-failed"
    assert store.ContextUnitsStore.all(type_="error_pattern") == []


def test_rest_endpoint(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from topoone_app_architect.arch_routes import router as arch_router
    _setup_env(tmp_path, monkeypatch)
    conv_id = _mk_conv()
    record_turn_error(conv_id, "工具调用失败: 未知工具 foo")
    import topoone_app_architect.agent.reflection.repair as adapt
    monkeypatch.setattr(adapt, "summarize_task", _fake_llm(
        [{"signature": "工具调用失败", "cause": "工具名幻觉",
          "fix": "隔离修复循环已纠正"}]))
    app = FastAPI()
    app.include_router(arch_router)
    with TestClient(app, raise_server_exceptions=False) as client:
        res = client.post(f"/api/architect/sessions/{conv_id}/distill-errors")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["code"] == 0 and body["data"]["count"] == 1
        res404 = client.post("/api/architect/sessions/nope/distill-errors")
        assert res404.status_code == 404
