from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


LEGACY_APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "WiFiQuickSwitcher"
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "WifiAssistance"
PROFILES_PATH = APP_DIR / "profiles.json"


def ensure_app_dir() -> None:
    if not APP_DIR.exists() and LEGACY_APP_DIR.exists():
        try:
            shutil.copytree(LEGACY_APP_DIR, APP_DIR)
        except OSError:
            APP_DIR.mkdir(parents=True, exist_ok=True)
    else:
        APP_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class WifiProfile:
    display_name: str
    ssid: str
    password: str
    security_type: str = "WPA2-Personal"

    @classmethod
    def from_dict(cls, data: dict) -> "WifiProfile":
        return cls(
            display_name=str(data.get("display_name", "")).strip(),
            ssid=str(data.get("ssid", "")).strip(),
            password=str(data.get("password", "")),
            security_type=str(data.get("security_type", "WPA2-Personal")).strip()
            or "WPA2-Personal",
        )

    def validate(self) -> None:
        if not self.display_name:
            raise ValueError("Display name is required.")
        if not self.ssid:
            raise ValueError("SSID is required.")
        if self.security_type not in {"WPA2-Personal", "WPA3-Personal"}:
            raise ValueError("Security type must be WPA2-Personal or WPA3-Personal.")


class ProfileStore:
    def __init__(self, path: Path = PROFILES_PATH) -> None:
        self.path = path
        ensure_app_dir()
        if not self.path.exists():
            self.save_profiles([])

    def load_profiles(self) -> list[WifiProfile]:
        try:
            with self.path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Profiles file is not valid JSON: {self.path}") from exc
        except OSError as exc:
            raise RuntimeError(f"Could not read profiles file: {exc}") from exc

        if not isinstance(raw, list):
            raise RuntimeError("Profiles file must contain a list.")

        return [WifiProfile.from_dict(item) for item in raw if isinstance(item, dict)]

    def save_profiles(self, profiles: Iterable[WifiProfile]) -> None:
        sanitized: list[dict] = []
        for profile in profiles:
            profile.validate()
            data = asdict(profile)
            # Passwords are stored as plain text for v1 only. Do not use this
            # storage strategy for production; replace it with Windows
            # Credential Manager or encryption before handling sensitive use.
            sanitized.append(data)

        try:
            with self.path.open("w", encoding="utf-8") as file:
                json.dump(sanitized, file, indent=2, ensure_ascii=False)
        except OSError as exc:
            raise RuntimeError(f"Could not save profiles file: {exc}") from exc
