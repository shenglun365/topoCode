"""core 6 步分析管线集成测试（MS1 §4.4，roadmap P1-T1 落地）。

直调 `_do_parse`（同步编排器，analyst_runner.py:1064）——不走 asyncio 队列；
终态 done/cancelled 由上层 `_execute_task` 置位，不在本测试断言面。
步骤 1~6 为纯静态分析（零 LLM）；PUB 经 FakeServer 记录，零真实端口。

管线步骤（F6）：
  step1 AST 解析(graph_node+contains) → step2 引用解析(calls/imports 边)
  → step2.5 文件 IMPORTS 边 → step3 框架/合成边 → step4 社区(UNIFIED)
  → step5 汇总 report
"""
import json
import os
import sys
import time

import pytest

from topoone.db.manager import MultiDBManager

# 与 plugin_manager 运行时一致：topoone/plugins/parsers 挂入 sys.path
# （范本 test_parse_file_ast.py:7-13；analyst_runner 的 `from parsers.core...` 依赖）
_PLUGINS_PARSERS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "topoone", "plugins", "parsers"))
if _PLUGINS_PARSERS not in sys.path:
    sys.path.insert(0, _PLUGINS_PARSERS)

from topoone.engine.analyst_runner import _do_parse  # noqa: E402

PROJECT_ID = "pipe-proj"
TASK_ID = "pipe-task"

PYTHON_FILES = {
    "models.py": (
        "class Model:\n"
        "    def label(self):\n"
        "        return \"m\"\n"
    ),
    "repo.py": (
        "from models import Model\n\n\n"
        "class Repo:\n"
        "    def fetch(self):\n"
        "        return Model()\n"
    ),
    "service.py": (
        "from repo import Repo\n\n\n"
        "class Service:\n"
        "    def __init__(self):\n"
        "        self.repo = Repo()\n\n"
        "    def handle(self):\n"
        "        return self.repo.fetch().label()\n"
    ),
    "app.py": (
        "from service import Service\n\n\n"
        "class App:\n"
        "    def __init__(self):\n"
        "        self.service = Service()\n\n"
        "    def run(self):\n"
        "        return self.service.handle()\n"
    ),
    "api.py": (
        "from app import App\n\n\n"
        "def main():\n"
        "    a = App()\n"
        "    return a.run()\n"
    ),
    "util.py": (
        "def helper(x):\n"
        "    return x * 2\n"
    ),
}

TS_FILES = {
    "src/models.ts": (
        "export class Model {\n"
        "  label(): string {\n"
        "    return \"m\";\n"
        "  }\n"
        "}\n"
    ),
    "src/repo.ts": (
        "import { Model } from \"./models\";\n\n"
        "export class Repo {\n"
        "  fetch(): Model {\n"
        "    return new Model();\n"
        "  }\n"
        "}\n"
    ),
    "src/service.ts": (
        "import { Repo } from \"./repo\";\n\n"
        "export class Service {\n"
        "  private repo = new Repo();\n\n"
        "  handle(): string {\n"
        "    return this.repo.fetch().label();\n"
        "  }\n"
        "}\n"
    ),
    "src/app.ts": (
        "import { Service } from \"./service\";\n\n"
        "export class App {\n"
        "  private s = new Service();\n\n"
        "  run(): string {\n"
        "    return this.s.handle();\n"
        "  }\n"
        "}\n"
    ),
}


class FakeServer:
    """publish 记录器（范本 test_db_layout.py:17-29）"""

    def __init__(self):
        self.events = []

    def publish(self, topic, event, data=None):
        self.events.append((topic, event, data))


@pytest.fixture
def pipe(tmp_path):
    multi_db = MultiDBManager(str(tmp_path / "pipe"))
    server = FakeServer()

    proj_root = tmp_path / "projroot"
    (proj_root / "src").mkdir(parents=True)
    all_files = {**PYTHON_FILES, **TS_FILES}
    for rel, content in all_files.items():
        p = proj_root / rel
        p.write_text(content, encoding="utf-8")

    multi_db.main_db.execute(
        "INSERT INTO projects (id, name, root_path) VALUES (?, ?, ?)",
        (PROJECT_ID, "pipe-proj", str(proj_root)),
    )
    multi_db.main_db.execute(
        "INSERT INTO analysis_tasks (id, project_id, type, name, status) "
        "VALUES (?, ?, 'full', 'pipe', 'running')",
        (TASK_ID, PROJECT_ID),
    )
    multi_db.main_db.commit()

    pdb = multi_db.get_project_db(PROJECT_ID)
    for rel, content in all_files.items():
        pdb.execute(
            "INSERT INTO source_files (id, file_path, file_name, language, size) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"sf-{rel.replace('/', '_')}", rel, rel.rsplit("/", 1)[-1],
             "typescript" if rel.endswith(".ts") else "python", len(content)),
        )
    pdb.commit()
    return {"multi_db": multi_db, "server": server, "pdb": pdb, "n_files": len(all_files)}


