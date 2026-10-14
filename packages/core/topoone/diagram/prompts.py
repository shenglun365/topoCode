"""LLM-facing IR documentation for the unified DiagramSchema (single source of truth).

Describes the DiagramSchema IR (schema_data/diagram.schema.json) so agents produce
the SAME IR the render/validate/export kernels consume. Replaces the legacy
per-type IR prompt (old topoone.engine.diagram_ir_docs), which now only remains as
a re-export shim for backward import compat.

The build/validate tools (web_diagram_build / web_diagram_validate / the docs
/api/diagram/* endpoints) accept this IR; legacy IR is still accepted via
topoone.diagram.compat and normalized onto this schema.
"""

from __future__ import annotations

import json

from .capabilities import load_capabilities


def _engine_types() -> str:
    caps = load_capabilities()
    lines = []
    for engine, cfg in caps.get("engines", {}).items():
        types = cfg.get("types", {})
        native = ", ".join(t for t, s in types.items() if s == "native")
        emulated = ", ".join(t for t, s in types.items() if s == "emulated")
        if native:
            lines.append(f"- {engine}: native={native}")
        if emulated:
            lines.append(f"- {engine}: emulated={emulated}（前端模拟转译）")
    return "\n".join(lines)


def overview_docs() -> str:
    return (
        "## 建图能力\n"
        "你可以创建以下类型图。构造 DiagramSchema IR 后调用 web_diagram_build 生成代码。\n\n"
        "### 类型与引擎支持矩阵\n"
        f"{_engine_types()}\n\n"
        "### IR 公共字段\n"
        "```\n"
        "version: 1\n"
        "type: flowchart | activity | sequence | state | class | er | usecase | component | architecture | gantt | pie\n"
        "title: string（可选）\n"
        "direction: TB | BT | LR | RL（可选，flowchart 用）\n"
        "nodes: [{id, label, kind?, style?{fill,stroke,color}, lane?}]（流程图类）\n"
        "edges: [{from, to, label?, kind?(solid|dashed|dotted|thick), arrow?(filled|open|none)}]\n"
        "groups: [{id, label, contains[id...], kind?(subgraph|layer|boundary)}]\n"
        "animation: {mode?(reveal|highlight), stepMs?, steps:[{label?, nodes?, edges?, selectors?}]}（可选）\n"
        "```\n"
        "id 约束：`^[A-Za-z][A-Za-z0-9_-]{0,63}$`（字母开头，≤64 字符）。\n"
        "engine 由服务端按支持矩阵协商（native 优先，其次 emulated）。\n"
    )


def sequence_docs() -> str:
    return (
        "### sequence — 时序图\n"
        "```\n"
        "participants: [{id, label, type?(participant|actor|boundary|database|entity)}]\n"
        "messages: [{from, to, label, kind(sync|async|return), self?}]\n"
        "```"
    )


def state_docs() -> str:
    return (
        "### state — 状态图\n"
        "```\n"
        "states: [{id, label, initial?, final?, sub?[id...]}]\n"
        "transitions: [{from, to, label?, guard?}]\n"
        "```"
    )


def class_docs() -> str:
    return (
        "### class — 类图\n"
        "```\n"
        "classes: [{id, name, members?:[{name, kind?(attr|method), visibility?(public|private|protected|package), type?}]}]\n"
        "classRelations: [{from, to, kind(inherit|impl|assoc|comp|agg|dep), label?}]\n"
        "```"
    )


def er_docs() -> str:
    return (
        "### er — 实体关系图\n"
        "```\n"
        "entities: [{id, name, attrs?:[{name, key?, type?}]}]\n"
        "erRelations: [{from, to, kind(1:1|1:N|M:N), label?}]\n"
        "```"
    )


def gantt_docs() -> str:
    return (
        "### gantt — 甘特图\n"
        "```\n"
        "sections: [{id, label}]\n"
        "tasks: [{id, title, section(id), start(YYYY-MM-DD), duration(天), dependsOn?[id...], tags?(done|active|crit)}]\n"
        "```"
    )


def pie_docs() -> str:
    return (
        "### pie — 饼图\n"
        "```\n"
        "slices: [{id, label, value(number>=0)}]\n"
        "```"
    )


def activity_docs() -> str:
    return (
        "### activity — 活动图\n"
        "```\n"
        "nodes: [{id, label, kind?(action|decision|fork|join|start|end)}]\n"
        "edges: [{from, to, label?}]\n"
        "```"
    )


def flowchart_example_docs() -> str:
    return (
        "### 示例 IR（flowchart）\n"
        "```json\n"
        "{\n"
        '  "version": 1,\n'
        '  "type": "flowchart",\n'
        '  "direction": "TB",\n'
        '  "title": "系统架构",\n'
        '  "nodes": [\n'
        '    {"id": "vue", "label": "Vue前端", "kind": "rect", "style": {"fill": "#42b883"}},\n'
        '    {"id": "api", "label": "API网关", "kind": "diamond"},\n'
        '    {"id": "db", "label": "数据库", "kind": "stadium"}\n'
        "  ],\n"
        '  "edges": [\n'
        '    {"from": "vue", "to": "api", "label": "HTTP", "kind": "solid"},\n'
        '    {"from": "api", "to": "db", "kind": "thick"}\n'
        "  ],\n"
        '  "groups": [\n'
        '    {"id": "fe", "label": "前端层", "contains": ["vue"]},\n'
        '    {"id": "be", "label": "后端层", "contains": ["api", "db"]}\n'
        "  ]\n"
        "}\n"
        "```"
    )


def animation_docs() -> str:
    return (
        "### 动画（可选）\n"
        "需要动态讲解时在 IR 中携带 animation 块（steps 引用节点/边 id 或 CSS 选择器）。\n"
        "前端提供播放控件；默认不自动播放。\n"
        "```\n"
        'animation: {mode: "reveal", stepMs?: 1500, steps: [{label?: "步骤1", nodes: ["a"]}, {edges: ["e1"]}]}\n'
        "```"
    )


def constraints_docs() -> str:
    return (
        "### 工作流程\n"
        "1. 先用项目分析工具查询数据（如 web_get_community_tree / web_get_community_graph / web_get_architecture_overview 等）\n"
        "2. 根据查询结果构造 DiagramSchema IR（version/type + 各类型字段 + 可选 animation）\n"
        "3. 调用 web_diagram_build 从 IR 生成图代码\n"
        "4. 调用 web_diagram_validate 校验（可传 code 或 IR，schema 源会做结构/语义/动画一致性校验）\n"
        "5. 用 📐 前缀和 ``` 代码块展示给用户\n\n"
        "### 约束\n"
        "- 永远不要直接输出图代码。必须通过 web_diagram_build 生成。\n"
        "- 生成后调用 web_diagram_validate 确保语法正确。\n"
        "- nodes/edges 等数组字段即使为空也要传入（空数组 []）；类型必填字段缺一不可。"
    )


def diagram_editor_prompt() -> str:
    return "\n\n".join([
        overview_docs(),
        flowchart_example_docs(),
        sequence_docs(),
        state_docs(),
        class_docs(),
        er_docs(),
        gantt_docs(),
        pie_docs(),
        activity_docs(),
        animation_docs(),
        constraints_docs(),
    ])


__all__ = [
    "diagram_editor_prompt",
    "overview_docs",
    "sequence_docs",
    "state_docs",
    "class_docs",
    "er_docs",
    "gantt_docs",
    "pie_docs",
    "activity_docs",
    "flowchart_example_docs",
    "animation_docs",
    "constraints_docs",
]
