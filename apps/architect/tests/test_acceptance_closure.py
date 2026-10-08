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


# ── W4 K2 测试段(2610-B1): 回执 refs.tests 主张层字段 ─────────────────

def test_sediment_tests_section_from_changed_test_files(arch_env):
    """变更含测试文件 → refs.tests 记录清单+run_result(verify_test 缺省 not_run)。"""
    conv_row = store.ConversationsStore.create({"projectId": "", "title": "t", "meta": {}})
    conv_id = conv_row["id"]
    task = store.TasksStore.create({
        "conversationId": conv_id, "projectId": "", "title": "补测任务",
        "instruction": "x", "executorType": "cline-sdk", "status": "done"})
    unit = _sediment_task_receipt(
        conv_id, task["id"], "", "done", "补测任务", "摘要",
        ["src/a.ts", "tests/a.test.ts", "src/test_util.py", "app/b.spec.js"],
        "", "")
    refs = unit["refs"]
    assert refs["tests"]["run_result"] == "not_run"
    paths = [f["path"] for f in refs["tests"]["files"]]
    assert paths == ["tests/a.test.ts", "src/test_util.py", "app/b.spec.js"]
    assert "src/a.ts" not in paths
    assert "测试文件: 3 个" in str(unit["content"])


def test_sediment_tests_run_result_from_progress(arch_env):
    """prog.verify_test 有值(verify gate 落地后) → run_result 取真值。"""
    conv_row = store.ConversationsStore.create({"projectId": "", "title": "t2", "meta": {}})
    conv_id = conv_row["id"]
    task = store.TasksStore.create({
        "conversationId": conv_id, "projectId": "", "title": "通过任务",
        "instruction": "x", "executorType": "opencode", "status": "done",
        "progress": {"verify_test": "pass"}})
    unit = _sediment_task_receipt(conv_id, task["id"], "", "done", "通过任务",
                                  "摘要", ["tests/x_test.py"], "", "")
    assert unit["refs"]["tests"]["run_result"] == "pass"


def test_sediment_no_test_files_omits_tests(arch_env):
    conv_row = store.ConversationsStore.create({"projectId": "", "title": "t3", "meta": {}})
    conv_id = conv_row["id"]
    task = store.TasksStore.create({
        "conversationId": conv_id, "projectId": "", "title": "纯实现",
        "instruction": "x", "executorType": "cline-sdk", "status": "done"})
    unit = _sediment_task_receipt(conv_id, task["id"], "", "done", "纯实现",
                                  "摘要", ["src/only.ts"], "", "")
    assert "tests" not in unit["refs"]
