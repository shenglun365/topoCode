"""统一超时配置(governance/timeouts)测试 — cv-199。

纪律: 框架级阻塞调用超时禁止字面量散落, 一律经 timeouts.get(name) 读取;
环境变量 TOPO_TIMEOUT_<NAME> 应急覆盖(不改代码)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_timeouts_config.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)


def test_registry_defaults_and_coverage():
    """关键阻塞链全部登记; 缺省值合理。"""
    from topoone_app_architect.agent.governance.timeouts import names
    t = names()
    for name in ("llm_call", "se_llm", "kb_rpc", "kb_mcp_tools", "kb_mcp_call",
                 "stream_idle", "runner_snapshot", "runner_steer",
                 "runner_finish", "git_push", "build_engine", "probe_ping"):
        assert name in t, f"超时未登记: {name}"
        assert t[name] > 0
    assert t["probe_ping"] < t["llm_call"]          # 探活远短于生成调用
    assert t["kb_mcp_tools"] < t["kb_mcp_call"]     # 目录列取远短于执行


def test_env_override_and_fail_fast(arch_env, monkeypatch):
    """TOPO_TIMEOUT_<NAME> 覆盖生效; 未登记名字 fail-fast(KeyError)。"""
    monkeypatch.setenv("TOPO_TIMEOUT_KB_RPC", "20")
    import importlib
    from topoone_app_architect.agent.governance import timeouts as T
    importlib.reload(T)
    assert T.get("kb_rpc") == 20
    monkeypatch.setenv("TOPO_TIMEOUT_KB_RPC", "not-a-number")
    importlib.reload(T)
    assert T.get("kb_rpc") == 10.0                  # 非法值回退缺省
    try:
        T.get("no_such_name")
        assert False, "未登记名字应 KeyError"
    except KeyError:
        pass


def test_llm_call_sourced_from_registry(arch_env, monkeypatch):
    """cognition.llm 的调用超时取自单源(env 不覆盖时 = 注册值)。"""
    monkeypatch.delenv("LLM_SYNC_TIMEOUT", raising=False)
    import importlib
    from topoone_app_architect.agent.cognition import llm as llm_mod
    from topoone_app_architect.agent.governance import timeouts as T
    importlib.reload(T)
    importlib.reload(llm_mod)
    assert llm_mod._LLM_CALL_TIMEOUT == T.get("llm_call")
    # 遗留 LLM_SYNC_TIMEOUT 仍优先(口径并存, 不断既有部署)
    monkeypatch.setenv("LLM_SYNC_TIMEOUT", "120")
    importlib.reload(llm_mod)
    assert llm_mod._LLM_CALL_TIMEOUT == 120.0
    monkeypatch.delenv("LLM_SYNC_TIMEOUT")
    importlib.reload(llm_mod)


def test_saved_task_tracks_as_waiting():
    """cv-200: 默认保存(saved)在台账里是「待启动」, 不是 cancelled。"""
    from topoone_app_architect.store.tracking import _task_state_of
    from topoone_app_architect.store.states import (
        TASK_SAVED, TASK_PENDING_CONFIRM, TRACK_WAITING)
    assert _task_state_of(TASK_SAVED) == (TRACK_WAITING, "user")
    assert _task_state_of(TASK_PENDING_CONFIRM) == (TRACK_WAITING, "user")
