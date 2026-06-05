"""Tests for skill_executor.py and skills.py."""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from mcp_server.dispatcher import ToolDispatcher
from mcp_server.skill_executor import SkillExecutor, SkillDefinition
from mcp_server.skills import register_core_skills


class TestSkillDefinition:
    def test_minimal_construction(self):
        sd = SkillDefinition(name="test", description="A test skill")
        assert sd.name == "test"
        assert sd.description == "A test skill"
        assert sd.steps == []
        assert sd.max_tokens == 8000

    def test_with_steps(self):
        steps = [lambda args: {"result": "ok"}]
        sd = SkillDefinition(name="test", description="Test", steps=steps)
        assert len(sd.steps) == 1


class TestSkillExecutor:
    def test_register_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            exe = SkillExecutor(disp)
            sd = SkillDefinition(name="ping", description="Returns pong")
            exe.register(sd)
            skills = exe.list_skills()
            assert len(skills) == 1
            assert skills[0]["name"] == "ping"

    def test_register_duplicate_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            exe = SkillExecutor(disp)
            exe.register(SkillDefinition(name="a", description="first"))
            exe.register(SkillDefinition(name="a", description="second"))
            assert len(exe.list_skills()) == 1
            assert exe.list_skills()[0]["description"] == "second"

    def test_get_definition_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            exe = SkillExecutor(disp)
            sd = SkillDefinition(name="find_me", description="Found")
            exe.register(sd)
            assert exe.get_definition("find_me") is sd

    def test_get_definition_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            exe = SkillExecutor(disp)
            assert exe.get_definition("nope") is None

    @pytest.mark.asyncio
    async def test_execute_unknown_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            exe = SkillExecutor(disp)
            result = await exe.execute("nope", {})
            assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_single_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            exe = SkillExecutor(disp)
            exe.register(SkillDefinition(
                name="echo",
                description="Echo back",
                steps=[lambda args: {"echo": args.get("msg", "")}],
            ))
            result = await exe.execute("echo", {"msg": "hello"})
            assert result["skill"] == "echo"
            assert result["steps"] == 1
            assert result["result"]["echo"] == "hello"

    @pytest.mark.asyncio
    async def test_execute_multi_step_merges_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            exe = SkillExecutor(disp)
            exe.register(SkillDefinition(
                name="multi",
                description="Two steps",
                steps=[
                    lambda args: {"first": "a"},
                    lambda args: {"second": "b"},
                ],
            ))
            result = await exe.execute("multi", {})
            assert result["result"]["first"] == "a"
            assert result["result"]["second"] == "b"

    @pytest.mark.asyncio
    async def test_execute_passes_arguments_to_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            exe = SkillExecutor(disp)
            exe.register(SkillDefinition(
                name="passthrough",
                description="Pass args through",
                steps=[lambda args: {"x": args.get("x")}],
            ))
            result = await exe.execute("passthrough", {"x": 42})
            assert result["result"]["x"] == 42


class TestCoreSkills:
    def test_register_core_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = ToolDispatcher(project_root=tmp)
            exe = SkillExecutor(disp)
            register_core_skills(exe, disp)
            skills = exe.list_skills()
            names = [s["name"] for s in skills]
            assert "get_context_for_symbol" in names
            assert "get_impact_analysis" in names
            assert "explain_code_block" in names
            assert "prepare_refactor" in names
            assert "generate_docstring" in names
            assert "assess_merge_impact" in names
            assert "review_refactoring" in names
            assert len(skills) == 7

    @pytest.mark.asyncio
    async def test_explain_code_block_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_file = os.path.join(tmp, "app.ts")
            with open(test_file, "w") as f:
                f.write("")
            disp = ToolDispatcher(project_root=tmp)
            exe = SkillExecutor(disp)
            register_core_skills(exe, disp)
            result = await exe.execute("explain_code_block", {"file_path": test_file})
            assert result["skill"] == "explain_code_block"
            assert result["steps"] == 2
            assert "symbols" in result["result"] or "imports" in result["result"]
