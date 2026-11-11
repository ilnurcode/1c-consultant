from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, List, Optional


class StepAction(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    PRESS_KEY = "press_key"
    WAIT = "wait"
    WAIT_FOR_ELEMENT = "wait_for_element"
    TABLE_ADD_ROW = "table_add_row"
    TABLE_FILL_CELL = "table_fill_cell"
    ASSERT_VISIBLE = "assert_visible"
    ASSERT_NOT_VISIBLE = "assert_not_visible"
    ASSERT_FIELD_VALUE = "assert_field_value"
    ASSERT_TITLE = "assert_title"
    SCREENSHOT = "screenshot"
    ODATA_VERIFY = "odata_verify"


@dataclass(slots=True)
class WebTestStep:
    action: StepAction
    target: str = ""           # Target text, selector, button label or table name
    field_name: str = ""       # Field label or column name
    value: str = ""            # Text value to type or select
    expected: str = ""         # Expected value for assertions
    timeout_ms: int = 10000    # Step timeout in ms
    description: str = ""      # Human readable description of the step
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "action": self.action.value,
        }
        if self.target:
            d["target"] = self.target
        if self.field_name:
            d["field_name"] = self.field_name
        if self.value:
            d["value"] = self.value
        if self.expected:
            d["expected"] = self.expected
        if self.timeout_ms != 10000:
            d["timeout_ms"] = self.timeout_ms
        if self.description:
            d["description"] = self.description
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebTestStep":
        return cls(
            action=StepAction(data.get("action", "click")),
            target=str(data.get("target", "")),
            field_name=str(data.get("field_name", "")),
            value=str(data.get("value", "")),
            expected=str(data.get("expected", "")),
            timeout_ms=int(data.get("timeout_ms", 10000)),
            description=str(data.get("description", "")),
            extra=dict(data.get("extra", {})),
        )


@dataclass(slots=True)
class ODataAssertion:
    entity: str                   # e.g. "Document_ЗаказКлиента"
    filter_expr: str = ""         # OData $filter, e.g. "Number eq '000000001'"
    expected_count: int = 1       # Expected number of matched rows
    expected_fields: dict[str, Any] = field(default_factory=dict) # Fields to assert (e.g. {"Posted": True})

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "filter_expr": self.filter_expr,
            "expected_count": self.expected_count,
            "expected_fields": self.expected_fields,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ODataAssertion":
        return cls(
            entity=str(data.get("entity", "")),
            filter_expr=str(data.get("filter_expr", "")),
            expected_count=int(data.get("expected_count", 1)),
            expected_fields=dict(data.get("expected_fields", {})),
        )


@dataclass(slots=True)
class WebTestScenario:
    id: str
    title: str
    description: str = ""
    metadata_object: str = ""     # e.g. "Документ.ЗаказКлиента"
    steps: list[WebTestStep] = field(default_factory=list)
    odata_assertions: list[ODataAssertion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "metadata_object": self.metadata_object,
            "steps": [s.to_dict() for s in self.steps],
            "odata_assertions": [a.to_dict() for a in self.odata_assertions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebTestScenario":
        return cls(
            id=str(data.get("id", "scenario_1")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            metadata_object=str(data.get("metadata_object", "")),
            steps=[WebTestStep.from_dict(s) for s in data.get("steps", [])],
            odata_assertions=[ODataAssertion.from_dict(a) for a in data.get("odata_assertions", [])],
        )


@dataclass(slots=True)
class WebTestSuite:
    id: str
    title: str
    description: str = ""
    scenarios: list[WebTestScenario] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "scenarios": [s.to_dict() for s in self.scenarios],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebTestSuite":
        return cls(
            id=str(data.get("id", "suite_1")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            scenarios=[WebTestScenario.from_dict(s) for s in data.get("scenarios", [])],
        )
