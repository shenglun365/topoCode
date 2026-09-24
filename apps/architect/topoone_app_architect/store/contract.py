"""store 拆分模块（A1-T3：纯移动）。"""
from __future__ import annotations

from .base import _delete, _fetchall_routed, _get, _insert, _now_ms, _row_to_api, _update

class ContractItemStore:
    """契约条目（ci-{seq} 项目内自增；状态机 draft→confirmed→injected→verifying→accepted|rejected）。"""

    TABLE = "arch_contract_items"

    @classmethod
    def next_seq(cls, project_id: str) -> int:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT MAX(seq) AS s FROM {cls.TABLE} WHERE project_id = ?",
            (project_id,), project_id or None)
        s = rows[0].get("s") if rows else None
        return int(s or 0) + 1

    @classmethod
    def create(cls, project_id: str, item: dict, author: str = "") -> dict:
        """item: {reqId?, convId?, origin?, kind, level?, target?, intentOnly?,
        behavior?, zAxis?, acceptance?} → draft 条目。"""
        now = _now_ms()
        seq = cls.next_seq(project_id)
        data = {"id": f"ci-{seq}", "projectId": project_id, "seq": seq,
                "reqId": item.get("reqId") or "", "convId": item.get("convId") or "",
                "origin": item.get("origin") or {},
                "kind": item["kind"], "level": item.get("level") or "implementation",
                "target": item.get("target") or {},
                "intentOnly": 1 if item.get("intentOnly") else 0,
                "behavior": item.get("behavior") or {},
                "zAxis": item.get("zAxis") or [],
                "acceptance": item.get("acceptance") or {},
                "status": "draft", "staleByFramework": 0, "version": 1,
                "createdBy": author, "createdAt": now,
                "confirmedAt": 0, "injectedAt": 0, "verifiedAt": 0}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def get(cls, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.TABLE, row_id, project_id)

    @classmethod
    def list(cls, project_id: str, status: str = "", req_id: str = "",
             limit: int = 500) -> list[dict]:
        conds = ["project_id = ?"]
        params: list = [project_id]
        if status:
            conds.append("status = ?")
            params.append(status)
        if req_id:
            conds.append("req_id = ?")
            params.append(req_id)
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
            f"ORDER BY seq ASC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def update(cls, row_id: str, patch: dict) -> Optional[dict]:
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def set_status(cls, row_id: str, status: str, ts_field: str = "") -> Optional[dict]:
        """状态迁移 + 时间戳列（confirmed_at/injected_at/verified_at）。"""
        patch: dict = {"status": status}
        if ts_field in ("confirmed_at", "injected_at", "verified_at"):
            patch[ts_field] = _now_ms()
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def delete(cls, row_id: str) -> bool:
        return _delete(cls.TABLE, row_id)




