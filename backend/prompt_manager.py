"""Prompt 模板管理器 — 模板 CRUD + 渲染 + 内置模板

支持三种模式:
  - chat: 对话模式（完整文本流式输出）
  - tools: Tools Calling 模式（模型按需调用工具）
  - structured: 结构化输出模式（JSON Schema 校验）
"""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlite_ctx import MultiDBManager

logger = logging.getLogger(__name__)


def _make_id() -> str:
    return uuid.uuid4().hex[:12]


# ==================== 内置模板定义 ====================

BUILTIN_TEMPLATES: List[Dict[str, Any]] = [
    # ===== 对话模式 (chat) =====
    {
        "id": "src_to_pseudocode",
        "name": "源码转伪码",
        "mode": "chat",
        "module_type": "project_resource",
        "category": "解析",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码压缩助手。用户会提供一段较长的代码，请将其压缩为简洁的伪码，"
            "保留核心逻辑和关键步骤。用中文回答。只输出伪码，不要额外解释。"
        ),
        "user_prompt_template": (
            "请将以下 {language} 代码压缩为伪码（保留核心逻辑）：\n\n"
            "```{language}\n{code}\n```\n\n"
            "只保留核心逻辑，用简洁的中文伪码表示。"
        ),
        "variables_json": json.dumps([
            {"name": "language", "type": "string", "description": "编程语言", "required": True},
            {"name": "code", "type": "string", "description": "源代码", "required": True},
        ]),
    },
    {
        "id": "func_summary",
        "name": "程序功能概要",
        "mode": "chat",
        "module_type": "project_resource",
        "category": "摘要",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个专业的代码分析助手。请阅读以下代码文件，概述其整体功能和结构。"
            "用中文回答，层次分明：1. 文件用途 2. 核心类/函数 3. 关键逻辑。"
        ),
        "user_prompt_template": (
            "## 文件: {filePath}\n"
            "## 语言: {language}\n\n"
            "```{language}\n{code}\n```\n\n"
            "请概述这个文件的功能和结构。"
        ),
        "variables_json": json.dumps([
            {"name": "filePath", "type": "string", "description": "文件路径", "required": True},
            {"name": "language", "type": "string", "description": "编程语言", "required": True},
            {"name": "code", "type": "string", "description": "源代码", "required": True},
        ]),
    },
    {
        "id": "arch_analysis",
        "name": "架构深度解析",
        "mode": "tools",
        "module_type": "project_analysis",
        "category": "分析",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码架构分析专家。用户提供项目概要信息（文件名、类名、节点和边的名称列表），"
            "你需要分析架构模式、依赖关系和潜在问题。\n\n"
            "重要约束：上下文容量有限，不要一次性请求所有文件内容。"
            "先给出整体架构概览，然后使用提供的工具按需获取关键文件/符号的详细信息。"
            "每次只获取最关键的 2-3 个符号，分析后再决定是否需要更多。"
        ),
        "user_prompt_template": (
            "## 项目: {projectName}\n"
            "## 语言: {language}\n\n"
            "### 文件列表 (部分)\n{fileList}\n\n"
            "### 节点示例 (前 50 个)\n{nodeNames}\n\n"
            "### 边示例 (前 50 个)\n{edgeNames}\n\n"
            "请分析这个项目的架构。先用工具获取关键文件的详细信息，然后给出架构概览。"
        ),
        "variables_json": json.dumps([
            {"name": "projectName", "type": "string", "description": "项目名称", "required": True},
            {"name": "language", "type": "string", "description": "编程语言", "required": True},
            {"name": "fileList", "type": "string", "description": "文件列表 (一行一个)", "required": False},
            {"name": "nodeNames", "type": "string", "description": "节点名称列表", "required": False},
            {"name": "edgeNames", "type": "string", "description": "边名称列表", "required": False},
        ]),
        "tools_json": json.dumps(["get_file_content", "get_symbol_detail", "search_symbols", "get_edge_detail"]),
        "tool_strategy": "auto",
    },
    {
        "id": "doc_qa",
        "name": "文档问答",
        "mode": "chat",
        "module_type": "knowledge_base",
        "category": "问答",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个知识库助手。根据用户提供的文档内容和问题，给出准确、简洁的回答。"
            "如果文档中没有相关信息，请明确说明。用中文回答。"
        ),
        "user_prompt_template": (
            "## 文档: {docTitle}\n\n"
            "{docContent}\n\n"
            "## 问题\n{question}"
        ),
        "variables_json": json.dumps([
            {"name": "docTitle", "type": "string", "description": "文档标题", "required": True},
            {"name": "docContent", "type": "string", "description": "文档内容", "required": True},
            {"name": "question", "type": "string", "description": "用户问题", "required": True},
        ]),
    },
    {
        "id": "doc_organize",
        "name": "文档梳理",
        "mode": "chat",
        "module_type": "knowledge_base",
        "category": "整理",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个文档整理助手。根据用户提供的原始文档内容，"
            "提取关键信息，整理为结构化的摘要。用中文回答。"
        ),
        "user_prompt_template": (
            "## 原始文档\n\n{docContent}\n\n"
            "请整理该文档：1. 核心主题 2. 关键要点 (3-5 个) 3. 技术术语表 4. 建议的分类标签"
        ),
        "variables_json": json.dumps([
            {"name": "docContent", "type": "string", "description": "文档内容", "required": True},
        ]),
    },
    {
        "id": "doc_parse",
        "name": "文档解析",
        "mode": "chat",
        "module_type": "knowledge_base",
        "category": "解析",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个文档解析助手。从文档中提取结构化信息，"
            "包括：关键概念、API 引用、代码示例、外部链接。用中文回答。"
        ),
        "user_prompt_template": (
            "## 文档\n\n{docContent}\n\n"
            "请解析并提取：1. 关键概念 2. API/SDK 引用 3. 代码示例 4. 外部引用链接"
        ),
        "variables_json": json.dumps([
            {"name": "docContent", "type": "string", "description": "文档内容", "required": True},
        ]),
    },
    {
        "id": "agent_chat",
        "name": "Agent 对话",
        "mode": "chat",
        "module_type": "ai_assistant",
        "category": "通用",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个 AI 编程助手 (TopoOne AI Assistant)，集成在源码架构分析工具中。\n"
            "你的能力包括：\n"
            "1. 代码架构分析 — 分析项目结构、依赖关系、调用链路\n"
            "2. 知识库问答 — 基于项目文档回答技术问题\n"
            "3. 设计辅助 — 帮助设计 API、模块划分、重构方案\n"
            "4. 代码解释 — 解释函数/类/模块的功能和实现\n\n"
            "请用中文回答，保持专业简洁。"
        ),
        "user_prompt_template": "{question}",
        "variables_json": json.dumps([
            {"name": "question", "type": "string", "description": "用户问题", "required": True},
        ]),
    },

    # ===== 结构化输出模式 (structured) =====
    {
        "id": "community_name",
        "name": "组件命名",
        "mode": "structured",
        "module_type": "project_analysis",
        "category": "命名",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码组件命名助手。根据提供的节点和边的统计信息，"
            "为组件生成一个简洁的中文名称（不超过 10 个字）。返回 JSON 格式。"
        ),
        "user_prompt_template": (
            "节点数: {nodeCount}, 边数: {edgeCount}\n"
            "节点列表: {nodeNames}"
        ),
        "output_schema_json": json.dumps({
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 10, "description": "组件中文名称"},
                "category": {
                    "type": "string",
                    "enum": ["核心逻辑", "数据访问", "接口定义", "配置管理", "测试", "工具类", "其他"],
                    "description": "组件分类"
                },
                "summary": {"type": "string", "maxLength": 30, "description": "一句话概述"},
            },
            "required": ["name", "category"],
        }),
        "output_example": json.dumps({"name": "HTTP请求处理", "category": "核心逻辑", "summary": "负责处理HTTP请求的解析和响应生成"}),
        "variables_json": json.dumps([
            {"name": "nodeCount", "type": "integer", "description": "节点数量", "required": True},
            {"name": "edgeCount", "type": "integer", "description": "边数量", "required": True},
            {"name": "nodeNames", "type": "string", "description": "节点名称列表", "required": True},
        ]),
    },
    {
        "id": "symbol_summary",
        "name": "符号摘要",
        "mode": "structured",
        "module_type": "project_analysis",
        "category": "摘要",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码符号摘要助手。为指定的代码符号生成结构化的摘要信息。"
            "返回 JSON 格式，严格遵守 schema。"
        ),
        "user_prompt_template": (
            "## 符号: {symbolName}\n"
            "## 类型: {symbolType}\n"
            "## 文件: {filePath}\n\n"
            "```{language}\n{codeSnippet}\n```"
        ),
        "output_schema_json": json.dumps({
            "type": "object",
            "properties": {
                "summary": {"type": "string", "maxLength": 80, "description": "功能摘要（1-2句话）"},
                "purpose": {"type": "string", "maxLength": 40, "description": "场景用途"},
                "logic": {"type": "string", "maxLength": 60, "description": "实现逻辑关键词"},
                "params": {"type": "array", "items": {"type": "string"}, "description": "关键参数列表"},
                "returns": {"type": "string", "maxLength": 40, "description": "返回值说明"},
            },
            "required": ["summary", "purpose", "logic"],
        }),
        "output_example": json.dumps({
            "summary": "处理HTTP请求并将其路由到对应的处理器",
            "purpose": "Web请求分发",
            "logic": "责任链+反射调用+路径匹配",
            "params": ["HttpRequest request", "HttpResponse response"],
            "returns": "void",
        }),
        "variables_json": json.dumps([
            {"name": "symbolName", "type": "string", "description": "符号名称", "required": True},
            {"name": "symbolType", "type": "string", "description": "符号类型 (function/class/method)", "required": True},
            {"name": "filePath", "type": "string", "description": "文件路径", "required": False},
            {"name": "language", "type": "string", "description": "编程语言", "required": True},
            {"name": "codeSnippet", "type": "string", "description": "代码片段", "required": True},
        ]),
    },
    {
        "id": "code_keywords",
        "name": "代码关键词摘要",
        "mode": "structured",
        "module_type": "project_analysis",
        "category": "摘要",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码关键词提取助手。为代码或文档生成结构化的关键词摘要。"
            "返回 JSON 格式，严格遵守 schema。"
        ),
        "user_prompt_template": (
            "## 来源: {sourceType} — {sourceName}\n\n"
            "```\n{content}\n```"
        ),
        "output_schema_json": json.dumps({
            "type": "object",
            "properties": {
                "scenario": {"type": "string", "maxLength": 40, "description": "场景摘要"},
                "function": {"type": "string", "maxLength": 60, "description": "功能摘要"},
                "implementation": {"type": "string", "maxLength": 60, "description": "实现逻辑关键词"},
                "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 5, "description": "分类标签"},
            },
            "required": ["scenario", "function", "implementation"],
        }),
        "output_example": json.dumps({
            "scenario": "依赖注入容器初始化",
            "function": "扫描类路径，创建Bean定义，管理Bean生命周期",
            "implementation": "反射+注解处理+工厂模式+单例缓存",
            "tags": ["DI容器", "Spring", "Bean管理"],
        }),
        "variables_json": json.dumps([
            {"name": "sourceType", "type": "string", "description": "来源类型 (code/doc)", "required": True},
            {"name": "sourceName", "type": "string", "description": "来源名称", "required": True},
            {"name": "content", "type": "string", "description": "内容", "required": True},
        ]),
    },

    # ===== 边解释模板 =====
    {
        "id": "edge_explain",
        "name": "边关系解释",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "source_code",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个专业的代码分析助手。用户会提供一个代码中的调用关系或依赖关系。"
            "请解释这个关系的含义和作用。用中文回答。"
        ),
        "user_prompt_template": (
            "## 边信息\n"
            "- 类型: {edgeTypeLabel}\n"
            "- 源: {source}\n"
            "- 目标: {target}\n"
            "{callSite}"
            "{includePath}"
            "{isSystem}"
            "\n请解释这个关系。"
        ),
        "variables_json": json.dumps([
            {"name": "edgeTypeLabel", "type": "string", "description": "边类型标签（调用关系/依赖关系）", "required": True},
            {"name": "source", "type": "string", "description": "源节点名", "required": True},
            {"name": "target", "type": "string", "description": "目标节点名", "required": True},
            {"name": "callSite", "type": "string", "description": "调用位置信息（可选，含前导换行）", "required": False},
            {"name": "includePath", "type": "string", "description": "包含路径信息（可选，含前导换行）", "required": False},
            {"name": "isSystem", "type": "string", "description": "系统头文件标记（可选，含前导换行）", "required": False},
        ]),
    },

    # ===== 前端迁移模板 (community / source_code) =====
    {
        "id": "community_architecture",
        "name": "组件架构说明",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "community",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个软件架构师。请根据提供的代码组件结构信息,生成结构化的架构说明文档。\n"
            "输出格式要求:\n"
            "- 使用 Markdown 标题层级组织\n"
            "- 包含: 概述、模块划分、核心流程、依赖关系、设计评价\n"
            "- 每个模块用表格列出关键节点\n"
            "- 使用 Mermaid 图表展示模块关系"
        ),
        "user_prompt_template": (
            "## 组件结构数据\n"
            "- 组件ID: {commId}\n"
            "- 节点数: {nodeCount}\n"
            "- 边数: {edgeCount}\n\n"
            "## 节点列表\n"
            "{nodeList}\n\n"
            "## 边关系\n"
            "{edgeList}\n\n"
            "{detailNodes}\n\n"
            "请生成结构化的架构说明文档。"
        ),
        "variables_json": json.dumps([
            {"name": "commId", "type": "string", "description": "组件ID", "required": True},
            {"name": "nodeCount", "type": "integer", "description": "节点数", "required": True},
            {"name": "edgeCount", "type": "integer", "description": "边数", "required": True},
            {"name": "nodeList", "type": "string", "description": "节点列表", "required": True},
            {"name": "edgeList", "type": "string", "description": "边关系列表", "required": True},
            {"name": "detailNodes", "type": "string", "description": "详细节点信息", "required": False},
        ]),
    },
    {
        "id": "community_business",
        "name": "业务场景适配分析",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "community",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个业务架构分析师。请根据提供的代码组件结构,分析:\n"
            "1. 这段代码可能适配的业务场景\n"
            "2. 核心业务流程\n"
            "3. 可扩展性评估\n"
            "4. 可能的优化方向\n"
            "用中文回答,结合软件工程最佳实践。"
        ),
        "user_prompt_template": (
            "## 组件结构\n"
            "- 组件ID: {commId}\n"
            "- 节点数: {nodeCount}\n"
            "- 边数: {edgeCount}\n\n"
            "## 节点列表\n"
            "{nodeList}\n\n"
            "## 边关系\n"
            "{edgeList}\n\n"
            "{detailNodes}\n\n"
            "请分析这个组件适配的业务场景。"
        ),
        "variables_json": json.dumps([
            {"name": "commId", "type": "string", "description": "组件ID", "required": True},
            {"name": "nodeCount", "type": "integer", "description": "节点数", "required": True},
            {"name": "edgeCount", "type": "integer", "description": "边数", "required": True},
            {"name": "nodeList", "type": "string", "description": "节点列表", "required": True},
            {"name": "edgeList", "type": "string", "description": "边关系列表", "required": True},
            {"name": "detailNodes", "type": "string", "description": "详细节点信息", "required": False},
        ]),
    },
    {
        "id": "community_pseudocode",
        "name": "组件伪代码生成",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "community",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码抽象专家。请根据提供的代码组件结构信息,生成该组件核心逻辑的伪代码。\n"
            "要求:\n"
            "- 保留核心算法流程和关键判断逻辑\n"
            "- 用中文注释说明每个步骤\n"
            "- 忽略具体语法细节,关注逻辑结构"
        ),
        "user_prompt_template": (
            "## 组件结构\n"
            "- 组件ID: {commId}\n"
            "- 节点数: {nodeCount}\n\n"
            "## 节点列表\n"
            "{nodeList}\n\n"
            "## 边关系\n"
            "{edgeList}\n\n"
            "{detailNodes}\n\n"
            "请生成这个组件核心逻辑的伪代码。"
        ),
        "variables_json": json.dumps([
            {"name": "commId", "type": "string", "description": "组件ID", "required": True},
            {"name": "nodeCount", "type": "integer", "description": "节点数", "required": True},
            {"name": "nodeList", "type": "string", "description": "节点列表", "required": True},
            {"name": "edgeList", "type": "string", "description": "边关系列表", "required": True},
            {"name": "detailNodes", "type": "string", "description": "详细节点信息", "required": False},
        ]),
    },
    {
        "id": "source_explain",
        "name": "源码功能说明",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "source_code",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码解释专家。用户会提供一段源码及其上下文信息。请解释:\n"
            "1. 这段代码实现什么功能\n"
            "2. 核心逻辑流程\n"
            "3. 关键数据结构和算法\n"
            "4. 可能的边界条件处理\n"
            "用中文回答,保持简洁专业。"
        ),
        "user_prompt_template": (
            "## 代码信息\n"
            "- 文件路径: {filePath}\n"
            "- 文件名: {fileName}\n"
            "- 语言: {language}\n"
            "{symbolInfo}"
            "\n## 代码内容\n"
            "```{language}\n"
            "{codeContent}\n"
            "```\n\n"
            "请解释这段代码的功能。"
        ),
        "variables_json": json.dumps([
            {"name": "filePath", "type": "string", "description": "文件路径", "required": True},
            {"name": "fileName", "type": "string", "description": "文件名", "required": True},
            {"name": "language", "type": "string", "description": "编程语言", "required": True},
            {"name": "codeContent", "type": "string", "description": "代码内容", "required": True},
            {"name": "symbolInfo", "type": "string", "description": "符号信息（可选，含前导换行，如\"- 符号名: xxx\\n- 符号类型: function\"）", "required": False},
        ]),
    },
    {
        "id": "source_summary",
        "name": "源码摘要",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "source_code",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码摘要专家。请为提供的源码生成简洁的功能摘要。\n"
            "要求:\n"
            "- 不超过 200 字\n"
            "- 说明核心功能和关键接口\n"
            "- 适合用作文档索引"
        ),
        "user_prompt_template": (
            "## 文件: {filePath}\n\n"
            "```{language}\n"
            "{codeContent}\n"
            "```\n\n"
            "请生成这段代码的功能摘要。"
        ),
        "variables_json": json.dumps([
            {"name": "filePath", "type": "string", "description": "文件路径", "required": True},
            {"name": "language", "type": "string", "description": "编程语言", "required": True},
            {"name": "codeContent", "type": "string", "description": "代码内容", "required": True},
        ]),
    },
    {
        "id": "source_pseudocode",
        "name": "源码伪代码",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "source_code",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码抽象专家。请将提供的源码转换为简洁的伪代码,保留核心逻辑和关键步骤。\n"
            "要求:\n"
            "- 使用中文关键字和注释\n"
            "- 保留循环、条件、函数调用等核心结构\n"
            "- 省略具体语法细节"
        ),
        "user_prompt_template": (
            "## 文件: {filePath}\n\n"
            "```{language}\n"
            "{codeContent}\n"
            "```\n\n"
            "请将这段代码转换为伪代码。"
        ),
        "variables_json": json.dumps([
            {"name": "filePath", "type": "string", "description": "文件路径", "required": True},
            {"name": "language", "type": "string", "description": "编程语言", "required": True},
            {"name": "codeContent", "type": "string", "description": "代码内容", "required": True},
        ]),
    },

    # ===== 报告生成流水线模板 (report_pipeline) =====
    {
        "id": "report_project_summary",
        "name": "报告-项目概要",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "report_pipeline",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个项目文档生成助手。请根据提供的项目信息生成项目概要。\n"
            "输出 Markdown 格式，包含:\n"
            "1. 项目名称和语言\n"
            "2. 文件数量和目录结构\n"
            "3. 主要技术栈\n"
            "4. README 摘要\n"
            "5. 依赖管理工具和库\n"
            "用中文回答。"
        ),
        "user_prompt_template": (
            "## 项目信息\n"
            "- 项目名称: {projectName}\n"
            "- 主要语言: {language}\n"
            "- 文件总数: {fileCount}\n"
            "- 根目录: {rootPath}\n\n"
            "## 文件分布\n"
            "{fileDistribution}\n\n"
            "## README 摘要\n"
            "{readmeContent}\n\n"
            "## 依赖信息\n"
            "{dependencySummary}\n\n"
            "## 核心文件摘要\n"
            "{fileSummaries}\n\n"
            "请生成项目概要文档。"
        ),
        "variables_json": json.dumps([
            {"name": "projectName", "type": "string", "description": "项目名称", "required": True},
            {"name": "language", "type": "string", "description": "主要编程语言", "required": True},
            {"name": "fileCount", "type": "string", "description": "文件总数", "required": True},
            {"name": "rootPath", "type": "string", "description": "项目根路径", "required": False},
            {"name": "fileDistribution", "type": "string", "description": "文件分布统计", "required": False},
            {"name": "readmeContent", "type": "string", "description": "README 摘要", "required": False},
            {"name": "dependencySummary", "type": "string", "description": "依赖管理信息", "required": False},
            {"name": "fileSummaries", "type": "string", "description": "核心文件摘要", "required": False},
        ]),
    },
    {
        "id": "report_arch_decomposition",
        "name": "报告-架构分解",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "report_pipeline",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个软件架构分析专家。请根据组件分析数据分解项目架构层次。\n"
            "输出 Markdown 格式，包含:\n"
            "1. 架构层次划分\n"
            "2. 各层次的核心职责\n"
            "3. Mermaid graph TD 架构图\n"
            "用中文回答。Mermaid 代码放在 ```mermaid 代码块中。"
        ),
        "user_prompt_template": (
            "## 组件分组数据\n"
            "{communitySummary}\n\n"
            "请根据以上组件分析数据:\n"
            "1. 识别项目的主要架构层次（如：核心逻辑层、数据访问层、接口层等）\n"
            "2. 将组件分组映射到各层次\n"
            "3. 生成 Mermaid graph TD 架构图\n"
            "4. 说明各层次之间的依赖关系"
        ),
        "variables_json": json.dumps([
            {"name": "communitySummary", "type": "string", "description": "组件分组摘要", "required": True},
        ]),
    },
    {
        "id": "report_core_modules",
        "name": "报告-核心模块说明",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "report_pipeline",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码分析专家。请根据组件节点和调用关系,详细说明核心模块的功能和职责。\n"
            "输出 Markdown 格式，每个模块包含:\n"
            "1. 模块名称和分类\n"
            "2. 核心功能说明\n"
            "3. 关键类/函数列表（表格形式）\n"
            "4. 内部调用关系\n"
            "用中文回答。"
        ),
        "user_prompt_template": (
            "## 核心组件分组\n"
            "{topCommunities}\n\n"
            "请详细分析以上 {count} 个组件的功能:\n"
            "1. 每个组件的业务/技术职责\n"
            "2. 关键符号（类、函数）及其作用\n"
            "3. 组件内部的高频调用关系模式"
        ),
        "variables_json": json.dumps([
            {"name": "topCommunities", "type": "string", "description": "核心组件分组详情", "required": True},
            {"name": "count", "type": "string", "description": "组件数量", "required": True},
        ]),
    },
    {
        "id": "report_dependency_analysis",
        "name": "报告-依赖与调用分析",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "report_pipeline",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个依赖分析专家。请根据跨组件调用和依赖数据,分析模块间的耦合关系。\n"
            "输出 Markdown 格式，包含:\n"
            "1. 跨组件调用统计\n"
            "2. 核心依赖链路\n"
            "3. 循环依赖检测（如有）\n"
            "4. 架构质量评估\n"
            "用中文回答。"
        ),
        "user_prompt_template": (
            "## 跨组件调用/依赖数据\n"
            "{crossCommunityEdges}\n\n"
            "请分析:\n"
            "1. 哪些组件之间存在最多的交互（高耦合）\n"
            "2. 是否存在单向依赖违反或循环依赖\n"
            "3. 核心数据流向\n"
            "4. 给出架构改进建议"
        ),
        "variables_json": json.dumps([
            {"name": "crossCommunityEdges", "type": "string", "description": "跨组件边数据", "required": True},
        ]),
    },
    {
        "id": "report_final_assembly",
        "name": "报告-最终整合",
        "mode": "chat",
        "module_type": "project_analysis",
        "category": "report_pipeline",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个技术文档编辑专家。请将多个分析片段整合为一份完整、连贯的架构分析报告。\n"
            "输出为标准的 Markdown 文档，要求:\n"
            "1. 保持各部分的逻辑衔接\n"
            "2. 去除重复内容\n"
            "3. 统一术语和风格\n"
            "4. 生成的 Mermaid/PlantUML 代码块保留原始格式\n"
            "5. 添加目录和章节编号"
        ),
        "user_prompt_template": (
            "请将以下分析内容整合为一份完整的架构分析报告：\n\n"
            "---\n"
            "## 步骤1: 项目概要\n"
            "{step1}\n\n"
            "---\n"
            "## 步骤2: 架构分解\n"
            "{step2}\n\n"
            "---\n"
            "## 步骤3: 核心模块说明\n"
            "{step3}\n\n"
            "---\n"
            "## 步骤4: 依赖与调用分析\n"
            "{step4}\n\n"
            "---\n"
            "请整合以上内容为一份完整的 Markdown 报告，添加文档标题、目录和页码标记。"
        ),
        "variables_json": json.dumps([
            {"name": "step1", "type": "string", "description": "项目概要步骤输出", "required": True},
            {"name": "step2", "type": "string", "description": "架构分解步骤输出", "required": True},
            {"name": "step3", "type": "string", "description": "核心模块说明步骤输出", "required": True},
            {"name": "step4", "type": "string", "description": "依赖分析步骤输出", "required": True},
        ]),
    },

    # ===== 文件摘要模板 (structured) =====
    {
        "id": "file_summarize",
        "name": "文件摘要生成",
        "mode": "structured",
        "module_type": "project_analysis",
        "category": "report_pipeline",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码摘要专家。为提供的源码文件生成不超过 100 字的功能摘要。\n"
            "返回 JSON 格式，包含: summary, keywords (最多 5 个标签)。\n"
            "用中文回答。"
        ),
        "user_prompt_template": (
            "## 文件: {filePath}\n"
            "## 语言: {language}\n\n"
            "```{language}\n{codeContent}\n```\n\n"
            "请生成功能摘要（不超过 100 字）。"
        ),
        "output_schema_json": json.dumps({
            "type": "object",
            "properties": {
                "summary": {"type": "string", "maxLength": 100, "description": "功能摘要（不超过100字）"},
                "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 5, "description": "关键标签"},
            },
            "required": ["summary"],
        }),
        "output_example": json.dumps({"summary": "处理HTTP请求的路由分发，支持路径参数匹配和中间件链", "keywords": ["路由", "HTTP", "中间件"]}),
        "variables_json": json.dumps([
            {"name": "filePath", "type": "string", "description": "文件路径", "required": True},
            {"name": "language", "type": "string", "description": "编程语言", "required": True},
            {"name": "codeContent", "type": "string", "description": "源代码", "required": True},
        ]),
    },

    # ===== 组件分析模板 (structured — 返回名称+摘要+图表) =====
    {
        "id": "community_analyze",
        "name": "组件功能分析",
        "mode": "structured",
        "module_type": "project_analysis",
        "category": "report_pipeline",
        "is_builtin": 1,
        "system_prompt": (
            "你是一个代码架构分析专家。请根据提供的模块结构信息，分析该模块的功能和架构含义。\n"
            "注意：分析对象是代码中的一个功能模块（module/component），不是社交组件。\n"
            "返回 JSON 格式，包含 name、summary、mermaid、plantuml 四个字段。\n"
            "用中文回答。\n\n"
            "字段说明:\n"
            "- name: 模块名称（根据功能概括，不超过 20 个字），格式如「XXX模块」或「XXX组件」\n"
            "- summary: 模块功能说明（Markdown 格式，包含：核心功能说明、涉及的文件列表、内部调用关系）\n"
            "- mermaid: 用 Mermaid 语法绘制的模块内文件依赖关系结构图（graph LR 或 flowchart），"
            "展示节点间调用/依赖关系，节点标签用文件名或函数名\n"
            "- plantuml: 用 PlantUML 语法绘制的同一关系图（可选，如不擅长可省略）\n"
        ),
        "user_prompt_template": (
            "## 组件信息\n"
            "- 组件ID: {communityId}\n"
            "- 层级: {level} (L0/L1/L2)\n"
            "- 节点数: {nodeCount}\n"
            "- 边数: {edgeCount}\n\n"
            "## 节点列表（源码文件/符号）\n"
            "{nodeListWithPaths}\n\n"
            "## 边关系（调用/依赖）\n"
            "{edgeListWithDetails}\n\n"
            "{parentSummaries}\n\n"
            "请分析这个组件，返回 JSON 格式的 name、summary、mermaid、plantuml。"
        ),
        "output_schema_json": json.dumps({
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 20, "description": "组件名称（不超过20个字）"},
                "summary": {"type": "string", "description": "组件功能说明（Markdown格式，含核心功能、文件列表、调用关系）"},
                "mermaid": {"type": "string", "description": "Mermaid 代码（graph LR 或 flowchart），展示组件内文件依赖关系"},
                "plantuml": {"type": "string", "description": "PlantUML 代码，展示组件内文件依赖关系（可选）"},
            },
            "required": ["name", "summary", "mermaid"],
        }),
        "output_example": json.dumps({
            "name": "HTTP路由处理",
            "summary": "负责HTTP请求的路由分发和参数解析，包含路由注册、中间件链、路径匹配等功能。",
            "mermaid": "graph LR\\n  A[router.js] --> B[handler.js]\\n  B --> C[middleware.js]",
            "plantuml": "@startuml\\nfile router.js --> file handler.js\\n@enduml",
        }),
        "variables_json": json.dumps([
            {"name": "communityId", "type": "string", "description": "组件ID", "required": True},
            {"name": "level", "type": "string", "description": "层级 (L0/L1/L2)", "required": True},
            {"name": "nodeCount", "type": "integer", "description": "节点数", "required": True},
            {"name": "edgeCount", "type": "integer", "description": "边数", "required": True},
            {"name": "nodeListWithPaths", "type": "string", "description": "节点列表（含源码路径和扩展名）", "required": True},
            {"name": "edgeListWithDetails", "type": "string", "description": "边关系列表（显示名已去前缀）", "required": True},
            {"name": "parentSummaries", "type": "string", "description": "父组件摘要 + 项目上下文（README/依赖等）", "required": False},
        ]),
    },
]

