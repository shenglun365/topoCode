"""V1 验收配置设定面回归(task_set_verify_config + REST)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_verify_config.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_exec_implement import _mk_v2_fixture  # noqa: E402

from topoone_app_architect.arch_routes import exec_bridge  # noqa: E402


def test_set_verify_config_roundtrip(tmp_path, monkeypatch):
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "带验收配置", "x")
    t = exec_bridge.task_set_verify_config(
        task["id"], {"test": "npm run test", "build": "npm run build",
                     "maxAttempts": 99, "timeoutMul": 0.1,
                     "autoRepair": False})
    assert t is not None
    assert t["verifyConfig"]["test"] == "npm run test"
    assert t["verifyConfig"]["maxAttempts"] == 6      # 越界钳制
    assert t["verifyConfig"]["timeoutMul"] == 0.5
    assert t["verifyConfig"]["autoRepair"] is False


def test_set_verify_config_rejects_running(tmp_path, monkeypatch):
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "运行态", "x")
    from topoone_app_architect.arch_routes import store
    store.TasksStore.update(task["id"], {"status": "running"})
    assert exec_bridge.task_set_verify_config(task["id"], {"test": "x"}) is None


def test_set_verify_config_invalid_value_rejected(tmp_path, monkeypatch):
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "非法值", "x")
    assert exec_bridge.task_set_verify_config(
        task["id"], {"maxAttempts": "abc"}) is None


def test_confirm_payload_carries_verify(tmp_path, monkeypatch):
    """任务行 verifyConfig → runner start payload.verify(P0 最高权威)。"""
    conv, eb, calls = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "P0 透传", "x")
    assert exec_bridge.task_set_verify_config(
        task["id"], {"test": "python -m pytest -q"}) is not None
    assert eb.confirm_task(task["id"])["ok"]
    paths = [p for p, _ in calls["implement"]]
    assert "/api/implement" in paths
    payload = next(pl for p, pl in calls["implement"] if p == "/api/implement")
    assert payload["verify"] == {"test": "python -m pytest -q"}
