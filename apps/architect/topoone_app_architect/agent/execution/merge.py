"""合并域(本地 PR 语义, 环节十五) — M2 自 exec_bridge 机械迁出(行为等价)。

职责: 合并入口检视(precheck)/链式基点/未合并预警/合并执行/合并后清理。
接缝约定: runner 访问经 exec_bridge 调用期解析(_eb._client)——保持
monkeypatch.setattr(eb, "_runner") 测试打桩不变(导入期绑定会失效)。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _TASK_TERMINAL_ref():
    from ...agent.execution.exec_bridge import _TASK_TERMINAL
    return _TASK_TERMINAL


def merge_precheck(task_id: str) -> Dict[str, Any]:
    """合并入口检查(环节十五): 任务分支合并前的 git 事实检视。

    - 主目录 HEAD vs 任务基点(baseCommit): 基点以来主目录有推进 → 需先
      rebase/冲突检测(这是"逐步 hash 校验"该守的位置——git 三方合并本身
      即 hash 校验, 我们守合并入口);
    - 任务分支推进清单: 验收合并内容。
    """
    from ... import store
    task = store.TasksStore.get(task_id)
    if not task:
        return {"ok": False, "error": "task-not-found", "code": 404}
    if (task.get("status") or "") not in _TASK_TERMINAL_ref():
        return {"ok": False, "error": "任务非终态——先完成/停止再合并", "code": 400}
    # cv-201: 就地任务变更已直接生效于项目目录, 无分支可合
    if str(task.get("workspace") or "") == "inplace":
        return {"ok": True, "checkable": False, "fastForward": None,
                "mainNewCommits": [], "branchCommits": [],
                "advice": "融合模式任务——变更已直接生效于项目目录, 无需合并。"}
    base = str(task.get("baseCommit") or "")
    branch = str(task.get("branch") or "")
    conv = store.ConversationsStore.get(task.get("conversationId") or "") or {}
    from ...arch_routes.execution import conv_root_project
    root, _project = conv_root_project(conv)
    if not root or not os.path.isdir(root):
        return {"ok": False, "error": "no-project-root", "code": 400}
    from ..governance.boundary import _git_run
    branch_commits: List[str] = []
    if branch:
        r = _git_run(["log", "--oneline", f"{base}..{branch}", "-n", "20"],
                     root, check=False)
        if r.returncode == 0:
            branch_commits = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if not base:
        return {"ok": True, "checkable": False, "fastForward": None,
                "mainNewCommits": [], "branchCommits": branch_commits,
                "advice": "任务无基点记录(旧任务)——请手工 git log 检视后合并。"}
    r = _git_run(["log", "--oneline", f"{base}..HEAD", "-n", "20"],
                 root, check=False)
    if r.returncode != 0:
        return {"ok": False,
                "error": "基点不在当前仓库历史中(主分支可能已重写)", "code": 400}
    main_new = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if main_new:
        advice = (f"主目录自任务基点已有 {len(main_new)} 个新提交"
                  f"({'; '.join(main_new[:3])})——合并前请先在任务分支上"
                  " rebase 主目录并解决冲突, 或用合并工具逐文件检视。")
    else:
        advice = "主目录自任务基点无新提交——可直接合并(无冲突风险)。"
    return {"ok": True, "checkable": True, "fastForward": not main_new,
            "mainNewCommits": main_new, "branchCommits": branch_commits,
            "advice": advice}


def _chain_base(conv_id: str, exclude_task_id: str, root: str) -> str:
    """链式基点(本地 PR 语义, 环节十五): 同会话最近一个**未合并**终态任务
    分支的 head 作为新任务基点——worktree 物理包含前序代码(文字+代码一致);
    前序分支已合并进主(merge-base --is-ancestor) → 回落 HEAD(返回 "")。

    只在同会话链内; 跨会话靠卡片未合并预警暴露。
    """
    from ... import store
    try:
        from ..governance.boundary import _git_run
        for t in sorted(store.TasksStore.of_conv(conv_id),
                        key=lambda x: x.get("createdAt") or 0, reverse=True):
            if t.get("id") == exclude_task_id:
                continue
            if (t.get("status") or "") not in _TASK_TERMINAL_ref():
                continue
            branch = str(t.get("branch") or "")
            if not branch.startswith("task/"):
                continue
            if _git_run(["merge-base", "--is-ancestor", branch, "HEAD"],
                        root, check=False).returncode == 0:
                continue                      # 已合并 → 基线已含, 跳过
            r = _git_run(["rev-parse", branch], root, check=False)
            if r.returncode == 0:
                return r.stdout.strip()
    except Exception as e:  # noqa: BLE001 — 基点解析失败回落 HEAD
        logger.debug("[exec-bridge] chain_base: %s", e)
    return ""


def _unmerged_branch_notes(conv_id: str, root: str, limit: int = 3) -> str:
    """同项目未合并终态分支清单 → 任务卡预警文案(基线不含其改动)。"""
    from ... import store
    try:
        from ..governance.boundary import _git_run
        items = []
        for t in sorted(store.TasksStore.of_conv(conv_id),
                        key=lambda x: x.get("createdAt") or 0, reverse=True):
            if (t.get("status") or "") not in _TASK_TERMINAL_ref():
                continue
            branch = str(t.get("branch") or "")
            if not branch.startswith("task/"):
                continue
            if _git_run(["merge-base", "--is-ancestor", branch, "HEAD"],
                        root, check=False).returncode == 0:
                continue
            r = _git_run(["rev-parse", branch], root, check=False)
            if r.returncode != 0:
                continue
            items.append(f"`{branch}`({t.get('title')})")
            if len(items) >= limit:
                break
        if not items:
            return ""
        return ("\n\n> ⚠️ 存在未合并分支: " + ", ".join(items)
                + "——当前任务基线**不含**其改动; 如需基于其成果请先合并"
                  "(完成卡上有「合并检查/确认合并」)。")
    except Exception as e:  # noqa: BLE001
        logger.debug("[exec-bridge] unmerged notes: %s", e)
        return ""


def _post_merge_cleanup(task: dict, root: str) -> str:
    """合并后清理(本地 PR 语义·生命周期闭环): merged 终态意味着内容已进
    主目录——分支/worktree 是过程产物, 随合并同意一并清理(GitHub
    auto-delete-head-branch 同款)。最佳努力: 清理失败不影响合并结果。

    - failed 分支不在此列(续跑锚点); branch -d 仅已合并可删(git 层保险)
    """
    from ..governance.boundary import _git_run
    notes = []
    wt = str(task.get("worktree") or "")
    if wt and os.path.isdir(wt):
        r = _git_run(["worktree", "remove", "--force", wt], root, check=False)
        notes.append("worktree 已移除" if r.returncode == 0
                     else f"worktree 移除失败({(r.stderr or '')[:80]})")
        if os.path.isdir(wt):   # 注册已清但目录残留(构建产物) → 兜底删目录
            import shutil as _shutil
            _shutil.rmtree(wt, ignore_errors=True)
            notes.append("worktree 目录已兜底删除")
    branch = str(task.get("branch") or "")
    if branch:
        r = _git_run(["branch", "-d", branch], root, check=False)
        notes.append("分支已删除" if r.returncode == 0
                     else f"分支删除失败({(r.stderr or '')[:80]})")
    job_id = str(task.get("runnerJobId") or "")
    if job_id:
        try:
            # 调用期解析: 保持 eb._runner/eb._client 测试打桩接缝
            from ...agent.execution import exec_bridge as _eb
            from ..governance.timeouts import get as _timeout_of
            _eb._client().finish(job_id, keep_worktree=False,
                                 timeout=_timeout_of("runner_finish"))
            notes.append("runner 资源已释放")
        except Exception:  # noqa: BLE001
            notes.append("runner 资源释放失败(可稍后任务清理)")
    return "；".join(notes)


def merge_branch(task_id: str, mode: str = "ff") -> Dict[str, Any]:
    """确认合并(本地 PR 语义, 环节十五): 门禁(precheck)通过后执行合并。

    mode: ff = 仅快进(主目录无推进时); no-ff = 强制合并提交(冲突则中止回显)。
    成功 → 任务行记 merged_at/merged_head(merged 终态, 分支内容已进主)。
    同会话任务状态迁移锁内执行——防双击双 merge(precheck/git 慢路径窗口)。"""
    from ... import store
    task = store.TasksStore.get(task_id)
    if not task:
        return {"ok": False, "error": "task-not-found", "code": 404}
    from .dispatch import _conv_task_lock
    with _conv_task_lock(task.get("conversationId") or ""):
        return _merge_branch_locked(task_id, mode)


def _merge_branch_locked(task_id: str, mode: str) -> Dict[str, Any]:
    """merge 主体(须持 _conv_task_lock 调用)——锁内重读任务行裁决状态门禁。"""
    from ... import store
    task = store.TasksStore.get(task_id)
    if not task:
        return {"ok": False, "error": "task-not-found", "code": 404}
    if (task.get("status") or "") != "done":
        return {"ok": False, "error": "仅 done 任务可合并", "code": 400}
    if str(task.get("mergedAt") or "") not in ("", "0") or int(task.get("mergedAt") or 0):
        return {"ok": False, "error": "任务已合并(勿重复)", "code": 400}
    pre = merge_precheck(task_id)
    if not pre.get("ok"):
        return pre
    if not pre.get("checkable"):
        # 就地任务: 变更已生效——直接记 merged 终态(无 git 动作)
        if "融合模式" in str(pre.get("advice") or ""):
            import time as _t
            return store.TasksStore.update(task_id, {
                "mergedAt": int(_t.time() * 1000),
                "mergedHead": str(task.get("runnerJobId") or "inplace")}) or {
                "ok": True, "merged": True, "inplace": True}
        return {"ok": False, "error": str(pre.get("advice")), "code": 400}
    conv = store.ConversationsStore.get(task.get("conversationId") or "") or {}
    from ...arch_routes.execution import conv_root_project
    root, _project = conv_root_project(conv)
    from ..governance.boundary import _git_run
    if _git_run(["status", "--porcelain"], root, check=False).stdout.strip():
        return {"ok": False,
                "error": "主目录有未提交改动——先 commit 或 stash 再合并", "code": 400}
    branch = str(task.get("branch") or "")
    if pre.get("fastForward"):
        r = _git_run(["merge", "--ff-only", branch], root, check=False)
    else:
        if mode != "no-ff":
            return {"ok": False,
                    "error": (str(pre.get("advice"))
                              + " (确认主目录处理完毕后可用 mode=no-ff 强制合并)"),
                    "code": 400}
        r = _git_run(["merge", "--no-ff", "-m",
                      f"merge {branch} (task {task_id}: {task.get('title')})",
                      branch], root, check=False)
    if r.returncode != 0:
        st = _git_run(["status", "--porcelain"], root, check=False)
        conflicts = [ln[3:].strip() for ln in st.stdout.splitlines()
                     if ln.startswith(("UU", "AA", "DD"))]
        if conflicts:
            _git_run(["merge", "--abort"], root, check=False)
            return {"ok": False,
                    "error": (f"合并冲突: {', '.join(conflicts[:5])}——已中止"
                              "(主目录未动), 请解决冲突后重试"), "code": 409}
        return {"ok": False,
                "error": f"合并失败: {(r.stderr or r.stdout or '')[:200]}",
                "code": 400}
    head = _git_run(["rev-parse", "HEAD"], root).stdout.strip()
    from ...common import _ts
    store.TasksStore.update(task_id, {"mergedAt": _ts(), "mergedHead": head})
    # 生命周期闭环(用户裁决): 合并同意 = 过程产物清理同意(worktree/分支)
    cleanup_note = _post_merge_cleanup(task, root)
    return {"ok": True, "mergedHead": head, "mode": mode,
            "advice": (f"已合并 {branch} → 主目录({head[:12]})。"
                       + (f"清理: {cleanup_note}。" if cleanup_note else ""))}