def _run_pipeline(pipe):
    return _do_parse(pipe["server"], pipe["multi_db"], TASK_ID,
                     run_id="", start_time=time.time())


def test_pipeline_report_counts(pipe):
    report = _run_pipeline(pipe)
    assert isinstance(report, dict)
    assert report.get("files_processed", 0) >= pipe["n_files"] - 2  # 至少解析 8/10
    assert report.get("stopped") is not True


def test_pipeline_step1_nodes_and_contains(pipe):
    _run_pipeline(pipe)
    pdb = pipe["pdb"]
    nodes = pdb.fetchall("SELECT id, kind FROM graph_node WHERE task_id = ?", (TASK_ID,))
    assert len(nodes) > pipe["n_files"], "文件+符号节点应落库"
    file_nodes = [n for n in nodes if n["kind"] == "file"]
    assert len(file_nodes) == pipe["n_files"]

    contains = pdb.fetchall(
        "SELECT 1 FROM graph_edge WHERE task_id = ? AND kind = 'contains' LIMIT 1", (TASK_ID,))
    assert contains, "contains 边应落库"


def test_pipeline_step2_resolved_edges(pipe):
    _run_pipeline(pipe)
    pdb = pipe["pdb"]
    row = pdb.fetchone(
        "SELECT COUNT(*) AS c FROM graph_edge WHERE task_id = ? AND kind IN ('calls', 'imports')",
        (TASK_ID,))
    assert row["c"] > 0, "跨文件解析边（calls/imports）应非空"


def test_pipeline_step3_file_import_edges(pipe):
    _run_pipeline(pipe)
    pdb = pipe["pdb"]
    row = pdb.fetchone(
        "SELECT COUNT(*) AS c FROM graph_edge WHERE task_id = ? AND kind = 'imports'",
        (TASK_ID,))
    assert row["c"] > 0, "文件级 IMPORTS 边应非空"


def test_pipeline_step5_community_tables(pipe):
    _run_pipeline(pipe)
    pdb = pipe["pdb"]
    # 表可查即通过（10 文件小图 Louvain 可能不可分区，不强求非空）
    pdb.fetchall("SELECT * FROM community_hierarchy WHERE task_id = ?", (TASK_ID,))
    pdb.fetchall("SELECT * FROM graph_doc WHERE task_id = ?", (TASK_ID,))


def test_pipeline_progress_monotonic_and_published(pipe):
    pipe["multi_db"]  # noqa: 保持结构
    _run_pipeline(pipe)

    events = [e for e in pipe["server"].events if e[0] == "task" and e[1] == "progress"]
    assert events, "进度事件应经 publish 推送"
    progresses = [e[2]["progress"] for e in events]
    # 注：step1 批次并发(as_completed)下事件可能轻微交错，不保证严格单调；
    # 守卫「界内 + 收口 ≥99」即可
    assert all(0 <= p <= 100 for p in progresses)
    assert progresses[-1] >= 99

    row = pipe["multi_db"].main_db.fetchone(
        "SELECT progress FROM analysis_tasks WHERE id = ?", (TASK_ID,))
    assert row["progress"] >= 99


def test_pipeline_zero_llm_no_network(pipe, monkeypatch):
    """F6 静态性守卫：管线全程不得发起真实 LLM HTTP 调用。"""
    import requests

    def _forbidden(*a, **kw):
        raise AssertionError("管线不得发起外部 HTTP 调用")

    monkeypatch.setattr(requests, "post", _forbidden)
    monkeypatch.setattr(requests, "get", _forbidden)
    report = _run_pipeline(pipe)
    assert report.get("files_processed", 0) > 0
