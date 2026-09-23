"""写卡执法点授权矩阵(架构护栏, cv-246 架构裁决 2026-09-23)。

裁决「回合权力由 GU 决策表单源授予; 回合内一切可执行产物(原生调用/
正文载荷)统一在单一执法点验权; 载荷归属由内容 schema 单源判别; 卡即
回执单源」。本测试把该原则固化为可回归约束——任何新写卡通道绕过
验权关卡都会在此被拦下(与 R1 分层测试同思路的架构级护栏)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_write_surface.py -q
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.planning.req_spec import (
    extract_proposal_fence, strip_proposal_fence)
from topoone_app_architect.agent.planning.task_plan import (
    extract_task_fence, strip_task_fence)

SPEC_JSON = ('```json\n{"title": "项目初始化", "requirementMd": "从零初始化开发环境",'
             ' "allowedScopeMd": "根目录", "acceptanceMd": "pnpm install 成功"}\n```')
TASK_JSON = ('```json\n{"title": "任务K", "instruction": "实现批量导出并输出清单文件"}\n```')
TASK_FENCE = '```task\n{"title": "任务T", "instruction": "做事"}\n```'
DIAG_JSON = '```json\n{"type": "flow", "version": 1, "nodes": [], "edges": []}\n```'


class _IO:
    """_post_turn_land 的 io 桩: send 事件收集。"""

    def __init__(self):
        self.events = []

        async def send(ev):
            self.events.append(ev)
        self.send = send


def _land(content, allowed, conv_id="conv-t"):
    """跑一次回合后代落通道, 返回 (final_content, tools_used, tool_errors, io)。"""
    from topoone_app_architect.agent.turns.chat import _post_turn_land
    from topoone_app_architect.arch_routes import ctx as _ctx, store
    store.ConversationsStore.create({"id": conv_id, "kind": "generic",
                                     "title": "t"})
    io = _IO()

    def _run():
        token = _ctx.set_conv(conv_id)
        try:
            # asyncio.run 自建自毁 loop(测试全量运行时主线程 loop 可能被
            # 其它套件关闭, get_event_loop 不可靠)
            return asyncio.run(_post_turn_land(
                io, conv_id, [], None, None, None, None, {},
                set(), {}, content, None, allowed_tools=allowed))
        finally:
            _ctx.reset_conv(token)

    fc, _conv, used, errs, _landed = _run()
    return fc, used, errs, io


# ── 载荷归属: 内容 schema 单源判别 ────────────────────────────────────

def test_spec_payload_owned_by_req_domain():
    """规约 schema 载荷 → req.propose 域认领(不限围栏形态, cv-246 实证)。"""
    assert extract_proposal_fence(SPEC_JSON) is not None
    # 任务域排斥(规约字段不再折叠成 instruction——历史行为随「需求卡→确认
    # →任务」标准流程退役, cv-150[3] 旧语义授权重写)
    assert extract_task_fence(SPEC_JSON) is None


def test_task_payload_owned_by_task_domain():
    assert extract_task_fence(TASK_JSON) is not None
    assert extract_task_fence(TASK_FENCE) is not None
    assert extract_proposal_fence(TASK_JSON) is None
    assert extract_proposal_fence(TASK_FENCE) is None


def test_diagram_ir_unclaimed_by_both_domains():
    assert extract_task_fence(DIAG_JSON) is None
    assert extract_proposal_fence(DIAG_JSON) is None


def test_strip_is_scope_safe():
    """剥离与认领同源: 只剥规约载荷围栏, 任务/图 json 不误伤。"""
    mixed = f"前言\n{SPEC_JSON}\n中\n{TASK_JSON}"
    out = strip_proposal_fence(mixed)
    assert "项目初始化" not in out and "任务K" in out
    out2 = strip_task_fence(f"前置\n{TASK_FENCE}\n后记")
    assert "任务T" not in out2 and out2.startswith("前置")


# ── 执法点统一: 围栏代落受 GU 授权面约束 ──────────────────────────────

def test_pure_read_surface_never_lands_cards(arch_env):
    """纯读面(allowed_tools 不含写工具)不代落——载荷按模型原文诚实保留
    +rejected 遥测(cv-242「落卡权=确定性意图命中专属」的执法闭环)。"""
    from topoone_app_architect.arch_routes import store
    fc, used, errs, _io = _land(f"说明\n{SPEC_JSON}", allowed=set())
    assert used == set()                       # 未代落
    assert "requirementMd" in fc               # 载荷原文保留(不吞不改)
    assert "已从上文载荷" not in fc and "落库失败" not in fc
    assert store.RequirementsStore.all() == []  # 零卡
    assert store.TasksStore.of_conv("conv-t") == []


def test_authorized_surface_lands_and_strips(arch_env):
    """授权面代落: 需求卡落库 + 载荷正文剥离 + 零合成通知(卡即回执)。"""
    from topoone_app_architect.arch_routes import store
    fc, used, errs, _io = _land(f"按确认立卡。\n{SPEC_JSON}",
                                allowed={"req.propose", "req.amend"})
    assert used == {"req.propose"} and not errs
    assert "requirementMd" not in fc           # 载荷剥离
    assert "已从上文载荷" not in fc and "已从提案围栏" not in fc
    reqs = store.RequirementsStore.all()
    assert len(reqs) == 1 and reqs[0]["title"] == "项目初始化"


def test_task_payload_lands_task_card(arch_env):
    """任务载荷 → task.propose(规约排斥后归属唯一)。"""
    from topoone_app_architect.arch_routes import store
    fc, used, errs, _io = _land(f"建卡。\n{TASK_FENCE}",
                                allowed={"task.propose"})
    assert used == {"task.propose"} and not errs
    assert "任务T" not in fc                   # 显式围栏剥离
    tasks = store.TasksStore.of_conv("conv-t")
    assert len(tasks) == 1 and tasks[0]["title"] == "任务T"


def test_spec_payload_never_becomes_task_card(arch_env):
    """schema 归属终审: 任务面授权下规约载荷不得落成任务卡(cv-246 事故面)。"""
    from topoone_app_architect.arch_routes import store
    fc, used, _errs, _io = _land(SPEC_JSON, allowed={"task.propose"})
    assert used == set() and store.TasksStore.of_conv("conv-t") == []


# ── 通道冻结: 围栏提取函数调用点白名单(防新旁路) ──────────────────────

def test_fence_extractor_call_sites_frozen():
    """围栏提取/代落唯一消费点 = chat._post_turn_land(R1 冻结清单同思路)。
    新增调用点必须先过架构评审(否则即旁路)。"""
    import re
    root = os.path.join(_repo, "apps", "architect", "topoone_app_architect")
    allowed = {"agent/turns/chat.py",              # 唯一消费点(执法点)
               "agent/planning/task_plan.py",      # 定义处
               "agent/planning/req_spec.py"}       # 定义处
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            src = open(full, encoding="utf-8").read()
            calls = [ln for ln in src.splitlines()
                     if re.search(r"extract_(proposal|task)_fence\(", ln)
                     and not ln.strip().startswith("def ")
                     and "import" not in ln]
            if calls and rel not in allowed:
                raise AssertionError(
                    f"围栏提取函数出现于白名单外消费点: {rel}——"
                    "围栏代落必须走 chat._post_turn_land 统一执法点(cv-246)")


# ── 澄清答复消解(cv-246 主链) ────────────────────────────────────────

def test_clarify_reply_gets_write_surface():
    """澄清在飞(clarify_pending) + 无行动信号答复 → 续答面(req.propose 可达)。"""
    from topoone_app_architect.agent.governance.flow_policy import (
        DEFAULT_FLOW_POLICY)
    from topoone_app_architect.agent.turns.goal import (
        build_goal_profile, resolve_goal_directive)
    focus = {"top": {"kind": "clarify_pending"}, "phase": ""}
    p = build_goal_profile("全部确认", focus=focus)
    r = resolve_goal_directive(p, DEFAULT_FLOW_POLICY)
    assert p["kind"] == "continuation" and r["tools"] == ["req.amend", "req.propose"]


def test_clarify_frame_pure_read_without_focus():
    """无澄清帧 → 「全部确认」仍纯读(cv-242 纪律不因新帧放宽)。"""
    from topoone_app_architect.agent.governance.flow_policy import (
        DEFAULT_FLOW_POLICY)
    from topoone_app_architect.agent.turns.goal import (
        build_goal_profile, resolve_goal_directive)
    p = build_goal_profile("全部确认")
    r = resolve_goal_directive(p, DEFAULT_FLOW_POLICY)
    assert p["kind"] == "inquiry" and r["action"] == "answer" and r["tools"] == []


def test_clarify_frame_takes_priority_over_vocab():
    """cv-248 裁决重写: 澄清答复天然含主题词(答复内容=澄清主题), 词表重判
    会把答复误判为新澄清/候选菜单 → 澄清帧优先于 strategy/exec 判定;
    command/help 仍在其前(显式意图优先)。"""
    from topoone_app_architect.agent.turns.goal import build_goal_profile
    focus = {"top": {"kind": "clarify_pending"}, "phase": ""}
    p = build_goal_profile("环境搭建用什么包管理器", focus=focus)
    assert p["kind"] == "continuation" and "focus-clarify" in p["sources"]
    # help 仍优先于澄清消解
    p2 = build_goal_profile("怎么配置执行器？", focus=focus)
    assert p2["kind"] == "help"


def test_focus_clarify_frame_derivation():
    """帧源: 回合产物 meta.guAction 派生(零写点); 非澄清动作不产帧。"""
    from topoone_app_architect.agent.governance.focus import frames_from_entities
    now = 1_800_000_000_000
    fs = frames_from_entities({}, [], None, [],
                              pending={"action": "clarify-first", "since": now})
    assert [f["kind"] for f in fs] == ["clarify_pending"]
    assert frames_from_entities({}, [], None, [],
                                pending={"action": "answer", "since": now}) == []
    assert frames_from_entities({}, [], None, []) == []


# ── cv-248 复放: spec-apply 上下文/幂等/澄清帧遮蔽 ────────────────────

def test_clarify_frame_not_shadowed_by_card_messages(arch_env):
    """choices 卡等落流产物不得遮蔽回合产物的 guAction(cv-248: 围栏源问询卡
    后落流 → 澄清帧丢失 → 答复误判新澄清 → 面缺 req.propose → 代落被拒)。"""
    from topoone_app_architect.agent.governance.focus import _pending_action
    from topoone_app_architect.arch_routes import store
    store.ConversationsStore.create({"id": "conv-sh", "kind": "generic",
                                     "title": "t"})
    now = 1_800_000_000_000
    store.ConversationsStore.append_message({
        "id": "m1", "conversationId": "conv-sh", "role": "assistant",
        "time": now - 5000, "content": "请确认",
        "meta": {"guAction": "clarify-first"}})
    # 卡片消息后落流(无 guAction, 有 kind)——不得遮蔽
    store.ConversationsStore.append_message({
        "id": "m2", "conversationId": "conv-sh", "role": "assistant",
        "time": now - 3000, "content": "问询卡",
        "meta": {"kind": "choices", "title": "x", "groups": []}})
    pend = _pending_action(store, "conv-sh", now)
    assert pend.get("action") == "clarify-first"
    # 答复轮 GU: 续答面(req.propose 可达)
    from topoone_app_architect.agent.governance.flow_policy import (
        DEFAULT_FLOW_POLICY)
    from topoone_app_architect.agent.turns.goal import (
        build_goal_profile, resolve_goal_directive)
    focus = {"top": {"kind": "clarify_pending"}, "phase": ""}
    p = build_goal_profile("技术栈版本确认: Vue3 + Vite，Monorepo", focus=focus)
    r = resolve_goal_directive(p, DEFAULT_FLOW_POLICY)
    assert r["action"] == "continue" and "req.propose" in r["tools"]


def test_spec_apply_lands_card_binds_and_idempotent(arch_env):
    """spec-apply 三缺陷终审(cv-248): ①ctx 设置→specReady 卡落流+
    conv.reqId 回写 ②载荷指纹幂等(重复提交不再新建)。"""
    import asyncio
    from topoone_app_architect.arch_routes import sessions as _sess, store
    from fastapi import Request

    conv = store.ConversationsStore.create({"id": "conv-sa", "kind": "generic",
                                            "title": "t"})

    def _post():
        async def _body():
            return {"payload": {
                "title": "cv-248 规约", "requirementMd": "从零初始化开发环境xx",
                "allowedScopeMd": "根目录", "acceptanceMd": "安装成功"}}
        req = SimpleNamespace(json=_body)
        return asyncio.run(_sess.session_spec_apply("conv-sa", req))

    r1 = (_post() or {}).get("data") or {}
    assert r1.get("ok") and not r1.get("idempotent")
    rid1 = r1.get("requirementId") or r1.get("reqId")
    assert rid1
    # ① specReady 卡落流
    cards = [m for m in store.ConversationsStore.messages("conv-sa")
             if (m.get("meta") or {}).get("kind") == "specReady"]
    assert cards, "spec-apply 必须落 specReady 卡(一键建卡执行入口)"
    # ① conv.reqId 回写
    assert (store.ConversationsStore.get("conv-sa") or {}).get("reqId") == rid1
    # ② 同载荷重复提交 → 幂等跳过(不再新建)
    r2 = (_post() or {}).get("data") or {}
    assert r2.get("ok") and r2.get("idempotent")
    rows = [r for r in store.RequirementsStore.all()
            if (r.get("title") or "") == "cv-248 规约"]
    assert len(rows) == 1, f"重复提交不得新建需求, 实落 {len(rows)} 条"
