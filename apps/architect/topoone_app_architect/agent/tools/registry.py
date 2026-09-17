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


def register_architect_tool(name: str, description: str = "",
                            params_doc: str = "", brief: str = "") -> Callable:
    """注册工具。B4 单源: brief(能力清单一行简介)/params_doc(参数形状)为
    能力文档渲染元数据, 注册点直接传参(优先于 prompt.py 迁移表)。
    注: 存量迁移表(TOOL_BRIEFS/TOOL_PARAM_DOCS)在 cognition/prompt.py——
    它们是提示词内容而非执行元数据, 放 cognition 层避免反向依赖本模块。"""
    def decorator(fn):
        _ARCH_TOOLS[name] = {"name": name, "description": description,
                             "handler": fn,
                             "params_doc": params_doc, "brief": brief}
        return fn
    return decorator


def architect_tools() -> List[Dict[str, str]]:
    return [{"name": t["name"], "description": t["description"]} for t in _ARCH_TOOLS.values()]




# 归档会话上禁止的动作类工具(生成/落库/指派); 检索与读取类不在此列
_ARCHIVED_DENY_TOOLS = {
    "req.propose", "contract.propose", "task.propose",
}

# v2 统一会话: 规约状态机工具在快捷挡退役(严格挡恢复可用, run_arch_tool 按挡放行)
# ——快捷挡模型误调时给出引导而非静默失败(P2 物理删除注册)。
# 文案必须是快捷挡语义(此映射只在 quick 挡触达模型; strict 挡放行不会看到)。
_RETIRED_TOOLS = {
    "req.finalize": "req.finalize 已退役——需求卡创建即 ready, 无需确认步骤。",
}