# 内置模板 ID 集合
BUILTIN_IDS = {t["id"] for t in BUILTIN_TEMPLATES}


def _now() -> str:
    return datetime.now().isoformat()


# ==================== PromptManager 类 ====================

class PromptManager:
    """Prompt 模板管理器"""

    def __init__(self, multi_db: MultiDBManager):
        self.multi_db = multi_db
        self._init_builtins()

    def _init_builtins(self):
        """确保内置模板已插入数据库"""
        main_db = self.multi_db.main_db
        for tmpl in BUILTIN_TEMPLATES:
            existing = main_db.fetchone(
                "SELECT id FROM llm_prompt_templates WHERE id = ?", (tmpl["id"],)
            )
            if not existing:
                self._insert_template(tmpl)
                logger.info(f"[PromptManager] Builtin template '{tmpl['name']}' inserted")

    def _insert_template(self, data: Dict[str, Any]):
        main_db = self.multi_db.main_db
        main_db.execute(
            """INSERT INTO llm_prompt_templates
               (id, name, mode, module_type, category, is_builtin,
                system_prompt, user_prompt_template,
                tools_json, tool_strategy,
                output_schema_json, output_example,
                variables_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"], data["name"], data["mode"],
                data.get("module_type"), data.get("category", "general"),
                data.get("is_builtin", 0),
                data.get("system_prompt"), data.get("user_prompt_template"),
                data.get("tools_json"), data.get("tool_strategy"),
                data.get("output_schema_json"), data.get("output_example"),
                data.get("variables_json"),
                _now(), _now(),
            ),
        )
        main_db.commit()

    # ==================== CRUD ====================

    def list_templates(
        self,
        mode: Optional[str] = None,
        module_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列举模板"""
        main_db = self.multi_db.main_db
        sql = "SELECT * FROM llm_prompt_templates WHERE 1=1"
        params: list = []

        if mode:
            sql += " AND mode = ?"
            params.append(mode)
        if module_type:
            sql += " AND module_type = ?"
            params.append(module_type)
        if category:
            sql += " AND category = ?"
            params.append(category)

        sql += " ORDER BY is_builtin DESC, mode, name"
        return main_db.fetchall(sql, tuple(params)) if params else main_db.fetchall(sql)

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """获取模板详情"""
        return self.multi_db.main_db.fetchone(
            "SELECT * FROM llm_prompt_templates WHERE id = ?", (template_id,)
        )

    def create_template(
        self,
        name: str,
        mode: str,
        module_type: Optional[str] = None,
        category: str = "general",
        system_prompt: Optional[str] = None,
        user_prompt_template: Optional[str] = None,
        tools_json: Optional[str] = None,
        tool_strategy: str = "auto",
        output_schema_json: Optional[str] = None,
        output_example: Optional[str] = None,
        variables_json: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建用户自定义模板"""
        if mode not in ('chat', 'tools', 'structured'):
            raise ValueError(f"Invalid mode: {mode}")

        template_id = _make_id()
        data = {
            "id": template_id, "name": name, "mode": mode,
            "module_type": module_type, "category": category, "is_builtin": 0,
            "system_prompt": system_prompt, "user_prompt_template": user_prompt_template,
            "tools_json": tools_json, "tool_strategy": tool_strategy,
            "output_schema_json": output_schema_json, "output_example": output_example,
            "variables_json": variables_json,
        }
        self._insert_template(data)
        logger.info(f"[PromptManager] Template created: {template_id} ({name})")
        return self.get_template(template_id)

    def update_template(
        self,
        template_id: str,
        name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        user_prompt_template: Optional[str] = None,
        tools_json: Optional[str] = None,
        output_schema_json: Optional[str] = None,
        variables_json: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """更新模板（不允许修改内置模板的 mode/module_type）"""
        tmpl = self.get_template(template_id)
        if not tmpl:
            raise ValueError(f"Template not found: {template_id}")

        main_db = self.multi_db.main_db
        now = _now()

        fields = []
        params: list = []
        for key, val in [
            ("name", name), ("system_prompt", system_prompt),
            ("user_prompt_template", user_prompt_template),
            ("tools_json", tools_json), ("output_schema_json", output_schema_json),
            ("variables_json", variables_json),
        ]:
            if val is not None:
                fields.append(f"{key} = ?")
                params.append(val)

        if not fields:
            return tmpl

        fields.append("updated_at = ?")
        params.append(now)
        params.append(template_id)

        main_db.execute(
            f"UPDATE llm_prompt_templates SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
        main_db.commit()

        return self.get_template(template_id)

    def delete_template(self, template_id: str) -> Dict[str, Any]:
        """删除模板（内置模板不可删除）"""
        if template_id in BUILTIN_IDS:
            raise ValueError(f"Cannot delete builtin template: {template_id}")

        tmpl = self.get_template(template_id)
        if not tmpl:
            raise ValueError(f"Template not found: {template_id}")

        self.multi_db.main_db.execute(
            "DELETE FROM llm_prompt_templates WHERE id = ?", (template_id,)
        )
        self.multi_db.main_db.commit()
        logger.info(f"[PromptManager] Template deleted: {template_id}")
        return {'success': True}

    # ==================== 渲染 ====================

    def render(
        self,
        template_id: str,
        variables: Dict[str, Any],
    ) -> Dict[str, Any]:
        """渲染模板 → 返回 messages + mode + schema

        Returns:
            {
                'messages': [{'role': 'system', 'content': '...'}, {'role': 'user', 'content': '...'}],
                'mode': 'chat' | 'tools' | 'structured',
                'tools': [...] | None,
                'outputSchema': {...} | None,
                'templateId': '...',
                'templateName': '...',
            }
        """
        tmpl = self.get_template(template_id)
        if not tmpl:
            raise ValueError(f"Template not found: {template_id}")

        # 渲染 system prompt
        system_prompt = tmpl.get('system_prompt', '') or ''

        # 渲染 user prompt — 替换 {variable} 占位符
        user_template = tmpl.get('user_prompt_template', '') or ''
        user_prompt = self._fill_template(user_template, variables)

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]

        # tools
        tools = None
        if tmpl.get('tools_json'):
            try:
                tools = json.loads(tmpl['tools_json'])
            except json.JSONDecodeError:
                pass

        # output schema
        output_schema = None
        if tmpl.get('output_schema_json'):
            try:
                output_schema = json.loads(tmpl['output_schema_json'])
            except json.JSONDecodeError:
                pass

        return {
            'messages': messages,
            'mode': tmpl['mode'],
            'tools': tools,
            'outputSchema': output_schema,
            'templateId': tmpl['id'],
            'templateName': tmpl['name'],
        }

    def _fill_template(self, template: str, variables: Dict[str, Any]) -> str:
        """替换模板中的 {variable} 占位符"""
        result = template
        for key, val in variables.items():
            placeholder = '{' + key + '}'
            if placeholder in result:
                result = result.replace(placeholder, str(val) if val is not None else '')
        return result


