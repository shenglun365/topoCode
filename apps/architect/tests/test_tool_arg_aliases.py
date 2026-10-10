"""arg_aliases 参数别名机制测试(cv-3 事故回归 + 机制通用性)。

机制与契约分离(注册声明式): resolve_arg_aliases 纯函数通用语义 +
run_arch_tool 接线 + task.propose 真实契约。fixture 工具验证机制不绑定
任何具体工具名——未来工具在注册点加声明即获得同尺兼容。
"""
from __future__ import annotations

import pytest

from topoone_app_architect.agent.tools.registry import (
    _ARCH_TOOLS,
    register_architect_tool,
    resolve_arg_aliases,
)


# ── 机制层: fixture 工具(通用性, 不依赖真实工具) ──────────────────────


def _register_fixture():
    @register_architect_tool(
        "_test_echo",
        "测试专用: 回显 payload",
        arg_aliases={"body": "payload", "noteMd": "payload"},
        arg_alias_sections={"body": "正文", "noteMd": "备注"},
    )
    def _test_echo(payload: str, root=None, project=None):
        return {"ok": True, "payload": payload}


_register_fixture()


def _entry(name="_test_echo"):
    _register_fixture()      # 按需重注册(防 autouse 清理后失效)
    return _ARCH_TOOLS[name]


@pytest.fixture(autouse=True)
def _cleanup_fixture_tool():
    yield
    _ARCH_TOOLS.pop("_test_echo", None)


class TestResolveArgAliases:
    def test_single_alias_fills_target_without_section(self):
        out, mapped = resolve_arg_aliases(_entry(), {"body": "abc"})
        assert out == {"payload": "abc"}
        assert mapped == [("body", "payload")]

    def test_multiple_aliases_merge_with_sections_in_declaration_order(self):
        out, mapped = resolve_arg_aliases(
            _entry(), {"noteMd": "N", "body": "B"})   # 乱序传入
        assert out["payload"] == "## 正文\nB\n\n## 备注\nN"
        assert mapped == [("body", "payload"), ("noteMd", "payload")]

    def test_explicit_target_wins_alias_dropped(self):
        out, mapped = resolve_arg_aliases(
            _entry(), {"payload": "显式", "body": "别名"})
        assert out == {"payload": "显式"}
        assert mapped == []           # 显式优先: 别名丢弃不记命中

    def test_empty_alias_value_not_mapped(self):
        out, mapped = resolve_arg_aliases(_entry(), {"body": "  "})
        assert out == {}
        assert mapped == []

    def test_undeclared_tool_untouched(self):
        # 未声明别名的 entry: 参数原样返回(后续由 cv-188 TypeError 兜底)
        plain = {"name": "plain", "handler": None, "arg_aliases": {},
                 "arg_alias_sections": {}}
        out, mapped = resolve_arg_aliases(plain, {"requirementMd": "x"})
        assert out == {"requirementMd": "x"}
        assert mapped == []

    def test_registration_rejects_alias_target_not_in_signature(self):
        with pytest.raises(ValueError, match="目标参数不存在于签名"):
            @register_architect_tool(
                "_test_bad", "x",
                arg_aliases={"a": "no_such_param"})
            def _bad(v: str):
                return {}


class TestRunArchToolWiring:
    def test_task_propose_requirement_md_only_maps_to_instruction(self, monkeypatch):
        """cv-3 场景复现: requirementMd(误传) → instruction 分节归一建卡。"""
        from topoone_app_architect.agent.tools import req_agent
        captured = {}

        def _fake_propose(title, instruction, executorType=None, root=None,
                          project=None, safetyClass="", workTags=None):
            captured.update(title=title, instruction=instruction)
            return {"ok": True, "taskId": "task-1", "status": "pending_confirm",
                    "safetyClass": "mutating", "hint": "x"}

        monkeypatch.setattr(
            "topoone_app_architect.agent.planning.task_plan.propose_task_tool",
            _fake_propose)
        res = req_agent.run_arch_tool(
            "task.propose",
            {"title": "连通性探测", "requirementMd": "实现探测",
             "designMd": "用 socket", "acceptanceMd": "跑通"},
            None, None)
        assert res.get("ok") is True
        assert captured["title"] == "连通性探测"
        assert captured["instruction"] == (
            "## 需求目标\n实现探测\n\n## 实现方案\n用 socket\n\n## 验收标准\n跑通")

    def test_task_propose_explicit_instruction_wins(self, monkeypatch):
        from topoone_app_architect.agent.tools import req_agent
        captured = {}

        def _fake_propose(title, instruction, **_kw):
            captured.update(instruction=instruction)
            return {"ok": True, "taskId": "task-2"}

        monkeypatch.setattr(
            "topoone_app_architect.agent.planning.task_plan.propose_task_tool",
            _fake_propose)
        res = req_agent.run_arch_tool(
            "task.propose",
            {"title": "t", "instruction": "显式全文", "requirementMd": "别名"},
            None, None)
        assert res.get("ok") is True
        assert captured["instruction"] == "显式全文"

    def test_alias_types_coerced_after_rename(self):
        """别名值 list → 归一到 str 目标后按注解收敛(类型链协同)。"""
        from topoone_app_architect.agent.tools import req_agent
        entry = _entry()

        def _call(payload: str):
            return payload

        entry["handler"] = _call
        try:
            out, _ = resolve_arg_aliases(entry, {"body": ["行1", "行2"]})
            coerced = req_agent._coerce_args(_call, out)
            assert coerced["payload"] == "行1\n行2"
        finally:
            _register_fixture()   # 恢复真实 handler(防污染后续用例)


class TestTaskProposeContract:
    def test_params_doc_declared_with_required_marks(self):
        entry = _ARCH_TOOLS["task.propose"]
        pd = entry.get("params_doc") or ""
        assert '"title"' in pd and "必填" in pd
        assert '"instruction"' in pd

    def test_alias_targets_exist_in_signature(self):
        """注册校验的运行时等价断言(注册期 fail-fast 之外的双保险)。"""
        import inspect
        fn = _ARCH_TOOLS["task.propose"]["handler"]
        sig = set(inspect.signature(fn).parameters)
        for target in (_ARCH_TOOLS["task.propose"].get("arg_aliases") or {}).values():
            assert target in sig
