"""LoopGuard 循环检测器 + 无进展看门狗(环节十一) 单元测试。

Run: cd <repo> && python -m pytest packages/core/tests/test_loopguard.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from topoone.plugins.runner.loopguard import LoopGuard, _norm_digest  # noqa: E402


# ── 文本归一 ─────────────────────────────────────────────────────────

def test_norm_digest_ignores_digits_and_case():
    assert _norm_digest("Connection refused (pid 46542) port 8888") == \
        _norm_digest("connection refused (pid 12) port 9999")


def test_norm_digest_empty():
    assert _norm_digest("") == ""
    assert _norm_digest("123 456") == ""


# ── 重复指纹(轮级) ───────────────────────────────────────────────────

def _round(g: LoopGuard, text: str, *tools: str):
    """喂一轮(工具+叙述), usage 收口并返回本轮判定。"""
    for t in tools:
        g.feed("tool", tool_name=t)
    g.feed("text", text=text)
    return g.feed("usage")


def test_repeat_fingerprint_triggers_on_three_identical_rounds():
    g = LoopGuard()
    assert not _round(g, "Let me check the config again",
                      "read_files", "run_commands")[0]
    assert not _round(g, "Let me check the config again",
                      "read_files", "run_commands")[0]
    loop, reason = _round(g, "Let me check the config again",
                          "read_files", "run_commands")
    assert loop and "3 轮" in reason


def test_repeat_fingerprint_not_triggered_on_varied_rounds():
    g = LoopGuard()
    narrations = ("reading the config file", "reading the source tree",
                  "reading the header files", "reading the makefile rules",
                  "checking the build output", "checking the link stage")
    for text in narrations:
        loop, _ = _round(g, text, "read_files")
        assert not loop


def test_fingerprint_requires_same_tool_sequence():
    g = LoopGuard()
    assert not _round(g, "checking", "read_files", "run_commands")[0]
    assert not _round(g, "checking", "run_commands", "read_files")[0]
    loop, _ = _round(g, "checking", "read_files", "run_commands")
    assert not loop


def test_silent_rounds_do_not_fingerprint():
    """静默轮(无叙述)不参与指纹——不同命令批次在工具名指纹下不可区分,
    误伤修复(cv-181): 连续纯 run_commands 零叙述 = 正常探索/编译批次。"""
    g = LoopGuard()
    for _ in range(8):
        for _ in range(2):
            g.feed("tool", tool_name="run_commands")
        loop, _ = g.feed("usage")
        assert not loop
    # 静默轮重置后, 带叙述的真循环仍可检出
    for _ in range(3):
        loop, _ = _round(g, "still trying the same fix", "run_commands")
    assert loop


def test_narrated_loop_interleaved_with_silent_not_fingerprinted():
    """交错静默轮 → 指纹不触发(静默重置, 按设计); 此类循环由
    错误签名检测器(同文本 ×5 非连续)兜底。"""
    g = LoopGuard()
    for _ in range(6):
        loop, _ = _round(g, "retrying the identical compile fix", "run_commands")
        assert not loop                     # 指纹永不触发
        g.feed("tool", tool_name="run_commands")
        g.feed("usage")
    # 错误签名检测器兜底: 同一叙述累计 5 次即判(显式收紧阈值)
    g2 = LoopGuard(signature_hits=5)
    verdict = (False, "")
    for _ in range(5):
        g2.feed("tool", tool_name="run_commands")
        verdict = g2.feed("text", text="retrying the identical compile fix")
        g2.feed("usage")
    # 真循环仍被检出: 叙述相同 → 指纹(第3轮)先于签名(第5次)触发, 任一即可
    assert verdict[0] and ("指纹轮" in verdict[1] or "签名重复" in verdict[1])


# ── 错误/叙述签名 ────────────────────────────────────────────────────

def test_text_signature_triggers_on_repetition():
    g = LoopGuard(signature_hits=5)      # 收紧参数显式传, 测触发语义
    long_text = "编译仍然失败: undefined reference to ngx_http_healthcheck_handler " * 1
    verdict = (False, "")
    for _ in range(5):
        verdict = g.feed("text", text=long_text)
    assert verdict[0] and "签名重复 5 次" in verdict[1]


def test_text_signature_default_tolerance():
    """默认阈值 ×8: 合法的重复状态话术(≤7 次)不触发——误伤排查。"""
    g = LoopGuard()
    long_ok = "编译通过，全部测试通过，验证结果符合预期，继续下一个里程碑的处理流程和报告输出约定"
    assert len(long_ok) >= 40              # 超过 min_sig_len(否则被长度过滤, 另有测试覆盖)
    verdict = (False, "")
    for _ in range(7):
        verdict = g.feed("text", text=long_ok)
        assert not verdict[0]
    verdict = g.feed("text", text=long_ok)
    assert verdict[0] and "签名重复 8 次" in verdict[1]


def test_text_signature_ignores_short_text():
    g = LoopGuard(signature_hits=5)
    for _ in range(10):
        loop, _ = g.feed("text", text="ok")
    assert not loop


def test_verdict_is_sticky():
    g = LoopGuard(signature_hits=5)
    long_text = "still failing with the same undefined reference error output"
    for _ in range(5):
        g.feed("text", text=long_text)
    loop, reason = g.feed("text", text="completely different narration now")
    assert loop and "签名重复" in reason


# ── 无进展看门狗(implement._progress_check) ──────────────────────────

@pytest.fixture()
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True, env=env)
    return repo


def _mk_job(tmp_path, wt):
    from topoone.plugins.runner.implement import ImplementJob
    return ImplementJob("job-t", str(tmp_path), str(wt), "HEAD", "task/t",
                        "instruction", auto_start=False)


def test_progress_check_exploration_not_armed(tmp_path, git_repo):
    job = _mk_job(tmp_path, git_repo)
    for _ in range(10):            # 纯探索(无文件变更): 永不武装不判定
        assert job._progress_check() == ""


def test_progress_check_stall_triggers_after_ticks(tmp_path, git_repo):
    from topoone.plugins.runner import implement as impl
    job = _mk_job(tmp_path, git_repo)
    (git_repo / "b.txt").write_text("work\n")   # 新文件(??) → 武装
    reasons = [job._progress_check() for _ in range(impl._PROGRESS_TICKS + 1)]
    assert reasons[0] == ""                       # 武装当轮不判
    assert all(r == "" for r in reasons[:-1])
    assert "无文件进展" in reasons[-1]


def test_progress_check_resets_on_tracked_edit(tmp_path, git_repo):
    """tracked 文件内容编辑 → 进度信号变化 → 计数归零(编辑-编译循环不误伤)。"""
    from topoone.plugins.runner import implement as impl
    job = _mk_job(tmp_path, git_repo)
    (git_repo / "a.txt").write_text("edit v1\n")   # tracked 修改( M)
    for _ in range(impl._PROGRESS_TICKS - 1):      # 顶格空转
        assert job._progress_check() == ""
    (git_repo / "a.txt").write_text("edit v2\n")   # 真编辑 → 内容哈希变
    assert job._progress_check() == ""
    for _ in range(impl._PROGRESS_TICKS - 1):
        assert job._progress_check() == ""
    assert job._progress_check() != ""             # 再次顶格才判


def test_reset_turn_guard_per_turn(tmp_path, git_repo):
    job = _mk_job(tmp_path, git_repo)
    job.loop_guard.feed("text", text="x" * 50)
    job._progress_armed = True
    job._progress_stall = 99
    job._reset_turn_guard()
    assert job._progress_armed is False
    assert job._progress_stall == 0
    loop, _ = job.loop_guard.feed("text", text="x" * 50)
    assert not loop                               # 新实例, 旧计数不带入


def test_progress_check_chat_role_exempt(tmp_path, git_repo):
    """2610 cv-12: chat 角色豁免——起始即脏 worktree 的只读排查回合不误杀
    (直通对话天然无文件进展; 活动停滞看门狗另行兜底)。"""
    job = _mk_job(tmp_path, git_repo)
    job.session_role = "chat"
    (git_repo / "b.txt").write_text("dirty\n")   # 起始即脏 → 若为 task 已武装
    for _ in range(15):                          # 顶格 + 余量: 恒不判
        assert job._progress_check() == ""


def test_progress_check_task_role_still_triggers(tmp_path, git_repo):
    """任务链(task)语义不变: 同样场景照旧判定循环。"""
    job = _mk_job(tmp_path, git_repo)
    assert job.session_role == "task"
    (git_repo / "b.txt").write_text("work\n")
    reasons = [job._progress_check() for _ in range(11)]
    assert "无文件进展" in reasons[-1]
