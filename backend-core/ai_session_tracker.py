"""AISessionTracker — AI 编码会话追踪。

追踪 AI coding agent 在项目中的活动，生成结构化摘要和质检查报告。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FileSnapshot:
    path: str
    mtime: float
    sha256: str
    symbol_count: int = 0


@dataclass
class ChangeRecord:
    file_path: str
    change_type: str  # added, modified, deleted
    symbols_added: list[str] = field(default_factory=list)
    symbols_modified: list[str] = field(default_factory=list)
    symbols_deleted: list[str] = field(default_factory=list)


@dataclass
class QualityIssue:
    file_path: str
    line_number: int
    issue_type: str
    severity: str  # HIGH, MEDIUM, LOW, INFO
    title: str
    description: str = ""
    suggestion: str = ""


class AISessionTracker:
    """追踪 AI coding agent 的活动。

    用法:
        tracker = AISessionTracker(project_root, store, ctx)
        tracker.start(tag="auth-refactor")
        # ... AI agent 工作 ...
        summary = tracker.stop()
        print(tracker.generate_summary())
    """

    def __init__(self, project_root: str, store, ctx=None):
        self._project_root = project_root
        self._store = store
        self._ctx = ctx
        self._active_session_id: Optional[str] = None
        self._snapshots: dict[str, FileSnapshot] = {}
        self._started_at: Optional[str] = None

    # ═══════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════

    def start(self, tag: str = "") -> str:
        """开始追踪。返回 session_id。"""
        import uuid
        self._active_session_id = f"ais-{uuid.uuid4().hex[:12]}"
        self._started_at = datetime.now().isoformat()

        # 快照当前文件状态
        self._snapshots = self._snapshot_files()

        # 持久化到 DB
        try:
            self._store._db.execute(
                """INSERT INTO ai_sessions (id, project_id, task_id, tag, started_at, status, file_snapshot)
                   VALUES (?, ?, ?, ?, ?, 'active', ?)""",
                (self._active_session_id, "", self._ctx._task_id if self._ctx else "",
                 tag, self._started_at, json.dumps(self._serialize_snapshots())),
            )
            self._store._db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist session start: {e}")

        logger.info(f"AI session started: {self._active_session_id}")
        return self._active_session_id

    def stop(self) -> dict:
        """停止追踪，分析变更，生成摘要。"""
        if not self._active_session_id:
            return {"error": "No active session"}

        ended_at = datetime.now().isoformat()
        changes = self._compute_changes()
        issues = self._run_quality_checks(changes)

        # 持久化变更和问题
        self._persist_changes(changes)
        self._persist_issues(issues)

        # 更新 session 状态
        summary = self.generate_summary()
        try:
            self._store._db.execute(
                "UPDATE ai_sessions SET ended_at=?, status='completed', summary_markdown=?, quality_score=? WHERE id=?",
                (ended_at, summary.get("_markdown", ""), self._calc_quality_score(issues), self._active_session_id),
            )
            self._store._db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist session end: {e}")

        result = {
            "session_id": self._active_session_id,
            "started_at": self._started_at,
            "ended_at": ended_at,
            "changes": self._serialize_changes(changes),
            "issues": [self._serialize_issue(i) for i in issues],
            "summary": summary,
        }

        self._active_session_id = None
        self._snapshots = {}
        return result

    # ═══════════════════════════════════════════
    # 文件快照
    # ═══════════════════════════════════════════

    def _snapshot_files(self) -> dict[str, FileSnapshot]:
        """对项目文件做 snapshot。"""
        snapshots: dict[str, FileSnapshot] = {}
        root = Path(self._project_root)
        if not root.exists():
            return snapshots

        for fp in root.rglob("*"):
            if fp.is_file() and fp.suffix in (".ts", ".js", ".py", ".go", ".rs", ".java", ".kt",
                                              ".swift", ".cs", ".rb", ".php", ".dart", ".scala",
                                              ".lua", ".tsx", ".jsx", ".vue", ".c", ".h", ".cpp", ".hpp"):
                rel = fp.relative_to(root).as_posix()
                try:
                    content = fp.read_bytes()
                    snapshots[rel] = FileSnapshot(
                        path=rel,
                        mtime=fp.stat().st_mtime,
                        sha256=hashlib.sha256(content).hexdigest(),
                    )
                except Exception:
                    pass
        return snapshots

    def _compute_changes(self) -> list[ChangeRecord]:
        """计算文件变更。"""
        changes = []
        current = self._snapshot_files()

        # 修改和新增
        for path, snap in current.items():
            old = self._snapshots.get(path)
            if not old:
                changes.append(ChangeRecord(file_path=path, change_type="added"))
            elif old.sha256 != snap.sha256:
                changes.append(ChangeRecord(file_path=path, change_type="modified"))

        # 删除
        for path in self._snapshots:
            if path not in current:
                changes.append(ChangeRecord(file_path=path, change_type="deleted"))

        return changes

    # ═══════════════════════════════════════════
    # 质量检查
    # ═══════════════════════════════════════════

    def _run_quality_checks(self, changes: list[ChangeRecord]) -> list[QualityIssue]:
        """对变更运行质量检查。"""
        issues = []

        # 检查缺失测试
        for ch in changes:
            if ch.change_type in ("added", "modified") and ch.file_path.endswith(".ts"):
                test_path = ch.file_path.replace(".ts", ".test.ts").replace("/src/", "/tests/")
                if not os.path.exists(os.path.join(self._project_root, test_path)):
                    # Check alternate test locations
                    alt1 = ch.file_path.replace(".ts", ".spec.ts")
                    alt2 = ch.file_path.replace("/src/", "/__tests__/")
                    if not (os.path.exists(os.path.join(self._project_root, alt1)) or
                            os.path.exists(os.path.join(self._project_root, alt2))):
                        issues.append(QualityIssue(
                            file_path=ch.file_path, line_number=0,
                            issue_type="missing_test", severity="HIGH",
                            title=f"变更文件 {ch.file_path} 缺少对应测试",
                            suggestion=f"建议创建 {test_path}",
                        ))

        # 检查硬编码密钥（简易检测）
        for ch in changes:
            if ch.change_type == "modified":
                try:
                    fp = os.path.join(self._project_root, ch.file_path)
                    if os.path.exists(fp):
                        lines = Path(fp).read_text().split("\n")
                        for i, line in enumerate(lines, 1):
                            if re.search(r'(password|secret|token|api_key)\s*[:=]\s*["\']', line, re.IGNORECASE):
                                issues.append(QualityIssue(
                                    file_path=ch.file_path, line_number=i,
                                    issue_type="hardcoded_secret", severity="HIGH",
                                    title=f"疑似硬编码密钥/密码",
                                    suggestion="使用环境变量或配置管理存放敏感信息",
                                ))
                except Exception:
                    pass

        return issues

    # ═══════════════════════════════════════════
    # 摘要生成
    # ═══════════════════════════════════════════

    def generate_summary(self) -> dict:
        """生成会话摘要。"""
        if not self._active_session_id:
            return {}

        # 重新计算变更以获取最新数据
        changes = self._compute_changes()
        issues = self._run_quality_checks(changes)

        added = sum(1 for c in changes if c.change_type == "added")
        modified = sum(1 for c in changes if c.change_type == "modified")
        deleted = sum(1 for c in changes if c.change_type == "deleted")
        high = sum(1 for i in issues if i.severity == "HIGH")
        med = sum(1 for i in issues if i.severity == "MEDIUM")

        markdown = self._build_summary_markdown(changes, issues, added, modified, deleted, high, med)

        return {
            "session_id": self._active_session_id,
            "files_added": added,
            "files_modified": modified,
            "files_deleted": deleted,
            "issues_high": high,
            "issues_medium": med,
            "total_issues": len(issues),
            "_markdown": markdown,
        }

    def _build_summary_markdown(self, changes, issues, added, modified, deleted, high, med) -> str:
        duration = ""
        if self._started_at:
            try:
                dt = datetime.now() - datetime.fromisoformat(self._started_at)
                mins = int(dt.total_seconds() / 60)
                duration = f" | **耗时**: {mins}min"
            except Exception:
                pass

        lines = [
            f"# AI Session Summary",
            f"**会话 ID**: {self._active_session_id}",
            f"**时间**: {self._started_at or '?'} → {datetime.now().isoformat()}{duration}",
            "",
            "## 做了什么",
            f"| 变更类型 | 数量 |",
            f"|---------|------|",
            f"| 新增文件 | {added} |",
            f"| 修改文件 | {modified} |",
            f"| 删除文件 | {deleted} |",
            "",
        ]

        if changes:
            lines.append("### 关键文件")
            for c in changes[:15]:
                lines.append(f"- `{c.file_path}` ({c.change_type})")

        if issues:
            lines.append("")
            lines.append("## 可能的问题")
            lines.append(f"| 严重度 | 文件 | 问题 |")
            lines.append(f"|--------|------|------|")
            for i in issues[:10]:
                lines.append(f"| **{i.severity}** | `{i.file_path}" +
                             (f":{i.line_number}" if i.line_number else "") +
                             f"` | {i.title} |")

        if high or med:
            lines.append("")
            lines.append("## 架构影响")
            lines.append(f"- HIGH 严重问题: {high} 项")
            lines.append(f"- MEDIUM 问题: {med} 项")

        return "\n".join(lines)

    # ═══════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════

    def _persist_changes(self, changes: list[ChangeRecord]):
        try:
            for c in changes:
                self._store._db.execute(
                    """INSERT INTO ai_session_changes (session_id, file_path, change_type)
                       VALUES (?, ?, ?)""",
                    (self._active_session_id, c.file_path, c.change_type),
                )
            self._store._db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist changes: {e}")

    def _persist_issues(self, issues: list[QualityIssue]):
        try:
            for i in issues:
                self._store._db.execute(
                    """INSERT INTO ai_session_issues (session_id, file_path, line_number, issue_type, severity, title, description, suggestion)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (self._active_session_id, i.file_path, i.line_number, i.issue_type,
                     i.severity, i.title, i.description or "", i.suggestion or ""),
                )
            self._store._db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist issues: {e}")

    def _serialize_snapshots(self) -> dict:
        return {k: {"path": v.path, "mtime": v.mtime, "sha256": v.sha256} for k, v in self._snapshots.items()}

    def _serialize_changes(self, changes: list[ChangeRecord]) -> list[dict]:
        return [{"file_path": c.file_path, "change_type": c.change_type} for c in changes]

    def _serialize_issue(self, i: QualityIssue) -> dict:
        return {"file_path": i.file_path, "line": i.line_number, "type": i.issue_type,
                "severity": i.severity, "title": i.title, "suggestion": i.suggestion}

    @staticmethod
    def _calc_quality_score(issues: list[QualityIssue]) -> float:
        if not issues:
            return 1.0
        weights = {"HIGH": 10, "MEDIUM": 3, "LOW": 1, "INFO": 0}
        penalty = sum(weights.get(i.severity, 1) for i in issues)
        return max(0.0, 1.0 - penalty / 50.0)
