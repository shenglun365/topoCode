"""Skills — Web AI 对话的可组合能力单元

每个 Skill 是一组相关工具 + 上下文提示的集合。
UI 层可列出所有 Skills，用户按需启用/禁用，LLM 的 function calling 列表随之变化。
"""

from __future__ import annotations

import json
import os
import sys as _sys
from dataclasses import dataclass, field
from typing import Optional

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_plugins_dir = os.path.join(_project_root, "plugins")
if _plugins_dir not in _sys.path:
    _sys.path.insert(0, _plugins_dir)

from reports.web_tools import get_web_tool_definitions


@dataclass
class Skill:
    name: str
    title: str
    description: str
    icon: str
    tools: list[str]
    context_prompt: str
    default: bool = False


# ==================== 预置 Skills ====================

BUILTIN_SKILLS: dict[str, Skill] = {
    "project_browser": Skill(
        name="project_browser",
        title="项目浏览",
        description="浏览已分析的项目和任务",
        icon="📁",
        tools=["web_list_projects", "web_get_project", "web_get_task_list"],
        context_prompt="用户可以浏览已分析的项目和任务。",
        default=True,
    ),
    "architecture_explorer": Skill(
        name="architecture_explorer",
        title="架构探索",
        description="浏览社区层级、查看社区分析详情和结构图",
        icon="🏗",
            tools=[
                "web_get_architecture_overview",
                "web_get_community_tree",
                "web_get_community_detail",
                "web_get_community_graph",
                "web_set_session_title",
                "web_search_conversation_history",
            ],
        context_prompt=(
            "项目架构按社区层级组织（L0-L5），"
            "用户可以查询各层级的社区详情、子图结构和组件关系。"
        ),
        default=True,
    ),
    "source_reader": Skill(
        name="source_reader",
        title="源码阅读",
        description="读取源码文件和文件摘要",
        icon="📄",
        tools=["web_read_file", "web_get_file_summary", "web_get_community_files"],
        context_prompt=(
            "用户可以读取项目源码文件和文件摘要。"
            "查询文件内容时，优先使用 web_get_file_summary 获取预摘要（速度最快）；"
            "摘要信息不足时，使用 web_read_file 查看文件结构概览（符号名+行号）；"
            "如需阅读具体代码片段，使用 web_read_file_lines 按行号范围读取。"
        ),
        default=True,
    ),
    "symbol_analyzer": Skill(
        name="symbol_analyzer",
        title="符号分析",
        description="搜索符号、查看定义和调用关系",
        icon="🔍",
        tools=["web_search_symbols", "web_get_symbol_detail", "web_get_call_chain"],
        context_prompt=(
            "用户可以搜索项目中的符号（函数/类/方法），"
            "查看符号的详细定义和调用链。"
        ),
        default=False,
    ),
    "knowledge_keeper": Skill(
        name="knowledge_keeper",
        title="知识归档",
        description="管理对话中产生的分析结论（搜索由 web_search_knowledge 统一提供）",
        icon="💾",
        tools=[
            "web_save_archive",
            "web_list_archives",
            "web_delete_archive",
            "web_update_archive",
        ],
        context_prompt="用户可以保存和管理历史归档知识。知识搜索请使用 web_search_knowledge。",
        default=False,
    ),
    "conversation_analyst": Skill(
        name="conversation_analyst",
        title="会话分析",
        description="检索、分析和对比历史对话记录",
        icon="💬",
        tools=[
            "web_list_sessions",
            "web_get_session_info",
            "web_search_across_sessions",
            "web_get_session_messages",
            "web_summarize_session",
            "web_extract_topics",
            "web_compare_sessions",
        ],
        context_prompt=(
            "用户可以检索历史对话记录，对多个会话进行搜索、摘要和对比分析。"
            "可以获取指定会话的全部消息，提取讨论主题，生成结构化摘要。"
        ),
        default=True,
    ),
    "knowledge_manager": Skill(
        name="knowledge_manager",
        title="知识库",
        description="统一搜索用户存档文档、对话归档、架构分析报告等知识内容",
        icon="📄",
        tools=[
            "web_search_knowledge",
        ],
        context_prompt=(
            "你可以使用 web_search_knowledge 统一搜索知识库，结果按类型区分：\n"
            "- user_doc：用户手动保存的笔记/文章\n"
            "- archive：对话中归档的结论片段\n"
            "- community_analysis：LLM 对架构组件的分析报告（需指定项目ID）\n"
            "- report：项目整体架构概览文档（需指定项目ID）\n"
            "注意：知识库文档是用户手动保存或系统自动生成的内容，与实时查询的项目数据分析结果不同。"
        ),
        default=True,
    ),
}


class SkillRegistry:
    """Skills 注册表，管理预置 + 自定义 Skills"""

    def __init__(self, skills: Optional[dict[str, Skill]] = None):
        self._skills = dict(BUILTIN_SKILLS)
        if skills:
            self._skills.update(skills)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_all(self) -> list[Skill]:
        return list(self._skills.values())

    def list_defaults(self) -> list[str]:
        return [s.name for s in self._skills.values() if s.default]

    def collect_tool_names(self, active_skills: list[str]) -> list[str]:
        """收集 active_skills 的工具名列表（字符串，传给 provider.chat_stream）"""
        names: list[str] = []
        seen: set[str] = set()
        for sk_name in active_skills:
            sk = self._skills.get(sk_name)
            if sk:
                for t in sk.tools:
                    if t not in seen:
                        seen.add(t)
                        names.append(t)
        return names

    def collect_tools(self, active_skills: list[str]) -> list[dict]:
        """收集 active_skills 的全部工具定义（OpenAI 格式）"""
        return get_web_tool_definitions(self.collect_tool_names(active_skills))

    def collect_context(self, active_skills: list[str]) -> str:
        """收集 active_skills 的系统提示片段"""
        parts = []
        for sk_name in active_skills:
            sk = self._skills.get(sk_name)
            if sk and sk.context_prompt:
                parts.append(sk.context_prompt)
        return "\n".join(parts) if parts else ""

    def collect_tool_descriptions(self, active_skills: list[str]) -> str:
        """收集 active_skills 的工具名+用途描述（给 LLM 参考，避免猜测工具名）"""
        parts = []
        for sk_name in active_skills:
            sk = self._skills.get(sk_name)
            if sk and sk.tools:
                parts.append(f"- {sk.title}（{sk.description}）: {', '.join(sk.tools)}")
        return "\n".join(parts)

    def to_frontend_list(self) -> list[dict]:
        """返回前端可展示的 Skills 列表"""
        return [
            {
                "name": s.name,
                "title": s.title,
                "description": s.description,
                "icon": s.icon,
                "tools": s.tools,
                "default": s.default,
            }
            for s in self._skills.values()
        ]


# 全局单例
_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
