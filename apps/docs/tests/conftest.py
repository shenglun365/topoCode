
# MS7-W4: diagram-editor 运行时跨服务 import topoone_app_chat——包体已迁
# apps/workbench/chat_service/，测试环境经 sys.path 引导（生产由 setup.sh editable 覆盖）。
import sys as _sys
from pathlib import Path as _Path

_CHAT_PKG_PARENT = str(_Path(__file__).resolve().parents[2] / "workbench" / "chat_service")
if _CHAT_PKG_PARENT not in _sys.path:
    _sys.path.insert(0, _CHAT_PKG_PARENT)

"""docs 服务测试夹具——临时数据目录 + 全局态设置/复位 + TestClient。

纪律（MS1 §4.6）：service_common 全局态是进程级单例，每个用例 teardown
必须复位 common.multi_db，防止跨套件/跨用例泄漏（同 architect isolate_arch）。

性能约束（MS1 §5：整套 ≤30s）：app/sidecar 会话级单实例；
用例间隔离靠 unique 种子 project/task id（seeded_db fixture）。
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from topoone import service_common as common
from topoone.db.manager import MultiDBManager


@pytest.fixture(scope="session")
def docs_env(tmp_path_factory):
    data_dir = str(tmp_path_factory.mktemp("docsdata"))
    multi_db = MultiDBManager(data_dir)
    common.set_globals(multi_db, port=3481)
    yield multi_db
    common.multi_db = None
    common.plantuml_cache_db = None
    multi_db.close_all()


@pytest.fixture(scope="session")
def client(docs_env):
    """build_app + TestClient（context manager 触发 lifespan，渲染池按需降级）。"""
    from topoone_app_docs.main import build_app

    app = build_app(docs_env.data_dir, port=3481)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def seeded_db(client, docs_env, tmp_path):
    """用例级最小项目：唯一 id 的 projects/analysis_tasks 行 + 物化项目库 + 源码 2 文件。"""
    suffix = uuid.uuid4().hex[:8]
    project_id = f"proj-{suffix}"
    task_id = f"task-{suffix}"
    multi_db = docs_env

    project_root = tmp_path / "projroot"
    (project_root / "pkg").mkdir(parents=True)
    (project_root / "pkg" / "mod_a.py").write_text("def fa():\n    return 1\n", encoding="utf-8")
    (project_root / "README.md").write_text("# seed\n", encoding="utf-8")

    multi_db.main_db.execute(
        "INSERT INTO projects (id, name, root_path) VALUES (?, ?, ?)",
        (project_id, f"proj-{suffix}", str(project_root)),
    )
    multi_db.main_db.execute(
        "INSERT INTO analysis_tasks (id, project_id, type, name) VALUES (?, ?, 'full', 'task-1')",
        (task_id, project_id),
    )
    multi_db.main_db.commit()
    multi_db.get_project_db(project_id)  # 物化项目库（自动建全 schema）
    return {"project_id": project_id, "task_id": task_id, "root": str(project_root),
            "project_db": multi_db.get_project_db(project_id)}
