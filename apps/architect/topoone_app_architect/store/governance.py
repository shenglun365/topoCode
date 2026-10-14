"""store 拆分模块（A1-T3：纯移动）。"""
from __future__ import annotations

import json

from .base import _delete, _dumps, _fetchall_routed, _get, _insert, _locate_db, _now_ms, _row_to_api, _row_to_api_v, _target_db, _update

class FrameworkConfigStore:
    """认知框架配置（版本行即变更审计；每 project 至多一行 active=1）。

    无 active 行 = 未定制 → 调用方回退默认预设 mid（不落库，首次变更时才落版本行）。
    """

    TABLE = "arch_framework_configs"

    @classmethod
    def get_active_raw(cls, project_id: str) -> Optional[dict]:
        """返回 raw 行（config 仍为 JSON 串）；无则 None。"""
        if not project_id:
            return None
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE project_id = ? AND active = 1 "
            f"ORDER BY version DESC LIMIT 1",
            (project_id,), project_id or None)
        return rows[0] if rows else None

    @classmethod
    def versions(cls, project_id: str, limit: int = 50) -> list[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE project_id = ? ORDER BY version DESC LIMIT ?",
            (project_id, int(limit)), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def next_version(cls, project_id: str) -> int:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT MAX(version) AS v FROM {cls.TABLE} WHERE project_id = ?",
            (project_id,), project_id or None)
        v = rows[0].get("v") if rows else None
        return int(v or 0) + 1

    @classmethod
    def activate(cls, project_id: str, config: dict, change_kind: str,
                 affected: Optional[dict] = None, executed_by: str = "",
                 note: str = "") -> dict:
        """事务：旧 active 行清零 + 插入新版本行(active=1)。"""
        now = _now_ms()
        version = cls.next_version(project_id)
        row_id = f"fwc-{project_id[:8]}-{version}"
        db = _target_db(cls.TABLE, project_id=project_id)
        db.execute(
            f"UPDATE {cls.TABLE} SET active = 0 WHERE project_id = ?", (project_id,))
        db.execute(
            f"INSERT INTO {cls.TABLE} (id, project_id, version, config, change_kind, "
            f"affected_summary, executed_by, note, active, created_at) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (row_id, project_id, version, _dumps(config), change_kind,
             _dumps(affected or {}), executed_by, note, now))
        db.commit()
        return {"id": row_id, "projectId": project_id, "version": version,
                "config": config, "changeKind": change_kind,
                "affectedSummary": affected or {}, "executedBy": executed_by,
                "note": note, "active": 1, "createdAt": now}




class CapabilityProposalStore:
    """能力提案(WS7 提炼闭环): 规约/流程/技巧/skill 提案——pending 待审, 采纳后生效。"""

    TABLE = "arch_capability_proposals"

    @classmethod
    def create(cls, project_id: str, type_: str, title: str, content: str,
               scenarios: Optional[list] = None, reason: str = "",
               source_conversation_id: str = "") -> dict:
        now = _now_ms()
        data = {"id": f"cap-{now}-{abs(hash(title + type_)) % 10 ** 6}",
                "projectId": project_id, "type": type_, "title": title,
                "content": content,
                "scenarios": json.dumps(scenarios or [], ensure_ascii=False),
                "reason": reason, "sourceConversationId": source_conversation_id,
                "status": "pending", "createdAt": now, "updatedAt": now}
        _insert(cls.TABLE, data)
        return _row_to_api(data)

    @classmethod
    def list(cls, project_id: str, status: str = "", limit: int = 200) -> list[dict]:
        where, params = ["project_id = ?"], [project_id]
        if status:
            where.append("status = ?")
            params.append(status)
        rows, _m = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(where)} "
            f"ORDER BY created_at DESC LIMIT {int(limit)}",
            tuple(params), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def update(cls, row_id: str, patch: dict) -> Optional[dict]:
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def get(cls, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        rows, _m = _fetchall_routed(
            cls.TABLE, f"SELECT * FROM {cls.TABLE} WHERE id = ? LIMIT 1",
            (row_id,), project_id or None)
        row = _row_to_api(rows[0]) if rows else None
        if row and project_id and row.get("projectId") != project_id:
            return None
        return row


class RuleDefStore:
    """守护规约库(2610 重构): skill 式自由文本规约, 一等实体。

    可复用(多目标共享)/可多挂(一目标多规约); source: manual | skill(技能库导入)。
    """

    TABLE = "arch_rule_defs"

    @classmethod
    def create(cls, project_id: str, title: str, content: str,
               source: str = "manual") -> dict:
        now = _now_ms()
        data = {"id": f"rule-{now}-{abs(hash((title, project_id))) % 10 ** 6}",
                "projectId": project_id,
                "title": str(title or "").strip()[:120] or "未命名规约",
                "content": str(content or "")[:8000],
                "source": source if source in ("manual", "skill") else "manual",
                "createdAt": now, "updatedAt": now}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def list(cls, project_id: str, q: str = "", limit: int = 500) -> list[dict]:
        conds, params = ["project_id = ?"], [project_id]
        if (q or "").strip():
            conds.append("(title LIKE ? OR content LIKE ?)")
            like = f"%{q.strip()}%"
            params += [like, like]
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
            f"ORDER BY updated_at DESC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def get(cls, rule_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.TABLE, rule_id, project_id)

    @classmethod
    def update(cls, rule_id: str, title: str = "", content: str = "") -> Optional[dict]:
        patch: dict = {"updatedAt": _now_ms()}
        if title.strip():
            patch["title"] = title.strip()[:120]
        if content or content == "":
            patch["content"] = str(content)[:8000]
        return _update(cls.TABLE, rule_id, patch)

    @classmethod
    def delete(cls, rule_id: str) -> bool:
        # 级联卸载关联(规约删除即全目标卸载)——同库事务
        db, found = _locate_db(cls.TABLE, rule_id)
        if not db or not found:
            return False
        db.execute(f"DELETE FROM {TargetRuleStore.TABLE} WHERE rule_id = ?", (rule_id,))
        db.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (rule_id,))
        db.commit()
        return True


