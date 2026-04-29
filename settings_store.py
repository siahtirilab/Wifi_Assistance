from __future__ import annotations

import json
import sys
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path

from app_info import APP_CREATOR
from profile_store import APP_DIR, ensure_app_dir


SETTINGS_PATH = APP_DIR / "settings.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "WifiAssistance"


@dataclass(slots=True)
class AppSettings:
    ping_target: str = "siahtiri.ir"
    ping_timeout_seconds: int = 250
    start_with_windows: bool = True
    creator: str = APP_CREATOR

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        timeout = data.get("ping_timeout_seconds", 250) or 250
        if int(timeout) == 45:
            timeout = 250
        return cls(
            ping_target=str(data.get("ping_target", "siahtiri.ir")).strip() or "siahtiri.ir",
            ping_timeout_seconds=int(timeout),
            start_with_windows=bool(data.get("start_with_windows", True)),
            creator=str(data.get("creator", APP_CREATOR)).strip() or APP_CREATOR,
        )

    def validate(self) -> None:
        if not self.ping_target.strip():
            raise ValueError("Ping target is required.")
        if self.ping_timeout_seconds < 1 or self.ping_timeout_seconds > 600:
            raise ValueError("Ping timeout must be between 1 and 600 seconds.")


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = path
        ensure_app_dir()
        if not self.path.exists():
            self.save_settings(AppSettings())

    def load_settings(self) -> AppSettings:
        try:
            with self.path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Settings file is not valid JSON: {self.path}") from exc
        except OSError as exc:
            raise RuntimeError(f"Could not read settings file: {exc}") from exc

        if not isinstance(raw, dict):
            raise RuntimeError("Settings file must contain an object.")
        return AppSettings.from_dict(raw)

    def save_settings(self, settings: AppSettings) -> None:
        settings.validate()
        try:
            with self.path.open("w", encoding="utf-8") as file:
                json.dump(asdict(settings), file, indent=2, ensure_ascii=False)
        except OSError as exc:
            raise RuntimeError(f"Could not save settings file: {exc}") from exc


class StartupManager:
    def get_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        script_path = Path(__file__).with_name("main.py")
        executable = Path(sys.executable)
        pythonw = executable.with_name("pythonw.exe")
        launcher = pythonw if pythonw.exists() else executable
        return f'"{launcher}" "{script_path}"'

    def set_enabled(self, enabled: bool) -> None:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, self.get_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass

    def is_enabled(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, RUN_VALUE_NAME)
                return True
        except FileNotFoundError:
            return False
        except OSError:
            return False
