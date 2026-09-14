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
    etype = (executorType or "").strip()
    if etype not in ("cline", "opencode", "codex"):
        # 会话绑定了执行器 → 用其注册表类型(用户既定选择); 否则 opencode
        _bound = exec_bridge.executor_hint_by_id(str(conv.get("executorId") or ""), conv)
        etype = ((_bound or {}).get("executorType") or "").strip() or "opencode"
    if not (instruction or "").strip():
        return {"error": "instruction 缺少实质内容(为空)——请写实质任务内容(目标/方案/验收)"}
    task = exec_bridge.propose_task(conv, title, instruction,
                                    executor_hint={"executorType": etype,
                                                   "executorId": conv.get("executorId") or ""})
    return {"ok": True, "taskId": task["id"], "status": task.get("status"),
            "hint": "任务卡已生成, 等待用户确认后执行; 请告知用户可确认/取消/调整。"}


def assemble_task_instruction(task: dict, prior_brief: str = "") -> str:
    """任务指令组装: task.instruction(architect 整理) 为正文 + 绑定需求规约
    补充(边界/验收) + 工作环境/DoD 系统段(确定性注入, 不依赖 LLM)。

    prior_brief: 前情简报(重试时注入)。
    """
    rid = task.get("reqId") or ""
    r = _store().RequirementsStore.get(rid) or {} if rid else {}
    active = _store().RequirementsStore.spec_active(rid) or {} if rid else {}
    a = (active.get("snapshot") or {}) if rid else {}
    if not a and rid:
        a = r.get("analysis") or {}
    parts = [f"# 实施任务：{task.get('title') or '任务'}"
             + (f"（{rid} · 规约 v{active.get('ver') or '?'}）" if rid else "")]
    body = str(task.get("instruction") or "").strip()
    if prior_brief:
        parts.append("## 前情简报(上次作业)\n" + prior_brief)
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
        "2. 为新增/变更逻辑编写并运行单元测试(全部通过)；\n"
        "3. 完成整体编译/构建验证(项目可编译、无链接错误)；\n"
        "4. 全部完成后输出 [[IMPLEMENT_DONE]] 与摘要(变更文件/单测结果/编译结果/遗留项)；"
        "任一环节需要用户操作、确认、澄清或补充信息时，输出 [[NEED_INPUT]] 与具体问题后结束回合等待。")
    return "\n\n".join(parts)

