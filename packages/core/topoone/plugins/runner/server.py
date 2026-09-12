"""Coding Agent Runner — 会话作业执行宿主(单一执行面)。

执行原语: implement.ImplementJob(TurnAdapter 适配 opencode/cline/codex)。
probe(方案草图)复用同一适配面的一次性单回合(worktree 快照, 用完即清)。

历史: SE 树调度器(TaskTreeScheduler/ExecutorPool/runner.db)已整体退役,
执行器配置由 architect 单源管理(arch_collab_config), 作业按 executorId
显式路由(build_adapter), 不再存在 runner 侧执行器池与启动期配置拉取。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
import uuid
from typing import Optional

from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)

app = FastAPI(title="coding-agent-runner")

PORT = int(os.environ.get("RUNNER_PORT", "3458"))
DATA_DIR = os.environ.get("TOPOCODE_DB_DIR") or os.path.join(
    os.path.expanduser("~"), ".topocode")
STATE_DIR = os.path.join(DATA_DIR, "runner", "state")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)


def _git(args: list, cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=check)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "coding-agent-runner", "port": PORT}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# ── probe: worktree 方案草图(一次性单回合, 与 implement 同一适配面) ──

_PROBE_HARNESS = (
    "【probe 方案草图模式】\n"
    "- 你在 git worktree 快照中工作，改动不影响主工作区\n"
    "- 禁止 git commit / branch / push / checkout 等仓库操作；只编辑文件表达方案\n"
    "- 禁止运行构建/测试/安装依赖(worktree 无构建产物，属正常)\n"
    "- 先读相关代码理解现状，再用最小文件改动表达方案(伪 diff)\n"
    "- 结束时用 3-5 行总结改动思路与影响面\n"
)


class _ProbeJob:
    """probe 一次性回合的 job 形参 shim(TurnAdapter 鸭子类型)。"""

    def __init__(self, wt: str, model: str, turn_timeout: float):
        self.id = f"probe-{uuid.uuid4().hex[:8]}"
        self.wt = wt
        self.model = model or ""
        self.session_id = ""
        self.serve_url = ""
        self.last_activity_ts = time.time()
        self.last_error = ""
        self.turn_timeout = turn_timeout
        self.sse_stop = None


@app.post("/api/probe")
async def run_probe(request: Request):
    """probe: worktree 快照上执行 coding agent 产出方案草图 + diff。

    body: {root, baseCommit?, instruction, files?, model?,
           executorId?, executorType?, executorConfig?, timeoutS?}
    返回 {ok, status, changedFiles, diff, summary, executorError}。结束即清理 worktree。
    """
    from .turn_adapter import build_adapter

    body = await request.json()
    root = os.path.abspath(body.get("root") or "")
    instruction = (body.get("instruction") or "").strip()
    if not root or not os.path.isdir(root):
        return {"ok": False, "error": "root 无效"}
    if not instruction:
        return {"ok": False, "error": "instruction 为空"}
    base = body.get("baseCommit") or "HEAD"
    files = [str(f) for f in (body.get("files") or []) if str(f).strip()]
    timeout_s = min(max(int(body.get("timeoutS") or 900), 60), 3600)

    try:
        adapter = build_adapter(
            str(body.get("executorType") or ""),
            str(body.get("executorId") or ""),
            dict(body.get("executorConfig") or {}))
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    probe_dir = os.path.join(STATE_DIR, "probes")
    os.makedirs(probe_dir, exist_ok=True)
    wt = os.path.join(probe_dir, f"probe-{int(time.time() * 1000)}")

    def _cleanup_worktree() -> None:
        _git(["worktree", "remove", "--force", wt], cwd=root, check=False)
        _git(["worktree", "prune"], cwd=root, check=False)

    r = _git(["worktree", "add", "--detach", wt, base], cwd=root, check=False)
    if r.returncode != 0:
        return {"ok": False, "error": f"worktree 创建失败: {r.stderr.strip()[:300]}"}

    prompt = _PROBE_HARNESS
    if files:
        prompt += "\n相关文件：\n" + "\n".join(f"- {f}" for f in files[:50]) + "\n"
    prompt += "\n" + instruction

    job = _ProbeJob(wt, str(body.get("model") or ""), float(timeout_s))
    status, executor_error = "done", ""
    try:
        try:
            await adapter.start_session(job)
            outcome = await asyncio.wait_for(adapter.run_turn(job, prompt),
                                             timeout=float(timeout_s))
            if getattr(outcome, "output", None) is None and job.last_error:
                status, executor_error = "failed", job.last_error[:500]
        except asyncio.TimeoutError:
            status, executor_error = "timeout", f"probe 回合超时({timeout_s}s)"
            try:
                await adapter.abort(job)
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            status, executor_error = "failed", str(e)[:500]

        # diff 提取(未跟踪文件 intent-to-add 纳入)——须在 worktree 清理前
        _git(["add", "-A", "-N"], cwd=wt, check=False)
        d = _git(["diff"], cwd=wt, check=False)
        st = _git(["status", "--porcelain"], cwd=wt, check=False)
        changed = [line[3:].strip() for line in st.stdout.splitlines() if line.strip()]
        add = del_ = 0
        for line in d.stdout.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                add += 1
            elif line.startswith("-") and not line.startswith("---"):
                del_ += 1
    finally:
        try:
            adapter.dispose(job)
        except Exception:  # noqa: BLE001
            pass
        _cleanup_worktree()

    summary = (f"probe {status}; {len(changed)} 个文件变更(+{add}/-{del_} 行)"
               + (f"; 执行器异常: {executor_error[:200]}" if executor_error else ""))
    return {
        "ok": status == "done",
        "status": status,
        "changedFiles": changed,
        "diff": d.stdout[:200_000],
        "summary": summary,
        "executorError": executor_error,
    }


def main():
    logging.basicConfig(level=logging.INFO)
    from topoone.http_logging import install_heartbeat_filter
    install_heartbeat_filter()
    from . import implement
    implement.register(app)
    logger.info("[runner] starting on port %s (execution plane: TurnAdapter)", PORT)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
