"""程序化验收门禁 V1 —— 交付判定从「agent 自述」改为「runner 实测」。

设计蓝本: docs/runner-verify-gate-design.md（V1 = L1 发现链 + L2 执行 + 级别判定）。
V4 编排(修复回注/升级)与 V5 反馈落流(矩阵进会话消息)不在本模块——本模块只产出
验证矩阵 dict, 由 ImplementJob done 分支 emit "verify" 事件携带。

四条设计原则(设计文档 §1): 验证优先 / 确定性反馈(原因码) / 零假设(零假设语言
框架, 探测失败走降级) / 分层降级(A 完整闭环→D 仅审查, 反馈永远确定)。

发现链(P0→P3 取第一个命中, 全程记录来源):
  P0 config   作业 start payload.verify {build?, test?, timeoutMul?}——最高权威
  P1 ci       .github/workflows/*.yml run 行含 test/build 关键字; Makefile test:/check: 目标
  P2 约定     package.json scripts.{test,build}; pyproject.toml [tool.pytest] → pytest -q;
              go.mod → go test ./...; Cargo.toml → cargo test (构建不自动跑, 防意外重活)
  P3 启发     存在 test_*.py/*_test.py → python -m pytest -q(标注 heuristic)
  未命中      → 级别 C(NO_VERIFY_CONFIG)——不猜命令
级别(每环节独立判定):
  B  有命令可执行(退出码可判; V2 结构化适配器接入后升 A)
  C  探测不到(NO_VERIFY_CONFIG) / 命令被白名单拒绝(WHITELIST_REJECTED)
  D  diff 仅纯文档/资源(PURE_DOCS)——仅人工审查
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

# L2 白名单: 验收命令只允许构建/测试类; 破坏性/外联模式一律拒绝(确定性反馈)
_WHITELIST_DENY_PATTERNS = (
    r"\brm\b", r"\bmkfs", r"\bdd\b\s+if=", r"\bshutdown\b", r"\breboot\b",
    r"\bcurl\b", r"\bwget\b", r"\bsudo\b", r"\bgit\s+push\b",
    r">\s*/dev/sd", r"\bchmod\s+777\s+/",
)
_DENY_RE = re.compile("|".join(_WHITELIST_DENY_PATTERNS))

# D 档: 纯文档/资源后缀(diff 仅含这些 → 跳过执行验收, 强制人工 diff 审查)
_PURE_DOCS_EXTS = {".md", ".txt", ".rst", ".png", ".jpg", ".jpeg", ".gif",
                   ".svg", ".ico", ".pdf", ".woff", ".woff2", ".ttf"}

_BASE_TIMEOUT = {"build": 300.0, "test": 600.0}
_LOG_HEAD = 800
_LOG_TAIL = 800


def _stage_result(cmd: str, source: str, stage: str,
                  verdict: str, reason: str = "",
                  exit_code: Optional[int] = None,
                  duration_ms: int = 0, log_tail: str = "",
                  structured: bool = False,
                  per_test: Optional[List[Dict[str, Any]]] = None,
                  summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"stage": stage, "verdict": verdict, "reason": reason,
            "cmd": cmd, "source": source, "exitCode": exit_code,
            "durationMs": duration_ms, "logTail": log_tail,
            "structured": structured,
            "perTest": per_test or [],
            "summary": summary or {}}


# ── V2 结构化适配器（A 档）: 报告旗标注入 + 结果解析 ────────────────────

def augment_command(stage: str, cmd: str, report_dir: str) -> str:
    """给已知测试命令注入结构化报告旗标(幂等——已带旗标不改写)。"""
    report = os.path.join(report_dir, "junit.xml").replace(os.sep, "/")
    if stage == "test" and "pytest" in cmd and "junitxml" not in cmd:
        return f"{cmd} --junitxml={report}"
    if stage == "test" and cmd.strip().startswith("go test") and "-json" not in cmd:
        return f"{cmd} -json"
    return cmd


def _parse_junit(path: str) -> Optional[Dict[str, Any]]:
    """junit XML → {perTest, summary}; 解析失败返回 None(降 B 档按退出码)。"""
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(path).getroot()
    except Exception:  # noqa: BLE001
        return None
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if root.tag == "testsuites":
        suites = root.findall("testsuite") or [root]
    per: List[Dict[str, Any]] = []
    total = failed = skipped = passed = 0
    for suite in suites:
        total += int(suite.get("tests") or 0)
        failed += int(suite.get("failures") or 0) + int(suite.get("errors") or 0)
        skipped += int(suite.get("skipped") or 0)
        for tc in suite.iter("testcase"):
            name = f"{tc.get('classname') or ''}.{tc.get('name') or ''}".lstrip(".")
            status = "passed"
            message = ""
            if tc.find("failure") is not None:
                status, message = "failed", (tc.find("failure").text or "")[:400]
            elif tc.find("error") is not None:
                status, message = "failed", (tc.find("error").text or "")[:400]
            elif tc.find("skipped") is not None:
                status = "skipped"
            passed += status == "passed"
            per.append({"name": name, "status": status,
                        "durationMs": int(float(tc.get("time") or 0) * 1000),
                        "message": message})
    if not total:
        return None
    return {"perTest": per,
            "summary": {"total": total, "passed": passed,
                        "failed": failed, "skipped": skipped}}


def _parse_go_json(output: str) -> Optional[Dict[str, Any]]:
    """go test -json 流 → {perTest, summary}; 无测试事件返回 None。"""
    per: List[Dict[str, Any]] = {}
    order: List[str] = []
    for ln in (output or "").splitlines():
        try:
            row = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        test = row.get("Test")
        if not test or row.get("Action") not in ("pass", "fail", "skip"):
            continue
        key = f"{row.get('Package') or ''}.{test}".lstrip(".")
        if key not in per:
            per[key] = {"name": key, "status": row["Action"],
                        "durationMs": 0, "message": ""}
            order.append(key)
        if row["Action"] in ("pass", "fail", "skip"):
            per[key]["status"] = row["Action"]
        if row.get("output") and per[key]["status"] == "fail":
            per[key]["message"] = (per[key]["message"] + row["output"])[:400]
    if not order:
        return None
    rows = [per[k] for k in order]
    failed = sum(1 for r in rows if r["status"] == "fail")
    skipped = sum(1 for r in rows if r["status"] == "skip")
    return {"perTest": rows,
            "summary": {"total": len(rows), "passed": len(rows) - failed - skipped,
                        "failed": failed, "skipped": skipped}}


def _attach_structured(result: Dict[str, Any], stage: str, cmd: str,
                       report_dir: str, combined: str) -> Dict[str, Any]:
    """解析结构化报告(A 档); 无报告/解析失败 → 原 result(B 档)。"""
    parsed = None
    junit = os.path.join(report_dir, "junit.xml")
    if os.path.isfile(junit):
        parsed = _parse_junit(junit)
    if parsed is None and "go test" in cmd:
        parsed = _parse_go_json(combined)
    if parsed is None:
        return result
    result["structured"] = True
    result["perTest"] = parsed["perTest"]
    result["summary"] = parsed["summary"]
    if parsed["summary"]["failed"] > 0 and result["verdict"] == "PASS":
        # 退出码 0 但报告有失败 → 以报告为准(防假通过)
        result["verdict"] = "FAIL"
        result["reason"] = "TEST_FAILED"
    return result


def _tail(head_tail: str) -> str:
    if len(head_tail) <= _LOG_HEAD + _LOG_TAIL:
        return head_tail
    return head_tail[:_LOG_HEAD] + "\n…(截断)…\n" + head_tail[-_LOG_TAIL:]


def _command_allowed(cmd: str) -> bool:
    return _DENY_RE.search(cmd or "") is None


def _makefile_target(wt: str, names=("test", "check")) -> Optional[str]:
    p = os.path.join(wt, "Makefile")
    if not os.path.isfile(p):
        return None
    try:
        lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:  # noqa: BLE001
        return None
    capture = False
    for ln in lines:
        if re.match(r"^[A-Za-z0-9_.-]+:", ln):
            target = ln.split(":")[0].strip()
            capture = target in names
            continue
        if capture and ln.startswith("\t") and ln.strip() \
                and not ln.strip().startswith("@"):
            first = ln.strip().split("&&")[0].strip()
            return first
    return None


def _ci_workflow_cmd(wt: str, keyword: str) -> Optional[str]:
    d = os.path.join(wt, ".github", "workflows")
    if not os.path.isdir(d):
        return None
    for fn in sorted(os.listdir(d)):
        if not fn.endswith((".yml", ".yaml")):
            continue
        try:
            text = open(os.path.join(d, fn), encoding="utf-8", errors="replace").read()
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r"run:\s*(.+)", text):
            cmd = m.group(1).strip().strip("'\"")
            if keyword in cmd.lower():
                return cmd
    return None


def _package_json_script(wt: str, key: str) -> Optional[str]:
    p = os.path.join(wt, "package.json")
    if not os.path.isfile(p):
        return None
    try:
        scripts = (json.load(open(p, encoding="utf-8")) or {}).get("scripts") or {}
    except Exception:  # noqa: BLE001
        return None
    val = scripts.get(key)
    return f"npm run {key}" if isinstance(val, str) and val.strip() else None


def discover_verify(wt: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """L1 发现链: 返回 {build: {cmd,source}|None, test: {cmd,source}|None, level, reason}。

    level 为发现面预判(C=无命令); 执行后由 verify_and_judge 定稿。
    """
    cfg = config if isinstance(config, dict) else {}
    plan: Dict[str, Any] = {"build": None, "test": None, "level": "", "reason": ""}
    # P0 显式配置(最高权威, 命中即停)
    for stage, key in (("build", "build"), ("test", "test")):
        val = str(cfg.get(key) or "").strip()
        if val:
            plan[stage] = {"cmd": val, "source": "config"}
    if plan["build"] or plan["test"]:
        plan["level"] = ""
        return plan
    # P1 CI
    if plan["test"] is None:
        cmd = _ci_workflow_cmd(wt, "test") or _makefile_target(wt, ("test", "check"))
        if cmd:
            plan["test"] = {"cmd": cmd, "source": "ci"}
    if plan["build"] is None:
        cmd = _ci_workflow_cmd(wt, "build")
        if cmd:
            plan["build"] = {"cmd": cmd, "source": "ci"}
    # P2 清单约定
    if plan["test"] is None:
        cmd = _package_json_script(wt, "test")
        if cmd:
            plan["test"] = {"cmd": cmd, "source": "convention"}
        elif os.path.isfile(os.path.join(wt, "pyproject.toml")) and "[tool.pytest]" in \
                open(os.path.join(wt, "pyproject.toml"), encoding="utf-8",
                     errors="replace").read():
            plan["test"] = {"cmd": "python -m pytest -q", "source": "convention"}
        elif os.path.isfile(os.path.join(wt, "go.mod")):
            plan["test"] = {"cmd": "go test ./...", "source": "convention"}
        elif os.path.isfile(os.path.join(wt, "Cargo.toml")):
            plan["test"] = {"cmd": "cargo test", "source": "convention"}
    if plan["build"] is None:
        cmd = _package_json_script(wt, "build")
        if cmd:
            plan["build"] = {"cmd": cmd, "source": "convention"}
    # P3 语言启发
    if plan["test"] is None:
        has_py_tests = any(
            fn.startswith(("test_", )) or fn.endswith("_test.py")
            for _, _, fs in os.walk(wt) for fn in fs if fn.endswith(".py"))
        if has_py_tests:
            plan["test"] = {"cmd": "python -m pytest -q", "source": "heuristic"}
    if not plan["test"] and not plan["build"]:
        plan["level"] = "C"
        plan["reason"] = "NO_VERIFY_CONFIG"
    return plan


def _run_stage(wt: str, stage: str, cmd: str, source: str,
               timeout_mul: float, report_dir: str = "") -> Dict[str, Any]:
    """L2 执行: cwd=wt 白名单前置 + 超时分级 + 输出头尾截断 + V2 结构化报告。"""
    if not _command_allowed(cmd):
        return _stage_result(cmd, source, stage, "UNVERIFIABLE",
                             "WHITELIST_REJECTED")
    exec_cmd = augment_command(stage, cmd, report_dir) if report_dir else cmd
    timeout = max(1.0, _BASE_TIMEOUT.get(stage, 300.0) * (timeout_mul or 1.0))
    started = time.monotonic()
    try:
        proc = subprocess.run(exec_cmd, cwd=wt, shell=True, capture_output=True,
                              text=True, timeout=timeout,
                              env={**os.environ, "CI": "1"})
        duration = int((time.monotonic() - started) * 1000)
        combined = ((proc.stdout or "") + (proc.stderr or "")).strip()
        verdict = "PASS" if proc.returncode == 0 else "FAIL"
        reason = "" if proc.returncode == 0 else (
            "TIMEOUT" if duration >= timeout * 990 else "")
        result = _stage_result(cmd, source, stage, verdict, reason,
                               exit_code=proc.returncode, duration_ms=duration,
                               log_tail=_tail(combined))
        if report_dir:
            result = _attach_structured(result, stage, cmd, report_dir, combined)
        return result
    except subprocess.TimeoutExpired:
        duration = int((time.monotonic() - started) * 1000)
        return _stage_result(cmd, source, stage, "FAIL", "TIMEOUT",
                             duration_ms=duration, log_tail="超时终止(>{:.0f}s)".format(timeout))
    except Exception as e:  # noqa: BLE001
        return _stage_result(cmd, source, stage, "UNVERIFIABLE",
                             "RUNNER_ENV_BROKEN", log_tail=str(e)[:800])


def _pure_docs(changed_files: List[str]) -> bool:
    if not changed_files:
        return False
    return all(os.path.splitext(f)[1].lower() in _PURE_DOCS_EXTS
               for f in changed_files)


def verify_and_judge(wt: str, config: Optional[Dict[str, Any]] = None,
                     changed_files: Optional[List[str]] = None,
                     baseline: Optional[Dict[str, Any]] = None,
                     report_dir: str = "") -> Dict[str, Any]:
    """V1/V2 门禁入口: 发现 → 执行(结构化) → 回归对比 → 级别判定。

    baseline(V3): 作业基点的基线运行结果 {perTest}|None——缺失 → regression
    UNVERIFIABLE(NO_BASELINE, 不阻塞 test 判定); 在场 → 新增失败 vs 存量失败,
    仅存量失败 → PASS_WITH_KNOWN。overall: A(结构化)/B(退出码)/C(未验)/D(仅审查)。
    """
    changed = [str(f) for f in (changed_files or [])]
    if _pure_docs(changed):
        return {"overall": "D", "reason": "PURE_DOCS", "build": None, "test": None,
                "regression": None}
    cfg = config if isinstance(config, dict) else {}
    mul = float(cfg.get("timeoutMul") or 1.0)
    plan = discover_verify(wt, cfg)
    if plan["level"] == "C":
        return {"overall": "C", "reason": plan["reason"],
                "build": None, "test": None, "regression": None}
    matrix: Dict[str, Any] = {"overall": "B", "reason": "", "build": None,
                              "test": None, "regression": None}
    if plan["build"]:
        matrix["build"] = _run_stage(wt, "build", plan["build"]["cmd"],
                                     plan["build"]["source"], mul, report_dir)
    if plan["test"]:
        matrix["test"] = _run_stage(wt, "test", plan["test"]["cmd"],
                                    plan["test"]["source"], mul, report_dir)
    # V3 回归对比(仅结构化可 per-test 对照; 退出码档无基线可比)
    test = matrix.get("test")
    if test and test.get("structured"):
        known = {(r.get("name")) for r in (baseline or {}).get("perTest") or []
                 if r.get("status") == "failed"}
        fails = [r for r in test.get("perTest") or [] if r["status"] == "failed"]
        new_failures = [r["name"] for r in fails if r["name"] not in known]
        known_failures = [r["name"] for r in fails if r["name"] in known]
        if baseline is None:
            matrix["regression"] = {"verdict": "UNVERIFIABLE", "reason": "NO_BASELINE",
                                    "newFailures": [], "knownFailures": []}
        elif test["verdict"] == "FAIL" and not new_failures and known_failures:
            test["verdict"] = "PASS_WITH_KNOWN"
            test["reason"] = ""
            matrix["regression"] = {"verdict": "PASS_WITH_KNOWN",
                                    "reason": "",
                                    "newFailures": [],
                                    "knownFailures": known_failures}
        else:
            flaky = {r.get("name") for r in (baseline or {}).get("perTest") or []
                     if r.get("status") == "flaky"}
            matrix["regression"] = {
                "verdict": "FAIL" if new_failures else "PASS",
                "reason": "", "newFailures": new_failures,
                "knownFailures": known_failures + sorted(flaky & set(
                    r["name"] for r in fails))}
    # 白名单拒绝/环境损坏 = 想验验不了 → 整体降 C(宁可不验, 不可假验)
    for stage in ("build", "test"):
        r = matrix.get(stage)
        if r and r["verdict"] == "UNVERIFIABLE":
            matrix["overall"] = "C"
            matrix["reason"] = r["reason"]
            break
    else:
        if matrix["test"] and matrix["test"].get("structured"):
            matrix["overall"] = "A"          # V2: 结构化可判 → A 档
    return matrix


# ── V3 回归基线(作业基点临时 worktree 运行 + 磁盘缓存) ───────────────────

def baseline_cache_path(state_dir: str, root: str, base: str, cmd: str) -> str:
    import hashlib
    key = hashlib.sha1(f"{root}|{base}|{cmd}".encode()).hexdigest()[:16]
    return os.path.join(state_dir, "verify-baseline", f"{key}.json")


def load_baseline(state_dir: str, root: str, base: str, cmd: str) -> Optional[Dict[str, Any]]:
    p = baseline_cache_path(state_dir, root, base, cmd)
    if not os.path.isfile(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def run_baseline(root: str, base: str, test_cmd: str, state_dir: str,
                 timeout_mul: float = 1.0,
                 report_dir: str = "") -> Dict[str, Any]:
    """作业基点临时 worktree 跑一次 test 命令, 结果缓存(key: root+base+cmd 哈希)。

    基线失败(无工具链等) → {"perTest": [], "error": ...}——不阻塞实施, 仅延后对比。
    """
    cached = load_baseline(state_dir, root, base, test_cmd)
    if cached is not None:
        return cached
    tmp_wt = os.path.join(state_dir, "verify-baseline",
                          f"wt-{int(time.time() * 1000)}-{os.getpid()}")
    os.makedirs(os.path.dirname(tmp_wt), exist_ok=True)
    out: Dict[str, Any] = {"perTest": [], "summary": {}, "error": ""}
    try:
        r = subprocess.run(["git", "worktree", "add", "--detach", tmp_wt, base],
                           cwd=root, capture_output=True, text=True, check=True)
        result = _run_stage(tmp_wt, "test", test_cmd, "baseline",
                            timeout_mul, report_dir)
        out = {"perTest": result.get("perTest") or [],
               "summary": result.get("summary") or {},
               "error": result.get("logTail", "")[:400]}
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:400]
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", tmp_wt],
                       cwd=root, capture_output=True, text=True)
    p = baseline_cache_path(state_dir, root, base, test_cmd)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    return out


# ── V4 失败分类(R3 RunnerFailureRule 并入) + 修复回注判定 ────────────────

def classify_failure(matrix: Dict[str, Any], attempt: int = 1,
                     max_attempts: int = 3) -> Dict[str, Any]:
    """失败 → 分类 bundle: L1 编译/静态 / L2 定位明确的测试失败 / L3 症状≠根因。

    L3 判据(设计 §9.2): TIMEOUT / 结构化失败项 > 5 / 重复失败至轮次上限。
    R3 精神: 退出码单独永不构成失败类别——必须携带 verdict/reason 证据。
    """
    build = matrix.get("build") or {}
    test = matrix.get("test") or {}
    if build.get("verdict") == "FAIL":
        level, reason, log = "L1", build.get("reason") or "BUILD_FAILED", build
    elif test.get("verdict") == "FAIL":
        reason = test.get("reason") or "TEST_FAILED"
        fails = [r for r in test.get("perTest") or [] if r.get("status") == "failed"]
        # L3 判据: 超时 / 结构化大面积失败(>5) / 轮次已尽——否则按 L2 回注修复
        if reason == "TIMEOUT" or (fails and len(fails) > 5) or attempt > max_attempts:
            level = "L3"
        else:
            level = "L2"
        log = test
    else:
        level, reason, log = "L3", matrix.get("reason") or "UNCLASSIFIED", \
            test or build
    return {"level": level, "reason": reason, "attempt": attempt,
            "maxAttempts": max_attempts, "logTail": (log.get("logTail") or "")[-800:]}


def matrix_failed(matrix: Optional[Dict[str, Any]]) -> bool:
    """验收未过: B/A 档且任一环节 FAIL(仅存量失败 PASS_WITH_KNOWN 不算失败)。"""
    if not matrix or matrix.get("overall") not in ("A", "B"):
        return False
    return any((matrix.get(s) or {}).get("verdict") == "FAIL"
               for s in ("build", "test"))


def matrix_summary(matrix: Dict[str, Any]) -> str:
    """矩阵 → 单行摘要(事件 text 用)。"""
    overall = matrix.get("overall") or "?"
    if overall == "D":
        return "验收: D 仅人工审查(纯文档/资源变更)"
    if overall == "C":
        return f"验收: C 未能自动验收({matrix.get('reason') or 'NO_VERIFY_CONFIG'})"
    rows = []
    for stage in ("build", "test"):
        r = matrix.get(stage)
        if not r:
            continue
        mark = {"PASS": "✅", "FAIL": "❌"}.get(r["verdict"], "⚠️")
        rows.append(f"{stage} {mark} {r['verdict']}"
                    + (f"({r['reason']})" if r.get("reason") else "")
                    + f" [{r['source']}] {r['durationMs']}ms")
    return f"验收: B 自动执行——" + "；".join(rows)
