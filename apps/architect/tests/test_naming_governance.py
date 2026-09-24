"""M3 命名治理测试 — plan-C-M0.md §7.2/§7.3。

覆盖:
  - 命名规约 CRUD + 场景检索（R7）+ induce 归纳提议（pending→active 确认）
  - 术语表 CRUD + 项目文档导入（JSON/行式解析、越界拒绝、source_ref）
  - 墓碑参考池查询
  - 资产命名历史（墓碑 + overlay 改名重放 + 资产行内溯源）

Run: cd <repo> && PYTHONPATH=apps/architect python -m pytest apps/architect/tests/test_naming_governance.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.ctx as C  # noqa: E402
_SEM_MODULE_NAMES = ("taxonomy", "paths", "codegraph", "scope", "incremental", "context", "anchors", "engine")


def _patch_all(monkeypatch, name, value):
    """A1 拆分后名字可能绑定在 facade 或任一 sem 模块 —— 全部绑定位统一 patch。"""
    import importlib
    import topoone_app_architect.arch_routes.semantic_assets as _sa
    if hasattr(_sa, name):
        monkeypatch.setattr(_sa, name, value)
    for _mn in _SEM_MODULE_NAMES:
        _mod = importlib.import_module(f"topoone_app_architect.sem.{_mn}")
        if hasattr(_mod, name):
            monkeypatch.setattr(_mod, name, value)


from topoone_app_architect.arch_routes import semantic_assets as S
from topoone_app_architect.sem import context as _sem_context
from topoone_app_architect.arch_routes.naming import (  # noqa: E402
    _parse_terms_file)
from topoone_app_architect.store import (  # noqa: E402
    GlossaryStore, NameTombstoneStore, NamingConventionStore,
    SemanticAssetsStore, UserOverlayStore)


def _ctx_setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.setup(data_dir=data)


def _pid(tmp_path):
    return S.project_id_for(str(tmp_path), None)


def _fake_collect(monkeypatch, root):
    node = {"id": "n1", "kind": "func", "name": "create_order",
            "qualified_name": "create_order", "file_path": "m.py",
            "start_line": 1, "end_line": 10, "signature": "def create_order():",
            "docstring": "", "return_type": ""}

    def _collect(r, project, scope_type, scope_key, files, symbols):
        return {"root": root, "project": project, "files": files or [],
                "symbols": symbols or [], "nodes": [node],
                "table": {"create_order": node},
                "edges": [], "text": "", "srcHash": "h1", "source": "live",
                "implDetails": {}, "calleeNames": {}}
    _patch_all(monkeypatch, "collect_context", _collect)


# ── 命名规约 ──────────────────────────────────────────────────

class TestConventions:
    def test_crud_and_scenario_filter(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        a = NamingConventionStore.create(pid, "过程用动宾结构", scenarios=["extract"])
        b = NamingConventionStore.create(pid, "验收条目给可判定标准", scenarios=["accept"])
        assert [c["id"] for c in NamingConventionStore.list(pid, scenario="extract")] \
            == [a["id"]]
        all_rows = NamingConventionStore.list(pid, status="active")
        assert len(all_rows) == 2
        NamingConventionStore.update(a["id"], {"ruleText": "过程资产用动宾结构"})
        assert NamingConventionStore.get(a["id"])["ruleText"] == "过程资产用动宾结构"
        NamingConventionStore.delete(a["id"])
        assert NamingConventionStore.get(a["id"]) is None

    def test_induce_pending_then_confirm(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        row = NamingConventionStore.create(pid, "归纳出的规约", scenarios=["naming"],
                                           source="induced", author="agent",
                                           status="pending")
        assert row["status"] == "pending"
        # pending 不进入 active 列表（不注入 agent）
        assert NamingConventionStore.list(pid, scenario="naming") == []
        # 设计者确认 → active
        NamingConventionStore.update(row["id"], {"status": "active"})
        got = NamingConventionStore.get(row["id"])
        assert got["status"] == "active" and got["source"] == "induced"
        assert [c["id"] for c in NamingConventionStore.list(pid, scenario="naming")] \
            == [row["id"]]

    def test_scenario_required(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        from topoone_app_architect.arch_routes.naming import _validate_scenarios
        assert _validate_scenarios([]) is not None
        assert _validate_scenarios(None) is not None
        assert _validate_scenarios(["hacking"]) is not None
        assert _validate_scenarios(["extract"]) is None

    def test_propose_convention_tool(self, tmp_path, monkeypatch):
        """A4: agent 工具 convention.propose → pending 提案（设计者确认才生效）。"""
        _ctx_setup(tmp_path, monkeypatch)
        from topoone_app_architect.arch_routes.req_agent import run_arch_tool
        out = run_arch_tool("convention.propose",
                            {"ruleText": "服务以 XxxService 结尾",
                             "scenarios": ["naming"]},
                            str(tmp_path), None)
        assert "error" not in out, out
        assert out["status"] == "pending"
        pid = _pid(tmp_path)
        rows = NamingConventionStore.list(pid, status="pending")
        assert len(rows) == 1 and rows[0]["id"] == out["id"]
        assert rows[0]["source"] == "induced"
        # pending 不进入 active 列表（不注入 agent）
        assert NamingConventionStore.list(pid, scenario="naming") == []
        # 缺 ruleText → 错误
        out2 = run_arch_tool("convention.propose", {"ruleText": ""},
                             str(tmp_path), None)
        assert "error" in out2


# ── 术语表 ────────────────────────────────────────────────────

class TestGlossary:
    def test_crud_and_search(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        row = GlossaryStore.create(pid, "幂等", alias=["idempotent"],
                                   definition="重复执行结果一致")
        assert GlossaryStore.list(pid, q="幂等")[0]["id"] == row["id"]
        assert GlossaryStore.list(pid, q="不存在") == []
        GlossaryStore.update(row["id"], {"definition": "重复调用不产生副作用"})
        assert GlossaryStore.get(row["id"])["definition"] == "重复调用不产生副作用"
        GlossaryStore.delete(row["id"])
        assert GlossaryStore.get(row["id"]) is None

    def test_import_json_and_lines(self, tmp_path, monkeypatch):
        assert _parse_terms_file('[{"term": "A", "definition": "a定义"}]', "x.json") \
            == [{"term": "A", "definition": "a定义", "alias": ""}]
        assert _parse_terms_file('{"B": "b定义"}', "x.json") \
            == [{"term": "B", "definition": "b定义"}]
        lines = _parse_terms_file("- 幂等: 重复执行结果一致\n超时 | 3s 中止\n", "x.md")
        assert [t["term"] for t in lines] == ["幂等", "超时"]
        assert lines[0]["definition"] == "重复执行结果一致"
        assert _parse_terms_file("随便一段文字", "x.md") == []

    def test_import_endpoint_path_and_boundary(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        (tmp_path / "glossary.md").write_text(
            "- 订单: 一次购买行为的记录\n- 幂等: 重复执行结果一致\n",
            encoding="utf-8")
        pid = _pid(tmp_path)
        # 正常导入
        from topoone_app_architect.arch_routes.naming import api_glossary_import
        res = _call(lambda: api_glossary_import(_req(
            {"root": str(tmp_path), "path": "glossary.md"})))
        res = res.get("data") or {}
        assert res["imported"] == 2
        terms = GlossaryStore.list(pid, q="订单")
        assert terms and terms[0]["sourceRef"] == "glossary.md" \
            and terms[0]["source"] == "doc_import"
        # 越界拒绝
        res2 = _call(lambda: api_glossary_import(_req(
            {"root": str(tmp_path), "path": "../escape.md"})))
        assert res2.get("_error") and "越界" in res2["_error"]


def _req(body):
    class _Req:
        async def json(self):
            return body

    return _Req()


def _call(coro_factory):
    """运行 async 端点协程；解包 ok/err（err 为 JSONResponse）为 dict。"""
    import asyncio
    import json as _json
    from fastapi.responses import JSONResponse
    out = asyncio.run(coro_factory())
    if isinstance(out, JSONResponse):
        body = _json.loads(out.body.decode("utf-8"))
        body["_error"] = body.get("message", "")
        return body
    if isinstance(out, dict) and "code" in out and out["code"] != 0:
        out["_error"] = out.get("message", "")
    return out


# ── 墓碑 + 命名历史 ───────────────────────────────────────────

class TestNamesHistory:
    def test_tombstone_search(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        NameTombstoneStore.add(pid, "创建订单(旧)", file_path="m.py",
                               symbol="create_order", source="llm")
        rows = NameTombstoneStore.search(pid, q="旧")
        assert rows and rows[0]["name"] == "创建订单(旧)"
        assert NameTombstoneStore.search(pid, q="不存在的") == []

    def test_asset_names_history(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _fake_collect(monkeypatch, str(tmp_path))
        pid = _pid(tmp_path)
        res = S.save_agent_assets(str(tmp_path), None, [{
            "name": "创建订单", "kind": "process", "level": "implementation",
            "desc": "创建订单过程",
            "astRefs": [{"file": "m.py", "symbol": "create_order",
                         "startLine": 1, "endLine": 10}]},
        ])
        asset = res["saved"][0]
        # 墓碑：该锚点的历史旧名
        NameTombstoneStore.add(pid, "下单", file_path="m.py",
                               symbol="create_order", source="llm")
        # overlay：用户改名
        UserOverlayStore.add(pid, "rename", [asset["id"]],
                             {"newName": "创建订单(校验版)"},
                             [{"file": "m.py", "symbol": "create_order"}],
                             author="designer", reason="区分校验版本")
        # 资产行内溯源
        SemanticAssetsStore.update(asset["id"], {"renamedFrom": "下单"})
        from topoone_app_architect.arch_routes.naming import api_asset_names
        out = _call(lambda: api_asset_names(asset["id"]))
        detail = out.get("data", out)
        assert detail["currentName"] == "创建订单"
        assert detail["renamedFrom"] == "下单"
        types = {h["type"] for h in detail["history"]}
        assert "tombstone" in types and "overlay" in types and "asset_row" in types
        overlay_rows = [h for h in detail["history"] if h["type"] == "overlay"]
        assert overlay_rows[0]["name"] == "创建订单(校验版)"


# ── 就地认知编辑（rename/merge/split；R5 main-KB 拒绝） ─────────

def _mk_asset(pid, name, refs, kind="entity", level="implementation"):
    from topoone_app_architect.store import _now_ms
    return SemanticAssetsStore.create({
        "id": f"sa-t-{abs(hash(name)) % 10 ** 8}", "projectId": pid,
        "kind": kind, "level": level, "name": name,
        "astRefs": refs, "status": "active", "meta": {},
        "createdAt": _now_ms(), "updatedAt": _now_ms(),
    })


class TestCognitiveEdit:
    def test_rename_endpoint_and_history(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        _mk_asset(pid, "创建订单", [{"file": "m.py", "symbol": "create_order"}])
        rows = SemanticAssetsStore.all(pid, kind="entity")
        aid = rows[0]["id"]
        from topoone_app_architect.semantic_assets import api_asset_rename
        out = _call(lambda: api_asset_rename(_req(
            {"assetId": aid, "newName": "下单(校验版)", "author": "designer"})))
        data = out.get("data") or {}
        assert data["asset"]["name"] == "下单(校验版)"
        assert data["asset"]["renamedFrom"] == "创建订单"
        assert data["asset"]["nameAlias"] == ["创建订单"]
        ovl = UserOverlayStore.list_active(pid)
        assert any(o["op"] == "rename" and o["payload"]["newName"] == "下单(校验版)"
                   for o in ovl)
        # 同名拒绝
        out2 = _call(lambda: api_asset_rename(_req(
            {"assetId": aid, "newName": "下单(校验版)"})))
        assert out2.get("_error")

    def test_merge_endpoint(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        into = _mk_asset(pid, "订单服务", [{"file": "a.py", "symbol": "Svc"}])
        t1 = _mk_asset(pid, "订单校验", [{"file": "b.py", "symbol": "Check"}])
        t2 = _mk_asset(pid, "订单落库", [{"file": "a.py", "symbol": "Svc"},
                                        {"file": "c.py", "symbol": "Persist"}])
        from topoone_app_architect.semantic_assets import api_asset_merge
        out = _call(lambda: api_asset_merge(_req({
            "intoId": into["id"], "targetIds": [t1["id"], t2["id"]],
            "targetName": "订单"})))
        data = out.get("data") or {}
        assert set(data["merged"]) == {t1["id"], t2["id"]}
        merged_asset = SemanticAssetsStore.get(into["id"])
        syms = {r["symbol"] for r in merged_asset["astRefs"]}
        assert syms == {"Svc", "Check", "Persist"}  # 锚点并集去重
        assert merged_asset["name"] == "订单"
        assert merged_asset["renamedFrom"] == "订单服务"
        for t in (t1, t2):
            row = SemanticAssetsStore.get(t["id"])
            assert row["status"] == "deleted"
            assert row["meta"]["mergedInto"] == into["id"]
        assert any(o["op"] == "merge" for o in UserOverlayStore.list_active(pid))

    def test_split_endpoint(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        src = _mk_asset(pid, "订单流程", [
            {"file": "a.py", "symbol": "Validate"},
            {"file": "a.py", "symbol": "Persist"},
        ], kind="process")
        from topoone_app_architect.semantic_assets import api_asset_split
        out = _call(lambda: api_asset_split(_req({
            "assetId": src["id"],
            "parts": [
                {"name": "订单校验", "anchorKeys": ["a.py:Validate"]},
                {"name": "订单落库", "anchorKeys": ["a.py:Persist"]},
            ]})))
        data = out.get("data") or {}
        assert len(data["created"]) == 2
        new_rows = [SemanticAssetsStore.get(c["id"]) for c in data["created"]]
        assert {r["name"] for r in new_rows} == {"订单校验", "订单落库"}
        for r in new_rows:
            assert len(r["astRefs"]) == 1
            assert r["meta"]["splitFrom"] == src["id"]
        src_row = SemanticAssetsStore.get(src["id"])
        assert src_row["status"] == "deleted"
        assert len(src_row["meta"]["splitInto"]) == 2
        # 锚点不匹配拒绝
        out2 = _call(lambda: api_asset_split(_req({
            "assetId": src["id"],
            "parts": [{"name": "X", "anchorKeys": ["a.py:Nope"]}]})))
        assert out2.get("_error")

    def test_main_kb_reject_with_deeplink(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        pid = _pid(tmp_path)
        _mk_asset(pid, "创建订单", [{"file": "m.py", "symbol": "create_order"}])
        rows = SemanticAssetsStore.all(pid, kind="entity")
        aid = rows[0]["id"]
        from topoone_app_architect import store as st
        monkeypatch.setattr(
            st.ProjectsStore, "get",
            classmethod(lambda cls, row_id: {"kbProjectId": "kb-1"}))
        from topoone_app_architect.semantic_assets import api_asset_rename
        out = _call(lambda: api_asset_rename(_req(
            {"assetId": aid, "newName": "X"})))
        assert out.get("code") == 409
        assert out["data"]["deepLink"] == "/kb/kb-1/assets"
        # 资产未被改动
        assert SemanticAssetsStore.get(aid)["name"] == "创建订单"

    def test_agent_semantic_update_tool(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _fake_collect(monkeypatch, str(tmp_path))
        pid = _pid(tmp_path)
        res = S.save_agent_assets(str(tmp_path), None, [{
            "name": "创建订单", "kind": "process", "level": "implementation",
            "astRefs": [{"file": "m.py", "symbol": "create_order",
                         "startLine": 1, "endLine": 10}]},
        ])
        aid = res["saved"][0]["id"]
        from topoone_app_architect.arch_routes.req_agent import run_arch_tool
        out = run_arch_tool("asset.semantic.update",
                            {"assetId": aid, "patch": {"name": "下单"}},
                            str(tmp_path), None)
        assert "error" not in out
        assert SemanticAssetsStore.get(aid)["name"] == "下单"
        out2 = run_arch_tool("asset.semantic.update",
                             {"assetId": aid, "patch": {"desc": "修订描述"}},
                             str(tmp_path), None)
        assert "error" not in out2
        assert SemanticAssetsStore.get(aid)["desc"] == "修订描述"
        out3 = run_arch_tool("asset.semantic.update",
                             {"assetId": "sa-nope", "patch": {"name": "X"}},
                             str(tmp_path), None)
        assert "error" in out3


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
