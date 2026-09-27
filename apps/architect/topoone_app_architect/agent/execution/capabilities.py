"""执行器能力矩阵单源（B1; agent-structure-review 批次 B1 落地）。

任务行语义类型（canonical）= cline / opencode / codex；注册表实现类型
（runner TurnAdapter 面）= cline-sdk / opencode / codex-server——双命名空间
在此归一（教训 cv-153/G4: 类型字符串散落 4+ 处, 加第 4 个执行器要改 7+ 处）。

新增执行器 = 在 _CANONICAL/_ALIASES/CAPABILITIES 各加一行 + 一个 TurnAdapter。
写范围（workspace_rules/agents）: cline 为目录约定（.cline/rules|agents）,
opencode/codex 为 AGENTS.md 单文件（空串约定, 组装端回落）。
"""
from __future__ import annotations

from typing import Dict

_CAPA = Dict[str, object]

CAPABILITIES: Dict[str, _CAPA] = {
    "cline": {
        "multi_turn": True, "approval": True, "checkpoint": True,
        "readonly_hard": True, "steer": True,
        "workspace_rules": ".cline/rules", "workspace_agents": ".cline/agents",
        # mcp_servers 载荷形状(turn_adapter 侧约定): cline sidecar=list,
        # opencode=dict, codex adapter 不消费=""
        "mcp_shape": "list",
    },
    "opencode": {
        "multi_turn": True, "approval": False, "checkpoint": False,
        "readonly_hard": False, "steer": False,
        "workspace_rules": "", "workspace_agents": "",
        "mcp_shape": "dict",
    },
    "codex": {
        "multi_turn": True, "approval": False, "checkpoint": False,
        "readonly_hard": True, "steer": False,
        "workspace_rules": "", "workspace_agents": "",
        "mcp_shape": "",
    },
}

# 注册表实现类型 → 任务行语义类型（别名单源; registry type 字段值在此入列）
_ALIASES: Dict[str, str] = {
    "cline": "cline",
    "cline-sdk": "cline",
    "opencode": "opencode",
    "codex": "codex",
    "codex-server": "codex",
}


def normalize(t: str) -> str:
    """任意命名空间（任务行/注册表）→ 任务行语义类型；未知返回空串。"""
    return _ALIASES.get(str(t or "").strip(), "")


def is_valid_type(t: str) -> bool:
    """bool(normalize(t))——任意命名空间下的合法性判断（替代散落元组成员检查）。"""
    return bool(normalize(t))


def executor_types() -> list:
    """语义类型清单（UI 下拉/校验单源）。"""
    return sorted(CAPABILITIES)


def caps(t: str) -> _CAPA:
    """按任意命名空间取能力行；未知类型返回 {}（调用方按 falsy 回落通用路径）。"""
    return CAPABILITIES.get(normalize(t), {})
