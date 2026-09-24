"""auto 合并语义(1+1 增强)单测：native 优先 ∪ codegraph 补充。

覆盖四类不一致识别：
1. kind 判定差异(native method vs cg function) → 身份归并类去重，不产生重复节点
2. 行号漂移(一方过期) → 去重且位置取 native，漂移计数进 merge_stats
3. cg 独有符号/边 → 补充('cg:' 前缀防 id 碰撞)，边端点映射回 native id
4. cg 不可用 → 回退纯 native(merge_stats 不存在)
"""
import json
import os
import sqlite3

import pytest

from topoone_app_architect.sem import symbols as sym


@pytest.fixture()
def fake_sources(tmp_path, monkeypatch):
    """fake core project.db + codegraph.db，同 root 双源。"""
    root = tmp_path / "proj"
    root.mkdir()
    core_dir = tmp_path / "core" / "projects" / "proj-x"
    core_dir.mkdir(parents=True)
    cg_dir = root / ".codegraph"
    cg_dir.mkdir()

    # native: graph_node/graph_edge(core 分析库 schema 最小集)
    nc = sqlite3.connect(core_dir / "project.db")
    nc.executescript("""
    CREATE TABLE graph_node (id TEXT PRIMARY KEY, task_id TEXT, kind TEXT, name TEXT,
        qualified_name TEXT, file_path TEXT, start_line INTEGER, end_line INTEGER,
        start_col INTEGER, end_col INTEGER, signature TEXT, docstring TEXT,
        language TEXT, is_exported INTEGER DEFAULT 0, provenance TEXT DEFAULT 'parser',
        metadata TEXT);
    CREATE TABLE graph_edge (id TEXT PRIMARY KEY, task_id TEXT, source_id TEXT,
        target_id TEXT, kind TEXT, provenance TEXT DEFAULT 'parser',
        line INTEGER DEFAULT 0, col INTEGER DEFAULT 0, file_path TEXT DEFAULT '',
        metadata TEXT DEFAULT '');
    """)
    nc.executemany("INSERT INTO graph_node (id, task_id, kind, name, qualified_name, "
                   "file_path, start_line, end_line) VALUES (?,?,?,?,?,?,?,?)", [
        ("n1", "t", "class", "Store", "Store", "src/store.ts", 1, 100),
        # native 判定为 method；行号 10
        ("n2", "t", "method", "build", "Store::build", "src/store.ts", 10, 20),
        ("n3", "t", "function", "util", "util", "src/util.ts", 5, 9),
    ])
    nc.executemany("INSERT INTO graph_edge VALUES (?,?,?,?,?, 'parser', 0,0,'','')", [
        ("ne1", "t", "n2", "n3", "calls"),
    ])
    nc.commit(); nc.close()

    # codegraph: nodes/edges；build 判定为 function(归并类同 callable → 去重)且行号漂移 11；
    # extra 是 cg 独有符号；ue1 是 cg 独有边(build → Extra)
    cc = sqlite3.connect(cg_dir / "codegraph.db")
    cc.executescript("""
    CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, name TEXT, qualified_name TEXT,
        file_path TEXT, start_line INTEGER, end_line INTEGER, start_column INTEGER DEFAULT 0,
        end_column INTEGER DEFAULT 0, signature TEXT DEFAULT '', docstring TEXT DEFAULT '',
        return_type TEXT DEFAULT '');
    CREATE TABLE edges (source TEXT, target TEXT, kind TEXT,
        line INTEGER DEFAULT 0, col INTEGER DEFAULT 0, metadata TEXT DEFAULT '');
    """)
    cc.executemany("INSERT INTO nodes (id, kind, name, qualified_name, file_path, "
                   "start_line, end_line) VALUES (?,?,?,?,?,?,?)", [
        ("cg1", "function", "build", "Store.build", str(root / "src" / "store.ts"), 11, 20),
        # 绝对路径形态 + 行号一致 → 仍应被身份键去重
        ("cg2", "class", "Store", "Store", str(root / "src" / "store.ts"), 1, 100),
        # cg 独有
        ("cg3", "class", "Extra", "Extra", "src/extra.ts", 1, 30),
    ])
    cc.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?)", [
        # 端点均与 native 身份重合 → 映射回 native id；与 ne1 不同 source/target 组合 → 保留
        ("cg1", "cg3", "calls", 12, 0, ""),
        # 与 native ne1 (n2→n3 calls) 完全同构 → 去重丢弃
        ("cg1", "cg2", "references", 11, 0, ""),
    ])
    # ne1 等价 cg 边: build(cg1)→util？util 无 cg 节点 → 端点映射不了。
    # 用 cg1→cg2 references 补一条 native 也有的: n2→n1 references
    cc.execute("INSERT INTO edges VALUES ('cg1','cg2','references',10,0,'')")
    cc.commit(); cc.close()

    monkeypatch.setattr(sym, "_resolve_core_pid", lambda r: "proj-x")
    monkeypatch.setattr(sym, "_core_data_dir", lambda: str(tmp_path / "core"))
    monkeypatch.setattr(sym._cg_mod, "cg_dir", lambda r: str(cg_dir))
    sym.invalidate_native_cache()
    yield {"root": str(root)}
    sym.invalidate_native_cache()


