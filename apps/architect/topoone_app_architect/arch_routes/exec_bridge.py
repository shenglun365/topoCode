"""执行会话桥接泵(exec_bridge)——architect 执行会话 ↔ runner 实施作业的双向缓冲。

职责(准实时, 轮询式解耦, 不要求实时流)：
- 下行: 轮询 runner /api/implement/{id}?since=seq → 事件批量落为会话消息
  (input_required/done 等关键事件即时可见)
- 上行: 会话出现新用户消息且作业 waiting_input → POST /input 转发作业
- 生命周期: 泵为每会话单 asyncio 任务; architect 重启后按会话下一条消息懒重挂
  (作业元数据持久化在 conv.meta.execJob)

不阻塞: 泵内一切异常只记日志/落错误消息, 不抛出。
"""
import asyncio
import json
import logging
import os
import time
import urllib.request
from typing import Any, Dict, Optional

from . import store

logger = logging.getLogger(__name__)

RUNNER_BASE = os.environ.get("RUNNER_BASE_URL", "http://127.0.0.1:3458").rstrip("/")
POLL_INTERVAL = 2.5          # 事件轮询(准实时)
CONV_POLL_INTERVAL = 3.0     # 上行用户消息轮询
_MAX_CONSECUTIVE_ERR = 5

_JOBS: Dict[str, Dict[str, Any]] = {}   # conv_id → {jobId, branch, worktree, task, lastSeq, lastUserTs, stopped}


