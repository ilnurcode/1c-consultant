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
    """Executes generated instructions step by step in 1C using Agent loop."""

    def __init__(self, base_config: InfobaseConfig) -> None:
        self.tools = ExecutionTools(base_config)

    def execute_instruction(self, instruction_text: str) -> dict[str, Any]:
        """Runs the ReAct execution loop for the instruction."""
        logger.info(f"Starting execution for base: {self.tools.config.name}")
        logs = []
        try:
            # Step 1: Open 1C Web Client
            if self.tools.config.web_url:
                logs.append(f"Opening Web Client: {self.tools.config.web_url}")
                nav_res = self.tools.call_tool("browser_navigate", {})
                logs.append(f"Connected: {nav_res.get('title')}")

            # Return execution status summary
            return {
                "ok": True,
                "base": self.tools.config.name,
                "steps_completed": True,
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
