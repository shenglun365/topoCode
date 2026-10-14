"""M05: agent 服务 — skill 注册表同步 + agent.dispatch(presummary, mock llm 通道)。"""

import asyncio
import os
import sys
import tempfile
import time

import pytest


@pytest.fixture()
def data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class _MockProvider:
    def chat_sync(self, model, messages, mode, tools, output_schema, max_tokens=None):
        return "Mock summary: this module defines helper functions used by the application."

    def chat_stream(self, model, messages, chunk_queue, tools, mode, max_tokens=None):
        chunk_queue.put({"type": "done", "content": "mock"})
        return {}


def _add_model(multi_db):
    multi_db.main_db.execute(
        "INSERT INTO model_configs (id, name, provider, model, url, is_default) VALUES (?, ?, ?, ?, ?, 1)",
        ("mock-model", "Mock", "ollama", "mock-llm", "http://127.0.0.1:11434"),
    )
    multi_db.main_db.commit()


def test_skill_registry_and_sync(data_dir):
    """@register_skill 装饰器注册 + sync_skills_to_db 落库（engine 启动同序 import）。"""
    from topoone.db.manager import MultiDBManager
    from topoone.agent.agent_workflow import skill_registry

    from topoone.agent.agent_workflow.workflows import overview as _  # noqa: F401
    from topoone.agent.agent_workflow.workflows import component_analyst as _  # noqa: F401
    from topoone.agent.agent_workflow.workflows import agentic_component_analyst as _  # noqa: F401
    from topoone.agent.agent_workflow.toolkits import file_tools as _  # noqa: F401
    from topoone.agent.agent_workflow.toolkits import symbol_tools as _  # noqa: F401
    from topoone.agent.agent_workflow.toolkits import graph_tools as _  # noqa: F401
    from topoone.agent.agent_workflow.toolkits import edge_tools as _  # noqa: F401

    skills = skill_registry.get_registered_skills()
    assert skills, "no skills registered after importing skill modules"

    multi_db = MultiDBManager(data_dir)
    try:
        skill_registry.sync_skills_to_db(multi_db)
        rows = multi_db.main_db.fetchall("SELECT id FROM skill_configs")
        assert len(rows) >= len(skills)
    finally:
        multi_db.close_all()


def test_agent_dispatch_presummary_with_mock_llm(data_dir, tmp_path, monkeypatch):
    """mock LLM 通道下 agent.dispatch(presummary_files) 跑通 + 进度轮询至完成。"""
    from topoone.db.manager import MultiDBManager
    from topoone.rpc.service_app import MethodServer
    from topoone.agent.__main__ import register_methods

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.py").write_text("def f():\n    return 1\n")
    (proj / "b.py").write_text("def g():\n    return 2\n")

    multi_db = MultiDBManager(data_dir)
    srv = MethodServer(pub_port=None)
    register_methods(srv, multi_db)
    try:
        import topoone.llm.service as svc_mod
        monkeypatch.setattr(svc_mod, "get_provider", lambda name: _MockProvider())
        _add_model(multi_db)

        pid = "proj-mock-1"
        multi_db.main_db.execute(
            "INSERT INTO projects (id, name, root_path, language, status) VALUES (?, ?, ?, ?, 'synced')",
            (pid, "mockproj", str(proj), "Python"),
        )
        multi_db.main_db.commit()

        async def drive():
            res = await srv.methods["agent.dispatch"](
                route="presummary_files", task_id="t-1",
                context={"files": ["a.py", "b.py"], "language": "python",
                         "subagent_concurrency": 1, "project_id": pid},
                project_id=pid, project_root=str(proj), project_summary="",
            )
            agent_id = res["agent_id"]
            deadline = time.time() + 60
            progress = {}
            while time.time() < deadline:
                progress = await srv.methods["agent.getProgress"](agent_id=agent_id)
                status = str(progress.get("status", "")).lower()
                if status in ("completed", "success", "succeeded", "failed", "error", "cancelled"):
                    return res, progress
                await asyncio.sleep(0.2)
            return res, progress

        res, progress = asyncio.run(drive())
        assert res.get("agent_id")
        status = str(progress.get("status", "")).lower()
        assert status in ("completed", "success", "succeeded"), f"progress={progress}"
    finally:
        multi_db.close_all()
