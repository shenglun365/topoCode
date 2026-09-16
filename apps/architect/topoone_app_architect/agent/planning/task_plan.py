"""任务规划(规划层) — P4 机械迁入。

extract_task_fence(任务载荷围栏, 自 req_agent) + propose_task_tool(轻门禁入口,
自 req_agent.tool_task_propose) + assemble_task_instruction(指令组装,
自 exec_bridge._task_instruction)。执行拉起留执行层(exec_bridge.confirm_task)。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("arch.planning.task_plan")


def _store():
    from ...arch_routes import store
    return store


def extract_task_fence(text: str) -> Optional[Dict[str, Any]]:
    """提取任务载荷: ```task 围栏(显式协议) 或 ```json 围栏中的任务形态对象。

    cv-150 实证: 模型(9b 级)宣称要调 task.propose 却直接把载荷写成 ```json
    围栏 → 工具不执行/守卫拦截/流程死路。围栏协议化: 服务端解析代为落卡。
    防误判: 图 IR(version+type+nodes/edges)与规约提案(title+方案字段但带
    acceptanceMd 优先走提案域)不认领; 只认 title + 实质任务字段。
    """
    if not text or "```" not in text:
        return None
    explicit: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    m = re.search(r"```task\s*\n?(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(1))
            if isinstance(d, dict):
                explicit.append(d)
        except Exception:  # noqa: BLE001
            pass
    for fm in re.finditer(r"```(?:json)?\s*\n?(\{.*?\})\s*```", text, re.DOTALL):
        try:
            d = json.loads(fm.group(1))
            if isinstance(d, dict):
                candidates.append(d)
        except Exception:  # noqa: BLE001
            continue

    def _norm(d: Dict[str, Any], explicit: bool = False) -> Optional[Dict[str, str]]:
        # 图 IR 排除(diagram.build 产物形态)
        t = str(d.get("type") or "").lower()
        if d.get("nodes") and d.get("type") and t in ("component", "flow", "graph", "diagram"):
            return None
        if d.get("version") and d.get("nodes"):
            return None
        title = str(d.get("title") or d.get("name") or "").strip()
        if not title:
            return None
        instr = str(d.get("instruction") or d.get("instructionMd") or "").strip()
        _min_len = 0 if explicit else 10   # 显式 task 围栏=明确意图, 不卡长度
        if not instr:
            req_md = str(d.get("requirementMd") or d.get("requirement") or "").strip()
            design = str(d.get("designMd") or d.get("implementationPath") or "").strip()
            parts = []
            if req_md:
                parts.append("## 需求目标\n" + req_md)
            if design:
                parts.append("## 实现方案\n" + design)
            acc = d.get("acceptance") or d.get("acceptanceMd")
            if acc:
                acc_lines = acc if isinstance(acc, str) else "\n".join(str(x) for x in acc)
                parts.append("## 验收标准\n" + str(acc_lines))
            instr = "\n\n".join(parts)
        if len(instr) < _min_len:
            return None
        return {"title": title[:120], "instruction": instr[:8000]}

    for d in explicit:
        out = _norm(d, explicit=True)
        if out:
            return out
    for d in candidates:
        out = _norm(d)
        if out:
            return out
    return None


def propose_task_tool(title: str, instruction: str,
                      executorType: Optional[str] = None,
                      root: Optional[str] = None,
                      project: Optional[str] = None) -> Dict[str, Any]:
    """task.propose 工具本体(轻门禁: 用户确认后执行)。"""
    from ...arch_routes import ctx as _ctx
    from ...arch_routes import exec_bridge
    store = _store()
    conv_id = _ctx.get_conv() or ""
    if not conv_id:
        return {"error": "no-conversation"}
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return {"error": "conversation-not-found"}
    if (conv.get("status") or "active") == "archived":
        return {"error": "会话已归档(只读)"}
    # 执行器选定单源: 模型显式指定(别名归一) > 会话绑定 > 注册表默认;
    # 不再字面回落 opencode(cv-153: 注册表 default=cline 被无视/类型名不一致静默降级)
    from ...arch_routes.agent_executors import normalize_executor_type, default_executor
    etype = normalize_executor_type(executorType or "")
    if not etype:
        _bound = exec_bridge.executor_hint_by_id(str(conv.get("executorId") or ""), conv)
        etype = normalize_executor_type((_bound or {}).get("executorType") or "")
    if not etype:
        etype = normalize_executor_type((default_executor() or {}).get("type") or "")
    if not etype:
        return {"error": "无可用执行器：注册表无启用项且未指定执行器——"
                         "请在「执行器配置」启用执行器, 或在消息中显式指定(如 @cline)。"}
    if not (instruction or "").strip():
        return {"error": "instruction 缺少实质内容(为空)——请写实质任务内容(目标/方案/验收)"}
    task = exec_bridge.propose_task(conv, title, instruction,
                                    executor_hint={"executorType": etype,
                                                   "executorId": conv.get("executorId") or ""})
    if not task.get("id"):
        return {"error": str(task.get("error") or "任务卡创建失败")}
    return {"ok": True, "taskId": task["id"], "status": task.get("status"),
            "hint": "任务卡已生成, 等待用户确认后执行; 请告知用户可确认/取消/调整。"}


def assemble_task_instruction(task: dict, prior_brief: str = "",
                              policy: Optional[Any] = None,
                              runtime: Optional[dict] = None) -> str:
    """任务指令组装: task.instruction(architect 整理) 为正文 + 绑定需求规约
    补充(边界/验收) + 工作环境/DoD 系统段(确定性注入, 不依赖 LLM)。

    policy: 挡位策略(gears.GearPolicy, 环节十二a)——确认节奏/粒度按挡分叉;
    None → 默认档(T1)。
    prior_brief: 前情链简报(同会话近期终态任务摘要, confirm 时自动注入)。
    runtime: 运行时身份事实(A3/postmortem 防误验)——{"branch","root"};
    已知即注入「运行时身份」段, 杜绝 agent 把主目录服务探测当完成依据。
    """
    if policy is None:
        from ..governance.gears import default_policy
        policy = default_policy()
    if getattr(policy, "cap_note", ""):
        # M1: 实测边界封顶随指令告知 subagent(编排已按能力边界降档)
        parts_style_note = ("> 🛡️ " + str(policy.cap_note)
                            + "——本次任务编排已按你的实测能力边界降档, "
                              "请严格按微步/步骤粒度推进, 里程碑报告照常。\n")
    else:
        parts_style_note = ""
    rid = task.get("reqId") or ""
    r = _store().RequirementsStore.get(rid) or {} if rid else {}
    active = _store().RequirementsStore.spec_active(rid) or {} if rid else {}
    a = (active.get("snapshot") or {}) if rid else {}
    if not a and rid:
        a = r.get("analysis") or {}
    parts = [f"# 实施任务：{task.get('title') or '任务'}"
             + (f"（{rid} · 规约 v{active.get('ver') or '?'}）" if rid else "")]
    if parts_style_note:
        parts.append(parts_style_note)
    body = str(task.get("instruction") or "").strip()
    if prior_brief:
        parts.append("## 前情简报(同会话近期任务)\n" + prior_brief
                     + "\n请避免重复前情中已完成的改动, 基于前情继续。")
    # 方案兜底: designMd 未细化时用需求正文(requirementMd/desc)——agent 永远拿到实质任务,
    # 不允许"只有标题+DoD"的空指令把作业打成 NEED_INPUT 空转(cv-140 教训)。
    if body:
        parts.append("## 任务上下文（architect 整理, 遵循执行）\n" + body)
    desc_text = str(a.get("desc") or r.get("desc") or "").strip()
    if body and not (a.get("designMd") or a.get("implementationPath")):
        pass   # 正文已给——不做空方案警告
    elif not (a.get("designMd") or a.get("implementationPath")):
        if desc_text:
            parts.append(
                "> ⚠️ 本规约未细化实现方案(仅需求正文)。请基于以下需求描述自行设计并实施,"
                "不确定处一次性集中提问, 不要每步暂停。\n\n## 需求描述\n" + desc_text)
        else:
            parts.append("> ⚠️ 本规约既无实现方案也无需求正文——若你无法从任务上下文推断目标, "
                         "请立即 [[NEED_INPUT]] 报告\"规约为空\", 不要猜测实施。")
    if a.get("functionalScope"):
        parts.append("## 需求目标\n" + "\n".join(f"- {x}" for x in a["functionalScope"]))
    parts.append(
        "## 工作环境(重要, 先读)\n"
        "- 你在项目源码仓库的**隔离 worktree 分支**执行, pwd 即源码树根——"
        "先浏览仓库(README/构建文件/目录结构)理解项目, 再动手。\n"
        "- 交付物一律**写入源码树**(新文件/修改/文档, git 分支内); "
        "**不要写系统路径**(/etc /usr /opt 等运行时部署位置)——环境搭建与部署"
        "由用户手工执行, 你提供文件与部署说明即可。\n"
        "- 环境类问题(sudo/依赖/编译工具)先自主查证仓库与 README; "
        "只对**需求歧义**集中一次性提问, 不要为环境搭建反复提问。")
    runtime = runtime or {}
    _branch = str(runtime.get("branch") or "").strip()
    _root = str(runtime.get("root") or "").strip()
    if _branch or _root:
        ident = ["## 运行时身份(防误验, 先确认)"]
        if _branch:
            ident.append(f"- 任务分支: `{_branch}`——你的 cwd 即该分支的隔离 worktree 根, "
                         "与用户主目录相互独立。")
        if _root:
            ident.append(f"- 主仓位置: `{_root}`(用户主检出)——你**不在**主目录工作; "
                         "主目录当前运行的服务/端口与你完全无关。")
        ident.append("- 验收事实约定: 构建/测试/检查一律在你 worktree 内执行; "
                     "**禁止**把「主目录服务的 HTTP 探测 200」当作完成依据——"
                     "那不是你的产出。")
        parts.append("\n".join(ident))
    if a.get("designMd") or a.get("implementationPath"):
        parts.append("## 实现方案(遵循执行)\n"
                     + str(a.get("designMd") or a.get("implementationPath")))
    if a.get("allowedScope"):
        scope_lines = [str(x) for x in a["allowedScope"]]
        abs_paths = [s for s in scope_lines if s.strip().startswith("/")]
        if abs_paths:
            parts.append(
                "## 允许增删改\n" + "\n".join(f"- {x}" for x in scope_lines)
                + "\n> 注: 其中以 `/` 开头的是**运行时部署路径**(用户环境的目标位置)"
                "——请在源码树中创建对应文件(或等价物)并附部署说明, "
                "不要尝试直接写这些系统路径。")
        else:
            parts.append("## 允许增删改\n" + "\n".join(f"- {x}" for x in scope_lines))
    if a.get("forbiddenScope"):
        parts.append("## 一定不能动\n" + "\n".join(f"- {x}" for x in a["forbiddenScope"]))
    if a.get("acceptance"):
        parts.append("## 验收标准\n" + "\n".join(f"- {x}" for x in a["acceptance"]))
    parts.append(
        "## 交付定义(DoD)\n"
        "1. 按方案完成代码实现；\n"
        "2. 完成整体编译/构建验证 + 运行冒烟（产物实际运行核对输入/输出成败）；\n"
        "3. 单元测试是自主选用的验证手段（鼓励按\"可独立验证\"的粒度拆分工作），"
        "不是强制交付项——禁止为迁就测试而改动源码结构"
        "（头文件解耦/前向声明链/重构 include 等一律不做）；\n"
        "4. **测试/脚手架的被测逻辑必须来自真实生产源码**（include/链接生产头文件"
        "或源文件）——禁止在测试内复制/镜像生产实现来\"自证\"（测副本≠验证代码）；"
        "确实无法链接时（内部函数未导出等），必须在摘要中显式声明\"复制实现\"及原因；\n"
        "5. 全部完成后输出 [[IMPLEMENT_DONE]] 与摘要(变更文件/验证结果/编译结果/遗留项)；"
        "任一环节需要用户操作、确认、澄清或补充信息时，输出 [[NEED_INPUT]] 与具体问题后结束回合等待。")
    # 里程碑协议(环节十一) + 挡位粒度/节奏分叉(环节十二a, 数据驱动)
    parts.append(
        "## 里程碑协议（重要，防止无限消耗）\n"
        "- 预计超过约 15 次工具调用的复杂任务：先探索代码库，在首次回复中提交"
        "**里程碑计划**（按功能模块+可独立验证标准划分；每个里程碑给出：目标、"
        "涉及文件、验证方式），然后输出 [[NEED_INPUT]] 等待用户确认后再动手；\n"
        "- 每个里程碑完成后：输出里程碑报告（固定三行格式：\n"
        "  `改动文件: 文件a, 文件b, 文件c`\n"
        "  `验证: 构建与冒烟结果`\n"
        "  `下一里程碑: 名称 或 \"全部完成\"`），"
        "然后输出 [[NEED_INPUT]] 等待用户指示；**禁止未提交报告就连续跨里程碑推进**；\n"
        "- 预计 15 次工具调用以内的简单任务：直接执行，完成后输出 [[IMPLEMENT_DONE]]。")
    agent_note = str(getattr(policy, "agent_note", "") or "").strip()
    if agent_note:
        parts.append("## 执行方式（按任务挡位）\n" + agent_note)
    return "\n\n".join(parts)



# ══════════════════════════════════════════════════════════════════════
# 任务计划(环节十四): 需求 → 有序步骤 → 顺序下发 + 汇总验收
# 存储需求行 taskPlan(JSON): [{seq,title,instruction,taskId,status}]
#   status: pending(待下发) | proposed(卡已建) | done | failed
# 触发: /执行 在 T2+ 挡位(pre_split≠none)生成计划(单步则走原单卡路径);
#       任务 done 事件驱动下一步预填; 全部 done → 汇总回执。
# ══════════════════════════════════════════════════════════════════════

def get_plan(rid: str) -> list:
    rows = _store().RequirementsStore.get(rid or "") or {}
    plan = rows.get("taskPlan")
    if isinstance(plan, str) and plan.strip():
        try:
            plan = json.loads(plan)
        except Exception:  # noqa: BLE001
            plan = None
    return plan if isinstance(plan, list) else []


def save_plan(rid: str, plan: list) -> None:
    _store().RequirementsStore.update(rid, {"taskPlan": plan})


def split_tasks_llm(req_text: str) -> Optional[list]:
    """LLM 拆步: ≥2 步返回步骤列表; 单步/失败/不可用 → None(回落单卡)。"""
    if not (req_text or "").strip():
        return None
    schema = {
        "type": "object",
        "properties": {
            "tasks": {"type": "array", "items": {
                "type": "object",
                "properties": {"title": {"type": "string"},
                               "instruction": {"type": "string"}},
                "required": ["title", "instruction"]}},
        },
        "required": ["tasks"],
    }
    from ...arch_routes import req_agent as _ra
    try:
        res = _ra.llm_sync(
            [{"role": "system",
              "content": "你是任务计划器。把需求拆成**有序的实施步骤**(每步单一模块级"
                         "目标、可独立构建验证)。规则: 2-5 步; 若需求足够单一一步可完成,"
                         "返回单步; 步骤 instruction 写实质内容(目标/涉及文件/验证方式)。"
                         "只输出结构化结果。"},
             {"role": "user", "content": f"需求文本:\n{req_text[:6000]}"}],
            mode="structured", output_schema=schema, max_tokens=2048)
    except Exception as e:  # noqa: BLE001
        logger.info("[task-plan] llm 不可用: %s", e)
        return None
    payload = (res or {}).get("output")
    tasks = (payload or {}).get("tasks")
    if not isinstance(tasks, list):
        return None
    out = []
    for t in tasks[:5]:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title") or "").strip()
        instr = str(t.get("instruction") or "").strip()
        if title and instr:
            out.append({"title": title[:120], "instruction": instr[:4000]})
    return out if len(out) >= 2 else None


def _step_instruction(plan: list, idx: int) -> str:
    step = plan[idx]
    return (f"{step.get('instruction')}\n\n"
            f"> 本任务属于任务计划: 步骤 {idx + 1}/{len(plan)}（{step.get('title')}）。"
            "只完成本步范围; 后续步骤由系统在完成后自动预填。")


def propose_plan_step(conv: dict, rid: str, idx: int,
                      executor_hint: Optional[dict] = None) -> dict:
    """下发计划第 idx 步(0 基): 建任务卡 + 回填步骤状态。"""
    plan = get_plan(rid)
    if idx >= len(plan):
        return {"ok": False, "error": "计划步骤越界"}
    from ...arch_routes import exec_bridge as eb
    req = _store().RequirementsStore.get(rid) or {}
    base_title = str(req.get("title") or "实施任务").strip()[:60]
    step = plan[idx]
    task = eb.propose_task(
        conv, f"{base_title} · 步骤{idx + 1}/{len(plan)} {step.get('title')}",
        _step_instruction(plan, idx), executor_hint=executor_hint)
    if task.get("id"):
        plan[idx]["taskId"] = task["id"]
        plan[idx]["status"] = "proposed"
        save_plan(rid, plan)
    return {"ok": bool(task.get("id")), "task": task,
            "error": str(task.get("error") or "")}


def maybe_plan_and_propose(conv: dict, rid: str, req_text: str, fallback_title: str,
                           fallback_instruction: str,
                           executor_hint: Optional[dict] = None) -> Optional[dict]:
    """/执行 计划入口: T2+ 挡位生成/续发计划; None = 走原单卡路径。

    - 挡位 pre_split=none(T0/T1) → None
    - 已有计划: 有待发/失败步骤 → 续发下一步; 全部完成 → 汇总提示(None 由调用方回落? 不, 直接返回提示)
    - 无计划: LLM 拆步 ≥2 → 建计划 + taskPlan 卡 + 下发第一步; 否则 None
    """
    from ...arch_routes.agent_executors import normalize_executor_type
    from ...arch_routes.exec_bridge import executor_hint_by_id
    from ..governance.gears import resolve_gear
    _hint = executor_hint
    if not _hint:
        _bound = executor_hint_by_id(str((conv or {}).get("executorId") or ""), conv)
        _hint = {"executorType": normalize_executor_type(
            (_bound or {}).get("executorType") or ""),
            "executorId": (_bound or {}).get("id") or ""}
    _cfg = {}
    if _hint.get("executorId"):
        _cfg = (executor_hint_by_id(str(_hint["executorId"]), conv)
                or {}).get("executorConfig") or {}
    policy = resolve_gear(str((conv or {}).get("analysisMode") or ""), _cfg)
    if policy.pre_split == "none":
        return None

    plan = get_plan(rid)
    if plan:
        pending = [i for i, s in enumerate(plan)
                   if s.get("status") in ("pending", "failed")]
        if not pending:
            return {"ok": False,
                    "receipt": "📋 任务计划已全部完成。如需继续演进, 请 `/调整` "
                               "完善需求后重新 `/执行`。"}
        idx = pending[0]
        out = propose_plan_step(conv, rid, idx, executor_hint=_hint)
        if out.get("ok"):
            retried = "重发" if plan[idx].get("status") == "failed" else "下发"
            out["receipt"] = f"📋 计划步骤 {idx + 1}/{len(plan)} 已{retried}，待确认执行。"
        return out or {"ok": False, "receipt": "计划步骤下发失败"}

    steps = split_tasks_llm(req_text)
    if not steps:
        return None
    plan = [{"seq": i + 1, "title": s["title"], "instruction": s["instruction"],
             "taskId": "", "status": "pending"} for i, s in enumerate(steps)]
    save_plan(rid, plan)
    _land_plan_card(conv, rid, plan)
    out = propose_plan_step(conv, rid, 0, executor_hint=_hint)
    if out.get("ok"):
        out["receipt"] = (f"📋 已生成任务计划({len(plan)} 步)并下发第一步，"
                          "待确认执行; 后续步骤完成后自动预填。")
    return out


def _land_plan_card(conv: dict, rid: str, plan: list) -> None:
    from ...arch_routes import exec_bridge as eb
    lines = "\n".join(
        f"{i + 1}. **{s.get('title')}** — {s.get('instruction', '')[:80]}"
        for i, s in enumerate(plan))
    eb._append(conv["id"], "assistant",
               f"📋 **任务计划**（{len(plan)} 步, 需求 {rid}）\n\n{lines}\n\n"
               "---\n顺序下发: 每步完成确认后自动预填下一步; 全部完成后出汇总。",
               msg_meta={"kind": "taskPlan", "requirementId": rid,
                         "total": len(plan)},
               project_id=(conv or {}).get("projectId") or "")


def on_plan_task_done(conv_id: str, task_id: str) -> None:
    """done 事件钩子: 回填步骤状态 → 预填下一步 / 汇总。"""
    try:
        from ...arch_routes import store as _s
        task = _s.TasksStore.get(task_id) or {}
        rid = task.get("reqId") or ""
        plan = get_plan(rid)
        if not plan:
            return
        for s in plan:
            if s.get("taskId") == task_id:
                s["status"] = "done"
                s["result"] = str(task.get("resultMd") or "")[:400]
        save_plan(rid, plan)
        pending = [i for i, s in enumerate(plan)
                   if s.get("status") in ("pending", "failed")]
        if pending:
            conv = _s.ConversationsStore.get(conv_id) or {}
            out = propose_plan_step(conv, rid, pending[0])
            if out.get("ok"):
                from ...arch_routes import exec_bridge as eb
                eb._append(conv_id, "assistant",
                           f"➡️ 计划步骤 {pending[0] + 1}/{len(plan)} 已预填"
                           "（含前情简报），待确认执行。",
                           msg_meta={"kind": "taskPlan", "requirementId": rid,
                                     "total": len(plan)},
                           project_id=(conv or {}).get("projectId") or "")
        else:
            _finish_plan_receipt(conv_id, rid, plan)
    except Exception as e:  # noqa: BLE001
        logger.warning("[task-plan] done hook: %s", e)


def on_plan_task_failed(task_id: str) -> None:
    """failed 事件钩子: 步骤标 failed(下次 /执行 自动重发该步)。"""
    try:
        from ...arch_routes import store as _s
        task = _s.TasksStore.get(task_id) or {}
        rid = task.get("reqId") or ""
        plan = get_plan(rid)
        for s in plan:
            if s.get("taskId") == task_id:
                s["status"] = "failed"
        if plan:
            save_plan(rid, plan)
    except Exception as e:  # noqa: BLE001
        logger.warning("[task-plan] failed hook: %s", e)


def _finish_plan_receipt(conv_id: str, rid: str, plan: list) -> None:
    from ...arch_routes import exec_bridge as eb
    from ...arch_routes import store as _s
    conv = _s.ConversationsStore.get(conv_id) or {}
    lines = "\n".join(
        f"- 步骤 {s.get('seq')}: **{s.get('title')}** — "
        f"{str(s.get('result') or '完成')[:120]}" for s in plan)
    branches = [str(t.get("branch") or "") for t in
                (_s.TasksStore.get(s.get("taskId")) or {} for s in plan)
                if t.get("branch")]
    merge_note = (f"\n\n🔀 各步骤分支: {', '.join(b for b in branches if b)}——"
                  "合并时请逐分支检视(主目录若有推进先 rebase)。") if branches else ""
    eb._append(conv_id, "assistant",
               f"✅ **任务计划全部完成**（{len(plan)} 步, 需求 {rid}）\n\n{lines}"
               + merge_note,
               msg_meta={"kind": "taskPlanDone", "requirementId": rid,
                         "total": len(plan)},
               project_id=(conv or {}).get("projectId") or "")
