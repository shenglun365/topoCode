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
import hashlib
import logging
import os
import subprocess
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

from .loopguard import LoopGuard
from .turn_adapter import TurnAdapter, build_adapter

logger = logging.getLogger(__name__)

_TURN_TIMEOUT = 3600.0
_WATCH_INTERVAL = 30.0
_WATCH_ABORT_GRACE = 10.0
_DEFAULT_STALL_SEC = 180.0
# 无进展看门狗: worktree 状态哈希连续 N 个探测周期不变(已动过文件的前提下)
# → 判定循环空转(环节十一)。10×30s=5min——纯编译/命令重跑无文件变化即命中;
# 正常编辑-编译循环每次编辑都会改变内容哈希 → 计数归零。
# 5min 而非 3min: 全量重建/长冒烟套件可无写入运行数分钟(误伤排查, cv-181 同类)
_PROGRESS_TICKS = 10

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
                 project_id: str = "",
                 verify_config: Optional[Dict[str, Any]] = None):
        self.id = job_id
        self.root = os.path.abspath(root)
        self.wt = wt
        self.base = base
        self.branch = branch
        # 字面 HEAD 钉死为具体 SHA(自动 commit 进度后 diff HEAD 会恒空——
        # 验收 diff/变更文件全丢; 钉 SHA 后 diff 永远对准任务基点)
        if str(base).strip() in ("HEAD", "") and wt and os.path.isdir(wt):
            try:
                self.base = _git(["rev-parse", "HEAD"], wt).stdout.strip()
            except Exception:  # noqa: BLE001
                self.base = base
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
        # A6.3 TurnContext: 作业级上下文事实 + 每轮快照(恢复/合并检查/审计消费)
        self.turn_context: Dict[str, Any] = {
            "model": model, "base": self.base, "branch": branch,
            "root": self.root, "executorId": self.adapter.executor_id,
            "turns": []}
        # A6.1 反向请求登记表: approval_request 在答 → 断线重连/恢复后宿主可见
        # (dsh queued-minus-delivered 最小形态; 应答经 /approval 销账)
        self.pending_requests: Dict[str, Dict[str, Any]] = {}
        self.turn_timeout = float(turn_timeout)
        self.stall_sec = float(stall_sec)
        self.project_id = project_id
        # V1 程序化验收门禁: start payload.verify {build?, test?, timeoutMul?,
        # maxAttempts?, autoRepair?}; V4 修复回注计数 + V5 DONE 诚实化连击
        self.verify_config = verify_config if isinstance(verify_config, dict) else {}
        self.verify_attempts = 0
        self.verify_max_attempts = int((self.verify_config or {}).get("maxAttempts") or 3)
        self.auto_repair = bool((self.verify_config or {}).get("autoRepair", True))
        self.done_mismatch_streak = 0
        self.baseline: Optional[Dict[str, Any]] = None
        self._repair_queue: List[str] = []
        # 活动信号(adapter 刷新; 看门狗消费)
        self.last_activity_ts = self.created_at
        self.last_error = ""
        self.sse_stop: Optional[asyncio.Event] = None
        # 循环护栏(环节十一): 事件面检测器(cline 流式喂入) + 无进展看门狗状态
        self.loop_guard = LoopGuard()
        self._loop_verdict = ""
        self._progress_hash = ""
        self._progress_stall = 0
        self._progress_armed = False

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
                "turnContext": {**self.turn_context,
                                "turns": self.turn_context["turns"][-5:]},
                "pendingApprovals": [
                    {"requestId": rid, **{k: v for k, v in row.items()
                                          if k != "requestId"}}
                    for rid, row in sorted(self.pending_requests.items())],
                "events": self.bus.since(since)}

    # ── A6.1 反向请求登记(A5 切片: 应答前可见) ──

    def register_pending_request(self, request_id: str, tool_name: str = "",
                                 tool_input: Any = None) -> None:
        if not request_id:
            return
        self.pending_requests[str(request_id)] = {
            "toolName": str(tool_name or ""), "toolInput": tool_input,
            "ts": int(time.time() * 1000)}

    def resolve_pending_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        return self.pending_requests.pop(str(request_id or ""), None)

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
            if isinstance(self.verify_config, dict) and \
                    (self.verify_config.get("test") or ""):
                # V3 回归基线: 异步预跑基点测试(不阻塞实施; 未完成仅延后对比)
                asyncio.create_task(self._prepare_baseline())
            self._kick_turn(self.instruction)
        except Exception as e:  # noqa: BLE001
            self.status = "failed"
            self.error = str(e)
            self._commit_progress()
            self.emit("failed", f"作业启动失败: {e}")

    def _reset_turn_guard(self) -> None:
        """循环护栏状态按回合复位(指纹/签名是回合内概念)。"""
        self.loop_guard = LoopGuard()
        self._loop_verdict = ""
        self._progress_hash = ""
        self._progress_stall = 0
        self._progress_armed = False

    def _kick_turn(self, text: str) -> None:
        if self._busy:
            self.pending_inputs.append(text)
            return
        self._busy = True
        self.status = "running"
        self._reset_turn_guard()
        self.turn_task = asyncio.create_task(self._run_turn(text))
        self.watch_task = asyncio.create_task(self._watch_turn(self.turn_task))

    def observe(self, kind: str, text: str = "", tool_name: str = "") -> None:
        """适配器事件喂入口(事件循环线程内同步调用): 循环检测, 置旗标由
        _watch_turn 消费——解耦 sidecar 回调上下文与异步中止路径。"""
        loop, reason = self.loop_guard.feed(kind, text=text, tool_name=tool_name)
        if loop and not self._loop_verdict:
            self._loop_verdict = reason

    async def user_input(self, text: str, steer: bool = False) -> Dict[str, Any]:
        """用户输入：不 busy 触发新回合；busy 时 steer=true 且执行器支持 →
        直达注入（cline pending 优先投递），否则排队缓冲。"""
        if self.status in ("done", "failed", "stopped"):
            return {"ok": False, "error": f"作业已终态({self.status})，不可追加输入"}
        if self._busy and steer:
            steer_fn = getattr(self.adapter, "steer", None)
            if steer_fn is not None:
                try:
                    if await steer_fn(self, text):
                        self.emit("user_input", text, steered=True)
                        return {"ok": True, "steered": True}
                except Exception:  # noqa: BLE001
                    pass
        self.emit("user_input", text)
        if self._busy:
            self.pending_inputs.append(text)
            return {"ok": True, "queued": True}
        self._kick_turn(text)
        return {"ok": True, "queued": False}

    async def _prepare_baseline(self) -> None:
        """V3: 基点临时 worktree 异步跑一次基线测试(缓存 key: root+base+cmd)。"""
        try:
            from . import verify as _verify
            cmd = str(self.verify_config.get("test") or "").strip()
            if not cmd:
                plan = _verify.discover_verify(self.wt, self.verify_config)
                cmd = (plan.get("test") or {}).get("cmd") or ""
            if not cmd:
                return
            self.baseline = await asyncio.to_thread(
                _verify.run_baseline, self.root, self.base, cmd,
                self._verify_state_dir(),
                float(self.verify_config.get("timeoutMul") or 1.0),
                self._verify_state_dir())
            logger.info("[implement] baseline ready job=%s tests=%s",
                        self.id, len((self.baseline or {}).get("perTest") or []))
        except Exception as e:  # noqa: BLE001
            logger.warning("[implement] baseline failed job=%s: %s", self.id, e)

    def _verify_state_dir(self) -> str:
        """门禁状态目录(基线缓存/结构化报告)——job 级隔离。"""
        base_dir = os.environ.get("TOPOCODE_DB_DIR") or os.path.join(
            os.path.expanduser("~"), ".topocode")
        p = os.path.join(base_dir, "runner", "verify-reports", self.id)
        os.makedirs(p, exist_ok=True)
        return p

    async def _run_verify_gate(self, changed: List[str]) -> Optional[Dict[str, Any]]:
        """V1/V2 验收门禁: done 自述后实测验证, 矩阵落 verify 事件并返回。

        None = 门禁未启用/不可用(逃生开关/无有效 worktree/内部异常)。
        """
        if os.environ.get("RUNNER_VERIFY_DISABLE") == "1":
            return None
        if not self.wt or not os.path.isdir(self.wt):
            return None                 # 无有效 worktree(测试桩/异常作业): 无从验证
        try:
            from . import verify as _verify
            matrix = await asyncio.to_thread(
                _verify.verify_and_judge, self.wt, self.verify_config, changed,
                self.baseline, self._verify_state_dir())
            self.emit("verify", _verify.matrix_summary(matrix), **matrix)
            return matrix
        except Exception as e:  # noqa: BLE001
            logger.warning("[implement] verify gate failed job=%s: %s", self.id, e)
            return None

    async def _handle_verify_failure(self, matrix: Dict[str, Any],
                                     changed: List[str], output: str) -> None:
        """V4/V5: 验收未过 → L1/L2 自动修复回注(上限 verify_max_attempts);
        L3/轮次尽/连续 2 轮 DONE 与实测不符 → waiting_input 退回并附确定性 bundle。"""
        from . import verify as _verify
        self.verify_attempts += 1
        self.done_mismatch_streak += 1
        bundle = _verify.classify_failure(matrix, attempt=self.verify_attempts,
                                          max_attempts=self.verify_max_attempts)
        repairable = (bundle["level"] in ("L1", "L2")
                      and self.verify_attempts <= self.verify_max_attempts
                      and self.auto_repair)
        if not repairable:
            if self.done_mismatch_streak >= 2:
                hint = (f"连续 {self.done_mismatch_streak} 轮 DONE 声明与验证结果不符"
                        "——已退回人工介入(提示: 当前模型可能不足以胜任该任务,"
                        "建议降档 T3/T4 或人工预拆)。")
            elif bundle["level"] == "L3":
                hint = "失败超出可自动修复范畴(L3 症状≠根因/超时/大面积失败)。"
            else:
                hint = "自动修复轮次已用尽。"
            self.status = "waiting_input"
            self._commit_progress()
            self.emit("input_required",
                      f"[[NEED_INPUT]] DONE 声明与验证结果不符, 已退回。\n"
                      f"{hint}\n失败分类: {bundle['level']} ({bundle['reason']}, "
                      f"第 {bundle['attempt']}/{bundle['maxAttempts']} 轮)\n"
                      f"证据(尾部):\n{bundle['logTail']}",
                      changedFiles=changed)
            return
        self.status = "running"
        self.emit("notice",
                  f"⛔ 验收未过(第 {bundle['attempt']}/{bundle['maxAttempts']} 轮, "
                  f"{bundle['level']}: {bundle['reason']})——自动修复回注。",
                  reason="verify_repair")
        self._repair_queue.append(
            f"上一轮你报告 [[IMPLEMENT_DONE]], 但程序化验收未过"
            f"({bundle['level']}: {bundle['reason']}, 第 {bundle['attempt']}/"
            f"{bundle['maxAttempts']} 轮)。\n失败证据(尾部):\n{bundle['logTail']}\n"
            "请**仅修复上述失败**, 不要改动测试断言或为迁就测试改源码结构; "
            "修复完成后照常 [[IMPLEMENT_DONE]]。")

    async def _run_turn(self, text: str) -> None:
        # A6.3 TurnContext: 每轮快照(回合号/时点/模型——恢复与审计消费)
        self.turn_context["turns"].append({
            "turn": len(self.turn_context["turns"]) + 1,
            "startedAt": int(time.time() * 1000),
            "model": self.model or ""})
        self.turn_context["turns"] = self.turn_context["turns"][-20:]
        try:
            outcome = await self.adapter.run_turn(self, text)
            output = outcome.output or ""
            changed = self._diff_files() or outcome.changed_files
            if _MARK_DONE in output:
                # V4/V5: 先实测验证再定终态——DONE 自述与实测不符时退回/修复回注
                from . import verify as _verify
                matrix = await self._run_verify_gate(changed)
                if _verify.matrix_failed(matrix):
                    await self._handle_verify_failure(matrix, changed, output)
                    return
                self.done_mismatch_streak = 0
                self.status = "done"
                self._commit_progress()
                self.emit("done", output, changedFiles=changed)
            elif _MARK_NEED in output or True:
                # 兜底: 无标记的回合结束也归为等待输入(agent 提问/未守约)
                self.status = "waiting_input"
                self._commit_progress()
                self.emit("input_required", output, changedFiles=changed)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            if self.status == "failed":
                # 看门狗已终态收口(abort 触发的本异常), 不重复 emit
                return
            self.status = "failed"
            self.error = str(e)
            self._commit_progress()
            self.emit("failed", f"回合执行失败: {e}")
            # 终态后 SSE 订阅(若有)不再有意义, 停止重连空转
            stop = getattr(self, "sse_stop", None)
            if stop:
                stop.set()
        finally:
            self._busy = False
            # V4: 验收失败修复回注轮(先于 waiting_input 队列——状态互斥不冲突)
            if self._repair_queue and self.status == "running":
                nxt = self._repair_queue.pop(0)
                self._kick_turn(nxt)
            elif self.status in ("waiting_input",) and self.pending_inputs:
                nxt = self.pending_inputs.pop(0)
                self._kick_turn(nxt)

    # ── 回合看门狗(执行器无关; 只依赖 adapter.probe/abort) ──

    async def _fail_turn(self, reason: str, turn_task: asyncio.Task) -> None:
        """回合异常收口单源(看门狗/循环检测共用): 终态 → 进度 commit →
        failed 事件 → abort 回合 → 宽限等待/强杀。"""
        logger.warning("[implement] watchdog %s: %s", self.id, reason)
        # 先终态(abort 后 run_turn 的终态检查/异常路径据此收口), 再中止回合
        self.status = "failed"
        self.error = reason
        self._commit_progress()
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

    def _progress_check(self) -> str:
        """worktree 无进展检测(每探测周期一次)。

        进度信号 = 已跟踪修改文件的**内容哈希**(编辑会变) + untracked 文件的
        (路径,大小)清单(编译产物逐个落盘会变) + porcelain 状态行。
        纯命令重跑/编译空转(无编辑、无新产物) → 信号不变 → 连续
        _PROGRESS_TICKS 周期后判循环。探索期(从未出现文件变更)不武装。
        """
        try:
            st = _git(["status", "--porcelain"], self.wt, check=False).stdout
        except Exception:  # noqa: BLE001
            return ""
        lines = [ln for ln in st.splitlines() if ln.strip()]
        parts = [st]
        sha = hashlib.sha1
        for ln in lines:
            xy = ln[:2]
            path = ln[3:].strip().strip('"')
            if "M" in xy and "->" not in ln:      # tracked 修改 → 内容参与
                try:
                    with open(os.path.join(self.wt, path), "rb") as f:
                        parts.append(sha(f.read(262144)).hexdigest())
                    continue
                except Exception:  # noqa: BLE001
                    pass
            parts.append(f"{path}:{os.path.getsize(os.path.join(self.wt, path))}"
                         if os.path.exists(os.path.join(self.wt, path)) else path)
        h = sha("".join(parts).encode("utf-8", "replace")).hexdigest() \
            if lines else ""
        if h and not self._progress_armed:
            # 首次出现文件变更 → 武装(纯探索期不判定, 防误伤只读阶段)
            self._progress_armed = True
            self._progress_hash = h
            self._progress_stall = 0
            return ""
        if not self._progress_armed:
            return ""
        if h and h == self._progress_hash:
            self._progress_stall += 1
        else:
            self._progress_stall = 0
            self._progress_hash = h
        if self._progress_stall >= _PROGRESS_TICKS:
            return (f"worktree 已 {_PROGRESS_TICKS * int(_WATCH_INTERVAL)}s "
                    "无文件进展且回合未结束(疑似改→跑→同错循环)")
        return ""

    async def _watch_turn(self, turn_task: asyncio.Task) -> None:
        """探测执行器: error/活动停滞/循环护栏 → abort 回合, 防会话无限锁定。"""
        try:
            while not turn_task.done() and self.status not in ("done", "failed", "stopped"):
                await asyncio.sleep(_WATCH_INTERVAL)
                if turn_task.done() or not self._busy:
                    return
                # 循环护栏(事件面检测器置旗标; 无流式事件的执行器自然不触发)
                if self._loop_verdict:
                    await self._fail_turn(f"循环检测: {self._loop_verdict}",
                                          turn_task)
                    return
                # worktree 无进展看门狗(所有执行器通用)
                stall_reason = self._progress_check()
                if stall_reason:
                    await self._fail_turn(stall_reason, turn_task)
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
                elif p.status == "idle" and stall > self.stall_sec:
                    # 只有明确 idle 才判停滞; unknown = 观测不到(serve 抖动),
                    # 误杀长编译等无流式事件阶段(cv-181 同类, 排查修复)
                    reason = (f"回合活动停滞 {stall:.0f}s(阈值 {self.stall_sec:.0f}s,"
                              "疑似 LLM 无响应/通道挂起)")
                if not reason:
                    continue
                await self._fail_turn(reason, turn_task)
                return
        except asyncio.CancelledError:
            raise

    async def abort(self) -> Dict[str, Any]:
        ok = await self.adapter.abort(self)
        if ok:
            self.emit("aborted", "当前回合已被中止")
            return {"ok": True}
        return {"ok": False, "error": "执行器中止调用失败(回合可能仍在等待)"}

    def _commit_progress(self) -> None:
        """终态进度保全(cv-177): 把 worktree 改动 commit 到任务分支——
        失败重跑时分支已含全部进度, 续跑不再从零开始。尽力而为, 失败不阻断。"""
        try:
            _git(["add", "-A"], cwd=self.wt, check=False)
            st = _git(["status", "--porcelain"], cwd=self.wt, check=False)
            if not st.stdout.strip():
                return
            msg = f"task(progress): {self.status} (job {self.id})"
            _git(["commit", "-m", msg, "--no-verify"], cwd=self.wt, check=False)
        except Exception:  # noqa: BLE001
            pass

    async def finish(self, keep_worktree: bool = True) -> Dict[str, Any]:
        self.status = "stopped" if self.status != "done" else self.status
        self._commit_progress()
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
        """变更文件清单: 对任务基点(base SHA)的 name-only diff。

        不用 status——自动 commit 进度后 worktree 恒干净, status 恒空;
        对基点的 diff 在 commit 前后语义一致(改了什么 vs 任务起点)。"""
        try:
            _git(["add", "-A", "-N"], cwd=self.wt, check=False)
            d = _git(["diff", "--name-only", self.base], cwd=self.wt, check=False)
            return [ln.strip() for ln in d.stdout.splitlines() if ln.strip()]
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


