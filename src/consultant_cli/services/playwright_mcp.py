from __future__ import annotations

import subprocess
import time
import json
import re
from pathlib import Path

from consultant_cli.errors import ConsultantError
from consultant_cli.infrastructure.store import RepositoryPaths
from consultant_cli.services.connections import ConnectionProfile


class PlaywrightMcpService:
    """Starts a local Playwright MCP session without accepting credentials."""

    def __init__(self, paths: RepositoryPaths) -> None:
        self.paths = paths
        self._login_process: subprocess.Popen[str] | None = None

    def start_manual_login(self, profile: ConnectionProfile) -> None:
        if self._login_process and self._login_process.poll() is None:
            raise ConsultantError("Окно входа в 1С уже открыто.")
        profile_dir = self._browser_profile(profile)
        profile_dir.mkdir(parents=True, exist_ok=True)
        runner = self.paths.root / "mcp" / "playwright-scenario-runner.mjs"
        self._login_process = subprocess.Popen(
            ["node", str(runner), "session", str(profile_dir), profile.web_url],
            cwd=self.paths.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        if not self._wait_ready(self._login_process):
            stderr = self._login_process.stderr.read() if self._login_process.stderr else ""
            self._login_process = None
            raise ConsultantError(f"Не удалось открыть окно 1С через Playwright MCP. {stderr.strip()}")

    def finish_manual_login(self) -> bool:
        process = self._login_process
        if not process:
            return False
        if process.stdin:
            process.stdin.write("LOGIN_COMPLETE\n")
            process.stdin.flush()
        if not process.stdout:
            return False
        return process.stdout.readline().strip() == "LOGIN_CONFIRMED"

    def close_session(self) -> None:
        process = self._login_process
        if not process:
            return
        if process.stdin:
            process.stdin.write("STOP\n")
            process.stdin.flush()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
        self._login_process = None

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        """Call one Playwright MCP tool in the already authenticated session."""
        process = self._login_process
        if not process or process.poll() is not None or not process.stdin or not process.stdout:
            raise ConsultantError("Нет активной сессии 1С. Сначала выберите «Войти в 1С».")
        process.stdin.write("CALL " + json.dumps({"name": name, "arguments": arguments or {}}, ensure_ascii=False) + "\n")
        process.stdin.flush()
        line = process.stdout.readline().strip()
        if not line.startswith("RESULT "):
            raise ConsultantError("Playwright MCP вернул некорректный ответ.")
        payload = json.loads(line[7:])
        if not payload.get("ok"):
            raise ConsultantError(f"Playwright MCP: {payload.get('error', 'неизвестная ошибка')}")
        return payload["result"]

    def run_customer_order(self, request) -> dict[str, object]:
        """Execute the one approved creation route using accessible MCP controls only.

        Every lookup is exact and must resolve to one control.  A changed 1С
        form therefore stops safely instead of guessing a control or price.
        """
        self._click_named("Продажи")
        self._click_named("Заказы клиентов")
        self._click_named("Создать")
        self._fill_named(("Клиент", "Контрагент"), request.customer)
        self._fill_named(("Организация",), request.organization)
        self._fill_named(("Договор",), request.contract)
        self._click_named("Добавить")
        self._fill_named(("Номенклатура", "Товар"), request.product)
        self._fill_named(("Количество",), request.quantity)
        snapshot = self._snapshot()
        if not re.search(r"(?<!\d)100(?:[\s ]*RUB|[\s ]*₽|[,.]00)?(?!\d)", snapshot, re.IGNORECASE):
            raise ConsultantError("Автоматическая цена 100 RUB не распознана; заказ не записан.")
        self._click_named("Записать")
        snapshot = self._snapshot()
        number = self._document_number(snapshot)
        if not number:
            raise ConsultantError("После записи не удалось однозначно распознать номер заказа.")
        return {"number": number, "snapshot": snapshot[:2000]}

    def post_customer_order(self, number: str) -> None:
        if not number:
            raise ConsultantError("Не задан номер заказа для проведения.")
        snapshot = self._snapshot()
        if number not in snapshot:
            raise ConsultantError("Открытая форма не соответствует заказу из подтверждённого запуска.")
        self._click_named("Провести")

    def _snapshot(self) -> str:
        result = self.call_tool("browser_snapshot", {"depth": 12})
        return json.dumps(result, ensure_ascii=False)

    def _click_named(self, name: str) -> None:
        ref = self._unique_ref(name, self._snapshot())
        self.call_tool("browser_click", {"target": ref, "element": name})
        self.call_tool("browser_wait_for", {"time": 1})

    def _fill_named(self, names: tuple[str, ...], value: str) -> None:
        snapshot = self._snapshot()
        choices = [self._unique_ref(name, snapshot, optional=True) for name in names]
        refs = [ref for ref in choices if ref]
        if len(refs) != 1:
            raise ConsultantError(f"Поле «{' / '.join(names)}» не распознано однозначно; сценарий остановлен.")
        self.call_tool("browser_fill_form", {"fields": [{"target": refs[0], "name": names[0], "type": "textbox", "value": value}]})
        self.call_tool("browser_wait_for", {"time": 1})

    @staticmethod
    def _unique_ref(name: str, snapshot: str, optional: bool = False) -> str | None:
        # Snapshot is returned as text content by MCP; a ref belongs to the line
        # describing the accessible control.  More than one match is unsafe.
        matches = re.findall(rf"[^\\n]*{re.escape(name)}[^\\n]*\[ref=([^\]]+)\]", snapshot, flags=re.IGNORECASE)
        unique = list(dict.fromkeys(matches))
        if len(unique) == 1:
            return unique[0]
        if optional and not unique:
            return None
        raise ConsultantError(f"Элемент «{name}» распознан {len(unique)} раз; выбор наугад запрещён.")

    @staticmethod
    def _document_number(snapshot: str) -> str:
        matches = re.findall(r"(?:Заказ клиента|Заказ покупателя)[^№]{0,30}№\s*([A-Za-zА-Яа-я0-9-]+)", snapshot, re.IGNORECASE)
        unique = list(dict.fromkeys(matches))
        return unique[0] if len(unique) == 1 else ""

    def _browser_profile(self, profile: ConnectionProfile) -> Path:
        safe_name = "".join(char if char.isalnum() else "-" for char in profile.name).strip("-")
        return self.paths.data_root / "automation" / "browser-profiles" / (safe_name or "default")

    @staticmethod
    def _wait_ready(process: subprocess.Popen[str], timeout_seconds: float = 45) -> bool:
        if not process.stdout:
            return False
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            line = process.stdout.readline().strip()
            if line == "READY_FOR_MANUAL_LOGIN":
                return True
            if process.poll() is not None:
                return False
        return False
