"""恢复对账系(M2 自 exec_bridge 机械迁出, 行为等价) — C 定时对账 + 惰性泵恢复。

职责: 服务重启后扫描假 running 任务并收敛(recover_sweep 周期任务) +
会话交互前核对(recover_conv_tasks)。任务泵核心(_task_pump/_handle_task_event)
仍居 exec_bridge(与 eb.* 打桩面深耦合, 随 M4 DispatchTurn 接缝重构迁出);
本模块对其引用一律调用期解析(exec_bridge import inside function)。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_SWEEP_TASK: Optional[asyncio.Task] = None

# cv-248 liveness 补口: runner 持续不可达的容忍时限(分钟, env 可覆写)。
# 「跳过(可能在重启)」只在短暂窗口成立; runner 进程级死亡时任务必须按时限
# 显式终态化——无出路状态(永久 running 锁死会话互斥)不允许存在(liveness
# 不变式: 任何判定不可操作的状态必须有一条不依赖丢失对象的出路)。
_UNREACHABLE_LIMIT_MIN = float(os.environ.get("ARCH_RUNNER_UNREACHABLE_MIN", "15"))


def start_recover_sweep(interval: float = 45.0) -> None:
    """C 定时对账: 主循环周期任务——扫描默认库+全部项目库的假 running 任务。

    恢复触发不再依赖用户交互(GET messages/handle_chat); 服务重启后
    由本循环自动收敛。重复调用幂等(任务存活即跳过)。"""
    global _SWEEP_TASK
    if _SWEEP_TASK and not _SWEEP_TASK.done():
        return

    async def _loop() -> None:
        while True:
            try:
                n = await asyncio.to_thread(recover_sweep)
                if n:
                    logger.info("[exec-bridge] sweep 收尾任务数=%s", n)
            except Exception as e:  # noqa: BLE001
                logger.warning("[exec-bridge] sweep 异常: %s", e)
            await asyncio.sleep(interval)

    _SWEEP_TASK = asyncio.create_task(_loop())


def recover_sweep() -> int:
    """扫默认库+全部项目库(目录发现 {data}/architect/{pid}/arch.db)中
    存在 running/waiting_input 任务的会话 → recover_conv_tasks。
    返回收尾任务数(重挂泵不计)。"""
    import sqlite3
    from ...arch_routes import ctx as _ctx
    data_dir = _ctx.data_dir()
    db_paths = [os.path.join(data_dir, "architect.db")]
    proj_root = os.path.join(data_dir, "architect")
    if os.path.isdir(proj_root):
        for pid in sorted(os.listdir(proj_root)):
            dbp = os.path.join(proj_root, pid, "arch.db")
            if os.path.isfile(dbp):
                db_paths.append(dbp)
    conv_ids: list = []
    for dbp in db_paths:
        if not os.path.isfile(dbp):
            continue
        try:
            con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT DISTINCT conversation_id FROM arch_tasks "
                    "WHERE status IN ('running','waiting_input')").fetchall()
                conv_ids += [r[0] for r in rows if r[0]]
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            continue
    total = 0
    for conv_id in dict.fromkeys(conv_ids):
        try:
            rec = recover_conv_tasks(conv_id)
            total += int((rec or {}).get("finished") or 0)
        except Exception as e:  # noqa: BLE001
            logger.warning("[exec-bridge] sweep 恢复失败: %s", e)
        # 流程相位自愈(M6): 恢复无收敛且活跃任务 stale → interrupted
        # (显式声明卡点并给出恢复动作, 不静默悬置——cv-153/161/204 事故模式收口)
        try:
            from ..governance import flow as _flow
            if _flow.mark_stale_interrupted(conv_id):
                logger.warning("[exec-bridge] 会话 stale 置 interrupted conv=%s", conv_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[exec-bridge] 相位自愈失败 conv=%s: %s", conv_id, e)
    return total


def recover_conv_tasks(conv_id: str) -> dict:
    """P1 泵恢复(惰性): 会话交互前核对 running/waiting_input 任务与 runner 实际态。

    服务重启会丢内存泵(_TASK_PUMPS)与 runner 作业(_JOBS 同为内存态)——runner
    侧已终态的任务被卡 running(互斥锁死会话、无结果回执; cv-153 实证)。
    - runner 终态(done/failed) → 重放终态事件(回执+result_md+work_state 聚合)
    - 仍在执行 → 返回 repump 清单(调用方须在事件循环内 _start_task_pump;
      本函数可能跑在工作线程, 不能 create_task)
    - runner 报作业不存在 → 显式 failed(不臆测不悬置)
    - runner 不可达 → 跳过(可能在重启, 下次交互再试)
    返回 {"finished": 收尾数, "repump": [(task_id, job_id, rid, agent), ...]}。
    """
    # 调用期解析: eb._client/_handle_task_event/_task_ctx 为测试打桩接缝
    from ...arch_routes import exec_bridge as _eb
    from ...arch_routes.store import states as ST
    out = {"finished": 0, "repump": []}
    now_ms = int(__import__("time").time() * 1000)
    for t in _eb.store.TasksStore.of_conv(conv_id):
        if (t.get("status") or "") not in ("running", ST.TASK_WAITING_INPUT):
            continue
        job_id = t.get("runnerJobId") or ""
        if not job_id:
            # cv-204 补窗: confirm 链中被重启截断的任务(status 已 running 但
            # start POST 未回)——原实现静默跳过 → 永久 running 锁死会话互斥。
            # 按更新时间防误伤在途请求(2 分钟内视为仍在进行, 交下轮再判)。
            _upd = int(t.get("updatedAt") or t.get("createdAt") or 0)
            if now_ms - _upd > 2 * 60 * 1000:
                _eb._handle_task_event(
                    {"kind": "failed",
                     "text": "服务重启中断了任务启动(未获得执行作业)——请重新发起。"},
                    _eb._task_ctx(conv_id, t["id"], "",
                                  t.get("reqId") or "",
                                  t.get("executorType") or ""))
                out["finished"] += 1
            continue
        from ..governance.timeouts import get as _timeout_of
        snap = _eb._client().snapshot(job_id, timeout=_timeout_of("runner_snapshot"))
        if snap is None or not snap.ok:
            if snap is not None and "作业不存在" in (snap.error or ""):
                err = "runner 作业已丢失(执行器服务重启)——无法续跑, 请重新发起任务。"
                _eb._handle_task_event({"kind": "failed", "text": err},
                                       _eb._task_ctx(conv_id, t["id"], job_id,
                                                     t.get("reqId") or "",
                                                     t.get("executorType") or ""))
                out["finished"] += 1
                continue
            # cv-248 liveness 补口: 不可达超出容忍时限(45s sweep × 多轮确认,
            # 避开重启窗口)→ 显式 failed——变更保留在工作区, 重试/重新发起
            # 出路可达; 绝不因悬空 running 永久锁死执行互斥。
            _upd = int(t.get("updatedAt") or t.get("createdAt") or 0)
            if now_ms - _upd > _UNREACHABLE_LIMIT_MIN * 60 * 1000:
                err = ("执行器持续不可达(对账超时)——任务终止。"
                       "已产生的变更保留在工作区, 可重试或重新发起。")
                _eb._handle_task_event({"kind": "failed", "text": err},
                                       _eb._task_ctx(conv_id, t["id"], job_id,
                                                     t.get("reqId") or "",
                                                     t.get("executorType") or ""))
                out["finished"] += 1
            continue
        evs = snap.events or []
        last_term = None
        for ev in evs:
            if (ev.get("kind") or "") in ("done", "failed", "input_required"):
                last_term = ev
        if last_term and (last_term.get("kind") in ("done", "failed")):
            _eb._handle_task_event(last_term,
                                   _eb._task_ctx(conv_id, t["id"], job_id,
                                                 t.get("reqId") or "",
                                                 t.get("executorType") or ""))
            out["finished"] += 1
        else:
            # 仍在执行或等待输入: 交还调用方在事件循环内重挂泵
            out["repump"].append((t["id"], job_id, t.get("reqId") or "",
                                  t.get("executorType") or ""))
    # 流程相位重算(force: 解除 interrupted 粘滞——恢复成功即占用事实已变)
    try:
        from ..governance import flow as _flow
        _flow.recompute(conv_id, trigger="recover", force=True)
    except Exception:  # noqa: BLE001
        pass
    return out
