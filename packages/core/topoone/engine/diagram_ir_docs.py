"""Human-readable IR documentation for LLM prompts.

Each function returns a markdown string describing the IR format
for a specific diagram type. Used by skills.py to build the
context_prompt for the diagram_editor skill.

Individual type docs are exported so they can be used independently
if per-type skills are needed in the future.
"""


def overview_docs() -> str:
    return (
        "## 建图能力\n"
        "你可以创建以下类型图。构造 IR 后调用 web_diagram_build 生成代码。\n\n"
        "### 支持类型\n"
        "mermaid: flowchart, sequence, class, state, er, gantt, pie\n"
        "plantuml: component, sequence, activity\n\n"
        "### IR 公共字段\n"
        "```\n"
        "lang: mermaid | plantuml\n"
        "diagram_type: flowchart | sequence | class | state | er | gantt | pie | component\n"
        "title: string（可选）\n"
        "comments: string[]（可选，行首注释）\n"
        "```"
    )


def mermaid_flowchart_docs() -> str:
    return (
        "### flowchart — 流程图\n"
        "```\n"
        "direction: TB | LR | RL | BT\n"
        "nodes: [{id, text, shape(rect|round|stadium|diamond|circle), styles:{fill,stroke}, classes[], click:{url,tooltip}}]\n"
        "edges: [{from, to, label, style(arrow|thick|dotted|line|cross|circle), markers:{start,end}}]\n"
        "subgraphs: [{id, title, nodes[id...], direction}]\n"
        "class_defs: [{name, styles}]\n"
        "init_config: {theme, themeVariables}\n"
        "```"
    )


def mermaid_sequence_docs() -> str:
    return (
        "### sequence — 时序图\n"
        "```\n"
        "participants: [{name, alias, type(participant|actor)}]\n"
        "messages: [{from, to, label, arrow(->|-->|->>|-->>|-x|--x)}]\n"
        "```"
    )


def mermaid_class_docs() -> str:
    return (
        "### class — 类图\n"
        "```\n"
        "classes: [{name, stereotype, members:[{visibility,name,type,is_method,params}], namespace}]\n"
        "relations: [{from, to, type(extension|composition|aggregation|association|dependency|realization), label}]\n"
        "```"
    )


def mermaid_state_docs() -> str:
    return (
        "### state — 状态图\n"
        "```\n"
        "states: [{id, text, children:[{id,text,children...}]}]\n"
        "transitions: [{from, to, label}]\n"
        "```"
    )


def mermaid_er_docs() -> str:
    return (
        "### er — 实体关系图\n"
        "```\n"
        "entities: [{name, attributes:[{name,type,pk,fk}]}]\n"
        "relations: [{from, to, type(one_to_one|one_to_many|many_to_many|...), label}]\n"
        "```"
    )


def mermaid_gantt_docs() -> str:
    return (
        "### gantt — 甘特图\n"
        "```\n"
        "date_format: string（如 YYYY-MM-DD）\n"
        "sections: [{name, tasks:[{name,start,duration,status(done|active)}]}]\n"
        "```"
    )


def mermaid_pie_docs() -> str:
    return (
        "### pie — 饼图\n"
        "```\n"
        "items: [{label, value}]\n"
        "```"
    )


def plantuml_component_docs() -> str:
    return (
        "### component — 组件图（PlantUML）\n"
        "```\n"
        "nodes: [{id, text, styles:{fill}}]\n"
        "edges: [{from, to, label}]\n"
        "subgraphs: [{id, title, nodes[id...]}]\n"
        "```"
    )


def plantuml_sequence_docs() -> str:
    return (
        "### sequence — 时序图（PlantUML）\n"
        "```\n"
        "participants: [{name, alias, type(participant|actor)}]\n"
        "messages: [{from, to, label}]\n"
        "```"
    )


def flowchart_example_docs() -> str:
    return (
        "### 示例 IR（flowchart）\n"
        "```json\n"
        "{\n"
        '  "lang": "mermaid",\n'
        '  "diagram_type": "flowchart",\n'
        '  "direction": "TB",\n'
        '  "title": "系统架构",\n'
        '  "nodes": [\n'
        '    {"id": "vue", "text": "Vue前端", "shape": "rect", "styles": {"fill": "#42b883"}},\n'
        '    {"id": "api", "text": "API网关", "shape": "diamond"},\n'
        '    {"id": "db", "text": "数据库", "shape": "stadium"}\n'
        "  ],\n"
        '  "edges": [\n'
        '    {"from": "vue", "to": "api", "label": "HTTP", "style": "arrow"},\n'
        '    {"from": "api", "to": "db", "style": "thick"}\n'
        "  ],\n"
        '  "subgraphs": [\n'
        '    {"id": "fe", "title": "前端层", "nodes": ["vue"]},\n'
        '    {"id": "be", "title": "后端层", "nodes": ["api", "db"]}\n'
        "  ]\n"
        "}\n"
        "```"
    )


def constraints_docs() -> str:
    return (
        "### 工作流程\n"
        "1. 先用项目分析工具查询数据（如 web_get_community_tree 查看层级、web_get_community_graph 获取子图结构、web_get_architecture_overview 查看概览等）\n"
        "2. 根据查询结果构造 IR（节点、边、分组等）\n"
        "3. 调用 web_diagram_build 从 IR 生成图代码\n"
        "4. 调用 web_diagram_validate 校验语法\n"
        "5. 用 📐 前缀和 ``` 代码块展示给用户\n\n"
        "### 约束\n"
        "- 永远不要直接输出图代码。必须通过 web_diagram_build 生成。\n"
        "- 生成后调用 web_diagram_validate 确保语法正确。\n"
        "- nodes/edges 等数组字段即使为空也要传入（空数组 []）。"
    )


def plantuml_activity_docs() -> str:
    return (
        "### activity — 活动图（PlantUML）\n"
        "```\n"
        "flow: 线性步骤数组，每步含 type:\n"
        '  {type: "action", text: "动作"}\n'
        '  {type: "note", text: "备注"}\n'
        '  {type: "branch", condition: "判断条件", then: [steps], else: [steps], '
        'then_label?: "是", else_label?: "否"}\n'
        '  {type: "fork", branches: [[steps], [steps]]}\n'
        "兼容简化写法 steps: [\"动作1\", \"动作2\"]。\n"
        "```"
    )


def diagram_editor_prompt() -> str:
    return "\n\n".join([
        overview_docs(),
        mermaid_flowchart_docs(),
        mermaid_sequence_docs(),
        mermaid_class_docs(),
        mermaid_state_docs(),
        mermaid_er_docs(),
        mermaid_gantt_docs(),
        mermaid_pie_docs(),
        plantuml_component_docs(),
        plantuml_sequence_docs(),
        plantuml_activity_docs(),
        flowchart_example_docs(),
        constraints_docs(),
    ])


__all__ = [
    "diagram_editor_prompt",
    "overview_docs",
    "mermaid_flowchart_docs",
    "mermaid_sequence_docs",
    "mermaid_class_docs",
    "mermaid_state_docs",
    "mermaid_er_docs",
    "mermaid_gantt_docs",
    "mermaid_pie_docs",
    "plantuml_component_docs",
    "plantuml_sequence_docs",
    "plantuml_activity_docs",
    "flowchart_example_docs",
    "constraints_docs",
]
