"""绘图工具域(diagram.build|validate, 薄代理单一起源) — M3 自 req_agent 机械迁出(逐字保真, 注册随定义点)。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..registry import register_architect_tool

logger = logging.getLogger("arch_routes.req_agent")

# ── 绘图增强工具（经薄代理转发 reports diagram_tools 服务，单一起源） ──

@register_architect_tool(
    "diagram.build",
    "从结构化中间表示(IR)生成语法正确的 Mermaid/PlantUML 图代码。"
    "LLM 只描述图的结构(节点/边/分组/方向)，由本工具生成精确代码，"
    "避免小参数模型直接输出 mermaid/plantuml 源码时的语法错误。",
    params_doc='{"ir": "图 IR 对象(必填: nodes/edges/分组/方向等结构描述)"}',
)
def tool_diagram_build(ir: Dict[str, Any]) -> Dict[str, Any]:
    from ....arch_routes import diagram as _diagram
    return _diagram.call_build(ir)


@register_architect_tool(
    "diagram.validate",
    "校验 Mermaid/PlantUML 代码语法。返回 {valid, errors, warnings}。"
    "生成图后建议校验一次，语法有问题时修正 IR 重新调用 diagram.build。",
    params_doc='{"code": "图代码文本(必填)", "lang": "可选: mermaid(默认)|plantuml"}',
)
def tool_diagram_validate(code: str, lang: str = "mermaid") -> Dict[str, Any]:
    from ....arch_routes import diagram as _diagram
    return _diagram.call_validate(code, lang)
