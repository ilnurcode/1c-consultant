from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from consultant_cli.errors import InvalidConfigurationError
from consultant_cli.infrastructure.store import atomic_write_json


@dataclass(frozen=True, slots=True)
class ConnectionProfile:
    """Safe, persistent description of a 1C web publication.

    Credentials intentionally do not belong here. They are accepted only for
    the current program run and are kept by ODataService in memory.
    """

    name: str
    web_url: str

    @property
    def odata_url(self) -> str:
        return f"{self.web_url}odata/standard.odata"


class ConnectionProfiles:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self) -> list[ConnectionProfile]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidConfigurationError("Не удалось прочитать список подключений 1С.") from exc
        records = payload.get("profiles", []) if isinstance(payload, dict) else []
        return [
            ConnectionProfile(name=str(item["name"]), web_url=normalize_web_url(str(item["web_url"])))
            for item in records
            if isinstance(item, dict) and item.get("name") and item.get("web_url")
        ]

    def save(self, profiles: list[ConnectionProfile]) -> None:
        names = [profile.name.casefold() for profile in profiles]
        if len(names) != len(set(names)):
            raise InvalidConfigurationError("Названия подключений 1С должны быть уникальными.")
        atomic_write_json(self.path, {"profiles": [asdict(profile) for profile in profiles]})


def normalize_web_url(raw_url: str) -> str:
    value = raw_url.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise InvalidConfigurationError("Укажите адрес веб-клиента 1С вида http://сервер/база/.")
    path = parsed.path.rstrip("/") + "/"
    if path.endswith("/odata/standard.odata/"):
        raise InvalidConfigurationError("Нужен адрес веб-клиента 1С, а не адрес OData.")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
