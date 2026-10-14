"""
组件命名消歧模块单测 — strip_doc_header / scan_name_conflicts / resolve_group /
clean_community_summaries。
"""

import asyncio
import sqlite3

import pytest

from topoone.db.manager import SQLiteContext
from topoone.engine.component_name_disambiguation import (
    clean_community_summaries,
    normalize_name,
    resolve_group,
    scan_name_conflicts,
    strip_doc_header,
)

TASK = "t1"

SCHEMA = """
CREATE TABLE community_llm_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    comm_lv TEXT NOT NULL,
    comm_id TEXT NOT NULL,
    name TEXT,
    summary TEXT,
    model_id TEXT,
    template_id TEXT,
    name_manual TEXT,
    component_type TEXT DEFAULT 'community',
    status TEXT DEFAULT 'completed',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(task_id, edge_type, comm_lv, comm_id)
);
CREATE TABLE graph_doc (
    task_id TEXT,
    edge_type TEXT,
    comm_id TEXT,
    parent_comm_id TEXT
);
"""


@pytest.fixture()
def pdb(tmp_path):
    ctx = SQLiteContext(str(tmp_path / "proj.db"))
    ctx.conn.executescript(SCHEMA)
    yield ctx
    ctx.close()


def _insert(pdb, cid, name, lv="L0", summary="正文内容", manual=None,
            status="completed", et="UNIFIED"):
    pdb.execute(
        "INSERT INTO community_llm_results (task_id, edge_type, comm_lv, comm_id, "
        "name, summary, name_manual, status) VALUES (?,?,?,?,?,?,?,?)",
        (TASK, et, lv, cid, name, summary, manual, status))
    pdb.commit()


# ==================== strip_doc_header ====================

def test_strip_single_zh_header():
    text = "# 社区: nginx-core\n\n**ID**: comm-1\n\n正文第一段\n\n正文第二段"
    assert strip_doc_header(text) == "正文第一段\n\n正文第二段"


def test_strip_single_en_header():
    text = "# Community: nginx-core\n\n**ID**: comm-1\n\nBody text"
    assert strip_doc_header(text) == "Body text"


def test_strip_multi_layer_pollution():
    # 模拟多次编辑保存后累积的多层头部（同一 commId 不同名）
    text = (
        "# 社区: nginx-core-module-01\n\n**ID**: comm-1\n\n"
        "# 社区: nginx-core-md\n\n**ID**: comm-1\n\n"
        "# 社区: nginx-core-module\n\n**ID**: comm-1\n\n"
        "## Functional Summary\n基础定义组件"
    )
    assert strip_doc_header(text) == "## Functional Summary\n基础定义组件"


def test_strip_parent_and_struct_blocks():
    text = (
        "# 社区: core\n\n**ID**: comm-1\n\n正文A\n\n---\n\n"
        "## 父组件\nnginx-core — 核心调度\n\n---\n\n"
        "## 结构分析（2）\n\n### 依赖关系（1）\n\n- [child-a](##community:UNIFIED:comm-2)\n\n"
        "### 调用关系（1）\n\n- [child-b](##community:UNIFIED:comm-3)"
    )
    assert strip_doc_header(text) == "正文A"


def test_strip_en_struct_block():
    text = (
        "# Community: core\n\n**ID**: comm-1\n\nBody\n\n"
        "## Parent Component\nnginx — web server\n\n---\n\n"
        "## Structural Analysis（2）\n\n### Dependency Relationship（1）\n\n"
        "- [a](##community:UNIFIED:comm-2)\n\n### Call Relationship（1）\n\n"
        "- [b](##community:UNIFIED:comm-3)"
    )
    assert strip_doc_header(text) == "Body"


def test_strip_no_header_unchanged():
    text = "## Functional Summary\n纯正文，无头部"
    assert strip_doc_header(text) == text


def test_strip_preserves_user_headings():
    text = "## 自定义标题\n\n# 不是社区前缀（中文冒号外）内容\n\n**ID变量** 说明"
    assert strip_doc_header(text) == text


def test_strip_docs_viewer_id_type_line():
    # docs 端形式：**ID**: x  **类型**: y（同一行）；`# {name}` 无社区前缀、
    # 仅存在于渲染层不落库 → 不剥离（避免误伤用户一级标题）
    text = "# nginx\n\n**ID**: comm-1  **类型**: UNIFIED\n\n正文"
    assert strip_doc_header(text) == "# nginx\n\n正文"


# ==================== normalize_name / 分组 ====================

def test_normalize_name_variants():
    assert normalize_name("Nginx_HTTP_Modules") == normalize_name("nginx http modules")
    assert normalize_name("nginx-http-modules") == normalize_name("nginx-http modules")
    assert normalize_name("Ｎginx Core") == normalize_name("nginx core")


