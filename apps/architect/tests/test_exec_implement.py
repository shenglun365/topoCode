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
    _AMEND_TRIG_RE, _DIFF_TRIG_RE, _STOP_TRIG_RE,
    _build_impl_instruction, _is_impl_intent,
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
    """分层意图判定: 显式词(search)/共现兜底/疑问与迟疑排除。"""
    # 命中: 显式词(含长消息内嵌) + 共现兜底 + 英文
    for q in ("执行方案", "执行本任务", "执行任务。", "开始执行", "实施", "执行", "动手实现",
              "执行。", "开始", "调用 coding agent 执行本会话的方案",
              "补充：连接池上限改为64。请执行方案",
              "跑一下方案", "跑起来", "Go Ahead", "执行 RQ-37", "启动执行作业"):
        assert _is_impl_intent(q), q
    # 排除: 疑问语气 / 迟疑前置句 / 否定 / 无宾语动词
    for q in ("这个方案怎么执行", "执行方案吗", "执行本任务？", "怎么执行任务",
              "执行方案前先确认依赖", "检查本会话方案是否符合执行标准",
              "不执行了", "执行风险怎么评估", "还是先讨论执行细节吧",
              "什么是执行方案", "要不要执行方案还是先等等",
              "验证是否生效。请执行方案", "不执行", "执行x",
              "并行执行的分析报告"):
        assert not _is_impl_intent(q), q


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


# ── 两段式执行确认 ────────────────────────────────────────────────────

def _mk_conv_fixture(tmp_path, monkeypatch, rid=None, title="T-确认"):
    """建需求+待执行会话, 返回 (camelCase 会话行, 真实 rid)。"""
    _setup(tmp_path, monkeypatch)
    res = req_agent.run_arch_tool(
        "req.propose", {"title": title, "requirementMd": "目标",
                        "designMd": "方案甲", "acceptanceMd": "编译通过"},
        root=None, project=None)
    assert res.get("ok"), res
    rid = res["requirementId"]
    reqs_mod.spawn_execution_session(req_agent.store.RequirementsStore.get(rid))
    convs = req_agent.store.ConversationsStore.by_req(rid, limit=5)
    conv = next(c for c in convs if c.get("kind") == "execution")
    return conv, rid


def test_two_stage_confirm_preview_then_start(tmp_path, monkeypatch):
    """执行方案→预览(不建作业); 确认执行→建作业+计数; 规约变更→预览刷新。"""
    import asyncio
    conv, _rid = _mk_conv_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import websocket as ws
    from topoone_app_architect.arch_routes import exec_bridge

    started = {}
    monkeypatch.setattr(exec_bridge, "start_implement",
                        lambda conv, instruction, executor_hint=None, branch_name="":
                        started.update(instruction=instruction, branch=branch_name)
                        or "🚀 已启动")

    # ① 首次触发 → 预览, 不建作业
    out1 = asyncio.run(ws._executor_implement(conv, None))
    assert "执行预览" in out1 and "确认执行" in out1
    assert not started, "预览阶段不应启动作业"
    meta1 = req_agent.store.ConversationsStore.get(conv["id"])["meta"]
    assert meta1["execPending"]["instruction"]

    # ② 确认执行 → 建作业, pending 清除, 计数+1
    out2 = asyncio.run(ws._executor_implement(conv, None, confirmed=True))
    assert started and "方案甲" in started["instruction"]
    meta2 = req_agent.store.ConversationsStore.get(conv["id"])["meta"]
    assert not meta2.get("execPending")
    assert meta2["execJobCount"] == 1

    # ③ 再次执行 → 新预览 + 已有实施记录提醒; 确认 → 第二次作业
    out3 = asyncio.run(ws._executor_implement(conv, None))
    assert "已有 1 次实施记录" in out3
    asyncio.run(ws._executor_implement(conv, None, confirmed=True))
    meta3 = req_agent.store.ConversationsStore.get(conv["id"])["meta"]
    assert meta3["execJobCount"] == 2


def test_confirm_stale_spec_forces_repreview(tmp_path, monkeypatch):
    """预览后规约被方案调整 → 确认时不启动, 自动按最新规约刷新预览。"""
    import asyncio
    conv, rid91 = _mk_conv_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import websocket as ws
    from topoone_app_architect.arch_routes import exec_bridge

    started = {}
    monkeypatch.setattr(exec_bridge, "start_implement",
                        lambda conv, instruction, executor_hint=None, branch_name="":
                        started.update(instruction=instruction) or "🚀 已启动")
    monkeypatch.setattr("topoone_app_architect.arch_routes.execution.conv_root_project",
                        lambda conv: (str(tmp_path), "proj-t"))

    asyncio.run(ws._executor_implement(conv, None))          # 预览 v1
    # 方案调整(规约变更)
    req_agent.run_arch_tool("req.amend", {"reqId": rid91, "designMd": "方案乙(改)"},
                            root=None, project=None)
    conv = req_agent.store.ConversationsStore.get(conv["id"])   # 重取(模拟下一条消息现取行)
    out = asyncio.run(ws._executor_implement(conv, None, confirmed=True))
    assert not started, "规约变更后旧预览不得直接启动"
    assert "已按最新规约刷新" in out
    assert "方案乙" in out or "执行预览" in out
    # 重新确认 → 启动, 指令含新方案
    asyncio.run(ws._executor_implement(conv, None, confirmed=True))
    assert started and "方案乙(改)" in started["instruction"]


def test_confirm_trigger_regex():
    from topoone_app_architect.arch_routes.websocket import _CONFIRM_TRIG_RE
    assert _CONFIRM_TRIG_RE.fullmatch("确认执行")
    assert _CONFIRM_TRIG_RE.fullmatch("确认执行！")
    assert not _CONFIRM_TRIG_RE.fullmatch("不确认执行")
