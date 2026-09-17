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
    assert mp.heuristic_tier("qwen3.5-9b-mtp") == 1   # 刻度 T0-T2: 9B → T1(中)
    assert mp.heuristic_tier("llama-3.2-3b") == 2   # 刻度 T0-T2: 3B → T2(弱)
    assert mp.heuristic_tier("qwen2.5-0.5b") == 2
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
    assert prof["tier"] == 1                    # 8b 启发式 T1, 满分不升档
    assert prof["caps"]["toolCallRate"] == 1.0
    assert prof["source"] == "probed"
    assert mp.tier_of("m-8b") == 1


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


def _mk_conv_nobind(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    return store.ConversationsStore.get(conv["id"])


def test_manual_model_update_route(tmp_path, monkeypatch):
    """manual 条目可改(name/provider/model/url); imported 条目拒绝(主库为源)。"""
    import asyncio
    from fastapi import Request
    from topoone_app_architect.arch_routes import mcp_collab as M

    class FakeReq:
        def __init__(self, body):
            self._b = body
        async def json(self):
            return self._b

    # 隔离 KB: manual 同步走本地保留路径(不触真实主库)
    from topoone_app_architect.arch_routes import kb_gateway
    monkeypatch.setattr(kb_gateway, "call_kb",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("kb isolated")))

    async def _run():
        created = await M.add_manual_llm_model_route(FakeReq(
            {"name": "旧名", "model": "old-model", "provider": "custom", "url": "http://a"}))
        mid = created.body["data"]["id"] if hasattr(created, "body") else created["data"]["id"]
        res = await M.update_manual_llm_model_route(mid, FakeReq(
            {"name": "新名", "model": "new-model", "url": "http://b"}))
        return mid, res
    import topoone_app_architect.arch_routes.ctx as C
    _setup(tmp_path, monkeypatch)
    mid, res = asyncio.run(_run())
    data = res.body["data"] if hasattr(res, "body") else res["data"]
    assert data["name"] == "新名" and data["model"] == "new-model" and data["url"] == "http://b"
    # 存储已更新
    rows = [m for m in M.get_llm_models() if m.get("id") == mid]
    assert rows and rows[0]["model"] == "new-model"
    # imported 条目编辑 → 转正为 manual(KB 重新导入不覆盖)
    M.save_llm_models([{"source": "imported", "id": "imp-1", "name": "n", "model": "m",
                        "provider": "lm-studio", "url": "http://u"}])
    res2 = asyncio.run(M.update_manual_llm_model_route("imp-1", FakeReq({"name": "x"})))
    data2 = res2.body["data"] if hasattr(res2, "body") else res2["data"]
    assert data2["source"] == "manual" and data2["name"] == "x"


def test_model_delete_route(tmp_path, monkeypatch):
    """删除分流: imported 仅解除导入(不动主库); manual 清理主库注册条目;
    kbShared(复用 KB 自有)不删主库; 选中偏好指向被删条目时清空。"""
    import asyncio
    import topoone_app_architect.arch_routes.ctx as C
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import mcp_collab as M
    from topoone_app_architect.arch_routes import kb_gateway

    removed = []
    monkeypatch.setattr(kb_gateway, "call_kb",
                        lambda method, **kw: removed.append(kw.get("id")) or [])

    M.save_llm_models([
        {"source": "imported", "id": "model-kb1", "name": "a", "model": "m1"},
        {"source": "manual", "id": "model-arch1", "name": "b", "model": "m2"},      # 注册绑定
        {"source": "manual", "id": "model-kb9", "name": "c", "model": "m3",
         "kbShared": True},                                                          # 复用 KB 自有
    ])
    from topoone_app_architect.arch_routes import store as _st
    _st.CollabConfigStore.set("llm.modelId", "model-kb1")

    # imported: 仅本地移除, 不触主库
    asyncio.run(M.delete_llm_model_route("model-kb1"))
    assert removed == [], "解除导入不得动主库"
    assert [m["id"] for m in M.get_llm_models()] == ["model-arch1", "model-kb9"]
    assert _st.CollabConfigStore.get("llm.modelId", "") == "", "选中偏好应清空"

    # manual 注册绑定: 清理主库 architect 域条目
    asyncio.run(M.delete_llm_model_route("model-arch1"))
    assert removed == ["model-arch1"]

    # manual 复用 KB 自有(kbShared): 不删主库
    asyncio.run(M.delete_llm_model_route("model-kb9"))
    assert removed == ["model-arch1"]
    assert M.get_llm_models() == []


def test_manual_model_kb_sync_binds_id(tmp_path, monkeypatch):
    """manual 条目同步主库: 同名模型复用主库 id; 无匹配 → addModel 注册。

    主库 id 是探测/对话链路的真实路由键(否则 llm.sync 回退 is_default)。
    """
    import topoone_app_architect.arch_routes.ctx as C
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import mcp_collab as M
    from topoone_app_architect.arch_routes import kb_gateway
    import topoone_app_architect.arch_routes.mcp_collab as M
    calls = {"get": 0, "add": 0}

    def fake_call_kb(method, **kw):
        if method == "settings.getModels":
            calls["get"] += 1
            return [{"id": "model-kb42", "model": "qwen3.5-4b-mtp"}] if calls["get"] == 1 else []
        calls["add"] += 1
        return {"id": "model-new01", **kw}
    monkeypatch.setattr(kb_gateway, "call_kb", fake_call_kb)
    entry = M._sync_manual_to_kb({"id": "man-x", "name": "LMS-4b", "provider": "custom",
                                  "model": "qwen3.5-4b-mtp", "url": "http://10.0.0.75:1234/v1"})
    assert entry["id"] == "model-kb42", "同名应复用主库 id"

    # 无匹配 → addModel 注册并取新 id(注册到 architect 专属域, 不污染 KB 模型列表)
    added = {}

    def fake_add(method, **kw):
        if method == "settings.getModels":
            return []
        added.update(kw)
        return {"id": "model-new02", **kw}
    monkeypatch.setattr(kb_gateway, "call_kb", fake_add)
    entry2 = M._sync_manual_to_kb({"id": "man-y", "name": "LMS-2b", "provider": "custom",
                                   "model": "qwen3.5-2b-mtp", "url": "http://x"})
    assert entry2["id"] == "model-new02", "无匹配应注册主库并绑新 id"
    assert added.get("ownerApp") == "architect", "注册应带 ownerApp=architect 走专属域"

    # KB 不可达 → 保留本地 id 不抛出
    def boom(*a, **kw):
        raise RuntimeError("kb down")
    monkeypatch.setattr(kb_gateway, "call_kb", boom)
    entry3 = M._sync_manual_to_kb({"id": "man-z", "name": "n", "model": "m", "url": ""})
    assert entry3["id"] == "man-z"
