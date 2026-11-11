from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from consultant_cli.services.testgen.models import (
    ODataAssertion,
    StepAction,
    WebTestScenario,
    WebTestStep,
    WebTestSuite,
)


class WebTestGenerator:
    """Generates automated end-to-end test scenarios executable in 1C Web Client via Playwright."""

    @staticmethod
    def generate_document_test(
        doc_name: str,
        subsystem: str = "",
        header_fields: dict[str, str] | None = None,
        table_rows: list[dict[str, str]] | None = None,
        table_name: str = "Товары",
        post: bool = True,
        odata_entity: str = "",
    ) -> WebTestScenario:
        """Generates a complete creation, population and posting scenario for a 1C document."""
        clean_name = doc_name.replace("Документ.", "").strip()
        scenario_id = f"test_{clean_name.lower()}_posting"
        title = f"Создание и проведение документа '{clean_name}'"
        steps: list[WebTestStep] = []

        # 1. Navigation & List opening
        steps.append(
            WebTestStep(
                action=StepAction.NAVIGATE,
                description="Открытие веб-клиента 1С:Предприятие",
            )
        )
        if subsystem:
            steps.append(
                WebTestStep(
                    action=StepAction.CLICK,
                    target=subsystem,
                    description=f"Переход в подсистему '{subsystem}'",
                )
            )
        steps.append(
            WebTestStep(
                action=StepAction.CLICK,
                target=clean_name,
                description=f"Открытие списка документов '{clean_name}'",
            )
        )
        steps.append(
            WebTestStep(
                action=StepAction.WAIT_FOR_ELEMENT,
                target="Создать",
                description="Ожидание загрузки формы списка",
            )
        )

        # 2. Document Creation
        steps.append(
            WebTestStep(
                action=StepAction.CLICK,
                target="Создать",
                description="Нажатие кнопки 'Создать'",
            )
        )
        steps.append(
            WebTestStep(
                action=StepAction.WAIT_FOR_ELEMENT,
                target="Провести и закрыть",
                description="Ожидание открытия формы документа",
            )
        )

        # 3. Filling header attributes
        if header_fields:
            for field_label, field_val in header_fields.items():
                steps.append(
                    WebTestStep(
                        action=StepAction.FILL,
                        field_name=field_label,
                        value=str(field_val),
                        description=f"Заполнение реквизита '{field_label}' значением '{field_val}'",
                    )
                )

        # 4. Filling tabular section
        if table_rows:
            steps.append(
                WebTestStep(
                    action=StepAction.CLICK,
                    target=table_name,
                    description=f"Активация табличной части '{table_name}'",
                )
            )
            for row_idx, row_data in enumerate(table_rows, 1):
                steps.append(
                    WebTestStep(
                        action=StepAction.TABLE_ADD_ROW,
                        target=table_name,
                        description=f"Добавление строки {row_idx} в таблицу '{table_name}'",
                    )
                )
                for col_name, cell_val in row_data.items():
                    steps.append(
                        WebTestStep(
                            action=StepAction.TABLE_FILL_CELL,
                            field_name=col_name,
                            value=str(cell_val),
                            description=f"Заполнение колонки '{col_name}' значением '{cell_val}'",
                        )
                    )

        # 5. Posting document
        post_btn = "Провести и закрыть" if post else "Записать"
        steps.append(
            WebTestStep(
                action=StepAction.CLICK,
                target=post_btn,
                description=f"Нажатие кнопки '{post_btn}'",
            )
        )

        # 6. Check for success (no error banners, list visible again)
        steps.append(
            WebTestStep(
                action=StepAction.WAIT,
                timeout_ms=1500,
                description="Ожидание завершения транзакции проведения",
            )
        )
        steps.append(
            WebTestStep(
                action=StepAction.ASSERT_NOT_VISIBLE,
                target="Ошибка",
                description="Проверка отсутствия системных ошибок и блокировок",
            )
        )

        # Optional OData database verification
        odata_assertions: list[ODataAssertion] = []
        if odata_entity or post:
            entity_name = odata_entity or f"Document_{clean_name}"
            expected = {"Posted": True} if post else {}
            odata_assertions.append(
                ODataAssertion(
                    entity=entity_name,
                    expected_count=1,
                    expected_fields=expected,
                )
            )

        return WebTestScenario(
            id=scenario_id,
            title=title,
            description=f"Автоматический сквозной тест создания и проведения документа {clean_name}",
            metadata_object=f"Документ.{clean_name}",
            steps=steps,
            odata_assertions=odata_assertions,
        )

    @staticmethod
    def generate_smoke_test(subsystem: str, objects: list[str]) -> WebTestSuite:
        """Generates smoke test opening list forms of selected metadata objects to ensure no runtime crashes."""
        scenarios: list[WebTestScenario] = []
        for obj in objects:
            clean_obj = obj.split(".", 1)[-1].strip()
            scenario = WebTestScenario(
                id=f"smoke_{clean_obj.lower()}",
                title=f"Smoke-тест открытия формы '{clean_obj}'",
                metadata_object=obj,
                steps=[
                    WebTestStep(action=StepAction.NAVIGATE, description="Открытие 1С"),
                    WebTestStep(action=StepAction.CLICK, target=subsystem, description=f"Выбор подсистемы '{subsystem}'"),
                    WebTestStep(action=StepAction.CLICK, target=clean_obj, description=f"Открытие списка '{clean_obj}'"),
                    WebTestStep(action=StepAction.WAIT, timeout_ms=1000, description="Пауза для отрисовки динамического списка"),
                    WebTestStep(action=StepAction.ASSERT_NOT_VISIBLE, target="Критическая ошибка", description="Проверка отсутствия аварийного завершения"),
                ],
            )
            scenarios.append(scenario)

        return WebTestSuite(
            id=f"smoke_{subsystem.lower()}",
            title=f"Smoke-тесты подсистемы '{subsystem}'",
            description=f"Проверка открытия форм объектов: {', '.join(objects)}",
            scenarios=scenarios,
        )

    @classmethod
    def from_gherkin_text(cls, gherkin: str, suite_title: str = "Импортированный BDD сценарий") -> WebTestSuite:
        """Parses standard Vanessa Automation Gherkin (.feature) text and converts it to Playwright WebTestSteps."""
        scenarios: list[WebTestScenario] = []
        current_scenario: Optional[WebTestScenario] = None
        scenario_idx = 0

        # Patterns for standard Vanessa Automation steps
        p_click_button = re.compile(r"""(?:И|Когда|Затем|Тогда|Дано)?\s*(?:я|Я)?\s*нажимаю(?: на)? кнопку ["'](.+?)["']""", re.IGNORECASE)
        p_click_menu = re.compile(r"""(?:И|Когда|Затем)?\s*В командном интерфейсе я выбираю ["'](.+?)["'](?: ["'](.+?)["'])?""", re.IGNORECASE)
        p_fill_field = re.compile(r"""(?:И|Когда)?\s*(?:В|в) поле ["'](.+?)["'] (?:я )?ввожу (?:значение )?["'](.*?)["']""", re.IGNORECASE)
        p_window_opened = re.compile(r"""(?:Тогда|Затем|И)?\s*(?:открылось|открыто|открывается) окно ["'](.+?)["']""", re.IGNORECASE)
        p_table_add = re.compile(r"""(?:И|Когда)?\s*(?:в|В) таблице ["'](.+?)["'] (?:я )?нажимаю кнопку ["']Добавить["']""", re.IGNORECASE)
        p_table_cell = re.compile(r"""(?:И|Когда)?\s*(?:в|В) (?:текущей строке в )?поле ["'](.+?)["'] (?:я )?(?:ввожу|выбираю) (?:значение )?["'](.*?)["']""", re.IGNORECASE)

        for raw_line in gherkin.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.lower().startswith("сценарий:") or line.lower().startswith("scenario:"):
                scenario_title = line.split(":", 1)[1].strip()
                scenario_idx += 1
                current_scenario = WebTestScenario(
                    id=f"scenario_{scenario_idx}",
                    title=scenario_title,
                    steps=[WebTestStep(action=StepAction.NAVIGATE, description="Открытие 1С")],
                )
                scenarios.append(current_scenario)
                continue

            if not current_scenario:
                continue

            # Match step patterns
            m = p_click_menu.search(line)
            if m:
                s1, s2 = m.group(1), m.group(2)
                current_scenario.steps.append(WebTestStep(action=StepAction.CLICK, target=s1, description=f"Клик по меню '{s1}'"))
                if s2:
                    current_scenario.steps.append(WebTestStep(action=StepAction.CLICK, target=s2, description=f"Клик по разделу '{s2}'"))
                continue

            m = p_click_button.search(line)
            if m:
                btn_name = m.group(1)
                current_scenario.steps.append(WebTestStep(action=StepAction.CLICK, target=btn_name, description=f"Клик по кнопке '{btn_name}'"))
                continue

            m = p_fill_field.search(line)
            if m:
                f_name, f_val = m.group(1), m.group(2)
                current_scenario.steps.append(WebTestStep(action=StepAction.FILL, field_name=f_name, value=f_val, description=f"Заполнение поля '{f_name}' = '{f_val}'"))
                continue

            m = p_window_opened.search(line)
            if m:
                w_title = m.group(1)
                current_scenario.steps.append(WebTestStep(action=StepAction.ASSERT_VISIBLE, target=w_title, description=f"Проверка видимости окна '{w_title}'"))
                continue

            m = p_table_add.search(line)
            if m:
                t_name = m.group(1)
                current_scenario.steps.append(WebTestStep(action=StepAction.TABLE_ADD_ROW, target=t_name, description=f"Добавление строки в таблицу '{t_name}'"))
                continue

            m = p_table_cell.search(line)
            if m:
                c_name, c_val = m.group(1), m.group(2)
                current_scenario.steps.append(WebTestStep(action=StepAction.TABLE_FILL_CELL, field_name=c_name, value=c_val, description=f"Заполнение ячейки '{c_name}' = '{c_val}'"))
                continue

        return WebTestSuite(
            id="imported_suite",
            title=suite_title,
            scenarios=scenarios,
        )
