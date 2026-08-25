"""I3 集成测试：start_pipeline 双轨对拍（legacy 旧路径 vs tAgent 薄接线）。

同一合成场景分别跑两条路径，对比进度契约（状态/权重/item-log/步骤）与
组件落库 ingest payload——证明 tAgent 路径与生产旧路径行为一致。
LLM 全部脚本化打桩（legacy: agentic_chat + create_llm_chat_fn；tagent: Adapter.chat），零真实调用。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest

from topocode_agent.core.llm import ChatResponse
from topoone.agent.agent_workflow.agent_queue import get_global_queue
from topoone.engine.task_manager import register_analysis_methods
from topoone.llm.tagent_adapter import TopoLLMClientAdapter

from conftest import PROJECT_DB_SCHEMA, FakeDB, FakeMultiDB

PID = "proj-abtest"
TID = "task-abtest-1"


class FakeServer:
    def __init__(self):
        self.handlers = {}

    def register(self, name):
        def deco(fn):
            self.handlers[name] = fn
            return fn
        return deco


def _valid_json(name="AuthModule"):
    return json.dumps(
        {"name": name, "summary": "负责登录鉴权的核心模块。", "role": "AuthLayer",
         "key_files": [], "depends_on": []},
        ensure_ascii=False)


OVERVIEW_MD = "# 架构总览\n分层清晰。"


class ScriptedLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        if not self.script:
            return ChatResponse(content="", finish_reason="stop")
        return self.script.pop(0)


def _patch_tagent_llm(monkeypatch, script):
    scripted = ScriptedLLM(script)

    async def _chat(self, messages, **kw):
        return await scripted.chat(messages, **kw)

    monkeypatch.setattr(TopoLLMClientAdapter, "chat", _chat)
    return scripted


def _patch_legacy_llm(monkeypatch):
    """legacy 路径两处 LLM 收口：组件(agentic_chat) + 总览(create_llm_chat_fn)。"""
    from topoone.agent.agent_workflow.tool_calling import AgentChatResponse

    calls = {"n": 0}

    async def _fake_agentic_chat(messages, tools=None, multi_db=None, model_id="",
                                 strategy=None, temperature=0.3, max_tokens=None):
        calls["n"] += 1
        return AgentChatResponse(content=_valid_json(), finish_reason="stop")

    def _fake_llm_fn_factory(multi_db, model_id=""):
        async def _fn(messages, temperature=0.3, max_tokens=None, **kw):
            calls["n"] += 1
            return OVERVIEW_MD
        return _fn

    monkeypatch.setattr(
        "topoone.agent.agent_workflow.tool_calling.agentic_chat", _fake_agentic_chat)
    monkeypatch.setattr(
        "topoone.agent.agent_workflow.llm_adapter.create_llm_chat_fn",
        _fake_llm_fn_factory)
    return calls


def _seed(multi_db, project_db, root, all_analyzed=False):
    md = multi_db.main_db
    md.execute("""CREATE TABLE IF NOT EXISTS analysis_tasks (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('ast','call-chain','dependency','dataflow','full')),
        name TEXT NOT NULL, status TEXT DEFAULT 'pending', progress INTEGER DEFAULT 0,
        total INTEGER DEFAULT 100, current INTEGER DEFAULT 0, error TEXT, result_data TEXT,
        favorite INTEGER DEFAULT 0, pinned INTEGER DEFAULT 0, tags TEXT, scope TEXT,
        scopes TEXT, extensions TEXT, exclude_dirs TEXT, report_types TEXT,
        pattern_type TEXT, pattern TEXT, config_version INTEGER DEFAULT 1,
        last_run_id TEXT, created_at TEXT, updated_at TEXT)""")
    md.execute(
        "INSERT INTO analysis_tasks (id, project_id, type, name, status) VALUES (?,?,?,?,?)",
        (TID, PID, "full", "abtest", "done"))
    md.execute(
        "INSERT INTO projects (id, name, root_path, summary) VALUES (?,?,?,?)",
        (PID, "abtest", root, "a demo project"))
    md.execute(
        "INSERT INTO model_configs (id, name, provider, url, model, api_key, is_default) "
        "VALUES (?,?,?,?,?,?,?)",
        ("model-abtest", "abtest", "openai_compat", "http://fake", "m", "", 1))
    # legacy 总览路径依赖 prompt 模板 + 默认 locale
    md.execute("""CREATE TABLE IF NOT EXISTS llm_prompt_templates (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('chat','tools','structured')),
        module_type TEXT, category TEXT DEFAULT 'general', is_builtin INTEGER DEFAULT 0,
        system_prompt TEXT, user_prompt_template TEXT, tools_json TEXT,
        tool_strategy TEXT DEFAULT 'auto', output_schema_json TEXT, output_example TEXT,
        variables_json TEXT, metadata TEXT, locale TEXT DEFAULT 'zh-CN',
        created_at TEXT, updated_at TEXT)""")
    md.execute(
        "INSERT INTO llm_prompt_templates (id, name, mode, system_prompt, user_prompt_template, locale) "
        "VALUES (?,?,?,?,?,?)",
        ("agent_generate_overview", "overview", "chat", "architect", "{context}\n{lang_instr}", "zh-CN"))
    md.execute("CREATE TABLE IF NOT EXISTS context_store (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    md.commit()
    multi_db._project_dbs[PID] = project_db

    pd = project_db
    pd.execute("""CREATE TABLE IF NOT EXISTS agent_task_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
        task_id TEXT NOT NULL, agent_id TEXT NOT NULL UNIQUE, action TEXT NOT NULL,
        status TEXT NOT NULL, steps TEXT, message TEXT, error TEXT,
        created_at TEXT, finished_at TEXT)""")
    pd.execute(
        "INSERT INTO community_hierarchy (task_id, edge_type, comm_lv, comm_id, node_count, file_count) "
        "VALUES (?,?,?,?,?,?)",
        (TID, "INCLUDE", "L0", "comm-ab12cd34-incl-L0-0001", 10, 2))
    pd.execute(
        "INSERT INTO graph_doc (task_id, edge_type, comm_lv, comm_id, node_list, node_count) "
        "VALUES (?,?,?,?,?,?)",
        (TID, "INCLUDE", "L0", "comm-ab12cd34-incl-L0-0001", json.dumps(["n1", "n2"]), 2))
    for nid, fp in (("n1", "src/a.py"), ("n2", "src/b.py")):
        pd.execute(
            "INSERT INTO graph_node (id, task_id, kind, name, qualified_name, file_path) "
            "VALUES (?,?,?,?,?,?)",
            (nid, TID, "file", nid, nid, fp))
        pd.execute(
            "INSERT INTO file_summaries (id, project_id, task_id, file_path, summary, summary_len) "
            "VALUES (?,?,?,?,?,?)",
            (f"fs-{nid}", PID, TID, fp, f"summary {nid}", 10))
    if all_analyzed:
        pd.execute(
            "INSERT INTO community_llm_results (task_id, edge_type, comm_lv, comm_id, name, summary) "
            "VALUES (?,?,?,?,?,?)",
            (TID, "INCLUDE", "L0", "comm-ab12cd34-incl-L0-0001", "AuthModule", "cached"))
        pd.execute(
            "INSERT INTO report_subdocs (id, task_id, edge_type, comm_id, title, content) "
            "VALUES (?,?,?,?,?,?)",
            ("overall-1", TID, "INCLUDE", "overall", "架构总览", "cached overview"))
    pd.commit()


def _wait_terminal(agent_id, timeout=30.0):
    mgr = get_global_queue()
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = mgr.get_progress(agent_id)
        if d and d["status"] in ("completed", "partial", "failed", "cancelled"):
            return d
        time.sleep(0.05)
    raise AssertionError(f"pipeline did not finish: {mgr.get_progress(agent_id)}")


def _run_backend(backend: str, monkeypatch, tmp_path, all_analyzed=False) -> dict:
    """在指定 backend 上跑一次 startPipeline，返回进度契约 + 组件 ingest payload。"""
    base = os.path.join(str(tmp_path), backend)
    data_dir = os.path.join(base, "data")
    root = os.path.join(base, "root")
    os.makedirs(root, exist_ok=True)

    multi_db = FakeMultiDB(data_dir)
    project_db = FakeDB(sqlite3.connect(":memory:", check_same_thread=False))
    project_db.raw.row_factory = sqlite3.Row
    project_db.raw.executescript(PROJECT_DB_SCHEMA)
    _seed(multi_db, project_db, root, all_analyzed=all_analyzed)

    if backend == "legacy":
        llm_calls = _patch_legacy_llm(monkeypatch)
        llm_script = None
    else:
        llm_script = [ChatResponse(content=_valid_json(), finish_reason="stop"),
                      ChatResponse(content=OVERVIEW_MD, finish_reason="stop")] \
            if not all_analyzed else []
        llm_calls = _patch_tagent_llm(monkeypatch, llm_script)
    monkeypatch.setenv("TOPOCODE_PIPELINE_BACKEND", backend)

    server = FakeServer()
    register_analysis_methods(server, multi_db)
    out = server.handlers["analysis.startPipeline"](taskId=TID)
    assert out["success"] is True
    d = _wait_terminal(out["agentTaskId"])

    ing = os.path.join(data_dir, "ingest", PID)
    payloads = []
    if os.path.isdir(ing):
        for f in sorted(os.listdir(ing)):
            if f.startswith("community_result-"):
                payloads.append(json.load(open(os.path.join(ing, f))))
    return {"progress": d, "ingest": payloads, "llm_calls": llm_calls}


def _compare_contracts(legacy: dict, tagent: dict, label: str):
    lp, tp = legacy["progress"], tagent["progress"]
    assert lp["status"] == tp["status"] == "completed", \
        f"{label}: legacy={lp['status']} tagent={tp['status']} err={tp.get('error')}"
    for k in ("weighted_total", "weighted_done", "weighted_progress",
              "total_files", "total_comps", "done_files", "done_comps",
              "step_total", "step_current"):
        assert lp[k] == tp[k], f"{label}: {k} legacy={lp[k]} tagent={tp[k]}"
    assert [s["status"] for s in lp["steps"]] == [s["status"] for s in tp["steps"]], \
        f"{label}: step statuses differ"
    items_l = sorted((i["type"], i["status"]) for i in lp["item_logs"])
    items_t = sorted((i["type"], i["status"]) for i in tp["item_logs"])
    assert items_l == items_t, f"{label}: item_logs differ\nlegacy={items_l}\ntagent={items_t}"
    assert len(legacy["ingest"]) == len(tagent["ingest"]), \
        f"{label}: ingest count {len(legacy['ingest'])} vs {len(tagent['ingest'])}"
    for a, b in zip(legacy["ingest"], tagent["ingest"]):
        for k in ("comm_id", "name", "summary", "edge_type", "comm_lv", "status", "task_id"):
            assert a.get(k) == b.get(k), f"{label}: ingest.{k} {a.get(k)!r} vs {b.get(k)!r}"


def test_start_pipeline_ab_analysis(tmp_path, monkeypatch):
    """有 1 个未分析组件：双轨契约对拍。"""
    legacy = _run_backend("legacy", monkeypatch, tmp_path)
    tagent = _run_backend("tagent", monkeypatch, tmp_path)
    _compare_contracts(legacy, tagent, "analysis")
    # 每轨各 2 次 LLM 调用（组件 1 + 总览 1）
    assert legacy["llm_calls"]["n"] == 2, f"legacy llm={legacy['llm_calls']['n']}"
    assert tagent["llm_calls"].calls == 2, f"tagent llm={tagent['llm_calls'].calls}"
    # 组件 payload 内容正确（非仅形状）
    assert tagent["ingest"][0]["name"] == "AuthModule"
    assert tagent["ingest"][0]["comm_lv"] == "L0"
    assert tagent["ingest"][0]["edge_type"] == "INCLUDE"


def test_start_pipeline_ab_all_skipped(tmp_path, monkeypatch):
    """全部已缓存：双轨 0 LLM 调用、契约一致。"""
    legacy = _run_backend("legacy", monkeypatch, tmp_path, all_analyzed=True)
    tagent = _run_backend("tagent", monkeypatch, tmp_path, all_analyzed=True)
    _compare_contracts(legacy, tagent, "all_skipped")
    assert legacy["llm_calls"]["n"] == 0
    assert tagent["llm_calls"].calls == 0


def test_start_pipeline_tagent_cancel(tmp_path, monkeypatch):
    """tAgent 路径：执行中取消 → cancelled 终态（LLM 长调用中取消，2s 轮询中止）。"""
    import asyncio
    base = os.path.join(str(tmp_path), "cancel")
    data_dir = os.path.join(base, "data")
    root = os.path.join(base, "root")
    os.makedirs(root, exist_ok=True)

    multi_db = FakeMultiDB(data_dir)
    project_db = FakeDB(sqlite3.connect(":memory:", check_same_thread=False))
    project_db.raw.row_factory = sqlite3.Row
    project_db.raw.executescript(PROJECT_DB_SCHEMA)
    _seed(multi_db, project_db, root)

    started = []

    async def _hang_chat(self, messages, **kw):
        started.append(1)
        await asyncio.sleep(3600)  # 模拟挂起的 LLM 调用
        return ChatResponse(content=_valid_json(), finish_reason="stop")

    monkeypatch.setattr(TopoLLMClientAdapter, "chat", _hang_chat)
    monkeypatch.setenv("TOPOCODE_PIPELINE_BACKEND", "tagent")

    server = FakeServer()
    register_analysis_methods(server, multi_db)
    out = server.handlers["analysis.startPipeline"](taskId=TID)
    agent_id = out["agentTaskId"]

    mgr = get_global_queue()
    deadline = time.time() + 15
    while time.time() < deadline:
        d = mgr.get_progress(agent_id)
        if d and d["status"] == "running" and started:
            break
        time.sleep(0.05)
    assert started, "pipeline did not reach LLM call"

    t0 = time.time()
    assert mgr.cancel(agent_id) is True
    d = _wait_terminal(agent_id, timeout=20)
    assert d["status"] == "cancelled"
    # 取消应在数秒内生效（2s 轮询 + 收尾），而非等 LLM 超时
    assert time.time() - t0 < 15
