"""W6 skills 化（2610-B1）测试：arch_assets 表 / 目录覆盖 / REST / prompt 注入。

D-1 裁决验证：表为真相源（同名覆盖内置，清表回退）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from topoone_app_architect import store
from topoone_app_architect.server import build_app


@pytest.fixture()
def app(arch_env):
    return TestClient(build_app(data_dir=arch_env))


def _get(client, path, **params):
    r = client.get(f"/api/architect{path}", params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_store_upsert_and_override(app):
    a1 = store.ArchAssetsStore.upsert({
        "projectId": "p1", "kind": "skill", "name": "req.clarify",
        "description": "自定义澄清", "payload": {"route_hint": "需求含混时"}})
    assert a1["name"] == "req.clarify" and a1["payload"]["route_hint"] == "需求含混时"
    # 同名 upsert = 更新(不增行)
    a2 = store.ArchAssetsStore.upsert({
        "projectId": "p1", "kind": "skill", "name": "req.clarify",
        "description": "自定义澄清 v2", "payload": {"route_hint": "改"}})
    rows = store.ArchAssetsStore.all(kind="skill", project_id="p1")
    assert len([r for r in rows if r["name"] == "req.clarify"]) == 1
    assert a2["description"] == "自定义澄清 v2"


def test_catalog_asset_overrides_builtin(app):
    from topoone_app_architect.sem.skill_catalog import render_skill_catalog, skill_catalog
    base = {s["name"]: s for s in skill_catalog("p-none")}
    assert any(s["source"] == "builtin" for s in base.values())   # 内置目录非空
    store.ArchAssetsStore.upsert({
        "projectId": "p1", "kind": "skill", "name": "req.clarify",
        "description": "覆盖版", "payload": {"route_hint": "何时选我"}})
    cat = {s["name"]: s for s in skill_catalog("p1")}
    assert cat["req.clarify"]["source"] == "asset"
    assert cat["req.clarify"]["route_hint"] == "何时选我"
    md = render_skill_catalog("p1")
    assert "覆盖版" in md and "何时选我" in md
    assert "流程技能" in md and "非可调用工具" in md   # MS-C3 定位修正
    # 清表回退内置
    store.ArchAssetsStore.delete(cat["req.clarify"]["id"])
    cat2 = {s["name"]: s for s in skill_catalog("p1")}
    assert cat2["req.clarify"]["source"] == "builtin"


def test_prompt_contains_skill_catalog(app):
    from topoone_app_architect.agent.cognition.prompt import render_system
    md = render_system({"root": "", "project": None, "model_id": "", "tier": 1})
    assert "## 技能目录(流程技能)" in md
    assert "test.strategy" in md                          # 首批技能(W5 封装)


def test_rest_assets_crud_and_validation(app):
    r = app.post("/api/architect/arch/assets",
                 json={"projectId": "p1", "kind": "skill", "name": "s1",
                       "description": "d", "payload": {}})
    assert r.status_code == 400 and "route_hint" in r.json()["message"]
    r = app.post("/api/architect/arch/assets",
                 json={"projectId": "p1", "kind": "skill", "name": "s1",
                       "description": "d",
                       "payload": {"route_hint": "测试缺口时"}})
    assert r.status_code == 200
    aid = r.json()["data"]["id"]
    rows = _get(app, "/arch/assets", kind="skill", project="p1")
    assert any(x["id"] == aid for x in rows)
    r = app.delete(f"/api/architect/arch/assets/{aid}")
    assert r.json()["data"]["deleted"] is True


def test_test_advice_tool_registered(app):
    from topoone_app_architect.agent.tools.registry import architect_tools
    names = [t["name"] for t in architect_tools()]
    assert "test.advice" in names
    from topoone_app_architect.arch_routes.unit_advice import tool_test_advice
    res = tool_test_advice(5)                              # 无项目上下文 → 明确报错
    assert res["ok"] is False and res["error"] == "no_project"
