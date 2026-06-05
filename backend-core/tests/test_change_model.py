"""Tests for change_tracker.change_model."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
from change_tracker.change_model import (
    ChangeType,
    RiskLevel,
    SymbolChange,
    FileChange,
    DependencyChange,
    ChangeSummary,
    ChangeReport,
    ProjectSnapshot,
)


class TestChangeType:
    def test_values(self):
        assert ChangeType.ADDED.value == "added"
        assert ChangeType.MODIFIED.value == "modified"
        assert ChangeType.REMOVED.value == "removed"


class TestRiskLevel:
    def test_values(self):
        assert RiskLevel.NONE.value == "none"
        assert RiskLevel.HIGH.value == "high"


class TestSymbolChange:
    def test_default_risk_is_none(self):
        sc = SymbolChange(name="foo", kind="function", change_type=ChangeType.ADDED, file_path="/a.ts")
        assert sc.risk == RiskLevel.NONE

    def test_minimal_construction(self):
        sc = SymbolChange(name="foo", kind="function", change_type=ChangeType.ADDED, file_path="/a.ts")
        assert sc.name == "foo"
        assert sc.kind == "function"
        assert sc.change_type == ChangeType.ADDED
        assert sc.file_path == "/a.ts"
        assert sc.old_line is None
        assert sc.new_line is None


class TestFileChange:
    def test_defaults(self):
        fc = FileChange(file_path="/a.ts", change_type=ChangeType.MODIFIED)
        assert fc.symbols_changed == []
        assert fc.lines_added == 0
        assert fc.lines_removed == 0
        assert fc.risk == RiskLevel.NONE

    def test_with_symbols(self):
        sc = SymbolChange(name="bar", kind="class", change_type=ChangeType.MODIFIED, file_path="/a.ts")
        fc = FileChange(file_path="/a.ts", change_type=ChangeType.MODIFIED, symbols_changed=[sc])
        assert len(fc.symbols_changed) == 1
        assert fc.symbols_changed[0].name == "bar"


class TestDependencyChange:
    def test_construction(self):
        dc = DependencyChange(file_path="/a.ts", dependency="lodash", change_type=ChangeType.ADDED)
        assert dc.file_path == "/a.ts"
        assert dc.dependency == "lodash"
        assert dc.change_type == ChangeType.ADDED


class TestChangeSummary:
    def test_defaults(self):
        cs = ChangeSummary()
        assert cs.files_changed == 0
        assert cs.risk_score == 0.0
        assert cs.risk_level == RiskLevel.NONE


class TestChangeReport:
    def test_construction(self):
        report = ChangeReport(from_commit="abc123", to_commit="def456")
        assert report.from_commit == "abc123"
        assert report.to_commit == "def456"
        assert report.files == []
        assert report.dependencies == []

    def test_with_data(self):
        fc = FileChange(file_path="/a.ts", change_type=ChangeType.MODIFIED)
        report = ChangeReport(
            from_commit="abc",
            to_commit="def",
            files=[fc],
        )
        assert len(report.files) == 1
        assert report.files[0].file_path == "/a.ts"


class TestProjectSnapshot:
    def test_construction(self):
        now = datetime.now()
        snap = ProjectSnapshot(commit_hash="abc", timestamp=now)
        assert snap.commit_hash == "abc"
        assert snap.timestamp == now
        assert snap.file_hashes == {}
        assert snap.is_analyzed is False

    def test_with_symbols(self):
        snap = ProjectSnapshot(
            commit_hash="abc",
            timestamp=datetime.now(),
            symbols={"file1.ts": [{"name": "foo", "kind": "function"}]},
        )
        assert len(snap.symbols) == 1
        assert snap.symbols["file1.ts"][0]["name"] == "foo"
