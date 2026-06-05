"""GitAdapter — Git 集成适配器。

提供提交历史查询、文件变更列表和差异统计。
"""

import logging
import os
import subprocess
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class GitAdapter:
    def __init__(self, project_root: str):
        self.project_root = project_root

    def _run(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", self.project_root, *args],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.warning("Git command failed: %s\n%s", " ".join(args), e.stderr)
            return ""
        except FileNotFoundError:
            logger.warning("Git not found on system PATH")
            return ""

    def is_available(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "-C", self.project_root, "rev-parse", "--git-dir"],
                capture_output=True, text=True, check=True, timeout=10,
            )
            return bool(result.stdout.strip())
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def get_current_commit(self) -> Optional[str]:
        commit = self._run("rev-parse", "HEAD")
        return commit if commit else None

    def get_commit_history(self, max_count: int = 20) -> list[dict]:
        output = self._run(
            "log", f"--max-count={max_count}",
            "--format=%H||%ct||%s||%an",
        )
        if not output:
            return []
        commits = []
        for line in output.split("\n"):
            parts = line.split("||", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0],
                    "timestamp": datetime.fromtimestamp(int(parts[1])).isoformat(),
                    "message": parts[2],
                    "author": parts[3],
                })
        return commits

    def get_changed_files(self, from_commit: str, to_commit: str = "HEAD") -> list[dict]:
        output = self._run("diff", "--name-status", f"{from_commit}..{to_commit}")
        if not output:
            return []
        files = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                status_code = parts[0]
                file_path = parts[1]
                change_type = {
                    "A": "added",
                    "M": "modified",
                    "D": "removed",
                    "R": "renamed",
                    "C": "copied",
                }.get(status_code[0], "unknown")
                files.append({"file_path": file_path, "change_type": change_type})
        return files

    def get_diff_stats(self, from_commit: str, to_commit: str = "HEAD") -> dict:
        output = self._run("diff", "--shortstat", f"{from_commit}..{to_commit}")
        if not output:
            return {"files_changed": 0, "insertions": 0, "deletions": 0}
        parts = output.replace(",", "").split()
        stats = {"files_changed": 0, "insertions": 0, "deletions": 0}
        for i, p in enumerate(parts):
            clean = p.split("(")[0].strip()
            if clean == "file" or clean == "files":
                stats["files_changed"] = int(parts[i - 1])
            elif clean == "insertion" or clean == "insertions":
                stats["insertions"] = int(parts[i - 1])
            elif clean == "deletion" or clean == "deletions":
                stats["deletions"] = int(parts[i - 1])
        return stats

    def file_content_at_commit(self, file_path: str, commit: str = "HEAD") -> Optional[str]:
        return self._run("show", f"{commit}:{file_path}") or None
