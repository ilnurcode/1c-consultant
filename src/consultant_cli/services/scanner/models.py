from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class IssueCategory(str, Enum):
    SECURITY = "SECURITY"
    LOCKING = "LOCKING"
    PERFORMANCE = "PERFORMANCE"
    STANDARDS = "STANDARDS"
    SYNTAX = "SYNTAX"


@dataclass(slots=True)
class ScanIssue:
    rule_id: str
    category: IssueCategory
    severity: Severity
    message: str
    file_path: str
    line: int
    col: int = 1
    code_fragment: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "file_path": self.file_path,
            "line": self.line,
            "col": self.col,
            "code_fragment": self.code_fragment,
            "recommendation": self.recommendation,
        }


@dataclass(slots=True)
class ScanSummary:
    total_files: int = 0
    total_issues: int = 0
    issues_by_severity: dict[str, int] = field(default_factory=dict)
    issues_by_category: dict[str, int] = field(default_factory=dict)
    passed: bool = True
    duration_ms: float = 0.0
    issues: list[ScanIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_files": self.total_files,
            "total_issues": self.total_issues,
            "issues_by_severity": self.issues_by_severity,
            "issues_by_category": self.issues_by_category,
            "passed": self.passed,
            "duration_ms": self.duration_ms,
            "issues": [issue.to_dict() for issue in self.issues],
        }
