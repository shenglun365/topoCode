"""审计修复回归测试(P0/P1 项)。

A1: R3.2 图门禁不误伤 /执行 直通单卡路径(无 LLM 在环, 豁免);
A2: 基线再生纪律(再生脚本需 --confirm); 挡位字面量不散落补偿内核。

Run: cd <repo> && python -m pytest apps/architect/tests/test_audit_fixes.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store
from topoone_app_architect.store import states as ST


def _mk_ready_req(conv_id):
    req = {"id": store.next_id("RQ"), "kind": "user-story", "status": "ready",
           "title": "演示需求", "priority": "P1", "activeVer": 1,
           "specVersions": [{"ver": 1, "state": "confirmed",
                             "snapshot": {"title": "演示需求", "desc": "目标",
                                          "designMd": "方案: 改 A 模块",
                                          "allowedScope": ["src/a.py"],
                                          "forbiddenScope": [], "acceptance": ["编译通过"],
                                          "functionalScope": [], "assessmentSummary": "",
                                          "estMin": 10},
                             "source": {}, "reason": "t", "createdAt": 0}],
           "ownerConv": conv_id, "projectId": "", "updatedAt": 0, "createdAt": 0}
    store.RequirementsStore.create(req)
    store.ConversationsStore.update(conv_id, {"reqId": req["id"]})
    store.RequirementsStore.spec_confirm(req["id"])
    return req["id"]


def test_a1_t2_execute_single_card_not_gated(arch_env, monkeypatch, tmp_path):
    """A1 回归: T2 会话 /执行 单卡兜底(计划未触发)不被图门禁拒绝。"""
    import topoone_app_architect.agent.planning.task_plan as tp
    from topoone_app_architect.agent.perception.commands import run_execute
    monkeypatch.setattr(tp, "maybe_plan_and_propose", lambda *a, **k: None)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T",
                                            "analysisMode": "T2"})
    _mk_ready_req(conv["id"])
    conv = store.ConversationsStore.get(conv["id"])   # 重取(带 reqId)
    res = run_execute(conv, executor_id="")
    assert res.get("ok") is True, res
    assert res["task"].get("id") and res["task"]["status"] == ST.TASK_SAVED  # 默认保存


def test_a1_chat_propose_still_gated_at_t2(arch_env):
    """门禁仍适用于 chat task.propose 路径(有 LLM 可回炉)。"""
    from topoone_app_architect.agent.execution import exec_bridge as eb
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T",
                                            "analysisMode": "T2"})
    r = eb.propose_task(conv, "T", "无图指令(无回车)",
                        executor_hint={"executorType": "cline-sdk"})
    assert "error" in r and "逻辑图" in str(r.get("error"))
