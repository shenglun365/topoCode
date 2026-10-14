"""任务指令「运行时身份」段回归（A3/postmortem 防误验）。

runner 作业在隔离 worktree 执行, 用户主目录的服务/端口与 agent 无关——
指令必须显式注入分支/主仓事实, 杜绝「验证了替身服务器」类事故
（dsh postmortem 0003 同源教训）。

Run: cd <repo> && python -m pytest apps/architect/tests/test_task_instruction_runtime_identity.py -q
"""
from topoone_app_architect.agent.planning.task_plan import assemble_task_instruction


def test_runtime_identity_injected():
    """隔离形态(原 A3 场景): 分支/主仓事实 + 防误验红线。"""
    text = assemble_task_instruction(
        {"title": "T", "instruction": "改一下登录页"},
        runtime={"branch": "exec/ab12cd34", "root": "/home/u/proj",
                 "workspace": "worktree"})
    assert "## 运行时身份" in text
    assert "`exec/ab12cd34`" in text
    assert "/home/u/proj" in text
    assert "HTTP 探测 200" in text          # 防误验红线
    assert "任务上下文" in text and "改一下登录页" in text   # 正文不受影响


def test_runtime_identity_inplace():
    """cv-205 融合形态: 事实相反——修改直接生效, 谨慎对待用户环境。"""
    text = assemble_task_instruction(
        {"title": "T", "instruction": "改一下登录页"},
        runtime={"root": "/home/u/proj", "workspace": "inplace"})
    assert "融合执行" in text and "没有隔离副本" in text
    assert "不在**主目录工作" not in text
    assert "HTTP 探测 200" not in text      # 该红线仅属隔离形态


def test_no_runtime_keeps_backward_compat():
    """未传 runtime（旧调用方/测试）→ 不产出身份段，其余段落不变。"""
    text = assemble_task_instruction({"title": "T", "instruction": "做点事"})
    assert "运行时身份" not in text
    assert "## 工作环境" in text and "## 交付定义(DoD)" in text


def test_runtime_partial_branch_only():
    """仅知分支（root 未知, 隔离形态）→ 身份段只含分支事实, 不含主仓行。"""
    text = assemble_task_instruction({"title": "T", "instruction": "x"},
                                     runtime={"branch": "exec/r1",
                                              "workspace": "worktree"})
    assert "任务分支" in text
    assert "主仓位置" not in text


def test_cap_note_wired_into_instruction():
    """M1 接线: cap_note 随指令告知 subagent(2610 挡位退役——封顶来源已退役,
    手构策略行保组装器字段覆盖)。"""
    import dataclasses
    from topoone_app_architect.agent.governance.gears import resolve_gear
    policy = dataclasses.replace(
        resolve_gear("strict", {}),
        tier="T2", cap_note="指令跟随探针未过——封顶 T2(结构化 probeFlags)")
    assert policy.cap_note
    text = assemble_task_instruction({"title": "T", "instruction": "做"},
                                     policy=policy,
                                     runtime={"branch": "exec/c1", "workspace": "worktree"})
    assert "运行时身份" in text and "实测能力边界降档" in text


def test_no_cap_note_no_section():
    """未封顶 → 指令不含降档提示(负空间纪律)。"""
    from topoone_app_architect.agent.governance.gears import default_policy
    text = assemble_task_instruction({"title": "T", "instruction": "做"},
                                     policy=default_policy())
    assert "实测能力边界降档" not in text