def _commit_progress_in_existing_worktree(root: str, branch: str) -> None:
    """续跑让位(cv-177): 找到占用 branch 的旧 worktree → 提交其未提交进度 →
    remove 让位。旧 worktree 的未提交改动是上次失败任务的全部进度, 丢了就白跑。"""
    try:
        out = _git(["worktree", "list", "--porcelain"], cwd=root, check=False)
        cur = None
        for ln in out.stdout.splitlines():
            if ln.startswith("worktree "):
                cur = ln[9:].strip()
            elif ln.startswith("branch ") and ln[7:].strip() == f"refs/heads/{branch}":
                if cur and os.path.isdir(cur):
                    _git(["add", "-A"], cwd=cur, check=False)
                    st = _git(["status", "--porcelain"], cwd=cur, check=False)
                    if st.stdout.strip():
                        _git(["commit", "-m", f"task(progress): resume handoff (branch {branch})",
                              "--no-verify"], cwd=cur, check=False)
                    _git(["worktree", "remove", "--force", cur], cwd=root, check=False)
                return
    except Exception:  # noqa: BLE001
        pass


def _wt_root_dir() -> str:
    d = os.environ.get("TOPOCODE_DB_DIR") or os.path.join(
        os.path.expanduser("~"), ".topocode")
    p = os.path.join(d, "runner", "implement")
    os.makedirs(p, exist_ok=True)
    return p


