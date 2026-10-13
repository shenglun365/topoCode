"""核心资产守护(2610 重构)回归——规约库 / 挂载关联 / effective 聚合 / 引擎链 / REST / MCP。

模型: 挂载即核心(无分级); 规约库(arch_rule_defs) ↔ 目标(arch_target_rules) 多对多;
守护消费单口 = TargetRuleStore.list_effective。
"""
from __future__ import annotations

from tests.conftest import isolate_arch


def _mk_client(tmp_path, monkeypatch):
    data = isolate_arch(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    return TestClient(build_app(data_dir=data), base_url="http://127.0.0.1")


def _proj_env(arch_env):
    from topoone_app_architect import store
    store.ProjectsStore.create({"id": "proj-cg", "name": "演示",
                                "rootPath": "/tmp/proj-cg", "active": 0})
    return store


def _mark(store, ttype: str, tid: str, title: str, content: str,
          ttitle: str = "") -> str:
    """快捷: 建规约 + 挂载 → rule_id。"""
    rd = store.RuleDefStore.create("proj-cg", title, content)
    store.TargetRuleStore.attach("proj-cg", ttype, tid, rd["id"], title=ttitle or tid)
    return rd["id"]


def test_effective_aggregation_and_cascade(arch_env):
    """effective 聚合: 一目标多规约拼接 / 多目标共享规约 / 卸载 / 删规约级联卸载。"""
    store = _proj_env(arch_env)
    from topoone_app_architect import store as st
    r1 = st.RuleDefStore.create("proj-cg", "签名冻结", "- 对外接口签名不得变更")
    r2 = st.RuleDefStore.create("proj-cg", "纯函数", "- 保持纯函数")
    st.TargetRuleStore.attach("proj-cg", "file", "src/core.ts", r1["id"], title="核心模块")
    st.TargetRuleStore.attach("proj-cg", "file", "src/core.ts", r2["id"], title="核心模块")
    st.TargetRuleStore.attach("proj-cg", "asset", "sa-x", r1["id"])  # 共享 r1
    eff = st.TargetRuleStore.list_effective("proj-cg")
    by_id = {e["targetId"]: e for e in eff}
    core = by_id["src/core.ts"]
    assert len(core["rules"]) == 2 and core["title"] == "核心模块"
    assert "签名不得变更" in core["rulesMd"] and "保持纯函数" in core["rulesMd"]
    assert [r["title"] for r in core["rules"]] == ["签名冻结", "纯函数"]
    # 卸载一规约 → 剩一
    assert st.TargetRuleStore.detach("proj-cg", "file", "src/core.ts", r2["id"])
    eff = {e["targetId"]: e for e in st.TargetRuleStore.list_effective("proj-cg")}
    assert len(eff["src/core.ts"]["rules"]) == 1
    # 共享: 卸载不影响 sa-x
    assert len(eff["sa-x"]["rules"]) == 1
    # 删规约 → 级联卸载(sa-x 消失)
    assert st.RuleDefStore.delete(r1["id"])
    eff = st.TargetRuleStore.list_effective("proj-cg")
    assert all(e["targetId"] != "sa-x" for e in eff)
    # 幂等挂载
    st.TargetRuleStore.attach("proj-cg", "file", "src/core.ts", r2["id"])
    st.TargetRuleStore.attach("proj-cg", "file", "src/core.ts", r2["id"])
    eff = {e["targetId"]: e for e in st.TargetRuleStore.list_effective("proj-cg")}
    assert len(eff["src/core.ts"]["rules"]) == 1


def test_engine_three_layer_match_and_preflight(arch_env):
    """file 精确/后缀 + 轻量文本 + component owns + asset 锚点; pre/post 无分级。"""
    store = _proj_env(arch_env)
    from topoone_app_architect.sem import core_guard as cg
    _mark(store, "file", "src/core/engine.ts", "编译核心引擎",
          "- 对外接口签名不得变更")
    try:
        hits = cg.match_files("proj-cg", ["src/core/engine.ts", "x.ts"])
        assert len(hits) == 1
        assert len(cg.match_files("proj-cg", ["a/b/src/core/engine.ts"])) == 1  # 后缀
        md = cg.preflight_md("proj-cg", ["src/core/engine.ts"])
        assert "核心资产守护" in md and "编译核心引擎" in md and "签名不得变更" in md
        assert "🔴" not in md, "无分级: critical 徽章退役"
        assert "编译核心引擎" in cg.preflight_light_md("proj-cg", "请改 src/core/engine.ts")
        assert "map.core" in cg.preflight_light_md("proj-cg", "无关消息")
        r = cg.postflight_report("proj-cg", ["src/core/engine.ts", "other.ts"])
        assert r["hitChanged"] == 1 and r["totalChanged"] == 2
        assert r["extent"]["verdict"] == "medium"      # 1 命中 → medium(纯命中数)
        assert "核心资产变更评估" in cg.postflight_md("proj-cg", ["src/core/engine.ts"])
        assert "critical" not in cg.postflight_md("proj-cg", ["src/core/engine.ts"])
        assert cg.postflight_md("proj-cg", ["unrelated.ts"]) == ""
    finally:
        pass


def test_engine_component_and_asset_layers(arch_env):
    """component owns 展开 + asset 锚点 三层匹配。"""
    import json
    store = _proj_env(arch_env)
    from topoone_app_architect.sem import core_guard as cg
    _mark(store, "asset", "sa-anch", "锚点资产", "- 锚点规约")
    store.SemanticAssetsStore.create({
        "id": "sa-anch", "projectId": "proj-cg", "kind": "contract",
        "name": "锚点资产", "status": "active",
        "astRefs": json.dumps([{"file": "src/api.ts", "symbol": "get"}])})
    assert len(cg.match_files("proj-cg", ["src/api.ts"])) == 1
    assert cg.preflight_md("proj-cg", ["src/api.ts"]).count("★") == 1


def test_context_pack_injection_gated(arch_env):
    """任务链注入: 边界文件命中 → 契约段; overrides 显式 false → 不注入。"""
    store = _proj_env(arch_env)
    from topoone_app_architect.agent.execution.context_pack import (
        build_context_pack, render_context_pack_md)
    _mark(store, "file", "src/core.ts", "核心模块", "- 保持纯函数")
    task = {"id": "T1", "projectId": "proj-cg", "reqId": "", "title": "t"}
    pack = build_context_pack(task, None, "/tmp/proj-cg",
                              boundary_files=["src/core.ts"])
    md = render_context_pack_md(pack)
    assert "核心模块" in md and "保持纯函数" in md
    import json as _j
    store.CollabConfigStore.set("agent.comp.overrides",
                                _j.dumps({"core_guard_injection": False}))
    pack2 = build_context_pack(task, None, "/tmp/proj-cg",
                               boundary_files=["src/core.ts"])
    md2 = render_context_pack_md(pack2)
    assert "保持纯函数" not in md2
    store.CollabConfigStore.set("agent.comp.overrides", "{}")


def test_map_core_and_receipt(arch_env):
    """MCP map.core(按规约列表渲染) + task.receipt 确定性 post-flight。"""
    store = _proj_env(arch_env)
    from topoone_app_architect.sem.map_tools import run_tool
    from topoone_app_architect.sem.task_tools import tool_task_receipt
    _mark(store, "file", "src/core.ts", "核心模块", "- 保持纯函数")
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T",
                                            "projectId": "proj-cg"})
    t = store.TasksStore.create({"conversationId": conv["id"], "title": "S",
                                 "instruction": "x", "projectId": "proj-cg",
                                 "status": "done"})
    core = run_tool("map.core", {"project": "proj-cg"})
    assert "核心模块" in core and "保持纯函数" in core and "🔴" not in core
    md = tool_task_receipt(t["id"], ["src/core.ts", "a.ts"])
    assert "核心资产变更评估" in md and "核心模块" in md
    md2 = tool_task_receipt(t["id"], ["unrelated.ts"])
    assert "核心资产变更评估" not in md2, "无命中零噪音"


