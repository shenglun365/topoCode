"""V1 程序化验收门禁回归（批次 4; 设计蓝本 docs/runner-verify-gate-design.md）。

Run: cd <repo> && python -m pytest packages/core/tests/test_verify_gate.py -q
"""
import asyncio
import os
import subprocess

from topoone.plugins.runner import verify as vf  # noqa: E402
from topoone.plugins.runner.turn_adapter import TurnAdapter, TurnOutcome  # noqa: E402
from topoone.plugins.runner.implement import ImplementJob  # noqa: E402


def _mkfile(wt, rel, content):
    p = os.path.join(wt, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(rel) else None
    open(p, "w", encoding="utf-8").write(content)


# ── L1 发现链 ──────────────────────────────────────────────────────

def test_discovery_p0_config_wins(tmp_path):
    """P0 显式配置最高权威——命中即停，不再扫约定。"""
    _mkfile(tmp_path, "package.json",
            '{"scripts": {"test": "echo pkg-test"}}')
    plan = vf.discover_verify(str(tmp_path), {"test": "python -m pytest -q"})
    assert plan["test"] == {"cmd": "python -m pytest -q", "source": "config"}
    assert plan["level"] == ""


def test_discovery_p2_conventions(tmp_path):
    _mkfile(tmp_path, "package.json", '{"scripts": {"test": "echo t"}}')
    plan = vf.discover_verify(str(tmp_path), None)
    assert plan["test"] == {"cmd": "npm run test", "source": "convention"}


def test_discovery_p2_pytest_convention(tmp_path):
    _mkfile(tmp_path, "pyproject.toml", "[tool.pytest]\naddopts = '-q'\n")
    plan = vf.discover_verify(str(tmp_path), None)
    assert plan["test"]["cmd"] == "python -m pytest -q"
    assert plan["test"]["source"] == "convention"


def test_discovery_p1_makefile(tmp_path):
    _mkfile(tmp_path, "Makefile", "all:\n\techo all\n\ntest:\n\tpython -m pytest -q\n")
    plan = vf.discover_verify(str(tmp_path), None)
    assert plan["test"]["source"] == "ci"
    assert "pytest" in plan["test"]["cmd"]


def test_discovery_p3_heuristic(tmp_path):
    _mkfile(tmp_path, "test_ok.py", "def test_ok():\n    assert True\n")
    plan = vf.discover_verify(str(tmp_path), None)
    assert plan["test"] == {"cmd": "python -m pytest -q", "source": "heuristic"}


def test_discovery_nothing_level_c(tmp_path):
    plan = vf.discover_verify(str(tmp_path), None)
    assert plan["level"] == "C" and plan["reason"] == "NO_VERIFY_CONFIG"


# ── L2 执行 + 级别判定 ─────────────────────────────────────────────

def test_run_pass_and_fail(tmp_path):
    ok = vf.verify_and_judge(str(tmp_path), {"test": "python -c \"print('ok')\""}.copy(),
                             ["src/a.py"])
    assert ok["overall"] == "B" and ok["test"]["verdict"] == "PASS"
    bad = vf.verify_and_judge(str(tmp_path),
                              {"test": "python -c \"raise SystemExit(3)\""}, ["a.py"])
    assert bad["test"]["verdict"] == "FAIL" and bad["test"]["exitCode"] == 3
    assert bad["overall"] == "B"


def test_whitelist_rejection_downgrades_to_c(tmp_path):
    """破坏性命令 → UNVERIFIABLE(WHITELIST_REJECTED) → 整体 C(宁可不验不可假验)。"""
    m = vf.verify_and_judge(str(tmp_path), {"test": "rm -rf /"}, ["a.py"])
    assert m["overall"] == "C" and m["reason"] == "WHITELIST_REJECTED"


def test_timeout_reason(tmp_path):
    m = vf.verify_and_judge(str(tmp_path),
                            {"test": "python -c \"import time; time.sleep(5)\"",
                             "timeoutMul": 0.005}, ["a.py"])
    assert m["test"]["verdict"] == "FAIL" and m["test"]["reason"] == "TIMEOUT"


def test_pure_docs_level_d(tmp_path):
    m = vf.verify_and_judge(str(tmp_path), {"test": "python -c \"print('x')\""},
                            ["README.md", "docs/note.txt"])
    assert m["overall"] == "D" and m["reason"] == "PURE_DOCS"


def test_summary_shapes(tmp_path):
    m = vf.verify_and_judge(str(tmp_path), {"test": "python -c \"print('ok')\""}, ["a.py"])
    text = vf.matrix_summary(m)
    assert "验收" in text and "PASS" in text


# ── done 挂钩集成（真实 git worktree）───────────────────────────────

def _git(*a, cwd, check=True):
    return subprocess.run(["git", *a], cwd=cwd, check=check,
                          capture_output=True, text=True)


def test_done_branch_emits_verify_event(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    (repo / "base.txt").write_text("base\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "base", cwd=repo)
    _git("worktree", "add", "-b", "exec/t", str(tmp_path / "wt"), cwd=repo)
    wt = str(tmp_path / "wt")
    _mkfile(wt, "test_ok.py", "def test_ok():\n    assert 1 + 1 == 2\n")
    _git("add", "-A", cwd=wt)
    _git("commit", "-qm", "feat", cwd=wt)

    class _Adapter(TurnAdapter):
        executor_id = "fake"

        async def start_session(self, job):
            job.session_id = "s1"

        async def run_turn(self, job, text):
            return TurnOutcome(output=text, changed_files=[])

        async def probe(self, job):
            raise NotImplementedError

    j = ImplementJob("j-vg", root=str(repo), wt=wt, base="HEAD", branch="exec/t",
                     instruction="do", adapter=_Adapter(),
                     verify_config={"test": "python -m pytest -q test_ok.py",
                                    "timeoutMul": 0.05})
    j.status = "running"
    asyncio.run(j._run_turn("完成 [[IMPLEMENT_DONE]]"))
    assert j.status == "done"
    verify_events = [e for e in j.events if e["kind"] == "verify"]
    assert verify_events, "done 后缺 verify 事件"
    ev = verify_events[-1]
    assert ev["overall"] == "B" and ev["test"]["verdict"] == "PASS"
    assert "PASS" in ev["text"]
