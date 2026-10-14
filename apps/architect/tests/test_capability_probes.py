"""能力探测(环节十二b)回归: 探针判分 / 评分映射 / 边界判定 / 引擎流程。

Run: cd <repo> && python -m pytest apps/architect/tests/test_capability_probes.py -q
"""
import asyncio
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.execution import probes as P


@pytest.fixture(autouse=True)
def _cleanup_probe_sandboxes():
    """探针沙箱清理(判分器测试直接调 _mk_sandbox, 不走引擎的 finally 清理)
    ——防 /tmp/capprobe-* 泄漏。"""
    import glob
    import shutil
    yield
    for d in glob.glob("/tmp/capprobe-*"):
        shutil.rmtree(d, ignore_errors=True)

# ── 探针判分(真实 pytest 执行于夹具仓库) ─────────────────────────────

def _spec(pid: str) -> P.ProbeSpec:
    return next(p for p in P.PROBES if p.id == pid)


def _sandbox(pid: str) -> str:
    return P._mk_sandbox(_spec(pid))


def test_probe_impl_pass_and_fail(tmp_path):
    spec = _spec("impl")
    # 未实现 → 不通过
    wt = _sandbox("impl")
    passed, _ = spec.check(wt)
    assert passed is False
    # 正确实现 → 通过
    with open(os.path.join(wt, "calc.py"), "w", encoding="utf-8") as f:
        f.write("def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n"
                "    return a * b\n\n\ndef is_even(n):\n    return n % 2 == 0\n")
    passed, detail = spec.check(wt)
    assert passed and "全绿" in detail


def test_probe_impl_rejects_test_modification():
    wt = _sandbox("impl")
    with open(os.path.join(wt, "calc.py"), "w", encoding="utf-8") as f:
        f.write("def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n"
                "    return a * b\n\n\ndef is_even(n):\n    return n % 2 == 0\n")
    with open(os.path.join(wt, "test_calc.py"), "a", encoding="utf-8") as f:
        f.write("\n")                      # 改测试(追加空行) → 拒绝
    passed, detail = _spec("impl").check(wt)
    assert passed is False and "测试文件被修改" in detail


def test_probe_debug_seeded_bug_detected():
    spec = _spec("debug")
    wt = _sandbox("debug")
    passed, _ = spec.check(wt)             # 种子 bug 未修 → 失败
    assert passed is False
    rel = os.path.join(wt, "stats.py")
    src = open(rel, encoding="utf-8").read()
    open(rel, "w", encoding="utf-8").write(
        src.replace("len(nums) - 1", "len(nums)"))   # 最小修复
    passed, _ = spec.check(wt)
    assert passed


def test_probe_refactor_requires_split():
    spec = _spec("refactor")
    wt = _sandbox("refactor")
    src = open(os.path.join(wt, "textutil.py"), encoding="utf-8").read()
    refactored = (
        'def _normalize(text):\n    return " ".join(text.split())\n\n\n'
        "def count_words(normalized):\n    return len(normalized.split())\n\n\n"
        "def process(text):\n    n = _normalize(text)\n"
        "    return n, count_words(n)\n")
    open(os.path.join(wt, "textutil.py"), "w", encoding="utf-8").write(refactored)
    passed, _ = spec.check(wt)
    assert passed
    # 未拆分(仅抄原实现) → 附加谓词拒绝
    wt2 = _sandbox("refactor")
    passed2, detail2 = spec.check(wt2)
    assert passed2 is False