def test_proxy_light_injection_in_instruction(arch_env):
    """直通轻量(proxy.py 内联消费): 文本命中 → map.core 指针 + 规约; 门控关 → 不注入。"""
    store = _proj_env(arch_env)
    from topoone_app_architect.sem import core_guard as cg
    _mark(store, "file", "src/core.ts", "核心模块", "- 保持纯函数")
    text = cg.preflight_light_md("proj-cg", "请修改 src/core.ts 的实现")
    assert "核心模块" in text and "保持纯函数" in text
    # 门控在调用方(proxy.py guard_enabled)——引擎侧单测开关判定
    import json as _j
    store.CollabConfigStore.set("agent.comp.overrides",
                                _j.dumps({"core_guard_injection": False}))
    assert cg.guard_enabled(store.CollabConfigStore.get) is False
    store.CollabConfigStore.set("agent.comp.overrides", "{}")
    assert cg.guard_enabled(store.CollabConfigStore.get) is True


def test_postflight_landing(arch_env):
    """执行终态自动评估: 卡 + units 沉淀 + 门控。"""
    import json
    store = _proj_env(arch_env)
    from topoone_app_architect.sem import core_guard as cg  # noqa: F401
    from topoone_app_architect.agent.execution import core_assess as ca
    from topoone_app_architect.agent.execution.items import item_from_card
    _mark(store, "file", "src/core.ts", "核心模块", "- 保持纯函数")
    store.SemanticAssetsStore.create({
        "id": "sa-hit", "projectId": "proj-cg", "kind": "contract",
        "name": "编译契约", "status": "active",
        "astRefs": json.dumps([{"file": "src/core.ts", "symbol": "compile"}])})
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T",
                                            "projectId": "proj-cg"})
    got = ca.land_core_assessment(conv["id"], "proj-cg",
                                  ["src/core.ts"], source="direct:test")
    assert got and got["verdict"] == "medium" and got["hitChanged"] == 1
    msgs = store.ConversationsStore.messages(conv["id"])
    card = next(x for x in msgs if (x.get("meta") or {}).get("kind") == "asset_assess")
    it = item_from_card(card.get("meta"), card.get("content") or "",
                        ts=card.get("time"), msg_id=card.get("id"))
    assert it and it["type"] == "asset_assess" and it["payload"]["verdict"] == "medium"
    units = store.ContextUnitsStore.all(conv["id"], type_="core_assess")
    assert units and units[0]["importance"] >= 1
    import json as _json
    store.CollabConfigStore.set("agent.comp.overrides",
                                _json.dumps({"core_guard_injection": False}))
    assert ca.land_core_assessment(conv["id"], "proj-cg", ["src/core.ts"]) is None
    store.CollabConfigStore.set("agent.comp.overrides", "{}")
    assert ca.land_core_assessment(conv["id"], "proj-cg", ["unrelated.ts"]) is None


