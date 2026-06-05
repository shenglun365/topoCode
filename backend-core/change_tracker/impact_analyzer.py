"""ImpactAnalyzer — 变更影响分析。

对 ChangeReport 中的变更进行递归影响分析：
- 调用链遍历（直接/间接调用者）
- 测试文件匹配
- 影响范围评估
"""

import re
from typing import Optional

from .change_model import ChangeReport, ChangeType, FileChange, RiskLevel


class ImpactAnalyzer:
    def __init__(self, project_root: str, resolver=None):
        self.project_root = project_root
        self._resolver = resolver

    def analyze(self, report: ChangeReport) -> dict:
        impacted_files: set[str] = set()
        test_impacted: set[str] = set()
        high_risk_changes: list[dict] = []

        for fc in report.files:
            file_path = fc.file_path
            impacted_files.add(file_path)

            if self._is_test_file(file_path):
                continue

            if fc.change_type in (ChangeType.MODIFIED, ChangeType.REMOVED):
                if self._has_high_risk_symbol(fc):
                    high_risk_changes.append({
                        "file_path": file_path,
                        "reason": "contains high-risk symbol changes",
                    })

            dependents = self._find_dependents(fc.file_path)
            for dep in dependents:
                impacted_files.add(dep)
                if self._is_test_file(dep):
                    test_impacted.add(dep)

        return {
            "impacted_files": sorted(impacted_files),
            "test_files_impacted": sorted(test_impacted),
            "high_risk_changes": high_risk_changes,
            "impact_count": len(impacted_files),
            "test_impact_count": len(test_impacted),
        }

    def _is_test_file(self, file_path: str) -> bool:
        name = file_path.lower()
        test_patterns = [
            r"(^|[/\\])test_",
            r"(^|[/\\])tests[/\\]",
            r"\.test\.", r"\.spec\.", r"_test\.", r"_spec\.",
            r"(^|[/\\])__tests__[/\\]",
        ]
        return any(re.search(p, name) for p in test_patterns)

    def _has_high_risk_symbol(self, fc: FileChange) -> bool:
        return any(
            sc.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            for sc in fc.symbols_changed
        )

    def _find_dependents(self, file_path: str) -> list[str]:
        if not self._resolver:
            return []
        try:
            result = self._resolver.find_dependents(file_path)
            return result if isinstance(result, list) else []
        except Exception:
            return []
