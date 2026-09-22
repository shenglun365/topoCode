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
                      project: Optional[str] = None,
                      safetyClass: str = "",
                      workTags: Optional[List[str]] = None) -> Dict[str, Any]:
    """task.propose 工具本体(轻门禁: 用户确认后执行)。

    safetyClass: 安全等级三值轴(readonly|mutating|high-stakes; 缺省 mutating)
      —— readonly 豁免互斥+强制就地; high-stakes worktree 强制+合并门禁。
    workTags: 开放工作类型标签(分析/文档/部署…不设枚举; 仅影响提示)。"""
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
                                                   "executorId": conv.get("executorId") or ""},
                                    safety_class=safetyClass,
                                    work_tags=workTags)
    if not task.get("id"):
        return {"error": str(task.get("error") or "任务卡创建失败")}
    return {"ok": True, "taskId": task["id"], "status": task.get("status"),
            "safetyClass": task.get("safetyClass") or "mutating",
            "hint": "任务卡已保存; 用户点「开始执行」启动, 可对话调整或忽略——请告知用户。"}


def assemble_task_instruction(task: dict, prior_brief: str = "",
                              policy: Optional[Any] = None,
                              runtime: Optional[dict] = None,
                              probe_score: Optional[float] = None) -> str:
    """任务指令组装: task.instruction(architect 整理) 为正文 + 绑定需求规约
    补充(边界/验收) + 工作环境/DoD 系统段(确定性注入, 不依赖 LLM)。

    policy: 挡位策略(gears.GearPolicy, 环节十二a)——确认节奏/粒度按挡分叉;
    None → 默认档(T1)。
    prior_brief: 前情链简报(同会话近期终态任务摘要, confirm 时自动注入)。
    runtime: 运行时身份事实(A3/postmortem 防误验)——{"branch","root"};
    已知即注入「运行时身份」段, 杜绝 agent 把主目录服务探测当完成依据。
    probe_score: C 轴执行器探测分(R2.5 同挡个体差异, 仅 T1/T2; 开关
    r2_5_intra_tier)——弱则密度升档, T2 强则允许并步。
    """
    if policy is None:
        from ..governance.gears import default_policy
        policy = default_policy()
    # M1 收编: cap_note 段经 compensation.providers(字节级等价, R1.1)
    from ..compensation.providers import cap_note_section
    parts_style_note = cap_note_section(policy)
    # R2.5(开关 r2_5_intra_tier): 同挡密度微调段(仅 T1/T2)
    try:
        from ..compensation.overrides import read_overrides
        from ..compensation.overrides import override_enabled as _oe
        from ...arch_routes import store as _s
        if _oe(read_overrides(_s.CollabConfigStore.get), "r2_5_intra_tier"):
            from ..compensation.providers.intratier import intra_tier_note
            _intra = intra_tier_note(str(getattr(policy, "tier", "") or ""),
                                     probe_score)
            if _intra:
                parts_style_note += _intra + "\n"
    except Exception:  # noqa: BLE001 — 微调基础设施异常不阻塞指令组装
        pass
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
    # cv-205: 工作环境段按执行形态分叉, 文案经 compensation.providers 单源
    # (R1.1; 形态事实由执行层 runtime.workspace 传入, 本层不推断)
    from ..compensation.providers.exec_env import work_env_section
    runtime = runtime or {}
    parts.append(work_env_section(str(runtime.get("workspace") or "inplace")))
    _branch = str(runtime.get("branch") or "").strip()
    _root = str(runtime.get("root") or "").strip()
    if _branch or _root:
        # cv-205: 运行时身份段同样按形态分叉(就地/隔离事实相反), 文案经单源
        from ..compensation.providers.exec_env import runtime_identity_section
        parts.append(runtime_identity_section(
            str(runtime.get("workspace") or "inplace"), _branch, _root))
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
    # M1 收编: 里程碑协议 + 挡位粒度/节奏分叉经 compensation.providers
    # (环节十一/十二a 文案单源迁移, 字节级等价 R1.1)
    # R3.3: structured_output 挡 → 报告优先 JSON 块契约(双轨解析, 白名单行为变更)
    from ..compensation.providers import agent_note_section, milestone_section
    parts.append(milestone_section(
        structured=bool(getattr(policy, "structured_output", False))))
    agent_note = agent_note_section(policy)
    if agent_note:
        parts.append(agent_note)
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