def test_scan_exact_and_similar_groups(pdb):
    _insert(pdb, "comm-1-uni-L0-0007", "nginx-core-modules", "L0")
    _insert(pdb, "comm-1-uni-L1-0004", "nginx-core-modules", "L1")
    _insert(pdb, "comm-1-uni-L1-0008", "NginxHTTPCoreModules", "L1")
    _insert(pdb, "comm-1-uni-L1-0012", "网络 I/O 操作模块", "L1")
    result = scan_name_conflicts(pdb, TASK)
    names_in_groups = {m["name"] for g in result["groups"] for m in g["members"]}
    # nginx-core-modules(L0/L1) 精确重复；NginxHTTPCoreModules 归一化后与前者仅差 core/coremodules
    assert "nginx-core-modules" in names_in_groups
    assert "网络 I/O 操作模块" not in names_in_groups
    group = next(g for g in result["groups"]
                 if any(m["name"] == "nginx-core-modules" for m in g["members"]))
    assert len(group["members"]) >= 2
    assert {m["commLv"] for m in group["members"]} == {"L0", "L1"}


def test_scan_skips_failed_and_empty(pdb):
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core", status="failed")
    _insert(pdb, "comm-1-uni-L0-0001", "", status="completed")
    _insert(pdb, "comm-1-uni-L0-0002", "网络 I/O 操作模块")
    result = scan_name_conflicts(pdb, TASK)
    assert result["groups"] == []
    assert result["scanned"] == 1


def test_scan_manual_rows_locked_but_included(pdb):
    # 人工名与另一组件的 LLM 名精确相同 → 成组，且 manual 行标记锁定
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core", manual="nginx-core")
    _insert(pdb, "comm-1-uni-L0-0001", "nginx-core")
    result = scan_name_conflicts(pdb, TASK)
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert len(group["members"]) == 2
    manuals = {m["manual"] for m in group["members"]}
    assert manuals == {True, False}
    assert group["locked"] is False


def test_scan_detects_dirty_summary(pdb):
    dirty = "# 社区: nginx-core\n\n**ID**: comm-1\n\n正文"
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core", summary=dirty)
    _insert(pdb, "comm-1-uni-L0-0001", "http 解析模块", summary="干净正文")
    result = scan_name_conflicts(pdb, TASK)
    assert result["dirtySummaryCommIds"] == ["comm-1-uni-L0-0000"]


def test_scan_comm_ids_filter(pdb):
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core")
    _insert(pdb, "comm-1-uni-L0-0001", "nginx-core")
    result = scan_name_conflicts(pdb, TASK, comm_ids=["comm-1-uni-L0-0000"])
    assert result["groups"] == []
    assert result["scanned"] == 1


# ==================== resolve_group ====================

def _run(coro):
    return asyncio.run(coro)


def test_resolve_group_renames_and_writes(pdb):
    _insert(pdb, "comm-1-uni-L0-0007", "nginx-core-modules", "L0")
    _insert(pdb, "comm-1-uni-L1-0004", "nginx-core-modules", "L1")
    proposals = {
        "comm-1-uni-L0-0007": "核心初始化模块",
        "comm-1-uni-L1-0004": "HTTP 核心模块族",
    }

    async def fake_llm(messages, temperature=0.2, max_tokens=800, **kw):
        import json
        return json.dumps(proposals, ensure_ascii=False)

    result = _run(resolve_group(None, pdb, TASK,
                                [{"commId": "comm-1-uni-L0-0007", "commLv": "L0"},
                                 {"commId": "comm-1-uni-L1-0004", "commLv": "L1"}],
                                llm_fn=fake_llm))
    assert len(result["changes"]) == 2
    rows = pdb.fetchall("SELECT comm_id, name FROM community_llm_results", ())
    names = {r["comm_id"]: r["name"] for r in rows}
    assert names["comm-1-uni-L0-0007"] == "核心初始化模块"
    assert names["comm-1-uni-L1-0004"] == "HTTP 核心模块族"


def test_resolve_group_rejects_duplicate_and_invalid(pdb):
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core")
    _insert(pdb, "comm-1-uni-L0-0001", "nginx-core-module")

    async def fake_llm(messages, temperature=0.2, max_tokens=800, **kw):
        import json
        # 两个提案归一化后相同（core module / core-module）→ 第二个撞已分配名被拒
        return json.dumps({
            "comm-1-uni-L0-0000": "Core Module",
            "comm-1-uni-L0-0001": "core-module",
        }, ensure_ascii=False)

    result = _run(resolve_group(None, pdb, TASK,
                                [{"commId": "comm-1-uni-L0-0000", "commLv": "L0"},
                                 {"commId": "comm-1-uni-L0-0001", "commLv": "L0"}],
                                llm_fn=fake_llm))
    assert [c["commId"] for c in result["changes"]] == ["comm-1-uni-L0-0000"]
    assert len(result["failed"]) == 1
    rows = pdb.fetchall("SELECT comm_id, name FROM community_llm_results", ())
    names = {r["comm_id"]: r["name"] for r in rows}
    assert names["comm-1-uni-L0-0001"] == "nginx-core-module"


