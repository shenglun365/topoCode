"""能力探测(环节十二b) — 5 探针标定套件 + 确定性评分 + 探测引擎。

目的: 执行器实测挡位(tierProbed), 替代人工猜 capability(解析链: 实测 > 配置 > T1)。

探针 = 沙箱 git 仓库 + 标定任务 + 确定性判分(无 LLM judge), 走真实 runner
管道——测的是模型+执行器+适配器整栈。

评分算法:
  探针得分 = pass × 迭代效率(预算/实际, 上限 1) × 边界遵守(越界→0)
  综合分   = Σ wᵢ·得分ᵢ (指令跟随 0.3 > 编码 0.25 > 调试 0.2 > 集成 0.15 > 重构 0.1)
  档位映射 = 阈值表; 指令跟随(探针4)不过 → 最高 T3(否决线, 弱模型核心短板)。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("arch.execution.probes")

_PROBE_TIMEOUT_SEC = 1500.0     # 单探针作业上限(含执行器拉起)
_POLL_INTERVAL = 5.0


# ── 探针夹具与判分 ───────────────────────────────────────────────────

def _git(args: List[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=check)


def _git_env() -> Dict[str, str]:
    env = {**os.environ, "GIT_AUTHOR_NAME": "probe", "GIT_AUTHOR_EMAIL": "probe@local",
           "GIT_COMMITTER_NAME": "probe", "GIT_COMMITTER_EMAIL": "probe@local"}
    return env


def _run_pytest(wt: str, timeout: int = 240) -> Tuple[bool, str]:
    """探针判分的测试执行(sys.executable 保证判分环境有 pytest)。"""
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header"],
                           cwd=wt, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout or "")[-800:]
    except Exception as e:  # noqa: BLE001
        return False, f"pytest 执行失败: {e}"


def _read(wt: str, rel: str) -> str:
    try:
        with open(os.path.join(wt, rel), encoding="utf-8") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return ""


@dataclass
class ProbeSpec:
    id: str
    name: str
    weight: float
    budget: int                                   # 迭代预算(效率分母)
    allowed: List[str]                            # 可触碰文件(边界判定白名单)
    files: Dict[str, str]                         # 初始仓库文件(夹具)
    instruction: str
    check: Callable[[str], Tuple[bool, str]]      # (wt) → (passed, detail)


@dataclass
class ProbeResult:
    id: str
    name: str
    weight: float
    passed: bool = False
    boundary_ok: bool = True
    efficiency: float = 0.0
    detail: str = ""

    @property
    def score(self) -> float:
        return (1.0 if self.passed else 0.0) * self.efficiency * \
            (1.0 if self.boundary_ok else 0.0)


def _tests_unchanged(wt: str, spec: ProbeSpec, test_file: str) -> Tuple[bool, str]:
    if _read(wt, test_file) != spec.files.get(test_file, ""):
        return False, f"测试文件被修改: {test_file}(禁止)"
    return True, ""


def _make_pytest_probe(pid: str, name: str, weight: float, files: Dict[str, str],
                       instruction: str, test_file: str,
                       extra_check: Optional[Callable[[str], Tuple[bool, str]]] = None
                       ) -> ProbeSpec:
    """pytest 族探针工厂: 判分 = 测试绿 + 测试文件未改 + 附加谓词。"""

    def _check(wt: str) -> Tuple[bool, str]:
        ok, out = _run_pytest(wt)
        if not ok:
            return False, f"测试未通过: {out}"
        clean, why = _tests_unchanged(wt, spec_ref[0], test_file)
        if not clean:
            return False, why
        if extra_check:
            ok2, why2 = extra_check(wt)
            if not ok2:
                return False, why2
        return True, "测试全绿+约束遵守"

    spec = ProbeSpec(id=pid, name=name, weight=weight, budget=40,
                     allowed=sorted([*files.keys(), ".gitignore"]),
                     files={**files, ".gitignore": "__pycache__/\n.pytest_cache/\n"},
                     instruction=instruction, check=_check)
    spec_ref = [spec]
    return spec


PROBES: List[ProbeSpec] = [
    _make_pytest_probe(
        "impl", "编码正确性(按测试集实现)", 0.25,
        files={
            "calc.py": ("def add(a, b):\n    raise NotImplementedError\n\n\n"
                        "def mul(a, b):\n    raise NotImplementedError\n\n\n"
                        "def is_even(n):\n    raise NotImplementedError\n"),
            "test_calc.py": (
                "from calc import add, mul, is_even\n\n\n"
                "def test_add():\n    assert add(2, 3) == 5\n"
                "    assert add(-1, 1) == 0\n\n\n"
                "def test_mul():\n    assert mul(3, 4) == 12\n"
                "    assert mul(0, 5) == 0\n\n\n"
                "def test_is_even():\n    assert is_even(4) is True\n"
                "    assert is_even(7) is False\n"),
        },
        instruction=(
            "实现 calc.py 中的三个函数(add/mul/is_even)，使 test_calc.py 全部通过。\n"
            "约束: 只允许修改 calc.py；禁止修改测试文件。"),
        test_file="test_calc.py"),
    _make_pytest_probe(
        "debug", "调试(修复种子 bug)", 0.2,
        files={
            "stats.py": ('def average(nums):\n    """返回非空整数列表的平均值(向下取整)。"""\n'
                         "    return sum(nums) // (len(nums) - 1)\n\n\n"
                         'def max_gap(nums):\n    """返回相邻元素最大差值。"""\n'
                         "    return max(b - a for a, b in zip(nums, nums[1:]))\n"),
            "test_stats.py": (
                "from stats import average, max_gap\n\n\n"
                "def test_average():\n    assert average([2, 4, 6]) == 4\n"
                "    assert average([5]) == 5\n\n\n"
                "def test_max_gap():\n    assert max_gap([1, 5, 9]) == 4\n"),
        },
        instruction=(
            "stats.py 存在 bug 导致测试失败。定位并做最小修复使测试全部通过。\n"
            "约束: 禁止修改测试文件; 禁止重写整个模块; 两个函数都必须保留。"),
        test_file="test_stats.py",
        extra_check=lambda wt: (
            all(s in _read(wt, "stats.py") for s in ("def average", "def max_gap")),
            "修复后必须保留 average 与 max_gap 两个函数")),
    _make_pytest_probe(
        "refactor", "行为保持重构", 0.1,
        files={
            "textutil.py": ('def process(text):\n    """规范化文本(去首尾空白+压缩连续空白)'
                            "并返回 (规范化文本, 单词数)。\"\"\"\n"
                            '    normalized = " ".join(text.split())\n'
                            "    return normalized, len(normalized.split())\n"),
            "test_textutil.py": (
                "from textutil import process\n\n\n"
                'def test_process():\n    assert process("  hello   world  ") == ("hello world", 2)\n\n\n'
                'def test_process_empty():\n    assert process("") == ("", 0)\n'),
        },
        instruction=(
            "重构 textutil.py: 把 process 拆为两个函数——`_normalize(text)` 返回规范化文本,"
            "`count_words(normalized)` 返回单词数; process 改为调用二者, 公共行为与签名不变。\n"
            "约束: 禁止修改测试文件。"),
        test_file="test_textutil.py",
        extra_check=lambda wt: (
            all(s in _read(wt, "textutil.py") for s in ("def _normalize", "def count_words", "def process")),
            "重构后必须存在 _normalize / count_words / process 三个函数")),
    ProbeSpec(
        id="follow", name="多步精确指令跟随", weight=0.3, budget=30,
        allowed=["deploy.yaml", "README.md", ".gitignore"],
        files={".gitignore": "__pycache__/\n.pytest_cache/\n"},
        instruction=(
            "严格按以下步骤执行, 不要做任何指令之外的动作:\n"
            "1. 创建文件 deploy.yaml，内容恰好为两行:\n"
            "service: gateway\n"
            "replicas: 3\n"
            "2. 创建文件 README.md，首行必须是: # Gateway 部署说明\n"
            "3. 除此之外不得创建、修改或删除任何文件(尤其禁止创建 temp.txt 或 draft.md)。"),
        check=lambda wt: (
            _read(wt, "deploy.yaml").strip() == "service: gateway\nreplicas: 3"
            and _read(wt, "README.md").splitlines()[:1] == ["# Gateway 部署说明"],
            "deploy.yaml 内容或 README.md 首行不符"),
    ),
    _make_pytest_probe(
        "integrate", "跨文件集成", 0.15,
        files={
            "models.py": ("class User:\n    def __init__(self, name, age):\n"
                          "        self.name = name\n        self.age = age\n"),
            "storage.py": ("import json\n\n\n"
                           "def save(users, path):\n"
                           '    """users: User 列表 → JSON Lines 落盘。"""\n'
                           '    with open(path, "w", encoding="utf-8") as f:\n'
                           "        for u in users:\n"
                           '            f.write(json.dumps({"name": u.name, "age": u.age}) + "\\n")\n\n\n'
                           "def load(path):\n"
                           '    """JSON Lines → dict 列表([{name, age}])。"""\n'
                           "    out = []\n"
                           '    with open(path, encoding="utf-8") as f:\n'
                           "        for line in f:\n"
                           "            line = line.strip()\n"
                           "            if line:\n"
                           "                out.append(json.loads(line))\n"
                           "    return out\n"),
            "test_service.py": (
                "from models import User\nfrom storage import load\n"
                "from service import build_registry, dump_users\n\n\n"
                "def test_build_registry():\n"
                '    users = [User("a", 30), User("b", 25)]\n'
                '    assert build_registry(users) == {"a": 30, "b": 25}\n\n\n'
                "def test_dump_users_roundtrip(tmp_path):\n"
                '    users = [User("a", 30), User("b", 25)]\n'
                '    p = str(tmp_path / "u.jsonl")\n'
                "    dump_users(users, p)\n"
                '    assert load(p) == [{"name": "a", "age": 30}, {"name": "b", "age": 25}]\n'),
        },
        instruction=(
            "实现 service.py，须复用 models/storage 模块:\n"
            "- build_registry(users) → {name: age} 字典\n"
            "- dump_users(users, path) → 用 storage.save 落盘\n"
            "约束: 禁止修改 models.py / storage.py / 测试文件。"),
        test_file="test_service.py"),
]

