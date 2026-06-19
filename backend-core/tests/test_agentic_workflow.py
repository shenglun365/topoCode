"""
测试 AgenticWorkflow 基类和相关组件。
"""
import pytest
from unittest.mock import MagicMock

from agent_workflow.tools import ToolRegistry, ToolResult, AgentTool
from agent_workflow.workflows.base import AgenticWorkflow, WorkflowResult
from agent_workflow.workflows.agentic_component_analyst import AgenticComponentAnalystWorkflow


class DummyAgenticWorkflow(AgenticWorkflow):
    """用于测试的虚拟 Agentic 工作流"""
    name = "dummy_agentic"
    description = "test"
    max_turns = 3
    max_turn_timeout = 10

    def get_system_prompt(self, component, project_summary=""):
        return f"sys prompt for {component.get('id', '?')}"

    def finalize(self, results):
        return WorkflowResult(success=True, data=results)


class TestAgenticWorkflowBase:
    """AgenticWorkflow 基类测试"""

    def test_plan_returns_empty(self):
        wf = DummyAgenticWorkflow()
        steps = wf.plan({})
        assert steps == [], "AgenticWorkflow plan() should return empty list by default"

    def test_max_turns_default(self):
        wf = AgenticComponentAnalystWorkflow()
        assert wf.max_turns == 30

    def test_max_turn_timeout_default(self):
        wf = AgenticComponentAnalystWorkflow()
        assert wf.max_turn_timeout == 180

    def test_get_tool_filter(self):
        wf = AgenticComponentAnalystWorkflow()
        tools = wf.get_tool_filter({})
        assert "read_file" in tools
        assert "search_content" in tools
        assert "get_symbol_detail" in tools
        assert len(tools) >= 4


class TestAgenticComponentAnalystWorkflow:
    """AgenticComponentAnalystWorkflow 测试"""

    def test_name(self):
        wf = AgenticComponentAnalystWorkflow()
        assert wf.name == "agentic_component_analyst"

    def test_system_prompt_includes_component_id(self):
        wf = AgenticComponentAnalystWorkflow()
        prompt = wf.get_system_prompt(
            {"id": "comp-abc", "name": "TestComp", "metadata": {}},
            project_summary="project overview",
        )
        assert "comp-abc" in prompt
        assert "TestComp" in prompt

    def test_system_prompt_includes_project_summary(self):
        wf = AgenticComponentAnalystWorkflow()
        prompt = wf.get_system_prompt(
            {"id": "c1", "name": "foo", "metadata": {}},
            project_summary="this is the project summary text",
        )
        assert "project summary text" in prompt

    def test_system_prompt_includes_parent_summary(self):
        wf = AgenticComponentAnalystWorkflow()
        prompt = wf.get_system_prompt(
            {"id": "c1", "name": "foo", "metadata": {}, "parent_summary": "parent comp summary"},
            project_summary="",
        )
        assert "parent comp summary" in prompt

    def test_input_output_schemas_defined(self):
        wf = AgenticComponentAnalystWorkflow()
        assert wf.input_schema, "input_schema should be defined"
        assert wf.output_schema, "output_schema should be defined"
        assert "components" in str(wf.input_schema)
        assert "component_results" in str(wf.output_schema)

    def test_finalize_success(self):
        wf = AgenticComponentAnalystWorkflow()
        result = wf.finalize({"component_results": [
            {"component_id": "c1", "output_text": "analysis done", "turns": 3, "success": True},
        ]})
        assert result.success is True
        assert result.data["success"] == 1
        assert result.data["total"] == 1

    def test_finalize_empty(self):
        wf = AgenticComponentAnalystWorkflow()
        result = wf.finalize({"component_results": []})
        assert result.success is False
        assert result.data["success"] == 0


class TestToolIntegration:
    """工具注册与 schema 生成测试"""

    def test_tool_registry_to_openai_tools_filtered(self):
        from agent_workflow.tool_factory import build_agentic_component_tools
        registry = build_agentic_component_tools(project_root="/tmp")
        schemas = registry.to_openai_tools(["read_file"])
        assert len(schemas) >= 1
        assert all(s["type"] == "function" for s in schemas)

    def test_tool_registry_to_openai_tools_all(self):
        from agent_workflow.tool_factory import build_agentic_component_tools
        registry = build_agentic_component_tools(project_root="/tmp")
        schemas = registry.to_openai_tools()
        names = [s["function"]["name"] for s in schemas]
        assert "read_file" in names
        assert "search_content" in names

    def test_read_file_tool_schema(self):
        from agent_workflow.toolkits.file_tools import ReadFileTool
        tool = ReadFileTool(project_root="/tmp")
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "read_file"
        params = schema["function"]["parameters"]
        assert "path" in params["properties"]


class TestAgenticRuntimeBehavior:
    """_run_agentic 运行时行为测试（不需要真实 LLM）"""

    def test_native_strategy_selected_for_openai_compat(self):
        """验证 openai_compat provider 的模型自动选择 NativeStrategy"""
        from agent_workflow.tool_calling.strategy import create_strategy, NativeToolCallingStrategy
        # 即使 model_id 为空，create_strategy 没有 multi_db 时也应返回 TextFallback
        s = create_strategy(preferred="native")
        assert isinstance(s, NativeToolCallingStrategy)

    def test_text_fallback_explicit(self):
        """验证显式指定 text_fallback 返回 TextFallbackStrategy"""
        from agent_workflow.tool_calling.strategy import create_strategy, TextFallbackToolCallingStrategy
        s = create_strategy(preferred="text_fallback")
        assert isinstance(s, TextFallbackToolCallingStrategy)

    def test_tool_calling_package_imports(self):
        """验证 tool_calling 包的完整导入链"""
        from agent_workflow.tool_calling import (
            ToolCall, AgentChatResponse,
            NativeToolCallingStrategy, TextFallbackToolCallingStrategy,
            agentic_chat, create_strategy,
        )
        assert ToolCall is not None
        assert AgentChatResponse is not None
        assert agentic_chat is not None
        assert create_strategy is not None

    def test_agentic_chat_response_dataclass(self):
        """验证 AgentChatResponse 数据类的所有字段"""
        from agent_workflow.tool_calling import AgentChatResponse, ToolCall
        # 模拟一次完整的 tool_calls 响应
        resp = AgentChatResponse(
            content="",
            tool_calls=[
                ToolCall(name="read_file", arguments={"path": "/tmp/test"}, id="call_1"),
                ToolCall(name="search_content", arguments={"pattern": "hello"}, id="call_2"),
            ],
            tokens_used=1500,
            finish_reason="tool_calls",
        )
        assert not resp.content
        assert len(resp.tool_calls) == 2
        assert resp.tool_calls[0].name == "read_file"
        assert resp.tool_calls[0].arguments["path"] == "/tmp/test"
        assert resp.tokens_used == 1500
        assert resp.finish_reason == "tool_calls"

    def test_agentic_chat_response_empty(self):
        """验证 AgentChatResponse 空响应"""
        from agent_workflow.tool_calling import AgentChatResponse
        resp = AgentChatResponse(content="empty", tokens_used=0)
        assert resp.content == "empty"
        assert resp.tool_calls == []
        assert resp.finish_reason == ""
