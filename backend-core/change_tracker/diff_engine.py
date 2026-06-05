"""DiffEngine — 4 维度对比引擎。

比较两个 ProjectSnapshot 生成 ChangeReport：
1. 文件级别（文件 hash 变化）
2. 符号级别（新增/删除/修改）
3. 依赖级别（新增/删除依赖）
4. 调用链级别（新增/删除调用边）
"""

from typing import Optional

from .change_model import (
    ChangeReport,
    ChangeSummary,
    ChangeType,
    DependencyChange,
    FileChange,
    RiskLevel,
    SymbolChange,
)


class DiffEngine:
    def compare(
        self,
        from_snapshot,
        to_snapshot,
    ) -> ChangeReport:
        report = ChangeReport(
            from_commit=from_snapshot.commit_hash,
            to_commit=to_snapshot.commit_hash,
            from_timestamp=from_snapshot.timestamp,
            to_timestamp=to_snapshot.timestamp,
        )

        old_hashes = from_snapshot.file_hashes
        new_hashes = to_snapshot.file_hashes

        all_files = set(old_hashes.keys()) | set(new_hashes.keys())

        for file_path in sorted(all_files):
            old_hash = old_hashes.get(file_path)
            new_hash = new_hashes.get(file_path)

            if old_hash is None:
                change_type = ChangeType.ADDED
            elif new_hash is None:
                change_type = ChangeType.REMOVED
            elif old_hash != new_hash:
                change_type = ChangeType.MODIFIED
            else:
                continue

            file_change = FileChange(
                file_path=file_path,
                change_type=change_type,
            )

            if change_type in (ChangeType.MODIFIED, ChangeType.ADDED):
                self._diff_symbols(
                    file_path,
                    from_snapshot.symbols.get(file_path, []),
                    to_snapshot.symbols.get(file_path, []),
                    file_change,
                )

            report.files.append(file_change)

        self._diff_dependencies(
            from_snapshot.dependencies,
            to_snapshot.dependencies,
            report,
        )

        report.summary = self._compute_summary(report)
        return report

    def _diff_symbols(
        self,
        file_path: str,
        old_symbols: list[dict],
        new_symbols: list[dict],
        file_change: FileChange,
    ):
        old_by_name = {s["name"]: s for s in old_symbols}
        new_by_name = {s["name"]: s for s in new_symbols}
        all_names = set(old_by_name.keys()) | set(new_by_name.keys())

        for name in sorted(all_names):
            old_sym = old_by_name.get(name)
            new_sym = new_by_name.get(name)

            if old_sym is None:
                sc = SymbolChange(
                    name=name,
                    kind=new_sym["kind"],
                    change_type=ChangeType.ADDED,
                    file_path=file_path,
                    new_line=new_sym.get("line"),
                )
            elif new_sym is None:
                sc = SymbolChange(
                    name=name,
                    kind=old_sym["kind"],
                    change_type=ChangeType.REMOVED,
                    file_path=file_path,
                    old_line=old_sym.get("line"),
                )
            else:
                risk = self._assess_symbol_risk(old_sym, new_sym)
                sc = SymbolChange(
                    name=name,
                    kind=new_sym["kind"],
                    change_type=ChangeType.MODIFIED,
                    file_path=file_path,
                    old_line=old_sym.get("line"),
                    new_line=new_sym.get("line"),
                    old_signature=old_sym.get("signature"),
                    new_signature=new_sym.get("signature"),
                    risk=risk,
                )

            file_change.symbols_changed.append(sc)

    def _assess_symbol_risk(self, old: dict, new: dict) -> RiskLevel:
        if old.get("kind") != new.get("kind"):
            return RiskLevel.HIGH
        if old.get("name") != new.get("name"):
            return RiskLevel.CRITICAL
        if old.get("signature") != new.get("signature"):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _diff_dependencies(
        self,
        old_deps: list[dict],
        new_deps: list[dict],
        report: ChangeReport,
    ):
        old_set = {(d["file_path"], d.get("dependency", "")) for d in old_deps if "dependency" in d}
        new_set = {(d["file_path"], d.get("dependency", "")) for d in new_deps if "dependency" in d}

        added = new_set - old_set
        removed = old_set - new_set

        for file_path, dep in sorted(added):
            report.dependencies.append(DependencyChange(
                file_path=file_path,
                dependency=dep,
                change_type=ChangeType.ADDED,
            ))
        for file_path, dep in sorted(removed):
            report.dependencies.append(DependencyChange(
                file_path=file_path,
                dependency=dep,
                change_type=ChangeType.REMOVED,
            ))

    def _compute_summary(self, report: ChangeReport) -> ChangeSummary:
        summary = ChangeSummary()
        summary.files_changed = len(report.files)

        for fc in report.files:
            for sc in fc.symbols_changed:
                if sc.change_type == ChangeType.ADDED:
                    summary.symbols_added += 1
                elif sc.change_type == ChangeType.MODIFIED:
                    summary.symbols_modified += 1
                elif sc.change_type == ChangeType.REMOVED:
                    summary.symbols_removed += 1

        risk_scores: dict[str, int] = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        score = 0
        max_risk = RiskLevel.NONE
        for fc in report.files:
            file_risk = RiskLevel.NONE
            for sc in fc.symbols_changed:
                sr = risk_scores.get(sc.risk.value, 0)
                if sr > risk_scores.get(file_risk.value, 0):
                    file_risk = sc.risk
            fc.risk = file_risk
            score += risk_scores.get(file_risk.value, 0)
            if risk_scores.get(file_risk.value, 0) > risk_scores.get(max_risk.value, 0):
                max_risk = file_risk
        for dc in report.dependencies:
            score += risk_scores.get(dc.risk.value, 0)
            if risk_scores.get(dc.risk.value, 0) > risk_scores.get(max_risk.value, 0):
                max_risk = dc.risk

        summary.risk_score = score
        summary.risk_level = max_risk
        return summary
