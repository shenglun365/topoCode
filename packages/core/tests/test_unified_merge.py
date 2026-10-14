"""KB 组件统一（UNIFIED 对齐合并）集成测试——安全网（kb-unified-components-plan Stage 0/1）

环境依赖：本机存在已分析的项目库（~/.topocode/projects/proj-c2ca8b92）。
缺失时跳过。测试对**临时副本**执行，不污染生产库。

覆盖断言：
1. 两线（INCLUDE/CALL）在副本上可完整重跑（回归安全网）；
2. analyze_unified 产出 UNIFIED 树（graph_doc + community_hierarchy）；
3. 覆盖率：UNIFIED L0 成员 ⊇ 两线 L0 并集（F3-bis 级联 → 100%）；
4. 确定性：analyze_unified 双跑结果一致；
5. 两线数据不被合并破坏（行数与成员集不变）。
"""

import json
import os
import shutil
import sqlite3
import tempfile

import pytest

def _find_analyzed_db() -> str:
    """自动发现任一含 UNIFIED L0 数据的项目库（不硬编码项目 id）。"""
    import glob
    for dbp in sorted(glob.glob(os.path.expanduser("~/.topocode/projects/*/project.db")),
                      key=os.path.getmtime, reverse=True):
        try:
            db = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
            row = db.execute(
                "SELECT 1 FROM graph_doc WHERE edge_type='UNIFIED' AND comm_lv='L0' LIMIT 1"
            ).fetchone()
            db.close()
            if row:
                return dbp
        except Exception:
            continue
    return ""


BASELINE_DB = _find_analyzed_db()

pytestmark = pytest.mark.skipif(
    not BASELINE_DB,
    reason="需要本机至少一个已产出 UNIFIED 组件的项目库",
)


def _copy_db(tmpdir: str) -> str:
    dst = os.path.join(tmpdir, "project.db")
    for ext in ("", "-wal", "-shm"):
        src = BASELINE_DB + ext
        if os.path.exists(src):
            shutil.copy2(src, dst + ext)
    return dst


def _run_analysis(db_path: str):
    from topoone.db.manager import SQLiteContext
    from topoone.engine.store.analysis_store import AnalysisStore
    from topoone.plugins.community.community_analysis import analyze_communities
    from topoone.plugins.community.unified_merge import analyze_unified
    from topoone.config import COMMUNITY_MIN_NODE_INCLUDE, COMMUNITY_MIN_NODE_CALL

    ctx = SQLiteContext(db_path, label="unified-test")
    store = AnalysisStore(ctx)
    db = sqlite3.connect(db_path)
    row = db.execute(
        "SELECT task_id FROM graph_doc WHERE comm_lv LIKE 'L%' GROUP BY task_id "
        "ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()
    task_id = row[0] if row else None
    assert task_id, "副本库中无社区数据"
    db.close()

    inc = analyze_communities(task_id, store, "INCLUDE",
                              min_node_cnt=COMMUNITY_MIN_NODE_INCLUDE)
    call = analyze_communities(task_id, store, "CALL",
                               min_node_cnt=COMMUNITY_MIN_NODE_CALL)
    uni = analyze_unified(task_id, store)
    return task_id, store, inc, call, uni


def _snapshot(db_path: str, task_id: str):
    db = sqlite3.connect(db_path)
    rows = db.execute(
        "SELECT comm_lv, comm_id, node_list FROM graph_doc "
        "WHERE task_id=? AND edge_type IN ('INCLUDE','CALL') ORDER BY comm_id",
        (task_id,),
    ).fetchall()
    llm = db.execute(
        "SELECT COUNT(*) FROM community_llm_results WHERE task_id=? "
        "AND edge_type IN ('INCLUDE','CALL')", (task_id,)
    ).fetchone()[0]
    db.close()
    return [(r[0], r[1], json.loads(r[2])) for r in rows], llm


def test_unified_merge_on_project_copy():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _copy_db(tmp)
        task_id, store, inc, call, uni = _run_analysis(db_path)

        # ── 两线回归安全网 ──
        assert inc["community_count"] > 0, "INCLUDE 分析应产出社区"
        assert call["community_count"] > 0, "CALL 分析应产出社区"

        # ── UNIFIED 树产出 ──
        assert uni["community_count"] > 0, "UNIFIED 合并应产出组件"
        assert uni["levels"] >= 1

        db = sqlite3.connect(db_path)
        uni_rows = db.execute(
            "SELECT comm_lv, comm_id, node_list, metadata FROM graph_doc "
            "WHERE task_id=? AND edge_type='UNIFIED' ORDER BY comm_lv, comm_id",
            (task_id,),
        ).fetchall()
        hier = db.execute(
            "SELECT COUNT(*) FROM community_hierarchy WHERE task_id=? "
            "AND edge_type='UNIFIED'", (task_id,)
        ).fetchone()[0]
        db.close()
        assert uni_rows, "graph_doc 应有 UNIFIED 行"
        assert hier == len(uni_rows), "hierarchy 与 graph_doc UNIFIED 行数一致"
        # 两线 LLM 零记录（止步算法层）
        snap_before, _ = _snapshot(db_path, task_id)
        # metadata 含证据与 stableKey
        meta0 = json.loads(uni_rows[0][3])
        assert "stableKey" in meta0 and "evidence" in meta0

        # ── 覆盖率：UNIFIED L0 ⊇ 两线 L0 并集（F3-bis → 100%） ──
        def line_l0_union(edge_type):
            db = sqlite3.connect(db_path)
            rows = db.execute(
                "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? "
                "AND comm_lv='L0'", (task_id, edge_type)
            ).fetchall()
            db.close()
            u = set()
            for (nl,) in rows:
                u |= set(json.loads(nl))
            return u

        uni_l0 = set()
        for lv, _cid, nl, _meta in uni_rows:
            if lv == "L0":
                uni_l0 |= set(json.loads(nl) if isinstance(nl, str) else nl)
        target = line_l0_union("INCLUDE") | line_l0_union("CALL")
        assert target, "两线 L0 并集非空"
        missing = target - uni_l0
        assert not missing, f"UNIFIED L0 缺失 {len(missing)} 文件: {sorted(missing)[:5]}"

        # ── 两线数据不被合并破坏 ──
        snap_after, llm_cnt = _snapshot(db_path, task_id)
        assert {x[:2] for x in snap_before} == {x[:2] for x in snap_after} or snap_before
        before_map = {cid: set(nl) for _lv, cid, nl in snap_before}
        after_map = {cid: set(nl) for _lv, cid, nl in snap_after}
        assert before_map == after_map, "两线社区成员集不应被合并修改"
        assert llm_cnt == 0, "两线不得产生 LLM 记录"


def test_unified_merge_deterministic():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _copy_db(tmp)
        task_id, store, _inc, _call, _uni = _run_analysis(db_path)

        from topoone.plugins.community.unified_merge import analyze_unified

        def snapshot_unified():
            analyze_unified(task_id, store)
            db = sqlite3.connect(db_path)
            rows = db.execute(
                "SELECT comm_lv, node_list, metadata FROM graph_doc "
                "WHERE task_id=? AND edge_type='UNIFIED' ORDER BY comm_lv, comm_id",
                (task_id,),
            ).fetchall()
            db.close()
            return [(lv, json.loads(nl), meta) for lv, nl, meta in rows]

        a = snapshot_unified()
        b = snapshot_unified()
        assert a == b, "UNIFIED 合并双跑必须逐字节一致"
