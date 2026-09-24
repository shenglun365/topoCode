"""模型能力档案 + 适配管道(repair_loop)单元测试(P1 地基)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_model_profile.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.ctx as C
from topoone_app_architect import store


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


# ── 启发式分层(已退役, 函数兼容保留) ─────────────────────────────────

def test_heuristic_tier_retired():
    """参数规模猜档已退役(2026-09-18: 判档纯用例结果)——函数保留仅供兼容。"""
    from topoone_app_architect.agent.cognition import model_profile as mp
    assert mp.guess_params_b("qwen3.5-9b-mtp") == 9.0
    assert mp.heuristic_tier("Qwen2.5-72B-Instruct") == 0
    assert mp.heuristic_tier("unknown-model") == 1     # 不可判断 → 保守 t1


# ── 档案存取 + 手工 tier 优先 ─────────────────────────────────────────

def test_profile_store_and_manual_override(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.agent.cognition import model_profile as mp
    # 无档案 → 未探测缺省(中性 T1, 参数规模不参与; source=未探测标记)
    assert mp.get_profile("m-x").get("source") == "heuristic"
    assert mp.get_profile("qwen2.5-72b-instruct")["tier"] == 1   # 不按名称猜档
    assert mp.get_profile("llama-3.2-3b")["tier"] == 1
    # 手工设置(现行刻度钳制 T0-T2)
    prof = mp.set_manual_tier("m-x", 2)
    assert prof["tier"] == 2 and prof["source"] == "manual"
    assert mp.tier_of("m-x") == 2
    # 手工 tier 越界钳制(T0-T2)
    assert mp.set_manual_tier("m-y", 9)["tier"] == 2
    # 存量旧刻度(3/4)读路径归一 → 2
    from topoone_app_architect.agent.cognition import model_profile as real_mp
    real_mp._save_all({"m-old": {"modelId": "m-old", "tier": 4, "source": "probed"}})
    assert mp.get_profile("m-old")["tier"] == 2
    assert mp.tier_of("m-old") == 2


# ── 探测套件(mock LLM) ────────────────────────────────────────────────

def _mock_llm(responses, monkeypatch):
    """responses: 每次调用的返回 content 列表(耗尽后复用最后一个)。"""
    calls = {"n": 0}

    def fake_sync(messages, mode="chat", model_id=None, max_tokens=None, **kw):
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return {"content": responses[idx]}
    monkeypatch.setattr("topoone_app_architect.agent.tools.req_agent.llm_sync", fake_sync)
    return calls


TOOL_OK = '[TOOL_CALL]{"tool":"req.propose","arguments":{"title":"x"}}[/TOOL_CALL]'
JSON_OK = '```json\n{"title": "T", "requirementMd": "r", "designMd": "d"}\n```'
REQ_OK = ('```json\n{"title": "客服系统", "requirementMd": "在线客服与工单", '
          '"clarifications": [{"question": "q1", "defaultAssumption": "a1"}, '
          '{"question": "q2", "defaultAssumption": "a2"}], '
          '"scopeIn": "网页端", "scopeOut": "不做语音"}\n```')
ARCH_OK = ('```json\n{"modules": [{"name": "a", "duty": "x"}, {"name": "b", "duty": "y"}, '
           '{"name": "c", "duty": "z"}], "deps": [{"from": "a", "to": "b"}, '
           '{"from": "b", "to": "c"}], "choices": [{"area": "存储", "pick": "pg", '
           '"why": "多租户行级隔离成熟且团队熟悉"}]}\n```')
MOD_OK = ('```json\n{"interface": {"fn": "cancel", "params": ["id"], "returns": "bool"}, '
          '"dataStructures": "orders 表", "edgeCases": ["e1", "e2", "e3"], '
          '"steps": ["s1", "s2", "s3"]}\n```')


def test_probe_model_good_small_model(tmp_path, monkeypatch):
    """探测满分的小模型: 纯用例结果判档——参数规模不参与, 满分即 T0。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.agent.cognition import model_profile as mp

    def smart_sync(messages, mode="chat", model_id=None, max_tokens=None, **kw):
        sys0 = str(messages[0]["content"]) if messages else ""
        user = messages[-1]["content"] if messages else ""
        # 设计三维(关键字路由: system 含各自契约字段)
        if "clarifications" in sys0:
            return {"content": REQ_OK}
        if "edgeCases" in sys0:
            return {"content": MOD_OK}
        if "modules" in sys0:
            return {"content": ARCH_OK}
        if "req.propose" in sys0 or "调用" in user:
            tool = next((n for n in ("kb.asset.search", "map.overview",
                                     "req.propose") if n in user),
                        "req.propose")
            return {"content": f'[TOOL_CALL]{{"tool":"{tool}","arguments":{{}}}}[/TOOL_CALL]'}
        if "整理为规约" in sys0 or "```json" in sys0:
            return {"content": JSON_OK}
        return {"content": "好的, 我来整理该脚本需求并给出方案。"}
    monkeypatch.setattr("topoone_app_architect.agent.tools.req_agent.llm_sync", smart_sync)
    seen_budgets: list = []
    real_smart = smart_sync

    def budget_spy(messages, mode="chat", model_id=None, max_tokens=None, **kw):
        seen_budgets.append(max_tokens)
        return real_smart(messages, mode=mode, model_id=model_id,
                          max_tokens=max_tokens, **kw)
    monkeypatch.setattr("topoone_app_architect.agent.tools.req_agent.llm_sync", budget_spy)
    prof = mp.probe_model("m-8b")
    # 胜任容量分层: 8B → 8K 预算(全部用例统一)
    assert seen_budgets and set(seen_budgets) == {8192}
    assert prof.get("modelName") == "m-8b"      # 模型目录空 → 用 id 代名
    assert prof["tier"] == 0                    # 满分 → T0(8B 名字不再压档)
    assert prof["caps"]["toolCallRate"] == 1.0
    assert prof["caps"]["requirementScore"] == 1.0
    assert prof["caps"]["archScore"] == 1.0
    assert prof["caps"]["moduleScore"] == 1.0
    assert prof["source"] == "probed"
    assert mp.tier_of("m-8b") == 0


