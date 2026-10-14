"""执行器能力矩阵单源回归（B1/批次 2）。

Run: cd <repo> && python -m pytest apps/architect/tests/test_executor_capabilities.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect.agent.execution.capabilities import (  # noqa: E402
    caps, executor_types, is_valid_type, normalize)


def test_type_sets_and_aliases():
    """双命名空间（任务行/注册表）均合法; 未知类型拒绝; 清单排序稳定。"""
    for t in ("cline", "cline-sdk", "opencode", "codex", "codex-server"):
        assert is_valid_type(t), t
    assert not is_valid_type("mock")
    assert not is_valid_type("")
    assert normalize("cline-sdk") == "cline" and normalize("codex-server") == "codex"
    assert normalize("cline") == "cline"
    assert executor_types() == ["cline", "codex", "opencode"]


def test_caps_matrix_fields():
    """能力矩阵语义: 审批/检查点/steer 仅 cline; readonly_hard cline+codex。"""
    assert caps("cline")["approval"] and caps("cline")["checkpoint"]
    assert caps("cline")["steer"] and caps("cline")["readonly_hard"]
    assert not caps("opencode")["approval"] and not caps("opencode")["checkpoint"]
    assert not caps("codex")["steer"] and caps("codex")["readonly_hard"]
    assert caps("__nope__") == {}


def test_workspace_mapping_via_caps():
    """workspace 映射: cline 目录约定; opencode/codex 空串(组装端回落 AGENTS.md)。"""
    assert caps("cline-sdk")["workspace_rules"] == ".cline/rules"
    assert caps("cline-sdk")["workspace_agents"] == ".cline/agents"
    assert caps("opencode")["workspace_rules"] == ""
    assert caps("codex-server")["workspace_rules"] == ""


def test_build_workspace_files_mapping(tmp_path, monkeypatch):
    """组装端行为保真: cline→.cline/*, opencode/未知→AGENTS.md, teams 仅 cline。"""
    from topoone_app_architect.agent.execution import exec_bridge as eb
    task = {"rulesMd": "规则正文"}
    cfg = {"teams": {"agents": [{"name": "planner", "content": "规划者"}]}}

    cline = eb._build_workspace_files("cline-sdk", cfg, task)
    assert {f["path"] for f in cline} == {".cline/rules/000-guide.md",
                                          ".cline/agents/planner.md"}
    oc = eb._build_workspace_files("opencode", cfg, task)
    assert [f["path"] for f in oc] == ["AGENTS.md"]
    cx = eb._build_workspace_files("codex-server", {}, {"rulesMd": ""})
    assert cx == []                                  # 无规约来源 → 无文件产出
    unknown = eb._build_workspace_files("mock", cfg, task)
    assert [f["path"] for f in unknown] == ["AGENTS.md"]   # 未知类型回落通用路径


def test_task_set_executor_accepts_both_namespaces(tmp_path, monkeypatch):
    """任务卡切执行器: UI 语义类型与注册表类型都收, 未知拒绝。"""
    from test_exec_implement import _mk_v2_fixture
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "E", "x")
    assert eb.task_set_executor(task["id"], "codex-server")  # 注册表类型
    task2 = eb.propose_task(conv, "E2", "x")
    assert eb.task_set_executor(task2["id"], "opencode")     # 同名双空间
    task3 = eb.propose_task(conv, "E3", "x")
    assert eb.task_set_executor(task3["id"], "mock") is None  # 未知拒绝


def test_adapter_capability_parity_with_matrix():
    """跨层对账: runner TurnAdapter 覆写面 ↔ capabilities.py(approval/steer)。

    与 core 侧 test_adapter_conformance.py 的 EXPECTED_ADAPTER_CAPABILITIES
    构成双护栏——任一侧漂移即被捕获。
    """
    from topoone.plugins.runner.turn_adapter import TurnAdapter, build_adapter
    adapters = {
        "cline": build_adapter("cline-sdk", "cline", {}),
        "opencode": build_adapter("opencode", "opencode", {}),
        "codex": build_adapter("codex-server", "codex", {}),
    }
    for t, adapter in adapters.items():
        cap = caps(t)
        approval = callable(getattr(adapter, "respond_approval", None))
        steer_overridden = (type(adapter).steer is not TurnAdapter.steer)
        assert approval == bool(cap["approval"]), t
        assert steer_overridden == bool(cap["steer"]), t
