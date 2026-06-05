"""5 个核心 Skill 定义 — 构建在 7 个核心 Tool 之上。

每个 Skill 组合多个 Tool 调用来完成更高层级的分析任务。
"""

from .dispatcher import ToolDispatcher
from .skill_executor import SkillDefinition, SkillExecutor


def register_core_skills(executor: SkillExecutor, dispatcher: ToolDispatcher) -> None:
    context_steps = [
        lambda args: dispatcher._handle_definition({
            "file_path": args["file_path"],
            "line": args.get("line", 1),
            "character": args.get("character", 0),
        }),
        lambda args: dispatcher._handle_references({
            "file_path": args["file_path"],
            "line": args.get("line", 1),
            "character": args.get("character", 0),
            "max_results": args.get("max_results", 50),
        }),
    ]

    executor.register(SkillDefinition(
        name="get_context_for_symbol",
        description="获取符号的完整上下文：定义位置 + 所有引用",
        steps=context_steps,
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "line": {"type": "integer"},
                "character": {"type": "integer"},
                "max_results": {"type": "integer", "default": 50},
            },
            "required": ["file_path"],
        },
    ))

    impact_steps = [
        lambda args: dispatcher._handle_call_hierarchy({
            "file_path": args["file_path"],
            "line": args.get("line", 1),
            "character": args.get("character", 0),
            "direction": "both",
            "max_depth": args.get("max_depth", 3),
        }),
        lambda args: dispatcher._handle_dependencies({
            "file_path": args["file_path"],
            "direction": "both",
        }),
    ]

    executor.register(SkillDefinition(
        name="get_impact_analysis",
        description="变更影响分析：调用层级 + 依赖分析",
        steps=impact_steps,
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "line": {"type": "integer"},
                "character": {"type": "integer"},
                "max_depth": {"type": "integer", "default": 3},
            },
            "required": ["file_path"],
        },
    ))

    explain_steps = [
        lambda args: dispatcher._handle_file_symbols({
            "file_path": args["file_path"],
        }),
        lambda args: dispatcher._handle_dependencies({
            "file_path": args["file_path"],
            "direction": "imports",
        }),
    ]

    executor.register(SkillDefinition(
        name="explain_code_block",
        description="解释代码块：文件概览（符号 + 依赖）",
        steps=explain_steps,
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
            },
            "required": ["file_path"],
        },
    ))

    refactor_steps = [
        lambda args: dispatcher._handle_definition({
            "file_path": args["file_path"],
            "line": args.get("line", 1),
            "character": args.get("character", 0),
        }),
        lambda args: dispatcher._handle_references({
            "file_path": args["file_path"],
            "line": args.get("line", 1),
            "character": args.get("character", 0),
            "max_results": 200,
        }),
        lambda args: dispatcher._handle_call_hierarchy({
            "file_path": args["file_path"],
            "line": args.get("line", 1),
            "character": args.get("character", 0),
            "direction": "both",
            "max_depth": args.get("max_depth", 2),
        }),
    ]

    executor.register(SkillDefinition(
        name="prepare_refactor",
        description="重构准备：定义 + 引用 + 调用层级（三层上下文）",
        steps=refactor_steps,
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "line": {"type": "integer"},
                "character": {"type": "integer"},
                "max_depth": {"type": "integer", "default": 2},
            },
            "required": ["file_path"],
        },
    ))

    docstring_steps = [
        lambda args: dispatcher._handle_symbol_info({
            "file_path": args["file_path"],
            "line": args.get("line", 1),
            "character": args.get("character", 0),
        }),
    ]

    executor.register(SkillDefinition(
        name="generate_docstring",
        description="为符号生成文档注释：获取符号信息 + 上下文",
        steps=docstring_steps,
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "line": {"type": "integer"},
                "character": {"type": "integer"},
            },
            "required": ["file_path"],
        },
    ))

    assess_merge_steps = [
        lambda args: dispatcher._handle_get_changes({
            "from_commit": args.get("from_commit", "HEAD~1"),
            "to_commit": args.get("to_commit", "HEAD"),
            "scope": "full",
        }),
        lambda args: dispatcher._handle_version_history({
            "max_count": 5,
        }),
    ]

    executor.register(SkillDefinition(
        name="assess_merge_impact",
        description="评估合并影响：变更报告 + 版本历史分析",
        steps=assess_merge_steps,
        input_schema={
            "type": "object",
            "properties": {
                "from_commit": {"type": "string", "description": "Base commit hash"},
                "to_commit": {"type": "string", "description": "Target commit hash"},
            },
            "required": [],
        },
    ))

    review_refactor_steps = [
        lambda args: dispatcher._handle_get_changes({
            "from_commit": args.get("from_commit", "HEAD~1"),
            "to_commit": args.get("to_commit", "HEAD"),
            "scope": "full",
        }),
        lambda args: dispatcher._handle_evaluate_change({
            "from_commit": args.get("from_commit", "HEAD~1"),
            "to_commit": args.get("to_commit", "HEAD"),
            "focus": args.get("focus", "overview"),
        }),
    ]

    executor.register(SkillDefinition(
        name="review_refactoring",
        description="审查重构：变更报告 + 语义评估",
        steps=review_refactor_steps,
        input_schema={
            "type": "object",
            "properties": {
                "from_commit": {"type": "string", "description": "Base commit hash"},
                "to_commit": {"type": "string", "description": "Target commit hash"},
                "focus": {
                    "type": "string", "enum": ["overview", "breaking", "refactoring", "security"],
                    "default": "overview",
                },
            },
            "required": [],
        },
    ))