def test_rest_rule_defs_and_target_rules(tmp_path, monkeypatch):
    """REST: 规约库 CRUD(级联) + 挂载/卸载/effective + guard-config 开关。"""
    client = _mk_client(tmp_path, monkeypatch)
    with client:
        base = "/api/architect/arch"
        # 规约新建/清单/更新
        r = client.post(f"{base}/rule-defs", json={
            "project": "proj-r", "title": "签名冻结", "content": "- 签名不得变更"})
        assert r.status_code == 200, r.text[:200]
        rid = r.json()["data"]["id"]
        rows = client.get(f"{base}/rule-defs?project=proj-r").json()["data"]["items"]
        assert len(rows) == 1 and rows[0]["title"] == "签名冻结"
        r2 = client.put(f"{base}/rule-defs/{rid}", json={
            "project": "proj-r", "content": "- 新规约"})
        assert r2.status_code == 200 and "新规约" in r2.json()["data"]["content"]
        # 挂载(两目标共享) + effective
        for tid in ("src/a.ts", "src/b.ts"):
            ra = client.put(f"{base}/target-rules", json={
                "project": "proj-r", "targetType": "file",
                "targetId": tid, "ruleId": rid, "title": tid})
            assert ra.status_code == 200, ra.text[:200]
        eff = client.get(f"{base}/target-rules?project=proj-r").json()["data"]["items"]
        assert len(eff) == 2 and all("新规约" in x["rulesMd"] for x in eff)
        # 幂等挂载
        client.put(f"{base}/target-rules", json={
            "project": "proj-r", "targetType": "file",
            "targetId": "src/a.ts", "ruleId": rid})
        eff = client.get(f"{base}/target-rules?project=proj-r").json()["data"]["items"]
        assert len(eff) == 2
        # 守护开关(缺省开 → 关 → 开)
        assert client.get(f"{base}/guard-config").json()["data"]["autoInject"] is True
        client.put(f"{base}/guard-config", json={"autoInject": False})
        assert client.get(f"{base}/guard-config").json()["data"]["autoInject"] is False
        # 单目标卸载
        rd = client.delete(
            f"{base}/target-rules?project=proj-r&targetType=file&targetId=src/a.ts&ruleId={rid}")
        assert rd.status_code == 200
        eff = client.get(f"{base}/target-rules?project=proj-r").json()["data"]["items"]
        assert len(eff) == 1 and eff[0]["targetId"] == "src/b.ts"
        # 删规约级联 → b.ts 挂载消失
        assert client.delete(f"{base}/rule-defs/{rid}?project=proj-r").status_code == 200
        assert client.get(f"{base}/target-rules?project=proj-r").json()["data"]["items"] == []
        # 404 分支
        assert client.delete(f"{base}/rule-defs/{rid}?project=proj-r").status_code == 404
        assert client.put(f"{base}/target-rules", json={
            "project": "proj-r", "targetType": "file",
            "targetId": "x", "ruleId": rid}).status_code == 404


