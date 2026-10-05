"""链路跟踪(链路深度探索)：符号级 DFS 链树/环/剪枝/资产聚合/降级/展开端点。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio, json, sqlite3
import pytest

import topoone_app_architect.ctx as C
from topoone_app_architect.store import ProjectsStore, SemanticAssetsStore


PID = "proj-trace"


def _ctx_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path / "data"))
    C._db = None
    C._kb = None
    C.setup(data_dir=str(tmp_path / "data"))
    ProjectsStore.upsert(PID, {"name": "t", "rootPath": str(tmp_path)})


@pytest.fixture()
def env(tmp_path, monkeypatch):
    _ctx_setup(tmp_path, monkeypatch)
    # 符号库(内存, codegraph schema): A→B→C 链 + A→D + D→B(环) + B→E(超深截断候选)
    conn = sqlite3.connect(":memory:", check_same_thread=False)   # to_thread 线程查询
    conn.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, name TEXT, "
                 "qualified_name TEXT, file_path TEXT, start_line INT, end_line INT)")
    conn.execute("CREATE TABLE edges (id INTEGER PRIMARY KEY, source TEXT, target TEXT, "
                 "kind TEXT, metadata TEXT, line INT, col INT)")
    nodes = [("n-a", "func", "fa", "m::fa", "a.ts"), ("n-b", "func", "fb", "m::fb", "b.ts"),
             ("n-c", "func", "fc", "m::fc", "c.ts"), ("n-d", "func", "fd", "m::fd", "d.ts"),
             ("n-e", "func", "fe", "m::fe", "e.ts")]
    for nid, k, nm, qn, fp in nodes:
        conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?,0,0)", (nid, k, nm, qn, fp))
    edges = [("n-a", "n-b", "calls", 0.9, 10), ("n-a", "n-d", "calls", 0.8, 20),
             ("n-b", "n-c", "calls", 0.9, 30), ("n-d", "n-b", "calls", 0.7, 40),
             ("n-b", "n-e", "references", 0.9, 50)]   # references 默认不入链
    for i, (s, t, k, conf, line) in enumerate(edges):
        conn.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,0)",
                     (i + 1, s, t, k, json.dumps({"confidence": conf}), line))
    conn.commit()
    monkeypatch.setattr("topoone_app_architect.sem.trace.open_symbol_conn",
                        lambda root, project: (conn, "test"))
    monkeypatch.setattr("topoone_app_architect.sem.trace.close_symbol_conn",
                        lambda c: None)
    monkeypatch.setattr("topoone_app_architect.sem.symbol_notes.open_symbol_conn",
                        lambda root, project: (conn, "test"))
    monkeypatch.setattr("topoone_app_architect.sem.symbol_notes.close_symbol_conn",
                        lambda c: None)
    from topoone_app_architect.sem import trace as T
    T._cache.clear()
    yield conn


def _mk_asset(aid, name, syms):
    SemanticAssetsStore.create({
        "id": aid, "projectId": PID, "kind": "asset", "level": "implementation",
        "name": name, "desc": "", "detail": {"relations": []},
        "astRefs": [{"symbol": s} for s in syms], "scopeType": "comm",
        "scopeKey": "L0-0001", "srcHash": "h", "change": "added",
        "status": "active", "createdAt": 1, "updatedAt": 1})


def test_trace_down_chain(env):
    """下游链: A→B→C 主链; D→B 环截断; references 边不入链; 资产聚合。"""
    from topoone_app_architect.sem import trace as T
    _mk_asset("sa-a", "资产A", ["m::fa"])
    _mk_asset("sa-c", "资产C", ["m::fc"])
    r = T.trace(None, PID, "sa-a", direction="down")
    tr = r["trace"]
    assert not tr["stats"]["degraded"]
    root = tr["root"]
    assert root["id"] == "n-a" and root["assetId"] == "sa-a"
    kids = root["children"]
    by = {k["id"]: k for k in kids}
    assert set(by) == {"n-b", "n-d"}            # references(e) 不入链
    assert by["n-b"]["children"][0]["id"] == "n-c"
    assert by["n-b"]["children"][0]["assetId"] == "sa-c"   # 途经资产聚合
    d = by["n-d"]["children"][0]
    # D→B: B 已在主分支展开(seen_global) → 跨分支引用标记(不重复建子树)
    assert d["id"] == "n-b" and d.get("seenElsewhere")
    # 路径列表: 根→叶 完整链(叶=终态/引用截断)
    flat = [p[-1]["id"] for p in tr["paths"]]
    assert "n-c" in flat and "n-b" in flat


def test_trace_up_direction(env):
    """上游: C 的 up = B ← A/D; B 上游排序按 confidence。"""
    from topoone_app_architect.sem import trace as T
    _mk_asset("sa-c", "资产C", ["m::fc"])
    r = T.trace(None, PID, "sa-c", direction="up")
    kids = r["trace"]["root"]["children"]
    assert {k["id"] for k in kids} == {"n-b"}
    up2 = kids[0]["children"]
    assert {k["id"] for k in up2} == {"n-a", "n-d"}      # B 的上游两条


def test_trace_branch_limit_and_expand(env):
    """分支剪枝: branch_limit=1 只留 top(confidence); expand 以中途符号为根。"""
    from topoone_app_architect.sem import trace as T
    _mk_asset("sa-a", "资产A", ["m::fa"])
    r = T.trace(None, PID, "sa-a", direction="down", branch_limit=1)
    kids = r["trace"]["root"]["children"]
    assert len(kids) == 1 and kids[0]["id"] == "n-b"     # conf 0.9 优先
    assert r["trace"]["root"]["truncated"] == 1          # 另 1 条被剪
    # 懒加载展开: 以 n-d 为根
    e = T.trace_expand(None, PID, "m::fd", direction="down")
    assert e["trace"]["root"]["id"] == "n-d"
    assert e["trace"]["root"]["children"][0]["id"] == "n-b"


def test_trace_degraded_without_symbol_graph(tmp_path, monkeypatch):
    """符号库缺失 → 降级资产 relations 图 DFS(degraded=True)。"""
    _ctx_setup(tmp_path, monkeypatch)
    from topoone_app_architect.sem import trace as T
    T._cache.clear()
    monkeypatch.setattr("topoone_app_architect.sem.trace.open_symbol_conn",
                        lambda root, project: (None, "none"))
    SemanticAssetsStore.create({
        "id": "sa-x", "projectId": PID, "kind": "asset", "level": "implementation",
        "name": "X", "desc": "", "detail": {"relations": [
            {"target": "Y", "type": "calls"}]},
        "astRefs": [], "scopeType": "comm", "scopeKey": "k", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    SemanticAssetsStore.create({
        "id": "sa-y", "projectId": PID, "kind": "asset", "level": "implementation",
        "name": "Y", "desc": "", "detail": {"relations": []},
        "astRefs": [], "scopeType": "comm", "scopeKey": "k", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})
    r = T.trace(None, PID, "sa-x", direction="down")
    tr = r["trace"]
    assert tr["stats"]["degraded"]
    assert tr["root"]["children"][0]["assetId"] == "sa-y"


def test_symbol_detail_and_note(env):
    """符号详情: 元数据+代码段切片; AI 解读缓存 put/get; 详情携带缓存。"""
    from topoone_app_architect.sem.paths import project_id_for
    from topoone_app_architect.sem.symbol_notes import (
        symbol_detail, symbol_note_get, symbol_note_put)
    d = symbol_detail(None, PID, "m::fb")
    assert d["meta"]["file"] == "b.ts" and d["meta"]["startLine"] == 0
    assert isinstance(d["snippet"], str)
    pid = project_id_for(None, PID)
    symbol_note_put(pid, "m::fb", "fb 是测试符号")
    assert symbol_note_get(pid, "m::fb") == "fb 是测试符号"
    d2 = symbol_detail(None, PID, "m::fb")
    assert d2["note"] == "fb 是测试符号"          # 详情携带缓存
    # API: symbol-note 缓存回显(生成降级 → 回退缓存)
    from topoone_app_architect.arch_routes import sem_trace as api

    class _ReqJson:
        def __init__(self, payload):
            self._p = payload

        async def json(self):
            return self._p

    out = asyncio.run(api.api_symbol_note(_ReqJson({"project": PID, "symbol": "m::fb"})))
    assert out["data"]["note"] == "fb 是测试符号" and out["data"]["cached"]


def test_trace_api_endpoint(env):
    """API: /kb/semantic/trace asset 整链 + symbol 展开 + 缺参 400。"""
    from topoone_app_architect.arch_routes import sem_trace as api
    _mk_asset("sa-a", "资产A", ["m::fa"])

    class _Req:
        pass

    out = asyncio.run(api.api_trace(project=PID, asset="sa-a", direction="down"))
    assert not out["data"]["trace"]["stats"]["degraded"], out
    assert out["data"]["trace"]["root"]["id"] == "n-a"
    out = asyncio.run(api.api_trace(project=PID, symbol="m::fb", direction="down"))
    assert out["data"]["trace"]["root"]["id"] == "n-b"
    out = asyncio.run(api.api_trace(project=PID))
    assert json.loads(out.body)["code"] == 400            # err → JSONResponse
    out = asyncio.run(api.api_trace(project=PID, asset="sa-nonexist"))
    assert json.loads(out.body)["code"] == 404
