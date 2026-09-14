"""architect 工具注册表(工具层) — skills/tools 元数据注册。

P1 自 req_agent.py 迁入(注册表数据结构 + 装饰器 + 策略常量)。
工具 handler 本体仍注册于此表(经 req_agent 兼容层装饰器)；
执行环(run_arch_tool/参数收敛/修复)P2 随编排器迁入执行面。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

# ── Skills 注册表(architect 专属) ──────────────────────────────────────

_ARCH_SKILLS: List[Dict[str, Any]] = []


def register_architect_skill(name: str, description: str = "",
                             steps: int = 1, category: str = "requirement-analysis") -> Callable:
    """类/函数装饰器：注册 architect 专属技能元数据(与主后端 skill_registry 同形)。"""
    def decorator(fn):
        _ARCH_SKILLS.append({
            "name": name, "description": description, "steps": steps, "category": category,
        })
        return fn
    return decorator


def architect_skills() -> List[Dict[str, Any]]:
    seen: set = set()
    out = []
    for s in _ARCH_SKILLS:
        if s["name"] not in seen:
            seen.add(s["name"])
            out.append(s)
    return out


# ── Tools 注册表(architect 专属: 知识库检索 / 项目上下文) ──────────────

_ARCH_TOOLS: Dict[str, Dict[str, Any]] = {}


def register_architect_tool(name: str, description: str = "") -> Callable:
    def decorator(fn):
        _ARCH_TOOLS[name] = {"name": name, "description": description, "handler": fn}
        return fn
    return decorator


def architect_tools() -> List[Dict[str, str]]:
    return [{"name": t["name"], "description": t["description"]} for t in _ARCH_TOOLS.values()]


# 归档会话上禁止的动作类工具(生成/落库/定稿/指派); 检索与读取类不在此列
_ARCHIVED_DENY_TOOLS = {
    "req.propose", "req.finalize", "contract.propose", "task.propose",
}

# v2 统一会话: 规约状态机工具退役(命令路径已删)——模型误调时给出引导而非
# 静默失败(P2 物理删除注册)。
_RETIRED_TOOLS = {
    "req.propose": "需求规约状态机已退役。请在对话中整理需求与方案, 方案成熟时调用 task.propose 创建实施任务卡。",
    "req.finalize": "规约定稿已退役。任务经 task.propose 创建后由用户确认即可执行。",
    "req.amend": "规约修订已退役。直接在对话中调整方案, 并以 task.propose 重新发起。",
}
