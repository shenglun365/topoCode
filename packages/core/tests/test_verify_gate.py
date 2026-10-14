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


# ── V2 尾量: jest/vitest 结构化适配器 ──────────────────────────────

def test_discovery_p2_node_adapter_attached(tmp_path):
    """scripts.test 命中 + 依赖含 vitest → npm run test 携 adapter 标记。"""
    _mkfile(tmp_path, "package.json",
            '{"scripts": {"test": "vitest run"},'
            ' "devDependencies": {"vitest": "^1.0"}}')
    plan = vf.discover_verify(str(tmp_path), None)
    assert plan["test"]["cmd"] == "npm run test"
    assert plan["test"]["adapter"] == "vitest"


def test_discovery_p0_jest_cmd_infers_adapter(tmp_path):
    plan = vf.discover_verify(str(tmp_path),
                              {"test": "npx jest --coverage"})
    assert plan["test"]["adapter"] == "jest"


def test_augment_jest_npm_separator():
    out = vf.augment_command("test", "npm run test", "/r", adapter="jest")
    assert out == "npm run test -- --json --outputFile=/r/jest.json"
    out2 = vf.augment_command("test", "npx jest", "/r", adapter="jest")
    assert out2 == "npx jest --json --outputFile=/r/jest.json"
    # 幂等: 已带 outputFile 不改写
    assert vf.augment_command("test", out, "/r", adapter="jest") == out


def test_augment_vitest_reporter_flags():
    out = vf.augment_command("test", "npm run test", "/r", adapter="vitest")
    assert out == ("npm run test -- --reporter=json "
                   "--outputFile=/r/jest.json")
    out2 = vf.augment_command("test", "vitest run", "/r")
    assert "vitest" in out2 and "--reporter=json" in out2 \
        and "--outputFile=/r/jest.json" in out2


def test_parse_jest_json_report(tmp_path):
    rep = tmp_path / "jest.json"
    rep.write_text(
        '{"numTotalTests": 3, "testResults": [{"assertionResults": ['
        '{"fullName": "sum works", "status": "passed", "duration": 2},'
        '{"fullName": "sum fails", "status": "failed", "duration": 1,'
        ' "failureMessages": ["expect(1).toBe(2)"]},'
        '{"fullName": "skipped one", "status": "pending", "duration": 0}'
        ']}]}', encoding="utf-8")
    parsed = vf._parse_jest_json(str(rep))
    assert parsed is not None
    assert parsed["summary"] == {"total": 3, "passed": 1,
                                 "failed": 1, "skipped": 1}
    failed = [r for r in parsed["perTest"] if r["status"] == "failed"]
    assert failed[0]["name"] == "sum fails" and "toBe(2)" in failed[0]["message"]


def test_attach_structured_jest_report_flips_verdict(tmp_path):
    """退出码 0 但 jest 报告有失败 → 以报告为准(防假通过)。"""
    import json as _json
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "jest.json").write_text(_json.dumps({
        "testResults": [{"assertionResults": [
            {"fullName": "a", "status": "passed"},
            {"fullName": "b", "status": "failed",
             "failureMessages": ["x"]},
        ]}]}, ensure_ascii=False), encoding="utf-8")
    result = vf._stage_result("npm run test", "convention", "test",
                              "PASS", exit_code=0)
    out = vf._attach_structured(result, "test", "npm run test",
                                str(report_dir), "")
    assert out["structured"] is True
    assert out["verdict"] == "FAIL" and out["reason"] == "TEST_FAILED"
    assert out["summary"]["failed"] == 1



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
    assert ev["overall"] == "A"                          # V2: junitxml 结构化 → A 档
    assert ev["test"]["structured"] is True
    assert ev["test"]["verdict"] == "PASS"
    assert ev["test"]["summary"]["passed"] >= 1
    assert "PASS" in ev["text"]


# ── V4 修复回注 + V5 DONE 诚实化 ────────────────────────────────────

