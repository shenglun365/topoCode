"""git 历史探测(基线锚定选单)特征测试: 分支列表 + 提交分页/搜索/hash 前缀。

契约：git_branches 仅列本地分支并含当前分支；git_log 支持 branch/offset/limit
分页与 search(message/作者, 忽略大小写 OR)与 ≥4 位 hex hash 前缀置顶(仅首页去重)。
"""
import subprocess

import pytest

from topoone_app_architect.arch_routes.git_probe import git_branches, git_log


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args],
                   check=True, capture_output=True, text=True)


def _commit(root, msg, author="t"):
    _git(root, "-c", f"user.name={author}", "-c", "user.email=t@t",
         "commit", "--allow-empty", "-m", msg)


@pytest.fixture()
def repo(tmp_path):
    """main 分支 3 commit + dev 分支 1 commit。"""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "c1 first")
    hashes = {}
    hashes["c1"] = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
    _commit(r, "c2 polish wording", "alice")
    _commit(r, "c3 last")
    _git(r, "checkout", "-b", "dev")
    _commit(r, "d1 dev only")
    _git(r, "checkout", "main")
    return {"root": str(r), "c1": hashes["c1"]}


def test_git_branches_local_only(repo):
    b = git_branches(repo["root"])
    assert set(b["branches"]) == {"main", "dev"}
    assert b["current"] == "main"


def test_git_log_pagination(repo):
    page1 = git_log(repo["root"], limit=2, offset=0)
    page2 = git_log(repo["root"], limit=2, offset=2)
    assert [r["message"] for r in page1] == ["c3 last", "c2 polish wording"]
    assert [r["message"] for r in page2] == ["c1 first"]
    assert page1[0]["isHead"] is True and page2[0]["isHead"] is False


def test_git_log_branch_scope(repo):
    msgs = [r["message"] for r in git_log(repo["root"], branch="dev", limit=10)]
    assert msgs[0] == "d1 dev only" and len(msgs) == 4   # 含 main 历史


def test_git_log_search_message_author(repo):
    # message 命中(大小写不敏感)
    m = git_log(repo["root"], search="POLISH", limit=10)
    assert len(m) == 1 and m[0]["message"] == "c2 polish wording"
    # 作者命中
    a = git_log(repo["root"], search="alice", limit=10)
    assert len(a) == 1 and a[0]["author"] == "alice"
    # 无命中
    assert git_log(repo["root"], search="不存在的关键字xyz", limit=10) == []


def test_git_log_search_hash_prefix(repo):
    sha = repo["c1"]
    rows = git_log(repo["root"], search=sha[:8], limit=10)
    assert rows and rows[0]["hash"] == sha          # hash 前缀解析置顶
    # 非 hash 文本不走 rev-parse
    assert git_log(repo["root"], search="zzzz-not-hex", limit=10) == []