def _write_workspace_files(wt: str, files) -> list:
    """P5: 规约/规则/agent 配置落盘 worktree（cline .cline/* 或 AGENTS.md）。

    安全校验: path 必须相对且解析后仍在 wt 内（防路径穿越）。
    """
    written = []
    wt_abs = os.path.abspath(wt)
    for f in (files if isinstance(files, list) else []):
        if not isinstance(f, dict):
            continue
        rel = str(f.get("path") or "").strip().lstrip("/")
        content = str(f.get("content") or "")
        if not rel:
            continue
        dst = os.path.abspath(os.path.join(wt_abs, rel))
        if not dst.startswith(wt_abs + os.sep):
            logger.warning("[implement] workspaceFiles 路径越界拒绝: %r", rel)
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(content)
            written.append(rel)
        except Exception as e:  # noqa: BLE001
            logger.warning("[implement] workspaceFiles 写入失败 %r: %s", rel, e)
    return written


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
            resumed = False
            if r.returncode != 0:
                # 分支已存在 → 续跑复用(cv-177): 旧 worktree 提交进度后让位,
                # 新 worktree 检出已有分支承接全部进度
                _commit_progress_in_existing_worktree(root, branch)
                r2 = _git(["worktree", "add", wt, branch], cwd=root, check=False)
                if r2.returncode != 0:
                    return {"ok": False,
                            "error": f"worktree 创建失败: {r2.stderr.strip()[:300]}"}
                resumed = True
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
            project_id=str(body.get("projectId") or ""),
            verify_config=body.get("verify") if isinstance(body.get("verify"), dict) else None)
        _JOBS[job_id] = job
        # 子会话复活: 预置执行器原生会话 id(空=新建会话)
        job.session_id = str(body.get("sessionRef") or "")
        # P5: 规约/规则/agent 配置落盘 worktree（cline .cline/rules|agents、AGENTS.md）
        written = _write_workspace_files(wt, body.get("workspaceFiles"))
        job.turn_task = asyncio.create_task(job.start())
        if resumed:
            logger.info("[implement] job %s RESUMED branch=%s(承接上次进度)",
                        job_id, branch)
        logger.info("[implement] job %s created root=%s branch=%s files=%s",
                    job_id, root, branch, written)
        # 交接边界快照(环节十一): 任务分支基点 commit——里程碑比对/合并入口
        # precheck(主目录是否前移)的数据源
        try:
            base_commit = _git(["rev-parse", "HEAD"], wt, check=False).stdout.strip()
        except Exception:  # noqa: BLE001
            base_commit = ""
        return {"ok": True, "jobId": job_id, "branch": branch, "worktree": wt,
                "status": job.status, "workspaceFiles": written, "resumed": resumed,
                "baseCommit": base_commit}

    @app.get("/api/implement/running")
    async def implement_running():
        """全局运行中(非终态)作业清单——architect 互斥引擎的校验数据源。"""
        return {"ok": True, "jobs": [
            {"jobId": j.id, "root": j.root, "branch": j.branch,
             "status": j.status, "boundaries": j.boundaries}
            for j in _JOBS.values() if j.status not in ("done", "failed", "stopped")]}

    @app.get("/api/implement/list")
    async def implement_list():
        """全部作业台账(含终态)——architect 对账/清理数据源(cv-160: 重启丢作业无对账)。"""
        return {"ok": True, "jobs": [
            {"jobId": j.id, "status": j.status, "worktree": j.wt,
             "branch": j.branch, "root": j.root, "sessionId": j.session_id,
             "executorId": j.adapter.executor_id}
            for j in _JOBS.values()]}

    @app.post("/api/implement/gc")
    async def implement_gc(request: Request):
        """终态作业对账清理: 释放执行器资源 + 出台账; 分支保留在基仓库。

        body: {keepWorktree?: bool=true}——默认保 worktree(改动未合并时勿删)。"""
        try:
            body = await request.json()
        except Exception:
            body = {}
        keep_wt = bool((body or {}).get("keepWorktree", True))
        cleaned = []
        for jid, j in list(_JOBS.items()):
            if j.status not in ("done", "failed", "stopped"):
                continue
            try:
                await j.adapter.dispose(j)
            except Exception:  # noqa: BLE001
                pass
            if j.watch_task and not j.watch_task.done():
                j.watch_task.cancel()
            if not keep_wt and j.wt and os.path.isdir(j.wt):
                import shutil as _shutil
                _shutil.rmtree(j.wt, ignore_errors=True)
            _JOBS.pop(jid, None)
            cleaned.append(jid)
        return {"ok": True, "cleaned": cleaned, "keptWorktree": keep_wt}

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
        return await job.user_input(text, steer=bool(body.get("steer")))

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

    # ── cline v2 内省面（经 adapter 能力分派; 非对应执行器明确报错）──

    def _cap(job_id: str, name: str):
        """作业 adapter 能力获取(不存在/不支持返回 (None, err))。"""
        job = _JOBS.get(job_id)
        if not job:
            return None, "作业不存在"
        fn = getattr(job.adapter, name, None)
        if fn is None:
            return None, f"当前执行器({job.adapter.executor_id})不支持 {name}"
        return (job, fn), None

    @app.get("/api/implement/{job_id}/messages")
    async def implement_messages(job_id: str, display: bool = True):
        cap, err = _cap(job_id, "read_messages")
        if err:
            return {"ok": False, "error": err}
        job, fn = cap
        try:
            return {"ok": True, "messages": await fn(job, display=display)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}

    @app.get("/api/implement/{job_id}/usage")
    async def implement_usage(job_id: str):
        cap, err = _cap(job_id, "get_usage")
        if err:
            return {"ok": False, "error": err}
        job, fn = cap
        try:
            return {"ok": True, "usage": await fn(job)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}

    @app.get("/api/implement/{job_id}/checkpoints")
    async def implement_checkpoints(job_id: str, runCount: int = 1):
        cap, err = _cap(job_id, "compare_checkpoint")
        if err:
            return {"ok": False, "error": err}
        job, fn = cap
        try:
            return {"ok": True,
                    "compare": await fn(job, int(runCount))}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}

    @app.post("/api/implement/{job_id}/restore")
    async def implement_restore(job_id: str, request: Request):
        cap, err = _cap(job_id, "restore_checkpoint")
        if err:
            return {"ok": False, "error": err}
        job, fn = cap
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        try:
            return {"ok": True, "restore": await fn(
                job, int(body.get("runCount") or 0),
                body.get("options") or None)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}

    @app.post("/api/implement/{job_id}/model")
    async def implement_model(job_id: str, request: Request):
        cap, err = _cap(job_id, "update_model")
        if err:
            return {"ok": False, "error": err}
        job, fn = cap
        body = await request.json()
        model_id = str(body.get("modelId") or "").strip()
        if not model_id:
            return {"ok": False, "error": "modelId 为空"}
        try:
            ok = await fn(job, model_id)
            return {"ok": bool(ok), "error": "" if ok else "换模失败"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}

    @app.post("/api/implement/{job_id}/approval")
    async def implement_approval(job_id: str, request: Request):
        """越界审批桥：用户批准/拒绝 sidecar 工具调用。"""
        cap, err = _cap(job_id, "respond_approval")
        if err:
            return {"ok": False, "error": err}
        job, fn = cap
        body = await request.json()
        request_id = str(body.get("requestId") or "").strip()
        if not request_id:
            return {"ok": False, "error": "requestId 为空"}
        try:
            ok = await fn(job, request_id, body.get("approved") is True,
                          str(body.get("reason") or ""))
            if ok:
                # A6.1 反向请求销账(queued-minus-delivered: 应答即出队)
                resolve = getattr(job, "resolve_pending_request", None)
                if resolve:
                    resolve(request_id)
            return {"ok": bool(ok)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}

    @app.get("/api/implement/{job_id}/pending")
    async def implement_pending(job_id: str):
        """挂起提示清单（queue/steer 排队面）。"""
        cap, err = _cap(job_id, "list_pending_prompts")
        if err:
            return {"ok": False, "error": err}
        job, fn = cap
        try:
            return {"ok": True, "prompts": await fn(job)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}

    @app.post("/api/implement/{job_id}/proceed")
    async def implement_proceed(job_id: str, request: Request):
        """长命令放行（社区坑: dev server/watch 阻塞——后台继续并采集输出）。"""
        cap, err = _cap(job_id, "proceed_while_running")
        if err:
            return {"ok": False, "error": err}
        job, fn = cap
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        try:
            exit_code = await fn(job, body.get("toolCallId") or None)
            return {"ok": exit_code is not None, "exitCode": exit_code}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}

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