def test_done_but_verify_fail_repairs_then_escapes(tmp_path):
    """DONE 但实测 FAIL: L2 → 自动修复回注(转 running+notice) → 修复通过 → done;
    超限/连败 → waiting_input 退回(bundle 附确定性文案)。"""
    repo = tmp_path / "repo2"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    (repo / "base.txt").write_text("base\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "base", cwd=repo)
    _git("worktree", "add", "-b", "exec/t2", str(tmp_path / "wt2"), cwd=repo)
    wt = str(tmp_path / "wt2")
    _mkfile(wt, "test_flaky.py", "import os\n"
            "def test_gate():\n"
            "    assert os.path.exists(os.path.join(os.path.dirname(__file__), 'fixed.flag'))\n")
    _git("add", "-A", cwd=wt)
    _git("commit", "-qm", "feat", cwd=wt)

    class _Adapter(TurnAdapter):
        executor_id = "fake"

        async def start_session(self, job):
            job.session_id = "s1"

        async def run_turn(self, job, text):
            if "验收未过" in text:                      # 修复轮: 落修复标记
                _mkfile(wt, "fixed.flag", "1")
            return TurnOutcome(output=text + " [[IMPLEMENT_DONE]]", changed_files=[])

        async def probe(self, job):
            raise NotImplementedError

    j = ImplementJob("j-v4", root=str(repo), wt=wt, base="HEAD", branch="exec/t2",
                     instruction="do", adapter=_Adapter(),
                     verify_config={"test": "python -m pytest -q test_flaky.py",
                                    "timeoutMul": 0.05})
    j.status = "running"

    async def _flow():
        await j._run_turn("完成 [[IMPLEMENT_DONE]]")   # 轮1 FAIL → 回注队列
        await j.turn_task                              # 修复轮: 落 flag → PASS → done

    asyncio.run(_flow())
    kinds = [e["kind"] for e in j.events]
    assert j.status == "done"
    assert "verify_repair" in [e.get("reason") for e in j.events if e["kind"] == "notice"]
    assert "done" in kinds and "verify" in kinds
    assert j.verify_attempts == 1 and j.done_mismatch_streak == 0


def test_done_verify_fail_twice_escalates(tmp_path):
    """连续 2 轮 DONE 与实测不符 → waiting_input 退回 + 能力不足提示。"""
    repo = tmp_path / "repo3"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    (repo / "base.txt").write_text("base\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "base", cwd=repo)
    _git("worktree", "add", "-b", "exec/t3", str(tmp_path / "wt3"), cwd=repo)
    wt = str(tmp_path / "wt3")
    _mkfile(wt, "test_bad.py", "def test_gate():\n    assert False\n")
    _git("add", "-A", cwd=wt)
    _git("commit", "-qm", "feat", cwd=wt)

    class _Adapter(TurnAdapter):
        executor_id = "fake"

        async def start_session(self, job):
            job.session_id = "s1"

        async def run_turn(self, job, text):
            return TurnOutcome(output=text + " [[IMPLEMENT_DONE]]", changed_files=[])

        async def probe(self, job):
            raise NotImplementedError

    j = ImplementJob("j-v5", root=str(repo), wt=wt, base="HEAD", branch="exec/t3",
                     instruction="do", adapter=_Adapter(),
                     verify_config={"test": "python -m pytest -q test_bad.py",
                                    "timeoutMul": 0.05, "autoRepair": True, "maxAttempts": 1})
    j.status = "running"

    async def _flow():
        await j._run_turn("完成 [[IMPLEMENT_DONE]]")   # 轮1 FAIL(attempts=1) → 回注
        await j.turn_task                              # 轮2 FAIL(attempts=2>1) → 退回

    asyncio.run(_flow())
    assert j.status == "waiting_input", [e["kind"] for e in j.events][-4:]
    last = j.events[-1]
    assert last["kind"] == "input_required"
    assert "不符" in last["text"] or "修复轮次已用尽" in last["text"]
    assert j.verify_attempts == 2
