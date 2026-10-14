"""A2 最小 DAG 回归(task_graph 纯函数 + task_plan 就绪下发/fail-fast)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_task_graph.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect.agent.planning import task_graph as tg  # noqa: E402


def _plan(*rows):
    """rows: (seq, status, deps) → taskPlan 形状。"""
    return [{"seq": s, "title": f"步骤{s}", "instruction": "x", "taskId": "",
             "status": st, "depends": list(deps)} for s, st, deps in rows]


# ── 校验 ────────────────────────────────────────────────────────────

def test_validate_ok_graphs():
    assert tg.validate_graph(_plan((1, "pending", ()), (2, "pending", (1,))))["ok"]
    assert tg.validate_graph(_plan((1, "pending", ()), (2, "pending", ()),
                                   (3, "pending", (1, 2))))["ok"]
    assert tg.validate_graph([])["ok"]


def test_validate_rejects_self_and_missing_and_dup():
    g = tg.validate_graph(_plan((1, "pending", (1,))))
    assert not g["ok"] and any("自依赖" in e for e in g["errors"])
    g2 = tg.validate_graph([{"seq": 1, "title": "x", "instruction": "",
                             "status": "pending", "depends": [9]}])
    assert not g2["ok"] and any("悬空" in e for e in g2["errors"])
    dup = _plan((1, "pending", ()), (1, "pending", ()))
    g3 = tg.validate_graph(dup)
    assert not g3["ok"] and any("重复 seq" in e for e in g3["errors"])


def test_validate_rejects_cycle():
    g = tg.validate_graph(_plan((1, "pending", (2,)), (2, "pending", (1,))))
    assert not g["ok"] and any("依赖环" in e for e in g["errors"])


def test_linear_depends_chain_and_normalize():
    out = tg.linear_depends(_plan((1, "pending", ()), (2, "pending", ()),
                                  (3, "pending", ())))
    assert [s["depends"] for s in out] == [[], [1], [2]]
    # 非法依赖清洗(悬空剔除)
    norm = tg.normalize_plan([{"seq": 1, "status": "pending", "depends": [5, "x"]}])
    assert norm[0]["depends"] == []


# ── 就绪/fail-fast ──────────────────────────────────────────────────

def test_ready_requires_deps_done():
    plan = _plan((1, "done", ()), (2, "pending", (1,)), (3, "pending", ()),
                 (4, "pending", (2, 3)))
    assert set(tg.ready_indices(plan)) == {1, 2}   # 菱形展开: 2/3 均就绪(0 基)
    plan2 = _plan((1, "waiting_input", ()), (2, "pending", (1,)))
    assert tg.ready_indices(plan2) == []           # waiting_input 不解锁后继


def test_blocked_summary_fail_fast():
    plan = _plan((1, "failed", ()), (2, "pending", (1,)), (3, "pending", (1,)))
    text = tg.blocked_summary(plan)
    assert "失败步骤: #1" in text and "阻塞步骤: #2, #3" in text


# ── 产出按挡(depends_source) ────────────────────────────────────────

def test_split_llm_declares_depends_for_llm_source(tmp_path, monkeypatch):
    """llm 挡: LLM 声明 depends 保留; 校验失败 → 降线性(在 plan 装配处)。"""
    from topoone_app_architect.agent.planning import task_plan as tp

    def fake_llm_sync(msgs, **kw):
        return {"output": {"tasks": [
            {"title": "A", "instruction": "a"},
            {"title": "B", "instruction": "b", "depends": [1]},
            {"title": "C", "instruction": "c", "depends": [1]},
        ]}}

    monkeypatch.setattr("topoone_app_architect.agent.tools.req_agent.llm_sync",
                        fake_llm_sync)
    steps = tp.split_tasks_llm("需求")
    assert steps[1]["depends"] == [1] and steps[2]["depends"] == [1]


def test_ready_based_dispatch_end_to_end(tmp_path, monkeypatch):
    """菱形依赖: 完成 1 → 仅就绪链下发(2/3 竞争就绪取先); 4 保持阻塞。"""
    from topoone_app_architect.agent.planning import task_graph as tg
    plan = _plan((1, "done", ()), (2, "pending", (1,)), (3, "pending", (1,)),
                 (4, "pending", (2, 3)))
    ready = tg.ready_indices(plan)
    assert len(ready) == 2 and set(ready) == {1, 2}
    # 完成 2、3 → 4 就绪
    plan[1]["status"] = plan[2]["status"] = "done"
    assert tg.ready_indices(plan) == [3]
