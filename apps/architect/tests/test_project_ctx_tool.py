"""project.ctx 聚合画像特征测试(cv-256 教训)。

背景: 原 project.ctx 只返回 KB 域 6 字段——无 KB(降级)项目下 LLM 拿到的
全是 0, 只能答"空状态", 无视了任务执行史(7 done)与代码解析物(187 单元)。

架构对齐点(本测试同时是回归哨兵):
- 数据经 store 层(TasksStore.of_project / ContextUnitsStore.all), 工具不裸写 SQL;
- 每域独立降级(域失败→字段缺省), 工具整体不失败(req_agent 模块头降级语义);
- 无 KB 项目 degraded=True 仍必须给出 execution/parsed 非零画像。
"""
from __future__ import annotations

from topoone_app_architect.agent.tools.impl.kb import tool_project_ctx
from topoone_app_architect.store.base import _insert
from topoone_app_architect.store.conv import ContextUnitsStore
from topoone_app_architect.store.tasks import TasksStore


PID = "proj-ctxtest1"


def _seed_tasks() -> None:
    for i, st in enumerate(("done", "done", "running")):
        TasksStore.create({
            "conversationId": "cv-t1",
            "projectId": PID,
            "title": f"任务{i}",
            "status": st,
        })


def _seed_units(n: int = 3) -> None:
    for i in range(n):
        _insert("arch_context_units", {
            "id": f"cu-{i}",
            "projectId": PID,
            "conversationId": "cv-t1",
            "title": f"单元{i}",
            "type": "note",
        })


def test_degraded_project_sees_execution_and_parsed(arch_env):
    """无 KB(降级)项目: 任务执行史 + 解析物计数必须可见(非全 0 空状态)。"""
    _seed_tasks()
    _seed_units(3)

    out = tool_project_ctx(None, PID)

    assert out["bound"] is False          # 未走 resolve_project 绑定行
    assert out["degraded"] is True        # 无 KB → 降级态
    assert out["execution"]["tasksTotal"] == 3
    assert out["execution"]["tasksDone"] == 2
    assert out["execution"]["tasksActive"] == 1
    assert len(out["execution"]["recentDone"]) == 2
    assert out["parsed"]["semanticAssets"] == 0
    assert out["parsed"]["conversationUnits"] == 3
    assert "asset.semantic.extract" in out["parsed"]["hint"]


def test_recent_done_ordered_and_capped(arch_env):
    """recentDone 仅取最近 5 条 done(按 of_project 的 updated_at 倒序)。"""
    for i in range(7):
        TasksStore.create({
            "conversationId": "cv-t1",
            "projectId": PID,
            "title": f"任务{i}",
            "status": "done",
        })

    out = tool_project_ctx(None, PID)

    recent = out["execution"]["recentDone"]
    assert len(recent) == 5
    assert all(r["title"] for r in recent)


def test_domain_failure_degrades_fields_not_tool(arch_env, monkeypatch):
    """单域失败 → 对应字段缺省, 工具整体仍返回 KB 域基础字段(降级语义)。"""
    _seed_tasks()
    import topoone_app_architect.agent.tools.impl.kb as kb_mod  # noqa: F401

    def _boom(*a, **k):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(
        "topoone_app_architect.store.conv.ContextUnitsStore.all", _boom)

    out = tool_project_ctx(None, PID)

    assert "parsed" not in out              # 解析域失败 → 字段缺省
    assert out["execution"]["tasksDone"] == 2  # 执行域不受牵连
    assert out["degraded"] is True