def test_manual_semantic_asset_endpoint(tmp_path, monkeypatch):
    """手动建资产: ruleIds 挂既有规约 / ruleText 建规约并挂 / 校验 400 / 回落。"""
    client = _mk_client(tmp_path, monkeypatch)
    from topoone_app_architect import store
    store.ProjectsStore.create({"id": "proj-cg", "name": "演示",
                                "rootPath": "/tmp/proj-cg", "active": 0})
    rd = store.RuleDefStore.create("proj-cg", "既有规约", "- 既有内容")
    with client:
        base = {"project": "proj-cg", "root": "/tmp/proj-cg"}
        url = "/api/architect/semantic/assets/manual"
        r = client.post(url, json={
            **base, "name": "核心锁段", "file": "src/core/engine.ts",
            "startLine": 10, "endLine": 40, "symbol": "acquire",
            "ruleIds": [rd["id"]]})
        assert r.status_code == 200, r.text[:200]
        d = r.json()["data"]
        assert d["attached"] == [rd["id"]]
        a = d["asset"]
        assert a["id"].startswith("sa-") and a["status"] == "active"
        assert a["meta"]["manual"] is True
        ref = a["astRefs"][0]
        assert ref["startLine"] == 10 and ref["endLine"] == 40
        # ruleText → 建规约并挂载
        r2 = client.post(url, json={
            **base, "name": "编译契约", "file": "src/api.ts",
            "ruleText": "- 签名不得变更"})
        d2 = r2.json()["data"]
        assert len(d2["attached"]) == 1
        eff = {e["targetId"]: e for e in
               store.TargetRuleStore.list_effective("proj-cg")}
        assert "签名不得变更" in eff[d2["asset"]["id"]]["rulesMd"]
        # 校验分支
        assert client.post(url, json={**base, "name": "x"}).status_code == 400
        assert client.post(url, json={**base, "file": "f.ts"}).status_code == 400
        assert client.post(url, json={"name": "x", "file": "f.ts"}).status_code == 400
        r4 = client.post(url, json={**base, "name": "回落", "file": "src/y.ts",
                                    "kind": "bogus", "level": "bogus"})
        a4 = r4.json()["data"]["asset"]
        assert a4["kind"] == "entity" and a4["level"] == "implementation"


def test_guard_targets_unified_endpoint(tmp_path, monkeypatch):
    """GET /arch/guard-targets: 三层统一联想(后端分组独立实现)。"""
    root = tmp_path / "repo"
    (root / "apps").mkdir(parents=True)
    (root / "apps" / "main.py").write_text("x = 1")
    (root / "README.md").write_text("r")
    data = isolate_arch(tmp_path, monkeypatch)
    from topoone_app_architect import store as st
    st.ProjectsStore.create({"id": "proj-tg", "name": "tg",
                             "rootPath": str(root), "active": 0})
    st.SemanticAssetsStore.create({
        "id": "sa-t-t-t1", "projectId": "proj-tg", "kind": "entity",
        "level": "implementation", "name": "engine_core", "desc": "",
        "status": "active", "astRefs": [{"file": "apps/main.py"}],
        "scopeType": "files", "scopeKey": "apps/main.py",
        "meta": {}, "createdAt": 0,
    })
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    client = TestClient(build_app(data_dir=data), base_url="http://127.0.0.1")
    with client:
        base = "/api/architect/arch/guard-targets"
        r = client.get(base, params={"project": "proj-tg", "type": "file", "q": "main"})
        d = r.json()["data"]
        assert r.status_code == 200 and d["groups"]["file"] >= 1
        assert any(x["id"] == "apps/main.py" and x["type"] == "file" for x in d["items"])
        r2 = client.get(base, params={"project": "proj-tg", "type": "asset", "q": "engine"})
        d2 = r2.json()["data"]
        assert d2["groups"]["asset"] >= 1
        assert any(x["id"] == "sa-t-t-t1" and x["type"] == "asset" for x in d2["items"])
        r3 = client.get(base, params={"project": "proj-tg", "type": "component", "q": "app"})
        assert r3.status_code == 200
        assert "component" in r3.json()["data"]["groups"]
        r4 = client.get(base, params={"project": "proj-tg", "type": "all", "q": ""})
        assert set(r4.json()["data"]["groups"].keys()) == {"asset", "component", "file"}
