"""M3 轻任务模型(mixed-fleet 编排侧)回归。

纯函数层(governance.light_tasks, 零 IO) + 适配层读写(agent_roles) + 两处接线。

Run: cd <repo> && python -m pytest apps/architect/tests/test_light_tasks.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect.agent.governance import light_tasks as lt  # noqa: E402
from topoone_app_architect.arch_routes import store  # noqa: E402


def _setup_env(tmp_path, monkeypatch):
    import topoone_app_architect.arch_routes.ctx as C
    data = str(tmp_path / "d")
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)


# ── 纯函数层 ────────────────────────────────────────────────────────

def test_resolve_pure_empty_cases():
    """零配置/坏输入 = 现行为(恒空串, 绝不抛出)。"""
    assert lt.resolve_light_task_model("summary", {}) == ""
    assert lt.resolve_light_task_model("", {"summary": "m"}) == ""
    assert lt.resolve_light_task_model("summary", None) == ""
    assert lt.resolve_light_task_model("summary", "{bad") == ""
    assert lt.resolve_light_task_model("summary", {"summary": 123}) == ""


def test_normalize_strips_unknown_keys_and_models():
    """词表外键忽略; 越界 modelId 剥离(cv-168 同源教训); 目录空跳过校验。"""
    out = lt.normalize_light_tasks(
        {"summary": "m-lite", "probe": "ghost", "bogus": "x"},
        known_ids=["m-lite"])
    assert out == {"summary": "m-lite", "probe": ""}
    out2 = lt.normalize_light_tasks({"summary": "anything"}, known_ids=[])
    assert out2["summary"] == "anything"    # 目录空 → 校验跳过不误伤


# ── 适配层(存储读写) ────────────────────────────────────────────────

def test_adapter_roundtrip_and_strips(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import agent_roles
    assert agent_roles.get_light_tasks() == {"summary": "", "probe": ""}
    store.CollabConfigStore.set("llm.models", json.dumps(
        [{"id": "m-lite"}, {"id": "m-mid"}]))
    out = agent_roles.set_light_tasks({"summary": "m-lite", "probe": "ghost"})
    assert out == {"summary": "m-lite", "probe": ""}
    assert agent_roles.load_light_tasks_cfg() == {"summary": "m-lite", "probe": ""}


def test_adapter_corrupt_config(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import agent_roles
    store.CollabConfigStore.set(lt.LIGHT_TASKS_KEY, "{not-json")
    assert agent_roles.load_light_tasks_cfg() == {}
    assert agent_roles.get_light_tasks() == {"summary": "", "probe": ""}


# ── 接线(消费方注入 cfg) ────────────────────────────────────────────

def test_wiring_summarize_uses_light_model(tmp_path, monkeypatch):
    """接线①: 会话标题/摘要 → resolve('summary', cfg)。"""
    _setup_env(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import agent_roles
    agent_roles.set_light_tasks({"summary": "m-lite", "probe": ""})
    from topoone_app_architect.agent.memory import units
    from topoone_app_architect.arch_routes import adaptation
    captured = {}

    def fake_summarize_task(**kw):
        captured.update(kw)
        return {"ok": True, "output": {"title": "T", "summary": "S"},
                "degraded": False}

    monkeypatch.setattr(adaptation, "summarize_task", fake_summarize_task)
    conv = store.ConversationsStore.create({"kind": "requirement", "title": "x"})
    store.ConversationsStore.append_message({
        "id": "m1", "conversationId": conv["id"], "role": "user",
        "time": 1, "content": "讨论内容足够长以生成摘要"})
    units.summarize_conversation(conv["id"], force=True)
    assert captured["model_id"] == "m-lite"


def test_wiring_probe_uses_light_model(tmp_path, monkeypatch):
    """接线②: 范围探针 → resolve('probe', cfg)。"""
    _setup_env(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import agent_roles
    agent_roles.set_light_tasks({"summary": "", "probe": "m-mid"})
    import topoone_app_architect.agent.planning.scope_probe as sp
    from topoone_app_architect.arch_routes import req_agent
    captured = {}

    def fake_llm_sync(msgs, **kw):
        captured.update(kw)
        return {"output": {"files": [{"path": "src/a.py", "source": "inference"}],
                           "note": ""}}

    monkeypatch.setattr(req_agent, "llm_sync", fake_llm_sync)
    monkeypatch.setattr(sp, "gather_grounding",
                        lambda root, project, text, exclude_rid="": {
                            "tree": [], "history": [], "kb": []})
    r = sp.probe_scope("/tmp/x", None, "需求文本")
    assert r["ok"]
    assert captured["model_id"] == "m-mid"
