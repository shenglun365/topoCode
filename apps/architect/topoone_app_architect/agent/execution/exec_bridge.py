"""执行作业桥接泵(exec_bridge)——architect 会话 ↔ runner 实施作业(多实例)。

生命周期 v2(P3 清退旧 jobs 写路径):
- 唯一路径 = arch_tasks 任务模型(propose→confirm→泵); conv.meta.jobs 仅存量只读兼容
- workState 聚合: 存在非终态作业 → 会话 running(双收件人, 输入不锁); 全部终态 → architect
- 纯下行泵: 作业事件(提问/进度/完成/失败)批量落会话消息——**无上行自动转发**
  (裁决#6.1); 用户补充经「继续执行」显式增量回合交回等待中的作业
- 停止: 仅 UI 按钮(REST)调用 stop(); 无自然语言通道(裁决#5)
- 验收简报: done 时自动生成(实际改动 vs 规约边界越界检测 + 验收标准对照),
  消息带 meta {jobId, kind, branch} 供前端渲染验收操作
"""
import asyncio
import json
import logging
import os
import re
import time
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

from ... import store
from ...store import states as ST
from ...agent.execution.runner_client import RunnerClient

logger = logging.getLogger(__name__)

RUNNER_BASE = os.environ.get("RUNNER_BASE_URL", "http://127.0.0.1:3458").rstrip("/")
# architect 自身服务地址(runner 侧 turn_adapter 同名同缺省约定, 跨包一致)——
# 执行器会话 MCP 默认接线(ctx.* 历史检索)的 URL 基址; env 可覆盖。
ARCH_BASE = os.environ.get("ARCH_BASE_URL", "http://127.0.0.1:3470").rstrip("/")
_TERMINAL = ("done", "failed", "stopped", "lost")   # 存量 jobs 账本终态(只读兼容)