def split_tasks_llm(req_text: str, policy: Optional[Any] = None) -> Optional[list]:
    """LLM 拆步: ≥2 步返回步骤列表; 单步/失败/不可用 → None(回落单卡)。

    R3.1 链3收编(D7-①): 经 CallTurn——T2 附步骤模板脚手架(每步=文件+动作+验证,
    禁跨模块)/按挡重试; 兜底维持单卡(返回 None)。"""
    if not (req_text or "").strip():
        return None
    schema = {
        "type": "object",
        "properties": {
            "tasks": {"type": "array", "items": {
                "type": "object",
                "properties": {"title": {"type": "string"},
                               "instruction": {"type": "string"},
                               "depends": {"type": "array",
                                           "items": {"type": "integer"},
                                           "description": "前置步骤序号(1 基, 仅强依赖)"}},
                "required": ["title", "instruction"]}},
        },
        "required": ["tasks"],
    }
    # R3.1(D7-①): 经 CallTurn(分目的脚手架/按挡重试; 遥测带 tier/purpose)
    from ...agent.compensation.ctx import Purpose
    from ...agent.turns import call as _call_turn
    r = _call_turn.call(
        Purpose.SPLIT,
        [{"role": "system",
          "content": "你是任务计划器。把需求拆成**有序的实施步骤**(每步单一模块级"
                     "目标、可独立构建验证)。规则: 2-5 步; 若需求足够单一一步可完成,"
                     "返回单步; 步骤 instruction 写实质内容(目标/涉及文件/验证方式)。"
                     "只输出结构化结果。"},
         {"role": "user", "content": f"需求文本:\n{req_text[:6000]}"}],
        tier=str(getattr(policy, "tier", "") or "T1"),
        schema=schema, max_tokens=2048,
        validate=lambda p: (isinstance((p or {}).get("tasks"), list)
                            and bool(p["tasks"]), "tasks 非列表或为空"),
        fallback=lambda: None)
    payload = r.get("output") if r.get("ok") else None
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
            row = {"title": title[:120], "instruction": instr[:4000]}
            deps = t.get("depends")
            if isinstance(deps, list) and deps:
                row["depends"] = deps          # llm 挡声明; linear 挡由调用方覆盖
            out.append(row)
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
        _step_instruction(plan, idx), executor_hint=executor_hint,
        gate_diagram=False)   # R3.2: 计划步骤卡豁免图门禁(图随计划上下文)
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
        # 批戊收编: 「已有计划→推进」半边迁焦点栈(resolve_intent.confirm_task
        # 就近启动预填卡)——本路径只做**无副作用诊断**(三分态), 不再暗推进。
        return {"ok": False, "receipt": _plan_diagnosis(plan)}
    steps = split_tasks_llm(req_text, policy=policy)
    if not steps:
        return None
    plan = [{"seq": i + 1, "title": s["title"], "instruction": s["instruction"],
             "taskId": "", "status": "pending",
             **({"depends": s.get("depends") or []}
                if policy.depends_source == "llm" and s.get("depends") else {})}
            for i, s in enumerate(steps)]
    # A2: 建图确定性校验(不信任模型产出); 失败 → 降级线性链并明示
    from . import task_graph as _tg
    if policy.depends_source == "llm":
        graph = _tg.validate_graph(plan)
        if not graph["ok"]:
            plan = _tg.linear_depends(plan)
    else:
        plan = _tg.linear_depends(plan)     # 弱挡: LLM 不产边, 编排层线性链
    plan = _tg.normalize_plan(plan)
    save_plan(rid, plan)
    _land_plan_card(conv, rid, plan)
    out = propose_plan_step(conv, rid, 0, executor_hint=_hint)
    if out.get("ok"):
        out["receipt"] = (f"📋 已生成任务计划({len(plan)} 步)并保存第一步，"
                          "点「开始执行」启动; 后续步骤完成后自动预填。")
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


