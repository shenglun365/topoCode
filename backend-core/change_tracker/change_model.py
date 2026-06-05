"""数据模型 — 变更跟踪的核心类型定义。

包括快照、变更报告、符号变更和文件变更的数据模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ChangeType(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"


class RiskLevel(Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SymbolChange:
    name: str
    kind: str
    change_type: ChangeType
    file_path: str
    old_line: Optional[int] = None
    new_line: Optional[int] = None
    old_signature: Optional[str] = None
    new_signature: Optional[str] = None
    risk: RiskLevel = RiskLevel.NONE


@dataclass
class FileChange:
    file_path: str
    change_type: ChangeType
    symbols_changed: list[SymbolChange] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    risk: RiskLevel = RiskLevel.NONE


@dataclass
class DependencyChange:
    file_path: str
    dependency: str
    change_type: ChangeType
    risk: RiskLevel = RiskLevel.NONE


@dataclass
class ChangeSummary:
    files_changed: int = 0
    symbols_added: int = 0
    symbols_modified: int = 0
    symbols_removed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    risk_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.NONE


@dataclass
class ChangeReport:
    from_commit: str
    to_commit: str
    from_timestamp: Optional[datetime] = None
    to_timestamp: Optional[datetime] = None
    files: list[FileChange] = field(default_factory=list)
    dependencies: list[DependencyChange] = field(default_factory=list)
    summary: ChangeSummary = field(default_factory=ChangeSummary)


@dataclass
class ProjectSnapshot:
    commit_hash: str
    timestamp: datetime
    file_hashes: dict[str, str] = field(default_factory=dict)
    symbols: dict[str, list[dict]] = field(default_factory=dict)
    dependencies: list[dict] = field(default_factory=list)
    is_analyzed: bool = False