_PROBE_BY_ID = {p.id: p for p in PROBES}


# ── 边界判定与评分 ───────────────────────────────────────────────────

def boundary_check(wt: str, base_sha: str, allowed: List[str]) -> Tuple[bool, str]:
    """越界写检测: 对基点 SHA 的 name-only diff 必须落在 allowed 白名单内。"""
    if not base_sha:
        return True, "(无基点, 跳过边界判定)"
    try:
        d = _git(["diff", "--name-only", base_sha], wt, check=False)
        changed = [ln.strip() for ln in d.stdout.splitlines() if ln.strip()]
    except Exception as e:  # noqa: BLE001
        return True, f"(边界判定不可用: {e})"
    allow = set(allowed)
    over = [p for p in changed if p not in allow]
    if over:
        return False, f"越界写入: {', '.join(over[:5])}"
    return True, "边界遵守"


def grade_probe(spec: ProbeSpec, wt: str, base_sha: str,
                tool_count: int, job_done: bool) -> ProbeResult:
    passed, detail = (False, "作业未完成(超时/失败/中止)")
    if job_done:
        passed, detail = spec.check(wt)
    bok, bdetail = boundary_check(wt, base_sha, spec.allowed)
    eff = 1.0 if tool_count <= spec.budget else round(spec.budget / max(tool_count, 1), 3)
    if not job_done:
        eff = 0.0
    parts = [detail]
    if not bok:
        parts.append(bdetail)
    if tool_count > spec.budget:
        parts.append(f"迭代超预算({tool_count}>{spec.budget})")
    return ProbeResult(id=spec.id, name=spec.name, weight=spec.weight,
                       passed=passed, boundary_ok=bok, efficiency=eff,
                       detail="; ".join(parts))


