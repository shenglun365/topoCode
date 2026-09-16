"""边界与互斥引擎(治理层) — 交托边界解析 + 全局运行作业互斥校验。

P2 自 exec_bridge.py 迁入:
  - resolve_boundary_files: 规约边界 → 文件/目录前缀集合(组件经 KB 解析为文件集)
  - check_mutex:            与全局运行中作业的文件边界求交; readOnly 豁免
  - files_intersect:        文件/目录前缀集合求交(目录前缀覆盖其下所有文件)

设计对齐(裁决#1/#2/#9): 声明级互斥——启动前边界求交拒绝; 越界写靠验收简报
事后检测。runner 不可达时放行(无法校验, 风险自担)。
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import List, Optional, Tuple

logger = logging.getLogger("arch.governance.boundary")


def _git_run(args: List[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=check)


def resolve_boundary_files(rid: str, root: str, project: Optional[str]) -> List[str]:
    """规约边界 → 文件/目录前缀集合(文件级统一口径; 组件经 KB 解析为文件集)。"""
    from ...arch_routes.req_agent import parse_scope_files
    from ...arch_routes import store
    snap = (store.RequirementsStore.spec_active(rid or "") or {}).get("snapshot") or {}
    scope = snap.get("allowedScope") or []
    files = set(parse_scope_files(scope))
    comps = [str(x).strip()[5:] for x in scope
             if str(x or "").strip().startswith("comp:")]
    if comps:
        try:
            from ...arch_routes.sem.engine import _component_file_map
            cfm = _component_file_map(root or "", project)
            for cid in comps:
                for f in cfm.get(cid) or []:
                    files.add(str(f).lstrip("./").rstrip("/"))
        except Exception as e:  # noqa: BLE001
            logger.debug("[boundary] 组件边界解析失败: %s", e)
    return sorted(files)


def files_intersect(a: List[str], b: List[str]) -> List[str]:
    """文件/目录前缀集合求交(目录前缀视为覆盖其下所有文件)。"""
    out = []
    for x in a:
        for y in list(b):
            if x == y or x.startswith(y + "/") or y.startswith(x + "/"):
                if x not in out:
                    out.append(x)
                break
    return out


def check_mutex(conv: dict, root: str, boundary_files: List[str],
                runner=None) -> Optional[str]:
    """交托互斥校验: 与全局运行中作业的文件边界求交; readOnly 豁免。

    runner: callable(path, payload=None, timeout=...) → dict|None(exec_bridge._runner 注入;
    测试经 exec_bridge._runner monkeypatch 生效)。

    返回 None=通过; 冲突时返回说明文本。
    声明级互斥(越界写靠验收简报事后检测, 裁决#2)。
    """
    running = runner("/api/implement/running", timeout=8.0) if runner else None
    if not running or not running.get("ok"):
        return None           # runner 不可达 → 无法校验(不阻塞, 风险自担)
    for j in running.get("jobs") or []:
        jb = j.get("boundaries") or {}
        if jb.get("readOnly"):
            continue
        if (j.get("root") or "") != (root or ""):
            continue           # 跨项目天然隔离
        theirs = set(str(x).lstrip("./").rstrip("/") for x in (jb.get("files") or []))
        clash = files_intersect(boundary_files, theirs)
        if clash:
            return (f"操作边界冲突：与运行中作业 `{j.get('jobId')}`(分支 `{j.get('branch')}`)"
                    f" 的范围重叠于 {', '.join(clash[:5])}。"
                    "请等待其完成/停止，或修订规约边界后重试。")
    return None


# ── 文件状态助手单源(环节十三) — git 事实, 无解析/无 TTL ──────────────

def list_repo_files(root: str, limit: int = 600) -> List[str]:
    """仓库文件清单(跟踪+未跟踪, 排除 ignored; 截断 limit)——范围探针 tree 源。"""
    if not root or not os.path.isdir(root):
        return []
    try:
        r = _git_run(["ls-files", "-co", "--exclude-standard"], root)
        files = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
        return files[:limit]
    except Exception as e:  # noqa: BLE001
        logger.debug("[boundary] list_repo_files: %s", e)
        return []


def files_exist(root: str, files: List[str]) -> Tuple[List[str], List[str]]:
    """边界文件存在性: → (existing, missing)。目录前缀按前缀匹配任一仓库文件。"""
    if not files:
        return [], []
    repo = set(list_repo_files(root, limit=100000))
    existing, missing = [], []
    for f in files:
        f = str(f).lstrip("./").rstrip("/")
        if not f:
            continue
        if f in repo or any(x.startswith(f + "/") for x in repo):
            existing.append(f)
        else:
            missing.append(f)
    return existing, missing


def changed_since(root: str, base_commit: str, files: List[str]) -> List[str]:
    """基点以来发生变化的文件(git diff --name-only <base> -- <files>)。

    交接过期判定的可操作定义: 边界文件在主分支有推进 = 需求引用的文件状态
    已漂移。base_commit 无效/仓库不可用 → [](不阻塞, 交给合并入口兜底)。"""
    if not base_commit or not files or not root or not os.path.isdir(root):
        return []
    try:
        r = _git_run(["diff", "--name-only", base_commit, "--", *files], root,
                     check=False)
        return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    except Exception as e:  # noqa: BLE001
        logger.debug("[boundary] changed_since: %s", e)
        return []
