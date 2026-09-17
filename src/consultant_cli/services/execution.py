from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional
from consultant_cli.domain.infobases import InfobaseConfig
from consultant_cli.infrastructure.odata_client import ODataClient
from consultant_cli.infrastructure.playwright_client import Playwright1CClient

logger = logging.getLogger(__name__)


class ExecutionTools:
    """Provides tools for LLM agent to interact with 1C:Enterprise via Playwright & OData."""

    def __init__(self, base_config: InfobaseConfig) -> None:
        self.config = base_config
        self._odata: Optional[ODataClient] = None
        self._playwright: Optional[Playwright1CClient] = None

    @property
    def odata(self) -> ODataClient:
        if not self._odata:
            if not self.config.odata_url:
                raise ValueError(f"OData URL is not configured for database '{self.config.name}'")
            self._odata = ODataClient(
                base_url=self.config.odata_url,
                username=self.config.username,
                password=self.config.password,
            )
        return self._odata

    @property
    def playwright(self) -> Playwright1CClient:
        if not self._playwright:
            if not self.config.web_url:
                raise ValueError(f"Web URL is not configured for database '{self.config.name}'")
            self._playwright = Playwright1CClient(
                web_url=self.config.web_url,
                username=self.config.username,
                password=self.config.password,
                headless=self.config.headless,
                browser_type=self.config.browser_type,
            )
        return self._playwright

    def close(self) -> None:
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def get_definitions(self) -> list[dict[str, Any]]:
        """Returns tool declarations for tool-calling agent."""
        return [
            {
                "name": "browser_navigate",
                "description": "Open 1C Web Client or navigate to specific URL in 1C",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Optional specific URL, defaults to base web URL"}
                    },
                },
            },
            {
                "name": "browser_get_screen_state",
                "description": "Get current visible interactive elements (buttons, inputs, tables) from 1C Web Client",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "browser_click",
                "description": "Click on a button, menu item, link or table row by its text or CSS selector in 1C",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "Exact/partial text of button or selector"}
                    },
                    "required": ["target"],
                },
            },
            {
                "name": "browser_fill",
                "description": "Type text into a field in 1C by field label or selector",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "description": "Field label or selector"},
                        "value": {"type": "string", "description": "Text to enter"}
                    },
                    "required": ["field", "value"],
                },
            },
            {
                "name": "odata_query",
                "description": "Direct query to 1C OData endpoint to search catalogs or documents (e.g. Catalog_Номенклатура)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string", "description": "1C Entity name (e.g. Catalog_Номенклатура, Document_ЗаказКлиента)"},
                        "filter": {"type": "string", "description": "OData $filter expression (e.g. Description eq 'Товар 1')"},
                        "select": {"type": "array", "items": {"type": "string"}, "description": "List of fields to select"},
                        "top": {"type": "integer", "description": "Max rows to return (default 20)"}
                    },
                    "required": ["entity"],
                },
            },
            {
                "name": "odata_create",
                "description": "Create record directly in 1C via OData POST API",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string", "description": "1C Entity name"},
                        "data": {"type": "object", "description": "Key-value dictionary with field values"}
                    },
                    "required": ["entity", "data"],
                },
            },
            {
                "name": "odata_post_document",
                "description": "Post/conduct a document in 1C by its GUID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string", "description": "1C Document entity name"},
                        "guid": {"type": "string", "description": "Document Ref_Key GUID"}
                    },
                    "required": ["entity", "guid"],
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Dispatches tool execution."""
        if name == "browser_navigate":
            return self.playwright.navigate(arguments.get("url"))
        elif name == "browser_get_screen_state":
            return self.playwright.get_interactive_elements()
        elif name == "browser_click":
            return self.playwright.click(arguments["target"])
        elif name == "browser_fill":
            return self.playwright.fill(arguments["field"], arguments["value"])
        elif name == "odata_query":
            return self.odata.query(
                entity=arguments["entity"],
                filter_expr=arguments.get("filter", ""),
                select=arguments.get("select"),
                top=arguments.get("top", 20),
            )
        elif name == "odata_create":
            return self.odata.create(arguments["entity"], arguments["data"])
        elif name == "odata_post_document":
            return self.odata.post_document(arguments["entity"], arguments["guid"])
        else:
            raise ValueError(f"Unknown tool: {name}")


class ExecutorService:
    """Executes generated instructions step by step in 1C using an AI ReAct loop."""

    def __init__(self, base_config: InfobaseConfig, agent_service: Any | None = None, agent_profile: str = "") -> None:
        self.tools = ExecutionTools(base_config)
        self.agent_service = agent_service
        self.agent_profile = agent_profile

    def _decision_schema(self) -> dict[str, Any]:
        tool_names = [item["name"] for item in self.tools.get_definitions()]
        return {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "tool": {"type": "string", "enum": [*tool_names, "done", "fail"]},
                "arguments": {"type": "object"},
                "message": {"type": "string"},
            },
            "required": ["thought", "tool", "arguments", "message"],
            "additionalProperties": False,
        }

    def _agent_decide(self, instruction_text: str, screen_state: Any, logs: list[str]) -> dict[str, Any]:
        if not self.agent_service:
            raise RuntimeError("AI-подключение не передано в ExecutorService.")
        profile = self.agent_service.get_profile(self.agent_profile or None)
        prompt = f"""
