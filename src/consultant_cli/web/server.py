from __future__ import annotations

import json
import logging
import mimetypes
import os
import threading
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from consultant_cli.app import Application
from consultant_cli.domain.infobases import InfobaseConfig
from consultant_cli.services.scanner.models import ScanSummary, Severity
from consultant_cli.services.testgen import WebTestGenerator, WebTestScenario, WebTestSuite
from consultant_cli.services.testrunner import Playwright1CTestRunner

logger = logging.getLogger(__name__)


class ConsultantWebHandler(SimpleHTTPRequestHandler):
    """HTTP request handler providing REST API and serving UI assets."""

    app_instance: Application

    def __init__(self, *args, **kwargs):
        static_folder = Path(__file__).parent / "static"
        super().__init__(*args, directory=str(static_folder), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._send_json({
                "status": "online",
                "version": "5.0.1",
                "rules_count": len(self.app_instance.scanner.rules),
                "active_base": getattr(self.app_instance.infobases.get_active(), "name", "None"),
            })
            return
        elif parsed.path == "/api/bases":
            bases = [b.to_dict() for b in self.app_instance.infobases.load_all()]
            self._send_json({"bases": bases})
            return
        elif parsed.path == "/api/rules":
            rules = [
                {
                    "rule_id": r.rule_id,
                    "category": r.category.value,
                    "severity": r.severity.value,
                    "message": r.message,
                    "recommendation": r.recommendation,
                }
                for r in self.app_instance.scanner.rules
            ]
            self._send_json({"rules": rules})
            return

        # Serve static files or fallback to index.html for SPA
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if parsed.path == "/api/scan":
            self._handle_scan(data)
        elif parsed.path == "/api/test-gen":
            self._handle_test_gen(data)
        elif parsed.path == "/api/test-run":
            self._handle_test_run(data)
        elif parsed.path == "/api/bases":
            self._handle_add_base(data)
        else:
            self._send_error_json(HTTPStatus.NOT_FOUND, f"Неизвестный эндпоинт: {parsed.path}")

    def _handle_scan(self, data: dict[str, Any]):
        code = str(data.get("code", "")).strip()
        path_str = str(data.get("path", "")).strip()

        if code:
            issues = self.app_instance.scanner.scan_code(code, file_name="web_editor.bsl")
            sev_counts: dict[str, int] = {}
            cat_counts: dict[str, int] = {}
            for issue in issues:
                sev_counts[issue.severity.value] = sev_counts.get(issue.severity.value, 0) + 1
                cat_counts[issue.category.value] = cat_counts.get(issue.category.value, 0) + 1
            summary = ScanSummary(
                total_files=1,
                total_issues=len(issues),
                issues_by_severity=sev_counts,
                issues_by_category=cat_counts,
                passed=(sev_counts.get(Severity.CRITICAL.value, 0) == 0 and sev_counts.get(Severity.HIGH.value, 0) == 0),
                issues=issues,
            )
            self._send_json(summary.to_dict())
            return

        if path_str:
            p = Path(path_str).resolve()
            if p.is_file():
                issues = self.app_instance.scanner.scan_file(p)
                sev_counts = {}
                cat_counts = {}
                for issue in issues:
                    sev_counts[issue.severity.value] = sev_counts.get(issue.severity.value, 0) + 1
                    cat_counts[issue.category.value] = cat_counts.get(issue.category.value, 0) + 1
                summary = ScanSummary(
                    total_files=1,
                    total_issues=len(issues),
                    issues_by_severity=sev_counts,
                    issues_by_category=cat_counts,
                    passed=(sev_counts.get(Severity.CRITICAL.value, 0) == 0 and sev_counts.get(Severity.HIGH.value, 0) == 0),
                    issues=issues,
                )
                self._send_json(summary.to_dict())
                return
            elif p.is_dir():
                summary = self.app_instance.scanner.scan_directory(p)
                self._send_json(summary.to_dict())
                return
            else:
                self._send_error_json(HTTPStatus.BAD_REQUEST, f"Указанный путь не найден: {p}")
                return

        self._send_error_json(HTTPStatus.BAD_REQUEST, "Передайте 'code' или 'path' для сканирования.")

    def _handle_test_gen(self, data: dict[str, Any]):
        t_type = data.get("type", "document")
        meta = data.get("metadata", "ЗаказКлиента")
        sub = data.get("subsystem", "Продажи")
        gherkin = data.get("gherkin", "")

        if t_type == "from-feature" and gherkin:
            suite = WebTestGenerator.from_gherkin_text(gherkin)
            self._send_json(suite.to_dict())
            return
        elif t_type == "smoke":
            objs = [o.strip() for o in data.get("objects", "").split(",") if o.strip()] or [meta]
            suite = WebTestGenerator.generate_smoke_test(sub, objs)
            self._send_json(suite.to_dict())
            return
        else:
            header_fields = data.get("header_fields", {"Клиент": "ООО Ромашка"})
            table_rows = data.get("table_rows", [{"Номенклатура": "Товар 1", "Количество": "1", "Цена": "100"}])
            sc = WebTestGenerator.generate_document_test(
                doc_name=meta,
                subsystem=sub,
                header_fields=header_fields,
                table_rows=table_rows,
                post=bool(data.get("post", True)),
            )
            suite = WebTestSuite(id=f"suite_{sc.id}", title=f"Тест {meta}", scenarios=[sc])
            self._send_json(suite.to_dict())

    def _handle_test_run(self, data: dict[str, Any]):
        base_name = data.get("base", "")
        cfg = self.app_instance.infobases.get(base_name) if base_name else self.app_instance.infobases.get_active()
        if not cfg:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Активная база не найдена.")
            return

        scenario_data = data.get("scenario")
        if not scenario_data:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Отсутствуют данные сценария.")
            return

        if "scenarios" in scenario_data:
            suite = WebTestSuite.from_dict(scenario_data)
        elif "steps" in scenario_data:
            sc = WebTestScenario.from_dict(scenario_data)
            suite = WebTestSuite(id=f"suite_{sc.id}", title=sc.title, scenarios=[sc])
        else:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Некорректный формат сценария.")
            return

        runner = Playwright1CTestRunner(cfg)
        result = runner.run_suite(suite)
        self._send_json(result.to_dict())

    def _handle_add_base(self, data: dict[str, Any]):
        cfg = InfobaseConfig(
            name=data.get("name", "NewBase"),
            web_url=data.get("web_url", ""),
            odata_url=data.get("odata_url", ""),
            username=data.get("username", ""),
            password=data.get("password", ""),
            is_active=bool(data.get("is_active", False)),
            browser_type=data.get("browser_type", "msedge"),
            headless=bool(data.get("headless", False)),
        )
        self.app_instance.infobases.add_or_update(cfg)
        self._send_json({"added": cfg.name, "is_active": cfg.is_active})

    def _send_json(self, data: Any):
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, status: int, message: str):
        payload = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run_web_server(app: Application, host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True) -> None:
    """Starts the 1C-Consultant local Web Dashboard server."""
    ConsultantWebHandler.app_instance = app
    server_address = (host, port)
    try:
        httpd = ThreadingHTTPServer(server_address, ConsultantWebHandler)
    except OSError:
        # fallback to port 8081 if 8080 busy
        server_address = (host, port + 1)
        httpd = ThreadingHTTPServer(server_address, ConsultantWebHandler)

    actual_port = server_address[1]
    url = f"http://{host}:{actual_port}"
    print(f"\n" + "=" * 70)
    print(f"  ВЕБ-ИНТЕРФЕЙС 1C-CONSULTANT ЗАПУЩЕН: {url}")
    print(f"  Аудит уязвимостей | Стандарты v8std | Playwright Web-тестирование")
    print(f"  Нажмите Ctrl+C для остановки сервера")
    print("=" * 70 + "\n")

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка веб-сервера...")
    finally:
        httpd.server_close()
