"""K1 知识资产格式版本化回归——迁移链注册制/缺口拒绝/读时惰性迁移/四表 version 列。

Run: cd <repo> && python -m pytest apps/architect/tests/test_kb_schema_versions.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect import store  # noqa: E402
from topoone_app_architect.store import migrations as mig  # noqa: E402


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


# ── 迁移链(纯函数域) ────────────────────────────────────────────────

def test_apply_identity_unregistered_and_fresh_rows():
    row = {"id": "x", "schemaVersion": 1}
    assert mig.apply_migrations("arch_not_registered", row) == {
        "id": "x", "schemaVersion": 1}
    # v == target: 原样(只规整 version 字段)
    assert mig.apply_migrations("arch_glossary", {"a": 1, "schemaVersion": 1}) == {
        "a": 1, "schemaVersion": 1}


def test_register_duplicate_rejected():
    def fn(row):  # noqa: ANN001
        row["k"] = 1
    mig.register_migration("__t1__", 1, fn)
    try:
        mig.register_migration("__t1__", 1, fn)
    except RuntimeError as exc:
        assert "已注册" in str(exc)
    else:
        raise AssertionError("重复注册未拒绝")
    mig._MIGRATIONS.pop("__t1__", None)


def test_missing_step_raises():
    mig.SCHEMA_VERSIONS["__t2__"] = 3  # bump 到 3 但只注册 1→2
    try:
        mig.register_migration("__t2__", 1, lambda r: None)
        mig.apply_migrations("__t2__", {"schemaVersion": 1})
    except RuntimeError as exc:
        assert "缺口" in str(exc)
    finally:
        mig.SCHEMA_VERSIONS.pop("__t2__", None)
        mig._MIGRATIONS.pop("__t2__", None)


def test_chain_applies_in_order():
    mig.SCHEMA_VERSIONS["__t3__"] = 3
    order = []
    mig.register_migration("__t3__", 1, lambda r: order.append("v1→v2"),
                           lambda r: r.setdefault("k2", "b"))
    mig.register_migration("__t3__", 2, lambda r: (order.append("v2→v3"),
                                                   r.setdefault("k3", "c")))
    row = mig.apply_migrations("__t3__", {"schemaVersion": 1})
    assert order == ["v1→v2", "v2→v3"] and row["k2"] == "b" and row["k3"] == "c"
    assert row["schemaVersion"] == 3
    mig.SCHEMA_VERSIONS.pop("__t3__", None)
    mig._MIGRATIONS.pop("__t3__", None)


# ── 四表 schema_version 列 + 读路径挂钩 ─────────────────────────────

def test_four_tables_have_schema_version_column(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    store.SemanticAssetsStore.create({"id": "sa-v1", "projectId": "pj-k",
                                      "kind": "entity", "name": "n",
                                      "scopeType": "comm", "scopeKey": "k"})
    assert store.SemanticAssetsStore.get("sa-v1")["schemaVersion"] == 1
    store.GlossaryStore.create("pj-k", term="网关")
    assert store.GlossaryStore.list("pj-k")[0]["schemaVersion"] == 1
    store.ContextUnitsStore.create({"conversationId": "cv-k", "projectId": "pj-k",
                                    "type": "note", "title": "t"})
    assert store.ContextUnitsStore.get(store.ContextUnitsStore.all(
        conversation_id="cv-k")[0]["id"])["schemaVersion"] == 1
    store.DocsStore.create({"conversationId": "cv-k", "projectId": "pj-k",
                            "title": "d", "contentMd": "x"})
    assert store.DocsStore.all(conversation_id="cv-k")[0]["schemaVersion"] == 1


def test_read_path_lazy_migration_semantic_assets(tmp_path, monkeypatch):
    """v1 旧行 + 注册 v1→v2 + bump → 读出即迁移(内存态), 未写回不刷库。"""
    _setup_env(tmp_path, monkeypatch)
    store.SemanticAssetsStore.create({"id": "sa-old", "projectId": "pj-m",
                                      "kind": "entity", "name": "n",
                                      "scopeType": "comm", "scopeKey": "k"})
    def _v1_to_v2(row):
        row["summary"] = row.get("summary") or "(迁移默认)"
    mig.register_migration("arch_semantic_assets", 1, _v1_to_v2)
    monkeypatch.setitem(mig.SCHEMA_VERSIONS, "arch_semantic_assets", 2)
    try:
        row = store.SemanticAssetsStore.get("sa-old")
        assert row["summary"] == "(迁移默认)"
        assert row["schemaVersion"] == 2
    finally:
        mig.SCHEMA_VERSIONS["arch_semantic_assets"] = 1
        mig._MIGRATIONS["arch_semantic_assets"].pop(1)
        if not mig._MIGRATIONS["arch_semantic_assets"]:
            mig._MIGRATIONS.pop("arch_semantic_assets")


def test_unregistered_tables_identity_under_hook(tmp_path, monkeypatch):
    """同模块未登记表(命名规约等)读路径恒等——挂钩不误伤。"""
    _setup_env(tmp_path, monkeypatch)
    store.GlossaryStore.create("pj-i", term="术语")
    row = store.GlossaryStore.list("pj-i")[0]
    assert row["term"] == "术语" and row["schemaVersion"] == 1
