from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from consultant_cli.errors import InvalidConfigurationError, ODataError

_IDENTIFIER = re.compile(r"^[^\W\d][\w]*(?:/[^\W\d][\w]*)*$", re.UNICODE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class ODataConfiguration:
    service_url: str = ""
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_url", _normalize_url(self.service_url))
        if not 0.1 <= self.timeout_seconds <= 300:
            raise InvalidConfigurationError("Тайм-аут OData должен быть от 0.1 до 300 секунд.")


class ODataService:
    """Strictly read-only anonymous OData client, bound to a chosen publication."""

    def __init__(self, configuration: ODataConfiguration | None = None, *, opener: Callable[..., Any] = urlopen) -> None:
        self.configuration = configuration or ODataConfiguration()
        self._opener = opener

    def for_service_url(self, url: str) -> "ODataService":
        return ODataService(ODataConfiguration(url, self.configuration.timeout_seconds), opener=self._opener)

    def status(self, *, remote: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"configured": bool(self.configuration.service_url), "service_url": self.configuration.service_url, "read_only": True, "timeout_seconds": self.configuration.timeout_seconds}
        if remote:
            entities = self.list_entities()
            result.update({"reachable": True, "entity_count": entities["count"]})
        return result

    def list_entities(self) -> dict[str, Any]:
        try:
            root = ElementTree.fromstring(self._request("$metadata", "application/xml"))
        except ElementTree.ParseError as exc:
            raise ODataError("1С вернула некорректный XML в $metadata.") from exc
        result = []
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] == "EntitySet" and node.attrib.get("Name"):
                result.append({"name": node.attrib["Name"], "entity_type": node.attrib.get("EntityType", "")})
        return {"service_url": self.configuration.service_url, "count": len(result), "entities": sorted(result, key=lambda item: item["name"].casefold())}

    def query(self, entity: str, *, select: list[str] | None = None, filter_expression: str = "", order_by: str = "", expand: str = "", top: int = 100, skip: int = 0) -> dict[str, Any]:
        entity = _identifier(entity, "Имя OData-сущности")
        selected = [_identifier(field, "Поле $select") for field in (select or [])]
        if not 1 <= top <= 1000 or not 0 <= skip <= 1_000_000:
            raise InvalidConfigurationError("Недопустимый диапазон постраничного чтения OData.")
        pairs: list[tuple[str, str | int]] = [("$format", "json"), ("$top", top), ("$skip", skip)]
        for key, value in (("$select", ",".join(selected)), ("$filter", _expression(filter_expression, "$filter")), ("$orderby", _expression(order_by, "$orderby")), ("$expand", _expression(expand, "$expand"))):
            if value: pairs.append((key, value))
        try:
            payload = json.loads(self._request(f"{quote(entity, safe='_')}?{urlencode(pairs)}", "application/json").decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ODataError("1С вернула некорректный JSON.") from exc
        rows, next_link = _rows(payload)
        return {"entity": entity, "count": len(rows), "rows": rows, "next_link": next_link, "request": {"select": selected, "filter": filter_expression, "order_by": order_by, "expand": expand, "top": top, "skip": skip}}

    def _request(self, relative: str, accept: str) -> bytes:
        if not self.configuration.service_url:
            raise InvalidConfigurationError("Сначала выберите базу 1С: адрес OData формируется из её веб-адреса.")
        request = Request(f"{self.configuration.service_url}/{relative}", headers={"Accept": accept, "DataServiceVersion": "3.0", "MaxDataServiceVersion": "3.0", "User-Agent": "1C-Consultant-OData/2.0"}, method="GET")
        try:
            with self._opener(request, timeout=self.configuration.timeout_seconds) as response: return response.read()
        except HTTPError as exc: raise ODataError(f"OData 1С вернул HTTP {exc.code} для {relative.split('?', 1)[0]}.") from exc
        except (URLError, TimeoutError, OSError) as exc: raise ODataError(f"Не удалось обратиться к OData 1С: {getattr(exc, 'reason', exc)}") from exc


def _normalize_url(value: str) -> str:
    value = value.strip()
    if not value: return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise InvalidConfigurationError("Адрес OData должен быть адресом публикации без встроенных учётных данных.")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _identifier(value: str, label: str) -> str:
    value = value.strip()
    if len(value) > 200 or not _IDENTIFIER.fullmatch(value): raise InvalidConfigurationError(f"{label} содержит недопустимые символы.")
    return value


def _expression(value: str, label: str) -> str:
    value = value.strip()
    if len(value) > 4000 or _CONTROL.search(value): raise InvalidConfigurationError(f"Параметр {label} содержит недопустимые символы.")
    return value


def _rows(payload: Any) -> tuple[list[Any], str]:
    if not isinstance(payload, dict): raise ODataError("OData JSON должен содержать объект верхнего уровня.")
    next_link = str(payload.get("@odata.nextLink") or payload.get("odata.nextLink") or "")
    if isinstance(payload.get("value"), list): return payload["value"], next_link
    legacy = payload.get("d")
    if isinstance(legacy, dict) and isinstance(legacy.get("results"), list): return legacy["results"], str(legacy.get("__next") or next_link)
    if isinstance(legacy, list): return legacy, next_link
    raise ODataError("OData JSON не содержит коллекцию value или d.results.")
