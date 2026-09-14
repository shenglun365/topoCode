"""ImplementSession — 会话驱动实施作业宿主（执行会话 ↔ coding agent 双向缓冲）。

与 /api/probe(即用即焚快照) 的本质差异：**worktree+分支保留**——真实实施落地。
与 /api/trees(退役 SE 任务树) 的差异：单作业单会话，无调度器。

生命周期：
  POST /api/implement        → worktree(-b 分支) + TurnAdapter(start_session) + 首轮
  GET  /api/implement/{id}   → {status, events[seq>since]}   architect 泵轮询(准实时)
  POST /api/implement/{id}/input {text}   ← 用户回复/确认/澄清/补充(缓冲, 回合空闲即发)
  POST /api/implement/{id}/abort          ← 中止当前回合
  POST /api/implement/{id}/finish         ← 结束作业(保 worktree, 释放执行器资源)
  GET  /api/implement/{id}/diff           ← 对 base 的最终 diff(验收素材)

执行器：经 TurnAdapter 适配多类型 coding agent(opencode serve / cline SDK /
codex app-server)，见 turn_adapter.py。POST /api/implement 可携
executorId/executorType/executorConfig(architect 侧执行器注册表下发)，
缺省回退 opencode。

回合标记契约(注入首轮 instruction, coding agent 遵守)：
  回合输出含 [[NEED_INPUT]]  → status=waiting_input(需要用户操作/确认/澄清/补充)
  回合输出含 [[IMPLEMENT_DONE]] → status=done(开发+单测+编译验收完成, 附摘要)
  其余回合结束(无标记)       → 视为 waiting_input(兜底: agent 提问未守约)

回合看门狗(与执行器无关, 只依赖 adapter.probe)：
  每 30s 探测一次——status=error 或 last_activity 停滞超过 stall 秒
  (默认 180, 请求 stallSec 可覆盖) → abort 回合并转 failed, 防执行器
  挂死(API 断开/通道断流)造成会话无限锁定; _TURN_TIMEOUT 兜底。
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

from .turn_adapter import TurnAdapter, build_adapter

logger = logging.getLogger(__name__)

_TURN_TIMEOUT = 3600.0
_WATCH_INTERVAL = 30.0
_WATCH_ABORT_GRACE = 10.0
_DEFAULT_STALL_SEC = 180.0

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
    """单个实施作业：worktree + TurnAdapter 会话 + 事件缓冲 + 输入缓冲。"""

    def __init__(self, job_id: str, root: str, wt: str, base: str, branch: str,
                 instruction: str, model: str = "", base_port: int = 3478,
                 auto_start: bool = True, base_url: str = "",
                 boundaries: Optional[Dict[str, Any]] = None,
                 adapter: Optional[TurnAdapter] = None,
                 turn_timeout: float = _TURN_TIMEOUT,
                 stall_sec: float = _DEFAULT_STALL_SEC,
                 project_id: str = ""):
        self.id = job_id
        self.root = os.path.abspath(root)
        self.wt = wt
        self.base = base
        self.branch = branch
        self.instruction = instruction
        # 操作边界(互斥引擎口径): {files: [路径/目录前缀], components: [KB 组件 id],
        # readOnly: bool(只读作业豁免写互斥)}
        self.boundaries = boundaries or {}
        self.model = model
        self.base_port = base_port
        self.auto_start = auto_start
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.status = "starting"      # starting/running/waiting_input/done/failed/stopped
        self.error = ""
        # 事件环 + 实时扇出(P3 schema 化: 形状单源 events.EventBus)
        from .events import EventBus
        self.bus = EventBus()
        self.session_id = ""
        self.serve_url = ""
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.turn_task: Optional[asyncio.Task] = None
        self.watch_task: Optional[asyncio.Task] = None
        self.pending_inputs: List[str] = []   # 用户输入缓冲(回合进行中排队)
        self._busy = False
        # 执行器适配 + 看门狗参数
        self.adapter: TurnAdapter = adapter or build_adapter(
            "opencode", "opencode",
            {"base_port": base_port, "auto_start": auto_start, "base_url": base_url})
        self.turn_timeout = float(turn_timeout)
        self.stall_sec = float(stall_sec)
        self.project_id = project_id
        # 活动信号(adapter 刷新; 看门狗消费)
        self.last_activity_ts = self.created_at
        self.last_error = ""
        self.sse_stop: Optional[asyncio.Event] = None

    # ── 事件缓冲 + 实时扇出(P3 委托 events.EventBus, 形状单源) ──
    # 事件粒度: 回合级(done/input_required/failed/aborted/finished/user_input/
    # session_ready)——非流式 token。流式扩展预留: adapter 在实时订阅回调
    # (opencode _sse_loop / codex notifications / cline sidecar events)中
    # 逐段 job.emit("text", 片段) 即可——事件环+WS 订阅面与 architect 泵
    # (推送优先/轮询兜底)原生承载, 无需改架构。

    @property
    def seq(self) -> int:
        return self.bus.seq

    @property
    def events(self) -> List[Dict[str, Any]]:
        return self.bus.events

    def emit(self, kind: str, text: str = "", **extra: Any) -> int:
        self.updated_at = time.time()
        return self.bus.emit(kind, text, **extra)

    def subscribe(self) -> asyncio.Queue:
        return self.bus.subscribe()

    def unsubscribe(self, q) -> None:
        self.bus.unsubscribe(q)

    def snapshot(self, since: int = 0) -> Dict[str, Any]:
        return {"jobId": self.id, "status": self.status, "error": self.error,
                "branch": self.branch, "worktree": self.wt, "root": self.root,
                "boundaries": self.boundaries,
                "sessionId": self.session_id,
                "executorId": self.adapter.executor_id,
                "lastActivityTs": self.last_activity_ts,
                "events": self.bus.since(since)}

    # ── 生命周期 ──

    async def start(self) -> None:
        try:
            await self.adapter.start_session(self)
            if not self.session_id:
                raise RuntimeError("执行器会话创建失败")
            self.emit("session_ready",
                      f"{self.adapter.executor_id} 会话就绪 serve={self.serve_url} "
                      f"session={self.session_id}")
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
        self.watch_task = asyncio.create_task(self._watch_turn(self.turn_task))

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
        try:
            outcome = await self.adapter.run_turn(self, text)
            output = outcome.output or ""
            changed = self._diff_files() or outcome.changed_files
            if _MARK_DONE in output:
                self.status = "done"
                self.emit("done", output, changedFiles=changed)
            elif _MARK_NEED in output or True:
                # 兜底: 无标记的回合结束也归为等待输入(agent 提问/未守约)
                self.status = "waiting_input"
                self.emit("input_required", output, changedFiles=changed)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            if self.status == "failed":
                # 看门狗已终态收口(abort 触发的本异常), 不重复 emit
                return
            self.status = "failed"
            self.error = str(e)
            self.emit("failed", f"回合执行失败: {e}")
            # 终态后 SSE 订阅(若有)不再有意义, 停止重连空转
            stop = getattr(self, "sse_stop", None)
            if stop:
                stop.set()
        finally:
            self._busy = False
            if self.status in ("waiting_input",) and self.pending_inputs:
                nxt = self.pending_inputs.pop(0)
                self._kick_turn(nxt)

    # ── 回合看门狗(执行器无关; 只依赖 adapter.probe/abort) ──

    async def _watch_turn(self, turn_task: asyncio.Task) -> None:
        """探测执行器: error/活动停滞 → abort 回合, 防会话无限锁定。"""
        try:
            while not turn_task.done() and self.status not in ("done", "failed", "stopped"):
                await asyncio.sleep(_WATCH_INTERVAL)
                if turn_task.done() or not self._busy:
                    return
                try:
                    p = await self.adapter.probe(self)
                except Exception as e:  # noqa: BLE001
                    logger.debug("[implement] probe %s: %s", self.id, e)
                    continue
                stall = max(0.0, time.time() - (p.last_activity_ts
                                                or self.last_activity_ts))
                reason = ""
                if p.status == "error":
                    reason = f"执行器通道错误: {p.last_error or 'unknown'}"
                elif p.status != "busy" and stall > self.stall_sec:
                    reason = (f"回合活动停滞 {stall:.0f}s(阈值 {self.stall_sec:.0f}s,"
                              "疑似 LLM 无响应/通道挂起)")
                if not reason:
                    continue
                logger.warning("[implement] watchdog %s: %s", self.id, reason)
                # 先终态(abort 后 run_turn 的终态检查/异常路径据此收口), 再中止回合
                self.status = "failed"
                self.error = reason
                self.emit("failed", f"⚠️ {reason}——已中止回合。")
                try:
                    await self.adapter.abort(self)
                except Exception as e:  # noqa: BLE001
                    logger.debug("[implement] watchdog abort %s: %s", self.id, e)
                try:
                    await asyncio.wait_for(asyncio.shield(turn_task),
                                           timeout=_WATCH_ABORT_GRACE)
                except asyncio.TimeoutError:
                    turn_task.cancel()
                except Exception:  # noqa: BLE001
                    pass
                return
        except asyncio.CancelledError:
            raise

    async def abort(self) -> Dict[str, Any]:
        ok = await self.adapter.abort(self)
        if ok:
            self.emit("aborted", "当前回合已被中止")
            return {"ok": True}
        return {"ok": False, "error": "执行器中止调用失败(回合可能仍在等待)"}

    async def finish(self, keep_worktree: bool = True) -> Dict[str, Any]:
        self.status = "stopped" if self.status != "done" else self.status
        self.emit("finished", f"作业结束(保 worktree={keep_worktree})")
        d = self.diff()
        try:
            self.adapter.dispose(self)
        except Exception:  # noqa: BLE001
            pass
        if self.watch_task and not self.watch_task.done():
            self.watch_task.cancel()
        out = {"ok": True, "status": self.status, "worktree": self.wt,
               "branch": self.branch, "executorId": self.adapter.executor_id}
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
        try:
            adapter = build_adapter(
                str(body.get("executorType") or ""),
                str(body.get("executorId") or ""),
                dict(body.get("executorConfig") or {}))
        except RuntimeError as e:
            # 如 remote-agent 等不适配交互式作业的类型: 明确报错(不静默回退)
            try:
                _git(["worktree", "remove", "--force", wt], cwd=root, check=False)
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False, "error": str(e)}
        job = ImplementJob(
            job_id, root, wt, base, branch, instruction + _COLLAB_PROTOCOL,
            model=str(body.get("model") or ""),
            base_port=int(body.get("basePort") or 3478),
            auto_start=bool(body.get("autoStart", True)),
            base_url=str(body.get("baseUrl") or ""),
            boundaries=body.get("boundaries") or {},
            adapter=adapter,
            turn_timeout=float(body.get("turnTimeout") or _TURN_TIMEOUT),
            stall_sec=float(body.get("stallSec") or _DEFAULT_STALL_SEC),
            project_id=str(body.get("projectId") or ""))
        _JOBS[job_id] = job
        # 子会话复活: 预置执行器原生会话 id(空=新建会话)
        job.session_id = str(body.get("sessionRef") or "")
        job.turn_task = asyncio.create_task(job.start())
        logger.info("[implement] job %s created root=%s branch=%s", job_id, root, branch)
        return {"ok": True, "jobId": job_id, "branch": branch, "worktree": wt,
                "status": job.status}

    @app.get("/api/implement/running")
    async def implement_running():
        """全局运行中(非终态)作业清单——architect 互斥引擎的校验数据源。"""
        return {"ok": True, "jobs": [
            {"jobId": j.id, "root": j.root, "branch": j.branch,
             "status": j.status, "boundaries": j.boundaries}
            for j in _JOBS.values() if j.status not in ("done", "failed", "stopped")]}

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

    @app.websocket("/api/implement/{job_id}/events")
    async def implement_events(websocket: WebSocket, job_id: str):
        """作业事件实时订阅(上行通道推送面, 执行器能力自适应)。

        执行器实时(opencode SSE/codex notifications)→事件即产即推;
        执行器轮询型→事件仍按已知时点推送。?since=N 先回放环内 seq>N,
        再实时转发; done/failed 终态排空后关闭。客户端断线可携 since 重连续传。
        流式扩展: 见 ImplementJob.emit 注释——adapter 逐段 emit("text") 即经本
        端点推送, architect 泵落 job_progress 消息, 架构零改动。
        """
        job = _JOBS.get(job_id)
        if not job:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        try:
            since = 0
            qs = (websocket.query_params.get("since") or "0").strip()
            try:
                since = int(qs)
            except ValueError:
                since = 0
            # 回放环内积压(订阅竞态窗口的补齐)
            for e in list(job.events):
                if e.get("seq", 0) > since:
                    await websocket.send_json(e)
            if job.status in ("done", "failed", "stopped"):
                return
            q = job.subscribe()
            try:
                while True:
                    ev = await asyncio.wait_for(q.get(), timeout=60.0)
                    await websocket.send_json(ev)
                    if ev.get("kind") in ("done", "failed"):
                        return
            finally:
                job.unsubscribe(q)
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            pass
