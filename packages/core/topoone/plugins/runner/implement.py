"""ImplementSession — 会话驱动实施作业宿主（执行会话 ↔ coding agent 双向缓冲）。

与 /api/probe(即用即焚快照) 的本质差异：**worktree+分支保留**——真实实施落地。
与 /api/trees(退役 SE 任务树) 的差异：单作业单会话，无调度器。

生命周期：
  POST /api/implement        → worktree(-b 分支) + opencode serve + session + 首轮
  GET  /api/implement/{id}   → {status, events[seq>since]}   architect 泵轮询(准实时)
  POST /api/implement/{id}/input {text}   ← 用户回复/确认/澄清(缓冲, 回合空闲即发)
  POST /api/implement/{id}/abort          ← 中止当前回合
  POST /api/implement/{id}/finish         ← 结束作业(保 worktree, 释放 serve)
  GET  /api/implement/{id}/diff           ← 对 base 的最终 diff(验收素材)

回合标记契约(注入首轮 instruction, coding agent 遵守)：
  回合输出含 [[NEED_INPUT]]  → status=waiting_input(需要用户操作/确认/澄清/补充)
  回合输出含 [[IMPLEMENT_DONE]] → status=done(开发+单测+编译验收完成, 附摘要)
  其余回合结束(无标记)       → 视为 waiting_input(兜底: agent 提问未守约)
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Request

from .executors.opencode import OpenCodeServeManager

logger = logging.getLogger(__name__)

_MAX_EVENTS = 800
_TURN_TIMEOUT = 3600.0

_MARK_NEED = "[[NEED_INPUT]]"
_MARK_DONE = "[[IMPLEMENT_DONE]]"

_COLLAB_PROTOCOL = """

