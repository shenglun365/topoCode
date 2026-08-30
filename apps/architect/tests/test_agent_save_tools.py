"""对话式提取工具测试：asset.semantic.save（归一化管线）+ code.read_symbols。

Run: cd <repo> && PYTHONPATH=apps/architect python -m pytest apps/architect/tests/test_agent_save_tools.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
from topoone_app_architect.arch_routes import semantic_assets as S
from topoone_app_architect.arch_routes import asset_framework as F
from topoone_app_architect.arch_routes.req_agent import (
    tool_asset_semantic_save, tool_code_read_symbols)
from topoone_app_architect.arch_routes.store import (
    NameTombstoneStore, SemanticAssetsStore)


def _ctx_setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.setup(data_dir=data)


def _node(nid, kind, name, file_path="m.py", s=1, e=10, sig=""):
    return {"id": nid, "kind": kind, "name": name, "qualified_name": name,
            "file_path": file_path, "start_line": s, "end_line": e,
            "signature": sig, "docstring": "", "return_type": ""}


def _fake_collect(monkeypatch, root):
    """合成 collect_context（避免依赖 codegraph/KB/live 扫描）。"""

    def _collect(r, project, scope_type, scope_key, files, symbols):
        return {"root": root, "project": project, "files": files or [],
                "symbols": symbols or [], "nodes": [],
                "table": {"create_order": _node("n1", "func", "create_order",
                                                sig="def create_order():")},
                "edges": [], "text": "", "srcHash": "h1", "source": "live",
                "implDetails": {}, "calleeNames": {}}

    monkeypatch.setattr(S, "collect_context", _collect)


def _asset(name="创建订单", kind="process", symbol="create_order"):
    return {"name": name, "kind": kind, "level": "implementation",
            "desc": "创建订单过程",
            "astRefs": [{"file": "m.py", "symbol": symbol,
                         "startLine": 1, "endLine": 10}]}


# ── asset.semantic.save（归一化管线） ──────────────────────────

class TestSaveAgentAssets:
    def test_happy_path_saves_asset(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _fake_collect(monkeypatch, str(tmp_path))
        res = S.save_agent_assets(str(tmp_path), None, [_asset()])
        assert res["count"] == 1 and not res["rejected"]
        saved = SemanticAssetsStore.all(res["saved"][0]["projectId"])
        assert any(a["name"] == "创建订单" and a["kind"] == "process" for a in saved)

    def test_kind_out_of_framework_domain_rejected(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _fake_collect(monkeypatch, str(tmp_path))
        F.switch_tier(S.project_id_for(str(tmp_path), None), "low")  # low 无 state
        res = S.save_agent_assets(str(tmp_path), None, [_asset("订单状态", kind="state")])
        assert res["count"] == 0
        assert res["rejected"] and "值域" in res["rejected"][0]["reason"]

    def test_existing_canonical_key_keeps_old_name(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _fake_collect(monkeypatch, str(tmp_path))
        S.save_agent_assets(str(tmp_path), None, [_asset("创建订单")])
        # 同锚点再提，LLM 提议新名 → 旧名优先，提议进 proposedNames
        res = S.save_agent_assets(str(tmp_path), None, [_asset("下单流程")])
        assert res["count"] == 1
        assert res["proposedNames"], "提议名应返回供设计者定夺"
        p = res["proposedNames"][0]
        assert p["proposedName"] == "下单流程" and p["keptName"] == "创建订单"
        saved = SemanticAssetsStore.all(S.project_id_for(str(tmp_path), None))
        assert [a["name"] for a in saved if a["kind"] == "process"] == ["创建订单"]

    def test_tombstone_name_adopted_for_new_asset(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _fake_collect(monkeypatch, str(tmp_path))
        pid = S.project_id_for(str(tmp_path), None)
        NameTombstoneStore.add(pid, "历史命名·下单", file_path="m.py",
                               symbol="create_order", source="user")
        res = S.save_agent_assets(str(tmp_path), None, [_asset("全新名字")])
        assert res["count"] == 1
        saved = SemanticAssetsStore.all(pid)
        assert saved[0]["name"] == "历史命名·下单"  # 参考池捞回，非 LLM 新名

    def test_missing_ast_refs_rejected(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        res = S.save_agent_assets(str(tmp_path), None,
                                  [{"name": "无锚点", "kind": "process", "level": "implementation"}])
        assert res["count"] == 0
        assert "astRefs" in res["rejected"][0]["reason"]


# ── code.read_symbols ─────────────────────────────────────────

class TestCodeReadSymbols:
    def _mk_file(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir(exist_ok=True)
        (root / "m.py").write_text(
            "\n".join(f"line {i}" for i in range(1, 11)), encoding="utf-8")
        return str(root)

    def test_read_line_range(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path / "arch"))
        root = self._mk_file(tmp_path)
        res = tool_code_read_symbols(root=root, file="m.py", startLine=3, endLine=5)
        assert res["range"] == [3, 5]
        assert "line 3" in res["code"] and "line 4" in res["code"] and "line 6" not in res["code"]

    def test_path_traversal_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path / "arch"))
        root = self._mk_file(tmp_path)
        res = tool_code_read_symbols(root=root, file="../outside.py")
        assert "越界" in res["error"]

    def test_missing_file_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path / "arch"))
        root = self._mk_file(tmp_path)
        res = tool_code_read_symbols(root=root, file="nope.py")
        assert "不存在" in res["error"]
