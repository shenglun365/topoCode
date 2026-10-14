"""任务两端 MCP 工具(2610 规约&MCP 定型 P3)——serve 执行器/外部 TUI 交互闭环。

定位(裁决: 执行器编码期完全自主, architect 两端认知辅助):
- task.mandate 开工前取执行契约(context_pack 同源: 规约/边界/约束/验收
  + 项目规约全集)——帮执行器/TUI 准确知道"干什么、关键点怎么干";
- task.receipt 完工后提交回执(_acceptance_brief 同源: 越界检测 L-1①
  自纠正 + 验收对照 + 改动分布)——回答"干得怎么样、都干了什么、
  是否符合要求"。只做评估返回, 不改任务状态机(D-4)。
"""
from __future__ import annotations

from typing import List, Optional


def _task_of(task_id: str) -> dict:
    from ..store.tasks import TasksStore
    return TasksStore.get(task_id) or {}


def _root_of(project_id: str) -> str:
    from .. import store
    proj = store.ProjectsStore.get(project_id) or {}
    return str(proj.get("rootPath") or "")


def tool_task_mandate(task_id: str = "", req_id: str = "",
                      project: Optional[str] = None) -> str:
    """执行契约: task_id 或 req_id 二选一(req_id=需求级, 无任务字段)。"""
    from ..agent.execution.context_pack import (
        build_context_pack, render_context_pack_md)
    from .map_tools import tool_rules
    if task_id:
        task = _task_of(task_id)
        if not task:
            return f"# 执行契约\n\n任务不存在: {task_id}"
        req_id = str(task.get("reqId") or "")
        conv = None
        try:
            from .. import store
            conv = store.ConversationsStore.get(str(task.get("conversationId") or "")) or None
        except Exception:  # noqa: BLE001
            conv = None
        pid = str(task.get("projectId") or "")
        title = str(task.get("title") or "")
    else:
        if not req_id:
            return "# 执行契约\n\n请传 task_id 或 req_id。"
        task = {"reqId": req_id, "projectId": project or "", "safetyClass": "mutating"}
        conv, pid, title = None, project or "", ""
    root = _root_of(pid)
    pack = build_context_pack(task, conv, root)
    md = ["# 执行契约(architect 下发)",
          f"- 任务: {title or '(需求级契约, 无任务卡)'}",
          f"- 需求: `{req_id}` · 项目: `{pid or '?'}`"]
    if pack.get("incomplete"):
        md.append(f"- ⚠️ 契约要素缺失: {'; '.join(pack.get('missing') or [])}")
    md.append(render_context_pack_md(pack))
    rules = tool_rules(pid or project or None)
    if rules and "无法唯一定位项目" not in rules:
        md.append(rules)
    return "\n\n".join(md)


def tool_task_receipt(task_id: str, changed_files: Optional[List[str]] = None,
                      summary: str = "") -> str:
    """执行回执: 越界检测+验收对照+改动分布(评估性返回, 不改任务状态)。"""
    task = _task_of(task_id)
    if not task:
        return f"# 执行回执\n\n任务不存在: {task_id}"
    rid = str(task.get("reqId") or "")
    files = [str(f) for f in (changed_files or [])][:200]
    from ..agent.execution.exec_bridge import _acceptance_brief
    brief = _acceptance_brief(str(task.get("conversationId") or ""), rid, files)
    md = [f"# 执行回执(任务 {task_id})"]
    if summary:
        md.append(f"## 执行摘要\n{summary[:2000]}")
    md.append(f"## 改动清单({len(files)} 文件)\n"
              + ("\n".join(f"- `{f}`" for f in files[:20])
                 + ("\n- …" if len(files) > 20 else "") if files else "(空)"))
    if files:
        dirs: dict = {}
        for f in files:
            top = f.split("/")[0] if "/" in f else "(根)"
            dirs[top] = dirs.get(top, 0) + 1
        md.append("## 改动分布\n"
                  + "\n".join(f"- `{k}`: {v} 文件"
                              for k, v in sorted(dirs.items(), key=lambda x: -x[1])[:8]))
    md.append(brief or "(规约无验收要素)")
    # 2610 核心资产守护 P1: 确定性 post-flight(changed_files ∩ 标记集)
    try:
        from .. import store as _st
        from . import core_guard as _cg
        pid = str(task.get("projectId") or "")
        cg_md = _cg.postflight_md(pid, files) if pid else ""
        if cg_md:
            md.append(cg_md)
    except Exception:  # noqa: BLE001 — 守护评估失败不阻塞回执
        pass
    return "\n\n".join(md)


def run_task_tool(name: str, args: dict) -> str:
    if name == "task.mandate":
        return tool_task_mandate(str(args.get("task_id") or ""),
                                 str(args.get("req_id") or ""),
                                 args.get("project"))
    if name == "task.receipt":
        cf = args.get("changed_files")
        return tool_task_receipt(str(args.get("task_id") or ""),
                                 cf if isinstance(cf, list) else [],
                                 str(args.get("summary") or ""))
    return f"未知任务工具: {name}(可用: task.mandate, task.receipt)"