def _plan_diagnosis(plan: list) -> str:
    """计划现状三分态诊断(批戊: 替代旧 fail-fast 单文案——待确认/失败/依赖未满)。

    步骤态读**绑定任务的实际状态**(plan 行 status 只记账推进, 卡片真态在
    任务行——cv-241 实证: 预填后 plan 行仍 pending 而任务已 saved)。
    推进动作本身归焦点栈(resolve_intent.confirm_task)。"""
    from ...arch_routes import store as _s
    pending_confirm, failed = [], []
    for s in plan:
        tid = s.get("taskId")
        st = str(((_s.TasksStore.get(tid) or {}).get("status"))
                 if tid else (s.get("status") or ""))
        if st in ("saved", "pending_confirm"):
            pending_confirm.append(s)
        elif st == "failed":
            failed.append(s)
    if pending_confirm:
        names = "、".join(f"步骤 {s.get('seq')}" for s in pending_confirm[:3])
        return (f"📋 计划有已预填待确认的步骤（{names}）——点对应任务卡"
                "「开始执行」，或直接回复「确认/继续执行」即可启动。")
    if failed:
        names = "、".join(f"#{s.get('seq')}" for s in failed[:3])
        return (f"📋 计划存在失败步骤（{names}）——回复「重试」重新下发，"
                "或在对话中说明调整要求。")
    blocked = [s for s in plan if (s.get("status") or "") == "pending"]
    if not blocked:
        return ("📋 任务计划已全部完成。如需继续演进, "
                "直接在对话中说明要调整的内容后再说\"执行\"。")
    from . import task_graph as _tg
    overview = _tg.blocked_summary(plan)
    return f"📋 计划步骤存在未满足的依赖（{overview}）——完成前置步骤后自动预填。"


def retry_failed_step(conv: dict, task_id: str) -> Dict[str, Any]:
    """焦点动作执行器: 重发失败步骤(retry_failed 指代的落地; 批戊)。

    指代(taskId)由焦点 recent.task_failed 就近给出; 依赖满足性沿用
    propose_plan_step 内部校验。"""
    from ...arch_routes import store as _s
    task = _s.TasksStore.get(task_id) or {}
    rid = str(task.get("reqId") or "")
    plan = get_plan(rid)
    if not plan:
        return {"ok": False, "receipt": "该任务不在任何计划中，无法按步骤重发。"}
    for s in plan:
        if s.get("taskId") == task_id:
            if (s.get("status") or "") != "failed":
                return {"ok": False, "receipt":
                        f"步骤 {s.get('seq')} 当前状态为 {s.get('status')}，仅失败步骤可重发。"}
            out = propose_plan_step(conv, rid, plan.index(s))
            if out.get("ok"):
                out["receipt"] = (f"🔁 计划步骤 {s.get('seq')}/{len(plan)} "
                                  f"「{(s.get('title') or '')[:24]}」已重发，待确认执行。")
            return out
    return {"ok": False, "receipt": "计划与任务不一致——请以最新任务卡为准。"}


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
        from . import task_graph as _tg
        ready = [i for i in _tg.ready_indices(plan)
                 if plan[i].get("status") == "pending"]
        if ready:
            conv = _s.ConversationsStore.get(conv_id) or {}
            out = propose_plan_step(conv, rid, ready[0])
            if out.get("ok"):
                from ...arch_routes import exec_bridge as eb
                deps = plan[ready[0]].get("depends") or []
                dep_note = (f"（依赖 {', '.join('#' + str(d) for d in deps)}"
                            "已完成）" if deps else "")
                eb._append(conv_id, "assistant",
                           f"➡️ 计划步骤 {ready[0] + 1}/{len(plan)} 已预填"
                           f"{dep_note}（含前情简报），待确认执行。",
                           msg_meta={"kind": "taskPlan", "requirementId": rid,
                                     "total": len(plan)},
                           project_id=(conv or {}).get("projectId") or "")
        else:
            blocked = [s for s in plan if s.get("status") == "pending"]
            failed = [s for s in plan if s.get("status") == "failed"]
            if blocked and not failed:
                # fail-fast: 存在失败依赖 → 后继阻塞等人工(不自动跳过)
                conv = _s.ConversationsStore.get(conv_id) or {}
                from ...arch_routes import exec_bridge as eb
                overview = _tg.blocked_summary(plan)
                eb._append(conv_id, "assistant",
                           f"⛔ 计划后继步骤被阻塞（{overview}）——"
                           "请处理失败步骤后再说\"执行\"重发。",
                           msg_meta={"kind": "taskPlan", "requirementId": rid,
                                     "total": len(plan)},
                           project_id=(conv or {}).get("projectId") or "")
            elif not failed:
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
