"""Tests for change_tracker.snapshot_store."""

import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
from change_tracker.snapshot_store import SnapshotStore, VERSION_LIMIT
from change_tracker.change_model import ProjectSnapshot


class TestSnapshotStore:
    def test_init_creates_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            assert os.path.exists(db_path)

    def test_save_and_get_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            snap = ProjectSnapshot(
                commit_hash="abc123",
                timestamp=datetime(2025, 1, 1, 12, 0, 0),
                file_hashes={"src/main.ts": "hash1"},
                is_analyzed=True,
            )
            store.save_snapshot(tmp, snap)

            retrieved = store.get_snapshot(tmp, "abc123")
            assert retrieved is not None
            assert retrieved.commit_hash == "abc123"
            assert retrieved.file_hashes == {"src/main.ts": "hash1"}
            assert retrieved.is_analyzed is True

    def test_get_nonexistent_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            assert store.get_snapshot(tmp, "nope") is None

    def test_latest_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            snap1 = ProjectSnapshot(commit_hash="aaa", timestamp=datetime(2025, 1, 1))
            snap2 = ProjectSnapshot(commit_hash="bbb", timestamp=datetime(2025, 1, 2))
            store.save_snapshot(tmp, snap1)
            store.save_snapshot(tmp, snap2)
            latest = store.get_latest_snapshot(tmp)
            assert latest is not None
            assert latest.commit_hash == "bbb"

    def test_list_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            store.save_snapshot(tmp, ProjectSnapshot(commit_hash="a", timestamp=datetime(2025, 1, 1)))
            store.save_snapshot(tmp, ProjectSnapshot(commit_hash="b", timestamp=datetime(2025, 1, 2)))
            snaps = store.list_snapshots(tmp)
            assert len(snaps) == 2
            assert snaps[0]["commit_hash"] == "b"

    def test_delete_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            store.save_snapshot(tmp, ProjectSnapshot(commit_hash="abc", timestamp=datetime(2025, 1, 1)))
            assert store.delete_snapshot(tmp, "abc") is True
            assert store.get_snapshot(tmp, "abc") is None

    def test_delete_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            assert store.delete_snapshot(tmp, "nope") is False

    def test_enforces_version_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            for i in range(VERSION_LIMIT + 5):
                store.save_snapshot(
                    tmp,
                    ProjectSnapshot(commit_hash=f"c{i:03d}", timestamp=datetime(2025, 1, 1, 12, 0, i)),
                )
            snaps = store.list_snapshots(tmp, max_count=100)
            assert len(snaps) == VERSION_LIMIT

    def test_has_file_changed_no_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            assert store.has_file_changed(tmp, "src/main.ts", "somehash") is True

    def test_has_file_changed_same_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            store.save_snapshot(
                tmp,
                ProjectSnapshot(
                    commit_hash="c1",
                    timestamp=datetime(2025, 1, 1),
                    file_hashes={"src/main.ts": "hash1"},
                ),
            )
            assert store.has_file_changed(tmp, "src/main.ts", "hash1") is False
            assert store.has_file_changed(tmp, "src/main.ts", "hash2") is True

    def test_different_project_roots_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "snapshots.db")
            store = SnapshotStore(db_path)
            store.save_snapshot("/proj1", ProjectSnapshot(commit_hash="a", timestamp=datetime(2025, 1, 1)))
            store.save_snapshot("/proj2", ProjectSnapshot(commit_hash="a", timestamp=datetime(2025, 1, 1)))
            assert len(store.list_snapshots("/proj1")) == 1
            assert len(store.list_snapshots("/proj2")) == 1
