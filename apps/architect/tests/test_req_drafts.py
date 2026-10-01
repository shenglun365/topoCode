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
