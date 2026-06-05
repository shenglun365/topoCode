"""Tests for change_tracker.git_adapter."""

import sys
import os
import tempfile
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from change_tracker.git_adapter import GitAdapter


def _init_git_repo(path: str):
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)


def _commit_file(path: str, rel_path: str, content: str, msg: str):
    full = os.path.join(path, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=path, capture_output=True)


class TestGitAdapter:
    def test_is_available_in_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _commit_file(tmp, "readme.md", "# Hello", "init")
            adapter = GitAdapter(tmp)
            assert adapter.is_available() is True

    def test_is_not_available_outside_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = GitAdapter(tmp)
            assert adapter.is_available() is False

    def test_get_current_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _commit_file(tmp, "a.txt", "hello", "first")
            adapter = GitAdapter(tmp)
            commit = adapter.get_current_commit()
            assert commit is not None
            assert len(commit) == 40

    def test_get_current_commit_no_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = GitAdapter(tmp)
            assert adapter.get_current_commit() is None

    def test_get_commit_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _commit_file(tmp, "a.txt", "v1", "first")
            _commit_file(tmp, "b.txt", "v2", "second")
            adapter = GitAdapter(tmp)
            history = adapter.get_commit_history(max_count=10)
            assert len(history) == 2
            assert history[0]["message"] == "second"
            assert history[1]["message"] == "first"

    def test_get_changed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _commit_file(tmp, "a.txt", "v1", "first")
            _commit_file(tmp, "b.txt", "v2", "second")
            adapter = GitAdapter(tmp)
            files = adapter.get_changed_files("HEAD~1")
            assert len(files) == 1
            assert files[0]["file_path"] == "b.txt"
            assert files[0]["change_type"] == "added"

    def test_get_diff_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _commit_file(tmp, "a.txt", "hello\nworld\n", "first")
            _commit_file(tmp, "b.txt", "new\nfile\n", "second")
            adapter = GitAdapter(tmp)
            stats = adapter.get_diff_stats("HEAD~1")
            assert stats["files_changed"] >= 1
            assert stats["insertions"] >= 2

    def test_file_content_at_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _commit_file(tmp, "a.txt", "hello world", "first")
            adapter = GitAdapter(tmp)
            content = adapter.file_content_at_commit("a.txt")
            assert content == "hello world"

    def test_file_content_at_commit_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _commit_file(tmp, "a.txt", "hello", "first")
            adapter = GitAdapter(tmp)
            assert adapter.file_content_at_commit("nonexistent.ts") is None

    def test_get_changed_files_no_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = GitAdapter(tmp)
            assert adapter.get_changed_files("abc") == []

    def test_get_diff_stats_no_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = GitAdapter(tmp)
            stats = adapter.get_diff_stats("abc")
            assert stats["files_changed"] == 0
