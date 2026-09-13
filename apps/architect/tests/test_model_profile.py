"""模型能力档案 + 适配管道(repair_loop)单元测试(P1 地基)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_model_profile.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
from topoone_app_architect.arch_routes import store


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)


# ── 启发式分层 ────────────────────────────────────────────────────────

def test_heuristic_tier():
    from topoone_app_architect.arch_routes import model_profile as mp
    assert mp.guess_params_b("qwen3.5-9b-mtp") == 9.0
    assert mp.guess_params_b("Qwen2.5-72B-Instruct") == 72.0
    assert mp.guess_params_b("qwen2.5-1.5b") == 1.5
    assert mp.heuristic_tier("Qwen2.5-72B-Instruct") == 0
    assert mp.heuristic_tier("qwen3.5-9b-mtp") == 2
    assert mp.heuristic_tier("llama-3.2-3b") == 3
    assert mp.heuristic_tier("qwen2.5-0.5b") == 4
    assert mp.heuristic_tier("unknown-model") == 1     # 不可判断 → 保守 t1


# ── 档案存取 + 手工 tier 优先 ─────────────────────────────────────────

def test_profile_store_and_manual_override(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import model_profile as mp
    # 无档案 → 启发式(不落库)
    assert mp.get_profile("m-x").get("source") == "heuristic"
    # 手工设置
    prof = mp.set_manual_tier("m-x", 4)
    assert prof["tier"] == 4 and prof["source"] == "manual"
    assert mp.tier_of("m-x") == 4
    # 手工 tier 越界钳制
    assert mp.set_manual_tier("m-y", 9)["tier"] == 4


# ── 探测套件(mock LLM) ────────────────────────────────────────────────

def _mock_llm(responses, monkeypatch):
    """responses: 每次调用的返回 content 列表(耗尽后复用最后一个)。"""
    calls = {"n": 0}

    def fake_sync(messages, mode="chat", model_id=None, max_tokens=None, **kw):
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return {"content": responses[idx]}
    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", fake_sync)
    return calls


TOOL_OK = '[TOOL_CALL]{"tool":"req.propose","arguments":{"title":"x"}}[/TOOL_CALL]'
JSON_OK = '```json\n{"title": "T", "requirementMd": "r", "designMd": "d"}\n```'


def test_probe_model_good_small_model(tmp_path, monkeypatch):
    """探测满分的小模型: tier 保持启发式档(只降不升), caps 记录分数。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import model_profile as mp

    def smart_sync(messages, mode="chat", model_id=None, max_tokens=None, **kw):
        user = messages[-1]["content"] if messages else ""
        if "req.propose" in str(messages[0]["content"]) or "创建需求提案" in user:
            tool = "kb.asset.search" if "检索" in user else "req.propose"
            return {"content": f'[TOOL_CALL]{{"tool":"{tool}","arguments":{{}}}}[/TOOL_CALL]'}
        if "整理为规约" in messages[0]["content"] or "```json" in messages[0]["content"]:
            return {"content": JSON_OK}
        return {"content": "好的, 我来整理该脚本需求并给出方案。"}
    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", smart_sync)
    prof = mp.probe_model("m-8b")
    assert prof.get("modelName") == "m-8b"      # 模型目录空 → 用 id 启发式
    assert prof["tier"] == 2                    # 8b 启发式 t2, 满分不升档
    assert prof["caps"]["toolCallRate"] == 1.0
    assert prof["source"] == "probed"
    assert mp.tier_of("m-8b") == 2


def test_probe_model_degrades_tier(tmp_path, monkeypatch):
    """探测差 → tier 只降不升(名字大也降档, 启用兜底)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import model_profile as mp
    _mock_llm(["我不会调用工具, 直接回答: 无法完成该任务"], monkeypatch)
    prof = mp.probe_model("m-72b")
    assert prof["tier"] >= 2                    # 差 → 至少 t2
    assert prof["caps"]["toolCallRate"] < 0.5


def test_probe_unreachable_keeps_profile(tmp_path, monkeypatch):
    """模型不可达 → reachable=False 且不覆盖既有档案。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import model_profile as mp
    mp.set_manual_tier("m-down", 3)

    def boom(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr("topoone_app_architect.arch_routes.req_agent.llm_sync", boom)
    out = mp.probe_model("m-down")
    assert out.get("reachable") is False
    assert mp.tier_of("m-down") == 3            # 原档案未破坏


# ── repair_loop 六要素 ────────────────────────────────────────────────

def test_repair_loop_parse_only(tmp_path, monkeypatch):
    """纯解析任务(execute=None): 解析成功 ok, 失败 failed 不抛出。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import adaptation as ad

    def parse_ok(raw):
        return {"x": 1} if "json" in raw else None

    _mock_llm(['```json\n{"x":1}\n```'], monkeypatch)
    out = ad.run_repair_loop(ad.RepairTask(task_id="t", system="s", user="u", parse=parse_ok))
    assert out["ok"] and out["parsed"] == {"x": 1}

    _mock_llm(["无可解析产物"], monkeypatch)
    out2 = ad.run_repair_loop(ad.RepairTask(task_id="t", system="s", user="u", parse=parse_ok))
    assert not out2["ok"] and out2["action"] == "failed"


def test_repair_loop_execute_and_anchor(tmp_path, monkeypatch):
    """execute 执行 + 回灌锚定: 会话收到系统回执消息(真实编号锚点)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import adaptation as ad
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    _mock_llm(['```json\n{"rid":"RQ-1"}\n```'], monkeypatch)

    def _exec(parsed):
        return {"ok": True, "action": "proposed", "summary": f"✅ 已创建 {parsed['rid']}"}

    out = ad.run_repair_loop(ad.RepairTask(
        task_id="t2", system="s", user="u",
        parse=lambda raw: {"rid": "RQ-1"} if raw else None,
        execute=_exec, anchor_conv=conv["id"]))
    assert out["ok"] and out["action"] == "proposed"
    msgs = store.ConversationsStore.messages(conv["id"])
    assert any("已创建 RQ-1" in (m.get("content") or "") for m in msgs), "锚定回执应落会话"


def test_strategy_matrix():
    from topoone_app_architect.arch_routes import adaptation as ad
    assert ad.strategies_for_tier(0)["draft_card"] is False
    assert ad.strategies_for_tier(2)["draft_card"] is True
    assert ad.strategies_for_tier(4)["lenient_parse"] == "max"
    assert ad.strategies_for_tier(3)["postprocess"] is True
    assert ad.strategies_for_tier(1)["postprocess"] is False
