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
                  duration_ms: int = 0, log_tail: str = "") -> Dict[str, Any]:
    return {"stage": stage, "verdict": verdict, "reason": reason,
            "cmd": cmd, "source": source, "exitCode": exit_code,
            "durationMs": duration_ms, "logTail": log_tail}


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
               timeout_mul: float) -> Dict[str, Any]:
    """L2 执行: cwd=wt 白名单前置 + 超时分级 + 输出头尾截断(确定性反馈)。"""
    if not _command_allowed(cmd):
        return _stage_result(cmd, source, stage, "UNVERIFIABLE",
                             "WHITELIST_REJECTED")
    timeout = max(1.0, _BASE_TIMEOUT.get(stage, 300.0) * (timeout_mul or 1.0))
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=wt, shell=True, capture_output=True,
                              text=True, timeout=timeout,
                              env={**os.environ, "CI": "1"})
        duration = int((time.monotonic() - started) * 1000)
        combined = ((proc.stdout or "") + (proc.stderr or "")).strip()
        verdict = "PASS" if proc.returncode == 0 else "FAIL"
        reason = "" if proc.returncode == 0 else (
            "TIMEOUT" if verdict == "FAIL" and duration >= timeout * 990 else "")
        return _stage_result(cmd, source, stage, verdict, reason,
                             exit_code=proc.returncode, duration_ms=duration,
                             log_tail=_tail(combined))
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
                     changed_files: Optional[List[str]] = None) -> Dict[str, Any]:
    """V1 门禁入口: 发现 → 执行 → 级别判定。返回验证矩阵(事件载荷形状)。

    overall: B(有执行)/C(想验验不了)/D(仅人工审查); A 档待 V2 结构化适配器。
    每环节独立判定; 禁止假通过——无法验证必带原因码。
    """
    changed = [str(f) for f in (changed_files or [])]
    if _pure_docs(changed):
        return {"overall": "D", "reason": "PURE_DOCS", "build": None, "test": None}
    cfg = config if isinstance(config, dict) else {}
    mul = float(cfg.get("timeoutMul") or 1.0)
    plan = discover_verify(wt, cfg)
    if plan["level"] == "C":
        return {"overall": "C", "reason": plan["reason"],
                "build": None, "test": None}
    matrix: Dict[str, Any] = {"overall": "B", "reason": "", "build": None, "test": None}
    if plan["build"]:
        matrix["build"] = _run_stage(wt, "build", plan["build"]["cmd"],
                                     plan["build"]["source"], mul)
    if plan["test"]:
        matrix["test"] = _run_stage(wt, "test", plan["test"]["cmd"],
                                    plan["test"]["source"], mul)
    # 白名单拒绝/环境损坏 = 想验验不了 → 整体降 C(宁可不验, 不可假验)
    for stage in ("build", "test"):
        r = matrix.get(stage)
        if r and r["verdict"] == "UNVERIFIABLE":
            matrix["overall"] = "C"
            matrix["reason"] = r["reason"]
            break
    return matrix


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