def _cols(r): return dict(r)


def test_merge_nodes_kind_class_dedupe_and_cg_unique(fake_sources):
    conn, src = sym.open_symbol_conn(fake_sources["root"], None)
    assert src == "merged"
    rows = [dict(r) for r in conn.execute(
        "SELECT id, kind, name, file_path, start_line FROM nodes WHERE kind NOT IN ('file','import')")]
    names = {(r["file_path"], r["name"]): r for r in rows}
    # kind 差异去重: build 只有一份(native method 版, 行号取 native=10)
    assert names[("src/store.ts", "build")]["id"] == "n2"
    assert names[("src/store.ts", "build")]["kind"] == "method"
    assert names[("src/store.ts", "build")]["start_line"] == 10
    # Store class 行号一致 → native 优先
    assert names[("src/store.ts", "Store")]["id"] == "n1"
    # cg 独有 Extra 补充且带前缀
    assert names[("src/extra.ts", "Extra")]["id"] == "cg:cg3"
    # cg 绝对路径已归一 → 不再出现第二份 Store/build
    assert sum(1 for r in rows if r["name"] == "Store") == 1
    assert sum(1 for r in rows if r["name"] == "build") == 1


def test_merge_edges_map_and_dedupe(fake_sources):
    conn, _ = sym.open_symbol_conn(fake_sources["root"], None)
    edges = {(r["source"], r["target"], r["kind"]) for r in conn.execute(
        "SELECT source, target, kind FROM edges")}
    # native 原边
    assert ("n2", "n3", "calls") in edges
    # cg 独有边: build→Extra 映射后 source=n2, target=cg:cg3
    assert ("n2", "cg:cg3", "calls") in edges
    # 同构 references 边只保留一份(native n2→n1)——cg 两条 references 均映射到 n2→n1
    refs = [e for e in edges if e[2] == "references"]
    assert refs == [("n2", "n1", "references")]


def test_merge_stats_line_drift(fake_sources):
    conn, _ = sym.open_symbol_conn(fake_sources["root"], None)
    stats = {r["k"]: r["v"] for r in conn.execute("SELECT k, v FROM merge_stats")}
    assert stats["native_nodes"] == 3
    assert stats["cg_nodes"] == 3
    assert stats["cg_mapped"] == 2          # build + Store 身份重合
    assert stats["line_drift"] == 1          # build 行号 10 vs 11 漂移


def test_merge_fallback_without_codegraph(tmp_path, monkeypatch):
    root = tmp_path / "p2"
    root.mkdir()
    core_dir = tmp_path / "core" / "projects" / "proj-y"
    core_dir.mkdir(parents=True)
    nc = sqlite3.connect(core_dir / "project.db")
    nc.executescript("""
    CREATE TABLE graph_node (id TEXT PRIMARY KEY, task_id TEXT, kind TEXT, name TEXT,
        qualified_name TEXT, file_path TEXT, start_line INTEGER, end_line INTEGER,
        start_col INTEGER, end_col INTEGER, signature TEXT, docstring TEXT,
        language TEXT, is_exported INTEGER DEFAULT 0, provenance TEXT DEFAULT 'parser',
        metadata TEXT);
    """)
    nc.execute("INSERT INTO graph_node VALUES ('m1','t','class','A','A','a.py',1,5,0,0,'','',0,0,'','')")
    nc.commit(); nc.close()
    monkeypatch.setattr(sym, "_resolve_core_pid", lambda r: "proj-y")
    monkeypatch.setattr(sym, "_core_data_dir", lambda: str(tmp_path / "core"))
    monkeypatch.setattr(sym._cg_mod, "cg_dir", lambda r: None)
    sym.invalidate_native_cache()
    try:
        conn, src = sym.open_symbol_conn(str(root), None)
        assert src == "merged"                 # auto 语义, cg 缺失退化纯 native 数据
        rows = [dict(r) for r in conn.execute(
            "SELECT id FROM nodes WHERE kind NOT IN ('file','import')")]
        assert [r["id"] for r in rows] == ["m1"]
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("SELECT * FROM merge_stats").fetchone()
    finally:
        sym.invalidate_native_cache()
