"""需求内容手动编辑 特征测试(cv-279)。

用户裁决: 需求修改=生成新版, 旧版快照行永不改动(append-only), 防止已执行
需求与任务对应错乱(specVer 建卡固化)。编辑链与 architect 对话完善规约同源
(spec_append→spec_confirm→分析缓存→新版 spec 卡落流)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_req_edit_content.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.store as store
from topoone_app_architect.agent.tools.req_agent import edit_spec_content


def _seed(rid: str = "rq-edit") -> None:
    snap = {"title": "原题", "desc": "原始需求目标", "designMd": "d",
            "acceptance": ["验收 1"]}
    store.RequirementsStore.create({"id": rid, "title": "原题"})
    store.RequirementsStore.spec_append(rid, snap, actor="architect",
                                        conv_id="cv-1")
    store.RequirementsStore.spec_confirm(rid)


def _conv() -> str:
    return store.ConversationsStore.create(
        {"projectId": "", "title": "edit", "meta": {}})["id"]


def test_edit_appends_new_version_and_confirms(arch_env):
    _seed()
    res = edit_spec_content("rq-edit", "新题", "改后的需求目标",
                            conv_id=_conv())
    assert res["ok"] and res["ver"] == 2
    row = store.RequirementsStore.get("rq-edit")
    assert int(row.get("activeVer") or 0) == 2
    versions = store.RequirementsStore.spec_versions("rq-edit")
    assert [int(v["ver"]) for v in versions] == [1, 2]
    assert versions[1]["state"] == "confirmed"
    assert versions[1]["source"].get("actor") == "user"
    active = store.RequirementsStore.spec_active("rq-edit")
    assert active["snapshot"]["title"] == "新题"
    assert active["snapshot"]["desc"] == "改后的需求目标"


def test_edit_preserves_old_snapshot_row(arch_env):
    _seed()
    edit_spec_content("rq-edit", "新题", "改后", conv_id=_conv())
    versions = store.RequirementsStore.spec_versions("rq-edit")
    v1 = versions[0]
    assert v1["snapshot"]["desc"] == "原始需求目标"
    assert v1["snapshot"]["title"] == "原题"
    # 旧版快照内容行零改动; state 按既有 confirm 语义隐式收口 superseded
    assert v1["state"] == "superseded"


def test_edit_without_snapshot_rejected(arch_env):
    store.RequirementsStore.create({"id": "rq-bare", "title": "t"})
    res = edit_spec_content("rq-bare", "x", "y")
    assert not res["ok"] and "快照" in str(res.get("error"))


def test_edit_unknown_req_rejected(arch_env):
    res = edit_spec_content("rq-none", "x", "y")
    assert not res["ok"]


def test_edit_lands_new_spec_card_in_conversation(arch_env):
    _seed()
    conv_id = _conv()
    edit_spec_content("rq-edit", "新题", "改后", conv_id=conv_id)
    msgs = store.ConversationsStore.messages(conv_id)
    hit = [m for m in msgs if (m.get("meta") or {}).get("kind") == "specReady"]
    assert hit, "新版 spec 卡应落流"
    meta = hit[-1]["meta"]
    assert int(meta["ver"]) == 2 and meta.get("updated") is True
    assert meta["spec"]["desc"] == "改后"


def test_edit_route_roundtrip(arch_env, client):
    _seed()
    conv_id = _conv()
    r = client.put("/api/architect/requirements/rq-edit/content",
                   json={"title": "路由改", "desc": "路由改后的目标",
                         "convId": conv_id})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is not False
    assert body["data"]["ver"] == 2
    active = store.RequirementsStore.spec_active("rq-edit")
    assert active["snapshot"]["title"] == "路由改"
    r2 = client.put("/api/architect/requirements/rq-none/content",
                    json={"title": "x", "desc": "y"})
    assert r2.status_code == 400