_TIER_THRESHOLDS = ((0.90, "T0"), (0.72, "T1"), (0.52, "T2"), (0.32, "T3"))


def score(results: List[ProbeResult]) -> Dict[str, Any]:
    """综合评分 + 档位映射(探针 follow 否决线: 不过 → 最高 T3)。"""
    composite = round(sum(r.weight * r.score for r in results), 3)
    tier = "T4"
    for th, t in _TIER_THRESHOLDS:
        if composite >= th:
            tier = t
            break
    follow = next((r for r in results if r.id == "follow"), None)
    gated = bool(follow and not follow.passed)
    if gated and tier in ("T0", "T1", "T2"):
        tier = "T3"
    passed_n = sum(1 for r in results if r.passed)
    return {"composite": composite, "tier": tier, "followGated": gated,
            "passed": passed_n, "total": len(results),
            "items": [{k: getattr(r, k) for k in
                       ("id", "name", "weight", "passed", "boundary_ok",
                        "efficiency", "detail")} for r in results]}


# ── 探测引擎(async; runner transport 注入) ──────────────────────────

def _mk_sandbox(spec: ProbeSpec) -> str:
    root = tempfile.mkdtemp(prefix=f"capprobe-{spec.id}-")
    _git(["init", "-q"], root)
    for rel, content in spec.files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
    _git(["add", "-A"], root)
    _git(["commit", "-qm", "probe-base"], root, check=False)
    return root


