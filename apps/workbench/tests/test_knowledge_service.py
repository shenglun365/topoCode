"""workbench knowledge.* RPC 套件（MS1 §4.2）——进程内注册直调，不起 ZMQ/HTTP。

范本：packages/core/tests/test_db_layout.py:128-145（注册后 srv.methods["x"](...)）。
"""
import json

import pytest

from topoone.db.manager import MultiDBManager
from topoone.rpc.service_app import MethodServer
from topoone_app_workbench.server.knowledge_service import register_knowledge_methods


@pytest.fixture
def svc(tmp_path):
    multi_db = MultiDBManager(str(tmp_path / "wb"))
    server = MethodServer()
    register_knowledge_methods(server, multi_db)

    def call(name, **params):
        return server.methods[name](**params)

    return call


def test_create_doc_defaults(svc):
    doc = svc("knowledge.createDoc", title="T1", content="c" * 300, tags={"lifecycle": ["seed"]})
    assert doc["id"].startswith("doc-") and len(doc["id"]) == 12  # doc-{8hex}
    assert doc["status"] == "draft"
    assert doc["description"] == "c" * 200  # description = content[:200]
    # 契约注：createDoc 返回原始行，tags 仍为 JSON 字符串（listDocs/getDoc 才反序列化）
    assert json.loads(doc["tags"]) == {"lifecycle": ["seed"]}


def test_get_doc_roundtrip_and_missing(svc):
    created = svc("knowledge.createDoc", title="T", content="body")
    got = svc("knowledge.getDoc", id=created["id"])
    assert got["title"] == "T" and got["content"] == "body"
    assert svc("knowledge.getDoc", id="doc-nope") is None  # 缺失 → None 非异常


def test_list_search_and_pinned_priority(svc):
    d1 = svc("knowledge.createDoc", title="alpha design", content="x")
    d2 = svc("knowledge.createDoc", title="beta report", content="y")
    svc("knowledge.createDoc", title="gamma", content="z")

    all_docs = svc("knowledge.listDocs")
    assert len(all_docs) == 3

    hit = svc("knowledge.listDocs", search="alpha")
    assert [d["id"] for d in hit] == [d1["id"]]

    # pinned 优先于 updated 排序
    svc("knowledge.updateDoc", id=d2["id"], pinned=True)
    ordered = svc("knowledge.listDocs")
    assert ordered[0]["id"] == d2["id"]


def test_update_doc_whitelist_and_tags_merge(svc):
    doc = svc("knowledge.createDoc", title="T", content="c1",
              tags={"lifecycle": ["a"], "techStack": ["vue"]})

    updated = svc("knowledge.updateDoc", id=doc["id"],
                  title="T2", status="published",
                  tags={"lifecycle": ["b"], "purpose": ["ref"]},  # merge: 既有键整键替换+新键追加
                  hacker_field="nope")
    assert updated["title"] == "T2" and updated["status"] == "published"
    assert updated["tags"] == {"lifecycle": ["b"], "techStack": ["vue"], "purpose": ["ref"]}
    assert "hacker_field" not in updated  # 白名单外字段被忽略


def test_delete_doc(svc):
    doc = svc("knowledge.createDoc", title="T", content="")
    assert svc("knowledge.deleteDoc", id=doc["id"]) in (None, True, {})
    assert svc("knowledge.getDoc", id=doc["id"]) is None


def test_get_graph_bipartite(svc):
    d1 = svc("knowledge.createDoc", title="A", content="", tags={"lifecycle": ["seed", "grow"]})
    d2 = svc("knowledge.createDoc", title="B", content="", tags={"lifecycle": ["seed"]})

    g = svc("knowledge.getGraph")
    node_ids = {n["id"] for n in g["nodes"]}
    assert {d1["id"], d2["id"]} <= node_ids
    assert "tag-lifecycle-seed" in node_ids and "tag-lifecycle-grow" in node_ids
    # tag 节点去重（seed 被 2 篇共享只 1 个节点）
    assert sum(1 for n in g["nodes"] if n["id"] == "tag-lifecycle-seed") == 1
    # 边端点闭合：doc → tag
    doc_ids = {d1["id"], d2["id"]}
    for e in g["edges"]:
        assert e["source"] in doc_ids and e["target"] in node_ids


def test_get_dimensions_sorted_dedup(svc):
    svc("knowledge.createDoc", title="A", content="",
        tags={"lifecycle": ["b", "a"], "techStack": ["vue"]})
    svc("knowledge.createDoc", title="B", content="",
        tags={"lifecycle": ["a"], "abstraction": ["L0"], "purpose": ["ref"]})

    dims = svc("knowledge.getDimensions")
    assert dims["lifecycle"] == ["a", "b"]
    assert dims["techStack"] == ["vue"]
    assert dims["abstraction"] == ["L0"]
    assert dims["purpose"] == ["ref"]


def test_get_dimensions_empty(svc):
    assert svc("knowledge.getDimensions") == {
        "lifecycle": [], "techStack": [], "abstraction": [], "purpose": []
    }