NL2 = "\n\n"   # 规约拼接分隔(避免源内转义歧义)


class TargetRuleStore:
    """守护挂载关联(2610 重构): 目标(三层) ↔ 规约 多对多; 挂载即核心(无分级)。"""

    TABLE = "arch_target_rules"
    TYPES = ("asset", "component", "file")

    @classmethod
    def attach(cls, project_id: str, target_type: str, target_id: str,
               rule_id: str, title: str = "") -> dict:
        tt = target_type if target_type in cls.TYPES else "asset"
        tid = str(target_id or "").strip()
        if not tid:
            raise ValueError("target_id 不能为空")
        exist = cls.find(project_id, tt, tid, rule_id)
        if exist:
            return exist
        data = {"id": f"tr-{_now_ms()}-{abs(hash((tt, tid, rule_id))) % 10 ** 6}",
                "projectId": project_id, "targetType": tt, "targetId": tid,
                "ruleId": rule_id, "title": str(title or tid)[:120],
                "createdAt": _now_ms()}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def find(cls, project_id: str, target_type: str, target_id: str,
             rule_id: str) -> Optional[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE project_id=? AND target_type=? "
            f"AND target_id=? AND rule_id=? LIMIT 1",
            (project_id, target_type, str(target_id or "").strip(), rule_id),
            project_id or None)
        return _row_to_api(rows[0]) if rows else None

    @classmethod
    def list(cls, project_id: str, target_type: str = "",
             limit: int = 2000) -> list[dict]:
        conds, params = ["project_id = ?"], [project_id]
        if target_type in cls.TYPES:
            conds.append("target_type = ?")
            params.append(target_type)
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
            f"ORDER BY created_at ASC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def detach(cls, project_id: str, target_type: str, target_id: str,
               rule_id: str) -> bool:
        db = _target_db(cls.TABLE, project_id=project_id)
        cur = db.execute(
            f"DELETE FROM {cls.TABLE} WHERE project_id=? AND target_type=? "
            f"AND target_id=? AND rule_id=?",
            (project_id, target_type, str(target_id or "").strip(), rule_id))
        db.commit()
        return cur.rowcount > 0

    @classmethod
    def list_effective(cls, project_id: str, limit: int = 500) -> list[dict]:
        """守护消费聚合视图: 关联展开 → 旧 marks 形状(rulesMd=多规约按序拼接)。

        引擎(core_guard)/MCP(map.core)/回执 全链经此单口消费, 规约增删/复用
        对守护透明。行形状: {targetType, targetId, title, rulesMd, rules[{ruleId,title,content}]}。
        """
        links = cls.list(project_id, limit=limit * 5)
        if not links:
            return []
        by_rule: dict = {}
        for lk in links:
            rid = str(lk.get("ruleId") or "")
            if rid and rid not in by_rule:
                rd = RuleDefStore.get(rid, project_id)
                if rd:
                    by_rule[rid] = rd
        agg: dict = {}
        order: list = []
        for lk in links:
            rd = by_rule.get(str(lk.get("ruleId") or ""))
            if not rd:
                continue
            key = (lk["targetType"], lk["targetId"])
            if key not in agg:
                agg[key] = {"targetType": lk["targetType"], "targetId": lk["targetId"],
                            "title": lk.get("title") or lk["targetId"],
                            "rules": [], "rulesMd": ""}
                order.append(key)
            row = agg[key]
            row["title"] = row["title"] or (lk.get("title") or lk["targetId"])
            row["rules"].append({"ruleId": rd["id"], "title": rd.get("title") or "",
                                 "content": rd.get("content") or ""})
        out = []
        for key in order:
            row = agg[key]
            row["rulesMd"] = NL2.join(
                (f"- {r['title']}" + NL2 + r["content"]).strip() if r["title"]
                else r["content"] for r in row["rules"])
            out.append(row)
        return out[:limit]