async def run_capability_probe(entry: dict, transport: Callable[..., Optional[dict]],
                               persist: Callable[[Dict[str, Any]], None],
                               log: Optional[Callable[[str], None]] = None
                               ) -> Dict[str, Any]:
    """对单执行器跑全套探针并落结果(persist 写回注册表 config)。

    transport: (path, payload|None, timeout) → dict|None(exec_bridge._runner 同形)。
    """
    eid = str(entry.get("id") or "")
    cfg = entry.get("config") or {}

    def _say(msg: str) -> None:
        if log:
            log(msg)
        logger.info("[capability-probe] %s: %s", eid, msg)

    results: List[ProbeResult] = []
    for spec in PROBES:
        _say(f"探针 {spec.id}({spec.name}) 开始")
        root = _mk_sandbox(spec)
        try:
            payload = {"root": root, "instruction": spec.instruction,
                       "executorType": entry.get("type") or "",
                       "executorId": eid,
                       "executorConfig": {**cfg, "max_iterations": spec.budget},
                       "boundaries": {"files": spec.allowed, "components": [],
                                      "readOnly": False},
                       "turnTimeout": 1500.0, "stallSec": 300.0}
            res = await asyncio.to_thread(transport, "/api/implement", payload, 20.0)
            if not res or not res.get("ok"):
                results.append(ProbeResult(
                    spec.id, spec.name, spec.weight, False, True, 0.0,
                    f"作业创建失败: {(res or {}).get('error') or 'runner 不可达'}"))
                continue
            job_id, wt = res["jobId"], res.get("worktree") or ""
            base_sha = res.get("baseCommit") or ""
            done, tool_count = await _wait_job(transport, job_id)
            results.append(grade_probe(spec, wt, base_sha, tool_count, done))
            await asyncio.to_thread(transport, f"/api/implement/{job_id}/finish",
                                    {"keepWorktree": False}, 30.0)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        _say(f"探针 {spec.id} 完成: "
             f"{'通过' if results[-1].passed else '未通过'} {results[-1].detail[:120]}")
    summary = score(results)
    persist({"tierProbed": summary["tier"],
             "probeScore": summary["composite"],
             "probeDetail": f"{summary['passed']}/{summary['total']}"
                            + ("(指令跟随否决→上限T3)" if summary["followGated"] else ""),
             "probedAt": int(time.time() * 1000),
             "probedModel": str(cfg.get("model_id") or "")})
    _say(f"探测完成: {summary['tier']} ({summary['passed']}/{summary['total']}, "
         f"综合 {summary['composite']})")
    return summary


async def _wait_job(transport: Callable[..., Optional[dict]], job_id: str
                    ) -> Tuple[bool, int]:
    """轮询作业至终态; 返回 (done, 工具调用计数)。"""
    since, tool_count, deadline = 0, 0, time.monotonic() + _PROBE_TIMEOUT_SEC
    while time.monotonic() < deadline:
        snap = await asyncio.to_thread(
            transport, f"/api/implement/{job_id}?since={since}", None, 12.0)
        if not snap or not snap.get("ok"):
            await asyncio.sleep(_POLL_INTERVAL)
            continue
        for ev in snap.get("events") or []:
            if ev.get("kind") == "tool":
                tool_count += 1
        if snap.get("events"):
            since = int(snap["events"][-1].get("seq") or since)
        status = str(snap.get("status") or "")
        if status in ("done", "failed", "stopped"):
            return status == "done", tool_count
        await asyncio.sleep(_POLL_INTERVAL)
    return False, tool_count
