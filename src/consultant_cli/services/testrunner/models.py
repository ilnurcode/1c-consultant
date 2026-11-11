from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional


@dataclass(slots=True)
class StepResult:
    step_index: int
    action: str
    description: str
    status: str  # "PASSED" | "FAILED" | "SKIPPED"
    duration_ms: float = 0.0
    error: str = ""
    screenshot_b64: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "action": self.action,
            "description": self.description,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "has_screenshot": bool(self.screenshot_b64),
        }


@dataclass(slots=True)
class ScenarioResult:
    scenario_id: str
    title: str
    status: str  # "PASSED" | "FAILED"
    duration_ms: float = 0.0
    error: str = ""
    step_results: list[StepResult] = field(default_factory=list)
    odata_results: list[dict[str, Any]] = field(default_factory=list)
    failure_screenshot_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "step_results": [s.to_dict() for s in self.step_results],
            "odata_results": self.odata_results,
            "failure_screenshot_path": self.failure_screenshot_path,
        }


@dataclass(slots=True)
class SuiteResult:
    suite_id: str
    title: str
    base_name: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    duration_ms: float = 0.0
    scenario_results: list[ScenarioResult] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.failed == 0 and self.total > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "title": self.title,
            "base_name": self.base_name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "is_success": self.is_success,
            "duration_ms": self.duration_ms,
            "scenarios": [s.to_dict() for s in self.scenario_results],
        }
