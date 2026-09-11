"""执行上下文辅助(会话驱动执行)。

旧机制已退役——方案(plans)状态机、执行任务(exec tasks)状态机、并行资产锁、
SE 任务树派发(run/rejudge/verify/disposition/accept)、broker 指派(assign)等
「偏严格的软件工程流程」全部拆除；需求→定稿→待执行会话→执行会话(coding
agent 对话)的流转由会话自身承载(统一时间线)。

本模块仅保留会话/需求 → 工程 root/project/git 基线 的解析辅助。
"""
import logging
import os
from typing import Optional

from . import store

logger = logging.getLogger(__name__)


def _real_base_commit(root: Optional[str] = None) -> str:
    """工程目录真实 git HEAD(基线提交)；非 git/无 HEAD → 空串(调用方兜底)。"""
    if not root:
        return ""
    try:
        from . import arch_git
        return (arch_git.head_commit(root) or "").strip()
    except Exception:
        return ""


def _resolve_root_project(reqs, body):
    """解析工程 root(源码根)/project(项目 id)。

    优先 body（前端显式传入）；缺省经请求级项目上下文 + arch_projects 解析;
    再由需求行projectId 反解。
    """
    body = body or {}
    root = body.get("root")
    project = body.get("project")
    if not project:
        try:
            from . import ctx
            project = ctx.get_project()
        except Exception:
            project = None
    if not root and project:
        try:
            proj = store.ProjectsStore.get(project) or {}
            root = proj.get("rootPath") or proj.get("kbRoot") or ""
        except Exception:
            root = ""
    if not project:
        for r in reqs or []:
            if r.get("projectId"):
                project = r["projectId"]
                try:
                    proj = store.ProjectsStore.get(project) or {}
                    root = root or proj.get("rootPath") or proj.get("kbRoot") or ""
                except Exception:
                    pass
                break
    return root, project


def conv_root_project(conv: dict) -> tuple:
    """会话 → (root, project): 会话绑定项目/需求反解工程根, 供 coding agent 问答。"""
    reqs = []
    rid = (conv or {}).get("reqId") or ""
    if rid:
        r = store.RequirementsStore.get(rid)
        if r:
            reqs = [r]
    root, project = _resolve_root_project(reqs, {"project": (conv or {}).get("projectId") or ""})
    return root or "", project or ""
