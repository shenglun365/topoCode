"""「查找关联」KB 候选匹配单元测试。

覆盖 `project.py` 的 `_classify_kb_source` / `_match_kb_candidates`：
  - 本地仓库地址(源码路径/缓存/本地 repo 来源)为主 → `local` 组；
  - 工作目录 git origin 与 KB 远端一致 → `remote` 组；
  - 两组同时返回，未命中对应组为空。

Run:  cd <repo> && python -m pytest plugins/architect/tests/test_kb_match.py -q
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import plugins.architect.arch_routes.project as P


def _rows():
    return [
        {"id": "kb-s", "name": "s", "rootPath": "/repos/order-service",
         "sourceCacheDir": "", "remoteUrl": "", "localRepoPath": "/repos/order-service",
         "currentVersionId": "v", "status": "ready",
         "gitLinked": True, "hasBaseline": True},
        {"id": "kb-r", "name": "r", "rootPath": "/repos/order2",
         "sourceCacheDir": "", "remoteUrl": "git@example.com:acme/order-service.git",
         "localRepoPath": "", "currentVersionId": "v",
         "gitLinked": True, "hasBaseline": True},
    ]


def test_local_and_remote_groups_returned_together(monkeypatch):
    """同一工作目录可同时命中两组：本地路径命中 local，仅有远端一致命中 remote。"""
    monkeypatch.setattr(P, "_list_kb_projects", _rows)
    monkeypatch.setattr(P, "_git_origin", lambda path: "git@example.com:acme/order-service.git")
    res = P._match_kb_candidates("/repos/order-service/worktrees/main")
    assert res["level"] if "level" in res else True
    assert {m["id"] for m in res["local"]} == {"kb-s"}
    assert {m["id"] for m in res["remote"]} == {"kb-r"}
    assert res["local"][0]["matchLevel"] == "local"
    assert res["remote"][0]["matchLevel"] == "remote"


def test_local_only(monkeypatch):
    """只有本地路径命中：remote 组为空。"""
    monkeypatch.setattr(P, "_list_kb_projects", lambda: _rows()[:1])
    monkeypatch.setattr(P, "_git_origin", lambda path: "")
    res = P._match_kb_candidates("/repos/order-service")
    assert [m["id"] for m in res["local"]] == ["kb-s"]
    assert res["remote"] == []


def test_remote_only(monkeypatch):
    """本地无路径重叠、仅远端一致：local 组为空、remote 组命中。"""
    monkeypatch.setattr(P, "_list_kb_projects", lambda: _rows()[1:])
    monkeypatch.setattr(P, "_git_origin", lambda path: "git@example.com:acme/order-service.git")
    res = P._match_kb_candidates("/work/order-service")
    assert res["local"] == []
    assert [m["id"] for m in res["remote"]] == ["kb-r"]


def test_remote_disabled_when_arch_origin_missing(monkeypatch):
    """工作目录非 git 仓库(无 origin) → 即使 KB 配了远端也不进 remote 组。"""
    monkeypatch.setattr(P, "_list_kb_projects", lambda: _rows()[1:])
    monkeypatch.setattr(P, "_git_origin", lambda path: "")
    res = P._match_kb_candidates("/work/no-git")
    assert res["local"] == []
    assert res["remote"] == []


def test_no_match_both_empty(monkeypatch):
    monkeypatch.setattr(P, "_list_kb_projects", lambda: [
        {"id": "kb-x", "name": "x", "rootPath": "/repos/other",
         "sourceCacheDir": "", "remoteUrl": "", "localRepoPath": "",
         "currentVersionId": "v", "gitLinked": True, "hasBaseline": True},
    ])
    monkeypatch.setattr(P, "_git_origin", lambda path: "")
    res = P._match_kb_candidates("/work/elsewhere")
    assert res["local"] == []
    assert res["remote"] == []


def test_cache_dir_is_local(monkeypatch):
    """arch 工作目录位于 KB 源码缓存目录内 → 计入 local 组。"""
    monkeypatch.setattr(P, "_list_kb_projects", lambda: [
        {"id": "kb-c", "name": "c", "rootPath": "",
         "sourceCacheDir": "/cache/order-service", "remoteUrl": "",
         "localRepoPath": "", "currentVersionId": "v",
         "gitLinked": True, "hasBaseline": True},
    ])
    res = P._match_kb_candidates("/cache/order-service/worktrees/x")
    assert [m["id"] for m in res["local"]] == ["kb-c"]
    assert res["remote"] == []