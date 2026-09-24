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
    from ..ctx import data_dir
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
