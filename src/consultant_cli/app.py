from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from consultant_cli.infrastructure.settings import AppSettings, load_settings
from consultant_cli.infrastructure.store import ProjectStore, RepositoryPaths
from consultant_cli.services.agents import AgentService
from consultant_cli.services.examples import ExampleRegistry
from consultant_cli.services.export import ExportService
from consultant_cli.services.validation import ValidationService
from consultant_cli.services.workflow import WorkflowService
from consultant_cli.services.analytics import AnalyticsService
from consultant_cli.services.telemetry import TelemetryService
from consultant_cli.services.migration import MigrationService
from consultant_cli.services.odata import ODataService
from consultant_cli.services.connections import ConnectionProfile, ConnectionProfiles
from consultant_cli.services.playwright_mcp import PlaywrightMcpService
from consultant_cli.services.automation import AutomationHistory


@dataclass(slots=True)
class Application:
    paths: RepositoryPaths
    settings: AppSettings
    store: ProjectStore
    agents: AgentService
    workflow: WorkflowService
    examples: ExampleRegistry
    exports: ExportService
    validation: ValidationService
    analytics: AnalyticsService
    telemetry: TelemetryService
    migrations: MigrationService
    odata: ODataService
    connections: ConnectionProfiles
    active_connection: ConnectionProfile | None = None
    playwright: PlaywrightMcpService | None = None
    automation: AutomationHistory | None = None
    browser_login_completed: bool = False


def build_application(start: Path | None = None) -> Application:
    paths = RepositoryPaths.discover(start)
    settings = load_settings(paths.local_config)
    store = ProjectStore(paths)
    agents = AgentService(paths, settings, paths.local_config)
    workflow = WorkflowService(paths, store, settings, agents)
    examples = ExampleRegistry(paths, store)
    application = Application(
        paths=paths,
        settings=settings,
        store=store,
        agents=agents,
        workflow=workflow,
        examples=examples,
        exports=ExportService(store),
        validation=ValidationService(paths, store),
        analytics=workflow.analytics,
        telemetry=workflow.telemetry,
        migrations=MigrationService(paths, store, workflow.analytics),
        odata=ODataService(),
        connections=ConnectionProfiles(paths.connections_config),
    )
    application.playwright = PlaywrightMcpService(paths)
    application.automation = AutomationHistory(paths.automation_history)
    return application