Ты агент-исполнитель консультанта 1С. Нужно выполнить инструкцию в веб-клиенте 1С.

Правила:
- Действуй маленькими шагами: сначала смотри экран, затем кликай/заполняй/проверяй.
- Для быстрых проверок справочников и документов используй OData.
- Не выдумывай селекторы. Для browser_click используй видимый текст элемента из screen_state.
- Если данных недостаточно или действие опасное — верни tool='fail' с причиной.
- Если инструкция полностью выполнена — верни tool='done'.

Доступные инструменты:
{json.dumps(self.tools.get_definitions(), ensure_ascii=False, indent=2)}

Инструкция:
{instruction_text[:12000]}

Текущее состояние экрана 1С (видимые интерактивные элементы):
{json.dumps(screen_state, ensure_ascii=False, default=str)[:12000]}

Журнал уже выполненных шагов:
{json.dumps(logs[-20:], ensure_ascii=False, indent=2)}

Ответь строго JSON по схеме. Выбери ровно один следующий инструмент.
"""
        return self.agent_service.generate(profile, prompt, self._decision_schema())

    def execute_instruction(self, instruction_text: str, max_steps: int = 20) -> dict[str, Any]:
        """Runs the ReAct execution loop for the instruction."""
        logger.info(f"Starting execution for base: {self.tools.config.name}")
        logs: list[str] = []
        try:
            if self.tools.config.web_url:
                logs.append(f"Opening Web Client: {self.tools.config.web_url}")
                nav_res = self.tools.call_tool("browser_navigate", {})
                logs.append(f"Connected: {nav_res.get('title') or nav_res.get('url')}")
            else:
                logs.append("Web URL is not configured; only OData tools are available.")

            if not self.agent_service:
                return {
                    "ok": False,
                    "base": self.tools.config.name,
                    "error": "AI не подключён к исполнителю. Подключите AI в меню, затем повторите выполнение.",
                    "logs": logs,
                }

            for step in range(1, max_steps + 1):
                screen_state = self.tools.call_tool("browser_get_screen_state", {}) if self.tools.config.web_url else []
                decision = self._agent_decide(instruction_text, screen_state, logs)
                tool = str(decision.get("tool", "fail"))
                arguments = decision.get("arguments") or {}
                message = str(decision.get("message", ""))
                logs.append(f"Step {step}: {tool} {json.dumps(arguments, ensure_ascii=False)} — {message}")

                if tool == "done":
                    return {"ok": True, "base": self.tools.config.name, "steps_completed": True, "logs": logs}
                if tool == "fail":
                    return {"ok": False, "base": self.tools.config.name, "error": message or "Agent failed", "logs": logs}
                result = self.tools.call_tool(tool, arguments)
                logs.append(f"Step {step} result: {json.dumps(result, ensure_ascii=False, default=str)[:2000]}")

            return {
                "ok": False,
                "base": self.tools.config.name,
                "error": f"Достигнут лимит шагов ({max_steps}); выполнение остановлено для безопасности.",
                "logs": logs,
            }
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {
                "ok": False,
                "base": self.tools.config.name,
                "error": str(e),
                "logs": logs,
            }
        finally:
            self.tools.close()
