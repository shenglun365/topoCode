"""Tests for change_tracker.diff_engine."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
from change_tracker.change_model import (
    ChangeType, ProjectSnapshot,
)
from change_tracker.diff_engine import DiffEngine


def _snapshot(commit: str, file_hashes=None, symbols=None, dependencies=None):
    return ProjectSnapshot(
        commit_hash=commit,
        timestamp=datetime(2025, 1, 1),
        file_hashes=file_hashes or {},
        symbols=symbols or {},
        dependencies=dependencies or [],
        is_analyzed=True,
    )


class TestDiffEngine:
    def test_no_changes(self):
        old = _snapshot("a", {"f1.ts": "h1"})
        new = _snapshot("b", {"f1.ts": "h1"})
        report = DiffEngine().compare(old, new)
        assert len(report.files) == 0
        assert report.summary.files_changed == 0

    def test_file_added(self):
        old = _snapshot("a", {})
        new = _snapshot("b", {"f1.ts": "h1"})
        report = DiffEngine().compare(old, new)
        assert len(report.files) == 1
        assert report.files[0].change_type == ChangeType.ADDED

    def test_file_removed(self):
        old = _snapshot("a", {"f1.ts": "h1"})
        new = _snapshot("b", {})
        report = DiffEngine().compare(old, new)
        assert len(report.files) == 1
        assert report.files[0].change_type == ChangeType.REMOVED

    def test_file_modified(self):
        old = _snapshot("a", {"f1.ts": "h1"})
        new = _snapshot("b", {"f1.ts": "h2"})
        report = DiffEngine().compare(old, new)
        assert len(report.files) == 1
        assert report.files[0].change_type == ChangeType.MODIFIED

    def test_symbol_added(self):
        old = _snapshot("a", {"f1.ts": "h1"})
        new = _snapshot("b", {"f1.ts": "h2"}, symbols={
            "f1.ts": [{"name": "foo", "kind": "function", "line": 1}],
        })
        report = DiffEngine().compare(old, new)
        assert len(report.files) == 1
        assert len(report.files[0].symbols_changed) == 1
        sc = report.files[0].symbols_changed[0]
        assert sc.name == "foo"
        assert sc.change_type == ChangeType.ADDED

    def test_symbol_removed(self):
        old = _snapshot("a", {"f1.ts": "h1"}, symbols={
            "f1.ts": [{"name": "foo", "kind": "function", "line": 1}],
        })
        new = _snapshot("b", {"f1.ts": "h2"})
        report = DiffEngine().compare(old, new)
        assert len(report.files[0].symbols_changed) == 1
        assert report.files[0].symbols_changed[0].change_type == ChangeType.REMOVED

    def test_symbol_modified(self):
        old = _snapshot("a", {"f1.ts": "h1"}, symbols={
            "f1.ts": [{"name": "foo", "kind": "function", "line": 1}],
        })
        new = _snapshot("b", {"f1.ts": "h2"}, symbols={
            "f1.ts": [{"name": "foo", "kind": "function", "line": 5}],
        })
        report = DiffEngine().compare(old, new)
        sc = report.files[0].symbols_changed[0]
        assert sc.change_type == ChangeType.MODIFIED

    def test_symbol_kind_change_high_risk(self):
        old = _snapshot("a", {"f1.ts": "h1"}, symbols={
            "f1.ts": [{"name": "foo", "kind": "function", "line": 1}],
        })
        new = _snapshot("b", {"f1.ts": "h2"}, symbols={
            "f1.ts": [{"name": "foo", "kind": "class", "line": 1}],
        })
        report = DiffEngine().compare(old, new)
        sc = report.files[0].symbols_changed[0]
        assert sc.risk.value == "high"

    def test_summary_counts(self):
        old = _snapshot("a", {"f1.ts": "h1", "f2.ts": "h2"}, symbols={
            "f1.ts": [{"name": "a", "kind": "function", "line": 1}],
        })
        new = _snapshot("b", {"f1.ts": "h2", "f3.ts": "h3"}, symbols={
            "f1.ts": [{"name": "a", "kind": "function", "line": 5}],
            "f3.ts": [{"name": "b", "kind": "class", "line": 1}],
        })
        report = DiffEngine().compare(old, new)
        # f1: modified (symbol modified), f2: removed, f3: added (symbol added)
        assert report.summary.files_changed == 3
        assert report.summary.symbols_added == 1  # b
        assert report.summary.symbols_removed == 0  # nothing removed (a was just modified)
        assert report.summary.symbols_modified == 1  # a

    def test_dependency_added(self):
        old = _snapshot("a", {"f1.ts": "h1"}, dependencies=[])
        new = _snapshot("b", {"f1.ts": "h1"}, dependencies=[
            {"file_path": "f1.ts", "dependency": "lodash"},
        ])
        report = DiffEngine().compare(old, new)
        assert len(report.dependencies) == 1
        assert report.dependencies[0].change_type == ChangeType.ADDED

    def test_dependency_removed(self):
        old = _snapshot("a", {"f1.ts": "h1"}, dependencies=[
            {"file_path": "f1.ts", "dependency": "lodash"},
        ])
        new = _snapshot("b", {"f1.ts": "h1"}, dependencies=[])
        report = DiffEngine().compare(old, new)
        assert len(report.dependencies) == 1
        assert report.dependencies[0].change_type == ChangeType.REMOVED

    def test_risk_level_computed(self):
        old = _snapshot("a", {"f1.ts": "h1"}, symbols={
            "f1.ts": [{"name": "foo", "kind": "function", "line": 1}],
        })
        new = _snapshot("b", {"f1.ts": "h2"}, symbols={
            "f1.ts": [{"name": "foo", "kind": "class", "line": 1}],
        })
        report = DiffEngine().compare(old, new)
        assert report.summary.risk_score > 0
        assert report.summary.risk_level.value == "high"

    def test_report_commits(self):
        old = _snapshot("abc123", {})
        new = _snapshot("def456", {})
        report = DiffEngine().compare(old, new)
        assert report.from_commit == "abc123"
        assert report.to_commit == "def456"
