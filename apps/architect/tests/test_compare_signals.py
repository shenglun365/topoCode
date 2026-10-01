"""对比变化信号（BE）：changed 资产行级 hasAdded/hasDeleted（锚点段 ∩ 两侧 hunk）。

真实 git 仓库三文件三形态：a.py 纯删行 / b.py 纯增行 / c.py 行替换(有增有删)——
信号点判定（绿=含新增/红=含删除）的数据源。
"""
import subprocess
import sys

import pytest

sys.path.insert(0, ".")

import topoone_app_architect.ctx as C
import topoone_app_architect.store as store
from topoone_app_architect.arch_routes import semantic_assets as S
from topoone_app_architect.sem import compare as CMP


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C.setup(data_dir=data)
    yield
    C._db = None
    C._kb = None


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    repo = tmp_path / "src"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("l1\nl2\nl3\nl4\nl5\n")
    (repo / "b.py").write_text("m1\nm2\nm3\n")
    (repo / "c.py").write_text("n1\nn2\nn3\nn4\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    # a.py 纯删一行；b.py 纯增两行；c.py 行替换(删1增1)
    (repo / "a.py").write_text("l1\nl2\nl4\nl5\n")
    (repo / "b.py").write_text("m1\nm2\nm3\nm4\nm5\n")
    (repo / "c.py").write_text("n1\nn2-X\nn3\nn4\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return repo, base


def _mk_asset(pid, aid, fname):
    store.SemanticAssetsStore.create({
        "id": aid, "projectId": pid, "kind": "asset", "level": "implementation",
        "name": aid, "desc": "", "detail": {},
        "astRefs": [{"file": fname, "symbol": aid, "startLine": 1, "endLine": 50}],
        "anchorHashes": {fname: "deadbeef"},   # 不匹配两侧 → side=stale(保守口径仍判信号)
        "scopeType": "files", "scopeKey": "", "srcHash": "h",
        "change": "added", "status": "active", "createdAt": 1, "updatedAt": 1})


def test_compare_signals_added_deleted(repo, ctx):
    """changed 资产行级信号：纯删→hasDeleted；纯增→hasAdded；替换→双信号。"""
    r, base = repo
    pid = S.project_id_for(str(r), None)
    _mk_asset(pid, "sa-a", "a.py")
    _mk_asset(pid, "sa-b", "b.py")
    _mk_asset(pid, "sa-c", "c.py")
    res = CMP.compare_changes(str(r), None, base=base, target="worktree")
    assert not res.get("error"), res.get("error")
    by_id = {a["id"]: a for a in res["assets"]["changed"]}
    assert set(by_id) == {"sa-a", "sa-b", "sa-c"}
    assert by_id["sa-a"]["hasDeleted"] is True and by_id["sa-a"]["hasAdded"] is False
    assert by_id["sa-b"]["hasAdded"] is True and by_id["sa-b"]["hasDeleted"] is False
    assert by_id["sa-c"]["hasAdded"] is True and by_id["sa-c"]["hasDeleted"] is True
