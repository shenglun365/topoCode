"""需求文档投影 特征测试(cv-272)。

用户裁决: DB=真相源, 文档=dispatch 时投影的运行期快照(`.topo/docs/{reqId}/`
四件), 指令瘦身(要点+强指引)/written 缺失降级/任务轮次淘汰(终态即删/
waiting 保留/孤儿清扫)/并行范围重叠软警告(警告+可继续)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_req_docs.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.store as store
from topoone_app_architect.agent.execution import process_stream as ps
from topoone_app_architect.agent.execution import proxy
from topoone_app_architect.agent.execution.req_docs import (
    docs_dir_rel, project_docs)
# 同目录兄弟模块按路径加载(tests 无包结构——幻影测试纪律, 不加 __init__.py)
import importlib.util as _ilu
_spec_tei = _ilu.spec_from_file_location(
    "test_exec_implement", os.path.join(os.path.dirname(__file__),
                                        "test_exec_implement.py"))
_tei = _ilu.module_from_spec(_spec_tei)
_spec_tei.loader.exec_module(_tei)


def _seed_spec(rid: str = "rq-docs") -> None:
    snap = {"requirementMd": "# 需求全文\n做 X", "designMd": "# 设计\n用 Y",
            "allowedScope": ["docs/guide.md"], "scopeOut": "不做 Z",
            "acceptance": ["验收 1", "验收 2"]}
    store.RequirementsStore.create({"id": rid, "title": "t"})
    store.RequirementsStore.spec_append(rid, snap, actor="user", conv_id="cv-1")
    store.RequirementsStore.spec_confirm(rid)


def test_project_docs_four_files_full_fidelity(arch_env):
    _seed_spec()
    files = project_docs("rq-docs", boundary_files=["src/x/a.py"])
    paths = {f["path"] for f in files}
    assert paths == {".topo/docs/rq-docs/SPEC.md", ".topo/docs/rq-docs/DESIGN.md",
                     ".topo/docs/rq-docs/ACCEPTANCE.md",
                     ".topo/docs/rq-docs/BOUNDARY.md"}
    spec = next(f for f in files if f["path"].endswith("SPEC.md"))
    assert spec["content"] == "# 需求全文\n做 X", "规约全文不截断"
    acc = next(f for f in files if f["path"].endswith("ACCEPTANCE.md"))
    assert "验收 1" in acc["content"] and "不做 Z" in acc["content"]
    bnd = next(f for f in files if f["path"].endswith("BOUNDARY.md"))
    assert "src/x/a.py" in bnd["content"]


def test_project_docs_no_rid_or_empty_snap(arch_env):
    assert project_docs("") == []
    assert project_docs("rq-none") == []


def test_tool_self_count_and_fold_snapshot():
    """tool 自计数(cline 只发 tool 不发 progress→计数不恒 0)+折叠快照本轮环长。"""
    prog: dict = {}
    for i in range(3):
        prog = ps.apply_event(prog, {"kind": "tool", "toolName": f"t{i}"})
    assert prog["toolCount"] == 3
    # progress 报数取大(不回退)
    prog = ps.apply_event(prog, {"kind": "progress", "toolCount": 9,
                                 "msgCount": 1})
    assert prog["toolCount"] == 9


def test_dispatch_slim_instruction_and_docs_payload(tmp_path, monkeypatch):
    """dispatch 端到端: 绑规约任务 → 载荷含 .topo/docs 四件 + 指令瘦身
    (强指引进/规约全文不进); 未绑规约回落全量注入。"""
    conv, eb, calls = _tei._mk_v2_fixture(tmp_path, monkeypatch)
    _seed_spec()
    task = eb.propose_task(conv, "文档投影任务", "x")
    store.TasksStore.update(task["id"], {"reqId": "rq-docs", "specVer": 1})
    r = eb.confirm_task(task["id"])
    assert r["ok"]
    payload = next(pl for p, pl in calls["implement"] if p == "/api/implement")
    docs = [f for f in (payload.get("workspaceFiles") or [])
            if f["path"].startswith(".topo/docs/rq-docs/")]
    assert {f["path"].split("/")[-1] for f in docs} == {
        "SPEC.md", "DESIGN.md", "ACCEPTANCE.md", "BOUNDARY.md"}
    instr = payload["instruction"]
    assert "执行前必读" in instr and ".topo/docs/rq-docs/" in instr
    assert "# 需求全文" not in instr, "规约全文应只进文档(指令瘦身)"


def test_dispatch_fallback_full_render_without_spec(tmp_path, monkeypatch):
    """未绑规约: 无投影 → 指令回落全量 context pack(送达优先)。"""
    conv, eb, calls = _tei._mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "无规约任务", "x")
    r = eb.confirm_task(task["id"])
    assert r["ok"]
    payload = next(pl for p, pl in calls["implement"] if p == "/api/implement")
    assert "上下文包(执行契约)" in payload["instruction"]
    assert not [f for f in (payload.get("workspaceFiles") or [])
                if f["path"].startswith(".topo/docs/")]


def test_orphan_docs_sweep_on_dispatch(tmp_path, monkeypatch):
    """孤儿清扫: 无活跃任务的 reqId 目录在 dispatch 时移除; 活跃保留。"""
    conv, eb, calls = _tei._mk_v2_fixture(tmp_path, monkeypatch)
    root = tmp_path / "proj"
    docs = root / ".topo" / "docs"
    (docs / "rq-stale").mkdir(parents=True)
    (docs / "rq-stale" / "SPEC.md").write_text("旧投影")
    (docs / "rq-live").mkdir(parents=True)
    other = store.ConversationsStore.create({
        "projectId": "proj-v2", "title": "他会话", "meta": {"root": str(root)}})
    t = eb.propose_task(other, "进行中", "x")
    store.TasksStore.update(t["id"], {"reqId": "rq-live", "status": "running"})
    task = eb.propose_task(conv, "新任务", "y")
    eb.confirm_task(task["id"])
    assert not (docs / "rq-stale").exists(), "孤儿目录应被清扫"
    assert (docs / "rq-live").exists(), "活跃任务目录保留"


def test_overlap_warning_soft_lands_and_continues(tmp_path, monkeypatch):
    """并行范围重叠: 跨会话活跃任务边界求交 → 软警告落流(task_overlap 卡)+
    派发继续(警告+可继续, 非硬拦)。"""
    conv, eb, calls = _tei._mk_v2_fixture(tmp_path, monkeypatch)
    _seed_spec()
    # 他会话活跃任务(同 reqId → 边界集相交)
    other = store.ConversationsStore.create({
        "projectId": "proj-v2", "title": "他会话", "meta": {"root": str(tmp_path / "proj")}})
    t_other = eb.propose_task(other, "进行中任务", "x")
    store.TasksStore.update(t_other["id"], {"reqId": "rq-docs", "status": "running"})
    task = eb.propose_task(conv, "重叠任务", "x")
    store.TasksStore.update(task["id"], {"reqId": "rq-docs", "specVer": 1})
    r = eb.confirm_task(task["id"])
    assert r["ok"], "软警告不拦派发"
    msgs = store.ConversationsStore.messages(conv["id"], limit=20)
    overlap = [m for m in msgs
               if (m.get("meta") or {}).get("kind") == "task_overlap"]
    assert overlap and "重叠" in overlap[0]["content"], "软警告未落流"
    assert "进行中任务" in overlap[0]["content"], "应指明冲突任务"
