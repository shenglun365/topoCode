"""CallCatalog 统一目录测试(链3③, 整体设计 §4.1 / §6-⑨)。

覆盖: 目录条目与 D10 词表映射 / 词汇别名 / 领域模型路由(roles+light_tasks
配置域各自保留) / 显式 model_id 优先(护栏 R3)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_catalog.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.req_agent as _ra
from topoone_app_architect.agent.compensation.ctx import Purpose
from topoone_app_architect.agent.turns.catalog import (ALIASES, CATALOG,
                                                       resolve_key)


def test_catalog_entries_and_vocab():
    assert len(CATALOG) == 10
    assert set(CATALOG) == {
        "light:summary", "light:probe", "light:distill",
        "role:extract", "role:verify", "role:induce", "role:pseudo",
        "role:evaluate", "role:mine", "design"}
    # D10 词表映射
    assert CATALOG["role:induce"].purpose == Purpose.ROLE_INDUCE
    assert CATALOG["light:probe"].purpose == Purpose.PROBE
    assert CATALOG["design"].purpose == Purpose.DESIGN


def test_aliases_naked_names():
    assert resolve_key("induce") == "role:induce"
    assert resolve_key("summary") == "light:summary"
    assert resolve_key("design") == "design"            # 非别名原样
    assert set(ALIASES) == {"summary", "probe", "distill", "extract",
                            "verify", "induce", "pseudo", "evaluate", "mine"}


def test_role_route_resolves_config(arch_env, monkeypatch):
    """role:* 路由读 agent_roles 注册表配置。"""
    from topoone_app_architect.agent.cognition.roles import set_roles
    set_roles([{"name": "induce", "modelId": "m-induce-x"}])
    entry = CATALOG["role:induce"]
    assert entry.model_route() == "m-induce-x"


def test_light_route_resolves_config(arch_env):
    from topoone_app_architect.arch_routes import store
    store.CollabConfigStore.set("llm.lightTaskModels",
                                '{"summary": "m-sum-y"}')
    assert CATALOG["light:summary"].model_route() == "m-sum-y"
    assert CATALOG["light:probe"].model_route() is None   # 未配置 → None(全局兜底)


def test_catalog_call_explicit_overrides_route(arch_env, monkeypatch):
    """护栏 R3: 显式 model_id > 目录领域路由。"""
    from topoone_app_architect.agent.cognition.roles import set_roles
    set_roles([{"name": "verify", "modelId": "m-role-v"}])
    seen = {}

    def _fake(msgs, **kw):
        seen["model_id"] = kw.get("model_id")
        seen["mode"] = kw.get("mode")
        return {"output": {"ok": True}, "content": ""}

    monkeypatch.setattr(_ra, "llm_sync", _fake)
    from topoone_app_architect.agent.turns.catalog import catalog_call
    r1 = catalog_call("role:verify", [{"role": "user", "content": "x"}],
                      schema={"type": "object"})
    assert seen["model_id"] == "m-role-v"               # 目录路由生效
    r2 = catalog_call("role:verify", [{"role": "user", "content": "x"}],
                      schema={"type": "object"}, model_id="m-explicit")
    assert seen["model_id"] == "m-explicit"             # 显式优先
    assert r1["ok"] and r2["ok"]


def test_catalog_call_text_mode_reads_content(arch_env, monkeypatch):
    """无 schema(纯文本)通道产出在 content。"""
    monkeypatch.setattr(_ra, "llm_sync",
                        lambda msgs, **kw: {"content": "伪码走查文本", "output": None})
    from topoone_app_architect.agent.turns.catalog import catalog_call
    r = catalog_call("role:pseudo", [{"role": "user", "content": "x"}])
    assert r["ok"] and r["content"] == "伪码走查文本"
