"""kb_link.py — architect 项目 ↔ KB 项目 关联子系统(自 project.py 拆分, §8.2)。

- KB 项目映射/查询(_list_kb_projects/_lookup_kb/_kb_baseline_head)
- 同一仓库源校验(_classify_kb_source/_same_repo_source/_match_kb_candidates)
- 关联核心 link_arch_to_kb(概览页「查找关联」与 ensure-baseline 冷启动自动关联共用)
"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, Optional

from ..agent.governance.timeouts import get as _timeout_of
from ..common import _ts
from .. import store

_DEFAULT_CONFIG = {"estMinMin": 60, "estMinMax": 480, "acceptanceMax": 4, "p0SubsetMax": 5}

# KB 项目字段映射: main_db.projects 的 snake_case 列 → architect 消费的 camelCase。
# 派生字段 gitLinked/hasBaseline 供「选择 KB 项目做关联」做门槛判定(避免错误关联)。
_KB_FIELDS = {
    "id": "id", "name": "name", "root_path": "rootPath",
    "import_mode": "importMode", "remote_url": "remoteUrl",
    "local_repo_path": "localRepoPath", "source_cache_dir": "sourceCacheDir",
    "current_version_id": "currentVersionId", "status": "status",
    "language": "language", "file_count": "fileCount",
    "done_task_count": "doneTaskCount", "updated_at": "updatedAt",
}


def _kb_call(method: str, **params):
    """调用 KB 方法(经 ctx 网关，拓扑无关)；结果 None/错误时回退。"""
    from ..kb_gateway import call_kb
    return call_kb(method, **params)


def _list_kb_projects() -> list:
    """拉取 KB 全部项目(project.list)并映射为 architect 形状。"""
    rows = _kb_call("project.list") or []
    out = []
    for r in rows:
        item = {}
        for src, dst in _KB_FIELDS.items():
            if src in r:
                item[dst] = r[src]
        item["gitLinked"] = item.get("importMode") in ("git-local", "git-remote")
        item["hasBaseline"] = bool(item.get("currentVersionId"))
        item["sourceDir"] = item.get("rootPath") or ""
        if "sourceCacheDir" in item and not item["sourceCacheDir"]:
            item["sourceCacheDir"] = None
        out.append(item)
    return out


def _lookup_kb(kb_id: str) -> Optional[dict]:
    for p in _list_kb_projects():
        if p["id"] == kb_id:
            return p
    return None


def _kb_baseline_head(kb_project_id: str, baseline_id: str = "") -> str:
    """取 KB 项目基线版本对应的 head commit（version.list；baselineId 精确匹配，缺省取最新版本）。"""
    if not kb_project_id:
        return ""
    try:
        from ..kb_gateway import call_kb
        versions = call_kb("version.list", projectId=kb_project_id) or []
    except Exception:
        return ""
    if baseline_id:
        for v in versions:
            if v.get("id") == baseline_id:
                return v.get("head") or ""
    return (versions[0].get("head") or "") if versions else ""


# ── 同一仓库源校验 ───────────────────────────────────────────────

def _norm_url(u: str) -> str:
    u = (u or "").strip()
    u = u.replace("git@", "").replace("ssh://", "")
    if ":" in u and "/" in u and not u.startswith("http"):
        u = u.replace(":", "/", 1)
    return u.rstrip("/").removesuffix(".git").lower()


def _git_origin(path: str) -> str:
    if not os.path.isdir(path):
        return ""
    try:
        r = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=_timeout_of("git_status"),
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _is_subpath(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(child), os.path.abspath(parent)]) == os.path.abspath(parent)
    except Exception:
        return False


def _classify_kb_source(arch_root: str, kb: dict) -> str:
    """将 architect 工作目录与 KB 匹配分类：本地仓库地址优先，远端作为辅助。

    返回 ''(不匹配) / 'local'(本地 repo/源码路径重叠) / 'remote'(仅 git 远端一致)。
    """
    arch = os.path.abspath(str(arch_root))
    kb_root = kb.get("rootPath") or ""
    kb_cache = kb.get("sourceCacheDir") or ""
    kb_remote = kb.get("remoteUrl") or ""
    kb_local = kb.get("localRepoPath") or ""
    if kb_root and _is_subpath(arch, kb_root):
        return "local"
    if kb_cache and _is_subpath(arch, kb_cache):
        return "local"
    if kb_local and os.path.abspath(kb_local) == arch:
        return "local"
    a_remote = _norm_url(_git_origin(arch))
    if not a_remote:
        return ""
    if kb_remote and _norm_url(kb_remote) == a_remote:
        return "remote"
    k_remote = _norm_url(_git_origin(kb_root))
    if k_remote and k_remote == a_remote:
        return "remote"
    return ""


def _same_repo_source(arch_root: str, kb: dict) -> tuple:
    """判定 architect 工作目录与 KB 源码为同一仓库源。返回 (ok, reason/error)。"""
    kind = _classify_kb_source(arch_root, kb)
    if kind == "local":
        return True, "architect 工作目录为 KB 源码目录/缓存目录/本地仓库来源路径"
    if kind == "remote":
        return True, "git 远端一致"
    return False, "architect 工作目录与所选 KB 项目不是同一仓库源（路径不重叠、git 远端/本地仓库路径不匹配）"


def _match_kb_candidates(arch_root: str, rows: Optional[list] = None) -> dict:
    """「查找关联」候选：本地仓库地址为主参数、远端地址为辅参数，两组同时返回。

    - `local`：arch 工作目录与 KB 本地仓库/源码缓存/路径重叠命中(主)；
    - `remote`：arch 工作目录 git origin 与 KB 远端一致命中(仅两端都配了远端才成立)；
    - 两组各自独立列出命中候选；未命中该组为空数组，由前端逐组标明「无」。
    """
    rows = list(rows) if rows else _list_kb_projects()
    local = []
    remote = []
    for p in rows:
        kind = _classify_kb_source(arch_root, p)
        if kind == "local":
            p["matchLevel"] = "local"
            local.append(p)
        elif kind == "remote":
            p["matchLevel"] = "remote"
            remote.append(p)
    return {
        "workDir": arch_root,
        "remoteUrl": _git_origin(arch_root) or "",
        "local": local,
        "remote": remote,
    }


_LINK_REFRESH_TTL = 300  # 自动关联幂等窗(秒): 已关联同一 KB 且校验未过期则跳过


def link_arch_to_kb(proj: Optional[dict], kb_id: str,
                    refresh_ttl: int = _LINK_REFRESH_TTL) -> tuple:
    """architect 项目 ↔ KB 项目 关联核心(概览页「查找关联」与
    ensure-baseline 冷启动自动关联共用)。

    校验(存在性/gitLinked/hasBaseline/同一仓库源) + upsert 关联字段。
    返回 (ok, 项目数据或原因)。
    幂等: 已关联同一 kb_id 且 linkVerifiedAt 未过 refresh_ttl → 直接返回
    (ensure-baseline 轮询每 2.5s 一次, 不能每轮做 git 校验)。
    """
    kb = _lookup_kb(kb_id)
    if not kb:
        return False, "KB 项目中不存在该 id"
    if not kb.get("gitLinked") or not kb.get("hasBaseline"):
        return False, "该项目未 git 关联或尚无知识库基线，无法安全关联"
    if not proj or not proj.get("rootPath"):
        return False, "未定位到要关联的 architect 项目(缺 rootPath)"
    arch_root = proj["rootPath"]
    now = _ts()
    if proj.get("kbProjectId") == kb["id"] and refresh_ttl > 0:
        if now - (proj.get("linkVerifiedAt") or 0) < refresh_ttl:
            return True, "already-linked"
    from . import arch_git
    arch_git.ensure_gitignore_entries(arch_root)
    ok_, reason = _same_repo_source(arch_root, kb)
    if not ok_:
        return False, reason
    # 基线提交：取 KB 基线版本 head（变更检测的 diff base），branch 用真实分支
    baseline_head = _kb_baseline_head(kb["id"], kb.get("currentVersionId"))
    real_branch = (arch_git.repo_status(arch_root) or {}).get("branch") or "main"
    data = {
        "name": proj.get("name") or arch_root.rstrip("/").rsplit("/", 1)[-1],
        "desc": proj.get("desc", ""), "mode": proj.get("mode", "existing"),
        "rootPath": arch_root,
        "kbProjectId": kb["id"],
        "kbRoot": kb.get("rootPath") or "", "kbSourceDir": kb.get("rootPath") or "",
        "baselineId": kb.get("currentVersionId"), "baselineCommit": baseline_head,
        "branch": real_branch,
        "gitLinked": True, "linkVerifiedAt": now, "active": True,
        "config": proj.get("config") or dict(_DEFAULT_CONFIG),
        "createdAt": proj.get("createdAt") or now, "updatedAt": now,
    }
    store.ProjectsStore.upsert(proj["id"], data)
    return True, store.ProjectsStore.get(proj["id"])