class NamingConventionStore:
    """资产命名规约（场景标签 NOT NULL——agent 按场景加载，禁全量注入 R7）。"""

    TABLE = "arch_naming_conventions"

    @classmethod
    def create(cls, project_id: str, rule_text: str, scenarios: list,
               scope: str = "project", component_id: str = "",
               applies_kinds: Optional[list] = None, source: str = "manual",
               author: str = "", framework_version: int = 0,
               status: str = "active") -> dict:
        data = {"id": f"conv-{_now_ms()}-{abs(hash(rule_text)) % 10 ** 6}",
                "projectId": project_id, "scope": scope,
                "componentId": component_id,
                "appliesKinds": applies_kinds or [],
                "ruleText": rule_text, "source": source,
                "scenarios": scenarios or ["general"], "status": status,
                "author": author, "frameworkVersion": framework_version,
                "createdAt": _now_ms(), "updatedAt": _now_ms()}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def list(cls, project_id: str, scenario: str = "",
             status: str = "active", limit: int = 200) -> list[dict]:
        conds = ["project_id = ?", "status = ?"]
        params: list = [project_id, status]
        if scenario.strip():
            # 场景过滤：scenarios JSON 含该标签（LIKE 足够，标签是封闭枚举）
            conds.append("scenarios LIKE ?")
            params.append(f'%"{scenario.strip()}"%')
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
            f"ORDER BY updated_at DESC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def update(cls, row_id: str, patch: dict) -> Optional[dict]:
        patch = dict(patch)
        patch["updatedAt"] = _now_ms()
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def get(cls, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.TABLE, row_id, project_id)

    @classmethod
    def delete(cls, row_id: str) -> bool:
        return _delete(cls.TABLE, row_id)

    @classmethod
    def mark_pending_review(cls, project_id: str, framework_version: int) -> int:
        """框架标准变更 → 关联旧值域的规约标记待复核（plan-C §5.3）。"""
        db = _target_db(cls.TABLE, project_id=project_id)
        cur = db.execute(
            f"UPDATE {cls.TABLE} SET status = 'pending_review', updated_at = ? "
            f"WHERE project_id = ? AND status = 'active'",
            (_now_ms(), project_id))
        db.commit()
        return cur.rowcount or 0




class GlossaryStore:
    """术语表（词典，纯参考非约束）。"""

    TABLE = "arch_glossary"

    @classmethod
    def _api(cls, row: dict) -> dict:
        return _row_to_api_v("arch_glossary", row)


    @classmethod
    def create(cls, project_id: str, term: str, alias: Optional[list] = None,
               definition: str = "", source: str = "manual",
               source_ref: str = "", author: str = "") -> dict:
        data = {"id": f"gls-{_now_ms()}-{abs(hash(term)) % 10 ** 6}",
                "projectId": project_id, "term": term, "alias": alias or [],
                "definition": definition, "source": source,
                "sourceRef": source_ref, "author": author,
                "createdAt": _now_ms(), "updatedAt": _now_ms()}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def list(cls, project_id: str, q: str = "", limit: int = 500) -> list[dict]:
        conds = ["project_id = ?"]
        params: list = [project_id]
        if q.strip():
            conds.append("(term LIKE ? OR definition LIKE ?)")
            like = f"%{q.strip()}%"
            params += [like, like]
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
            f"ORDER BY term ASC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [cls._api(r) for r in rows]

    @classmethod
    def update(cls, row_id: str, patch: dict) -> Optional[dict]:
        patch = dict(patch)
        patch["updatedAt"] = _now_ms()
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def get(cls, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.TABLE, row_id, project_id)

    @classmethod
    def delete(cls, row_id: str) -> bool:
        db, found = _locate_db(cls.TABLE, row_id)
        if not found:
            return False
        db.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (row_id,))
        db.commit()
        return True


# ── M2 契约/验收（plan-C §6；事实/意见物理分表 R6） ─────────────────


