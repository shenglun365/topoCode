"""问询卡草稿随会话落库守门(cv-254) — 用户输入=工作产物。

用户实证: 问询卡填写内容从未到后端(库中无新 user 消息)——填写态是
纯前端 reactive 态, 刷新/断线/前端重启即丢。修法: specDraft 同类
conv.meta 草稿(cardId 级幂等 upsert), 呈现层销毁不丢用户工作量;
已答态零写点派生(时间序, 无需持久化)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_choices_draft.py -q
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import store


DRAFT = {"selections": {"1": "vue3"}, "customs": {"2": "自研轻量"},
         "skipped": {"3": True}, "note": "补充说明"}


@pytest.fixture()
def conv():
    c = store.ConversationsStore.create({"id": "conv-cd", "kind": "generic",
                                         "title": "t"})
    yield c
    store.ConversationsStore.delete("conv-cd")


def _put(client, conv_id, body):
    return client.put(f"/api/architect/sessions/{conv_id}/choices-draft",
                      json=body)


def _get(client, conv_id):
    return client.get(f"/api/architect/sessions/{conv_id}/choices-draft")


def test_draft_upsert_and_read(client, conv):
    """cardId 级幂等 upsert + 读取(呈现层恢复源)。"""
    r = _put(client, "conv-cd", {"cardId": "m-1", "draft": DRAFT})
    assert r.status_code == 200 and r.json()["data"]["saved"] is True
    r2 = _put(client, "conv-cd", {"cardId": "m-2", "draft": {"note": "x"}})
    assert r2.status_code == 200
    data = _get(client, "conv-cd").json()["data"]
    assert data["drafts"]["m-1"] == DRAFT
    assert data["drafts"]["m-2"] == {"note": "x"}
    # 同 cardId 再写 → 覆盖不新增(幂等)
    _put(client, "conv-cd", {"cardId": "m-1", "draft": {"note": "改"}})
    data = _get(client, "conv-cd").json()["data"]
    assert data["drafts"]["m-1"] == {"note": "改"} and len(data["drafts"]) == 2


def test_draft_clear_per_card(client, conv):
    """draft=null 清除该卡草稿; 其它卡保留; 全清后键收敛消失。"""
    _put(client, "conv-cd", {"cardId": "m-1", "draft": DRAFT})
    _put(client, "conv-cd", {"cardId": "m-2", "draft": {"note": "x"}})
    _put(client, "conv-cd", {"cardId": "m-1", "draft": None})
    data = _get(client, "conv-cd").json()["data"]
    assert "m-1" not in data["drafts"] and "m-2" in data["drafts"]
    _put(client, "conv-cd", {"cardId": "m-2", "draft": None})
    data = _get(client, "conv-cd").json()["data"]
    assert data["drafts"] == {}
    assert "choicesDraft" not in (store.ConversationsStore.get("conv-cd")
                                  .get("meta") or {})


def test_draft_rejects_bad_payload(client, conv):
    """缺 cardId / draft 非对象 → 400(守门不吞坏形状)。"""
    assert _put(client, "conv-cd", {"draft": DRAFT}).status_code == 400
    assert _put(client, "conv-cd",
                {"cardId": "m-1", "draft": "垃圾"}).status_code == 400
    assert _put(client, "conv-404",
                {"cardId": "m-1", "draft": DRAFT}).status_code == 404


def test_draft_survives_independent_of_other_meta(client, conv):
    """草稿与其它 meta 键(specDraft/analysisMode 等)并存互不干扰。"""
    store.ConversationsStore.update("conv-cd", {"meta": {"specDraft": {
        "title": "x"}, "titleEdited": True}})
    _put(client, "conv-cd", {"cardId": "m-1", "draft": DRAFT})
    meta = store.ConversationsStore.get("conv-cd").get("meta") or {}
    assert meta.get("specDraft") == {"title": "x"}      # 既有键保留
    assert meta.get("titleEdited") is True
    assert meta["choicesDraft"]["m-1"] == DRAFT