def test_probe_follow_precise_artifacts():
    spec = _spec("follow")
    wt = _sandbox("follow")
    passed, _ = spec.check(wt)
    assert passed is False                  # 未做 → 失败
    with open(os.path.join(wt, "deploy.yaml"), "w", encoding="utf-8") as f:
        f.write("service: gateway\nreplicas: 3\n")
    with open(os.path.join(wt, "README.md"), "w", encoding="utf-8") as f:
        f.write("# Gateway 部署说明\n正文...\n")
    passed, _ = spec.check(wt)
    assert passed
    # 多写的文件 → 边界违例(基点=正确产物 commit, 越界文件在其后)
    subprocess_git_add_commit(wt)
    base = P._git(["rev-parse", "HEAD"], wt).stdout.strip()
    with open(os.path.join(wt, "temp.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    subprocess_git_add_commit(wt)
    ok, detail = P.boundary_check(wt, base, spec.allowed + ["deploy.yaml", "README.md"])
    assert not ok and "越界" in detail


def subprocess_git_add_commit(wt: str) -> None:
    import subprocess
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "work"], cwd=wt, check=True,
                   capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


# ── 评分映射 ─────────────────────────────────────────────────────────

def _res(pid, passed, eff=1.0, bok=True):
    spec = _spec(pid)
    return P.ProbeResult(spec.id, spec.name, spec.weight, passed, bok, eff, "")


def test_score_all_pass_high_efficiency_is_t0():
    s = P.score([_res(p.id, True) for p in P.PROBES])
    assert s["tier"] == "T0" and s["passed"] == 5


def test_score_follow_gate_caps_t3():
    results = [_res(p.id, True) for p in P.PROBES]
    results = [r if r.id != "follow" else _res("follow", False) for r in results]
    s = P.score(results)
    assert s["followGated"] and s["tier"] == "T2"


def test_score_partial_pass_maps_mid_tiers():
    # 调试+重构失败 → 综合 = 1 - 0.2 - 0.1 = 0.7 → T1(中)
    results = [_res(p.id, p.id not in ("debug", "refactor")) for p in P.PROBES]
    s = P.score(results)
    assert s["tier"] == "T1"
    # 只有指令跟随过 → 综合 0.3 → T2(弱, 全面补偿)
    results2 = [_res(p.id, p.id == "follow") for p in P.PROBES]
    assert P.score(results2)["tier"] == "T2"


def test_score_boundary_violation_zeroes_probe():
    results = []
    for p in P.PROBES:
        r = _res(p.id, True)
        if p.id == "impl":
            r.boundary_ok = False
        results.append(r)
    s = P.score(results)
    assert s["tier"] == "T1"          # 1 - 0.25 = 0.75 → T1


# ── 引擎流程(fake transport, 单探针加速) ─────────────────────────────

def test_engine_full_flow_with_fake_runner(monkeypatch):
    spec = _spec("follow")
    wt = _sandbox("follow")
    with open(os.path.join(wt, "deploy.yaml"), "w", encoding="utf-8") as f:
        f.write("service: gateway\nreplicas: 3\n")
    with open(os.path.join(wt, "README.md"), "w", encoding="utf-8") as f:
        f.write("# Gateway 部署说明\n")
    base = P._git(["rev-parse", "HEAD"], wt).stdout.strip()
    calls = []

    def transport(path, payload=None, timeout=12.0):
        calls.append(path)
        if path == "/api/implement":
            return {"ok": True, "jobId": "job-p1", "branch": "task/p1",
                    "worktree": wt, "baseCommit": base}
        if path.endswith("?since=0"):
            return {"ok": True, "status": "done", "events": [
                {"seq": 1, "kind": "tool"}, {"seq": 2, "kind": "tool"},
                {"seq": 3, "kind": "done"}]}
        return {"ok": True}

    monkeypatch.setattr(P, "PROBES", [spec])
    persisted = {}
    summary = asyncio.run(P.run_capability_probe(
        {"id": "ex-p", "type": "cline-sdk", "config": {"model_id": "m-1"}},
        transport, lambda fields: persisted.update(fields)))
    assert summary["tier"] and summary["passed"] == 1
    assert persisted["tierProbed"] == summary["tier"]
    assert persisted["probedModel"] == "m-1"
    assert any(p.endswith("/finish") for p in calls)     # 作业收尾(清沙箱)


def test_engine_failed_job_records_unpassed(monkeypatch):
    spec = _spec("follow")
    wt = _sandbox("follow")

    def transport(path, payload=None, timeout=12.0):
        if path == "/api/implement":
            return {"ok": True, "jobId": "job-p2", "branch": "task/p2",
                    "worktree": wt, "baseCommit": ""}
        if path.endswith("?since=0"):
            return {"ok": True, "status": "failed", "events": []}
        return {"ok": True}

    monkeypatch.setattr(P, "PROBES", [spec])
    persisted = {}
    summary = asyncio.run(P.run_capability_probe(
        {"id": "ex-p", "type": "cline-sdk", "config": {}},
        transport, lambda fields: persisted.update(fields)))
    assert summary["passed"] == 0 and summary["tier"] == "T2"


# ── REST 端点 ────────────────────────────────────────────────────────

def test_capability_probe_rest_guards(client, monkeypatch):
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex-r", "type": "cline-sdk", "enabled": True, "config": {}}])
    r = client.post("/api/architect/agent/executors/ex-nope/capability-probe")
    assert r.status_code == 404
    ae._CAP_PROBE_RUNNING.add("ex-r")
    r = client.post("/api/architect/agent/executors/ex-r/capability-probe")
    assert r.status_code == 409
    ae._CAP_PROBE_RUNNING.discard("ex-r")
    r = client.get("/api/architect/agent/executors/ex-r/capability-probe")
    assert r.status_code == 200 and r.json()["data"]["running"] is False
