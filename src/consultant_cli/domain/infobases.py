from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _get_bases_file_path() -> Path:
    config_dir = Path.home() / ".1c-consultant"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "bases.json"


def _obfuscate(text: str) -> str:
    if not text:
        return ""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _deobfuscate(text: str) -> str:
    if not text:
        return ""
    try:
        return base64.b64decode(text.encode("ascii")).decode("utf-8")
    except Exception:
        return text


@dataclass(slots=True)
class InfobaseConfig:
    name: str
    web_url: str = ""
    odata_url: str = ""
    username: str = ""
    password: str = ""  # stored in-memory plaintext, obfuscated on disk
    auth_type: str = "basic"  # "basic" | "windows" | "anonymous"
    description: str = ""
    is_active: bool = False
    browser_type: str = "chromium"
    headless: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "web_url": self.web_url,
            "odata_url": self.odata_url,
            "username": self.username,
            "password_b64": _obfuscate(self.password),
            "auth_type": self.auth_type,
            "description": self.description,
            "is_active": self.is_active,
            "browser_type": self.browser_type,
            "headless": self.headless,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InfobaseConfig":
        raw_pwd = data.get("password", "")
        pwd_b64 = data.get("password_b64", "")
        password = _deobfuscate(pwd_b64) if pwd_b64 else raw_pwd

        return cls(
            name=str(data.get("name", "")),
            web_url=str(data.get("web_url", "")),
            odata_url=str(data.get("odata_url", "")),
            username=str(data.get("username", "")),
            password=str(password),
            auth_type=str(data.get("auth_type", "basic")),
            description=str(data.get("description", "")),
            is_active=bool(data.get("is_active", False)),
            browser_type=str(data.get("browser_type", "chromium")),
            headless=bool(data.get("headless", False)),
        )


class InfobaseManager:
    """Manages 1C Infobase configurations (add, list, update, remove, select active)."""

    def __init__(self, file_path: Path | None = None) -> None:
        self.file_path = file_path or _get_bases_file_path()

    def load_all(self) -> list[InfobaseConfig]:
        if not self.file_path.is_file():
            return []
        try:
            content = self.file_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, list):
                return [InfobaseConfig.from_dict(item) for item in data]
            if isinstance(data, dict) and "bases" in data:
                return [InfobaseConfig.from_dict(item) for item in data["bases"]]
            return []
        except Exception:
            return []

    def save_all(self, bases: list[InfobaseConfig]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        raw_list = [b.to_dict() for b in bases]
        self.file_path.write_text(json.dumps(raw_list, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, name: str) -> InfobaseConfig | None:
        bases = self.load_all()
        for b in bases:
            if b.name.casefold() == name.casefold():
                return b
        return None

    def get_active(self) -> InfobaseConfig | None:
        bases = self.load_all()
        for b in bases:
            if b.is_active:
                return b
        if bases:
            return bases[0]
        return None

    def add_or_update(self, config: InfobaseConfig) -> None:
        bases = self.load_all()
        found = False
        for i, b in enumerate(bases):
            if b.name.casefold() == config.name.casefold():
                bases[i] = config
                found = True
                break
        if not found:
            # If this is the first base, make it active
            if not bases:
                config.is_active = True
            bases.append(config)
        self.save_all(bases)

    def set_active(self, name: str) -> bool:
        bases = self.load_all()
        target_found = False
        for b in bases:
            if b.name.casefold() == name.casefold():
                b.is_active = True
                target_found = True
            else:
                b.is_active = False
        if target_found:
            self.save_all(bases)
        return target_found

    def delete(self, name: str) -> bool:
        bases = self.load_all()
        initial_len = len(bases)
        new_bases = [b for b in bases if b.name.casefold() != name.casefold()]
        if len(new_bases) < initial_len:
            # If deleted was active and others exist, activate first
            if new_bases and not any(b.is_active for b in new_bases):
                new_bases[0].is_active = True
            self.save_all(new_bases)
            return True
        return False
