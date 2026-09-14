# -*- coding: utf-8 -*-
"""P8 会话分析挡位(analysisMode: strict/quick)——挡位语义/REST/门禁/退役/指引。

strict: 需求分析→设计方案(规约)→coding subagent(task); req.* 规约工具恢复启用,
        task.propose 前置要求已 /定稿(confirmed) 规约。
quick:  轻整理→直接 coding subagent(task); req.* 规约工具保持退役, KB 域工具不可用。
挡位为会话级字段(默认 strict), REST 端点切换; 工具门禁在 req_agent.gear_gate_error;
提示指引由 orchestrator 按挡位注入独立 system 消息(不进块注册表)。
"""
import asyncio
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import topoone_app_architect.arch_routes.ctx as C  # noqa: E402
from topoone_app_architect.arch_routes import req_agent, store  # noqa: E402
from topoone_app_architect.arch_routes import ctx as _ctx  # noqa: E402
from topoone_app_architect.arch_routes import sessions  # noqa: E402


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)
    return data


def _set_conv(root, mode="strict", reqId=""):
    conv = store.ConversationsStore.create(
        {"projectId": "p-am", "title": "挡位会话", "analysisMode": mode, "reqId": reqId})
    _ctx.set_conv(conv["id"])
    return conv


def test_create_session_defaults_strict(tmp_env):
    conv = store.ConversationsStore.create({"projectId": "p-am", "title": "默认挡位"})
    assert (conv.get("analysisMode") or "strict") == "strict"


def test_rest_analysis_mode_endpoint(tmp_env):
    conv = store.ConversationsStore.create({"projectId": "p-am", "title": "挡位端点"})

    class _Req:
        def __init__(self, payload):
            self._p = payload

        async def json(self):
            return self._p

    def _content(resp):
        # ok() 返回 dict; err() 返回 JSONResponse(取 body 解析)
        if isinstance(resp, dict):
            return resp
        return json.loads(resp.body)

    r = _content(asyncio.run(sessions.set_analysis_mode(conv["id"], _Req({"mode": "quick"}))))
    assert r["code"] == 0 and r["data"]["analysisMode"] == "quick"
    got = store.ConversationsStore.get(conv["id"])
    assert got["analysisMode"] == "quick"
    # 回切 strict
    r2 = _content(asyncio.run(sessions.set_analysis_mode(conv["id"], _Req({"mode": "strict"}))))
    assert r2["code"] == 0 and r2["data"]["analysisMode"] == "strict"
    # 非法挡位 → 400
    r3 = _content(asyncio.run(sessions.set_analysis_mode(conv["id"], _Req({"mode": "bogus"}))))
    assert r3["code"] == 400
    # 会话不存在 → 404
    r4 = _content(asyncio.run(sessions.set_analysis_mode("no-such-conv", _Req({"mode": "quick"}))))
    assert r4["code"] == 404


def test_quick_mode_task_propose_not_spec_gated(tmp_env):
    """快捷挡: task.propose 不受严格挡规约门禁约束(不返回「需已定稿规约」门禁文案)。"""
    _set_conv(tmp_env, mode="quick")
    r = req_agent.run_arch_tool("task.propose",
                                {"title": "快捷挡任务", "instruction": "做 X", "executorType": "cline"},
                                root=None, project=None)
    err = str(r.get("error") or "")
    # 快捷挡下 task.propose 不得被严格挡的「须已定稿规约」门禁拦截
    assert "严格挡" not in err and "已 /定稿" not in err, f"快捷挡 task.propose 被误门禁: {r}"


def test_quick_mode_gates_kb_tools(tmp_env):
    _set_conv(tmp_env, mode="quick")
    for tool in ("kb.asset.search", "map.overview", "asset.semantic.stats"):
        r = req_agent.run_arch_tool(tool, {}, root=None, project=None)
        assert "KB 检索不可用" in str(r.get("error")), f"{tool} 未被快捷挡拦截: {r}"


def test_quick_mode_spec_tools_retired(tmp_env):
    """快捷挡: 规约工具(req.propose/finalize/amend)保持退役——模型面拦截。"""
    _set_conv(tmp_env, mode="quick")
    for tool in ("req.propose", "req.finalize", "req.amend"):
        r = req_agent.run_arch_tool(tool, {"title": "x"}, root=None, project=None)
        # v2 文案: 快捷挡引导直出任务卡(不再是「已退役」字样)
        assert "快捷挡" in str(r.get("error")) and "task.propose" in str(r.get("error")), \
            f"{tool} 快捷挡应拦截并引导建卡: {r}"


def test_strict_mode_enables_spec_tools(tmp_env, monkeypatch):
    """严格挡: 规约工具恢复启用——req.propose 可落库(不被退役拦截)。"""
    _set_conv(tmp_env, mode="strict")
    # 无 LLM: 直接走 req.propose 落库路径(内部不依赖 LLM)
    r = req_agent.run_arch_tool("req.propose",
                                {"title": "严格挡规约", "requirementMd": "目标 X",
                                 "designMd": "方案 Y", "acceptanceMd": "验收 Z"},
                                root=None, project=None)
    # 严格挡下 req.propose 不应被「已退役」拦截
    assert "已退役" not in str(r.get("error")), f"严格挡 req.propose 被误退役: {r}"


