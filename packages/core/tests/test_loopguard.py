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


# ── 错误/叙述签名 ────────────────────────────────────────────────────

def test_text_signature_triggers_on_repetition():
    g = LoopGuard()
    long_text = "编译仍然失败: undefined reference to ngx_http_healthcheck_handler " * 1
    verdict = (False, "")
    for _ in range(5):
        verdict = g.feed("text", text=long_text)
    assert verdict[0] and "签名重复 5 次" in verdict[1]


def test_text_signature_ignores_short_text():
    g = LoopGuard()
    for _ in range(10):
        loop, _ = g.feed("text", text="ok")
    assert not loop


def test_verdict_is_sticky():
    g = LoopGuard()
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