def _runner(path: str, payload: Optional[dict] = None, timeout: float = 12.0) -> Optional[dict]:
    try:
        if payload is None:
            req = urllib.request.Request(f"{RUNNER_BASE}{path}")
        else:
            req = urllib.request.Request(
                f"{RUNNER_BASE}{path}", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001
        logger.debug("[exec-bridge] runner %s failed: %s", path, e)
        return None


def _ts() -> int:
    return int(time.time() * 1000)


def _append(conv_id: str, role: str, content: str, project_id: str = "") -> None:
    store.ConversationsStore.append_message({
        "id": store.next_id("m"), "conversationId": conv_id, "role": role,
        "time": _ts(), "content": content, "projectId": project_id,
    })
    try:
        store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
    except Exception:  # noqa: BLE001
        pass


def job_info(conv: dict) -> Optional[Dict[str, Any]]:
    """会话绑定的实施作业元数据(conv.meta.execJob)。"""
    try:
        meta = json.loads((conv or {}).get("meta") or "{}")
        return meta.get("execJob") or None
    except Exception:  # noqa: BLE001
        return None


def _save_job_meta(conv_id: str, info: Dict[str, Any]) -> None:
    try:
        conv = store.ConversationsStore.get(conv_id) or {}
        meta = {}
        try:
            meta = json.loads(conv.get("meta") or "{}")
        except Exception:  # noqa: BLE001
            pass
        meta["execJob"] = info
        store.ConversationsStore.update(conv_id, {"meta": json.dumps(meta, ensure_ascii=False)})
    except Exception as e:  # noqa: BLE001
        logger.warning("[exec-bridge] save meta failed: %s", e)


def is_running(conv_id: str) -> bool:
    st = _JOBS.get(conv_id)
    return bool(st and not st["stopped"] and not st["task"].done())


def start_implement(conv: dict, instruction: str, executor_hint: Optional[dict] = None,
                    branch_name: str = "") -> Dict[str, Any]:
    """触发实施: 组装 instruction(调用方已备) → runner 建作业 → 启动泵 → 返回 ack 文案。"""
    from .execution import conv_root_project
    conv_id = conv["id"]
    if is_running(conv_id):
        return "当前会话已有实施作业在运行，请先等待完成或发送澄清消息与执行工程师交互。"
    root, project = conv_root_project(conv)
    if not root:
        return "无法解析项目根(会话未绑定项目/需求)，无法启动实施。"
    rid = (conv.get("reqId") or "")
    branch = (branch_name or "").strip() or f"exec/{(rid or conv_id).replace('RQ-', 'rq').lower()}-{_ts()%100000}"
    payload = {"root": root, "instruction": instruction, "branchName": branch}
    # 执行器提示(模型/端口等, 来自角色绑定执行器配置)
    for k_src, k_dst in (("model", "model"), ("basePort", "basePort"),
                         ("autoStart", "autoStart"), ("baseUrl", "baseUrl")):
        if executor_hint and executor_hint.get(k_src) not in (None, ""):
            payload[k_dst] = executor_hint[k_src]
    res = _runner("/api/implement", payload, timeout=20.0)
    if not res or not res.get("ok"):
        err = (res or {}).get("error") or "runner 服务不可达(:3458)"
        return (f"❌ 实施作业启动失败：{err}\n"
                "请检查 runner 服务与 opencode 执行器(系统管理→执行器探活)后重试「执行方案」。")
    info = {"jobId": res["jobId"], "branch": res.get("branch") or branch,
            "worktree": res.get("worktree") or "", "lastSeq": 0, "lastUserTs": _ts()}
    _save_job_meta(conv_id, info)
    _start_pump(conv_id, info)
    return (f"🚀 实施作业已启动\n"
            f"- 作业: `{info['jobId']}`　分支: `{info['branch']}`\n"
            f"- 交付: 开发 + 单元测试 + 整体编译验收\n"
            f"- 执行工程师需要确认/澄清时会直接在本会话提问，回复即可送达；"
            f"随时可发送补充说明。发送「停止执行」可中止。")


def resume_if_job(conv_id: str, project_id: str = "") -> None:
    """会话有作业但泵不在跑(architect 重启/轮次结束) → 懒重挂。"""
    if is_running(conv_id):
        return
    conv = store.ConversationsStore.get(conv_id)
    info = job_info(conv or {})
    if not info:
        return
    job = _runner(f"/api/implement/{info['jobId']}?since=0", timeout=6.0)
    if not job or not job.get("ok"):
        return
    if job.get("status") in ("done", "failed", "stopped"):
        return
    info.setdefault("lastSeq", 0)
    info.setdefault("lastUserTs", _ts())
    _start_pump(conv_id, info, project_id=project_id)


def stop(conv_id: str, reason: str = "") -> str:
    st = _JOBS.get(conv_id)
    if not st:
        return "当前会话没有运行中的实施作业。"
    st["stopped"] = True
    _runner(f"/api/implement/{st['jobId']}/finish", payload={"keepWorktree": True}, timeout=30.0)
    return (f"🛑 实施作业已停止。分支 `{st['branch']}` 与工作区已保留，"
            "可随时发送「执行方案」继续。")


def _start_pump(conv_id: str, info: Dict[str, Any], project_id: str = "") -> None:
    old = _JOBS.get(conv_id)
    if old and not old["task"].done():
        return
    project_id = project_id or (store.ConversationsStore.get(conv_id) or {}).get("projectId") or ""
    st = {**info, "task": None, "stopped": False, "errs": 0, "projectId": project_id}
    st["task"] = asyncio.create_task(_pump(conv_id, st))
    _JOBS[conv_id] = st


async def _pump(conv_id: str, st: Dict[str, Any]) -> None:
    """下行事件→消息；waiting_input 时轮询上行用户消息→作业。"""
    logger.info("[exec-bridge] pump start conv=%s job=%s", conv_id, st["jobId"])
    last_agent_ts = _ts()
    try:
        while not st["stopped"]:
            await asyncio.sleep(POLL_INTERVAL)
            snap = await asyncio.to_thread(
                _runner, f"/api/implement/{st['jobId']}?since={st['lastSeq']}", None, 12.0)
            if not snap or not snap.get("ok"):
                st["errs"] += 1
                if st["errs"] >= _MAX_CONSECUTIVE_ERR:
                    _append(conv_id, "assistant",
                            "⚠️ 与执行作业失去联系(runner 不可达)。作业分支已保留，"
                            "可发送「执行方案」重新对接或检查 runner 服务。",
                            st.get("projectId", ""))
                    return
                continue
            st["errs"] = 0
            for ev in snap.get("events") or []:
                st["lastSeq"] = max(st["lastSeq"], ev.get("seq", 0))
                kind = ev.get("kind") or ""
                if kind == "user_input":
                    continue  # 用户自己的输入不回显(消息已在会话里)
                if kind == "session_ready":
                    continue
                text = (ev.get("text") or "").strip()
                if kind == "input_required":
                    clean = text.replace("[[NEED_INPUT]]", "").strip() or "(执行工程师等待你的输入)"
                    _append(conv_id, "assistant",
                            f"⏸ **执行工程师需要你的输入**\n\n{clean}",
                            st.get("projectId", ""))
                    last_agent_ts = _ts()
                elif kind == "done":
                    clean = text.replace("[[IMPLEMENT_DONE]]", "").strip()
                    changed = ev.get("changedFiles") or []
                    files = ("\n".join(f"- `{f}`" for f in changed[:20])
                             if changed else "- (无变更文件)")
                    _append(conv_id, "assistant",
                            f"✅ **实施完成**（分支 `{st['branch']}`，工作区 `{st['worktree']}`）\n\n"
                            f"{clean}\n\n**变更文件**：\n{files}\n\n"
                            "请验收：可发送「查看差异」获取完整 diff；确认无误后归档本会话即完成。",
                            st.get("projectId", ""))
                    last_agent_ts = _ts()
                elif kind == "failed":
                    _append(conv_id, "assistant",
                            f"❌ 执行作业失败：{text}\n分支已保留，可排查后重新「执行方案」。",
                            st.get("projectId", ""))
                elif kind in ("aborted", "finished"):
                    _append(conv_id, "assistant", f"ℹ️ {text}", st.get("projectId", ""))
                else:
                    if text:
                        _append(conv_id, "assistant", text, st.get("projectId", ""))
                        last_agent_ts = _ts()
            status = snap.get("status") or ""
            if status in ("done", "failed", "stopped"):
                return
            # 上行: waiting_input 时把会话新用户消息转发给作业
            if status == "waiting_input":
                await asyncio.sleep(CONV_POLL_INTERVAL - POLL_INTERVAL)
                msgs = store.ConversationsStore.messages(conv_id, limit=10)
                for m in msgs:
                    if (m.get("role") != "user"
                            or (m.get("time") or 0) <= st["lastUserTs"]
                            or (m.get("time") or 0) <= last_agent_ts):
                        continue
                    content = (m.get("content") or "").strip()
                    if not content or content.startswith(("停止执行", "查看差异")):
                        st["lastUserTs"] = m.get("time") or _ts()
                        continue
                    st["lastUserTs"] = m.get("time") or _ts()
                    r = await asyncio.to_thread(
                        _runner, f"/api/implement/{st['jobId']}/input",
                        {"text": content[:8000]}, 15.0)
                    if r and r.get("ok"):
                        _append(conv_id, "assistant",
                                "➡️ 已转达执行工程师。", st.get("projectId", ""))
                    break
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("[exec-bridge] pump crashed conv=%s: %s", conv_id, e)
