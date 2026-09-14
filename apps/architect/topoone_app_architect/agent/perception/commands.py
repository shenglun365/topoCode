"""会话指令直通(感知层)：/定稿 /执行 确定性执行，不经 LLM。

v2 流程(严格挡)：req.propose(draft) → /定稿(ready) → /执行(建任务卡) →
卡片确认 → coding subagent。历史教训(cv-152 实证)：指令落回 LLM 会引用
v1 旧文档(coding.task.execute 已无工具)而死胡同；prompt 曾宣称「系统直通」
但无实现——本模块使其成为事实。

- /定稿：复用 req.finalize 工具路径(结构门禁+幂等)，回执落 meta specReady；
- /执行：绑定 ready 规约 → exec_bridge.propose_task 建任务卡(pending_confirm)，
  用户点卡确认后 subagent 才启动(轻门禁保留)；
- /调整 需内容整理，保持经模型；/确认执行 /继续 /diff 已废弃(前端同步移除)。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

_COMMAND_RE = re.compile(r"^(?:@(?P<executor>\S+)\s+)?/(?P<cmd>定稿|执行)\s*$")
_CONFIRM_RE = re.compile(
    r"^(?:@(?P<executor>\S+)\s+)?(?:确认执行|确认任务|确认|同意|开始执行|开始吧|开始|ok|OK|好的?)[。.!！]?\s*$")


def match_command(question: str) -> Optional[Dict[str, str]]:
    """整条消息恰为指令(可带 @执行器 前缀)时返回 {cmd, executor}；其余 None。

    @cline /执行 → {"cmd": "执行", "executor": "cline"}(显式执行器直通建卡);
    /定稿 → {"cmd": "定稿", "executor": ""}。"""
    m = _COMMAND_RE.match((question or "").strip())
    if not m:
        return None
    return {"cmd": m.group("cmd"), "executor": (m.group("executor") or "").strip()}


def match_confirm(question: str) -> Optional[Dict[str, str]]:
    """文字确认(任务卡确认按钮的同义路径): 整条消息恰为确认语 → {executor}。

    cv-153 教训: 用户打「确认」被当普通消息进 LLM → 模型谎报已启动。"""
    m = _CONFIRM_RE.match((question or "").strip())
    if not m:
        return None
    return {"executor": (m.group("executor") or "").strip()}


def has_pending_task(conv_id: str) -> bool:
    from ...arch_routes import store
    return any((t.get("status") or "") == "pending_confirm"
               for t in store.TasksStore.of_conv(conv_id))


def run_confirm(conv: Dict[str, Any], executor_id: str = "") -> Dict[str, Any]:
    """直通文字确认: 恰有一张待确认任务卡 → confirm_task(@执行器 可换引擎)。

    无待确认卡返回 {noPending: True}(调用方回落普通对话, 不拦)。"""
    from ...arch_routes import exec_bridge, store
    pending = [t for t in store.TasksStore.of_conv(conv["id"])
               if (t.get("status") or "") == "pending_confirm"]
    if not pending:
        return {"ok": False, "noPending": True}
    if len(pending) > 1:
        names = "、".join(f"「{(t.get('title') or '')[:24]}」" for t in pending[:5])
        return {"ok": False, "receipt":
                f"有 {len(pending)} 张待确认任务卡（{names}）——请在具体卡片上点确认，"
                "或先取消多余任务。"}
    executor_id = (executor_id or "").strip()
    if executor_id:
        t2 = exec_bridge.task_set_executor(pending[0]["id"], executor_id)
        if not t2:
            return {"ok": False, "receipt":
                    f"执行器 `{executor_id}` 不可用（不在注册表或类型不支持）。"}
    res = exec_bridge.confirm_task(pending[0]["id"])
    if not res.get("ok"):
        return {"ok": False, "receipt": str(res.get("error") or "确认失败")}
    return {"ok": True, "task": res.get("task") or {}}


def run_finalize(conv: Dict[str, Any]) -> Dict[str, Any]:
    """直通 /定稿：req.finalize 同一路径(designMd 门禁/幂等)，notify=False
    由编排层统一落回执(meta specReady)，避免双回执。"""
    from ...arch_routes import req_agent
    return req_agent.tool_req_finalize((conv.get("reqId") or "").strip(), notify=False)


def run_execute(conv: Dict[str, Any], executor_id: str = "") -> Dict[str, Any]:
    """直通 /执行：绑定 ready 规约 → 服务端建任务卡(待用户卡片确认)。

    executor_id(@cline 前缀)显式指定执行器——查注册表, 查不到显式失败不降级。"""
    from ...arch_routes import exec_bridge, store
    executor_id = (executor_id or "").strip()
    hint = None
    if executor_id:
        hint = exec_bridge.executor_hint_by_id(executor_id, conv)
        if not hint:
            return {"ok": False, "receipt":
                    f"执行器 `{executor_id}` 不在注册表中——请检查「执行器配置」"
                    "(支持: " + ", ".join(_registered_ids()) + ")。"}
    req_id = (conv.get("reqId") or "").strip()
    if not req_id:
        return {"ok": False, "receipt":
                "当前会话未绑定需求：严格挡请先在对话中形成规约(req.propose)，"
                "快捷挡可直接描述任务让我建卡。"}
    row = store.RequirementsStore.get(req_id)
    if not row:
        return {"ok": False, "receipt": f"需求 {req_id} 不存在。"}
    active = store.RequirementsStore.spec_active(req_id) or {}
    snap = active.get("snapshot") or {}
    if (active.get("state") or "") != "confirmed":
        return {"ok": False, "receipt":
                f"规约 `{req_id}` 尚未定稿(draft)。先发送 `/定稿` 确认，再 `/执行` 建卡。"}
    title = (snap.get("title") or row.get("title") or "实施任务").strip()[:120]
    instruction = _instruction_from_snapshot(snap)
    if not instruction.strip():
        return {"ok": False, "receipt": "规约内容为空，无法建卡。请 `/调整` 完善后重试。"}
    task = exec_bridge.propose_task(conv, title, instruction, executor_hint=hint)
    if not task.get("id"):
        # 无可用执行器等建卡失败: 原文显式返回(不降级不吞错)
        return {"ok": False, "receipt": str(task.get("error") or "建卡失败")}
    return {"ok": True, "task": task}


def _registered_ids() -> list:
    try:
        from ...arch_routes.agent_executors import load_executors
        return [str(e.get("id") or "") for e in load_executors() if e.get("enabled", True)]
    except Exception:  # noqa: BLE001
        return []


def _instruction_from_snapshot(snap: Dict[str, Any]) -> str:
    """规约快照 → 任务卡 instruction(目标/方案/边界/验收，与 req.propose 分节对齐)。"""
    sections = []
    if str(snap.get("desc") or "").strip():
        sections.append(f"## 需求目标\n\n{snap['desc']}")
    if str(snap.get("designMd") or "").strip():
        sections.append(f"## 方案\n\n{snap['designMd']}")
    allowed = [str(x) for x in (snap.get("allowedScope") or []) if str(x).strip()]
    forbidden = [str(x) for x in (snap.get("forbiddenScope") or []) if str(x).strip()]
    if allowed:
        sections.append("## 允许改动范围\n\n" + "\n".join(f"- {x}" for x in allowed))
    if forbidden:
        sections.append("## 禁止改动\n\n" + "\n".join(f"- {x}" for x in forbidden))
    acceptance = [str(x) for x in (snap.get("acceptance") or []) if str(x).strip()]
    if acceptance:
        sections.append("## 验收标准\n\n" + "\n".join(f"- {x}" for x in acceptance))
    est = int(snap.get("estMin") or 0)
    if est > 0:
        sections.append(f"预估工作量：{est} 分钟")
    return "\n\n".join(sections)
