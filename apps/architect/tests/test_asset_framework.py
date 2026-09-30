"""M0 冻结 schema 之框架配置/墓碑/overlay/规约/术语 store 测试（plan-C-M0.md §6/§9）。

Run: cd <repo> && PYTHONPATH=apps/architect python -m pytest apps/architect/tests/test_asset_framework.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.ctx as C
from topoone_app_architect.arch_routes import asset_framework as F
from topoone_app_architect import store
from topoone_app_architect.store import (
    FrameworkConfigStore, GlossaryStore,
    NamingConventionStore, SemanticAssetsStore,
)


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    return C.setup(data_dir=data)


PID = "proj-fw1"


def _mk_asset(aid: str, kind: str = "process", status: str = "active",
              scope_key: str = "comm-a"):
    SemanticAssetsStore.create({
        "id": aid, "projectId": PID, "kind": kind, "level": "implementation",
        "name": f"资产{aid}", "desc": "", "status": status,
        "scopeType": "comm", "scopeKey": scope_key,
        "astRefs": [{"file": "a.py", "symbol": aid, "startLine": 1, "endLine": 2}],
        "createdAt": 1, "updatedAt": 1,
    })


def _get_raw(aid: str):
    from topoone_app_architect.store import _get
    return _get("arch_semantic_assets", aid)


# ── 预设形状（M0 §1.1） ─────────────────────────────────────────

class TestPresets:
    def test_low_has_five_kinds_no_state(self, tmp_path, monkeypatch):
        cfg = F.build_preset("low")
        tier = cfg["tiers"]["low"]
        assert "state" not in tier["x"]
        assert len(tier["x"]) == 5
        assert tier["y"] == ["implementation"]
        assert tier["z"] == []
        assert tier["acceptanceDefault"]["mode"] == "auto"

    def test_mid_full_six_kinds_three_levels(self, tmp_path, monkeypatch):
        cfg = F.build_preset("mid")
        tier = cfg["tiers"]["mid"]
        assert set(tier["x"]) == set(F.KIND_LABELS)
        assert set(tier["y"]) == set(F.LEVEL_LABELS)
        assert set(tier["z"]) == set(F.Z_LABELS)
        assert tier["acceptanceDefault"]["l3"] == "human-on-demand"

    def test_invalid_tier_rejected(self, tmp_path, monkeypatch):
        import pytest
        with pytest.raises(ValueError):
            F.build_preset("ultra")


# ── 框架配置版本（版本行即审计） ────────────────────────────────

class TestFrameworkConfigStore:
    def test_activate_creates_version_and_clears_old(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        r1 = FrameworkConfigStore.activate(PID, F.build_preset("mid"),
                                           "tier_switch", affected={"voidedAssets": 0})
        assert r1["version"] == 1 and r1["active"] == 1
        r2 = FrameworkConfigStore.activate(PID, F.build_preset("low"),
                                           "tier_switch", affected={})
        assert r2["version"] == 2 and r2["active"] == 1
        raw = FrameworkConfigStore.get_active_raw(PID)
        assert raw is not None and raw["version"] == 2
        versions = FrameworkConfigStore.versions(PID)
        assert [v["active"] for v in versions] == [1, 0]  # v2 active, v1 cleared

    def test_no_active_row_before_customization(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        assert FrameworkConfigStore.get_active_raw("proj-none") is None


# ── 标准变更：整体作废 + 不写墓碑（R1） ─────────────────────────

class TestStandardChange:
    def test_switch_voids_all_and_keeps_rows(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _mk_asset("sa-1", "process")
        _mk_asset("sa-2", "entity", status="stale")
        _mk_asset("sa-3", "rule")
        row = F.switch_tier(PID, "low", executed_by="designer")
        assert row["voidedAssets"] == 3
        for aid in ("sa-1", "sa-2", "sa-3"):
            raw = _get_raw(aid)
            assert raw["status"] == "voided"
            assert raw["voidedReason"] == "framework_change"
            assert raw["voidedFrameworkVersion"] == row["version"]
        # 行保留可溯源（不物理删除）
        assert _get_raw("sa-1") is not None

    def test_voided_assets_excluded_from_active_queries(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _mk_asset("sa-20", "process")
        F.switch_tier(PID, "low")
        assert SemanticAssetsStore.all(PID) == []

    def test_allowed_kinds_follow_active_tier(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        assert "state" in F.allowed_kinds(PID)          # 默认 mid
        F.switch_tier(PID, "low")
        assert "state" not in F.allowed_kinds(PID)      # low 无 state
        assert "contract" in F.allowed_kinds(PID)

    def test_preview_change_counts(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _mk_asset("sa-30", "process")
        _mk_asset("sa-31", "entity")
        pv = F.preview_change(PID)
        assert pv["voidedAssets"] == 2
        assert pv["byKind"] == {"process": 1, "entity": 1}
        assert pv["namingMigrated"] is False


# ── 命名规约（场景标签 R7） ────────────────────────────────────

class TestNamingConventions:
    def test_scenario_scoped_query(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        NamingConventionStore.create(PID, "过程资产用动宾结构",
                                     scenarios=["extract", "naming"])
        NamingConventionStore.create(PID, "验收对照契约行为",
                                     scenarios=["accept"])
        # 按场景检索（agent 注入口径）——R7 禁全量
        assert len(NamingConventionStore.list(PID, scenario="extract")) == 1
        assert len(NamingConventionStore.list(PID, scenario="accept")) == 1
        assert len(NamingConventionStore.list(PID, scenario="naming")) == 1
        # active 全量（UI 列表用）
        assert len(NamingConventionStore.list(PID)) == 2

    def test_framework_change_marks_pending_review(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        NamingConventionStore.create(PID, "实体命名用业务名词",
                                     scenarios=["naming"])
        F.switch_tier(PID, "low")
        rows = NamingConventionStore.list(PID, status="pending_review")
        assert len(rows) == 1


# ── 术语表 ─────────────────────────────────────────────────────

class TestGlossary:
    def test_crud(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        g = GlossaryStore.create(PID, "订单", alias=["Order"], definition="购买行为的数据载体")
        assert GlossaryStore.list(PID, q="订单")[0]["id"] == g["id"]
        GlossaryStore.update(g["id"], {"definition": "更新后的释义"})
        assert GlossaryStore.list(PID)[0]["definition"] == "更新后的释义"
        assert GlossaryStore.delete(g["id"]) is True
        assert GlossaryStore.list(PID) == []
