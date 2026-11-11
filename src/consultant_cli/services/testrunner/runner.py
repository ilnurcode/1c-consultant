from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from consultant_cli.domain.infobases import InfobaseConfig
from consultant_cli.infrastructure.odata_client import ODataClient
from consultant_cli.infrastructure.playwright_client import Playwright1CClient
from consultant_cli.services.testgen.models import (
    ODataAssertion,
    StepAction,
    WebTestScenario,
    WebTestStep,
    WebTestSuite,
)
from consultant_cli.services.testrunner.models import (
    ScenarioResult,
    StepResult,
    SuiteResult,
)

logger = logging.getLogger(__name__)


class Playwright1CTestRunner:
    """Executes WebTestSuites directly in 1C:Enterprise Web Client using Playwright."""

    def __init__(
        self,
        base_config: InfobaseConfig,
        screenshot_dir: Path | str | None = None,
        stop_on_first_error: bool = False,
    ) -> None:
        self.config = base_config
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.stop_on_first_error = stop_on_first_error
        self._client: Optional[Playwright1CClient] = None
        self._odata: Optional[ODataClient] = None

    @property
    def client(self) -> Playwright1CClient:
        if not self._client:
            if not self.config.web_url:
                raise ValueError(f"Для информационной базы '{self.config.name}' не настроен web_url.")
            self._client = Playwright1CClient(
                web_url=self.config.web_url,
                username=self.config.username,
                password=self.config.password,
                headless=self.config.headless,
                browser_type=self.config.browser_type,
            )
        return self._client

    @property
    def odata(self) -> Optional[ODataClient]:
        if not self._odata and self.config.odata_url:
            self._odata = ODataClient(
                base_url=self.config.odata_url,
                username=self.config.username,
                password=self.config.password,
            )
        return self._odata

    def close(self) -> None:
        if self._client:
            self._client.stop()
            self._client = None

    def execute_step(self, step_idx: int, step: WebTestStep) -> StepResult:
        """Executes a single test step in 1C Web Client with precise assertion handling."""
        start = time.perf_counter()
        action = step.action
        desc = step.description or f"{action.value} {step.target or step.field_name}"

        try:
            p = self.client.page

            if action == StepAction.NAVIGATE:
                self.client.navigate(step.target or None)

            elif action == StepAction.CLICK:
                self.client.click(step.target)

            elif action == StepAction.FILL:
                self.client.fill(step.field_name, step.value)

            elif action == StepAction.PRESS_KEY:
                key = step.value or step.target or "Enter"
                p.keyboard.press(key)
                p.wait_for_timeout(300)

            elif action == StepAction.WAIT:
                p.wait_for_timeout(step.timeout_ms)

            elif action == StepAction.WAIT_FOR_ELEMENT:
                target = step.target
                loc = p.get_by_text(target).first
                loc.wait_for(state="visible", timeout=step.timeout_ms)

            elif action == StepAction.TABLE_ADD_ROW:
                # Try clicking "Добавить" in table or pressing Insert key
                try:
                    add_btn = p.locator("button:has-text('Добавить'), div[role='button']:has-text('Добавить')").first
                    if add_btn.is_visible(timeout=1000):
                        add_btn.click()
                    else:
                        p.keyboard.press("Insert")
                except Exception:
                    p.keyboard.press("Insert")
                p.wait_for_timeout(400)

            elif action == StepAction.TABLE_FILL_CELL:
                # Fill active input or find column header
                field = step.field_name
                val = step.value
                try:
                    cell_input = p.locator("input:focus, .v8-activeCell input").first
                    if cell_input.is_visible(timeout=500):
                        cell_input.fill(val)
                    else:
                        self.client.fill(field, val)
                except Exception:
                    p.keyboard.type(val)
                p.keyboard.press("Enter")
                p.wait_for_timeout(300)

            elif action == StepAction.ASSERT_VISIBLE:
                target = step.target or step.expected
                loc = p.get_by_text(target).first
                if not loc.is_visible():
                    raise AssertionError(f"Ожидаемый элемент '{target}' не отображается на экране 1С.")

            elif action == StepAction.ASSERT_NOT_VISIBLE:
                target = step.target or step.expected
                loc = p.get_by_text(target).first
                if loc.is_visible():
                    raise AssertionError(f"Нежелательный элемент '{target}' отображается на экране 1С.")

            elif action == StepAction.ASSERT_FIELD_VALUE:
                field = step.field_name
                expected = step.expected or step.value
                # read field text or input value
                loc = p.get_by_label(field).first
                val = loc.input_value() if loc.is_visible() else ""
                if expected not in val:
                    raise AssertionError(f"Значение поля '{field}' ('{val}') не содержит ожидаемого '{expected}'.")

            elif action == StepAction.SCREENSHOT:
                pass

            duration = round((time.perf_counter() - start) * 1000, 2)
            return StepResult(
                step_index=step_idx,
                action=action.value,
                description=desc,
                status="PASSED",
                duration_ms=duration,
            )

        except Exception as e:
            duration = round((time.perf_counter() - start) * 1000, 2)
            screenshot_b64 = ""
            try:
                screenshot_b64 = self.client.take_screenshot()
            except Exception:
                pass

            return StepResult(
                step_index=step_idx,
                action=action.value,
                description=desc,
                status="FAILED",
                duration_ms=duration,
                error=str(e),
                screenshot_b64=screenshot_b64,
            )

    def verify_odata_assertion(self, assertion: ODataAssertion) -> dict[str, Any]:
        """Runs OData assertion against 1C database to verify actual persistent business state."""
        if not self.odata:
            return {
                "entity": assertion.entity,
                "status": "SKIPPED",
                "message": "OData URL не настроен в конфигурации базы.",
            }

        try:
            results = self.odata.query(
                entity=assertion.entity,
                filter_expr=assertion.filter_expr,
                top=10,
            )
            count = len(results)
            if count < assertion.expected_count:
                return {
                    "entity": assertion.entity,
                    "status": "FAILED",
                    "error": f"Найдено записей: {count}, ожидалось не менее: {assertion.expected_count}.",
                }

            # Check expected fields on matched records
            if assertion.expected_fields and count > 0:
                first_row = results[0]
                mismatches = []
                for k, expected_v in assertion.expected_fields.items():
                    actual_v = first_row.get(k)
                    if actual_v != expected_v:
                        mismatches.append(f"Поле '{k}': ожидалось '{expected_v}', получено '{actual_v}'")
                if mismatches:
                    return {
                        "entity": assertion.entity,
                        "status": "FAILED",
                        "error": "; ".join(mismatches),
                    }

            return {
                "entity": assertion.entity,
                "status": "PASSED",
                "count": count,
                "message": f"OData проверка подтверждена: найдено {count} записей.",
            }
        except Exception as e:
            return {
                "entity": assertion.entity,
                "status": "FAILED",
                "error": f"Ошибка выполнения OData-запроса: {e}",
            }

    def run_scenario(self, scenario: WebTestScenario) -> ScenarioResult:
        """Executes a single web scenario."""
        logger.info(f"Running scenario: {scenario.title}")
        start = time.perf_counter()
        step_results: list[StepResult] = []
        scenario_failed = False
        scenario_error = ""
        screenshot_path = ""

        for idx, step in enumerate(scenario.steps, 1):
            if scenario_failed:
                step_results.append(
                    StepResult(
                        step_index=idx,
                        action=step.action.value,
                        description=step.description or f"Step {idx}",
                        status="SKIPPED",
                    )
                )
                continue

            res = self.execute_step(idx, step)
            step_results.append(res)

            if res.status == "FAILED":
                scenario_failed = True
                scenario_error = f"Шаг {idx} ({res.action}): {res.error}"

                # Save screenshot if directory configured
                if res.screenshot_b64 and self.screenshot_dir:
                    self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                    img_file = self.screenshot_dir / f"fail_{scenario.id}_step{idx}.png"
                    img_file.write_bytes(base64.b64decode(res.screenshot_b64))
                    screenshot_path = str(img_file)

        # Run OData assertions if web steps passed
        odata_results: list[dict[str, Any]] = []
        if not scenario_failed and scenario.odata_assertions:
            for a in scenario.odata_assertions:
                od_res = self.verify_odata_assertion(a)
                odata_results.append(od_res)
                if od_res.get("status") == "FAILED":
                    scenario_failed = True
                    scenario_error = f"OData проверка ({a.entity}): {od_res.get('error')}"

        duration = round((time.perf_counter() - start) * 1000, 2)
        return ScenarioResult(
            scenario_id=scenario.id,
            title=scenario.title,
            status="FAILED" if scenario_failed else "PASSED",
            duration_ms=duration,
            error=scenario_error,
            step_results=step_results,
            odata_results=odata_results,
            failure_screenshot_path=screenshot_path,
        )

    def run_suite(self, suite: WebTestSuite) -> SuiteResult:
        """Executes entire test suite and returns aggregated SuiteResult."""
        start = time.perf_counter()
        scenario_results: list[ScenarioResult] = []
        passed = 0
        failed = 0

        try:
            for sc in suite.scenarios:
                res = self.run_scenario(sc)
                scenario_results.append(res)
                if res.status == "PASSED":
                    passed += 1
                else:
                    failed += 1
                    if self.stop_on_first_error:
                        break
        finally:
            self.close()

        duration = round((time.perf_counter() - start) * 1000, 2)
        return SuiteResult(
            suite_id=suite.id,
            title=suite.title,
            base_name=self.config.name,
            total=len(scenario_results),
            passed=passed,
            failed=failed,
            duration_ms=duration,
            scenario_results=scenario_results,
        )

    @staticmethod
    def format_text_report(result: SuiteResult) -> str:
        lines: list[str] = []
        lines.append("=" * 78)
        lines.append("  ПРОТОКОЛ ТЕСТИРОВАНИЯ 1С:ПРЕДПРИЯТИЕ (PLAYWRIGHT WEB CLIENT)")
        lines.append("=" * 78)
        lines.append(f"Набор тестов: {result.title} | База: {result.base_name}")
        lines.append(f"Всего сценариев: {result.total} | Успешно: {result.passed} | Ошибок: {result.failed} | Время: {result.duration_ms} мс")
        lines.append(f"Итоговый статус: {'[УСПЕХ / PASSED]' if result.is_success else '[ПРОВАЛ / FAILED]'}")
        lines.append("-" * 78)

        for sc_idx, sc in enumerate(result.scenario_results, 1):
            badge = "[OK]" if sc.status == "PASSED" else "[FAIL]"
            lines.append(f"\nСценарий {sc_idx}: {badge} {sc.title} ({sc.duration_ms} мс)")
            if sc.error:
                lines.append(f"  Причина падения: {sc.error}")
            if sc.failure_screenshot_path:
                lines.append(f"  Скриншот ошибки: {sc.failure_screenshot_path}")

            for st in sc.step_results:
                st_mark = "  ✓" if st.status == "PASSED" else "  ✗" if st.status == "FAILED" else "  -"
                lines.append(f"  {st_mark} Шаг {st.step_index}: {st.description} ({st.duration_ms} мс)")
                if st.error:
                    lines.append(f"      Ошибка: {st.error}")

            if sc.odata_results:
                lines.append("  Проверки базы данных (OData):")
                for od in sc.odata_results:
                    od_mark = "    ✓" if od.get("status") == "PASSED" else "    ✗"
                    lines.append(f"{od_mark} {od.get('entity')}: {od.get('message') or od.get('error')}")

        lines.append("\n" + "=" * 78)
        return "\n".join(lines)
