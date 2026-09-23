"""版本对齐特征测试(cv-248) — 计划为其规约版本而生, 版本演进使计划过期。

cv-248 实证: 会话内规约修订到 v2(新目标)后 /执行 被旧计划「全部完成」提示
拦截——连续任务流断裂。修复: 计划行 specVer 记账; active ver 晚于记账版本
→ 计划过期, 视同无计划重建(与 cv-215 历史快照原则同构); 同版本才做诊断。

Run: cd <repo> && python -m pytest apps/architect/tests/test_task_plan_version.py -q
"""
import os
import sys
from types import SimpleNamespace

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.planning import task_plan as tp
from topoone_app_architect.arch_routes import store

import pytest


@pytest.fixture()
def arch(arch_env):
    return arch_env


def _mk_req(rid="RQ-V1", active_ver=1):
    store.RequirementsStore.create({"id": rid, "kind": "user-story",
                                    "status": "ready", "title": "T",
                                    "activeVer": active_ver})
    return rid


def _v1_done_plan(conv_id):
    """v1 全 done 计划(taskId 指向真实任务行——cv-248 I2: 非空 taskId 必有行)。"""
    t1 = store.TasksStore.create({"conversationId": conv_id, "title": "S1",
                                  "instruction": "x", "status": "done",
                                  "executorType": "cline-sdk"})
    t2 = store.TasksStore.create({"conversationId": conv_id, "title": "S2",
                                  "instruction": "y", "status": "done",
                                  "executorType": "cline-sdk"})
    return [{"seq": 1, "title": "S1", "instruction": "x", "taskId": t1["id"],
             "status": "done"},
            {"seq": 2, "title": "S2", "instruction": "y", "taskId": t2["id"],
             "status": "done"}]


def _patch_rebuild(monkeypatch, steps=None, proposed=None):
    """重建路径外部依赖收口: 拆步/落卡/下发全部 mock(纯逻辑测版本判别)。"""
    monkeypatch.setattr(
        "topoone_app_architect.agent.governance.gears.resolve_gear",
        lambda mode, cfg: SimpleNamespace(pre_split="linear",
                                          depends_source="linear", tier="T2"))
    monkeypatch.setattr(tp, "split_tasks_llm",
                        lambda req_text, policy=None: steps
                        or [{"title": "N1", "instruction": "a"},
                            {"title": "N2", "instruction": "b"}])
    monkeypatch.setattr(tp, "_land_plan_card", lambda conv, rid, plan: None)
    proposed = proposed if proposed is not None else []
    monkeypatch.setattr(tp, "propose_plan_step",
                        lambda conv, rid, idx, executor_hint=None:
                        proposed.append((rid, idx))
                        or {"ok": True, "task": {"id": "task-new"}})
    return proposed


# ── 版本对齐: 过期重建 ────────────────────────────────────────────────

def test_stale_plan_rebuild_on_spec_version_bump(arch, monkeypatch):
    """v1 计划全 done(存量行, 无 specVer 记账) + active ver=2 → 重建非拒绝。"""
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = _mk_req("RQ-STALE", active_ver=2)
    tp.save_plan(rid, _v1_done_plan(conv["id"]))
    proposed = _patch_rebuild(monkeypatch)

    out = tp.maybe_plan_and_propose(conv, rid, "新目标文本", "T", "instr",
                                    spec_ver=2)
    assert out.get("ok") is True
    assert "重建" in str(out.get("receipt") or "")
    plan = tp.get_plan(rid)
    assert len(plan) == 2
    assert all(int(s.get("specVer") or 0) == 2 for s in plan)   # 新记账
    assert proposed == [(rid, 0)]                                # 第一步已下发


def test_same_version_completed_plan_still_diagnosed(arch):
    """同版本(v1)全 done → 诊断提示保留(「先说明调整」语义仍正确)。"""
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = _mk_req("RQ-SAME", active_ver=1)
    tp.save_plan(rid, _v1_done_plan(conv["id"]))

    out = tp.maybe_plan_and_propose(conv, rid, "x", "T", "i", spec_ver=1)
    assert out.get("ok") is False
    assert "全部完成" in str(out.get("receipt") or "")


def test_new_plan_rows_record_specver(arch, monkeypatch):
    """无计划新建: 行级 specVer 记账注入(normalize 后, 不依赖行构造)。"""
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = _mk_req("RQ-NEW", active_ver=3)
    _patch_rebuild(monkeypatch)

    out = tp.maybe_plan_and_propose(conv, rid, "x", "T", "i", spec_ver=3)
    assert out.get("ok") is True
    assert all(int(s.get("specVer") or 0) == 3 for s in tp.get_plan(rid))


def test_legacy_rows_default_ver1_not_stale(arch, monkeypatch):
    """存量行(无 specVer)默认 v1: spec_ver=1 时不重建(回归——不误判过期)。"""
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = _mk_req("RQ-LEG", active_ver=1)
    tp.save_plan(rid, _v1_done_plan(conv["id"]))
    rebuilt = []
    _patch_rebuild(monkeypatch)
    real_split = tp.split_tasks_llm

    def _spy(req_text, policy=None):
        rebuilt.append(1)
        return real_split(req_text, policy=policy)
    monkeypatch.setattr(tp, "split_tasks_llm", _spy)

    out = tp.maybe_plan_and_propose(conv, rid, "x", "T", "i", spec_ver=1)
    assert out.get("ok") is False          # 诊断, 非重建
    assert rebuilt == []


# ── 渲染面守门: 调用方必须携带版本(记账单源, 防裸调回落) ──────────────

def test_run_execute_passes_spec_ver():
    import re
    src = os.path.join(_repo, "apps/architect/topoone_app_architect",
                       "agent/perception/commands.py")
    code = open(src, encoding="utf-8").read()
    pattern = r'maybe_plan_and_propose\([\s\S]*?spec_ver=int\(active\.get\("ver"'
    assert re.search(pattern, code), "run_execute 调用未传 spec_ver(版本对齐记账缺失)"
