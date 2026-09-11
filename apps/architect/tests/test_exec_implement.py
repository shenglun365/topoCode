"""执行会话真实实施链路回归：触发词分流 + 实施指令组装 + req.amend + 播种消息。

Run: cd <repo> && python -m pytest apps/architect/tests/test_exec_implement.py -q
"""
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
from topoone_app_architect.arch_routes import req_agent
from topoone_app_architect.arch_routes import requirements as reqs_mod
from topoone_app_architect.arch_routes.websocket import (
    _AMEND_TRIG_RE, _DIFF_TRIG_RE, _IMPL_TRIG_RE, _STOP_TRIG_RE,
    _build_impl_instruction,
)


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    return C.setup(data_dir=data)


# ── 触发词分流 ────────────────────────────────────────────────────────

def test_impl_triggers():
    for q in ("执行方案", "开始执行", "继续执行", "执行", "实施", "动手实现",
              "执行方案。", "开始执行！"):
        assert _IMPL_TRIG_RE.fullmatch(q), q
    for q in ("执行方案吗", "帮我执行方案", "不执行", "执行x"):
        assert not _IMPL_TRIG_RE.fullmatch(q), q


def test_amend_triggers():
    for q in ("调整方案：把连接池改为全局单例", "方案调整", "调整需求", "修改规约"):
        assert _AMEND_TRIG_RE.search(q), q


def test_stop_and_diff_triggers():
    assert _STOP_TRIG_RE.fullmatch("停止执行")
    assert _STOP_TRIG_RE.fullmatch("中止执行！")
    assert not _STOP_TRIG_RE.fullmatch("停止")
    assert _DIFF_TRIG_RE.fullmatch("查看差异")
    assert _DIFF_TRIG_RE.fullmatch("看 diff?")
    assert not _DIFF_TRIG_RE.fullmatch("查看差异文件的内容")


# ── 实施指令组装 ──────────────────────────────────────────────────────

def test_build_impl_instruction(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = req_agent.run_arch_tool(
        "req.propose",
        {"title": "T-实施", "requirementMd": "目标",
         "designMd": "模块A+模块B", "allowedScopeMd": "modules/x/",
         "forbiddenScopeMd": "src/core/", "acceptanceMd": ["编译通过", "单测通过"],
         "estMin": 30},
        root=None, project=None)
    rid = res["requirementId"]
    r = req_agent.store.RequirementsStore.get(rid)
    a = r["analysis"]
    a["functionalScope"] = ["实现高性能API"]  # propose 侧默认空, 模拟 finalize 后
    req_agent.store.RequirementsStore.update(rid, {"analysis": a})

    ins = _build_impl_instruction(rid)
    assert "T-实施" in ins and rid in ins
    assert "模块A+模块B" in ins          # 方案全文
    assert "modules/x/" in ins           # 允许范围
    assert "src/core/" in ins            # 禁止范围
    assert "编译通过" in ins and "单测通过" in ins  # 验收
    assert "[[IMPLEMENT_DONE]]" in ins and "[[NEED_INPUT]]" in ins  # 回合标记契约
    assert "单元测试" in ins and "编译" in ins      # DoD 三件套


# ── req.amend(方案调整落既有规约) ────────────────────────────────────

def test_req_amend_updates_existing_only(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = req_agent.run_arch_tool(
        "req.propose", {"title": "T-amend", "designMd": "旧方案"},
        root=None, project=None)
    rid = res["requirementId"]
    before = req_agent.store.RequirementsStore.all()

    res2 = req_agent.run_arch_tool(
        "req.amend",
        {"reqId": rid, "designMd": "新方案 v2",
         "forbiddenScope": ["src/核心"], "reasoning": "用户要求"},
        root=None, project=None)
    assert res2.get("ok") is True, res2
    assert set(res2["amended"]) >= {"方案(designMd)", "禁止改动范围"}
    row = req_agent.store.RequirementsStore.get(rid)
    assert row["analysis"]["designMd"] == "新方案 v2"
    assert row["analysis"]["forbiddenScope"] == ["src/核心"]
    # 只更新不新建
    assert len(req_agent.store.RequirementsStore.all()) == len(before)

    # 空参数 → 明确错误
    res3 = req_agent.run_arch_tool("req.amend", {"reqId": rid},
                                   root=None, project=None)
    assert res3.get("ok") is False and "至少传一项" in res3["error"]

    # amend 走 run_arch_tool 的类型收敛(dict designMd → json 串, 不崩)
    res4 = req_agent.run_arch_tool(
        "req.amend", {"reqId": rid, "designMd": {"架构": "新"},
                      "reasoning": "dict 形状"},
        root=None, project=None)
    assert res4.get("ok") is True, res4
    row4 = req_agent.store.RequirementsStore.get(rid)
    assert isinstance(row4["analysis"]["designMd"], str)


# ── 播种消息: 触发词提示 + projectId 落对库 ──────────────────────────

def test_spawn_seed_message_with_triggers_and_project(tmp_path, monkeypatch):
    C2 = _setup(tmp_path, monkeypatch)
    res = req_agent.run_arch_tool(
        "req.propose", {"title": "T-种子", "requirementMd": "目标",
                        "forbiddenScopeMd": "src/core/", "acceptanceMd": "编译通过"},
        root=None, project=None)
    rid = res["requirementId"]
    row = req_agent.store.RequirementsStore.get(rid)
    conv = reqs_mod.spawn_execution_session(row)
    assert conv and conv["kind"] == "execution"
    msgs = req_agent.store.ConversationsStore.messages(conv["id"], limit=10)
    seed = "\n".join(m.get("content", "") for m in msgs if m.get("role") == "assistant")
    assert "执行方案" in seed and "方案调整" in seed          # 触发词提示
    assert "单元测试" in seed and "编译" in seed              # 交付说明
    assert "任务执行页" not in seed                           # 死路指引已移除
    # projectId 落对库(消息与会话同库——messages 能读到即为证明)
    assert any("触发词" in m.get("content", "") for m in msgs)
