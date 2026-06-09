"""Skills — 内置 Agent 可调用的技能定义。

所有 LLM 生成能力 Skills 化，Agent 自主组合。
Skills 分为五类: 文档生成、图生成、架构学习/设计、批量编排、会话追踪。
"""

from .dispatcher import ToolDispatcher
from .skill_executor import SkillDefinition, SkillExecutor, SkillStepDef


def _call(dispatcher: ToolDispatcher, method: str):
    """返回直接调用 dispatcher handler 的 lambda（sync）。"""
    handler = getattr(dispatcher, method, None)
    def _fn(args: dict) -> dict:
        if handler:
            return handler(args)
        return {"error": f"Method not found: {method}"}
    return _fn


def register_core_skills(executor: SkillExecutor, dispatcher: ToolDispatcher) -> None:
    """注册内置 Agent 可用的所有 Skills。"""

    # ═══════════════════════════════════════
    # 文档生成
    # ═══════════════════════════════════════

    executor.register(SkillDefinition(
        name="skill_generate_arch_overview",
        description="生成项目架构总览文档: 整体结构、L0 社区、关键依赖",
        steps=[
            SkillStepDef(name="get_communities", fn=_call(dispatcher, "_handle_community")),
            SkillStepDef(name="get_overview", fn=_call(dispatcher, "_handle_arch_overview")),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "edge_type": {"type": "string", "default": "INCLUDE"},
                "focus": {"type": "string", "default": "overview"},
            },
        },
    ))

    executor.register(SkillDefinition(
        name="skill_analyze_community",
        description="分析单个社区: 结构、Hub、角色、边界原因",
        steps=[
            SkillStepDef(name="get_detail", fn=_call(dispatcher, "_handle_community_detail")),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "comm_id": {"type": "string"},
            },
            "required": ["comm_id"],
        },
    ))

    # ═══════════════════════════════════════
    # 图生成
    # ═══════════════════════════════════════

    executor.register(SkillDefinition(
        name="skill_fix_mermaid",
        description="验证并修正 Mermaid 图语法",
        steps=[],
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
            },
            "required": ["code"],
        },
    ))

    executor.register(SkillDefinition(
        name="skill_fix_plantuml",
        description="验证并修正 PlantUML 图语法",
        steps=[],
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
            },
            "required": ["code"],
        },
    ))

    executor.register(SkillDefinition(
        name="skill_fix_diagram",
        description="通用图验证+修正: 语法检查 → 自动修正 → 再验证 (最多2轮)",
        steps=[
            SkillStepDef(name="validate", fn=_call(dispatcher, "_handle_quality_inspect")),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "type": {"type": "string", "enum": ["mermaid", "plantuml"]},
            },
            "required": ["code", "type"],
        },
    ))

    # ═══════════════════════════════════════
    # 架构学习/设计 (P0)
    # ═══════════════════════════════════════

    executor.register(SkillDefinition(
        name="skill_explain_arch_pattern",
        description="解释社区检测结果背后的成因: 为什么这些符号形成一个社区、边界由什么决定、在整体中的角色",
        steps=[
            SkillStepDef(name="get_detail", fn=_call(dispatcher, "_handle_community_detail")),
            SkillStepDef(name="get_overview", fn=_call(dispatcher, "_handle_arch_overview")),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "comm_id": {"type": "string"},
            },
            "required": ["comm_id"],
        },
    ))

    executor.register(SkillDefinition(
        name="skill_compare_arch",
        description="对比两个版本的架构差异，分析演化趋势和环境方向",
        steps=[
            SkillStepDef(name="get_diff", fn=_call(dispatcher, "_handle_diff")),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "from_commit": {"type": "string"},
                "to_commit": {"type": "string"},
            },
            "required": ["from_commit"],
        },
    ))

    executor.register(SkillDefinition(
        name="skill_recommend_refactor",
        description="基于架构分析给出具体重构建议: Hub过载/循环依赖/边界问题",
        steps=[
            SkillStepDef(name="inspect", fn=_call(dispatcher, "_handle_quality_inspect")),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "community_id": {"type": "string"},
                "max_suggestions": {"type": "number", "default": 5},
            },
        },
    ))

    # ═══════════════════════════════════════
    # 架构学习/设计 (P1)
    # ═══════════════════════════════════════

    executor.register(SkillDefinition(
        name="skill_validate_arch_impact",
        description="预测新增/修改模块对架构的影响: 社区归属、循环依赖风险",
        steps=[],
        input_schema={
            "type": "object",
            "properties": {
                "target_file": {"type": "string"},
            },
            "required": ["target_file"],
        },
    ))

    executor.register(SkillDefinition(
        name="skill_detect_arch_drift",
        description="检测项目架构是否偏离历史模式或预期结构",
        steps=[
            SkillStepDef(name="get_diff", fn=_call(dispatcher, "_handle_diff")),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "recent_commits": {"type": "number", "default": 10},
            },
        },
    ))

    # ═══════════════════════════════════════
    # 批量编排
    # ═══════════════════════════════════════

    executor.register(SkillDefinition(
        name="skill_batch_analyze_communities",
        description=(
            "批量分析所有 L0 社区: 并发分析 → 统一命名 → 组装总览 → 生成图。"
            "内置并发控制 + 进度上报 + 错误重试。"
        ),
        steps=[
            SkillStepDef(name="get_communities", fn=_call(dispatcher, "_handle_community")),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "edge_type": {"type": "string", "default": "INCLUDE"},
                "max_concurrency": {"type": "number", "default": 3},
            },
        },
    ))

    # ═══════════════════════════════════════
    # 会话追踪
    # ═══════════════════════════════════════

    executor.register(SkillDefinition(
        name="skill_track_ai_session",
        description="完整 AI 会话追踪: 开始 → 监控 → 分析变更 → 生成摘要",
        steps=[
            SkillStepDef(name="get_diff", fn=_call(dispatcher, "_handle_diff")),
            SkillStepDef(name="get_session", fn=_call(dispatcher, "_handle_session_summary")),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "tag": {"type": "string", "default": ""},
            },
        },
    ))

    executor.register(SkillDefinition(
        name="skill_audit_changes",
        description="审计代码变更质量: 检查架构风险、反模式",
        steps=[
            SkillStepDef(name="inspect", fn=_call(dispatcher, "_handle_quality_inspect")),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
            },
        },
    ))
