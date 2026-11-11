from __future__ import annotations

import unittest

from consultant_cli.services.testgen import (
    StepAction,
    WebTestGenerator,
    WebTestScenario,
    WebTestStep,
    WebTestSuite,
)


class TestTestGenerator(unittest.TestCase):
    def test_document_test_generation(self) -> None:
        scenario = WebTestGenerator.generate_document_test(
            doc_name="РеализацияТоваровУслуг",
            subsystem="Продажи",
            header_fields={"Контрагент": "ООО Вектор", "Склад": "Главный"},
            table_rows=[{"Номенклатура": "Кабель", "Количество": "10"}],
            post=True,
        )
        self.assertEqual(scenario.metadata_object, "Документ.РеализацияТоваровУслуг")
        self.assertGreater(len(scenario.steps), 10)

        # Check key actions exist
        actions = [s.action for s in scenario.steps]
        self.assertIn(StepAction.NAVIGATE, actions)
        self.assertIn(StepAction.CLICK, actions)
        self.assertIn(StepAction.FILL, actions)
        self.assertIn(StepAction.TABLE_ADD_ROW, actions)
        self.assertIn(StepAction.TABLE_FILL_CELL, actions)

        # Check serialization roundtrip
        d = scenario.to_dict()
        restored = WebTestScenario.from_dict(d)
        self.assertEqual(restored.id, scenario.id)
        self.assertEqual(len(restored.steps), len(scenario.steps))

    def test_smoke_test_generation(self) -> None:
        objs = ["Справочник.Склады", "Документ.ЗаказПоставщику"]
        suite = WebTestGenerator.generate_smoke_test(subsystem="Склад", objects=objs)
        self.assertEqual(len(suite.scenarios), 2)
        self.assertEqual(suite.scenarios[0].metadata_object, "Справочник.Склады")
        self.assertEqual(suite.scenarios[1].metadata_object, "Документ.ЗаказПоставщику")

    def test_gherkin_import(self) -> None:
        gherkin = """
        # language: ru
        Функционал: Проверка заказа

        Сценарий: Заполнение полей
          И В командном интерфейсе я выбираю "Продажи" "Заказы"
          И я нажимаю на кнопку "Создать"
          Тогда открылось окно "Заказ (создание)"
          И в поле "Клиент" я ввожу "ООО Тест"
        """
        suite = WebTestGenerator.from_gherkin_text(gherkin)
        self.assertEqual(len(suite.scenarios), 1)
        sc = suite.scenarios[0]
        self.assertEqual(sc.title, "Заполнение полей")
        step_descriptions = [s.description for s in sc.steps]
        self.assertTrue(any("Создать" in d for d in step_descriptions))
        self.assertTrue(any("Клиент" in d for d in step_descriptions))


if __name__ == "__main__":
    unittest.main()
