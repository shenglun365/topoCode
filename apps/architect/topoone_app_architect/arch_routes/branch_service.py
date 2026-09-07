"""任务分支协议（S2）— 执行通道的 git 落地闭环。

契约（对齐 arch_git.py 头注）：
  1. dispatch 前：工程实现目录切任务分支 `arch/{exec_id}` @base_commit（脏区拒绝）；
  2. 执行中：coding agent 直接在工程目录编辑（分支已就位，零感知）；
  3. 树完成后：自动 commit + push 到镜像 bare 仓（{data_dir}/git/{project}.git，
     本地路径 push；S3 远端模式同构换远端）；
  4. 验收：diff 来源 = `git diff base_commit...HEAD`（工程目录），弃 worktree 脏 diff 依赖；
     分析副本 pull_task_branch 保留为远端/归档通道。

幂等性：land 以 exec.task_branch 已 push（分支 tip==镜像 tip）为幂等闸。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

MIRROR_REMOTE = "topocode"
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _data_dir() -> str:
    from .ctx import data_dir
    return data_dir()


def _git(args: list, cwd: str, timeout: int = 120) -> Optional[str]:
    try:
        p = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                           text=True, timeout=timeout)
        if p.returncode != 0:
            logger.debug("[branch] git %s → rc=%s %s", args[0], p.returncode,
                         p.stderr.strip()[:200])
            return None
        return p.stdout.strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[branch] git %s failed: %s", args[0], e)
        return None


def mirror_path(project_id: str) -> str:
    safe = _SAFE.sub("-", (project_id or "unknown"))[:80]
    return os.path.join(_data_dir(), "git", f"{safe}.git")


def ensure_mirror(project: dict, root: str) -> Optional[str]:
    """确保项目镜像 bare 仓存在 + 工程目录配置 topocode remote。返回镜像路径。"""
    pid = project.get("id") or "unknown"
    path = mirror_path(pid)
    if not os.path.isdir(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        p = subprocess.run(["git", "init", "--bare", path], capture_output=True, text=True)
        if p.returncode != 0:
            logger.warning("[branch] 镜像初始化失败 %s: %s", path, p.stderr[:200])
            return None
        # 允许 HTTP push（内置 git 托管 remote worker 用）+ 默认分支指向 main
        subprocess.run(["git", "config", "http.receivepack", "true"], cwd=path,
                       capture_output=True)
        subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=path,
                       capture_output=True)
        logger.info("[branch] 镜像 bare 仓创建: %s", path)
    if root and os.path.isdir(os.path.join(root, ".git")):
        existing = _git(["remote", "get-url", MIRROR_REMOTE], cwd=root)
        if existing is None:
            _git(["remote", "add", MIRROR_REMOTE, path], cwd=root)
    return path


def prepare_task_branch(root: str, task_branch: str, base_commit: str) -> dict:
    """dispatch 前切换任务分支。返回 {ok, reason, commit}。"""
    if not root or not os.path.isdir(os.path.join(root, ".git")):
        return {"ok": False, "reason": "工程目录不存在或非 git 仓库", "commit": ""}
    dirty = _git(["status", "--porcelain"], cwd=root)
    if dirty:
        return {"ok": False, "reason": "工程目录存在未提交改动，请先提交或清理", "commit": ""}
    head = _git(["rev-parse", "HEAD"], cwd=root) or ""
    if base_commit and head and head != base_commit:
        # 基线不一致：以当前 HEAD 为准重定基（branch_mode=manual 场景宽容）
        logger.warning("[branch] HEAD(%s) != base(%s)，按 HEAD 建分支",
                       head[:8], base_commit[:8])
    if _git(["checkout", "-B", task_branch, base_commit or "HEAD"], cwd=root) is None:
        return {"ok": False, "reason": f"切换任务分支失败: {task_branch}", "commit": ""}
    commit = _git(["rev-parse", "HEAD"], cwd=root) or ""
    logger.info("[branch] 任务分支就位 %s @%s (%s)", task_branch,
                (base_commit or "HEAD")[:8], root)
    return {"ok": True, "reason": "", "commit": commit}


def land_task_branch(project: dict, root: str, exec_id: str, task_branch: str,
                     title: str = "") -> dict:
    """树完成后：commit 工程目录变更 + push 任务分支到镜像。幂等。"""
    if not task_branch:
        return {"ok": False, "reason": "无任务分支", "commit": ""}
    if not os.path.isdir(os.path.join(root or "", ".git")):
        return {"ok": False, "reason": "工程目录不可用", "commit": ""}
    path = ensure_mirror(project, root)
    if not path:
        return {"ok": False, "reason": "镜像仓不可用", "commit": ""}

    tip = _git(["rev-parse", "HEAD"], cwd=root) or ""
    dirty = _git(["status", "--porcelain"], cwd=root)
    if dirty:
        msg = f"arch({exec_id}): {title or 'coding agent 任务落地'}"[:100]
        _git(["add", "-A"], cwd=root)
        if _git(["commit", "-m", msg], cwd=root) is None:
            return {"ok": False, "reason": "git commit 失败", "commit": tip}
        tip = _git(["rev-parse", "HEAD"], cwd=root) or tip

    # 幂等：镜像已含该 tip 则跳过 push
    have = _git(["rev-parse", "--verify", "--quiet",
                 f"refs/heads/{task_branch}"], cwd=path)
    if have == tip:
        return {"ok": True, "reason": "already-landed", "commit": tip}
    # 任务分支单执行独占：重跑/rebase 后强制覆盖镜像（归档语义，取最新一次）
    branch = _git(["branch", "--show-current"], cwd=root) or task_branch
    r = _git(["push", "--force", MIRROR_REMOTE, f"{branch}:refs/heads/{task_branch}"],
             cwd=root, timeout=300)
    if r is None and _git(["push", "--force", MIRROR_REMOTE, task_branch], cwd=root) is None:
        return {"ok": False, "reason": f"push 镜像失败({task_branch})", "commit": tip}
    logger.info("[branch] 任务分支落地 %s → %s (%s)", task_branch, tip[:8], path)
    return {"ok": True, "reason": "", "commit": tip}


def branch_diff(root: str, base_commit: str, head: str = "HEAD") -> list[dict]:
    """base...head 变更清单（验收 diff 源）。"""
    if not base_commit or not os.path.isdir(os.path.join(root or "", ".git")):
        return []
    raw = _git(["diff", "--name-status", f"{base_commit}...{head}"], cwd=root) or ""
    out = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append({"status": parts[0][:1], "path": parts[-1]})
    return out


# ── 树完成监视（后台线程，architect 侧） ──

def watch_and_land(task: dict, project: dict, root: str, tree_id: str,
                   poll_s: float = 6.0, max_wait_s: float = 4 * 3600) -> None:
    """轮询 runner 树状态至终态：done → 落地任务分支；failed/cancelled → 跳过。

    由 /exec/{id}/run 启动（daemon 线程）；幂等由 land_task_branch 保证。
    """
    import threading
    import time as _time
    from .runner_gateway import get_runner

    def _run() -> None:
        runner = get_runner()
        deadline = _time.time() + max_wait_s
        last_status = ""
        while _time.time() < deadline:
            _time.sleep(poll_s)
            try:
                state = runner.get_tree(tree_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("[branch] 轮询 runner 失败: %s", e)
                continue
            last_status = (state or {}).get("status") or ""
            if last_status in ("done", "failed", "cancelled"):
                break
        if last_status != "done":
            logger.info("[branch] 树 %s 终态=%s，跳过落地", tree_id, last_status or "unknown")
            return
        try:
            r = land_task_branch(project, root, task.get("id") or "",
                                 task.get("taskBranch") or "",
                                 (task.get("title") or ""))
            from .common import _ts
            from . import store
            store.ExecutionTasksStore.update(task.get("id") or "", {
                "branchCommit": r.get("commit") or "",
                "branchLandedAt": _ts() if r.get("ok") else "",
                "updatedAt": _ts(),
            })
            logger.info("[branch] exec=%s 落地结果: %s", task.get("id"), r)
            if r.get("ok"):
                # P4 开发简报: 落地 → 资产版本锚点 + 执行回执单元
                try:
                    from . import context_registry, dev_digest
                    dev_digest.record_land_snapshot(task, r.get("commit") or "")
                    context_registry.write_exec_report(task.get("id") or "", "done")
                except Exception as e:  # noqa: BLE001
                    logger.warning("[branch] 落地后处理失败: %s", e)
        except Exception as e:  # noqa: BLE001
            logger.warning("[branch] 落地异常 exec=%s: %s", task.get("id"), e)

    threading.Thread(target=_run, daemon=True,
                     name=f"branch-land-{task.get('id')}").start()
