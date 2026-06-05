"""Tests for change_tracker.impact_analyzer."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from change_tracker.change_model import (
    ChangeReport, FileChange, SymbolChange, ChangeType, RiskLevel,
)
from change_tracker.impact_analyzer import ImpactAnalyzer


class TestImpactAnalyzer:
    def test_empty_report(self):
        report = ChangeReport(from_commit="a", to_commit="b")
        result = ImpactAnalyzer("/tmp").analyze(report)
        assert result["impacted_files"] == []
        assert result["test_files_impacted"] == []

    def test_basic_file_change(self):
        fc = FileChange(file_path="src/main.ts", change_type=ChangeType.MODIFIED)
        report = ChangeReport(from_commit="a", to_commit="b", files=[fc])
        result = ImpactAnalyzer("/tmp").analyze(report)
        assert "src/main.ts" in result["impacted_files"]
        assert result["impact_count"] == 1

    def test_high_risk_symbol_detected(self):
        sc = SymbolChange(
            name="foo", kind="function",
            change_type=ChangeType.MODIFIED,
            file_path="src/main.ts",
            risk=RiskLevel.CRITICAL,
        )
        fc = FileChange(file_path="src/main.ts", change_type=ChangeType.MODIFIED, symbols_changed=[sc])
        report = ChangeReport(from_commit="a", to_commit="b", files=[fc])
        result = ImpactAnalyzer("/tmp").analyze(report)
        assert len(result["high_risk_changes"]) == 1
        assert result["high_risk_changes"][0]["file_path"] == "src/main.ts"

    def test_low_risk_no_high_risk_report(self):
        sc = SymbolChange(
            name="foo", kind="function",
            change_type=ChangeType.MODIFIED,
            file_path="src/main.ts",
            risk=RiskLevel.LOW,
        )
        fc = FileChange(file_path="src/main.ts", change_type=ChangeType.MODIFIED, symbols_changed=[sc])
        report = ChangeReport(from_commit="a", to_commit="b", files=[fc])
        result = ImpactAnalyzer("/tmp").analyze(report)
        assert result["high_risk_changes"] == []

    def test_test_file_identified(self):
        analyzer = ImpactAnalyzer("/tmp")
        assert analyzer._is_test_file("tests/test_app.py") is True
        assert analyzer._is_test_file("src/app.test.ts") is True
        assert analyzer._is_test_file("src/app.spec.ts") is True
        assert analyzer._is_test_file("src/app.py") is False
        assert analyzer._is_test_file("__tests__/app_test.py") is True

    def test_test_file_not_in_impacted(self):
        sc = SymbolChange(
            name="foo", kind="function",
            change_type=ChangeType.MODIFIED,
            file_path="src/main.ts",
            risk=RiskLevel.LOW,
        )
        fc = FileChange(file_path="src/main.ts", change_type=ChangeType.MODIFIED, symbols_changed=[sc])
        report = ChangeReport(from_commit="a", to_commit="b", files=[fc])
        result = ImpactAnalyzer("/tmp").analyze(report)
        assert "src/main.ts" in result["impacted_files"]
