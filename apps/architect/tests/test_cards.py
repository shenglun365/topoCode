"""消息卡片契约(cards 单源) — cv-175 规范化环节一。

保证: 卡片落流唯一出口 land(); kind 白名单校验; 库路由/reviewState/SSE
单点实现; 旧入口(_append/log_conv_event)委托等价。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.store as store





def test_land_unknown_kind_raises(arch_env):
    """kind 不在白名单 → 明确报错(禁止静默降级/手写新卡)。"""
    from topoone_app_architect.agent.collab import cards
    with pytest.raises(ValueError, match="词汇表"):
        cards.land("cv-x", "t", kind="my_shiny_new_card")


def test_land_appends_meta_review_and_sse(arch_env, monkeypatch):
    """落库形状: meta 序列化 + reviewState(unread 默认/可覆盖) + SSE 单次。"""
    from topoone_app_architect.agent.collab import cards
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    sse = []
    monkeypatch.setattr(cards, "emit", lambda _t, cid, msgId="", agent="", kind="": sse.append((cid, msgId, kind)))
    row = cards.land(conv["id"], "卡内容", kind=cards.KIND_REQUIREMENT,
                     requirementId="RQ-1", ver=1)
    assert row and row["id"]
    msgs = store.ConversationsStore.messages(conv["id"])
    assert len(msgs) == 1
    assert json.loads(row["meta"]) == {"kind": "specReady", "requirementId": "RQ-1", "ver": 1}
    assert msgs[0]["meta"] == {"kind": "specReady", "requirementId": "RQ-1", "ver": 1}  # 读侧已解析为 dict
    assert (store.ConversationsStore.get(conv["id"]) or {}).get("reviewState") == "unread"
    assert sse == [(conv["id"], row["id"], "specReady")]
    # 错误卡: reviewState=error
    cards.land(conv["id"], "❌ boom", kind=cards.KIND_TURN_ERROR, review_state="error")
    assert (store.ConversationsStore.get(conv["id"]) or {}).get("reviewState") == "error"


def test_land_pure_text_without_kind(arch_env):
    """kind=None → 无 meta 纯文本回执(允许), 不校验白名单。"""
    from topoone_app_architect.agent.collab import cards
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    row = cards.land(conv["id"], "普通回执")
    assert row and "meta" not in row
    msgs = store.ConversationsStore.messages(conv["id"])
    assert (msgs[0].get("meta") or {}) == {}


def test_project_routing_from_conv(arch_env):
    """未显式给 project → 从会话行取(消息与会话同库, 防主库孤儿)。"""
    from topoone_app_architect.agent.collab import cards
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t",
                                            "projectId": "proj-1"})
    row = cards.land(conv["id"], "x", kind=cards.KIND_TASK_CARD, taskId="task-1")
    assert row["projectId"] == "proj-1"


def test_legacy_wrappers_delegate_to_land(arch_env, monkeypatch):
    """旧入口(_append/log_conv_event)必须委托 land——四实现漂移根因封死。"""
    from topoone_app_architect.agent.collab import cards
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    sse = []
    monkeypatch.setattr(cards, "emit", lambda _t, cid, msgId="", agent="", kind="": sse.append(kind))
    # log_conv_event 委托
    from topoone_app_architect.arch_routes import req_agent
    req_agent.log_conv_event(conv["id"], "需求卡", meta={"kind": "specReady",
                                                         "requirementId": "RQ-9", "ver": 2})
    # _append 委托
    from topoone_app_architect.arch_routes import exec_bridge as eb
    eb._append(conv["id"], "assistant", "任务卡",
               msg_meta={"kind": "task_card", "taskId": "task-9"})
    msgs = store.ConversationsStore.messages(conv["id"])
    kinds = [m["meta"]["kind"] for m in msgs if m.get("meta")]
    assert kinds == ["specReady", "task_card"]
    assert sse == ["specReady", "task_card"]
    # 旧入口同样受白名单约束
    with pytest.raises(ValueError):
        eb._append(conv["id"], "assistant", "x", msg_meta={"kind": "nope"})


def test_requirement_card_single_emit_per_extract_path(arch_env, monkeypatch):
    """cv-177 回归: propose/amend 路径各恰一张 specReady 卡(无双发)。"""
    from topoone_app_architect.agent.collab import cards
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    monkeypatch.setattr(cards, "emit", lambda *a, **k: None)
    from topoone_app_architect.arch_routes import req_agent
    token = C.set_conv(conv["id"])   # propose/amend 的卡片落流按请求级会话上下文路由
    try:
        r = req_agent.run_arch_tool(
            "req.propose", {"title": "T", "requirementMd": "目标", "designMd": "方案"},
            root=None, project=None, internal=True)
        assert r.get("ok")
        rid = r["requirementId"]
        req_agent.run_arch_tool(
            "req.amend", {"designMd": "方案v2"}, root=None, project=None, internal=True)
    finally:
        C.reset_conv(token)
    cards_rows = [m for m in store.ConversationsStore.messages(conv["id"])
                  if (m.get("meta") or {}).get("kind") == "specReady"]
    assert len(cards_rows) == 2   # 创建 1 + 修订 1, 各一次


def test_run_tool_with_progress_no_arg_repair(arch_env, monkeypatch):
    """cv-179 回归: 参数自动修复已拆除——工具失败必须如实返回,
    不得再引用已删除的 req_agent._is_repairable_error(漂移副本漏网)。"""
    import asyncio
    from topoone_app_architect.agent import orchestrator as orc
    sent = []

    async def fake_send(p):
        sent.append(p)

    calls = {"n": 0}

    def fake_run_arch_tool(name, args, root, project):
        calls["n"] += 1
        return {"error": "参数 missing_field 缺失(可修复形态)"}   # 旧逻辑会触发修复重试

    from topoone_app_architect.arch_routes import req_agent as _ra
    monkeypatch.setattr(_ra, "run_arch_tool", fake_run_arch_tool)
    res = asyncio.run(orc._run_tool_with_progress(fake_send, "rid-x", "req.propose",
                                                  {"title": "t"}, "", ""))
    assert calls["n"] == 1                    # 仅执行一次, 无修复重试
    assert res["ok"] is False and "缺失" in res["text"]
    kinds = [p.get("type") for p in sent]
    assert "arg_repair" not in kinds          # 修复状态帧不复存在