def test_resolve_rejects_overlong_and_commid_like(pdb):
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core")
    _insert(pdb, "comm-1-uni-L0-0001", "nginx-core-module")

    async def fake_llm(messages, temperature=0.2, max_tokens=800, **kw):
        import json
        return json.dumps({
            "comm-1-uni-L0-0000": "c" * 30,
            "comm-1-uni-L0-0001": "comm-e2794136-uni",
        }, ensure_ascii=False)

    result = _run(resolve_group(None, pdb, TASK,
                                [{"commId": "comm-1-uni-L0-0000", "commLv": "L0"},
                                 {"commId": "comm-1-uni-L0-0001", "commLv": "L0"}],
                                llm_fn=fake_llm))
    assert result["changes"] == []
    assert len(result["failed"]) == 2


def test_resolve_group_never_touches_manual(pdb):
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core", manual="人工核心模块")
    _insert(pdb, "comm-1-uni-L0-0001", "nginx-core")

    async def fake_llm(messages, temperature=0.2, max_tokens=800, **kw):
        import json
        # 恶意/失误：试图改 LOCKED 成员
        return json.dumps({
            "comm-1-uni-L0-0000": "被篡改",
            "comm-1-uni-L0-0001": "HTTP 核心模块",
        }, ensure_ascii=False)

    result = _run(resolve_group(None, pdb, TASK,
                                [{"commId": "comm-1-uni-L0-0000", "commLv": "L0"},
                                 {"commId": "comm-1-uni-L0-0001", "commLv": "L0"}],
                                llm_fn=fake_llm))
    assert [c["commId"] for c in result["changes"]] == ["comm-1-uni-L0-0001"]
    rows = pdb.fetchall("SELECT comm_id, name, name_manual FROM community_llm_results", ())
    by_id = {r["comm_id"]: r for r in rows}
    assert by_id["comm-1-uni-L0-0000"]["name"] == "nginx-core"
    assert by_id["comm-1-uni-L0-0000"]["name_manual"] == "人工核心模块"


def test_resolve_group_manual_only_skipped(pdb):
    _insert(pdb, "comm-1-uni-L0-0000", "a模块", manual="a模块")
    _insert(pdb, "comm-1-uni-L0-0001", "a 模块", manual="a 模块")

    async def fake_llm(messages, **kw):
        raise AssertionError("should not call LLM")

    result = _run(resolve_group(None, pdb, TASK,
                                [{"commId": "comm-1-uni-L0-0000", "commLv": "L0"},
                                 {"commId": "comm-1-uni-L0-0001", "commLv": "L0"}],
                                llm_fn=fake_llm))
    assert result["changes"] == []
    assert result.get("skipped")


def test_resolve_single_member_skipped(pdb):
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core")

    async def fake_llm(messages, **kw):
        raise AssertionError("should not call LLM")

    result = _run(resolve_group(None, pdb, TASK,
                                [{"commId": "comm-1-uni-L0-0000", "commLv": "L0"}],
                                llm_fn=fake_llm))
    assert result.get("skipped")


# ==================== clean_community_summaries ====================

def test_clean_community_summaries(pdb):
    dirty = "# 社区: nginx-core\n\n**ID**: comm-1\n\n正文"
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core", summary=dirty)
    _insert(pdb, "comm-1-uni-L0-0001", "http 模块", summary="干净正文")
    result = clean_community_summaries(pdb, TASK)
    assert result["cleaned"] == 1
    row = pdb.fetchone(
        "SELECT summary FROM community_llm_results WHERE comm_id=?",
        ("comm-1-uni-L0-0000",))
    assert row["summary"] == "正文"


def test_clean_skips_empty_summary(pdb):
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core", summary="")
    result = clean_community_summaries(pdb, TASK)
    assert result["cleaned"] == 0
    assert result["scanned"] == 1


# ==================== 占用名校验（含跨组件名） ====================

def test_resolve_avoids_taken_names_in_prompt(pdb):
    _insert(pdb, "comm-1-uni-L0-0000", "nginx-core")
    _insert(pdb, "comm-1-uni-L0-0001", "nginx-core-module")
    _insert(pdb, "comm-1-uni-L0-0002", "已占用模块名")

    captured = {}

    async def fake_llm(messages, temperature=0.2, max_tokens=800, **kw):
        captured["content"] = messages[-1]["content"]
        import json
        return json.dumps({"comm-1-uni-L0-0000": "依赖加载核心",
                           "comm-1-uni-L0-0001": "模块注册框架"}, ensure_ascii=False)

    _run(resolve_group(None, pdb, TASK,
                       [{"commId": "comm-1-uni-L0-0000", "commLv": "L0"},
                        {"commId": "comm-1-uni-L0-0001", "commLv": "L0"}],
                       llm_fn=fake_llm))
    assert "已占用模块名" in captured["content"]
    assert "TAKEN" in captured["content"]