class ContractPackageStore:
    """契约包（cp-{seq}；注入 runner 的单元，框架快照随行冻结）。"""

    TABLE = "arch_contract_packages"

    @classmethod
    def next_seq(cls, project_id: str) -> int:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT MAX(seq) AS s FROM {cls.TABLE} WHERE project_id = ?",
            (project_id,), project_id or None)
        s = rows[0].get("s") if rows else None
        return int(s or 0) + 1

    @classmethod
    def create(cls, project_id: str, framework_snapshot: dict, item_ids: list,
               asset_refs: Optional[list] = None,
               component_refs: Optional[list] = None,
               agents_md: str = "") -> dict:
        seq = cls.next_seq(project_id)
        data = {"id": f"cp-{seq}", "projectId": project_id, "seq": seq,
                "frameworkSnapshot": framework_snapshot,
                "itemIds": item_ids, "assetRefs": asset_refs or [],
                "componentRefs": component_refs or [],
                "agentsMd": agents_md, "status": "created",
                "injectedTo": "", "createdAt": _now_ms(), "injectedAt": 0}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def get(cls, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.TABLE, row_id, project_id)

    @classmethod
    def list(cls, project_id: str, limit: int = 100) -> list[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE project_id = ? "
            f"ORDER BY seq DESC LIMIT ?",
            (project_id, int(limit)), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def update(cls, row_id: str, patch: dict) -> Optional[dict]:
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def mark_injected(cls, row_id: str, injected_to: str = "") -> Optional[dict]:
        return _update(cls.TABLE, row_id,
                       {"status": "injected", "injectedTo": injected_to,
                        "injectedAt": _now_ms()})




class AcceptanceStore:
    """验收报告 + facts + opinions（报告 ar-{seq}；facts/opinions 无 seq，时间戳 id）。"""

    REPORTS = "arch_acceptance_reports"
    FACTS = "arch_acceptance_facts"
    OPINIONS = "arch_acceptance_opinions"

    @classmethod
    def next_report_seq(cls, project_id: str) -> int:
        rows, _ = _fetchall_routed(
            cls.REPORTS,
            f"SELECT MAX(seq) AS s FROM {cls.REPORTS} WHERE project_id = ?",
            (project_id,), project_id or None)
        s = rows[0].get("s") if rows else None
        return int(s or 0) + 1

    @classmethod
    def create_report(cls, project_id: str, package_id: str,
                      trigger_info: dict, profile: str = "strict") -> dict:
        seq = cls.next_report_seq(project_id)
        data = {"id": f"ar-{seq}", "projectId": project_id, "seq": seq,
                "packageId": package_id,
                "triggerInfo": trigger_info, "extractionProfile": profile,
                "summary": {}, "createdAt": _now_ms()}
        _insert(cls.REPORTS, data)
        return data

    @classmethod
    def get_report(cls, report_id: str,
                   project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.REPORTS, report_id, project_id)

    @classmethod
    def list_reports(cls, project_id: str, package_id: str = "",
                     limit: int = 100) -> list[dict]:
        conds = ["project_id = ?"]
        params: list = [project_id]
        if package_id:
            conds.append("package_id = ?")
            params.append(package_id)
        rows, _ = _fetchall_routed(
            cls.REPORTS,
            f"SELECT * FROM {cls.REPORTS} WHERE {' AND '.join(conds)} "
            f"ORDER BY seq DESC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def update_summary(cls, report_id: str, summary: dict) -> Optional[dict]:
        return _update(cls.REPORTS, report_id, {"summary": summary})

    @classmethod
    def add_fact(cls, project_id: str, report_id: str, item_id: str,
                 check_layer: str, verdict: str, evidence: dict) -> dict:
        data = {"id": f"af-{_now_ms()}-{abs(hash((report_id, item_id, check_layer))) % 10 ** 6}",
                "projectId": project_id, "reportId": report_id, "itemId": item_id,
                "checkLayer": check_layer, "verdict": verdict,
                "evidence": evidence or {}, "createdAt": _now_ms()}
        _insert(cls.FACTS, data)
        return data

    @classmethod
    def add_opinion(cls, project_id: str, report_id: str, item_id: str,
                    text: str, confidence: float, model: str,
                    evidence: dict, trigger_by: str = "") -> dict:
        data = {"id": f"ao-{_now_ms()}-{abs(hash((report_id, item_id, text[:64]))) % 10 ** 6}",
                "projectId": project_id, "reportId": report_id, "itemId": item_id,
                "text": text, "confidence": confidence, "model": model,
                "evidence": evidence or {}, "triggerBy": trigger_by,
                "createdAt": _now_ms()}
        _insert(cls.OPINIONS, data)
        return data

    @classmethod
    def report_detail(cls, report_id: str,
                      project_id: Optional[str] = None) -> Optional[dict]:
        report = _get(cls.REPORTS, report_id, project_id)
        if report is None:
            return None
        pid = report.get("projectId") or project_id
        facts, _ = _fetchall_routed(
            cls.FACTS,
            f"SELECT * FROM {cls.FACTS} WHERE project_id = ? AND report_id = ? "
            f"ORDER BY created_at ASC", (pid, report_id), pid or None)
        opinions, _ = _fetchall_routed(
            cls.OPINIONS,
            f"SELECT * FROM {cls.OPINIONS} WHERE project_id = ? AND report_id = ? "
            f"ORDER BY created_at ASC", (pid, report_id), pid or None)
        return {"report": _row_to_api(report),
                "facts": [_row_to_api(r) for r in facts],
                "opinions": [_row_to_api(r) for r in opinions]}

