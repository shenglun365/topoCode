"""M4 补偿组件: 工具调用隔离修复循环(repair_tool_call)回归。

Run: cd <repo> && python -m pytest apps/architect/tests/test_repair_tool_call.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


from topoone_app_architect.agent.reflection import repair_tasks as rt  # noqa: E402


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


def test_registry_has_tool_call_kind():
    """可扩展注册表: tool_call 在案; 新修复种类经 register_repair 扩展。"""
    assert "tool_call" in rt.repair_kinds()

    @rt.register_repair("test_kind")
    def _b(**kw):
        return None

    try:
        assert "test_kind" in rt.repair_kinds()
    finally:
        rt._REPAIR_BUILDERS.pop("test_kind", None)


def test_repair_fixes_unknown_tool(tmp_path, monkeypatch):
    """未知工具(名称幻觉) → 隔离修复出合法工具名 → 执行成功。"""
    _setup_env(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import req_agent, store

    def fake_llm_sync(msgs, **kw):
        assert "req_probe" in msgs[-1]["content"]       # 原调用可见
        assert "kb.asset.search" in msgs[-1]["content"]  # 合法清单在案
        return {"content": '{"tool": "kb.asset.search", '
                           '"arguments": {"text": "订单"}}'}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync",
                        fake_llm_sync)

    def fake_run(name, args, root, project):
        if name == "req_probe":                          # 名称幻觉
            return {"error": f"未知工具: {name}"}
        assert name == "kb.asset.search"
        return {"assets": [{"id": "a-1"}], "ok": True}

    monkeypatch.setattr(req_agent, "run_arch_tool", fake_run)
    out = req_agent.execute_tool_with_repair(
        "req_probe", {}, None, None, model_id="m1")
    assert out.get("ok") is True


def test_repair_failure_returns_original_error(tmp_path, monkeypatch):
    """修复器无法映射(空对象) → 原错误如实返回(不静默)。"""
    _setup_env(tmp_path, monkeypatch)

    def fake_llm_sync(msgs, **kw):
        return {"content": "{}"}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync",
                        fake_llm_sync)
    from topoone_app_architect.arch_routes import req_agent
    monkeypatch.setattr(req_agent, "run_arch_tool",
                        lambda name, args, root, project:
                        {"error": f"未知工具: {name}"})
    out = req_agent.execute_tool_with_repair("nope", {}, None, None)
    assert out == {"error": "未知工具: nope"}


def test_semantic_errors_not_repaired(tmp_path, monkeypatch):
    """语义类错误(资产不存在等)不走修复(仅「未知工具」机械类)。"""
    _setup_env(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import req_agent

    def boom(*a, **k):
        raise AssertionError("不应触发修复通道")

    monkeypatch.setattr("topoone_app_architect.agent.reflection."
                        "repair_tasks.run_tool_call_repair", boom)
    monkeypatch.setattr(req_agent, "run_arch_tool",
                        lambda name, args, root, project:
                        {"error": "asset-not-found"})
    out = req_agent.execute_tool_with_repair("asset.semantic.detail", {}, None, None)
    assert out == {"error": "asset-not-found"}


def test_repair_budget_single_attempt(tmp_path, monkeypatch):
    """预算: 每调用限 1 次修复——修复后再失败不再进入修复通道。"""
    _setup_env(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import req_agent
    calls = {"n": 0}

    def fake_llm_sync(msgs, **kw):
        calls["n"] += 1
        return {"content": '{"tool": "kb.baseline", "arguments": {}}'}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync",
                        fake_llm_sync)

    def fake_run(name, args, root, project):
        if name == "req_probe":
            return {"error": f"未知工具: {name}"}
        return {"error": "asset-not-found"}              # 修复后仍失败(语义类)

    monkeypatch.setattr(req_agent, "run_arch_tool", fake_run)
    out = req_agent.execute_tool_with_repair("req_probe", {}, None, None)
    assert out == {"error": "asset-not-found"}
    assert calls["n"] == 1                               # 预算 1 次, 无二次修复


def test_dataset_recorded(tmp_path, monkeypatch):
    """样本回流: 修复事件落 llm_dataset(kind=tool_call_repair)。"""
    _setup_env(tmp_path, monkeypatch)
    from topoone_app_architect.agent.reflection import dataset as ds
    from topoone_app_architect.arch_routes import req_agent

    def fake_llm_sync(msgs, **kw):
        return {"content": '{"tool": "kb.baseline", "arguments": {}}'}

    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync",
                        fake_llm_sync)
    monkeypatch.setattr(req_agent, "run_arch_tool",
                        lambda name, args, root, project:
                        {"error": f"未知工具: {name}"} if name == "req_probe"
                        else {"baseline": {}})
    req_agent.execute_tool_with_repair("req_probe", {}, None, None)
    rows = [json.loads(ln) for ln in open(ds._path(), encoding="utf-8")]
    kinds = [r["kind"] for r in rows]
    assert "tool_call_repair" in kinds
