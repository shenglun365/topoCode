"""直通会话状态域(2610 拆分)——句柄表 + 状态查询/停止/JobCard 回写。

自 proxy.py 机械迁出(行为等价): _PROXY_JOBS 存储单源在此, proxy.py 与
外部消费面(import 路径不变经 proxy.py 转发)共用。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("arch_routes.exec_bridge")

# conv_id -> {job_id, executor_type}（活跃直通会话; 进程级, 与 _TASK_PUMPS 同策略）
PROXY_JOBS: Dict[str, Dict[str, str]] = {}
# 兼容别名(原 proxy._PROXY_JOBS; 消费面经 proxy.py 转发使用)
_PROXY_JOBS = PROXY_JOBS


def proxy_enabled(conv: Optional[dict]) -> bool:
    """会话是否直通(coding 执行器持球)——路由分支判定单源(2610 统一模型)。

    原 analysisMode=quick 判定由 uses_direct_channel 吸收(legacy 兼容);
    本模块不引 arch_routes(R1), 经 exec_bridge 冻结缝取值。"""
    from . import exec_bridge as _eb
    return _eb.uses_direct_channel(conv)


def proxy_state(conv_id: str) -> Dict[str, Any]:
    """直通会话状态(cv-275): FE 持久状态条数据源(REST 查询, 刷新安全)。

    {active, jobId, sessionRef, executorType, state, queued}——active=有活跃直通
    作业(内存句柄; 后端重启后句柄清空但会话行 sessionRef 仍可复活);
    state=作业状态轴 running|idle(执行器忙/等待输入, 事件泵推进——
    FE JobCard 据此渲染, 禁止把「会话保活」误读成「执行中」);
    queued=调度排队位次(2610 F5b, >0 表示回合在工作区仲裁队列中)。"""
    entry = PROXY_JOBS.get(conv_id) or {}
    from ... import store as _st
    row = _st.ConversationsStore.get(conv_id) or {}
    try:
        from . import executor_scheduler as _sched
        _st_st = _sched.state_of_conv(conv_id)
    except Exception:  # noqa: BLE001 — 调度态缺失不阻断状态查询
        _st_st = {}
    return {"active": bool(entry),
            "jobId": entry.get("job_id") or "",
            "executorType": entry.get("executor_type") or "",
            "state": str(entry.get("state") or "running"),
            "sessionRef": row.get("sessionRef") or "",
            "queued": int(_st_st.get("position") or 0)
            if _st_st.get("state") == "queued" else 0}


def proxy_stop(conv_id: str, mode: str = "") -> Dict[str, Any]:
    """停止直通执行器(cv-273/275): 按作业状态分型——

    running → /abort(暂停语义: 中止本轮, 会话保留, 发消息即恢复);
    空闲(waiting_input) → /finish(结束会话: 下条消息开启全新会话)。
    2610 cv-15: mode 显式覆盖("abort"/"finish")——任务卡按钮跟随状态,
    running 态允许直接结束(finish)、不必先暂停。会话行 sessionRef 恒
    保留(finish 亦不清——用户可随时复活续上下文)。"""
    entry = PROXY_JOBS.get(conv_id)
    if not entry:
        return {"ok": False, "error": "无进行中的直通会话"}
    job_id = entry["job_id"]
    from . import exec_bridge as eb
    if mode in ("abort", "finish"):
        action = mode                       # 按钮语义显式覆盖
    else:
        snap = eb._runner(f"/api/implement/{job_id}", None, 12.0) or {}
        running = (snap.get("status") or "") not in ("waiting_input", "done",
                                                     "failed", "stopped")
        action = "abort" if running else "finish"
    running = action == "abort"             # 汇总文案语义(暂停=保留/结束=新会话)
    r = eb._runner(f"/api/implement/{job_id}/{action}", {}, 12.0)
    if r is None:
        return {"ok": False, "error": "runner 不可达(:3458)", "job_id": job_id}
    if r.get("ok") is False:
        return {"ok": False, "error": r.get("error") or f"{action} 调用失败",
                "job_id": job_id}
    # cv-283 JobCard 状态回写: abort=暂停(idle, 会话保留)/finish=结束(ended)
    set_job_card_state(conv_id, "idle" if action == "abort" else "ended")
    # 统筹调度: 用户主动停止 → 释放槽位且**不**自动续跑排队项(人为干预优先)
    if action == "finish":
        from . import executor_scheduler as _sched
        _sched.stop_conv("", conv_id)   # root 未知 → 全 root 扫(按 convId 匹配)
    return {"ok": True, "job_id": job_id, "action": action,
            "summary": ("已暂停——会话保留，发消息即恢复" if running
                        else "已结束直通会话——下条消息将开启全新会话")}


def job_card_fp(conv_id: str) -> str:
    return f"proxyjob:{conv_id}"


_job_card_fp = job_card_fp   # 兼容别名(原私有名)


def set_job_card_state(conv_id: str, state: str) -> None:
    """JobCard 状态回写(cv-283): fingerprint 原位更新 meta.jobState + SSE。
    词汇=running|idle|ended(执行器作业状态轴同源, 不自造)。"""
    from ... import store as _st
    from ...agent.collab import cards as _cards
    try:
        row = _st.ConversationsStore.update_message_by_meta(
            conv_id, {"kind": "proxy", "fingerprint": job_card_fp(conv_id)},
            {"meta": {"jobState": state}})
        if row:
            logger.info("[proxy] JobCard 状态翻转 conv=%s → %s msg=%s（SSE 已发）",
                        conv_id, state, row.get("id"))
            _cards.emit(conv_id, str(row.get("id") or ""), kind="proxy")
        else:
            logger.debug("[proxy] JobCard 状态回写无宿主行 conv=%s state=%s",
                         conv_id, state)
    except Exception:  # noqa: BLE001 — 状态回写失败不阻断主流程
        logger.warning("[proxy] JobCard 状态回写失败 conv=%s state=%s",
                       conv_id, state)


_set_job_card_state = set_job_card_state   # 兼容别名(原私有名)


def reset_stale_work_state(conv_id: str) -> bool:
    """2610 P1 对账: running 会话无任务且无直通句柄(重启丢失) → 回落 architect。

    直通作业真活在 runner 时, 下条消息经 sessionRef 复活——显示层不虚报执行中。"""
    from . import exec_bridge as _eb
    if _eb.active_task_of(conv_id) or conv_id in PROXY_JOBS:
        return False
    from ... import store as _st
    _st.ConversationsStore.set_work_state(conv_id, "architect")
    return True
