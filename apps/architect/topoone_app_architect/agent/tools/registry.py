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

# v2 统一会话: 规约状态机工具在快捷挡退役(严格挡恢复可用, run_arch_tool 按挡放行)
# ——快捷挡模型误调时给出引导而非静默失败(P2 物理删除注册)。
# 文案必须是快捷挡语义(此映射只在 quick 挡触达模型; strict 挡放行不会看到)。
_RETIRED_TOOLS = {
    "req.propose": "快捷挡不做规约(不调 req.propose)。请直接整理目标/方案要点/边界/验收, 调用 task.propose 创建任务卡。",
    "req.finalize": "快捷挡无规约可定稿(不调 req.finalize)。直接调用 task.propose 建卡即可。",
    "req.amend": "快捷挡无规约可修订(不调 req.amend)。直接按新方案调用 task.propose 重新建卡。",
}
