"""任务泵句柄清理回归（G5/批次 A1）。

泵退出（done/failed/lost/cancel/异常）必须清理 _TASK_PUMPS 句柄，
防长会话累积已完成任务的泵条目——此前仅 task_stop 弹出（结构评估 A1/G5）。

Run: cd <repo> && python -m pytest apps/architect/tests/test_exec_pump_cleanup.py -q
"""
import asyncio

from topoone_app_architect.agent.execution import pumps as _pumps
from topoone_app_architect.arch_routes import exec_bridge as eb


def _seed(conv_id: str, job_id: str) -> None:
    eb._TASK_PUMPS.setdefault(conv_id, {})[job_id] = "placeholder"


def test_pump_cleanup_on_normal_exit(monkeypatch):
    """泵正常返回（终态事件已处理）→ 句柄移除；空组弹除会话层条目。"""
    async def fake_run(**kw):
        return None

    monkeypatch.setattr(_pumps, "run_event_pump", fake_run)
    _seed("conv-c1", "job-c1")
    asyncio.run(eb._task_pump("conv-c1", "task-c1", "job-c1", "r1", "opencode"))
    assert "job-c1" not in eb._TASK_PUMPS.get("conv-c1", {})
    assert "conv-c1" not in eb._TASK_PUMPS


def test_pump_cleanup_on_exception(monkeypatch):
    """泵内部异常 → finally 仍清理（不让异常路径泄漏句柄）。"""
    async def boom(**kw):
        raise RuntimeError("runner 失联模拟")

    monkeypatch.setattr(_pumps, "run_event_pump", boom)
    _seed("conv-c2", "job-c2")
    try:
        asyncio.run(eb._task_pump("conv-c2", "task-c2", "job-c2", "r1", "opencode"))
    except RuntimeError:
        pass
    assert "job-c2" not in eb._TASK_PUMPS.get("conv-c2", {})


def test_pump_cleanup_keeps_sibling_jobs(monkeypatch):
    """同会话多作业：仅清理自己的句柄，兄弟作业保留。"""
    async def fake_run(**kw):
        return None

    monkeypatch.setattr(_pumps, "run_event_pump", fake_run)
    _seed("conv-c3", "job-c3a")
    _seed("conv-c3", "job-c3b")
    asyncio.run(eb._task_pump("conv-c3", "task-c3a", "job-c3a", "r1", "opencode"))
    assert "job-c3a" not in eb._TASK_PUMPS["conv-c3"]
    assert "job-c3b" in eb._TASK_PUMPS["conv-c3"]
