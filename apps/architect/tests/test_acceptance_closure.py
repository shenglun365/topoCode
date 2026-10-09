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


# ── L-1① 越界回执自纠正(deferred-2610): 允许集+最近前缀建议 ──────────

def test_overrun_receipt_self_correcting(arch_env):
    """越界回执含允许范围全集 + 最近前缀建议 + 无相近时的明确指引。"""
    from topoone_app_architect.agent.execution.exec_bridge import (
        _acceptance_brief, _nearest_scope)
    # 规约快照桩: 允许 src/auth/ 与 scripts/
    from topoone_app_architect.store.core import RequirementsStore
    orig = RequirementsStore.spec_active
    RequirementsStore.spec_active = classmethod(
        lambda cls, rid: {"snapshot": {
            "allowedScope": ["src/auth/", "scripts/"],
            "acceptance": ["条目1"]}})
    try:
        brief = _acceptance_brief("c1", "rq-1",
                                  ["src/auth/a.ts", "src/crypto/hash.py",
                                   "docs/readme.md"])
        assert "越界改动" in brief
        assert "src/crypto/hash.py" in brief and "docs/readme.md" in brief
        assert "src/auth/a.ts" not in brief.split("允许范围全集")[0]  # 未越界不在清单
        assert "建议移入允许前缀 `src/auth" in brief       # 最近前缀(共享 src/, 斜杠归一无关)
        assert "允许范围全集" in brief and "`scripts`" in brief
        assert "无相近允许前缀" in brief                     # docs/ 无共享段
    finally:
        RequirementsStore.spec_active = orig


def test_nearest_scope_longest_shared_segments():
    from topoone_app_architect.agent.execution.exec_bridge import _nearest_scope
    assert _nearest_scope("src/auth/deep/x.py",
                          ["src/", "src/auth/", "scripts/"]) == "src/auth/"
    assert _nearest_scope("docs/x.md", ["src/", "scripts/"]) == ""   # 零共享=无相近
    assert _nearest_scope("x.py", []) == ""


# ── 二期E3 变更回执语义化: 验收逐条信号 + 结论评估(建议, 人工裁决) ──────────

def test_receipt_acceptance_signals_and_verdict(arch_env):
    """验收条目信号(◐呼应/○无呼应) + 结论三档(符合/部分/偏离, verifyOverall 合成)。"""
    from topoone_app_architect.agent.execution.exec_bridge import _acceptance_brief
    from topoone_app_architect.store.core import RequirementsStore
    orig = RequirementsStore.spec_active
    RequirementsStore.spec_active = classmethod(
        lambda cls, rid: {"snapshot": {
            "allowedScope": ["src/auth/"],
            "acceptance": ["登录 src/auth/login.ts 重定向", "无关条目 xyzabc"]}})
    try:
        # 全符合 + 全呼应 + 自动验收过 → 建议: 符合
        brief = _acceptance_brief("c1", "rq-1",
                                  ["src/auth/login.ts"], "A")
        assert "◐ 登录 src/auth/login.ts 重定向（改动有呼应）" in brief
        assert "○ 无关条目 xyzabc" in brief and "人工重点核验" in brief
        assert "部分符合/信号不足" in brief            # 一条无呼应 → 部分符合
        # 无呼应清零 + verify A → 符合
        RequirementsStore.spec_active = classmethod(
            lambda cls, rid: {"snapshot": {
                "allowedScope": ["src/auth/"],
                "acceptance": ["登录 src/auth/login.ts 重定向"]}})
        brief2 = _acceptance_brief("c1", "rq-1", ["src/auth/login.ts"], "A")
        assert "建议评估：符合" in brief2
        # verify FAIL → 偏离(最高优先)
        brief3 = _acceptance_brief("c1", "rq-1", ["src/auth/login.ts"], "FAIL")
        assert "建议评估：偏离" in brief3
        # 越界 → 部分符合且理由含越界
        RequirementsStore.spec_active = classmethod(
            lambda cls, rid: {"snapshot": {
                "allowedScope": ["src/auth/"], "acceptance": ["条目"]}})
        brief4 = _acceptance_brief("c1", "rq-1", ["lib/x.py"], "")
        assert "越界改动" in brief4 and "部分符合/信号不足" in brief4
    finally:
        RequirementsStore.spec_active = orig
