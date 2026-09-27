"""消息卡片契约(单源) — 会话流内确定性回执卡的唯一落流出口。

## 卡类型词汇表(闭集; 新增 kind 必须先在此注册并补前端渲染分支)

| kind               | 卡       | 载荷字段                              | 前端渲染              |
|--------------------|----------|----------------------------------------|-----------------------|
| specReady          | 需求卡   | requirementId, ver, updated?, noDesign? | [一键建卡执行]        |
| task_card          | 执行卡   | taskId                                  | TaskCard(确认/停止)   |
| task_approval      | 决策卡   | taskId, approvalJobId, approvalRequestId | 批准/拒绝 + /approve  |
| task_start         | 执行回执 | taskId                                  | 文本                  |
| task_input         | 执行回执 | taskId                                  | 文本                  |
| task_done          | 执行回执 | taskId, branch                          | 文本                  |
| task_failed        | 执行回执 | taskId                                  | 文本                  |
| task_approval_done | 执行回执 | taskId                                  | 文本                  |
| task_progress      | 执行回执 | taskId                                  | 文本                  |
| turnError          | 错误卡   | —                                       | ❌ 文本(review=error) |
| digest_sent        | 转达存证 | chars                                   | 折叠卡                |
| taskPlan           | 计划卡   | requirementId, total                    | 文本(步骤清单)        |
| choices            | 问询卡   | title, groups[], note, fingerprint?     | ChoicesCard(点选/自定义/跳过) |
| taskPlanDone       | 汇总回执 | requirementId, total                    | 文本(合并提醒)        |

历史遗留(仅存在于旧数据, 渲染层兼容降级, 不再产生): specCreated、guard、
specDraft、task_* 旧语义变体。

## 持久化契约(cv-248 固化, 通用性承诺)
- **所有卡 = 会话消息行**(land 单点落 arch_conversation_messages)——持久化
  与随会话级联删除对全部卡型天然成立, 无例外; 用户填入信息类卡(问询
  choices/决策 task_approval/等待输入 task_input)与回执类卡同一路径。
  禁止任何「前端本地状态卡」(不落库即不可持久, 违例=架构缺陷)。
- 新卡三步注册(缺一即渲染面断裂): ①本词汇表登记 kind ②items.CARD_ITEM_MAP
  读侧投影(漏投影=刷新后卡片降级为正文——一致性由测试守门) ③前端 m.item
  分支渲染器。
- **删除策略(cv-248 liveness 裁决)**: 消息删除是正常操作, 卡的删除安全
  由读取面自愈兜底(I2 惰性失效)——锚位卡删后由 update-by-meta 失败回落
  land 自动重建; 回执卡删除无状态影响。新卡登记 kind 时须同时在
  DELETE_POLICY 声明策略(守门: 词汇表全覆盖), 缺省 receipt。

## 规范(cv-175/177 裁决)
- 卡片落流唯一入口 land(): 库路由 / reviewState / meta 序列化 / SSE 通知
  全部单点实现; 禁止再手写 append_message+meta 组合(四实现漂移是
  cv-163~177 多起事故根因)。
- kind 不在白名单 → raise ValueError(明确报错, 禁止静默降级)。
- wire 名(如 specReady)保持不变——前端与历史消息依赖, 语义重命名不做。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger("arch.collab.cards")

# ── 词汇表(wire 名 = 前端/历史契约, 不重命名) ──────────────────────────
KIND_REQUIREMENT = "specReady"
KIND_TASK_CARD = "task_card"
KIND_TASK_APPROVAL = "task_approval"
KIND_TURN_ERROR = "turnError"
KIND_DIGEST = "digest_sent"
KIND_TASK_PLAN = "taskPlan"          # 环节十四: 任务计划卡(有序步骤清单)
KIND_TASK_INPUT_ECHO = "task_input_echo"  # R4: 用户回复转达持久回执(requestId 对账)
KIND_TASK_PLAN_DONE = "taskPlanDone"  # 环节十四: 计划全部完成汇总回执
# 消息级标记(非卡片 kind): meta 布尔字段, 落流单点登记(cv-197 审计 D3)
MSG_FLAG_SYNTHETIC = "synthetic"      # 按钮触发的合成用户消息(/执行 等)——前端不回显

KIND_TASK_IGNORED = "task_ignored"    # 2026-09-20: 用户主动忽略任务卡(置灰回执)
KIND_TASK_OVERLAP = "task_overlap"    # cv-272: 并行范围重叠软警告(警告+可继续)
KIND_REQ_IGNORED = "req_ignored"      # 2026-09-20: 用户主动忽略需求卡(置灰回执)
KIND_TASK_STATUS = "task_status"      # cv-203: 任务执行状态卡(同 taskId 单卡原位更新)
KIND_CHOICES = "choices"              # cv-247: 结构化问询卡(可交互选项/开放题, 三源汇一)
KIND_PROXY = "proxy"                # 重定位: coding 直通会话回执(启动/续话/结束/错误)
KIND_TASK_RECEIPTS = (
    "task_start", "task_input", "task_done", "task_failed",
    "task_approval_done", "task_progress",
)

_KNOWN_KINDS = frozenset(
    (KIND_REQUIREMENT, KIND_TASK_CARD, KIND_TASK_APPROVAL, KIND_TURN_ERROR,
     KIND_DIGEST, KIND_TASK_PLAN, KIND_TASK_PLAN_DONE, KIND_TASK_INPUT_ECHO,
     KIND_TASK_IGNORED, KIND_REQ_IGNORED, KIND_TASK_STATUS,
     KIND_TASK_OVERLAP,
     *KIND_TASK_RECEIPTS, KIND_CHOICES, KIND_PROXY))

# ── 删除策略(cv-248 liveness): kind → 删除后状态语义(守门全覆盖) ──────
# rebuildable = 结构投影卡: 删除安全——读取面自愈(update-by-meta 回落 land
#               重建 / 焦点帧零写点派生 / 进度锚原位重落), 事实层独立不受影响
# receipt     = 回执/通知卡: 删除无状态影响(纯展示)
DELETE_REBUILDABLE = "rebuildable"
DELETE_RECEIPT = "receipt"
DELETE_POLICY = {
    KIND_REQUIREMENT: DELETE_REBUILDABLE,   # specReady: 事实层=需求/规约版本行
    KIND_TASK_PLAN: DELETE_REBUILDABLE,     # 进度锚: 下次刷新原位重落
    KIND_TASK_STATUS: DELETE_REBUILDABLE,   # 状态卡: 下次状态推进原位重落
    KIND_CHOICES: DELETE_REBUILDABLE,       # 问询卡: 帧源零写点派生, 跟踪条目独立
    KIND_TASK_CARD: DELETE_RECEIPT,
    KIND_TASK_APPROVAL: DELETE_RECEIPT,
    KIND_TURN_ERROR: DELETE_RECEIPT,
    KIND_DIGEST: DELETE_RECEIPT,
    KIND_TASK_PLAN_DONE: DELETE_RECEIPT,
    KIND_TASK_INPUT_ECHO: DELETE_RECEIPT,
    KIND_PROXY: DELETE_RECEIPT,           # 直通回执(文本形态, 会话删除随清)
    KIND_TASK_IGNORED: DELETE_RECEIPT,
    KIND_TASK_OVERLAP: DELETE_RECEIPT,     # cv-272 软警告回执(随会话删)
    KIND_REQ_IGNORED: DELETE_RECEIPT,
    **{k: DELETE_RECEIPT for k in KIND_TASK_RECEIPTS},
}

_ERROR_REVIEW_STATE = "error"


def land(conv_id: str, text: str, kind: Optional[str] = None, *,
         role: str = "assistant", project_id: str = "", agent: str = "",
         review_state: str = "unread", **payload) -> Optional[dict]:
    """卡片/回执落流唯一入口: 落库 + reviewState + SSE 通知单点实现。

    kind: 卡类型(白名单外 raise); None = 纯文本回执(无卡)。
    **payload: 卡载荷字段(requirementId/taskId/ver/branch/chars...)
    返回落库消息行(含 id; 供调用方回指 done 事件), 失败返回 None(不阻断主流程)。
    """
    if kind is not None and kind not in _KNOWN_KINDS:
        raise ValueError(
            f"未知卡片类型 {kind!r}——必须在 collab.cards 词汇表注册后再使用")
    try:
        from ... import store as _store
        from ...common import _ts
        if not project_id:
            try:
                project_id = ((_store.ConversationsStore.get(conv_id) or {})
                              .get("projectId") or "")
            except Exception:  # noqa: BLE001
                pass
        row = {
            "id": _store.next_id("m"), "conversationId": conv_id, "role": role,
            "time": _ts(), "content": text, "projectId": project_id,
            "agent": agent or "",
        }
        if kind is not None or payload:
            meta = {"kind": kind} if kind else {}
            meta.update(payload)
            row["meta"] = json.dumps(meta, ensure_ascii=False)
        _store.ConversationsStore.append_message(row)
        if review_state:
            try:
                _store.ConversationsStore.update(
                    conv_id, {"reviewState": review_state})
            except Exception:  # noqa: BLE001
                pass
        try:
            logger.info("[cards] land conv=%s kind=%s id=%s → emit conv-message",
                        conv_id, kind or "", row["id"])
            emit(conv_id, row["id"], agent=agent or "", kind=kind or "")
        except Exception:  # noqa: BLE001
            logger.exception("[cards] conv-message emit 失败 conv=%s", conv_id)
        return row
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("[cards] 落流失败 conv=%s kind=%s: %s", conv_id, kind, e)
        return None


def land_status(conv_id: str, text: str, task_id: str, *, status: str = "",
                project_id: str = "", agent: str = "", **payload) -> Optional[dict]:
    """任务状态卡(cv-203 裁决): 状态/进度独立为专用消息, 同 taskId 单卡。

    首次落新卡(kind=task_status); 之后原位 UPDATE 同一行(不追加新消息,
    进度不刷屏)——定位与改写同库连接(update_message_by_meta, 防跨库路由
    漂移); 读侧经 SSE conv-message 通知刷新。失败返回 None(不阻断)。"""
    try:
        from ... import store as _store
        upd = _store.ConversationsStore.update_message_by_meta(
            conv_id, {"kind": KIND_TASK_STATUS, "taskId": task_id},
            {"content": text, "meta": {"status": status, **payload},
             "time": int(__import__("time").time() * 1000)})
        if upd:
            try:
                emit(conv_id, upd["id"],
                     agent=agent or "", kind=KIND_TASK_STATUS)
            except Exception:  # noqa: BLE001
                pass
            return upd
        return land(conv_id, text, kind=KIND_TASK_STATUS, role="assistant",
                    project_id=project_id, agent=agent, taskId=task_id,
                    status=status, **payload)
    except Exception as e:  # noqa: BLE001
        logger.warning("[cards] 状态卡落流失败 conv=%s task=%s: %s",
                       conv_id, task_id, e)
        return None


def land_plan_progress(conv_id: str, rid: str, text: str, *, total: int = 0,
                       project_id: str = "", agent: str = "") -> Optional[dict]:
    """计划进度锚(L3, 批戊信息流优化): 同 requirementId 单卡原位更新。

    计划总览卡落首卡(kind=taskPlan); 之后每步完成/预填原位 UPDATE 为进度
    视图——信息流中 N 步计划只占 1 个锚位。失败返回 None(不阻断)。"""
    try:
        from ... import store as _store
        upd = _store.ConversationsStore.update_message_by_meta(
            conv_id, {"kind": KIND_TASK_PLAN, "requirementId": rid},
            {"content": text, "meta": {"total": total}})
        if upd:
            try:
                emit(conv_id, upd["id"], agent=agent or "", kind=KIND_TASK_PLAN)
            except Exception:
                pass
            return upd
        return land(conv_id, text, kind=KIND_TASK_PLAN, role="assistant",
                    project_id=project_id or "", agent=agent,
                    requirementId=rid, total=total)
    except Exception as e:
        logger.warning("[cards] 进度锚更新失败 conv=%s rid=%s: %s",
                       conv_id, rid, e)
        return None


# ── 结构化问询卡(cv-247): 协议解析+落流单源 ──────────────────────────
# 通用性约束(用户裁决): 问题自由度不设模板(组数/选项数/措辞自由, 最小可渲染
# 校验); 选择题组恒带自定义输入与跳过(前端语义, 协议无开关); 开放题组
# (无 options)纯输入——策略库开放式问题与模型临场问题同构适配。

# 围栏标记词汇(choices=协议显式标记 cv-247; json=漂移形态 cv-252 兜底):
# 单一模板派生——提取/剥离零复制, 标记互斥由字面天然隔离(零围栏竞争)
_CHOICES_FENCE_RES = {
    _m: re.compile(rf"```{_m}\s*\n?(\{{.*?\}})\s*```", re.DOTALL)
    for _m in ("choices", "json")}


def valid_choices_payload(payload: Any) -> bool:
    """最小可渲染校验(fail-soft): groups 非空、组有 label/question、
    选项有 label。不校验语义/数量——问题自由度不设模板(cv-247)。"""
    if not isinstance(payload, dict):
        return False
    groups = payload.get("groups")
    if not isinstance(groups, list) or not groups:
        return False
    for g in groups:
        if not isinstance(g, dict):
            return False
        if not (str(g.get("label") or "").strip()
                or str(g.get("question") or "").strip()):
            return False
        opts = g.get("options")
        if opts is not None:
            if not isinstance(opts, list):
                return False
            for o in opts:
                if not isinstance(o, dict) \
                        or not str(o.get("label") or "").strip():
                    return False
    return True


def extract_choices_fence(text: str) -> Optional[dict]:
    """提取显式 ```choices 围栏(结构化问询卡协议; cv-247)。

    只认显式标记——不进 json 候选扫描(cv-246 教训: 围栏竞争致误归属);
    坏载荷返回 None(调用方保留正文, 信息不丢)。"""
    return _extract_fence_payload(text, "choices")


def extract_choices_json_fence(text: str) -> Optional[dict]:
    """```json 围栏兜底识别(cv-252): 模型漂移到 ```json 标记的问询载荷归一。

    只在问询意图佐证下由调用方启用(见 resolve_choices_payload——意图+schema
    双门); 载荷校验与显式标记同一把尺。"""
    return _extract_fence_payload(text, "json")


def resolve_choices_payload(text: str, *,
                            intent_clarify: bool = False
                            ) -> "tuple[Optional[dict], str]":
    """问询载荷识别单源入口(cv-247 协议 + cv-252 兜底汇一)。

    显式 ```choices 标记优先(协议); 未命中且调用方持问询意图佐证
    (GU 判 CLARIFY_ACTION——意图+schema 双门, 调用方把关)时对 ```json
    围栏做同尺兜底, 不做无差别扫描(cv-246)。
    返回 (payload, marker): marker 供落卡成功后按命中标记精确剥离。"""
    d = _extract_fence_payload(text, "choices")
    if d is not None:
        return d, "choices"
    if intent_clarify:
        d = _extract_fence_payload(text, "json")
        if d is not None:
            return d, "json"
    return None, ""


def _extract_fence_payload(text: str, marker: str) -> Optional[dict]:
    """单一提取路径: 按标记取围栏 JSON → valid_choices_payload 同尺校验。"""
    m = _CHOICES_FENCE_RES[marker].search(text or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return None
    return d if valid_choices_payload(d) else None


def strip_choices_fence(text: str, marker: str = "choices") -> str:
    """移除命中标记的问询围栏(落卡成功后卡即回执, 正文复述 JSON 属垃圾
    ——cv-174 同规); marker 与 resolve_choices_payload 返回值配对。"""
    if not text:
        return ""
    rx = _CHOICES_FENCE_RES.get(marker)
    if not rx or not rx.search(text):
        return text
    return rx.sub("", text).strip()


def land_choices(conv_id: str, payload: dict, *, fingerprint: str = "",
                 project_id: str = "", agent: str = "",
                 gu_action: str = "") -> Optional[dict]:
    """问询卡落流: 校验通过才落; fingerprint 非空时同源卡**原位更新**
    (GU 确定性源每回合重判, 多回合澄清只占一个锚位——进度锚同款)。
    模型围栏源 fingerprint 留空(每回合独立卡)。坏载荷返回 None。

    gu_action: 回合管线写入的回合动作记账(cv-254)——围栏代落+空收尾豁免
    后回合只有卡, guAction 载体随卡归位(供焦点帧 clarify_pending 派生);
    空缺省=调用方无记账语义(向后兼容)。"""
    if not valid_choices_payload(payload):
        return None
    title = str(payload.get("title") or "").strip() or "请确认以下问题"
    meta_payload = {"title": title,
                    "groups": payload.get("groups") or [],
                    "note": str(payload.get("note") or "")}
    if gu_action:
        meta_payload["guAction"] = gu_action
    if fingerprint:
        meta_payload["fingerprint"] = fingerprint
    if fingerprint:
        try:
            from ... import store as _store
            upd = _store.ConversationsStore.update_message_by_meta(
                conv_id, {"kind": KIND_CHOICES, "fingerprint": fingerprint},
                {"content": title, "meta": meta_payload,
                 "time": int(__import__("time").time() * 1000)})
            if upd:
                try:
                    emit(conv_id, upd["id"], agent=agent or "",
                         kind=KIND_CHOICES)
                except Exception:  # noqa: BLE001
                    pass
                return upd
        except Exception as e:  # noqa: BLE001
            logger.warning("[cards] 问询卡原位更新失败 conv=%s: %s", conv_id, e)
    row = land(conv_id, title, kind=KIND_CHOICES, role="assistant",
               project_id=project_id, agent=agent, **meta_payload)
    # 需求跟踪资产条目(cv-248 裁决): 问询发出即挂账留档(用户填入的信息
    # 收集在台账可溯); 仅新卡挂账(原位更新不重复)。
    if row:
        try:
            from ...store import tracking as _tr
            summary = "；".join(
                f"{(g.get('label') or g.get('question') or '')[:24]}"
                for g in (payload.get("groups") or [])[:6])
            _tr.emit(category="问询", title=title[:120],
                     content=summary, action_type="澄清",
                     creator_role="architect", state=_tr.TRACK_DONE,
                     result="问询卡已落流，待用户答复",
                     result_state="ok", ref_type="choices_card",
                     ref_id=str(row.get("id") or ""),
                     conversation_id=conv_id, project_id=project_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[cards] 问询卡挂账失败 conv=%s: %s", conv_id, e)
    return row


def emit(conv_id: str, msg_id: str, agent: str = "", kind: str = "") -> None:
    """SSE conv-message 通知(前端按会话刷新 → 卡片即时渲染)。测试可 patch。"""
    from .sse import emit as _emit
    _emit("conv-message", conv_id, msgId=msg_id, agent=agent, kind=kind)