## 协作协议(必须遵守)
- 需要用户操作/确认/澄清/补充时：在回合输出中写 `[[NEED_INPUT]]` 并附具体问题，然后结束回合等待用户。
- 开发+单元测试+整体编译验收全部完成时：在回合输出中写 `[[IMPLEMENT_DONE]]`，附摘要(变更文件/单测结果/编译结果/遗留项)，然后结束回合。
- 严禁在未完成上述三项交付时输出 `[[IMPLEMENT_DONE]]`。
- 除上述两个标记外不要输出其他 [[...]] 标记。
"""


def _git(args: list, cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args[0]} 失败: {r.stderr.strip()[:300]}")
    return r


class ImplementJob:
    """单个实施作业：worktree + opencode session + 事件缓冲 + 输入缓冲。"""

    def __init__(self, job_id: str, root: str, wt: str, base: str, branch: str,
                 instruction: str, model: str = "", base_port: int = 3478,
                 auto_start: bool = True, base_url: str = ""):
        self.id = job_id
        self.root = os.path.abspath(root)
        self.wt = wt
        self.base = base
        self.branch = branch
        self.instruction = instruction
        self.model = model
        self.base_port = base_port
        self.auto_start = auto_start
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.status = "starting"      # starting/running/waiting_input/done/failed/stopped
        self.error = ""
        self.seq = 0
        self.events: List[Dict[str, Any]] = []
        self.session_id = ""
        self.serve_url = ""
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.turn_task: Optional[asyncio.Task] = None
        self.pending_inputs: List[str] = []   # 用户输入缓冲(回合进行中排队)
        self._busy = False
        self._mgr = OpenCodeServeManager(base_port=base_port, auto_start=auto_start)

    # ── 事件缓冲 ──

    def emit(self, kind: str, text: str = "", **extra: Any) -> int:
        self.seq += 1
        ev = {"seq": self.seq, "ts": int(time.time() * 1000),
              "kind": kind, "text": (text or "")[:20000]}
        ev.update(extra)
        self.events.append(ev)
        if len(self.events) > _MAX_EVENTS:
            self.events = self.events[-_MAX_EVENTS:]
        self.updated_at = time.time()
        return ev["seq"]

    def snapshot(self, since: int = 0) -> Dict[str, Any]:
        return {"jobId": self.id, "status": self.status, "error": self.error,
                "branch": self.branch, "worktree": self.wt,
                "sessionId": self.session_id,
                "events": [e for e in self.events if e["seq"] > since]}

    # ── 生命周期 ──

    async def start(self) -> None:
        try:
            sp = await self._mgr.ensure(self.wt)
            self.serve_url = sp.url
            headers = {"Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=30.0, headers=headers) as c:
                r = await c.post(f"{sp.url}/session", json={"title": self.id})
                r.raise_for_status()
                self.session_id = (r.json() or {}).get("id") or ""
            if not self.session_id:
                raise RuntimeError("opencode session 创建失败")
            self.emit("session_ready", f"opencode 会话就绪 serve={sp.url} session={self.session_id}")
            self.status = "running"
            self._kick_turn(self.instruction)
        except Exception as e:  # noqa: BLE001
            self.status = "failed"
            self.error = str(e)
            self.emit("failed", f"作业启动失败: {e}")

    def _kick_turn(self, text: str) -> None:
        if self._busy:
            self.pending_inputs.append(text)
            return
        self._busy = True
        self.status = "running"
        self.turn_task = asyncio.create_task(self._run_turn(text))

    async def user_input(self, text: str) -> Dict[str, Any]:
        if self.status in ("done", "failed", "stopped"):
            return {"ok": False, "error": f"作业已终态({self.status})，不可追加输入"}
        self.emit("user_input", text)
        if self._busy:
            self.pending_inputs.append(text)
            return {"ok": True, "queued": True}
        self._kick_turn(text)
        return {"ok": True, "queued": False}

    async def _run_turn(self, text: str) -> None:
        headers = {"Content-Type": "application/json"}
        body: Dict[str, Any] = {"parts": [{"type": "text", "text": text}]}
        if self.model:
            if "/" in self.model:
                pid, mid = self.model.split("/", 1)
                body["model"] = {"providerID": pid, "modelID": mid}
            else:
                body["model"] = {"modelID": self.model}
        try:
            async with httpx.AsyncClient(timeout=_TURN_TIMEOUT, headers=headers) as c:
                r = await c.post(
                    f"{self.serve_url}/session/{self.session_id}/message", json=body)
                r.raise_for_status()
                data = r.json() or {}
            output = ""
            for part in (data.get("parts") or [])[::-1]:
                if part.get("type") == "text" and part.get("text"):
                    output = part["text"]
                    break
            changed = self._diff_files()
            if _MARK_DONE in output:
                self.status = "done"
                self.emit("done", output, changedFiles=changed)
            elif _MARK_NEED in output or True:
                # 兜底: 无标记的回合结束也归为等待输入(agent 提问/未守约)
                self.status = "waiting_input"
                self.emit("input_required", output, changedFiles=changed)
        except Exception as e:  # noqa: BLE001
            self.status = "failed"
            self.error = str(e)
            self.emit("failed", f"回合执行失败: {e}")
        finally:
            self._busy = False
            if self.status in ("waiting_input",) and self.pending_inputs:
                nxt = self.pending_inputs.pop(0)
                self._kick_turn(nxt)

    async def abort(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                await c.post(f"{self.serve_url}/session/{self.session_id}/abort")
            self.emit("aborted", "当前回合已被中止")
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    async def finish(self, keep_worktree: bool = True) -> Dict[str, Any]:
        self.status = "stopped" if self.status != "done" else self.status
        self.emit("finished", f"作业结束(保 worktree={keep_worktree})")
        d = self.diff()
        try:
            self._mgr.dispose_root(self.wt)
        except Exception:  # noqa: BLE001
            pass
        out = {"ok": True, "status": self.status, "worktree": self.wt,
               "branch": self.branch}
        out.update(d)
        return out

    # ── diff ──

    def _diff_files(self) -> List[str]:
        try:
            _git(["add", "-A", "-N"], cwd=self.wt, check=False)
            st = _git(["status", "--porcelain"], cwd=self.wt, check=False)
            return [ln[3:].strip() for ln in st.stdout.splitlines() if ln.strip()]
        except Exception:  # noqa: BLE001
            return []

    def diff(self) -> Dict[str, Any]:
        try:
            _git(["add", "-A", "-N"], cwd=self.wt, check=False)
            d = _git(["diff", self.base], cwd=self.wt, check=False)
            add = sum(1 for ln in d.stdout.splitlines()
                      if ln.startswith("+") and not ln.startswith("+++"))
            dele = sum(1 for ln in d.stdout.splitlines()
                       if ln.startswith("-") and not ln.startswith("---"))
            return {"changedFiles": self._diff_files(), "diff": d.stdout[:200000],
                    "addLines": add, "delLines": dele}
        except Exception as e:  # noqa: BLE001
            return {"changedFiles": [], "diff": "", "error": str(e)}


_JOBS: Dict[str, ImplementJob] = {}


def _wt_root_dir() -> str:
    d = os.environ.get("TOPOCODE_DB_DIR") or os.path.join(
        os.path.expanduser("~"), ".topocode")
    p = os.path.join(d, "runner", "implement")
    os.makedirs(p, exist_ok=True)
    return p


def register(app: FastAPI) -> None:
    """把实施作业端点挂到 runner FastAPI。"""

    @app.post("/api/implement")
    async def create_implement(request: Request):
        body = await request.json()
        root = os.path.abspath(body.get("root") or "")
        instruction = (body.get("instruction") or "").strip()
        if not root or not os.path.isdir(root):
            return {"ok": False, "error": "root 无效"}
        if not instruction:
            return {"ok": False, "error": "instruction 为空"}
        base = body.get("baseCommit") or "HEAD"
        branch = (body.get("branchName") or "").strip() or f"exec/{uuid.uuid4().hex[:8]}"
        job_id = f"impl-{uuid.uuid4().hex[:10]}"
        wt = os.path.join(_wt_root_dir(), job_id)
        try:
            os.makedirs(os.path.dirname(wt), exist_ok=True)
            r = _git(["worktree", "add", "-b", branch, wt, base], cwd=root, check=False)
            if r.returncode != 0:
                # 分支已存在等场景: 重试 detach? 直接报错(architect 侧换名)
                return {"ok": False, "error": f"worktree 创建失败: {r.stderr.strip()[:300]}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        job = ImplementJob(
            job_id, root, wt, base, branch, instruction + _COLLAB_PROTOCOL,
            model=str(body.get("model") or ""),
            base_port=int(body.get("basePort") or 3478),
            auto_start=bool(body.get("autoStart", True)),
            base_url=str(body.get("baseUrl") or ""))
        _JOBS[job_id] = job
        job.turn_task = asyncio.create_task(job.start())
        logger.info("[implement] job %s created root=%s branch=%s", job_id, root, branch)
        return {"ok": True, "jobId": job_id, "branch": branch, "worktree": wt,
                "status": job.status}

    @app.get("/api/implement/{job_id}")
    async def implement_snapshot(job_id: str, since: int = 0):
        job = _JOBS.get(job_id)
        if not job:
            return {"ok": False, "error": "作业不存在"}
        return {"ok": True, **job.snapshot(since)}

    @app.post("/api/implement/{job_id}/input")
    async def implement_input(job_id: str, request: Request):
        job = _JOBS.get(job_id)
        if not job:
            return {"ok": False, "error": "作业不存在"}
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "text 为空"}
        return await job.user_input(text)

    @app.post("/api/implement/{job_id}/abort")
    async def implement_abort(job_id: str):
        job = _JOBS.get(job_id)
        if not job:
            return {"ok": False, "error": "作业不存在"}
        return await job.abort()

    @app.post("/api/implement/{job_id}/finish")
    async def implement_finish(job_id: str, request: Request):
        job = _JOBS.get(job_id)
        if not job:
            return {"ok": False, "error": "作业不存在"}
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        return await job.finish(bool(body.get("keepWorktree", True)))

    @app.get("/api/implement/{job_id}/diff")
    async def implement_diff(job_id: str):
        job = _JOBS.get(job_id)
        if not job:
            return {"ok": False, "error": "作业不存在"}
        return {"ok": True, **job.diff()}
