"""组件表存储(ComponentStore): arch_components / arch_component_hierarchy /
arch_component_naming(批B 社区结果 + 批C 快速命名承载)。

自 graph.py 拆分(行数门禁软上限); 消费方兼容: store.graph 重导出。

Run: cd <repo> && python -m pytest apps/architect/tests/test_graph_collect.py -q
"""
import json
import time
from typing import Dict, List, Optional

from .base import _fetchall_routed, _target_db


def _now() -> int:
    return int(time.time() * 1000)


class ComponentStore:
    """arch_components / arch_component_hierarchy（批B 社区结果承载，A1 先建）。"""

    TABLE = "arch_components"

    @classmethod
    def replace_rev(cls, project_id: str, rev: str,
                    components: List[dict], hierarchy: List[dict]) -> dict:
        db = _target_db(cls.TABLE, project_id)
        now = _now()
        c_rows = []
        for c in components or []:
            if not (c or {}).get("id"):
                continue
            c_rows.append((
                project_id, rev, c["id"], c.get("name") or "",
                c.get("summary") or "",
                json.dumps(c.get("owns") or [], ensure_ascii=False),
                c.get("source") or "community", now, now,
            ))
        h_rows = []
        for h in hierarchy or []:
            cid = (h or {}).get("childId") or (h or {}).get("child_id") or ""
            if not cid:
                continue
            h_rows.append((project_id, rev, cid,
                           h.get("parentId") or h.get("parent_id") or "",
                           int(h.get("level") or 0)))
        db.execute("DELETE FROM arch_components WHERE project_id=? AND rev=?",
                   (project_id, rev))
        db.execute("DELETE FROM arch_component_hierarchy WHERE project_id=? AND rev=?",
                   (project_id, rev))
        if c_rows:
            db.executemany(
                "INSERT INTO arch_components (project_id, rev, id, name, summary, "
                "owns, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                c_rows)
        if h_rows:
            db.executemany(
                "INSERT INTO arch_component_hierarchy (project_id, rev, child_id, "
                "parent_id, level) VALUES (?,?,?,?,?)",
                h_rows)
        db.commit()
        return {"components": len(c_rows), "hierarchy": len(h_rows)}

    @classmethod
    def list_rev(cls, project_id: str, rev: str) -> List[dict]:
        """目录形状（catalog 最小消费形状 {id,name,owns,parentId} 直配接缝）。"""
        rows, _ = _fetchall_routed(
            cls.TABLE,
            "SELECT c.*, h.parent_id AS parent_id, h.level AS level FROM arch_components c "
            "LEFT JOIN arch_component_hierarchy h ON h.project_id = c.project_id "
            "AND h.rev = c.rev AND h.child_id = c.id "
            "WHERE c.project_id=? AND c.rev=? ORDER BY c.id",
            (project_id, rev), project_id or None)
        out = []
        for r in rows:
            try:
                owns = json.loads(r.get("owns") or "[]")
            except Exception:  # noqa: BLE001
                owns = []
            out.append({
                "id": r["id"], "name": r.get("name") or "",
                "summary": r.get("summary") or "", "owns": owns,
                "parentId": r.get("parent_id") or "",
                "level": int(r.get("level") or 0),
                "source": r.get("source") or "community",
            })
        return out

    @classmethod
    def latest_rev(cls, project_id: str) -> str:
        """最近一次写入组件结果的 rev（无则 ''）。"""
        rows, _ = _fetchall_routed(
            cls.TABLE,
            "SELECT rev, MAX(updated_at) AS ts FROM arch_components "
            "WHERE project_id=? GROUP BY rev ORDER BY ts DESC LIMIT 1",
            (project_id,), project_id or None)
        return (rows[0] or {}).get("rev") or "" if rows else ""

    @classmethod
    def prune_old_revs(cls, project_id: str, keep: int = 2) -> int:
        """修剪旧快照(数据主权批E): 按写入时间保留最近 keep 个 rev(当前+DIFF
        基准), 更旧的组件/层级/命名行清理。图快照(graph_node/edge)由
        GraphStore.prune_old_revs 同步修剪。返回删除组件行数。"""
        db = _target_db(cls.TABLE, project_id)
        rows = db.fetchall(
            "SELECT rev FROM arch_components WHERE project_id=?"
            " GROUP BY rev ORDER BY MAX(updated_at) DESC LIMIT -1 OFFSET ?",
            (project_id, keep))
        stale = [r["rev"] for r in (rows or [])]
        n = 0
        for rev in stale:
            for t in ("arch_components", "arch_component_hierarchy", "arch_component_naming"):
                cur = db.execute(f"DELETE FROM {t} WHERE project_id=? AND rev=?",
                                 (project_id, rev))
                n += cur.rowcount or 0
        db.commit()
        return n


    # ── 快速命名(批C) ─────────────────────────────────────────────

    @classmethod
    def upsert_naming(cls, project_id: str, rev: str,
                      items: List[dict], model_id: str,
                      fingerprints: Optional[Dict[str, str]] = None) -> int:
        """批量写命名结果(arch_component_naming) + 回写组件名/概要。

        items: [{componentId, name, summary}]；fingerprints: cid→owns 指纹。
        """
        db = _target_db(cls.TABLE, project_id)
        now = _now()
        rows = []
        for it in items or []:
            cid = (it or {}).get("componentId") or ""
            if not cid or not (it.get("name") or "").strip():
                continue
            rows.append((
                project_id, rev, cid, (it.get("name") or "").strip(),
                (it.get("summary") or "").strip(), model_id or "",
                "active", (fingerprints or {}).get(cid, ""), now, now,
            ))
        if not rows:
            return 0
        db.executemany(
            "INSERT INTO arch_component_naming (project_id, rev, component_id, "
            "name, summary, model_id, status, fingerprint, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(project_id, rev, component_id) DO UPDATE SET "
            "name=excluded.name, summary=excluded.summary, model_id=excluded.model_id, "
            "status='active', "
            "fingerprint=COALESCE(NULLIF(excluded.fingerprint,''), arch_component_naming.fingerprint), "
            "updated_at=excluded.updated_at", rows)
        for r in rows:
            db.execute(
                "UPDATE arch_components SET name=?, summary=?, updated_at=? "
                "WHERE project_id=? AND rev=? AND id=?",
                (r[3], r[4], now, project_id, rev, r[2]))
        db.commit()
        return len(rows)

    @classmethod
    def backfill_names(cls, project_id: str, rev: str) -> int:
        """把已有 active 命名回写组件表(幂等兜底)。

        场景: community-group 的 replace_rev 会把组件 name 重置回 id; 若命名
        缓存命中跳过 llm(不 upsert), 组件名停留在 id——分组后/命名前任何
        消费方都会读到裸 id。入口统一回补一次。返回回写行数。"""
        db = _target_db(cls.TABLE, project_id)
        cur = db.execute(
            "UPDATE arch_components SET "
            "name=(SELECT n.name FROM arch_component_naming n "
            "      WHERE n.project_id=arch_components.project_id "
            "      AND n.rev=arch_components.rev AND n.component_id=arch_components.id "
            "      AND n.status='active'), "
            "summary=(SELECT n.summary FROM arch_component_naming n "
            "      WHERE n.project_id=arch_components.project_id "
            "      AND n.rev=arch_components.rev AND n.component_id=arch_components.id "
            "      AND n.status='active'), "
            "updated_at=updated_at "
            "WHERE project_id=? AND rev=? AND id IN "
            "(SELECT component_id FROM arch_component_naming "
            " WHERE project_id=? AND rev=? AND status='active' AND name!='')",
            (project_id, rev, project_id, rev))
        db.commit()
        return cur.rowcount or 0

    @classmethod
    def namings(cls, project_id: str, rev: str) -> Dict[str, dict]:
        """rev 内全部命名 → {componentId: {name, summary, fingerprint, status}}。"""
        rows, _ = _fetchall_routed(
            "arch_component_naming",
            "SELECT * FROM arch_component_naming WHERE project_id=? AND rev=?",
            (project_id, rev), project_id or None)
        return {r["component_id"]: {
            "componentId": r["component_id"], "name": r.get("name") or "",
            "summary": r.get("summary") or "",
            "fingerprint": r.get("fingerprint") or "",
            "status": r.get("status") or "active", "modelId": r.get("model_id") or "",
        } for r in rows}

    @classmethod
    def mark_stale(cls, project_id: str, rev: str,
                   component_ids: Optional[List[str]] = None) -> int:
        """命名置 stale(owns/rev 变化后)；component_ids 缺省=全部。"""
        db = _target_db(cls.TABLE, project_id)
        if component_ids:
            ph = ",".join("?" * len(component_ids))
            cur = db.execute(
                f"UPDATE arch_component_naming SET status='stale', updated_at=? "
                f"WHERE project_id=? AND rev=? AND component_id IN ({ph})",
                (_now(), project_id, rev, *component_ids))
        else:
            cur = db.execute(
                "UPDATE arch_component_naming SET status='stale', updated_at=? "
                "WHERE project_id=? AND rev=?",
                (_now(), project_id, rev))
        db.commit()
        return cur.rowcount if cur else 0
