"""需求跟踪台账(arch_tracking_items) —— 会话中心左栏「需求跟踪」的单一事实源。

条目 = 工作记录六维度: 谁创建 / 内容 / 待谁操作 / 操作类型 / 结果 / 当前状态;
分类(category)与操作类型(action_type)为可配置字典(collab config tracking.*),
非固化枚举——用户裁决: 先不考虑固化分类, 分类需要灵活拓展。

主会话+子会话双 ID: main_conversation_id(需求主线) + conversation_id(直接/
子会话)——精确跟踪需求从提出到各 coding 子会话执行的全链路。

自动挂账: 事件点(任务/回执/需求/决策/异常)调用 emit()/sync_task(), 全部
吞错(台账失败不阻断主流程)。运行时台账, 不进 kb-schema-versions 登记。
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from .base import _db, _delete, _fetchall_routed, _get, _insert, _locate_db, _row_to_api, _scan_dbs, _update, next_id
from .states import (
    TASK_SAVED,
    TASK_PENDING_CONFIRM, TASK_RUNNING, TASK_WAITING_INPUT,
    TRACK_CANCELLED, TRACK_DONE, TRACK_FAILED, TRACK_RUNNING, TRACK_WAITING,
)

logger = logging.getLogger("arch.store.tracking")

# ── 可配置字典(collab config; UI 可增改, 不改代码拓展) ──────────────────
VOCAB_CATEGORIES_KEY = "tracking.categories"
VOCAB_ACTION_TYPES_KEY = "tracking.actionTypes"
DEFAULT_CATEGORIES = ["需求", "方案", "任务", "回执", "决策", "异常", "问询"]
DEFAULT_ACTION_TYPES = ["编码", "设计", "分析", "决策"]


def _now() -> int:
    return int(time.time() * 1000)


def _vocab(key: str, default: list) -> list:
    """读字典(collab config JSON 数组; 空/损坏回退默认)。"""
    from .blueprint import CollabConfigStore
    try:
        raw = CollabConfigStore.get(key, "")
        vals = json.loads(raw) if raw else []
        if isinstance(vals, list) and vals:
            return [str(x).strip() for x in vals if str(x).strip()]
    except Exception:  # noqa: BLE001
        pass
    return list(default)


def vocab_categories() -> list:
    return _vocab(VOCAB_CATEGORIES_KEY, DEFAULT_CATEGORIES)


def vocab_action_types() -> list:
    return _vocab(VOCAB_ACTION_TYPES_KEY, DEFAULT_ACTION_TYPES)


def vocab_save(categories: list = None, action_types: list = None) -> None:
    """写字典(传入 None 的域不动)。"""
    from .blueprint import CollabConfigStore
    if categories is not None:
        CollabConfigStore.set(VOCAB_CATEGORIES_KEY, json.dumps(
            [str(x).strip() for x in categories if str(x).strip()], ensure_ascii=False))
    if action_types is not None:
        CollabConfigStore.set(VOCAB_ACTION_TYPES_KEY, json.dumps(
            [str(x).strip() for x in action_types if str(x).strip()], ensure_ascii=False))


def resolve_main_conversation(conv_id: str) -> tuple[str, str]:
    """主/子会话双 ID 解析: 沿 parent_conv_id 上溯到主会话。

    返回 (main_conversation_id, direct_conversation_id)——直接会话即主会话
    时两者相同; 上游断裂(行缺失)时以已知最深会话兜底。"""
    direct = conv_id or ""
    cur = direct
    for _ in range(10):                       # 深度上限: 防脏数据成环
        if not cur:
            break
        from .conv import ConversationsStore
        conv = ConversationsStore.get(cur)
        if not conv:
            break
        parent = conv.get("parentConvId") or conv.get("parentId") or ""
        if not parent:
            break
        cur = parent
    return (cur or direct, direct)


class TrackingItemsStore:
    TABLE = "arch_tracking_items"

    @classmethod
    def create(cls, data: dict) -> dict:
        main_cid, direct_cid = resolve_main_conversation(
            str(data.get("conversationId") or ""))
        payload = {
            "id": data.get("id") or next_id("ti"),
            "category": data.get("category") or "",
            "title": data.get("title") or "",
            "content": data.get("content") or "",
            "action_type": data.get("actionType") or "",
            "creator_role": data.get("creatorRole") or "",
            "creator_id": data.get("creatorId") or "",
            "assignee_role": data.get("assigneeRole") or "",
            "assignee_id": data.get("assigneeId") or "",
            "state": data.get("state") or TRACK_DONE,
            "waiting_for": data.get("waitingFor") or "",
            "result": data.get("result") or "",
            "result_state": data.get("resultState") or "",
            "valid": 1 if data.get("valid", True) else 0,
            "main_conversation_id": main_cid,
            "conversation_id": direct_cid,
            "ref_type": data.get("refType") or "",
            "ref_id": data.get("refId") or "",
            "project_id": data.get("projectId") or "",
            "created_at": data.get("createdAt") or _now(),
            "updated_at": _now(),
        }
        # 项目归属兜底: 缺省时从主会话行推导(任务表同款防分裂约定);
        # 会话行缺失(旧数据/跨库) → 再从 ref 需求行推导(cv-204: 推导必须
        # 跨库——会话/需求住在项目库, 只查单桶会误落主库默认桶)
        if not payload["project_id"] and payload["main_conversation_id"]:
            try:
                from .conv import ConversationsStore
                payload["project_id"] = ((ConversationsStore.get(
                    payload["main_conversation_id"]) or {}).get("projectId") or "")
            except Exception:  # noqa: BLE001
                pass
        if not payload["project_id"] and payload["ref_id"]:
            # cv-204 台账写入路由: 需求表无 project_id 列——需求项目归属按库位置表达
            # (architect/<pid>/arch.db)。经 _locate_db 拿到所在库 → 解析 pid。
            try:
                rdb, found = _locate_db("arch_requirements", payload["ref_id"])
                if found:
                    _m = re.search(r"architect[/\\]([^/\\]+)[/\\]arch\.db$",
                                   getattr(rdb, "db_path", "") or "")
                    if _m:
                        payload["project_id"] = _m.group(1)
            except Exception:  # noqa: BLE001
                pass
        _insert(cls.TABLE, payload)
        return _row_to_api(payload)

    @classmethod
    def get(cls, item_id: str):
        row = _get(cls.TABLE, item_id)
        return _row_to_api(row) if row else None

    @classmethod
    def update(cls, item_id: str, data: dict) -> Optional[dict]:
        data = dict(data)
        if "valid" in data:                   # bool → int 列(读侧 0/1)
            data["valid"] = 1 if data["valid"] else 0
        data["updatedAt"] = _now()
        row = _update(cls.TABLE, item_id, data)
        return _row_to_api(row) if isinstance(row, dict) else None

    @classmethod
    def find_by_ref(cls, ref_type: str, ref_id: str,
                    category: str = "") -> list[dict]:
        """按溯源定位条目(任务状态同步/决策决议回填用); 同 ref 多条按时间倒序。"""
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE ref_type = ? AND ref_id = ? "
            "ORDER BY created_at DESC, rowid DESC",
            (ref_type, ref_id), None)
        out = [_row_to_api(r) for r in rows]
        if category:
            out = [r for r in out if (r.get("category") or "") == category]
        return out

    @classmethod
    def delete(cls, item_id: str) -> bool:
        """单条删除(误挂/过期条目清理; 会话删除走 delete_by_conversation 级联)。"""
        return bool(_delete(cls.TABLE, item_id))

    @classmethod
    def delete_by_conversation(cls, conv_id: str) -> int:
        """会话级联删除: 清该会话(直接会话或主线)相关的全部台账行。

        左侧删除会话 → 台账不留孤儿(主会话删除时, 其 coding 子会话条目
        经 main_conversation_id 一并清除)。台账与所属会话同库(project 推导)。
        返回删除行数; 失败吞错(不阻断会话删除)。"""
        if not conv_id:
            return 0
        try:
            from .base import _target_db
            from .conv import ConversationsStore
            pid = ((ConversationsStore.get(conv_id) or {}).get("projectId") or "")
            try:
                db = _target_db(cls.TABLE, project_id=pid or None)
            except Exception:  # noqa: BLE001
                from .base import _db
                db = _db()
            cur = db.execute(
                f"DELETE FROM {cls.TABLE} "
                "WHERE conversation_id = ? OR main_conversation_id = ?",
                (conv_id, conv_id))
            db.commit()
            return int(getattr(cur, "rowcount", 0) or 0)
        except Exception as e:  # noqa: BLE001
            logger.warning("[tracking] 会话级联删除失败 conv=%s: %s", conv_id, e)
            return 0

    @classmethod
    def _conds(cls, category: str, state: str, assignee_role: str,
               q: str) -> tuple[str, list]:
        conds, params = [], []
        if category:
            conds.append("category = ?")
            params.append(category)
        if state:
            conds.append("state = ?")
            params.append(state)
        if assignee_role:
            conds.append("assignee_role = ?")
            params.append(assignee_role)
        if q:
            conds.append("(title LIKE ? OR content LIKE ?)")
            like = f"%{q}%"
            params += [like, like]
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        return where, params

    @classmethod
    def all(cls, category: str = "", state: str = "", assignee_role: str = "",
            q: str = "", project_id: str = None, conversation_id: str = "",
            limit: int = 200) -> list[dict]:
        """按项目读取(cv-204 项目硬隔离裁决): architect 无全局视角——

        project_id 缺省回落请求上下文; 两皆无 → [](不跨库扫描, 退役 scope=all
        语义)。conversation_id: 按会话过滤(双 ID 语义: 直接会话 | 主线会话)。
        """
        from .. import ctx as _ctx
        pid = project_id or _ctx.get_project()
        if not pid:
            return []            # 无项目上下文 → 空结果(硬隔离, 不扫描)
        conds, cparams = ["project_id = ?"], [pid]
        if conversation_id:
            conds.append("(conversation_id = ? OR main_conversation_id = ?)")
            cparams.extend([conversation_id, conversation_id])
        where, params = cls._conds(category, state, assignee_role, q)
        if where:
            conds.append(where[len(" WHERE "):])
            cparams.extend(params)
        sql = (f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
               "ORDER BY created_at DESC LIMIT ?")
        rows, mode = _fetchall_routed(cls.TABLE, sql, (*cparams, int(limit)), pid)
        if mode == "empty":
            # 项目库未建 → 条目在主库默认桶(推导路由的目标)——同过滤读主库,
            # 硬隔离语义不变(project_id = ? 恒在 WHERE)
            rows = _db().fetchall(sql, (*cparams, int(limit)))
            mode = "one"
        out = [_row_to_api(r) for r in rows]
        if mode == "scan":
            out.sort(key=lambda r: (r.get("createdAt") is None,
                                    r.get("createdAt") or 0), reverse=True)
        return out[: int(limit)]

    @classmethod
    def all_across(cls, category: str = "", state: str = "",
                   assignee_role: str = "", q: str = "",
                   limit: int = 200) -> list[dict]:
        """跨全库(主库+各项目库)扫描合并——会话中心统一视图, 不受请求项目上下文限制。"""
        where, params = cls._conds(category, state, assignee_role, q)
        sql = f"SELECT * FROM {cls.TABLE}{where} ORDER BY created_at DESC LIMIT ?"
        out: list[dict] = []
        for d in _scan_dbs():
            out.extend(_row_to_api(r) for r in d.fetchall(sql, (*params, int(limit))))
        out.sort(key=lambda r: (r.get("createdAt") is None,
                                r.get("createdAt") or 0), reverse=True)
        return out[: int(limit)]


# ── 自动挂账(事件点调用; 全部吞错——台账失败不阻断主流程) ────────────────

def emit(*, category: str, title: str, content: str = "", action_type: str = "",
         creator_role: str = "", creator_id: str = "", assignee_role: str = "",
         assignee_id: str = "", state: str = TRACK_DONE, waiting_for: str = "",
         result: str = "", result_state: str = "", ref_type: str = "",
         ref_id: str = "", conversation_id: str = "", project_id: str = "") -> None:
    """事件点挂账入口。幂等性由调用方保证(ref 定位去重); 本函数只写不抛。"""
    try:
        TrackingItemsStore.create({
            "category": category, "title": title, "content": content,
            "actionType": action_type, "creatorRole": creator_role,
            "creatorId": creator_id, "assigneeRole": assignee_role,
            "assigneeId": assignee_id, "state": state, "waitingFor": waiting_for,
            "result": result, "resultState": result_state,
            "refType": ref_type, "refId": ref_id,
            "conversationId": conversation_id, "projectId": project_id,
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("[tracking] 挂账失败 category=%s ref=%s: %s",
                       category, ref_id, e)


def _task_state_of(status: str) -> tuple[str, str]:
    """任务状态 → 台账 (state, waitingFor) 映射(单向同步)。"""
    if status in (TASK_PENDING_CONFIRM, TASK_SAVED):
        return TRACK_WAITING, "user"          # 等用户启动(默认保存: saved=待开跑)
    if status == TASK_RUNNING:
        return TRACK_RUNNING, ""
    if status == TASK_WAITING_INPUT:
        return TRACK_WAITING, "user"          # 执行器等待用户回复
    if status == "done":
        return TRACK_DONE, ""
    if status == "failed":
        return TRACK_FAILED, ""
    return TRACK_CANCELLED, ""                # cancelled 与未知值兜底


def sync_task(task: dict, prev_status: str = "") -> None:
    """任务生命周期 → 台账同步(创建建条, 状态变化更新; 单向, 不回写任务)。"""
    try:
        task_id = str(task.get("id") or "")
        if not task_id:
            return
        status = task.get("status") or ""
        state, waiting_for = _task_state_of(status)
        result_state = ("ok" if status == "done"
                        else ("failed" if status == "failed"
                              else ("cancelled" if status == "cancelled" else "")))
        result = str(task.get("resultMd") or "")[:500] if result_state else ""
        existing = TrackingItemsStore.find_by_ref("task", task_id, category="任务")
        patch = {
            "state": state, "waitingFor": waiting_for,
            "result": result, "resultState": result_state,
            "assigneeRole": "coding",
            "assigneeId": task.get("executorId") or task.get("executorType") or "",
        }
        if existing:
            TrackingItemsStore.update(existing[0]["id"], patch)
        else:
            emit(category="任务",
                 title=str(task.get("title") or "")[:120],
                 content=str(task.get("instruction") or "")[:2000],
                 action_type="编码", creator_role="architect",
                 assignee_role="coding",
                 assignee_id=task.get("executorId") or task.get("executorType") or "",
                 state=state, waiting_for=waiting_for,
                 result=result, result_state=result_state,
                 ref_type="task", ref_id=task_id,
                 conversation_id=task.get("conversationId") or "",
                 project_id=task.get("projectId") or "")
    except Exception as e:  # noqa: BLE001
        logger.warning("[tracking] 任务同步失败 task=%s: %s", task.get("id"), e)
