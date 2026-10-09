"""需求草稿（批B）：表/Store/CRUD API 生命周期测试。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio, json
import pytest

import topoone_app_architect.ctx as C
from topoone_app_architect.store import ProjectsStore, ReqDraftsStore

PID = "proj-b1drafts"


def _ctx_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path / "data"))
    C._db = None
    C._kb = None
    C.setup(data_dir=str(tmp_path / "data"))
    ProjectsStore.upsert(PID, {"name": "t", "rootPath": str(tmp_path)})
    return json.loads


def _body(resp):
    return json.loads(resp.body) if hasattr(resp, "body") else resp


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    _ctx_setup(tmp_path, monkeypatch)


def test_draft_crud_lifecycle():
    from topoone_app_architect.arch_routes import req_drafts as api

    class _Req:
        def __init__(self, payload):
            self._p = payload

        async def json(self):
            return self._p

    # 新建
    out = _body(asyncio.run(api.api_req_drafts_create(_Req({"project": PID, "title": "订单需求", "contentMd": "# 订单\n内容"}))))
    d = out["data"]
    assert d["id"].startswith("rd-") and d["status"] == "editing"
    # 列表：携带摘要、不带正文
    out = _body(asyncio.run(api.api_req_drafts_list(project=PID)))
    rows = out["data"]["drafts"]
    assert len(rows) == 1 and rows[0]["excerpt"] == "# 订单" and "contentMd" not in rows[0]
    # 保存
    out = _body(asyncio.run(api.api_req_drafts_update(d["id"], _Req({"contentMd": "# v2"}))))
    assert out["data"]["contentMd"] == "# v2"
    assert out["data"]["updatedAt"] >= d["updatedAt"]
    # 归档只读
    ReqDraftsStore.update(d["id"], {"status": "archived", "publishedConvId": "cv-1", "publishedReqId": "req-1"})
    out = _body(asyncio.run(api.api_req_drafts_update(d["id"], _Req({"contentMd": "# v3"}))))
    assert out.get("code") == 409
    # 续写副本：editing 态、parent 溯源、不带未采纳产物
    ReqDraftsStore.update(d["id"], {"lastProposedMd": "AI 产物"})
    out = _body(asyncio.run(api.api_req_drafts_copy(d["id"], _Req({}))))
    cp = out["data"]
    assert cp["status"] == "editing" and cp["parentId"] == d["id"]
    assert cp["contentMd"] == "# v2" and cp["lastProposedMd"] == ""
    # 删除
    out = _body(asyncio.run(api.api_req_drafts_delete(cp["id"])))
    assert out["data"]["deleted"] == cp["id"]
    assert _body(asyncio.run(api.api_req_drafts_delete(cp["id"]))).get("code") == 404


def test_draft_ai_split_strips_comments():
    """topo-cmd 注释行(# //)剥离——模板引导注释不进指令; 全注释块不产生空指令。"""
    from topoone_app_architect.arch_routes.req_drafts import split_agent_blocks
    md = "前文\n\n```topo-cmd\n# 模板注释\n// 注释2\n润色本文措辞\n```\n\n后文"
    clean, emb = split_agent_blocks(md)
    assert "前文" in clean and "后文" in clean and "topo-cmd" not in clean
    assert emb == ["润色本文措辞"]
    # 全注释块 → 指令列表为空(不产生空串指令)
    _, emb2 = split_agent_blocks("```topo-cmd\n# 只有注释\n```")
    assert emb2 == []


def test_draft_tags_store_and_api():
    """tags: 归一(去重/trim/截限64B×20)/copy 继承/all_tags 聚合/API PUT+归档拒绝。"""
    from topoone_app_architect.arch_routes import req_drafts as api

    class _Req:
        def __init__(self, payload):
            self._p = payload

        async def json(self):
            return self._p

    d = ReqDraftsStore.create(PID, "T", tags=[" 需求 ", "需求", "分析"])
    assert d["tags"] == ["需求", "分析"]                      # trim + 去重保序
    # 聚合: 引用计数(先于后续覆盖校验)
    ReqDraftsStore.create(PID, "T2", tags=["需求", "备忘录"])
    agg = {x["name"]: x["count"] for x in ReqDraftsStore.all_tags(PID)}
    assert agg["需求"] == 2 and agg["分析"] == 1 and agg["备忘录"] == 1
    # 64B 截断 + 复制继承
    ReqDraftsStore.update(d["id"], {"tags": ["a" * 80, "设计"]})
    row = ReqDraftsStore.get(d["id"])
    assert row["tags"] == ["a" * 64, "设计"]                  # 64B 截断(80 ASCII→64)
    cp = ReqDraftsStore.copy(d["id"])
    assert cp["tags"] == row["tags"]
    # API: PUT tags 落库
    out = _body(asyncio.run(api.api_req_drafts_update(d["id"], _Req({"tags": ["评审", "需求"]}))))
    assert out["data"]["tags"] == ["评审", "需求"]
    # API: 归档态 tags 只读拒绝(409)
    ReqDraftsStore.update(d["id"], {"status": "archived"})
    out = _body(asyncio.run(api.api_req_drafts_update(d["id"], _Req({"tags": ["y"]}))))
    assert out["code"] == 409
    # 联想端点
    out = _body(asyncio.run(api.api_req_drafts_tags(project=PID)))
    assert any(x["name"] == "评审" for x in out["data"]["tags"])


def test_draft_store_list_order_and_copy_missing():
    a = ReqDraftsStore.create(PID, "A")
    b = ReqDraftsStore.create(PID, "B")
    rows = ReqDraftsStore.list(PID)
    ids = [r["id"] for r in rows]
    assert {a["id"], b["id"]} <= set(ids)
    assert ReqDraftsStore.copy("rd-nonexist") is None


def test_draft_ai_split_agent_blocks():
    from topoone_app_architect.arch_routes.req_drafts import split_agent_blocks
    md = "# 需求\n\n正文A\n\n```topo-cmd\n补充性能指标\n```\n\n正文B\n\n```topo-cmd\n再补充验收\n```\n"
    clean, embedded = split_agent_blocks(md)
    assert "```topo-cmd" not in clean and "正文A" in clean and "正文B" in clean
    assert embedded == ["补充性能指标", "再补充验收"]
    # 无标记块
    clean2, emb2 = split_agent_blocks("纯文本")
    assert clean2 == "纯文本" and emb2 == []


def test_draft_ai_job_and_endpoint(monkeypatch):
    """ai 端点提交 + 执行体产物落 last_proposed_md（run_tools_loop 打桩）。"""
    import topoone_app_architect.arch_routes.req_drafts as api
    from topoone_app_architect.store import ReqDraftsStore

    d = ReqDraftsStore.create(PID, "AI", "# 原\n正文")
    ReqDraftsStore.update(d["id"], {"lastProposedMd": "旧产物"})

    # 执行体打桩：不走真实 LLM
    calls = {}

    def _fake_loop(msgs, **kw):
        calls["allowed"] = kw.get("allowed")
        calls["user"] = msgs[-1]["content"]
        return {"content": "# 新版草稿全文"}

    from topoone_app_architect.agent.tools import req_agent as _ra
    monkeypatch.setattr(_ra, "run_tools_loop", _fake_loop)

    class _Req:
        async def json(self):
            return {"project": PID, "preset": "review"}

    out = _body(asyncio.run(api.api_req_drafts_ai(d["id"], _Req())))
    r = out["data"]
    assert r.get("started") is True and r["job"]["id"].startswith("sj-")

    # 等作业线程完成(LLM 信号量串行, 同步执行体秒回)
    import time as _t
    from topoone_app_architect.store import SemanticJobsStore
    for _ in range(50):
        row = SemanticJobsStore.get(r["job"]["id"])
        if row and row["state"] in ("done", "failed"):
            break
        _t.sleep(0.1)
    assert row["state"] == "done", row.get("result")
    # 产物落 last_proposed_md；content_md 不动
    d2 = ReqDraftsStore.get(d["id"])
    assert d2["lastProposedMd"] == "# 新版草稿全文"
    assert d2["contentMd"] == "# 原\n正文"
    # 白名单只读 + 指令进上下文 + 标记块合并
    assert "asset.semantic.search" in calls["allowed"] and "req.propose" not in calls["allowed"]
    assert "需求审核" in calls["user"] and "# 原" in calls["user"]

    # 归档态拒绝
    ReqDraftsStore.update(d["id"], {"status": "archived"})
    out = _body(asyncio.run(api.api_req_drafts_ai(d["id"], _Req())))
    assert out.get("code") == 409


def test_draft_adopt(monkeypatch):
    """采纳：contentMd ← lastProposedMd 并清空；归档/空产物拒绝。"""
    from topoone_app_architect.arch_routes import req_drafts as api
    from topoone_app_architect.store import ReqDraftsStore

    d = ReqDraftsStore.create(PID, "adopt", "# v1")
    # 空产物拒绝
    out = _body(asyncio.run(api.api_req_drafts_adopt(d["id"])))
    assert out.get("code") == 400
    ReqDraftsStore.update(d["id"], {"lastProposedMd": "# v2 AI", "lastProposedAt": 1})
    out = _body(asyncio.run(api.api_req_drafts_adopt(d["id"])))
    row = out["data"]
    assert row["contentMd"] == "# v2 AI" and row["lastProposedMd"] == "" and row["lastProposedAt"] == 0
    # 归档拒绝
    ReqDraftsStore.update(d["id"], {"status": "archived", "lastProposedMd": "# v3"})
    out = _body(asyncio.run(api.api_req_drafts_adopt(d["id"])))
    assert out.get("code") == 409


def test_draft_publish_flow(monkeypatch):
    """发布：新会话 propose / 未完结覆盖 409→overwrite amend / 归档回填。"""
    import topoone_app_architect.arch_routes.req_drafts as api
    from topoone_app_architect import store
    from topoone_app_architect.agent.planning import req_spec

    d = store.ReqDraftsStore.create(PID, "发布", "# 需求A\n内容")

    class _Req:
        def __init__(self, payload):
            self._p = payload

        async def json(self):
            return self._p

    # 打桩 apply_spec_payload：不落真实需求库，验证调用与回执
    stub_calls = {}

    def _fake_apply(payload, req_id="", project="", root=""):
        stub_calls["payload"] = payload
        stub_calls["req_id"] = req_id
        rid = req_id or "req-stub-1"
        stub_calls.setdefault("rids", []).append(rid)
        return {"ok": True, "requirementId": rid, "summary": "stub"}

    monkeypatch.setattr(req_spec, "apply_spec_payload", _fake_apply)

    # ① 新会话发布
    out = _body(asyncio.run(api.api_req_drafts_publish(d["id"], _Req({"project": PID}))))
    r = out["data"]
    assert r["requirementId"] == "req-stub-1" and r["amended"] is False
    conv = store.ConversationsStore.get(r["convId"])
    assert conv and conv.get("title") == "发布"
    # 草稿已归档 + 回填
    d2 = store.ReqDraftsStore.get(d["id"])
    assert d2["status"] == "archived" and d2["publishedReqId"] == "req-stub-1"
    # 会话消息已写
    msgs = store.ConversationsStore.messages(r["convId"])
    assert any("需求草稿发布" in (m.get("content") or "") for m in msgs)

    # ② 已有会话 + 未完结需求 → 409；overwrite → amend
    d3 = store.ReqDraftsStore.create(PID, "再发布", "# 需求B")
    conv2 = store.ConversationsStore.create({
        "kind": "requirement", "projectId": PID, "title": "目标会话",
        "status": "active", "roles": ["architect"], "tags": {"modules": [], "groups": []},
        "reqId": "req-live-1"})
    store.RequirementsStore.create({
        "id": "req-live-1", "projectId": PID, "title": "既有需求",
        "status": "draft", "requirementMd": "# 旧"})
    monkeypatch.setattr(req_spec, "_plan_delivered", lambda rid: False)  # 未完结
    out = _body(asyncio.run(api.api_req_drafts_publish(
        d3["id"], _Req({"project": PID, "targetConvId": conv2["id"]}))))
    assert out.get("code") == 409
    out = _body(asyncio.run(api.api_req_drafts_publish(
        d3["id"], _Req({"project": PID, "targetConvId": conv2["id"], "overwrite": True}))))
    r2 = out["data"]
    assert r2["amended"] is True and stub_calls["req_id"] == "req-live-1"
    assert store.ReqDraftsStore.get(d3["id"])["status"] == "archived"

    # ③ 已完结需求 → 无需 overwrite 直接发布(propose 语义由打桩承载)
    d4 = store.ReqDraftsStore.create(PID, "完结后", "# 需求C")
    monkeypatch.setattr(req_spec, "_plan_delivered", lambda rid: True)
    out = _body(asyncio.run(api.api_req_drafts_publish(
        d4["id"], _Req({"project": PID, "targetConvId": conv2["id"]}))))
    assert out.get("data", {}).get("requirementId")


def test_sessions_picker():
    """发布目标选择器：活跃过滤 + 多关键字 AND→OR + 分页。"""
    from topoone_app_architect.arch_routes import req_drafts as sapi
    from topoone_app_architect import store

    def _mk(title, status="active", summary=""):
        c = store.ConversationsStore.create({
            "kind": "requirement", "projectId": PID, "title": title,
            "status": status, "roles": ["architect"],
            "tags": {"modules": [], "groups": []}})
        if summary:
            store.ConversationsStore.update(c["id"], {"summary": summary})
        return c["id"]

    _mk("订单 支付 对账")
    _mk("订单 退款")
    _mk("归档旧会话", status="archived")
    _mk("库存 盘点")

    out = _body(asyncio.run(sapi.list_sessions_picker(project=PID)))
    r = out["data"]
    # 活跃过滤：归档不显示；总数 3
    assert r["total"] == 3 and len(r["items"]) == 3
    # AND 匹配
    out = _body(asyncio.run(sapi.list_sessions_picker(project=PID, kw="订单 退款")))
    r = out["data"]
    assert r["total"] == 1 and r["orFallback"] is False
    # AND 无结果 → OR 降级（订单×2 + 盘点×1 = 3）
    out = _body(asyncio.run(sapi.list_sessions_picker(project=PID, kw="订单 盘点")))
    r = out["data"]
    assert r["total"] == 3 and r["orFallback"] is True
    # 分页：每页 2，第 2 页
    out = _body(asyncio.run(sapi.list_sessions_picker(project=PID, limit=2, offset=2)))
    r = out["data"]
    assert r["total"] == 3 and len(r["items"]) == 1
    # 关键字超限截断(6 个取前 5)
    out = _body(asyncio.run(sapi.list_sessions_picker(project=PID, kw="a b c d e f")))
    assert len(out["data"]["keywords"]) == 5


def test_skills_registry_and_endpoint():
    """B1 技能注册表: 首批三技能(自 _PRESETS 等价迁移) + GET /skills。"""
    from topoone_app_architect.agent import skills
    from topoone_app_architect.arch_routes import req_drafts as api

    assert skills.get_skill("generate") is not None
    assert "补齐背景/场景/功能点/约束/验收标准" in skills.get_skill("generate").instruction
    assert skills.get_skill("nonexist") is None
    # 只读白名单单源: 注册表工具 = 原 _AI_TOOLS 全集
    assert "asset.semantic.search" in skills.SKILL_TOOLS_READONLY
    assert skills.get_skill("review").tools == skills.SKILL_TOOLS_READONLY
    # 端点: 域过滤 + 卡片字段(指令全文不列)
    out = _body(asyncio.run(api.api_skills_list("draft")))
    ids = [x["id"] for x in out["data"]["skills"]]
    assert {"generate", "review", "relate"} <= set(ids)
    assert all("instruction" not in x for x in out["data"]["skills"])


def test_topo_skill_fence_resolution():
    """B1 topo-skill 围栏: 回调命中注入技能指令+附加; 未命中按自由指令。"""
    from topoone_app_architect.agent import skills
    from topoone_app_architect.arch_routes.req_drafts import split_agent_blocks

    md = "正文\n\n```topo-skill: review\n额外关注性能\n```\n"
    clean, emb = split_agent_blocks(md, resolve_skill=skills.get_skill)
    assert "topo-skill" not in clean and "正文" in clean
    assert len(emb) == 1
    assert "需求审核" in emb[0] and "额外关注性能" in emb[0]
    # 未注册技能 id: 附加文本按自由指令(不虚构)
    _, emb2 = split_agent_blocks("```topo-skill: nope\n做点什么\n```",
                                 resolve_skill=skills.get_skill)
    assert emb2 == ["做点什么"]
    # 不传回调(存量调用形态): 行为等同未命中
    _, emb3 = split_agent_blocks("```topo-skill: review\n做点什么\n```")
    assert emb3 == ["做点什么"]


def test_skill_run_job_equivalence(monkeypatch):
    """skill_run 作业: skill 字段与存量 preset 等价; custom 仅指令也可跑。"""
    import topoone_app_architect.arch_routes.req_drafts as api
    from topoone_app_architect.store import ReqDraftsStore

    d = ReqDraftsStore.create(PID, "S", "# 原\n正文")

    def _fake_loop(msgs, **kw):
        return {"content": "# 技能新版"}

    from topoone_app_architect.agent.tools import req_agent as _ra
    monkeypatch.setattr(_ra, "run_tools_loop", _fake_loop)

    class _Req:
        def __init__(self, payload):
            self._p = payload

        async def json(self):
            return self._p

    from topoone_app_architect.sem import job_runner as _jr
    out = _body(asyncio.run(api.api_req_drafts_ai(
        d["id"], _Req({"project": PID, "skill": "review"}))))
    r = out["data"]
    assert r.get("started") is True and r["job"]["kind"] == "skill_run"
    import time as _t
    from topoone_app_architect.store import SemanticJobsStore
    for _ in range(50):
        row = SemanticJobsStore.get(r["job"]["id"])
        if row and row["state"] in ("done", "failed"):
            break
        _t.sleep(0.1)
    assert row["state"] == "done", row.get("result")
    assert ReqDraftsStore.get(d["id"])["lastProposedMd"] == "# 技能新版"
    # scope 携带 skillId+preset(双字段, 存量幂等键兼容)
    assert row["scope"]["skillId"] == "review" and row["scope"]["preset"] == ""
