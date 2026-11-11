from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from consultant_cli.services.scanner import (
    BSLRule,
    IssueCategory,
    ScannerEngine,
    ScanIssue,
    Severity,
)


class TestScanner(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ScannerEngine()

    def test_dynamic_code_execution_detected(self) -> None:
        code = """
        Процедура Опасная(ИмяМетода)
            Выполнить("Модуль." + ИмяМетода);
        КонецПроцедуры
        """
        issues = self.engine.scan_code(code, "test.bsl")
        self.assertTrue(any(i.rule_id == "SEC001" and i.severity == Severity.CRITICAL for i in issues))

    def test_query_injection_detected(self) -> None:
        code = """
        Запрос = Новый Запрос;
        Запрос.Текст = "ВЫБРАТЬ * ИЗ Справочник.Номенклатура ГДЕ Код = " + Код;
        """
        issues = self.engine.scan_code(code, "test.bsl")
        self.assertTrue(any(i.rule_id == "SEC002" and i.severity == Severity.HIGH for i in issues))

    def test_unmanaged_locking_in_posting_detected(self) -> None:
        code = """
        Процедура ОбработкаПроведения(Отказ, РежимПроведения)
            Движения.Остатки.Записывать = Истина;
            Движения.Остатки.Записать();
        КонецПроцедуры
        """
        issues = self.engine.scan_code(code, "posting.bsl")
        self.assertTrue(any(i.rule_id == "LCK001" for i in issues))

    def test_managed_locking_present_no_issue(self) -> None:
        code = """
        Процедура ОбработкаПроведения(Отказ, РежимПроведения)
            Блокировка = Новый БлокировкаДанных;
            Элт = Блокировка.Добавить("РегистрНакопления.Остатки");
            Блокировка.Заблокировать();
            
            Движения.Остатки.Записывать = Истина;
            Движения.Остатки.Записать();
        КонецПроцедуры
        """
        issues = self.engine.scan_code(code, "safe_posting.bsl")
        self.assertFalse(any(i.rule_id == "LCK001" for i in issues))

    def test_query_in_loop_detected(self) -> None:
        code = """
        Для каждого Стр Из Таблица Цикл
            Запрос = Новый Запрос;
            Запрос.Выполнить();
        КонецЦикла;
        """
        issues = self.engine.scan_code(code, "loop.bsl")
        self.assertTrue(any(i.rule_id == "PERF001" for i in issues))

    def test_directory_scan_and_sarif_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "mod1.bsl").write_text("Выполнить(Действие);", encoding="utf-8")
            (tmp_path / "mod2.bsl").write_text("// Чистый файл\nЗначение = 1;", encoding="utf-8")

            summary = self.engine.scan_directory(tmp_path)
            self.assertEqual(summary.total_files, 2)
            self.assertGreaterEqual(summary.total_issues, 1)

            # Test text report
            txt = self.engine.format_text_report(summary)
            self.assertIn("ОТЧЁТ СТАТИЧЕСКОГО АНАЛИЗА", txt)

            # Test SARIF report
            sarif = self.engine.format_sarif_report(summary)
            self.assertIn("sarif-schema-2.1.0", sarif)


if __name__ == "__main__":
    unittest.main()
