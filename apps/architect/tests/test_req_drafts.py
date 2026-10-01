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


def test_draft_store_list_order_and_copy_missing():
    a = ReqDraftsStore.create(PID, "A")
    b = ReqDraftsStore.create(PID, "B")
    rows = ReqDraftsStore.list(PID)
    ids = [r["id"] for r in rows]
    assert {a["id"], b["id"]} <= set(ids)
    assert ReqDraftsStore.copy("rd-nonexist") is None


def test_draft_ai_split_agent_blocks():
    from topoone_app_architect.arch_routes.req_drafts import split_agent_blocks
    md = "# 需求\n\n正文A\n\n```agent\n补充性能指标\n```\n\n正文B\n\n```agent\n再补充验收\n```\n"
    clean, embedded = split_agent_blocks(md)
    assert "```agent" not in clean and "正文A" in clean and "正文B" in clean
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
