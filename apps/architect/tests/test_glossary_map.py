"""词典检索侧映射(P2)回归——expand_query 纯函数 + ctx.search 扩展集成。

Run: cd <repo> && python -m pytest apps/architect/tests/test_glossary_map.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect.agent.memory.glossary_map import expand_query  # noqa: E402
from topoone_app_architect.agent.memory.units import ctx_search  # noqa: E402
from topoone_app_architect import store  # noqa: E402


# ── 纯函数 ──────────────────────────────────────────────────────────

_ROWS = [
    {"term": "网关", "alias": ["Gateway", "GW"]},
    {"term": "结算中心", "alias": ["清结算"]},
    {"term": "", "alias": ["空词条"]},
]

def test_expand_query_hits_alias_returns_canonical_and_siblings():
    out = expand_query("gw 超时排查", _ROWS)
    assert out == ["网关", "Gateway"]


def test_expand_query_hits_term_returns_aliases():
    out = expand_query("网关超时", _ROWS)
    assert set(out) == {"Gateway", "GW"}


def test_expand_query_no_hit_or_guards():
    assert expand_query("支付回调", _ROWS) == []
    assert expand_query("", _ROWS) == []
    assert expand_query("网关", None) == []
    assert expand_query("网关", [None, "bad", {}]) == []


def test_expand_query_caps_and_no_self_dup():
    rows = [{"term": "网关", "alias": ["GW", "Gateway", "入口", "代理", "路由"]}]
    out = expand_query("网关异常", rows, max_extra=3)
    assert out == ["GW", "Gateway", "入口"]
    # query 已含的变体不重复
    out2 = expand_query("网关/GW 异常", rows)
    assert "GW" not in "".join(out2) or "gw" not in [x.lower() for x in out2]


# ── ctx.search 集成 ─────────────────────────────────────────────────

def _setup_env(tmp_path, monkeypatch):
    import topoone_app_architect.ctx as C
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    return C.setup(data_dir=data)


def test_ctx_search_glossary_expansion_merges_hits(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"title": "网关会话", "projectId": "pj-g"})
    store.GlossaryStore.create("pj-g", term="网关", alias=["GW"])
    # 只含别名单词的单元(原词检索不可达, 扩展后可达)
    store.ContextUnitsStore.create({
        "conversationId": conv["id"], "projectId": "pj-g",
        "type": "artifact", "title": "GW 部署说明",
        "content": "GW 服务部署在边缘节点", "refs": {}, "importance": 0})
    store.ContextUnitsStore.create({
        "conversationId": conv["id"], "projectId": "pj-g",
        "type": "note", "title": "网关超时记录", "content": "网关 504", "refs": {}})

    out = ctx_search("网关", conversation_id=conv["id"])
    assert "网关超时记录" in out
    assert "GW 部署说明" in out          # 经「GW」扩展命中
    assert "词典扩展: GW" in out
    assert "经「GW」扩展命中" in out


def test_ctx_search_no_glossary_unchanged(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"title": "普通会话", "projectId": "pj-n"})
    store.ContextUnitsStore.create({
        "conversationId": conv["id"], "projectId": "pj-n",
        "type": "note", "title": "普通记录", "content": "普通内容", "refs": {}})
    out = ctx_search("普通", conversation_id=conv["id"])
    assert "普通记录" in out
    assert "词典扩展" not in out
