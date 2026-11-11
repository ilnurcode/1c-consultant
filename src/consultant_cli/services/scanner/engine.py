from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable

from consultant_cli.services.scanner.bsl_rules import BSLRule, get_default_rules
from consultant_cli.services.scanner.models import IssueCategory, ScanIssue, ScanSummary, Severity

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".bsl", ".os", ".xml", ".txt"}


class ScannerEngine:
    """Core static analysis engine for 1C:Enterprise (BSL, configuration dumps, scripts)."""

    def __init__(self, rules: list[BSLRule] | None = None) -> None:
        self.rules = rules or get_default_rules()

    def scan_code(self, code: str, file_name: str = "snippet.bsl") -> list[ScanIssue]:
        lines = code.splitlines(keepends=True)
        issues: list[ScanIssue] = []
        for rule in self.rules:
            issues.extend(rule.analyze(file_name, lines))
        return sorted(issues, key=lambda x: (x.line, x.col))

    def scan_file(self, file_path: Path | str) -> list[ScanIssue]:
        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Файл для анализа не найден: {path}")

        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                content = path.read_text(encoding="cp1251")
            except Exception as e:
                logger.warning(f"Не удалось прочитать {path}: {e}")
                return []

        return self.scan_code(content, str(path))

    def scan_directory(
        self,
        directory: Path | str,
        recursive: bool = True,
        min_severity: Severity | None = None,
    ) -> ScanSummary:
        start_time = time.perf_counter()
        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Каталог не найден: {dir_path}")

        files_to_scan: list[Path] = []
        pattern = "**/*" if recursive else "*"
        for p in dir_path.glob(pattern):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                # ignore hidden folders like .git, .venv, node_modules
                parts = p.parts
                if any(part.startswith(".") or part in {"node_modules", "__pycache__", "build", "dist"} for part in parts):
                    continue
                files_to_scan.append(p)

        all_issues: list[ScanIssue] = []
        for file in files_to_scan:
            all_issues.extend(self.scan_file(file))

        severity_rank = {
            Severity.CRITICAL: 5,
            Severity.HIGH: 4,
            Severity.MEDIUM: 3,
            Severity.LOW: 2,
            Severity.INFO: 1,
        }

        if min_severity:
            threshold = severity_rank.get(min_severity, 1)
            all_issues = [i for i in all_issues if severity_rank.get(i.severity, 1) >= threshold]

        # Calculate statistics
        issues_by_sev: dict[str, int] = {}
        issues_by_cat: dict[str, int] = {}
        for issue in all_issues:
            issues_by_sev[issue.severity.value] = issues_by_sev.get(issue.severity.value, 0) + 1
            issues_by_cat[issue.category.value] = issues_by_cat.get(issue.category.value, 0) + 1

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        passed = (issues_by_sev.get(Severity.CRITICAL.value, 0) == 0 and issues_by_sev.get(Severity.HIGH.value, 0) == 0)

        return ScanSummary(
            total_files=len(files_to_scan),
            total_issues=len(all_issues),
            issues_by_severity=issues_by_sev,
            issues_by_category=issues_by_cat,
            passed=passed,
            duration_ms=duration_ms,
            issues=all_issues,
        )

    def format_text_report(self, summary: ScanSummary) -> str:
        lines: list[str] = []
        lines.append("=" * 78)
        lines.append("  ОТЧЁТ СТАТИЧЕСКОГО АНАЛИЗА И БЕЗОПАСНОСТИ 1С (BSL / 1C:Enterprise)")
        lines.append("=" * 78)
        lines.append(f"Проверено файлов: {summary.total_files} | Найдено замечаний: {summary.total_issues} | Время: {summary.duration_ms} мс")
        lines.append(f"Статус проверки: {'[ПРОЙДЕНО]' if summary.passed else '[ОБНАРУЖЕНЫ КРИТИЧЕСКИЕ ДЕФЕКТЫ]'}")
        lines.append("-" * 78)

        if summary.issues_by_severity:
            sev_str = ", ".join(f"{k}: {v}" for k, v in summary.issues_by_severity.items())
            lines.append(f"По критичности: {sev_str}")
        if summary.issues_by_category:
            cat_str = ", ".join(f"{k}: {v}" for k, v in summary.issues_by_category.items())
            lines.append(f"По категориям:  {cat_str}")
        lines.append("-" * 78)

        if not summary.issues:
            lines.append("Уязвимостей и нарушений стандартов не обнаружено.")
            return "\n".join(lines)

        for idx, issue in enumerate(summary.issues, 1):
            sev_badge = f"[{issue.severity.value}]"
            lines.append(f"{idx}. {sev_badge} {issue.rule_id} ({issue.category.value}): {issue.message}")
            lines.append(f"   Файл: {issue.file_path}:{issue.line}")
            if issue.code_fragment:
                lines.append(f"   Код:  {issue.code_fragment}")
            if issue.recommendation:
                lines.append(f"   Совет: {issue.recommendation}")
            lines.append("")

        return "\n".join(lines)

    def format_sarif_report(self, summary: ScanSummary) -> str:
        """Export results in OASIS SARIF v2.1.0 JSON format for GitHub Security and CI/CD."""
        rules_map: dict[str, BSLRule] = {r.rule_id: r for r in self.rules}
        sarif_rules = []
        for r_id, r in rules_map.items():
            sarif_rules.append({
                "id": r.rule_id,
                "name": r.rule_id,
                "shortDescription": {"text": r.message},
                "help": {"text": r.recommendation or r.message},
                "properties": {"category": r.category.value, "severity": r.severity.value},
            })

        results = []
        for issue in summary.issues:
            level = "error" if issue.severity in (Severity.CRITICAL, Severity.HIGH) else "warning" if issue.severity == Severity.MEDIUM else "note"
            results.append({
                "ruleId": issue.rule_id,
                "level": level,
                "message": {"text": issue.message},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": Path(issue.file_path).as_uri()},
                        "region": {
                            "startLine": issue.line,
                            "startColumn": issue.col,
                            "snippet": {"text": issue.code_fragment},
                        },
                    }
                }],
            })

        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "1C-Consultant-Security-Scanner",
                        "informationUri": "https://github.com/ilnurcode/1c-consultant",
                        "rules": sarif_rules,
                    }
                },
                "results": results,
            }],
        }
        return json.dumps(sarif, ensure_ascii=False, indent=2)
