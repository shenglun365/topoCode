"""P3 验收闭环特征测试(裁决 2026-09-26): done 任务的验收材料持久化于
execution_report 沉淀单元(不再只存活于消息文本); 越界缺口显式提示不自动建卡。
"""
from __future__ import annotations

from topoone_app_architect import store
from topoone_app_architect.agent.execution.exec_bridge import _sediment_task_receipt


def test_sediment_includes_acceptance_brief(arch_env):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "acc", "meta": {}})
    conv_id = conv_row["id"]
    task = store.TasksStore.create({
        "conversationId": conv_id, "projectId": "",
        "title": "带验收的任务", "instruction": "x",
        "executorType": "cline-sdk", "status": "done"})
    unit = _sediment_task_receipt(
        conv_id, task["id"], "RQ-x", "done", "带验收的任务",
        "完成摘要", ["src/a.ts"], "", "",
        acceptance_brief="✅ 边界符合：1 个改动文件均在允许范围内")
    assert unit is not None
    content = str(unit.get("content") or "")
    assert "验收材料" in content
    assert "边界符合" in content
    rows = store.ContextUnitsStore.all(conversation_id=conv_id, type_="execution_report")
    assert any("验收材料" in str(r.get("content") or "") for r in rows)


def test_sediment_without_brief_omits_section(arch_env):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "acc2", "meta": {}})
    conv_id = conv_row["id"]
    task = store.TasksStore.create({
        "conversationId": conv_id, "projectId": "",
        "title": "无验收材料的任务", "instruction": "x",
        "executorType": "cline-sdk", "status": "failed"})
    unit = _sediment_task_receipt(conv_id, task["id"], "", "failed",
                                  "无验收材料的任务", "失败摘要", [], "", "")
    assert "验收材料" not in str(unit.get("content") or "")
