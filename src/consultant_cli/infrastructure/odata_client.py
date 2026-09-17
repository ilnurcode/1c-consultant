from __future__ import annotations

import base64
import json
import logging
from typing import Any
import urllib.request
import urllib.error
import urllib.parse

logger = logging.getLogger(__name__)


class ODataClient:
    """Synchronous OData v3/v4 client for 1C Enterprise without external dependencies."""

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout

    def _get_headers(self, content_type: str = "application/json;charset=utf-8") -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": content_type,
            "User-Agent": "1C-Consultant-OData/1.0",
        }
        if self.username:
            auth_str = f"{self.username}:{self.password}"
            b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {b64_auth}"
        return headers

    def test_connection(self) -> dict[str, Any]:
        """Test reachability of the OData service and retrieve metadata overview."""
        url = f"{self.base_url}/$metadata"
        try:
            req = urllib.request.Request(url, headers=self._get_headers("application/xml"), method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status_code = resp.status
                return {
                    "ok": status_code in (200, 201),
                    "status_code": status_code,
                    "url": url,
                    "message": "Connected successfully to 1C OData endpoint",
                }
        except urllib.error.HTTPError as e:
            return {
                "ok": False,
                "status_code": e.code,
                "url": url,
                "error": f"HTTP Error {e.code}: {e.reason}",
            }
        except Exception as e:
            return {
                "ok": False,
                "status_code": 0,
                "url": url,
                "error": str(e),
            }

    def query(
        self,
        entity: str,
        select: list[str] | None = None,
        filter_expr: str = "",
        order_by: str = "",
        top: int = 50,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        """Query entities (e.g. Catalog_Номенклатура, Document_ПоступлениеТоваровУслуг)."""
        params: dict[str, str] = {
            "$format": "json",
            "$top": str(top),
            "$skip": str(skip),
        }
        if select:
            params["$select"] = ",".join(select)
        if filter_expr:
            params["$filter"] = filter_expr
        if order_by:
            params["$orderby"] = order_by

        query_str = urllib.parse.urlencode(params)
        url = f"{self.base_url}/{urllib.parse.quote(entity)}?{query_str}"

        req = urllib.request.Request(url, headers=self._get_headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    return data.get("value", [data])
                elif isinstance(data, list):
                    return data
                return []
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OData query failed (HTTP {e.code}): {err_body}") from e

    def get_by_guid(self, entity: str, guid: str) -> dict[str, Any]:
        """Fetch a specific entity by Ref_Key / GUID."""
        url = f"{self.base_url}/{urllib.parse.quote(entity)}(guid'{guid}')?$format=json"
        req = urllib.request.Request(url, headers=self._get_headers(), method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def create(self, entity: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new entity record via POST."""
        url = f"{self.base_url}/{urllib.parse.quote(entity)}?$format=json"
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=self._get_headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OData create failed (HTTP {e.code}): {err_body}") from e

    def update(self, entity: str, guid: str, data: dict[str, Any], partial: bool = True) -> dict[str, Any]:
        """Update an existing entity via PATCH (partial) or PUT (full)."""
        url = f"{self.base_url}/{urllib.parse.quote(entity)}(guid'{guid}')?$format=json"
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        method = "PATCH" if partial else "PUT"
        req = urllib.request.Request(url, data=body, headers=self._get_headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw else {"ok": True}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OData update failed (HTTP {e.code}): {err_body}") from e

    def post_document(self, entity: str, guid: str) -> dict[str, Any]:
        """Post a 1C document via OData Post action."""
        url = f"{self.base_url}/{urllib.parse.quote(entity)}(guid'{guid}')/Post?$format=json"
        req = urllib.request.Request(url, data=b"{}", headers=self._get_headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw else {"ok": True}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OData Post Document failed (HTTP {e.code}): {err_body}") from e