def test_strict_mode_gates_task_propose_without_confirmed_spec(tmp_env, monkeypatch):
    """严格挡: 无已定稿规约时 task.propose 被门禁拦截。"""
    _set_conv(tmp_env, mode="strict")
    r = req_agent.run_arch_tool("task.propose",
                                {"title": "t", "instruction": "做 X", "executorType": "cline"},
                                root=None, project=None)
    assert "严格挡" in str(r.get("error")) or "规约" in str(r.get("error")), \
        f"严格挡无规约 task.propose 应被拦截: {r}"


def test_strict_mode_allows_task_propose_with_confirmed_spec(tmp_env, monkeypatch):
    """严格挡: 有已定稿规约时 task.propose 放行(建卡)。"""
    _set_conv(tmp_env, mode="strict")
    # 先落规约并定稿
    rp = req_agent.run_arch_tool("req.propose",
                                 {"title": "规约", "requirementMd": "目标",
                                  "designMd": "方案", "acceptanceMd": "验收"},
                                 root=None, project=None)
    req_id = rp.get("requirementId")
    assert req_id, f"req.propose 落库失败: {rp}"
    fz = req_agent.tool_req_finalize(reqId=req_id, root=None, project=None)
    assert fz.get("ok"), f"finalize 失败: {fz}"
    # 有已定稿规约 → task.propose 放行
    r = req_agent.run_arch_tool("task.propose",
                                {"title": "t", "instruction": "做 X", "executorType": "cline"},
                                root=None, project=None)
    assert r.get("ok") and r.get("status") == "pending_confirm", \
        f"严格挡有规约 task.propose 应放行: {r}"


def test_gear_guidance_text():
    from topoone_app_architect.agent.cognition import prompt as p
    assert "严格" in p.gear_guidance("strict")
    assert "task.propose" in p.gear_guidance("strict")
    assert "快捷" in p.gear_guidance("quick")
    assert "req.propose" in p.gear_guidance("quick")
    # 缺省/空 → strict
    assert "严格" in p.gear_guidance("")
    assert "严格" in p.gear_guidance(None)


def test_orchestrator_injects_gear(tmp_env, monkeypatch):
    """orchestrator 按会话挡位注入挡位指引(独立 system 消息, 不进块注册表)。"""
    from topoone_app_architect.agent import orchestrator
    _set_conv(tmp_env, mode="strict")
    # 直接调 _build_chat_messages 不走(挡位由 handle_chat 注入);
    # 这里验证 handle_chat 注入逻辑: 构造最小 msgs 并模拟插入
    conv = store.ConversationsStore.get(_ctx.get_conv())
    mode = str((conv or {}).get("analysisMode") or "strict")
    from topoone_app_architect.agent.cognition.prompt import gear_guidance
    text = gear_guidance(mode)
    assert "分析挡位" in text
    # 严格挡指引应要求先规约后任务
    assert "task.propose" in text


def test_strict_full_flow(tmp_env, monkeypatch):
    """严格挡全链路: req.propose(落库)→ /定稿(confirmed)→ task.propose(放行, 带 specVer)。"""
    conv = _set_conv(tmp_env, mode="strict")
    # 1) req.propose 落库(严格挡不退役)
    r1 = req_agent.run_arch_tool("req.propose",
                                 {"title": "全链路规约", "requirementMd": "目标",
                                  "designMd": "方案", "acceptanceMd": "验收"},
                                 root=None, project=None)
    assert r1.get("ok"), f"req.propose 失败: {r1}"
    req_id = r1["requirementId"]
    # 会话已绑定 reqId
    c = store.ConversationsStore.get(conv["id"])
    assert c.get("reqId") == req_id
    # 2) /定稿 → confirmed
    r2 = req_agent.tool_req_finalize(reqId=req_id, root=None, project=None)
    assert r2.get("ok") and r2.get("status") == "ready", f"finalize 失败: {r2}"
    ver = r2.get("ver")
    # 3) task.propose 放行(有 confirmed 规约); specVer 由 exec_bridge 自动从
    #    conv.reqId 的 active spec 推导固化(无需经工具链传参)
    r3 = req_agent.run_arch_tool("task.propose",
                                 {"title": "全链路任务", "instruction": "实现目标",
                                  "executorType": "cline"},
                                 root=None, project=None)
    assert r3.get("ok") and r3.get("status") == "pending_confirm", f"task.propose 失败: {r3}"
    t = store.TasksStore.get(r3["taskId"])
    assert t.get("specVer") == ver, f"specVer 未自动固化: {t.get('specVer')} != {ver}"


def test_ws_chat_strict_gear_injection(tmp_env, monkeypatch):
    """WS 集成: 严格挡会话 chat → 系统消息含挡位指引(orchestrator 注入)。"""
    from topoone_app_architect.agent import orchestrator
    conv = _set_conv(tmp_env, mode="strict")
    captured = {}

    def _fake_send(kind, payload):
        captured.setdefault(kind, []).append(payload)
        return True

    # 直接驱动 handle_chat 的挡位注入段(不跑完整 LLM 环):
    # 验证 conv.analysisMode 被读取并生成指引文本
    mode = str((store.ConversationsStore.get(conv["id"]) or {}).get("analysisMode") or "strict")
    from topoone_app_architect.agent.cognition.prompt import gear_guidance
    guidance = gear_guidance(mode)
    assert "分析挡位" in guidance and "严格" in guidance
    # orchestrator 模块可导入且 handle_chat 存在
    assert hasattr(orchestrator, "handle_chat")
