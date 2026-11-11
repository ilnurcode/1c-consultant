from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from consultant_cli.domain.infobases import InfobaseConfig
from consultant_cli.services.testgen import StepAction, WebTestScenario, WebTestStep, WebTestSuite
from consultant_cli.services.testrunner import (
    Playwright1CTestRunner,
    ScenarioResult,
    StepResult,
    SuiteResult,
)


class TestTestRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.config = InfobaseConfig(name="MockBase", web_url="http://mock.1c/base")
        self.runner = Playwright1CTestRunner(self.config)

    def test_format_text_report(self) -> None:
        step_res = StepResult(
            step_index=1,
            action="click",
            description="Клик по Создать",
            status="PASSED",
            duration_ms=45.2,
        )
        sc_res = ScenarioResult(
            scenario_id="sc_1",
            title="Тестовый сценарий",
            status="PASSED",
            duration_ms=120.5,
            step_results=[step_res],
        )
        suite_res = SuiteResult(
            suite_id="suite_1",
            title="Главный набор",
            base_name="MockBase",
            total=1,
            passed=1,
            failed=0,
            duration_ms=150.0,
            scenario_results=[sc_res],
        )
        report = Playwright1CTestRunner.format_text_report(suite_res)
        self.assertIn("ПРОТОКОЛ ТЕСТИРОВАНИЯ", report)
        self.assertIn("[OK] Тестовый сценарий", report)
        self.assertIn("Клик по Создать", report)
        self.assertTrue(suite_res.is_success)

    @patch("consultant_cli.services.testrunner.runner.Playwright1CClient")
    def test_run_scenario_with_mock_client(self, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_page = MagicMock()
        mock_client.page = mock_page
        self.runner._client = mock_client

        scenario = WebTestScenario(
            id="test_sc",
            title="Mock Scenario",
            steps=[
                WebTestStep(action=StepAction.NAVIGATE, description="Открытие"),
                WebTestStep(action=StepAction.CLICK, target="Создать", description="Клик"),
            ],
        )

        res = self.runner.run_scenario(scenario)
        self.assertEqual(res.status, "PASSED")
        self.assertEqual(len(res.step_results), 2)
        self.assertEqual(res.step_results[0].status, "PASSED")
        self.assertEqual(res.step_results[1].status, "PASSED")


if __name__ == "__main__":
    unittest.main()
