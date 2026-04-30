from __future__ import annotations

import json
import shutil
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
    status_widget_x: int | None = 1800
    status_widget_y: int | None = 1000

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        timeout = data.get("ping_timeout_seconds", 250) or 250
        if int(timeout) == 45:
            timeout = 250
        widget_x = cls._optional_int(data.get("status_widget_x"), 1800)
        widget_y = cls._optional_int(data.get("status_widget_y"), 1000)
        if (widget_x is None or widget_x <= 0) and (widget_y is None or widget_y <= 0):
            widget_x = 1800
            widget_y = 1000
        return cls(
            ping_target=str(data.get("ping_target", "siahtiri.ir")).strip() or "siahtiri.ir",
            ping_timeout_seconds=int(timeout),
            start_with_windows=bool(data.get("start_with_windows", True)),
            creator=str(data.get("creator", APP_CREATOR)).strip() or APP_CREATOR,
            status_widget_x=widget_x,
            status_widget_y=widget_y,
        )

    def validate(self) -> None:
        if not self.ping_target.strip():
            raise ValueError("Ping target is required.")
        if self.ping_timeout_seconds < 1 or self.ping_timeout_seconds > 600:
            raise ValueError("Ping timeout must be between 1 and 600 seconds.")

    @staticmethod
    def _optional_int(value: object, default: int | None = None) -> int | None:
        if value is None or value == "":
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = path
        ensure_app_dir()
        if not self.path.exists():
            self.save_settings(AppSettings())

    def load_settings(self) -> AppSettings:
        try:
            raw = self._read_json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            backup_path = self.path.with_suffix(".invalid.json")
            try:
                shutil.copy2(self.path, backup_path)
            except OSError:
                pass
            settings = AppSettings()
            self.save_settings(settings)
            return settings
        except OSError as exc:
            raise RuntimeError(f"Could not read settings file: {exc}") from exc

        if not isinstance(raw, dict):
            settings = AppSettings()
            self.save_settings(settings)
            return settings

        settings = AppSettings.from_dict(raw)
        self.save_settings(settings)
        return settings

    def _read_json(self) -> object:
        last_error: Exception | None = None
        for encoding in ("utf-8", "utf-8-sig", "utf-16"):
            try:
                with self.path.open("r", encoding=encoding) as file:
                    return json.load(file)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise json.JSONDecodeError("Could not parse settings JSON.", "", 0)

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
