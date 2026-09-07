"""RemoteAgentExecutor — 远端三方 agent 会话模式（S3）。

模型：远端机器常驻其自己的 coding agent server（现支持 opencode serve 会话 API），
工作副本 clone 自共享 git 仓库（内置托管或外部远端）。architect 主 Agent：

  1. dispatch 前：任务分支 push 到共享远端（worker 可 fetch）；
  2. 远端会话执行：prompt = 编译后的任务规格 + 分支操作指令
     （fetch/checkout 任务分支 → 编码 → commit + push）；
  3. 执行后：从共享远端 fetch 任务分支回工程目录（ff/reset 到远端 tip），
     变更经分支 diff 进入验收（branch_service 落地镜像归档）。

远端 worker 前置（见 docs/architect/remote-agent.md）：
  - clone 共享仓库（凭据含 token：http://<token>@<host>:3470/git/<project>.git）
  - 在 clone 目录启动 `opencode serve`，保证 architect 可达 agent_url。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from topocode_agent.subagent.protocol import SubAgentResult

from .opencode import OpenCodeSessionExecutor, ServeProc

logger = logging.getLogger(__name__)

_BRANCH_INSTRUCTIONS = """

## 分支协作规约（必须遵守）
1. 执行前：`git fetch origin --prune`，然后
   `git checkout -B {branch} origin/{branch}`（远端无此分支则从当前默认分支新建）。
2. 只在任务清单列出的文件范围内修改（上下文另有说明除外）。
3. 完成后必须：`git add -A && git commit -m "task({task_id}): {title}"`，
   再 `git push origin {branch}`。未 push 视为未完成。
"""


class RemoteAgentExecutor(OpenCodeSessionExecutor):
    """远端 opencode serve 会话 + 共享 git 仓库同步（mode=remote）。"""

    mode = "remote"

    def __init__(self, id: str = "remote", agent_url: str = "", api_key: str = "",
                 git_remote: str = "auto", arch_url: str = "",
                 timeout: float = 3600.0, prompt_builder: Optional[object] = None,
                 permission: str = "auto", model: str = ""):
        super().__init__(id=id, base_url=agent_url, api_key=api_key,
                         timeout=timeout, prompt_builder=prompt_builder,
                         auto_start=False, permission=permission, model=model)
        self._agent_url = (agent_url or "").rstrip("/")
        self._git_remote = git_remote  # "auto" → 内置托管 {arch_url}/git/{project}.git
        self._arch_url = (arch_url or os.environ.get(
            "ARCH_BASE_URL", "http://127.0.0.1:3470")).rstrip("/")

    # 远端 serve 固定 URL：绕过本地 serve 管理器
    async def _ensure_remote(self, root: str) -> ServeProc:
        return ServeProc(root, self._agent_url, 0)

    def _git(self, args, cwd):
        import subprocess
        p = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True,
                           timeout=300)
        return p.returncode == 0, (p.stdout + p.stderr).strip()

    def _remote_url(self, context: dict) -> str:
        if self._git_remote and self._git_remote != "auto":
            return self._git_remote
        project = context.get("project") or context.get("projectId") or "unknown"
        return f"{self._arch_url}/git/{project}.git"

    def _prompt(self, task, context: dict) -> str:
        base = super()._prompt(task, context)
        branch = context.get("branch") or ""
        if not branch:
            return base
        return base + _BRANCH_INSTRUCTIONS.format(
            branch=branch, task_id=task.id, title=(task.title or "")[:60])

    async def execute(self, task, context: dict) -> SubAgentResult:
        root = os.path.abspath(context.get("root") or context.get("projectRoot")
                               or os.environ.get("RUNNER_PROJECT_ROOT", "") or os.getcwd())
        branch = (context.get("branch") or "").strip()
        remote = self._remote_url(context)

        # 1) 任务分支推共享远端（worker 可见）——HEAD:branch 使本地分支未建时同样可推
        if branch:
            okc, out = await _to_thread(self._git,
                                        ["push", "--force", remote,
                                         f"HEAD:refs/heads/{branch}"], root)
            if not okc:
                logger.warning("[remote] 分支推送失败 %s → %s: %s", branch, remote, out[:200])
                return SubAgentResult(success=False,
                                      error=f"任务分支推送共享远端失败: {out[:200]}")

        # 2) 远端会话执行（父类会话流程，serve 固定远端 URL）
        self._mgr.ensure = self._ensure_remote  # type: ignore[method-assign]
        result = await super().execute(task, context)
        if not result.success:
            return result

        # 3) 结果拉回：fetch 共享远端任务分支 → ff/reset 工程目录
        if branch:
            okc, out = await _to_thread(self._git,
                                        ["fetch", remote,
                                         f"{branch}:refs/remotes/remote-agent/{branch}"],
                                        root)
            if okc:
                await _to_thread(self._git,
                                 ["checkout", "-B", branch,
                                  f"refs/remotes/remote-agent/{branch}"], root)
            else:
                logger.warning("[remote] 结果 fetch 失败 %s: %s", branch, out[:200])

        base_commit = (context.get("baseCommit") or "").strip()
        changed = []
        if base_commit:
            from ..gateway import _git_diff_names  # 轻量 diff（同 branch_diff 语义）
            changed = _git_diff_names(root, base_commit)
        result.changed_files = changed or result.changed_files
        result.metadata = {**(result.metadata or {}),
                           "remote": True, "sharedRemote": remote, "branch": branch}
        return result


async def _to_thread(fn, *args):
    import asyncio
    return await asyncio.to_thread(fn, *args)
