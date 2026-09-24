"""下发域(M4 自 exec_bridge 机械迁出, 行为等价) — 设计 §8.2-①/DispatchTurn 协作面。

职责: 任务卡生命周期(propose 轻门禁/confirm 拉起/输入投递/执行器与验收设置/
停止/活跃查询/重试衔接)。任务泵核与事件落库仍居 exec_bridge(_eb 调用期解析,
保持 eb.* 测试打桩接缝); R3.2 图门禁/R2.3 探针兜底/R2.5 同挡微调随行。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from ... import store
from ...store import states as ST

logger = logging.getLogger("arch_routes.exec_bridge")


def _eb():
    """exec_bridge 调用期引用(驻留接缝; 模块对象绑定, 规避初始化环)。"""
    from ...arch_routes import exec_bridge as _m
    return _m


def stop(conv_id: str, reason: str = "") -> str:
    """UI 停止按钮(REST): 结束全部运行中作业(保留 worktree/分支)。"""
    jobs = [j for j in _eb().jobs_of(conv_id) if (j.get("status") or "") not in _eb()._TERMINAL]
    if not jobs:
        return "当前会话没有运行中的作业。"
    for j in jobs:
        from ..governance.timeouts import get as _timeout_of
        _eb()._client().finish(str(j["jobId"]), keep_worktree=True,
                               timeout=_timeout_of("runner_finish"))
        _eb()._job_upsert(conv_id, {"jobId": j["jobId"], "status": "stopped",
                              "endedAt": _eb()._ts()})
    _eb()._aggregate_work_state(conv_id)
    return (f"🛑 已停止 {len(jobs)} 个作业。分支与改动已保留，"
            "可「查看差异」检视，或 `/执行` 按当前规约重新执行。")


def _last_failed_task(conv_id: str) -> dict:
    """会话最近一次失败任务行(跨主库+项目库扫描, 与 recover_sweep 同法)。"""
    try:
        from ...store.base import _db, _scan_dbs
        seen = []
        for db in [_db(), *_scan_dbs()]:
            try:
                rows = db.fetchall(
                    "SELECT id, branch, base_commit, created_at FROM arch_tasks "
                    "WHERE conversation_id = ? AND status = 'failed' "
                    "AND branch LIKE 'task/%' ORDER BY created_at DESC",
                    (conv_id,))
                seen.extend(rows or [])
            except Exception:  # noqa: BLE001
                continue
        seen.sort(key=lambda r: r.get("created_at") or 0, reverse=True)
        for r in seen:
            return dict(r)
    except Exception:  # noqa: BLE001
        pass
    return {}


def _last_failed_branch(conv_id: str) -> str:
    """取会话最近一次失败任务的分支(跨主库+项目库扫描——任务库路由存在
    读写分裂隐患, 与 recover_sweep 同法兜住; 路由统一另行排查)。"""
    return str(_last_failed_task(conv_id).get("branch") or "")


__all__ = []


def _flow_recompute(conv_id: str, *, trigger: str = "",
                    force: bool = False) -> None:
    """流程相位重算(governance/flow.py derive-on-write)。fail-soft:
    相位机任何故障不阻塞任务主链。"""
    try:
        from ..governance import flow as _flow
        _flow.recompute(conv_id, trigger=trigger, force=force)
    except Exception:  # noqa: BLE001
        pass


def _telemetry(kind: str, **fields) -> None:
    """遥测(governance 横切面转发——R2 层序: execution 不直引 reflection)。"""
    try:
        from ..governance import flow as _flow
        _flow.telemetry(kind, **fields)
    except Exception:  # noqa: BLE001
        pass


# 只读声明轻校验(提示不拦截——等级最终由用户/编排裁决)
_WRITE_HINT_RE = re.compile(
    r"(写入|修改|删除|重构|新增文件|创建文件|编辑|替换|部署|发布|迁移|安装|卸载|覆写|更新文件)")


def propose_task(conv: dict, title: str, instruction: str,
                 executor_hint: Optional[dict] = None,
                 gate_diagram: bool = True,
                 safety_class: str = "", work_tags: Optional[list] = None,
                 card_tail: str = "full") -> dict:
    """轻门禁入口: 建任务(saved) + 任务卡消息落统一流。

    safety_class/work_tags: 安全等级三值轴(readonly/mutating/high-stakes, 缺省
    mutating)与开放工作类型标签(governance/flow.py 词汇单源)——安全等级影响
    互斥/worktree/门禁(confirm 时消费), 标签仅影响提示。
    由 LLM 工具 task.propose / architect 编排调用; 用户「开始执行」后
    confirm_task 真正拉起 runner。
    R3.2(r3_2_logic_gate, 默认启用): 弱挡任务指令须附核心逻辑图(ArtifactGate
    确定性校验: 图围栏存在且边≥3)——缺失拒绝建卡, 回执 nudge architect 补图;
    计划步骤卡(plan 下发)豁免(gate_diagram=False), 图随计划首卡/需求上下文。
    """
    conv_id = conv["id"]
    conv = store.ConversationsStore.get(conv_id) or conv   # 取全量行(create 返回值可能缺 reqId 等字段)
    # 安全等级归一(三值轴; 非法值回落 mutating——显式优于静默升档)
    from ...store.states import (SAFETY_CLASSES, SAFETY_MUTATING,
                                             SAFETY_READONLY)
    _safety = str(safety_class or "").strip().lower() or SAFETY_MUTATING
    if _safety not in SAFETY_CLASSES:
        _safety = SAFETY_MUTATING
    # 轻校验(不硬断): 声明只读但指令疑似含写操作 → 回执复核提示(等级照落)
    _safety_review = ""
    if _safety == SAFETY_READONLY and _WRITE_HINT_RE.search(instruction or ""):
        _safety_review = ("⚠️ 任务声明为只读(readonly)，但指令疑似包含写操作——"
                          "请复核安全等级；按只读执行将豁免互斥且不建隔离分支。")
    if gate_diagram:
        try:
            from ...agent.compensation.overrides import read_overrides, override_enabled
            if override_enabled(read_overrides(store.CollabConfigStore.get),
                                "r3_2_logic_gate"):
                from ...agent.governance.gears import resolve_gear
                _policy = resolve_gear(str((conv or {}).get("analysisMode") or ""))
                if str(getattr(_policy, "logic_diagram", "") or "") == "uml":
                    from ...agent.compensation.providers import validate_logic_diagram
                    _gate = validate_logic_diagram(instruction or "")
                    if not _gate.passed:
                        return {"ok": False, "error":
                                f"任务指令缺少核心逻辑图({_gate.note})——当前挡位(弱模型补偿)"
                                " instruction 附 PlantUML/Mermaid 标准语法核心逻辑图"
                                "(activity/sequence 类, ≥3 条边)。请补图后重新 task.propose。"}
        except Exception:  # noqa: BLE001 — 门禁基础设施异常不阻塞建卡主链
            pass
    _pid = (conv or {}).get("projectId") or (conv or {}).get("project_id") or ""
    # 执行器选定单源(显式 hint > 会话绑定 > 注册表默认); 不再字面回落 opencode(cv-153 教训)
    from ...arch_routes.agent_executors import normalize_executor_type, default_executor
    etype = normalize_executor_type((executor_hint or {}).get("executorType") or "")
    if not etype:
        _bound = _eb().executor_hint_by_id(str((conv or {}).get("executorId") or ""), conv) or {}
        etype = normalize_executor_type(_bound.get("executorType") or "")
    if not etype:
        etype = normalize_executor_type((default_executor() or {}).get("type") or "")
    if not etype:
        return {"ok": False,
                "error": "无可用执行器：注册表无启用项且未指定执行器类型——"
                         "请在「执行器配置」启用至少一个执行器后在对话中指定(如 @cline)。"}
    _eid = ((executor_hint or {}).get("executorId") or ""
            or (conv or {}).get("executorId") or "")
    if not _eid:
        # 类型/配置须同源(cv-158 实证: 默认执行器只给了 type 没带 id → confirm 时
        # 无 executorConfig 可查, sidecar 收到空 model 被拒)——eid 取同一注册项
        _def = default_executor() or {}
        _eid = str(_def.get("id") or "")
    # 续跑衔接(cv-177): 会话存在失败任务且其分支仍在 → 新任务复用该分支,
    # runner 检出已有分支承接上次进度(终态自动 commit 已保全)——重跑不再从零开始。
    resume_branch = _last_failed_branch(conv_id)
    _rid = (conv or {}).get("reqId") or ""
    _spec_ver = 0
    if _rid:
        _active = store.RequirementsStore.spec_active(_rid) or {}
        _spec_ver = int(_active.get("ver") or 0)
    # 交接过期提示(环节十三): 失败任务基点以来边界文件在主分支有推进 →
    # 需求引用的文件状态已漂移, 盲目续跑有冲突风险——卡片显式提示
    _stale_note = ""
    if resume_branch:
        _old = _last_failed_task(conv_id)
        _old_base = str(_old.get("base_commit") or "")
        if _old_base:
            try:
                from ...arch_routes.execution import conv_root_project as _crp
                from ...agent.governance.boundary import changed_since
                _root, _proj = _crp(conv)
                _bfiles = _eb()._resolve_boundary_files(_rid, _root, _proj) if _rid else []
                _moved = changed_since(_root, _old_base, _bfiles)
                if _moved:
                    _stale_note = (
                        f"\n> ⚠️ 交接过期：基点以来边界文件在主分支已有推进"
                        f"({', '.join(_moved[:5])})——续跑基于旧基点, 合并前请先检视冲突。")
            except Exception:  # noqa: BLE001
                pass
    # ── 默认保存(2026-09-20 产品裁决): 建卡即登记, 手动触发执行 ──
    # 同需求已有未开始(saved)卡 → 改写而非新建(对话补充 → agent 更新通道;
    # 同时天然消化弱模型重复提案——比 cv-174 去重更上游)
    _saved = next((t for t in reversed(store.TasksStore.of_conv(conv_id))
                   if _rid and t.get("reqId") == _rid
                   and (t.get("status") or "") == ST.TASK_SAVED), None)
    if _saved is None:
        # cv-203 防重复执行: 同需求存在进行中任务 → 拒绝新建(终态可重试;
        # saved 不算进行中——可被新卡修订替换, 见上方改写分支)
        _busy = next((t for t in reversed(store.TasksStore.of_conv(conv_id))
                      if _rid and t.get("reqId") == _rid
                      and (t.get("status") or "") in (
                          ST.TASK_RUNNING, ST.TASK_WAITING_INPUT,
                          ST.TASK_PENDING_CONFIRM)), None)
        if _busy is not None:
            return {"ok": False, "error":
                    f"同一需求已有进行中的任务（{_busy['id']} "
                    f"「{( _busy.get('title') or '')[:40]}」· {_busy.get('status')}）"
                    "——不可重复执行; 请等待完成, 或先停止/忽略现有任务。"}
    if _saved is not None:
        _upd = {
            "title": (title or "").strip()[:120] or _saved.get("title") or "实施任务",
            "instruction": instruction,
            "executorType": etype,
            "executorId": _eid,
            "specVer": _spec_ver,
        }
        if safety_class:
            _upd["safetyClass"] = _safety      # 修订卡: 仅显式给出才改等级(保留用户裁决)
        if work_tags is not None:
            _upd["workTags"] = [str(x)[:40] for x in list(work_tags)[:20]]
        task = store.TasksStore.update(_saved["id"], _upd) or _saved
        task = {**task, "ok": True, "revised": True}
        _eb()._append(conv_id, "assistant",
                f"📝 **任务卡已修订**（{task['title']}，按对话补充更新）\n"
                f"执行器 `{etype}`\n\n"
                + (instruction or "")[:2000]
                + ("\n\n" + _safety_review if _safety_review else "")
                + "\n\n---\n已保存，可开始执行 / 继续对话调整 / 忽略。",
                msg_meta={"kind": "task_card", "taskId": task["id"]},
                project_id=_pid)
        _publish_task(conv_id, task)
        _flow_recompute(conv_id, trigger="task-propose")
        return task
    task = store.TasksStore.create({
        "conversationId": conv_id,
        "projectId": _pid,
        "reqId": _rid,
        "title": (title or "").strip()[:120] or "实施任务",
        "instruction": instruction,
        "status": ST.TASK_SAVED,
        "executorType": etype,
        "executorId": _eid,
        "specVer": _spec_ver,
        "safetyClass": _safety,
        "workTags": [str(x)[:40] for x in list(work_tags or [])[:20]],
        **({"branch": resume_branch} if resume_branch else {}),
    })
    # 错误契约(docs/architect/error-contract.md): 成功形状显式 ok=True
    # (失败形状 {"ok": False, "error"}; store 行为规范列, ok 仅回执层)
    task = {**task, "ok": True}
    _resume_note = (f"\n\n> 🔁 续跑：将承接上次失败任务的进度分支 `{resume_branch}`"
                    "（进度已自动保全）" if resume_branch else "")
    # 未合并预警(本地 PR 语义): 基线不含同会话未合并分支的改动 → 卡片显式提示
    _unmerged_note = ""
    try:
        from ...arch_routes.execution import conv_root_project as _crp2
        _root0, _proj0 = _crp2(conv)
        if _root0:
            _unmerged_note = _eb()._unmerged_branch_notes(conv_id, _root0)
    except Exception:  # noqa: BLE001
        pass
    # 空边界保护(环节十三): 需求未声明边界 → 卡片显式标注(确认=显式接受;
    # confirm 时范围探针会先尝试 grounding 补全)
    _no_scope_note = ""
    if _rid:
        try:
            _snap = (store.RequirementsStore.spec_active(_rid) or {}).get("snapshot") or {}
            if not (_snap.get("allowedScope") or []):
                _no_scope_note = ("\n\n> ⚠️ 该需求未声明修改边界(allowedScope 为空)——"
                                  "开始执行时将自动运行范围探针补全；"
                                  "补全失败则本次执行**无互斥保护**。")
        except Exception:  # noqa: BLE001
            pass
    # cv-196: 回执瘦身——instruction 全文不再落流(任务清单 TaskCard 是详情
    # 载体; 流内全文即车轱辘话), 一行确认 + 异常附注。
    _eb()._append(conv_id, "assistant",
            f"📋 **任务已保存**：**{task['title']}**（执行器 `{etype}`）"
            + (f" · 安全等级 `{_safety}`" if _safety != "mutating" else "")
            + ("\n\n" + _safety_review if _safety_review else "")
            + ("\n——待确认执行。" if card_tail == "plan"
               else "\n——点「开始执行」启动; 可继续对话调整, 或忽略本卡。")
            + _resume_note + _stale_note + _no_scope_note + _unmerged_note,
            msg_meta={"kind": "task_card", "taskId": task["id"]},
            project_id=_pid)
    _publish_task(conv_id, task)
    # 外路由遥测(自我完善闭环): task.propose = architect 未承接 → 通用执行器
    _telemetry("outbound_route", conversationId=conv_id, taskId=task.get("id"),
               executorType=etype, safetyClass=_safety)
    _flow_recompute(conv_id, trigger="task-propose")
    return task


# 同会话任务状态迁移锁(confirm/stop/ignore/merge 共用)——实测连点「开始执行」
# 拉起多个 runner/LLM 进程, 且慢路径(范围探针 LLM + runner start ≤20s)期间
# 状态仍 saved: check-then-act 非原子。改任务状态的迁移操作全程持锁 + 锁内
# 重读状态, 杜绝 confirm×stop/ignore 互覆(僵尸任务)、双 confirm 双启动。
_confirm_locks: Dict[str, threading.Lock] = {}
_confirm_locks_guard = threading.Lock()


def _conv_task_lock(conv_id: str) -> threading.Lock:
    with _confirm_locks_guard:
        lk = _confirm_locks.get(conv_id)
        if lk is None:
            lk = threading.Lock()
            _confirm_locks[conv_id] = lk
        return lk


def confirm_task(task_id: str) -> dict:
    """开始执行(2026-09-20 语义: saved|pending_confirm → running)。

    原用户确认门禁已按产品裁决取消(默认保存/手动触发/主动忽略)——
    本函数即「开始执行」动作; 存量 pending_confirm 卡沿用同门。
    同会话状态迁移锁内执行(防重); 已在执行的任务重复 confirm 幂等成功。"""
    task = store.TasksStore.get(task_id)
    if not task:
        return {"ok": False, "error": "task-not-found"}
    conv = store.ConversationsStore.get(task["conversationId"])
    if not conv:
        return {"ok": False, "error": "conv-not-found"}
    with _conv_task_lock(conv["id"]):
        return _confirm_task_locked(task_id, conv)


def _confirm_task_locked(task_id: str, conv: dict) -> dict:
    """confirm 主体(须持 _conv_confirm_lock 调用)。锁内重读任务状态:
    并发第二次点击在慢路径完成前到达时, 已翻转的 running 态在此幂等命中。"""
    task = store.TasksStore.get(task_id) or {}
    _st = task.get("status") or ""
    if _st in (ST.TASK_RUNNING, ST.TASK_WAITING_INPUT):
        return {"ok": True, "task": task, "duplicate": True}
    if _st not in (ST.TASK_SAVED, ST.TASK_PENDING_CONFIRM):
        return {"ok": False, "error": f"task-status={_st}"}
    from ...arch_routes.execution import conv_root_project
    conv_id = conv["id"]
    # 同会话活跃任务互斥(一次一个 subagent 回合); 命中先惰性自愈——
    # 服务重启可能留下僵尸 running(泵丢失), 核对 runner 实际态后再裁决
    other = next((t for t in store.TasksStore.of_conv(conv_id)
                  if t["id"] != task_id and t.get("status") in ("running", ST.TASK_WAITING_INPUT)), None)
    if other:
        try:
            _eb().recover_conv_tasks(conv_id)
        except Exception:  # noqa: BLE001
            pass
        other = next((t for t in store.TasksStore.of_conv(conv_id)
                      if t["id"] != task_id and t.get("status") in ("running", ST.TASK_WAITING_INPUT)), None)
    if other:
        return {"ok": False,
                "error": f"另一任务执行中({other['title']}), 停止或等待其结束"}
    # 执行器选定单源(hint > 任务卡 > 注册表默认); 不再字面回落 opencode——
    # 解析不到 → 任务显式 failed(用户要求: 指定失败必须明确返回, 禁止降级)。
    # 先于项目根解析: 缺执行器是更前置的错误, 优先显式暴露。
    from ...arch_routes.agent_executors import normalize_executor_type, default_executor
    hint = _eb().executor_hint_by_id(task.get("executorId") or "", conv) or {}
    _etype = normalize_executor_type(hint.get("executorType")
                                     or task.get("executorType") or "")
    if not _etype:
        _etype = normalize_executor_type((default_executor() or {}).get("type") or "")
    if not hint and not (task.get("executorId") or ""):
        # 配置同源兜底(cv-158): 任务只有类型没有 id(默认执行器早期版本只写 type)
        # → 取注册表默认项的完整配置(/models/provider/key), 否则 sidecar 收到空 model
        hint = _eb().executor_hint_by_id(str((default_executor() or {}).get("id") or ""), conv) or {}
        _etype = _etype or normalize_executor_type(hint.get("executorType") or "")
    if not _etype:
        err = ("无可用执行器：任务未绑定执行器且注册表无默认项——"
               "请在任务卡上选择执行器或在「执行器配置」设置默认。")
        store.TasksStore.finish(task_id, "failed", err)
        _publish_task(conv_id, store.TasksStore.get(task_id) or {})
        return {"ok": False, "error": err}
    root, project = conv_root_project(conv)
    if not root:
        store.TasksStore.update(task_id, {"status": "failed",
                                          "result_md": "无法解析项目根(会话未绑定项目)"})
        return {"ok": False, "error": "no-project-root"}
    rid = task.get("reqId") or ""
    # 分支单源(续跑断裂修复, cv-181 实证): 分支由 propose 决定并落任务行
    # (失败任务复用其分支), confirm 只消费——此前此处无条件重算 task/{own-id}
    # 覆盖续跑分支, runner 侧续跑机制从未被触发过。
    branch = str(task.get("branch") or "").strip() \
        or f"task/{task_id.replace('task-', '')}"
    boundary_files = _eb()._resolve_boundary_files(rid, root, project)
    # 范围探针(环节十三): 规约边界为空 → grounding 补全(单次 LLM, 带来源引用),
    # 结果并回需求边界(里程碑回写同款闭环); 失败不阻断执行
    probe_note = ""
    _scope_fallback_done = False
    if rid and not boundary_files:
        _probe_ok = False
        try:
            from ...agent.planning.scope_probe import probe_scope
            from ...agent.compensation.overrides import read_overrides
            _r = store.RequirementsStore.get(rid) or {}
            _a = _r.get("analysis") or {}
            _req_text = "\n".join(str(x) for x in (
                _r.get("title"), _r.get("desc"),
                _a.get("requirementMd") or (store.RequirementsStore.spec_active(rid)
                                            or {}).get("snapshot", {}).get("requirementMd"),
                _a.get("designMd")) if x)
            from ...agent.governance.gears import DEFAULT_TIER_ID as _DT
            pr = probe_scope(root, project, _req_text, rid=rid,
                             tier=str(getattr(_eb()._task_gear(task), "tier", "")
                                      or _DT))
            if pr.get("ok") and pr.get("files"):
                _probe_ok = True
                new = [f["path"] for f in pr["files"] if f["path"] not in boundary_files]
                if new:
                    boundary_files = sorted(set(boundary_files) | set(new))
                    _eb()._merge_req_scope(rid, new)
                    probe_note = (f"\n> 🔎 范围探针补全边界 {len(new)} 项"
                                  f"({', '.join(new[:6])})——已并回需求边界。")
        except Exception as e:  # noqa: BLE001 — 探针失败 → 走 R2.3 兜底
            logger.info("[exec-bridge] 范围探针失败: %s", e)
        # R2.3(开关 r2_3_probe_fallback, 默认启用): 探针失败/无产出 →
        # 文件树+历史边界启发式兜底(零 LLM), 并明示降级来源
        if not _probe_ok:
            try:
                from ...agent.planning.scope_probe import heuristic_scope_fallback
                from ...agent.compensation.overrides import (override_enabled,
                                                            read_overrides)
                if override_enabled(read_overrides(store.CollabConfigStore.get),
                                    "r2_3_probe_fallback"):
                    fb = heuristic_scope_fallback(root, _req_text, exclude_rid=rid)
                    if fb.get("ok") and fb.get("files"):
                        new = [f["path"] for f in fb["files"]
                               if f["path"] not in boundary_files]
                        if new:
                            boundary_files = sorted(set(boundary_files) | set(new))
                            _eb()._merge_req_scope(rid, new)
                            _scope_fallback_done = True
                            probe_note = (f"\n> 🧭 范围探针降级：文件树/历史边界启发式"
                                          f"补全 {len(new)} 项({', '.join(new[:6])})——"
                                          "来源为启发式先验, 精度有限, 已并回需求边界。")
            except Exception as e:  # noqa: BLE001
                logger.info("[exec-bridge] 范围兜底失败: %s", e)
        if not boundary_files and not _scope_fallback_done:
            probe_note = "\n> ⚠️ 范围探针不可用，本次执行无互斥保护。"
    # 存在性检查(环节十三): 不存在的边界文件 = 预期新建, 注入指令显式声明
    missing_note = ""
    try:
        from ...agent.governance.boundary import files_exist
        _existing, _missing = files_exist(root, boundary_files)
        if _missing and _existing:
            missing_note = (f"\n> 边界中不存在的文件(预期新建): "
                            f"{', '.join(_missing[:8])}。")
    except Exception:  # noqa: BLE001
        pass
    # 安全等级消费(三值轴): readonly 豁免互斥+强制就地; high-stakes worktree 强制
    _safety = str(task.get("safetyClass") or "").strip().lower() or ST.SAFETY_MUTATING
    if _safety not in ST.SAFETY_CLASSES:
        _safety = ST.SAFETY_MUTATING
    conflict = None
    if _safety != ST.SAFETY_READONLY:
        conflict = _eb()._check_mutex(conv, root, boundary_files)
    if conflict:
        store.TasksStore.finish(task_id, "failed", f"边界冲突: {conflict}")
        return {"ok": False, "error": conflict}
    payload = {"root": root,
               "branchName": branch, "projectId": project,
               "boundaries": {"files": boundary_files, "components": [],
                              "readOnly": _safety == ST.SAFETY_READONLY}}
    # 挡位策略(环节十二a): 指令按挡分叉 + 任务级轮次上限随挡下发
    policy = _eb()._task_gear(task, conv)
    # cv-205: 执行形态事实(与 payload.worktree 同源——会话隔离开关), 经
    # runtime 传入指令组装, 环境段/身份段按形态分叉(文案单源 exec_env)
    # cv-202: worktree 隔离仅用户显式开启(会话隔离开关)时请求;
    # 安全等级方向覆盖(G2 补偿矩阵): readonly 强制就地 / high-stakes 强制隔离。
    # 决策须先于指令组装(runtime.workspace 文案与执行形态同源)。
    if _safety == ST.SAFETY_READONLY:
        payload["worktree"] = False
    elif _safety == ST.SAFETY_HIGH_STAKES:
        payload["worktree"] = True
    else:
        payload["worktree"] = bool((conv or {}).get("isolated"))
    _ws = "worktree" if bool(payload["worktree"]) else "inplace"
    payload["instruction"] = _eb()._task_instruction(task, _eb()._task_chain_brief(conv_id, task_id),
                                               policy=policy,
                                               runtime={"branch": branch, "root": root,
                                                        "workspace": _ws},
                                               probe_score=(hint.get("executorConfig") or {})
                                               .get("probeScore")) \
        + probe_note + missing_note
    # hint 已含注册表默认兜底(上方选定单源)——此处不得按空 executorId 重查覆盖
    for k in ("model", "basePort", "autoStart", "baseUrl"):
        v = hint.get(k)
        if v not in (None, ""):
            payload[k] = v
    if hint.get("executorId"):
        payload["executorId"] = hint["executorId"]
        payload["executorConfig"] = {**(hint.get("executorConfig") or {}),
                                     # 任务级轮次随挡下发(挡位表单源, 覆盖注册表默认)
                                     "max_iterations": policy.max_iterations}
    if _etype:
        payload["executorType"] = _etype   # 引擎选择以 task 为准(无注册表也可指定)
    # V1 验收门禁配置透传(P0 显式配置来源; 任务行 verifyConfig → runner 发现链)
    if task.get("verifyConfig"):
        payload["verify"] = task["verifyConfig"]
    # 回合超时配置下发(执行器注册表 config → runner 看门狗参数)
    _cfg = hint.get("executorConfig") or {}
    for k in ("turnTimeout", "stallSec"):
        v = _cfg.get(k)
        if isinstance(v, (int, float)) and v > 0:
            payload[k] = float(v)
    # 复活执行器原生会话(跨回合连续性): task 行持 sessionRef
    if task.get("sessionRef"):
        payload["sessionRef"] = task["sessionRef"]
    # P5: 规约/规则/agent 配置落盘 worktree（per-executor 路径映射）
    workspace_files = _eb()._build_workspace_files(_etype or "", _cfg, task)
    if workspace_files:
        payload["workspaceFiles"] = workspace_files

    # 链式基点(本地 PR 语义): 同会话最近未合并终态分支 head → worktree
    # 物理包含前序代码; 已合并则回落 HEAD(不传, runner 取当前 HEAD)
    try:
        _cb = _eb()._chain_base(conv_id, task_id, root)
        if _cb:
            payload["baseCommit"] = _cb
    except Exception:  # noqa: BLE001 — 基点解析失败回落 HEAD
        pass
    # cv-202: worktree 隔离已在指令组装前按安全等级/会话开关决策(上方)
    # G2 补偿矩阵: high-stakes × 无交互确认能力的执行器(approval=False) →
    # 门禁失效面以「强制隔离 + 合并 precheck 显式」补偿, 并在指令中明示
    if _safety == ST.SAFETY_HIGH_STAKES:
        try:
            from .capabilities import caps as _xcaps
            _xc = _xcaps(_etype or "")
            if not bool(_xc.get("approval", False)):
                payload["instruction"] += (
                    "\n\n> 🛡️ **高风险补偿**：该执行器不支持交互确认(approval)——"
                    "本次执行已强制 worktree 隔离，变更经分支合并(merge precheck)才生效，"
                    "不直接写入主目录；请在回执中显式列出全部改动文件。")
        except Exception:  # noqa: BLE001 — 能力矩阵异常不阻塞下发
            pass

    sr = _eb()._client().start_implement(payload, 20.0)
    if not sr.ok:
        err = sr.error or "runner 服务不可达(:3458)"
        store.TasksStore.finish(task_id, "failed", err)
        return {"ok": False, "error": err}
    store.TasksStore.update(task_id, {
        "status": "running", "runner_job_id": sr.job_id,
        "worktree": sr.worktree, "branch": sr.branch or branch,
        "workspace": sr.workspace or "inplace",
        "session_ref": sr.session_id,
        "baseCommit": sr.base_commit})
    try:
        store.ConversationsStore.set_work_state(conv_id, "running")
    except Exception:  # noqa: BLE001
        pass
    agent = task.get("executorType") or _etype
    pid = (conv or {}).get("projectId") or ""
    # cv-203: 启动状态独立专用状态卡(原位更新), 不再落 🚀 文本回执——
    # 状态/进度不与文本混流; 就地/隔离形态与回落提示进状态卡附注
    _loc = ("隔离 worktree" if (sr.workspace or "inplace") == "worktree"
            else "就地模式(直接写入项目目录)")
    _note = f"`{sr.job_id}` · {_loc}"
    _warn = str((sr.raw or {}).get("notice") or "")
    if _warn:
        _note += f"\n\n> ⚠️ {_warn}"
    _eb().task_status_card(conv_id, task_id, "running", agent=agent, pid=pid,
                           note=_note)
    _eb()._start_task_pump(conv_id, task_id, sr.job_id, rid, agent)
    t = store.TasksStore.get(task_id) or {}
    _publish_task(conv_id, t)
    _flow_recompute(conv_id, trigger="task-confirm")
    return {"ok": True, "task": t}


def task_set_verify_config(task_id: str, cfg: dict) -> Optional[dict]:
    """设定任务验收门禁配置(V1 P0 最高权威来源; 未开始(saved|pending_confirm)
    可改——running 配置已随 start payload 下发, 再改不生效)。白名单收敛+越界钳制。"""
    task = store.TasksStore.get(task_id)
    if not task or (task.get("status") or "") not in (ST.TASK_SAVED,
                                                      ST.TASK_PENDING_CONFIRM):
        return None
    clean: dict = {}
    for k in ("maxAttempts", "autoRepair", "timeoutMul", "build", "test"):
        v = (cfg or {}).get(k)
        if v is None or v == "":
            continue
        if k == "autoRepair":
            clean[k] = bool(v) if isinstance(v, bool) \
                else str(v).strip().lower() == "true"
        elif k == "maxAttempts":
            try:
                clean[k] = max(1, min(int(v), 6))
            except (TypeError, ValueError):
                return None
        elif k == "timeoutMul":
            try:
                clean[k] = max(0.5, min(float(v), 10.0))
            except (TypeError, ValueError):
                return None
        else:
            clean[k] = str(v).strip()[:500]
    store.TasksStore.update(task_id, {"verifyConfig": clean})
    return store.TasksStore.get(task_id)


def task_set_executor(task_id: str, executor_type: str) -> Optional[dict]:
    """设定任务执行器(别名归一: cline→cline-sdk)。仅 pending_confirm 可换——
    运行中引擎已固化(换=新任务); 返回更新后任务行(不可换返回 None)。"""
    from ...arch_routes.agent_executors import normalize_executor_type
    from ...agent.execution.capabilities import is_valid_type
    task = store.TasksStore.get(task_id)
    if not task or (task.get("status") or "") not in (ST.TASK_SAVED,
                                                      ST.TASK_PENDING_CONFIRM):
        return None
    etype = normalize_executor_type(executor_type)
    if not is_valid_type(etype):        # B1 单源: 替代散落元组成员判断
        return None
    return store.TasksStore.update(task_id, {"executor_type": etype})


def task_input(task_id: str, text: str, echo: bool = True) -> Dict[str, Any]:
    """用户回复 → 转达 subagent(waiting_input 立即; running 排队续跑)。

    审批指令: `/approve {requestId}` | `/deny {requestId} [理由]` →
    转发 runner approval 端点(越界确认桥), 不作为回合输入。
    echo(R4 回声): 转达成功时在主流落一条带 requestId 的持久回执
    (role=user, meta.kind=task_input_echo)——「发出→落地」可对账; 投喂等
    已自带落流的调用方传 echo=False 防双写。
    """
    from ..governance.timeouts import get as _timeout_of
    task = store.TasksStore.get(task_id)
    if not task or (task.get("status") or "") not in (ST.TASK_WAITING_INPUT, "running"):
        if task and (task.get("status") or "") == ST.TASK_SAVED:
            return {"ok": False, "error":
                    "任务未开始(已保存)——请在任务卡点「开始执行」后再投递输入。"}
        return {"ok": False, "error": "task-not-active"}
    stripped = (text or "").strip()
    approve = stripped.startswith("/approve ")
    deny = stripped.startswith("/deny ")
    if approve or deny:
        parts = stripped.split(None, 2)
        request_id = parts[1].strip() if len(parts) > 1 else ""
        if not request_id:
            return {"ok": False, "error": "缺少 requestId（用法: /approve {id} 或 /deny {id} [理由]）"}
        reason = parts[2].strip() if len(parts) > 2 else ""
        job_id = str(task.get("runnerJobId") or "")
        res = _eb()._client().approval(job_id, request_id, approve,
                                 reason or ("approved" if approve else "rejected by user"),
                                 15.0)
        if res and res.get("ok"):
            conv_id = task.get("conversationId") or ""
            _eb()._append(conv_id, "assistant",
                    f"{'✅ 已批准' if approve else '🚫 已拒绝'} 工具调用 `{request_id}`。",
                    msg_meta={"kind": "task_approval_done", "taskId": task_id},
                    project_id=(store.ConversationsStore.get(conv_id) or {}).get("projectId") or "")
            # 需求跟踪台账: 决议回填(按 requestId 定位挂起的「决策」条目)
            try:
                from ...store.tracking import TrackingItemsStore
                from ...store.states import TRACK_DONE, TRACK_WAITING
                for d in TrackingItemsStore.find_by_ref("approval", request_id, category="决策"):
                    if (d.get("state") or "") == TRACK_WAITING:
                        TrackingItemsStore.update(d["id"], {
                            "state": TRACK_DONE, "waitingFor": "",
                            "result": ("批准" if approve else "拒绝") + (f"：{reason}" if reason else ""),
                            "resultState": "ok"})
            except Exception:  # noqa: BLE001
                pass
            return {"ok": True, "approval": True}
        return {"ok": False, "error": (res or {}).get("error") or "审批转发失败"}
    # P4: running 态优先 steer 直达（cline pending 优先投递）；
    # runner 侧不支持的执行器自动回退排队
    steer = (task.get("status") or "") == "running"
    res = _eb()._client().input(str(task.get("runnerJobId") or ""), stripped[:12000],
                          steer=steer, timeout=_timeout_of("runner_steer"))
    if res.ok:
        if (task.get("status") or "") == ST.TASK_WAITING_INPUT:
            store.TasksStore.update(task_id, {"status": "running"})
            t = store.TasksStore.get(task_id) or {}
            _publish_task(task["conversationId"], t)
        request_id = uuid.uuid4().hex[:12]
        if echo:
            # A6.4 降级提示(回执卡, 拍板 2026-09-17): 实际送达语义显式可见
            delivery = getattr(res, "delivery", "") or (
                "queued" if res.queued else "started")
            reason = getattr(res, "reason", "")
            note = {
                "steered": "⚡ 已直达执行中回合（steer）",
                "queued": "⏳ 已排队，当前回合结束后送达"
                          + (f"——{reason}" if reason else ""),
                "started": "✓ 已作为新回合下发",
            }.get(delivery, "")
            conv_id = task.get("conversationId") or ""
            _eb()._append(conv_id, "user",
                    stripped[:12000] + (f"\n\n---\n_{note}_" if note else ""),
                    msg_meta={"kind": "task_input_echo", "taskId": task_id,
                              "requestId": request_id, "queued": res.queued,
                              "steer": steer, "delivery": delivery,
                              "reason": reason},
                    project_id=(store.ConversationsStore.get(conv_id) or {}
                                ).get("projectId") or "")
        return {"ok": True, "queued": res.queued, "requestId": request_id,
                "delivery": getattr(res, "delivery", ""), "reason": getattr(res, "reason", "")}
    return {"ok": False, "error": res.error or "runner 不可达"}




def ignore_task(task_id: str) -> Dict[str, Any]:
    """用户主动忽略(软删置灰, 2026-09-20 产品裁决): 仅未开始(saved)卡可忽略。

    终态 ignored: 排除互斥/恢复, 流内卡片置灰可追溯; 同需求可重新建卡。
    同会话状态迁移锁内执行——防与 confirm 慢启动竞态(忽略被 running 覆写复活)。"""
    task = store.TasksStore.get(task_id)
    if not task:
        return {"ok": False, "error": "task-not-found", "code": 404}
    conv_id = task.get("conversationId") or ""
    with _conv_task_lock(conv_id):
        task = store.TasksStore.get(task_id) or task
        if (task.get("status") or "") != ST.TASK_SAVED:
            return {"ok": False, "error":
                    f"仅未开始(saved)任务可忽略(当前 {task.get('status')})——"
                    "运行中请先停止, 已完成/已忽略无需忽略。", "code": 409}
        task = store.TasksStore.update(task_id, {"status": ST.TASK_IGNORED}) or task
        conv_id = task.get("conversationId") or ""
        _eb()._append(conv_id, "assistant",
                      f"🚫 **任务已忽略**：{task.get('title')}",
                      msg_meta={"kind": "task_ignored", "taskId": task_id})
        _publish_task(conv_id, task)
        _flow_recompute(conv_id, trigger="task-ignore")
        return {"ok": True, "task": task}


def dismiss_task(task_id: str) -> Dict[str, Any]:
    """回执已阅(dismiss, reviewing 消化出口): 仅 done 态。

    与 ignore 语义区分: ignore=saved 卡不执行; dismiss=done 回执已阅
    (不合并/不建下张卡的用户显式消化)。不改终态, dismissed_at 留痕可追溯。"""
    task = store.TasksStore.get(task_id)
    if not task:
        return {"ok": False, "error": "task-not-found", "code": 404}
    if (task.get("status") or "") != ST.TASK_DONE:
        return {"ok": False, "error":
                f"仅已完成(done)任务可标记已阅(当前 {task.get('status')})——"
                "未开始卡请用忽略, 运行中请先停止。", "code": 409}
    if task.get("dismissedAt"):
        return {"ok": True, "task": task}   # 幂等: 已阅重复标记无副作用
    task = store.TasksStore.update(task_id, {
        "dismissedAt": int(time.time() * 1000)}) or task
    conv_id = task.get("conversationId") or ""
    _publish_task(conv_id, task)
    _flow_recompute(conv_id, trigger="task-dismiss", force=True)
    return {"ok": True, "task": task}


def task_stop(task_id: str, reason: str = "") -> Dict[str, Any]:
    """停止任务(保留 worktree/分支)。同会话状态迁移锁内执行——
    防与 confirm 慢启动竞态(取消被 running 覆写成僵尸任务); 锁内重读状态。"""
    task = store.TasksStore.get(task_id)
    if not task:
        return {"ok": False, "error": "task-not-active"}
    with _conv_task_lock(task.get("conversationId") or ""):
        task = store.TasksStore.get(task_id) or task
        if (task.get("status") or "") in _eb()._TASK_TERMINAL:
            return {"ok": False, "error": "task-not-active"}
        if (task.get("status") or "") in (ST.TASK_SAVED, ST.TASK_PENDING_CONFIRM):
            store.TasksStore.finish(task_id, "cancelled", reason or "用户取消")
            t = store.TasksStore.get(task_id) or {}
            _publish_task(task["conversationId"], t)
            _flow_recompute(task["conversationId"], trigger="task-stop")
            return {"ok": True, "task": t}
        from ..governance.timeouts import get as _timeout_of
        _eb()._client().finish(str(task.get("runnerJobId") or ""), keep_worktree=True,
                               timeout=_timeout_of("runner_finish"))
        store.TasksStore.finish(task_id, "cancelled", reason or "用户停止")
        for fut in (_eb()._TASK_PUMPS.pop(task["conversationId"], None) or {}).values():
            fut.cancel()
        _task_reaggregate_work_state(task["conversationId"])
        t = store.TasksStore.get(task_id) or {}
        _publish_task(task["conversationId"], t)
        return {"ok": True, "task": t}


def active_task_of(conv_id: str) -> Optional[dict]:
    """最新活跃任务(running/waiting_input 优先, 次 pending_confirm); 无则 None。"""
    ts = store.TasksStore.of_conv(conv_id)
    for t in reversed(ts):
        if (t.get("status") or "") in ("running", ST.TASK_WAITING_INPUT):
            return t
    for t in reversed(ts):
        if (t.get("status") or "") == ST.TASK_PENDING_CONFIRM:
            return t
    return None


def _publish_task(conv_id: str, task: dict) -> None:
    """任务状态变更 → SSE 单通道广播(前端 TaskCard/过滤器响应)。"""
    try:
        from ...agent.collab.sse import emit
        emit("task", conv_id, task=task)
    except Exception:  # noqa: BLE001
        pass


def _task_reaggregate_work_state(conv_id: str) -> None:
    """任务终态后: 无其它活跃任务 → workState 回 architect 相位。

    (workState 为兼容读投影; 流程相位以 flow_state 为准——此处顺带重算。)"""
    try:
        if not active_task_of(conv_id):
            store.ConversationsStore.set_work_state(conv_id, "architect")
    except Exception:  # noqa: BLE001
        pass
    _flow_recompute(conv_id, trigger="task-settled")