def test_probe_model_degrades_tier(tmp_path, monkeypatch):
    """探测差 → tier 只降不升(名字大也降档, 启用兜底)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.agent.cognition import model_profile as mp
    _mock_llm(["我不会调用工具, 直接回答: 无法完成该任务"], monkeypatch)
    prof = mp.probe_model("m-72b")
    assert prof["tier"] >= 2                    # 差 → 至少 t2
    assert prof["caps"]["toolCallRate"] < 0.5


def test_probe_unreachable_keeps_profile(tmp_path, monkeypatch):
    """模型不可达 → reachable=False 且不覆盖既有档案。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.agent.cognition import model_profile as mp
    mp.set_manual_tier("m-down", 2)

    def boom(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr("topoone_app_architect.agent.tools.req_agent.llm_sync", boom)
    out = mp.probe_model("m-down")
    assert out.get("reachable") is False
    assert mp.tier_of("m-down") == 2            # 原档案未破坏


def test_probe_compensation_recheck(tmp_path, monkeypatch):
    """T2 补偿复核: 补偿救不回 → insufficient(模型能力不足); 救得回 → weak(补偿可修正)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.agent.cognition import model_profile as mp
    # 全程摆烂: 常规探测掉 T2, 补偿形态也救不回 → insufficient + 复核率 0
    _mock_llm(["我不会调用工具, 直接回答: 无法完成该任务"], monkeypatch)
    prof = mp.probe_model("m-dumb")
    assert prof["tier"] == 2
    assert prof["admission"]["level"] == "insufficient"
    assert "模型能力不足" in prof["admission"]["note"]
    assert prof["caps"]["compensationRate"] == 0.0

    # 常规形态差但补偿形态能救(生产补偿指令可拉回) → weak + 复核通过
    def comp_only(messages, mode="chat", model_id=None, max_tokens=None, **kw):
        sys = str(messages[0]["content"])
        if "核心逻辑图" in sys:
            return {"content": "```mermaid\nflowchart TD\nA[s] --> B[p]\nB --> C[q]\nC --> D[e]\n```"}
        if "结构化指令" in sys:
            return {"content": '```json\n{"title": "T", "designMd": "1. a\\n2. b\\n3. c"}\n```'}
        return {"content": "普通回答"}
    monkeypatch.setattr("topoone_app_architect.agent.tools.req_agent.llm_sync", comp_only)
    prof2 = mp.probe_model("m-weak-but-guided")
    assert prof2["tier"] == 2
    assert prof2["admission"]["level"] == "weak"
    assert "补偿复核通过" in prof2["admission"]["note"]


# ── repair_loop 六要素 ────────────────────────────────────────────────

def test_repair_loop_parse_only(tmp_path, monkeypatch):
    """纯解析任务(execute=None): 解析成功 ok, 失败 failed 不抛出。"""
    _setup(tmp_path, monkeypatch)
    import topoone_app_architect.agent.reflection.repair as ad

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
    from topoone_app_architect import kb_gateway
    monkeypatch.setattr(kb_gateway, "call_kb",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("kb isolated")))

    async def _run():
        created = await M.add_manual_llm_model_route(FakeReq(
            {"name": "旧名", "model": "old-model", "provider": "custom", "url": "http://a"}))
        mid = created.body["data"]["id"] if hasattr(created, "body") else created["data"]["id"]
        res = await M.update_manual_llm_model_route(mid, FakeReq(
            {"name": "新名", "model": "new-model", "url": "http://b"}))
        return mid, res
    import topoone_app_architect.ctx as C
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


def test_llm_models_save_dedupes_by_id(tmp_path, monkeypatch):
    """存储归一: 同 id 双行(KB 同步按名复用 id + 名称变体所致)保留 updatedAt 最新。"""
    import topoone_app_architect.ctx as C
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import mcp_collab as M
    M.save_llm_models([
        {"source": "manual", "id": "model-x", "name": "旧变体", "provider": "custom",
         "model": "m", "url": "", "updatedAt": 100},
        {"source": "imported", "id": "imp-1", "name": "a", "model": "m1"},
        {"source": "manual", "id": "model-x", "name": "LMS 新变体", "provider": "LMS",
         "model": "m", "url": "http://u", "updatedAt": 200},
    ])
    rows = M.get_llm_models()
    xs = [m for m in rows if m["id"] == "model-x"]
    assert len(xs) == 1 and xs[0]["name"] == "LMS 新变体"
    assert any(m["id"] == "imp-1" for m in rows)      # 他人条目不受影响


def test_model_delete_route(tmp_path, monkeypatch):
    """删除分流: imported 仅解除导入(不动主库); manual 清理主库注册条目;
    kbShared(复用 KB 自有)不删主库; 选中偏好指向被删条目时清空。"""
    import asyncio
    import topoone_app_architect.ctx as C
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import mcp_collab as M
    from topoone_app_architect import kb_gateway

    removed = []
    monkeypatch.setattr(kb_gateway, "call_kb",
                        lambda method, **kw: removed.append(kw.get("id")) or [])

    M.save_llm_models([
        {"source": "imported", "id": "model-kb1", "name": "a", "model": "m1"},
        {"source": "manual", "id": "model-arch1", "name": "b", "model": "m2"},      # 注册绑定
        {"source": "manual", "id": "model-kb9", "name": "c", "model": "m3",
         "kbShared": True},                                                          # 复用 KB 自有
    ])
    from topoone_app_architect import store as _st
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
    import topoone_app_architect.ctx as C
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import mcp_collab as M
    from topoone_app_architect import kb_gateway
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


# ── 探测并发治理: 互斥(串行) + FIFO 排队 + 同模型滤重 ─────────────────

def test_clear_profiles(tmp_path, monkeypatch):
    """清空探测档案: 全清/单清, 清后回到未探测缺省(中性 T1)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.agent.cognition import model_profile as mp
    mp.set_manual_tier("m-a", 1)
    mp.set_manual_tier("m-b", 0)
    assert mp.clear_profile("m-a") is True
    assert mp.clear_profile("m-a") is False          # 重复清空幂等
    assert mp.get_profile("m-a")["source"] == "heuristic"   # 回到未探测缺省
    assert mp.clear_profiles() == 1                   # 剩 m-b
    assert mp.get_profile("m-b")["source"] == "heuristic"
    assert mp.clear_profiles() == 0                   # 空仓再清 = 0


def test_probe_gate_mutex_queue_dedup(tmp_path, monkeypatch):
    """并发点击治理: 全局同一时刻仅一个套件在跑; 同模型重复请求回执 dup;
    结束后队列排空无残留。"""
    import threading
    import time as _t
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.agent.cognition import model_profile as mp  # 真实模块(shim 仅转发)

    gate = mp._ProbeGate()
    monkeypatch.setattr(mp, "_probe_gate", gate)
    stats = {"n": 0, "max": 0}
    lock = threading.Lock()

    def slow_probe(mid):
        with lock:
            stats["n"] += 1
            stats["max"] = max(stats["max"], stats["n"])
        _t.sleep(0.12)
        with lock:
            stats["n"] -= 1
        return {"modelId": mid, "tier": 1}
    monkeypatch.setattr(mp, "probe_model", slow_probe)

    barrier = threading.Barrier(4)   # 四请求对齐起跑, 保证 dup 命中在首跑进行中
    out = []

    def worker(mid):
        barrier.wait(5)
        out.append((mid, mp.probe_model_gated(mid)["status"]))

    ths = [threading.Thread(target=worker, args=(m,)) for m in ("a", "b", "a", "c")]
    for t in ths:
        t.start()
    for t in ths:
        t.join(10)

    statuses = sorted(s for _, s in out)
    assert statuses == ["dup", "run", "run", "run"], out   # 重复 'a' 被滤重
    assert stats["max"] == 1                               # 互斥: 串行无并发
    assert not gate._in and not gate._queue                # 队列排空无残留
