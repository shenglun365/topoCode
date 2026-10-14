"""P3 MCP 任务两端工具(2610 规约&MCP 定型)——task.mandate / task.receipt。

同源复用验证: context_pack(契约) + _acceptance_brief(L-1① 自纠正回执);
评估性返回, 不改任务状态机(D-4)。
"""
from __future__ import annotations

from topoone_app_architect import store
from topoone_app_architect.sem import map_tools
from topoone_app_architect.sem.task_tools import (
    run_task_tool, tool_task_mandate, tool_task_receipt)


def _fixture(arch_env, tmp_path):
    root = tmp_path / "repo2"
    root.mkdir()
    pid = "proj-mcp-task"
    store.ProjectsStore.create({
        "id": pid, "name": "mcp-task-fixture",
        "root_path": str(root), "active": 1})
    store.ConversationsStore.create(
        {"id": "conv-mcp1", "projectId": pid, "title": "mcp 任务夹具"})
    rid = "req-mcp1"
    req = store.RequirementsStore.create({
        "id": rid, "projectId": pid, "title": "越界检测样例",
        "conversationId": "conv-mcp1"})
    store.RequirementsStore.spec_append(rid, {
        "title": "越界检测样例", "desc": "d", "designMd": "方案X",
        "allowedScope": ["src/auth/", "scripts/"],
        "acceptance": ["登录态校验通过"], "estMin": 30})
    task = store.TasksStore.create({
        "id": "task-mcp1", "conversationId": "conv-mcp1", "projectId": pid,
        "reqId": rid, "title": "实现登录态校验", "instruction": "do",
        "safetyClass": "mutating"})
    return task


def test_task_mandate_by_task_and_req(arch_env, tmp_path):
    task = _fixture(arch_env, tmp_path)
    md = tool_task_mandate(task_id=task["id"])
    assert "执行契约" in md and "实现登录态校验" in md
    assert "允许范围" in md or "src/auth/" in md
    assert "登录态校验通过" in md                      # 验收判据
    assert "规约" in md                                  # 项目规约全集并入
    # req 级(无任务卡)
    md2 = tool_task_mandate(req_id="req-mcp1", project="proj-mcp-task")
    assert "执行契约" in md2 and "需求级契约" in md2
    # 双空参错误提示
    assert "task_id 或 req_id" in tool_task_mandate()
    # 任务不存在
    assert "任务不存在" in tool_task_mandate(task_id="task-nope")


def test_task_receipt_overrun_and_distribution(arch_env, tmp_path):
    task = _fixture(arch_env, tmp_path)
    md = tool_task_receipt(task["id"], ["src/auth/a.ts", "docs/x.md",
                                        "src/crypto/h.py"], "完成")
    assert "执行摘要" in md and "完成" in md
    assert "改动清单(3 文件)" in md
    assert "改动分布" in md and "`docs`: 1 文件" in md
    assert "越界改动" in md                                # L-1① 自纠正
    assert "允许范围全集" in md
    # 全在界内 → 边界符合
    md2 = tool_task_receipt(task["id"], ["scripts/run.py"])
    assert "边界符合" in md2 and "越界改动" not in md2


def test_run_tool_dispatch_and_unknown(arch_env, tmp_path):
    task = _fixture(arch_env, tmp_path)
    out = map_tools.run_tool("task.mandate", {"task_id": task["id"]})
    assert "执行契约" in out
    assert "未知任务工具" in run_task_tool("task.nope", {})
