from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from consultant_cli.errors import ConsultantError
from consultant_cli.infrastructure.store import atomic_write_text
from consultant_cli.services.odata import ODataService
from consultant_cli.services.playwright_mcp import PlaywrightMcpService


@dataclass(frozen=True, slots=True)
class CustomerOrderRequest:
    customer: str = "Тестовый клиент"
    organization: str = "Андромеда Плюс"
    contract: str = "Тестовый договор с клиентом (Андромеда Плюс)"
    product: str = "Хлеб пшеничный"
    quantity: str = "10"


@dataclass(frozen=True, slots=True)
class AutomationRun:
    run_id: str
    created_at: str
    scenario: str
    status: str
    values: dict[str, object]
    message: str


class AutomationHistory:
    """Append-only operational history. It has no fields for access secrets."""
    def __init__(self, path: Path) -> None: self.path = path
    def begin(self, request: CustomerOrderRequest) -> AutomationRun:
        run = AutomationRun(f"RUN-{uuid4().hex[:8].upper()}", datetime.now(UTC).isoformat(timespec="seconds"), "Заказ клиента", "проверка данных", asdict(request), "Запуск начат; проведение запрещено до отдельной команды.")
        self.append(run)
        return run
    def append(self, run: AutomationRun) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        old = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        atomic_write_text(self.path, old + json.dumps(asdict(run), ensure_ascii=False) + "\n")
    def update(self, run: AutomationRun, status: str, message: str, **values: object) -> AutomationRun:
        updated = AutomationRun(run.run_id, run.created_at, run.scenario, status, {**run.values, **values}, message)
        self.append(updated)
        return updated
    def list(self, limit: int = 10) -> list[AutomationRun]:
        latest: dict[str, AutomationRun] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    item = AutomationRun(**json.loads(line)); latest[item.run_id] = item
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
        return list(reversed(list(latest.values())[-limit:]))


class CustomerOrderAutomation:
    required = {"customer": "Catalog_Контрагенты", "organization": "Catalog_Организации", "contract": "Catalog_ДоговорыКонтрагентов", "product": "Catalog_Номенклатура"}
    def __init__(self, odata: ODataService, browser: PlaywrightMcpService, history: AutomationHistory) -> None:
        self.odata, self.browser, self.history = odata, browser, history
    def run(self, request: CustomerOrderRequest) -> AutomationRun:
        if request.quantity.replace(",", ".") != "10":
            raise ConsultantError("Для защищённого тестового сценария допустимо только количество 10.")
        run = self.history.begin(request)
        try:
            resolved = self._preflight(request)
            run = self.history.update(run, "выполнение в 1С", "Значения однозначно подтверждены через OData.", resolved=resolved)
            result = self.browser.run_customer_order(request)
            number = str(result.get("number") or "")
            if not number: raise ConsultantError("1С не вернула номер записанного заказа; проведение не выполнялось.")
            verified = self._verify(number, posted=False)
            return self.history.update(run, "записан, не проведён", "Заказ записан через Playwright MCP и подтверждён OData. Проведение не выполнялось.", number=number, verified=verified)
        except Exception as exc:
            self.history.update(run, "остановлен", str(exc)); raise
    def post(self, run_id: str, confirmed: bool) -> AutomationRun:
        if not confirmed: raise ConsultantError("Проведение отменено: требуется явное подтверждение.")
        runs = [item for item in self.history.list(100) if item.run_id == run_id]
        if not runs or runs[0].status != "записан, не проведён": raise ConsultantError("Для проведения нужен подтверждённый непроведённый запуск.")
        run = runs[0]; number = str(run.values.get("number") or "")
        self.browser.post_customer_order(number)
        return self.history.update(run, "проведён", "Проведение выполнено через Playwright MCP и подтверждено OData.", verified=self._verify(number, posted=True))
    def _preflight(self, request: CustomerOrderRequest) -> dict[str, str]:
        entities = {item["name"] for item in self.odata.list_entities()["entities"]}; resolved: dict[str, str] = {}
        for key, entity in self.required.items():
            if entity not in entities: raise ConsultantError(f"В OData нет сущности для «{key}»; сценарий остановлен.")
            value = getattr(request, key)
            rows = self.odata.query(entity, top=1000)["rows"]
            matches = [row for row in rows if str(row.get("Description", row.get("Наименование", ""))).strip() == value]
            if len(matches) != 1: raise ConsultantError(f"«{value}»: найдено совпадений {len(matches)}; выбор наугад запрещён.")
            resolved[key] = str(matches[0].get("Ref_Key", matches[0].get("Key", value)))
        return resolved
    def _verify(self, number: str, *, posted: bool) -> dict[str, object]:
        rows = self.odata.query("Document_ЗаказКлиента", top=1000)["rows"]
        matches = [row for row in rows if str(row.get("Number", "")) == number]
        if len(matches) != 1: raise ConsultantError(f"После действия OData нашла заказ {number} {len(matches)} раз.")
        if bool(matches[0].get("Posted")) != posted: raise ConsultantError("OData не подтвердила ожидаемое состояние заказа.")
        return matches[0]