def _runner(path: str, payload: Optional[dict] = None, timeout: float = 12.0) -> Optional[dict]:
    try:
        if payload is None:
            req = urllib.request.Request(f"{RUNNER_BASE}{path}")
        else:
            req = urllib.request.Request(
                f"{RUNNER_BASE}{path}", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001
        logger.debug("[exec-bridge] runner %s failed: %s", path, e)
        return None


def _client() -> "RunnerClient":
    """类型化 runner 访问端(R1 收敛裸 HTTP 调用; G7 关闭)。

    调用时构造、晚绑定模块级 _runner——保持既有 monkeypatch.setattr(eb, "_runner")
    测试接缝不变(导入期绑定会使打桩失效)。
    """
    return RunnerClient(_runner)


def _ts() -> int:
    return int(time.time() * 1000)


def _meta_of(conv_id: str) -> dict:
    conv = store.ConversationsStore.get(conv_id) or {}
    meta = conv.get("meta")
    if isinstance(meta, dict):
        return meta
    try:
        return json.loads(meta or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _save_meta(conv_id: str, meta: dict) -> None:
    import copy
    fresh = _meta_of(conv_id)
    fresh.update({k: v for k, v in meta.items() if not k.startswith("_")})
    store.ConversationsStore.update(conv_id, {"meta": json.dumps(fresh, ensure_ascii=False)})


# ── 账本(jobs[]) ──

def jobs_of(conv_id: str) -> List[dict]:
    j = _meta_of(conv_id).get("jobs")
    return j if isinstance(j, list) else []


def _job_upsert(conv_id: str, job: dict) -> None:
    meta = _meta_of(conv_id)
    jobs = meta.get("jobs") if isinstance(meta.get("jobs"), list) else []
    for i, e in enumerate(jobs):
        if e.get("jobId") == job.get("jobId"):
            jobs[i] = {**e, **job}
            break
    else:
        jobs.append(job)
    meta["jobs"] = jobs[-20:]          # 账本留最近 20 条
    _save_meta(conv_id, meta)
    _aggregate_work_state(conv_id)


def _aggregate_work_state(conv_id: str) -> None:
    """workState 聚合: 非终态作业存在 ⇔ running。

    (legacy jobs 兼容面; 流程相位以 arch_tasks 驱动的 flow_state 为准。)"""
    live = [j for j in jobs_of(conv_id) if (j.get("status") or "") not in _TERMINAL]
    try:
        store.ConversationsStore.set_work_state(conv_id, "running" if live else "architect")
    except Exception:  # noqa: BLE001
        pass
    try:   # 流程相位重算(作业账本变化即占用事实变化; fail-soft)
        from ...agent.governance import flow as _flow
        _flow.recompute(conv_id, trigger="job-settled")
    except Exception:  # noqa: BLE001
        pass
def _meta_dict_of(conv: dict) -> dict:
    meta = (conv or {}).get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (TypeError, ValueError):
            meta = {}
    return meta or {}
# ── 会话消息 ──

def _append(conv_id: str, role: str, content: str, msg_meta: Optional[dict] = None,
            project_id: str = "", agent: str = "") -> Optional[dict]:
    """委托 collab.cards.land(卡片落流唯一出口, cv-175 规范化)。

    返回落库行(含 id; 供调用方回指 WS done 帧 messageId; cv-259 直通收口用),
    失败 None。"""
    from ...agent.collab import cards as _cards
    meta = dict(msg_meta or {})
    return _cards.land(conv_id, content, kind=meta.pop("kind", None), role=role,
                       project_id=project_id, agent=agent, **meta)

def _copy_impl_flag(worktree: str, changed_files: List[str],
                    turn_text: str = "") -> str:
    """复制实现检测(本地 PR 语义·验证有效性, cv-181 实证): 测试/脚手架文件
    自包含定义被测函数且未引用任何生产源码文件 → 14/14 PASS 测的是副本。

    生产引用判定(语言无关, 双通道): #include/import 的目标路径在仓库内
    存在 = 引用了生产代码。自包含 + 零生产引用 → 标注; 若交付摘要显式
    声明"复制实现"(诚实通道, DoD 第 4 条) → 降级为备注而非警告。
    """
    if not worktree or not changed_files:
        return ""
    test_files = [f for f in changed_files
                  if "test" in os.path.basename(f).lower()
                  or f.lower().startswith(("tests/", "test/"))][:10]
    if not test_files:
        return ""
    declared = "复制实现" in (turn_text or "")
    flagged = []
    for rel in test_files:
        path = os.path.join(worktree, rel)
        if not os.path.isfile(path):
            continue
        try:
            content = open(path, encoding="utf-8", errors="replace").read()
        except Exception:  # noqa: BLE001
            continue
        if len(content) < 100:      # 空壳文件跳过; 实质门槛是下方 defs>=3
            continue
        includes = re.findall(r'#include\s+[<"]([^">]+)[">]', content)
        imports = re.findall(r'^\s*(?:from\s+([\w.]+)\s+import|import\s+[\w.]+)',
                             content, re.M)
        candidates = [x for x in includes + imports if x]
        prod_linked = any(os.path.isfile(os.path.join(worktree, x.lstrip("./")))
                          or os.path.isfile(os.path.join(
                              worktree, x.lstrip("./") + ".py"))
                          for x in candidates)
        if prod_linked:
            continue
        # 函数定义数(C 风格 / Python def)——纯常量/宏文件不算
        defs = len(re.findall(r'^\s*(?:[\w\*]+\s+)+\w+\s*\([^;{]*\)\s*\{',
                              content, re.M)) \
            + len(re.findall(r'^\s*def\s+\w+\s*\(', content, re.M))
        if defs >= 3:
            flagged.append(rel)
    if not flagged:
        return ""
    files = "\n".join(f"- `{f}`" for f in flagged[:3])
    if declared:
        return ("\n\n**ℹ️ 复制实现声明已收到**(摘要中显式说明, 降级为备注)：\n"
                + files + "\n以上测试文件未引用生产源码——按声明为有意镜像, "
                "请知悉其验证范围限于镜像副本。")
    return ("\n\n**⚠️ 疑似复制实现**(验证有效性提示)：\n" + files
            + "\n以上测试文件自包含定义了被测函数且未引用任何生产源码——"
            "14/14 PASS 类结果**只验证了副本**，未触及真实代码。"
            "请核查测试对象；若属有意镜像，请在交付摘要中声明\"复制实现\"及原因。")


def _acceptance_brief(conv_id: str, rid: str, changed_files: List[str]) -> str:
    """验收简报: 实际改动 vs 规约边界(越界检测) + 验收标准静态对照。

    architect 辅助判定材料——完成与否由用户判定(裁决#3)。
    """
    from ..tools.req_agent import parse_scope_files
    active = store.RequirementsStore.spec_active(rid or "") or {}
    snap = active.get("snapshot") or {}
    scope_files = parse_scope_files(snap.get("allowedScope") or [])
    out_lines = []
    if scope_files:
        overrun = [f for f in changed_files
                   if not any(f.startswith(p) for p in scope_files)]
        if overrun:
            out_lines.append("**⚠️ 越界改动**(超出规约允许范围，请核查)：\n"
                             + "\n".join(f"- `{f}`" for f in overrun[:15]))
        else:
            out_lines.append(f"✅ 边界符合：{len(changed_files)} 个改动文件均在允许范围内")
    else:
        out_lines.append("ℹ️ 规约未声明可解析边界，无法做越界检测")
    acc = snap.get("acceptance") or []
    if acc:
        out_lines.append("**验收标准对照**(静态，逐条人工确认)：\n"
                         + "\n".join(f"- [ ] {a}" for a in acc[:12]))
    return "\n\n".join(out_lines)


# ── 互斥引擎(裁决#1/#2/#9) — 实现迁至 agent.governance.boundary(P2), 薄委托 ──

def _resolve_boundary_files(rid: str, root: str, project: Optional[str]) -> List[str]:
    from ...agent.governance.boundary import resolve_boundary_files
    return resolve_boundary_files(rid, root, project)


def _check_mutex(conv: dict, root: str, boundary_files: List[str]) -> Optional[str]:
    from ...agent.governance.boundary import check_mutex
    return check_mutex(conv, root, boundary_files, runner=_runner)


def _files_intersect(a: List[str], b: List[str]) -> List[str]:
    from ...agent.governance.boundary import files_intersect
    return files_intersect(a, b)
# ── 下发域(M4 拆分): propose/confirm/task_input/setters/stop 迁
# agent/execution/dispatch.py(与 DispatchTurn 协作); re-export 保持 REST/测试接缝。
from ...agent.execution.dispatch import (_last_failed_branch, _last_failed_task,
                                        ignore_task,
                                        _publish_task, _task_reaggregate_work_state,
                                        active_task_of, confirm_task, propose_task,
                                        stop, task_input, task_set_executor,
                                        task_set_verify_config, task_stop)
_WS_IDLE_SEC = 10.0        # 订阅空闲窗口(超时→snapshot 校准一轮, 保留 lost/终态判定)
_WS_RETRY_GAP = 4          # 订阅失败后的重试间隔(轮询轮)
# ══════════════════════════════════════════════════════════════════
# v2 统一会话: coding subagent 任务模型(arch_tasks)
# 设计: 任务回执以消息(agent=executor_type)落统一流, 本节只管生命周期。
# 轻门禁: pending_confirm(任务卡确认) → running → waiting_input → 终态。
# 解耦: 本层不感知 executor 内部(TurnAdapter 协议隔离), agent 标注 =
# task.executorType(architect 泵统一写)。
# ══════════════════════════════════════════════════════════════════

_TASK_TERMINAL = ("done", "failed", "cancelled")
_TASK_ACTIVE = (ST.TASK_PENDING_CONFIRM, "running", ST.TASK_WAITING_INPUT)


# ── 合并域(M2 拆分): 实现迁 agent/execution/merge.py, 此处 re-export ──
# (sessions REST 与测试经 eb.* 引用, 接缝保持不变; runner 打桩经调用期解析仍生效)
from ...agent.execution.merge import (_chain_base, _post_merge_cleanup,
                                     _unmerged_branch_notes, merge_branch,
                                     merge_precheck)


# ── 任务泵: 事件 → 统一流(agent 标注) ──

_TASK_PUMPS: Dict[str, dict] = {}   # conv_id -> {job_id: asyncio.Task}
_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop) -> None:
    """服务启动时捕获主事件循环: REST to_thread 工作线程内启动泵须调度回这里
    (工作线程无循环, create_task 必炸——cv-153 泵从未启动的真根因)。"""
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def _start_task_pump(conv_id: str, task_id: str, job_id: str, rid: str,
                     agent: str) -> None:
    jobs = _TASK_PUMPS.setdefault(conv_id, {})
    old = jobs.get(job_id)
    if old and not old.done():
        return
    coro = _task_pump(conv_id, task_id, job_id, rid, agent)
    try:
        loop = asyncio.get_running_loop()
        jobs[job_id] = loop.create_task(coro)
    except RuntimeError:
        # 工作线程(REST to_thread 等): 调度回主事件循环
        if _MAIN_LOOP is not None and _MAIN_LOOP.is_running():
            jobs[job_id] = asyncio.run_coroutine_threadsafe(coro, _MAIN_LOOP)
        else:
            coro.close()   # 无循环可挂(测试/关停): 丢弃并告警, 不让协程泄漏
            logger.warning("[exec-bridge] 无事件循环可挂任务泵 conv=%s job=%s",
                           conv_id, job_id)


# ── 恢复对账系(M2 拆分): 实现迁 agent/execution/recover.py, re-export 保持接缝 ──
# (泵核 _task_pump/_handle_task_event 与 eb.* 打桩面深耦合, 随 M4 DispatchTurn 迁出)
from ...agent.execution.recover import (recover_conv_tasks, recover_sweep,
                                       start_recover_sweep)


def _task_ctx(conv_id: str, task_id: str, job_id: str, rid: str, agent: str) -> dict:
    conv = store.ConversationsStore.get(conv_id) or {}
    return {"convId": conv_id, "taskId": task_id, "jobId": job_id, "rid": rid,
            "pid": conv.get("projectId") or "", "agent": agent}


_PROGRESS_SSE_LAST: dict = {}   # task_id → 上次 SSE progress 发送时刻(文本节流)


_STATUS_CARD_LAST: Dict[str, float] = {}


def _status_card_refresh(conv_id: str, task_id: str, agent: str, pid: str,
                         min_interval: float = 30.0) -> None:
    """running 态状态卡节流刷新(进度事件高频——30s 一拍足够"状态在动";
    终态/等待态由对应分支即时更新, 不走此节流)。"""
    now = time.time()
    if now - _STATUS_CARD_LAST.get(task_id, 0.0) < min_interval:
        return
    _STATUS_CARD_LAST[task_id] = now
    task_status_card(conv_id, task_id, "running", agent=agent, pid=pid)


def land_plan_progress(conv_id: str, rid: str, text: str, *,
                       total: int = 0, project_id: str = "") -> Optional[dict]:
    """计划进度锚(L3): cards.land_plan_progress 桥(planning 经此落锚, 单源)。"""
    from ...agent.collab import cards as _cards
    return _cards.land_plan_progress(conv_id, rid, text, total=total,
                                     project_id=project_id)


def task_status_card(conv_id: str, task_id: str, status: str,
                     agent: str = "", pid: str = "",
                     note: str = "") -> Optional[dict]:
    """任务状态卡(cv-203 裁决): 状态/进度独立专用消息, 同 taskId 单卡原位更新。

    running/waiting/done/failed 四态 + 进度行(变更文件数/工具数/耗时);
    内容型回执(计划/摘要/验收)仍是独立文本消息——状态不与正文混流。"""
    try:
        t = store.TasksStore.get(task_id) or {}
        prog = t.get("progress") or {}
        title = (t.get("title") or "任务")[:40]
        from ...agent.collab import cards as _cards
        _AGENT = {"icon": agent or "architect"}
        marks = {"running": "🔄 **执行中**", "waiting": "⏸ **等待你的输入**",
                 "done": "✅ **已完成**", "failed": "❌ **失败**",
                 "starting": "🚀 **启动中**"}
        lines = [f"{marks.get(status, '🔄 **执行中**')}「{title}」 · `{agent or 'architect'}`"]
        if t.get("startedAt") or t.get("createdAt"):
            _t0 = int(t.get("startedAt") or t.get("createdAt") or 0)
            if _t0:
                # cv-205: _ts() 本身即毫秒——再 ×1000 产出天文数字(实证
                # 「耗时 29803143334m」)
                _el = max(0, int(_ts() - _t0) // 1000)
                lines.append(f"耗时 {_el // 60}m{_el % 60:02d}s")
        _n = len(prog.get("changedFiles") or [])
        if _n:
            lines.append(f"变更文件 {_n}")
        if prog.get("toolCount"):
            lines.append(f"工具调用 {prog['toolCount']}")
        elif prog.get("lastTool"):
            lines.append(f"最近工具 `{prog['lastTool']}`")
        if note:
            lines.append(str(note)[:200])
        elif prog.get("lastNote"):
            lines.append(f"最近：{str(prog['lastNote'])[:160]}")
        return _cards.land_status(conv_id, "\n\n".join(lines), task_id,
                                  status=status, project_id=pid,
                                  agent=agent or "architect")
    except Exception as e:  # noqa: BLE001
        logger.warning("[exec-bridge] 状态卡更新失败 task=%s: %s", task_id, e)
        return None


def _publish_progress(conv_id: str, task_id: str, prog: dict,
                      throttle: float = 0.0) -> None:
    """任务进度实时推送（WS/SSE 单一出口）。

    throttle>0 时按 task 节流(准流式: 文本片段高频, 0.5s 一拍足够"内容在动";
    工具/终态事件不节流保证不丢关键帧)。"""
    if throttle > 0:
        now = time.time()
        if now - _PROGRESS_SSE_LAST.get(task_id, 0.0) < throttle:
            return
        _PROGRESS_SSE_LAST[task_id] = now
    try:
        from ...agent.collab.sse import emit
        emit("progress", conv_id, taskId=task_id, **{"at": _ts(), **prog})
    except Exception:  # noqa: BLE001
        pass


def _build_workspace_files(executor_type: str, executor_cfg: dict, task: dict) -> list:
    """P5: 执行器约定文件组装（B1 单源 capabilities: cline→.cline/rules|agents
    目录约定; opencode/codex→AGENTS.md 单文件——映射查 caps(), 不再字面判型）。

    数据源（后续接 KB 语义资产的扩展点）:
    - task.rulesMd        任务级规约文本
    - cfg.rulesMd         执行器级规约文本
    - cfg.teams.agents    cline teams 成员配置([{name, content}])
    """
    from ...agent.execution.capabilities import caps
    files: list = []
    cap = caps(executor_type)
    rules_dir = str(cap.get("workspace_rules") or "")
    agents_dir = str(cap.get("workspace_agents") or "")
    rules_parts = []
    for src in (task.get("rulesMd"), (executor_cfg or {}).get("rulesMd")):
        if isinstance(src, str) and src.strip():
            rules_parts.append(src.strip())
    if rules_parts:
        content = "\n\n".join(rules_parts)
        if rules_dir:
            files.append({"path": f"{rules_dir}/000-guide.md", "content": content})
        else:
            files.append({"path": "AGENTS.md", "content": content})
    if agents_dir:
        teams = (executor_cfg or {}).get("teams") or {}
        for a in (teams.get("agents") if isinstance(teams, dict) else []) or []:
            if isinstance(a, dict) and str(a.get("name") or "").strip() \
                    and isinstance(a.get("content"), str):
                name = "".join(c for c in str(a["name"]) if c.isalnum() or c in "-_")
                if name:
                    files.append({"path": f"{agents_dir}/{name}.md",
                                  "content": str(a["content"])})
    return files


def _milestone_report_files(text: str) -> List[str]:
    """里程碑报告固定行(`改动文件: a, b, c`)宽松解析——解析不到返回 []。"""
    if not text:
        return []
    m = re.search(r"改动文件[:：]\s*([^\n]+)", text)
    if not m:
        return []
    raw = re.split(r"[,，;；、\s]+", m.group(1).strip())
    return [x for x in (p.strip().strip("`") for p in raw) if x]


def _milestone_report_payload(text: str) -> List[str]:
    """R3.3 双轨解析: JSON 块契约({changed_files})优先 → 文本固定三行降级。

    JSON 块缺少 changed_files(或非列表)时回落文本解析——两轨都空返回 []。"""
    if not text:
        return []
    try:
        from ...agent.compensation.providers import parse_json_block
        payload, _track = parse_json_block(text)
        if payload and isinstance(payload.get("changed_files"), list):
            files = [str(x).strip() for x in payload["changed_files"] if str(x).strip()]
            if files:
                return files[:40]
    except Exception:  # noqa: BLE001 — JSON 轨异常静默回落文本轨
        pass
    return _milestone_report_files(text)


def _merge_req_scope(rid: str, files: List[str]) -> int:
    """里程碑发现的文件并回需求边界(自我修正闭环: subagent 探索事实 →
    范围先验增强)。优先写 active 规约版本快照, 无版本写 analysis。返回并入数。"""
    if not rid or not files:
        return 0
    try:
        r = store.RequirementsStore.get(rid)
        if not r:
            return 0
        active = store.RequirementsStore.spec_active(rid)
        if active and isinstance(active.get("snapshot"), dict):
            snap = dict(active["snapshot"])
            cur = [str(x) for x in (snap.get("allowedScope") or [])]
            merged = cur + [f for f in files if f not in cur]
            if merged == cur:
                return 0
            snap["allowedScope"] = merged
            versions = store.RequirementsStore.spec_versions(rid)
            for v in versions:
                if v.get("ver") == active.get("ver"):
                    v["snapshot"] = snap
            store.RequirementsStore.update(rid, {"specVersions": versions})
            return len(merged) - len(cur)
        analysis = dict(r.get("analysis") or {})
        cur = [str(x) for x in (analysis.get("allowedScope") or [])]
        merged = cur + [f for f in files if f not in cur]
        if merged == cur:
            return 0
        analysis["allowedScope"] = merged
        store.RequirementsStore.update(rid, {"analysis": analysis})
        return len(merged) - len(cur)
    except Exception:  # noqa: BLE001 — 回写失败不阻断任务流
        return 0


def _sediment_task_receipt(conv_id: str, task_id: str, rid: str, status: str,
                           title: str, summary: str, changed_files,
                           branch: str, pid: str,
                           acceptance_brief: str = "") -> Optional[dict]:
    """知识沉淀(存储归一): 任务终态回执 → execution_report 单元(会话派生记忆, 检索面可捞)。

    归因来源: coding agent 执行报告(正文 summary)——P1 distill-errors 的材料。
    重定位 P3 闭环: 验收材料(边界比对/越界/判据对照)并入沉淀——done 任务的
    验收记录持久化于 execution_report 单元(不再只存活于消息文本)。
    """
    t = store.TasksStore.get(task_id) or {}
    prog = t.get("progress") or {}
    meta_lines = [f"- 任务: {task_id} · 状态: {status}" + (f" · 分支: {branch}" if branch else "")]
    for key, label in (("verifyOverall", "验收"), ("verify_build", "构建"),
                       ("verify_test", "测试")):
        if prog.get(key) is not None:
            meta_lines.append(f"- {label}: {prog[key]}")
    acc_section = ""
    if acceptance_brief:
        acc_section = ("\n\n**验收材料**(资产比对基底)\n" + str(acceptance_brief)[:2000])
    unit = store.ContextUnitsStore.create({
        "conversationId": conv_id, "projectId": pid,
        "type": "execution_report",
        "title": f"任务回执[{status}]：{title}",
        "content": ((summary or "")[:4000] + "\n\n**回执**\n"
                    + "\n".join(meta_lines) + acc_section),
        "refs": {"taskId": task_id, "reqId": rid,
                 "files": [str(f) for f in (changed_files or [])][:50],
                 "executorType": t.get("executorType") or ""},
        "importance": 1})
    # 需求跟踪台账: 回执挂账(终态结果), 失败不阻断沉淀
    try:
        from ...store.tracking import emit as _tr_emit
        from ...store.states import TRACK_DONE, TRACK_FAILED
        ok_receipt = status == "done"
        _tr_emit(category="回执",
                 title=f"任务回执[{status}]：{title}",
                 content=(summary or "")[:2000],
                 action_type="编码", creator_role="coding",
                 creator_id=str(t.get("executorType") or ""),
                 state=(TRACK_DONE if ok_receipt else TRACK_FAILED),
                 result=(summary or "")[:300],
                 result_state=("ok" if ok_receipt else "failed"),
                 ref_type="task", ref_id=task_id,
                 conversation_id=conv_id, project_id=pid)
    except Exception:  # noqa: BLE001
        pass
    return unit


def _handle_task_event(ev: dict, ctx: dict) -> None:
    """v2: runner 事件 → 任务生命周期 + 统一流消息(agent=executor)。

    (P3 起为唯一任务事件路径; 旧 jobs 泵已清退):
    - 无子会话: 全部落主流, agent=ctx.agent;
    - input_required: 消息 + task waiting_input(无熔断计数——统一流天然往返);
    - progress: task.progress + SSE progress(不落消息);
    - done/failed: 终态 + result_md。
    """
    conv_id, task_id, job_id = ctx["convId"], ctx["taskId"], ctx["jobId"]
    pid, agent = ctx["pid"], ctx["agent"]
    kind = ev.get("kind") or ""
    if kind in ("user_input", "session_ready"):
        return
    text = (ev.get("text") or "").strip()
    task = store.TasksStore.get(task_id) or {}
    title = task.get("title") or "任务"
    if kind == "input_required":
        clean = text.replace("[[NEED_INPUT]]", "").strip() or "(等待你的输入)"
        # cv-203 P4: 执行器工具回声 JSON 不入正文(实证: outcome recorded 泄漏)
        clean = re.sub(r'\{"result"\s*:\s*"outcome recorded[^}]*\}', "", clean)
        clean = clean.strip() or "(等待你的输入)"
        # 里程碑报告识别(环节十一): R3.3 双轨——JSON 块契约优先, 固定三行文本
        # 兼容降级(architect 侧解析层, D4 不动 runner); 改动文件并回需求边界
        ms_files = _milestone_report_payload(clean)
        merged = _merge_req_scope(ctx.get("rid") or "", ms_files) if ms_files else 0
        ms_note = ""
        if ms_files:
            shown = "\n".join(f"- `{f}`" for f in ms_files[:12])
            # A1 增强: 回执携带验收状态(实测矩阵) + 规约边界规模——事实→边界,
            # 状态→回执双向回写; 无验收记录不虚构(零假设)
            prog = (store.TasksStore.get(task_id) or {}).get("progress") or {}
            vo = str(prog.get("verifyOverall") or "")
            verify_line = ""
            if vo:
                marks = {"A": "✅ A 结构化验收通过",
                         "B": "✅ B 退出码验收通过",
                         "PASS_WITH_KNOWN": "✅ 通过(含存量失败)",
                         "C": "⚠️ C 未能自动验收——合并前请人工核验",
                         "D": "ℹ️ D 纯文档/资源变更(仅人工审查)"}
                verify_line = "\n\n**验收状态**：" + marks.get(
                    vo, "❌ 验收未过——变更未经验证" if vo == "FAIL" else f"⚠️ {vo}")
            boundary_n = 0
            if ctx.get("rid"):
                try:
                    _snap = (store.RequirementsStore.spec_active(ctx["rid"])
                             or {}).get("snapshot") or {}
                    boundary_n = len(_snap.get("allowedScope") or [])
                except Exception:  # noqa: BLE001
                    pass
            ms_note = (f"\n\n**📋 里程碑报告**（改动文件已并入需求边界"
                       f"{f'，新增 {merged} 项' if merged else ''}"
                       f"{f'，边界共 {boundary_n} 文件' if boundary_n else ''}）\n{shown}"
                       + verify_line)
        _append(conv_id, "assistant",
                f"⏸ **{agent} 需要你的输入**（任务「{title}」）\n\n{clean}"
                + ms_note +
                "\n\n直接回复即转达; 也可 @architect 讨论。",
                msg_meta={"kind": "task_input", "taskId": task_id},
                project_id=pid, agent=agent)
        if ms_files:
            # 知识沉淀(存储归一): 里程碑报告 → analysis 单元
            try:
                store.ContextUnitsStore.create({
                    "conversationId": conv_id, "projectId": pid,
                    "type": "analysis",
                    "title": f"里程碑报告：{title}",
                    "content": clean[:4000],
                    "refs": {"taskId": task_id, "reqId": ctx.get("rid") or "",
                             "files": ms_files[:50], "merged": merged,
                             "verifyOverall": vo},
                    "importance": 1})
            except Exception as e:  # noqa: BLE001
                logger.warning("[exec-bridge] 里程碑沉淀失败 task=%s: %s",
                               task_id, e)
        store.TasksStore.update(task_id, {"status": ST.TASK_WAITING_INPUT})
        _publish_task(conv_id, store.TasksStore.get(task_id) or {})
        task_status_card(conv_id, task_id, "waiting", agent=agent, pid=pid)
    elif kind == "done":
        # cv-285 用户先行终态守卫: 执行详情窗 stop→cancelled 与泵 done 事件
        # 并发竞态——cancelled/ignored(用户语义终态)不被事件覆写; done/failed
        # 行先行落态时事件仍处理(计划回填钩子依赖, 既有测试语义)。
        if (store.TasksStore.get(task_id) or {}).get("status") in (
                "cancelled", "ignored"):
            return
        clean = text.replace("[[IMPLEMENT_DONE]]", "").strip()
        clean = re.sub(r'\{"result"\s*:\s*"outcome recorded[^}]*\}', "", clean).strip()
        # cv-203 P2: 摘要质量降级——计划重印/空摘要(与上轮待输入正文同文或
        # 混入 [[NEED_INPUT]])不作为完成正文展示, 以变更文件与验收为准
        if (str(ev.get("summaryQuality") or "") == "suspect"
                or "[[NEED_INPUT]]" in clean):
            clean = ("⚠️ 执行器未附规范完成摘要(完成消息混入计划/待输入正文)——"
                     "以变更文件与验收简报为准。")
        changed = ev.get("changedFiles") or []
        brief = _acceptance_brief(conv_id, ctx["rid"], changed)
        # 复制实现检测(验证有效性): 测试对象须是真实生产代码
        _trow = store.TasksStore.get(task_id) or {}
        _wt = _trow.get("worktree") or ""
        copy_note = _copy_impl_flag(_wt, changed, clean)
        if copy_note:
            brief += copy_note
        files = ("\n".join(f"- `{f}`" for f in changed[:20])
                 if changed else "- (无变更文件)")
        # 重定位 P3: 越界缺口显式提示(可据此起草迭代规约——需用户确认, 不自动创建)
        gap_note = ("\n\n> ⚠️ 检出越界改动——缺口已随验收材料归档，"
                    "可据此起草迭代规约(回复确认后创建)。") if "越界改动" in brief else ""
        # cv-203 P3: 形态标签按任务 workspace 分叉(就地任务无分支, 分支名是
        # 建卡提案字段——展示它会误导)
        _loc = (f"分支 `{_trow.get('branch') or ''}`(隔离)"
                if (_trow.get("workspace") or "") == "worktree" else "融合模式")
        _append(conv_id, "assistant",
                f"✅ **任务完成**「{title}」· {_loc}\n\n{clean}\n\n"
                f"**变更文件**：\n{files}\n\n---\n**验收简报**\n{brief}{gap_note}",
                msg_meta={"kind": "task_done", "taskId": task_id,
                          "branch": _trow.get("branch") or "",
                          "workspace": _trow.get("workspace") or "inplace"},
                project_id=pid, agent=agent)
        store.TasksStore.finish(task_id, "done", clean[:2000])
        _task_reaggregate_work_state(conv_id)
        _publish_task(conv_id, store.TasksStore.get(task_id) or {})
        task_status_card(conv_id, task_id, "done", agent=agent, pid=pid,
                         note=f"变更 {len(changed)} 文件")
        # 任务计划(环节十四): 步骤完成 → 回填 + 预填下一步 / 汇总
        try:
            from ...agent.planning.task_plan import on_plan_task_done
            on_plan_task_done(conv_id, task_id)
        except Exception:  # noqa: BLE001
            pass
        # 知识沉淀: 任务回执 → execution_report 单元(会话派生记忆; 含验收材料)
        try:
            _sediment_task_receipt(conv_id, task_id, ctx.get("rid") or "", "done",
                                   title, clean or text, changed,
                                   _trow.get("branch") or "", pid,
                                   acceptance_brief=brief)
        except Exception as e:  # noqa: BLE001
            logger.warning("[exec-bridge] 回执沉淀失败 task=%s: %s", task_id, e)
    elif kind == "failed":
        # cv-285 用户先行终态守卫(与 done 分支同规)。
        if (store.TasksStore.get(task_id) or {}).get("status") in (
                "cancelled", "ignored"):
            return
        _append(conv_id, "assistant",
                f"❌ **任务失败**「{title}」：{text}\n可重新发起。",
                msg_meta={"kind": "task_failed", "taskId": task_id},
                project_id=pid, agent=agent)
        store.TasksStore.finish(task_id, "failed", text[:2000])
        _task_reaggregate_work_state(conv_id)
        _publish_task(conv_id, store.TasksStore.get(task_id) or {})
        task_status_card(conv_id, task_id, "failed", agent=agent, pid=pid,
                         note=text[:160])
        # 任务计划(环节十四): 步骤标 failed(下次 /执行 自动重发)
        try:
            from ...agent.planning.task_plan import on_plan_task_failed
            on_plan_task_failed(task_id)
        except Exception:  # noqa: BLE001
            pass
        # 知识沉淀: 失败回执同样入单元(P1 distill 材料/教训)
        try:
            _sediment_task_receipt(conv_id, task_id, ctx.get("rid") or "", "failed",
                                   title, text, ev.get("changedFiles") or "",
                                   (store.TasksStore.get(task_id) or {}).get("branch") or "",
                                   pid)
        except Exception as e:  # noqa: BLE001
            logger.warning("[exec-bridge] 失败回执沉淀失败 task=%s: %s", task_id, e)
    elif kind in ("progress", "text", "tool", "usage"):
        # cv-268: 过程落地单源(process_stream.apply_event), 行为与原四分支等价
        # (text 节流 0.5/tool·progress 不节流/usage 仅落库; tool 挂状态卡刷新
        # ——cv-205: cline 只发 tool 不发 progress, 刷新必须挂 tool 活动)
        from . import process_stream as _ps
        prev = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        prog = _ps.apply_event(prev, ev)
        if prog is not None:
            th = _ps.sse_throttle(kind)
            store.TasksStore.set_progress(task_id, prog)
            _publish_progress(conv_id, task_id, prog, throttle=th)
            if kind in ("progress", "tool"):
                _status_card_refresh(conv_id, task_id, agent, pid)
    elif kind == "approval_request":
        # 越界审批桥: 落可操作消息(meta 携 jobId/requestId), 前端渲染批准/拒绝
        tool_name = str(ev.get("toolName") or "工具")
        req_id = str(ev.get("requestId") or "")
        _append(conv_id, "assistant",
                f"🔐 **{agent} 请求确认**（任务「{title}」）\n\n"
                f"工具 `{tool_name}` 请求执行，等待你的批准。\n\n"
                f"批准：回复 /approve {req_id}；拒绝：回复 /deny {req_id}。",
                msg_meta={"kind": "task_approval", "taskId": task_id,
                          "approvalJobId": job_id, "approvalRequestId": req_id},
                project_id=pid, agent=agent)
        # 需求跟踪台账: 决策请求挂账(waiting/等用户), 失败不阻断执行流
        try:
            from ...store.tracking import emit as _tr_emit
            from ...store.states import TRACK_WAITING
            _tr_emit(category="决策",
                     title=f"越界审批：{tool_name}（任务「{title}」）",
                     content=f"任务 {task_id} 的执行器请求使用工具 `{tool_name}`，等待用户批准。",
                     action_type="决策", creator_role="coding",
                     assignee_role="user", state=TRACK_WAITING, waiting_for="user",
                     ref_type="approval", ref_id=req_id,
                     conversation_id=conv_id, project_id=pid)
        except Exception:  # noqa: BLE001
            pass
    elif kind == "verify":
        # V5 反馈落流: 验证矩阵 → 进度留痕; FAIL 落简短消息(通过不落流防刷屏;
        # 修复回注/退回的完整叙事由 notice/input_required 事件承载)
        overall = str(ev.get("overall") or "?")
        prog = {**((store.TasksStore.get(task_id) or {}).get("progress") or {}),
                "verifyOverall": overall,
                "verifyAt": _ts()}
        for stage in ("build", "test"):
            r = ev.get(stage)
            if r:
                prog[f"verify_{stage}"] = {"verdict": r.get("verdict"),
                                           "reason": r.get("reason") or ""}
        store.TasksStore.set_progress(task_id, prog)
        _publish_progress(conv_id, task_id, {"verifyOverall": overall})
        if overall in ("C", "D") or any(
                (ev.get(s) or {}).get("verdict") == "FAIL"
                for s in ("build", "test")):
            _append(conv_id, "assistant",
                    f"🧪 **程序化验收**（任务「{title}」）\n\n{(ev.get('text') or '')[:400]}",
                    msg_meta={"kind": "task_verify", "taskId": task_id},
                    project_id=pid, agent=agent)
    elif kind == "team":
        # P5: 团队进度 → 进度预览（不落消息，防刷屏）
        prev = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        prog = {**prev, "lastTeam": text[:120], "at": _ts()}
        store.TasksStore.set_progress(task_id, prog)
        _publish_progress(conv_id, task_id, {"lastTeam": text[:120]})
    elif kind == "mcp":
        # P5: MCP 注入结果 → 进度（失败轻提示落进度，不阻断）
        prev = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        prog = {**prev, "lastMcp": f"{ev.get('server')}:{'ok' if ev.get('ok') else 'failed'}",
                "at": _ts()}
        store.TasksStore.set_progress(task_id, prog)
    elif kind in ("notice", "turn_outcome"):
        # notice: 进展噪声(mistake_limit 由 failed 收口); turn_outcome: 标记已承载
        return
    elif kind in ("aborted", "finished"):
        _append(conv_id, "assistant", f"ℹ️ {text}", project_id=pid, agent=agent)
    elif text:
        # cv-203: 过程类文本不再逐条落消息(与状态/进度混流即刷屏)——
        # 并入专用状态卡附注(节流原位更新)
        prev0 = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        store.TasksStore.set_progress(task_id, {**prev0, "lastNote": text[:200]})
        _status_card_refresh(conv_id, task_id, agent, pid, min_interval=20.0)


def _land_stream_items(ev: dict, conv_id: str, task_id: str, job_id: str,
                       pid: str) -> None:
    """A6.2: 执行器事件 → item 投影(仅非落消息类型)——持久化 + SSE 单通道。

    投影语义单源 agent/execution/items.py; 落消息类卡片不入流表(读侧投影)。
    """
    try:
        from ...agent.execution.items import project_event, STREAM_PERSIST_TYPES
        items = [i for i in project_event(ev)
                 if i.get("type") in STREAM_PERSIST_TYPES]
        if not items:
            return
        for it_ in items:
            try:
                store.StreamItemsStore.create({
                    "id": it_["id"], "conversationId": conv_id,
                    "projectId": pid, "taskId": task_id, "jobId": job_id,
                    "type": it_["type"], "status": it_.get("status") or "",
                    "text": it_.get("text") or "",
                    "payload": it_.get("payload") or {},
                    "seq": it_.get("seq")})
            except Exception:  # noqa: BLE001 — 重复 id(泵重放)幂等跳过
                pass
        from ...agent.collab.sse import emit
        emit("items", conv_id, taskId=task_id, items=items)
    except Exception as e:  # noqa: BLE001 — 投影故障不阻断既有事件处理
        logger.warning("[exec-bridge] stream item 投影失败 task=%s: %s",
                       task_id, e)


async def _task_pump(conv_id: str, task_id: str, job_id: str, rid: str,
                     agent: str) -> None:
    """任务泵: 骨架委托 agent.execution.pumps(唯一实现), 事件走 task 路径。"""
    from ...agent.execution import pumps as _pumps
    logger.info("[exec-bridge] task-pump start conv=%s task=%s job=%s",
                conv_id, task_id, job_id)

    def on_event(ev: dict) -> None:
        _land_stream_items(ev, conv_id, task_id, job_id,
                           (store.ConversationsStore.get(conv_id) or {}).get("projectId") or "")
        _handle_task_event(ev, _task_ctx(conv_id, task_id, job_id, rid, agent))

    def on_snapshot(snap: dict) -> None:
        sid = (snap.get("sessionId") or "").strip()
        if sid:
            t = store.TasksStore.get(task_id) or {}
            if (t.get("sessionRef") or "") != sid:
                try:
                    store.TasksStore.update(task_id, {"session_ref": sid})
                except Exception:  # noqa: BLE001
                    pass

    def on_lost(reason: str) -> None:
        store.TasksStore.finish(task_id, "failed", reason)
        title = (store.TasksStore.get(task_id) or {}).get("title", "")
        _append(conv_id, "assistant",
                f"⚠️ 任务「{title}」与 runner 失去联系({reason}), 已记为失败。",
                msg_meta={"kind": "task_failed", "taskId": task_id},
                agent=agent)
        _publish_task(conv_id, store.TasksStore.get(task_id) or {})

    def on_finished(status: str) -> None:
        # runner 侧终态兜底(事件流已落终态时为 no-op; stopped→cancelled 语义)
        t = store.TasksStore.get(task_id) or {}
        if (t.get("status") or "") not in _TASK_TERMINAL:
            store.TasksStore.finish(
                task_id, "cancelled" if status == "stopped" else status)
            _publish_task(conv_id, store.TasksStore.get(task_id) or {})

    try:
        await _pumps.run_event_pump(
            base=RUNNER_BASE, job_id=job_id, runner=_runner,
            on_event=on_event, on_snapshot=on_snapshot,
            on_lost=on_lost, on_finished=on_finished)
    except Exception as e:  # noqa: BLE001 — 泵核重抛(cv-264): 记因后吞,
        # 防 create_task unretrieved 噪音; 句柄清理由 finally 统一收口
        logger.warning("[task-pump] conv=%s job=%s 崩溃退出: %s",
                       conv_id, job_id, e)
    finally:
        # G5 修复: 泵退出(done/failed/lost/cancel)即清理句柄, 防长会话累积
        # (此前仅 task_stop 弹出; finally 统一收口, 取消路径同样覆盖)
        jobs = _TASK_PUMPS.get(conv_id)
        if jobs is not None:
            jobs.pop(job_id, None)
            if not jobs:
                _TASK_PUMPS.pop(conv_id, None)


def _task_gear(task: dict, conv: Optional[dict] = None):
    """任务挡位解析(环节十二a, 三维矩阵): 会话 analysisMode + 执行器配置(C 轴)
    + architect 对话模型(A 轴) → GearPolicy。"""
    from ...agent.governance.gears import resolve_gear
    from ..tools.req_agent import get_model_preference
    _conv = conv or store.ConversationsStore.get(task.get("conversationId") or "") or {}
    try:
        hint = executor_hint_by_id(str(task.get("executorId") or ""), _conv) or {}
    except Exception:  # noqa: BLE001 — 注册表不可读时按无配置解析
        hint = {}
    return resolve_gear(str(_conv.get("analysisMode") or ""),
                        hint.get("executorConfig") or {},
                        architect_model_id=get_model_preference())


def _task_instruction(task: dict, prior_brief: str = "", policy=None,
                      runtime: Optional[dict] = None,
                      probe_score: Optional[float] = None) -> str:
    """任务指令组装(P4 委托 planning.task_plan; 挡位策略按挡分叉, 环节十二a;
    runtime=运行时身份事实 A3; probe_score=R2.5 同挡密度微调)。"""
    from ...agent.planning.task_plan import assemble_task_instruction
    return assemble_task_instruction(task, prior_brief, policy=policy, runtime=runtime,
                                     probe_score=probe_score)


def _meta_get(conv: dict) -> dict:
    import json as _json
    meta = (conv or {}).get("meta")
    if isinstance(meta, dict):
        return meta          # row_to_api 已解析
    try:
        return _json.loads(meta or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _meta_set(conv_id: str, meta: dict) -> None:
    import json as _json
    store.ConversationsStore.update(conv_id, {"meta": _json.dumps(meta, ensure_ascii=False)})


def _spec_updated_at(rid: str) -> int:
    return int((store.RequirementsStore.get(rid) or {}).get("updatedAt") or 0)



def _task_chain_brief(conv_id: str, current_task_id: str) -> str:
    """前情链: 同会话最近 ≤3 条终态任务的结果摘要(自动注入新任务指令)。

    任务链上下文延续——执行器不重走已完成的探索/改动; 纯确定性组装,
    不调 LLM、不弹 UI、不依赖 architect 自觉。"""
    rows = [t for t in store.TasksStore.of_conv(conv_id)
            if t.get("id") != current_task_id
            and (t.get("status") or "") in ("done", "failed", "cancelled")]
    if not rows:
        return ""
    lines = []
    for t in rows[::-1][:3]:               # 最近在前
        status = t.get("status") or ""
        result = str(t.get("resultMd") or t.get("result_md")
                     or "").strip().replace("\n", " ")
        if len(result) > 240:
            result = result[:240].rstrip() + "…"
        if not result:
            continue
        icon = "✅" if status == "done" else "⚠️"
        lines.append(f"- {icon}「{(t.get('title') or '')[:40]}」({status}): {result}")
    if not lines:
        return ""
    return "\n".join(lines)[:1000]




def executor_hint_by_id(executor_id: str, conv: Optional[dict] = None) -> Optional[dict]:
    """执行器 id → 注册表配置提示(model/端口/超时等)——v2 任务模型用。

    原 websocket._executor_hint 泛化: 按 task.executorId 直查注册表;
    无绑定 → None(缺省 opencode)。
    """
    eid = (executor_id or "").strip()
    if not eid:
        return None
    conv_model = ((conv or {}).get("executorModel") or "").strip()
    try:
        from ...arch_routes.agent_executors import (load_executors, _default_sidecar_path,
                                      _builtin_cline_models)
        for e in load_executors():
            if (e.get("id") or "") == eid:
                cfg = e.get("config") or {}
                # 内置 cline: 模型面=实例模型实时投影(覆盖任何落盘快照;
                # 端点/密钥随实例条目流转, 执行器只持默认模型 model_id)
                if e.get("type") == "cline-sdk" and eid == "cline":
                    live = _builtin_cline_models()
                    if live:
                        cfg = {**cfg, "models": live}
                model_names = [str(m.get("model") or m.get("name") or "")
                               for m in (cfg.get("models") or [])
                               if (m.get("model") or m.get("name"))]
                # 模型选择链对齐(turn_adapter._resolve_model 同序):
                # 会话绑定 > 注册表顶层默认(UI「默认模型」: cline=model_id,
                # opencode/codex=model) > models[0]。
                # 教训(cv-163/166): 各层各自兜底 → 实际执行模型与 UI 展示不一致;
                # 顶层默认必须在白名单首条之前——展示名跨 provider 可重复,
                # models[0] 旁路用户显式选型是同一教训的变体。
                model = (conv_model
                         or (cfg.get("model_id") or "")
                         or (cfg.get("model") or "")
                         or (model_names[0] if model_names else ""))
                # cline 引擎解析链(单点收口): 显式 sidecar_script > 引擎默认版本
                # (>仓库内置 dist)。引擎命中时随发 cline_data_dir——runner 按
                # 版本注入 TOPOCODE_CLINE_DATA_DIR, 会话/设置按版本隔离。
                sidecar_script = str(cfg.get("sidecar_script") or "").strip()
                cline_data_dir = ""
                if not sidecar_script and e.get("type") == "cline-sdk":
                    try:
                        from ...arch_routes.cline_engines import resolve_engine
                        eng = resolve_engine()
                        if eng:
                            sidecar_script = eng["script"]
                            cline_data_dir = eng["dataDir"]
                    except Exception:  # noqa: BLE001
                        pass
                return {"executorId": eid,
                        "executorType": e.get("type") or "",
                        "executorConfig": {
                            "model": cfg.get("model") or "",
                            "agent": cfg.get("agent") or "",
                            "base_port": cfg.get("base_port"),
                            "auto_start": cfg.get("auto_start"),
                            "base_url": cfg.get("base_url") or cfg.get("serve_url") or "",
                            "opencode_bin": cfg.get("opencode_bin") or "",
                            "node_bin": cfg.get("node_bin") or "",
                            "sidecar_script": sidecar_script
                                or _default_sidecar_path(),
                            **({"cline_data_dir": cline_data_dir}
                               if cline_data_dir else {}),
                            "provider_id": cfg.get("provider_id") or "",
                            "model_id": cfg.get("model_id") or "",
                            "api_key": cfg.get("api_key") or "",
                            "max_iterations": cfg.get("max_iterations"),
                            "capability": cfg.get("capability") or "",
                            "tierProbed": cfg.get("tierProbed") or "",
                            "arch_url": cfg.get("arch_url") or "",
                            "codex_bin": cfg.get("codex_bin") or "",
                            "codex_home": cfg.get("codex_home") or "",
                            "approval_policy": cfg.get("approval_policy") or "",
                            "sandbox_mode": cfg.get("sandbox_mode") or "",
                            "turnTimeout": cfg.get("turnTimeout"),
                            "stallSec": cfg.get("stallSec"),
                            # cv-158 修复: models/permission/mcp_servers 曾被丢弃——
                            # cline 按作业换模(_resolve_model)与 opencode MCP 全依赖它们
                            "models": cfg.get("models") or [],
                            "permission": cfg.get("permission") or "",
                            "rulesMd": cfg.get("rulesMd") or "",
                            "mcp_servers": cfg.get("mcp_servers") or {},
                            # cv-267: 会话 system prompt 全文覆盖(高级逃生口,
                            # cline adapter 既有读取; 缺省=按 sessionRole 分型)
                            "system_prompt": cfg.get("system_prompt") or "",
                        },
                        "model": model,
                        "basePort": cfg.get("base_port"),
                        "autoStart": cfg.get("auto_start"),
                        "baseUrl": cfg.get("base_url") or cfg.get("serve_url") or ""}
    except Exception:  # noqa: BLE001
        pass
    return None
