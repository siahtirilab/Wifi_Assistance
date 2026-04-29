from __future__ import annotations

import threading
from typing import Callable

import pystray
import ttkbootstrap as tb
from pystray import Menu, MenuItem
from tkinter import messagebox

from app_info import APP_NAME, TRAY_ID
from icon import create_tray_icon
from profile_store import ProfileStore, WifiProfile
from settings_store import SettingsStore, StartupManager
from status_widget import StatusWidget
from ui import ProfileManagerWindow
from wifi_manager import WifiManager, WifiStatus


class TrayApp:
    def __init__(self) -> None:
        self.store = ProfileStore()
        self.settings_store = SettingsStore()
        self.startup_manager = StartupManager()
        self.settings = self.settings_store.load_settings()
        self._apply_startup_setting(show_errors=False)
        self.wifi = WifiManager()
        self.root = tb.Window(themename="flatly")
        self.root.withdraw()
        self.root.title(APP_NAME)

        self.status_lock = threading.Lock()
        self.current_status = WifiStatus(False, message="Checking status...")
        self.connecting_to: str | None = None
        self.refresh_in_progress = False
        self.status_widget = StatusWidget(self.root)
        self.profile_window = ProfileManagerWindow(
            self.root,
            self.store,
            self.settings_store,
            self.startup_manager,
            self.wifi,
            self.refresh_menu,
            self.get_status_label,
            self.on_settings_changed,
            self.start_connectivity_indicator,
            self.finish_connectivity_indicator,
        )

        self.icon = pystray.Icon(
            TRAY_ID,
            create_tray_icon(),
            APP_NAME,
            self._build_menu(),
        )

    def run(self) -> None:
        self.status_widget.show()
        self.refresh_status_async()
        self.root.after(5000, self._status_refresh_loop)
        self.icon.run_detached()
        self.root.mainloop()

    def _build_menu(self) -> Menu:
        return Menu(*self._menu_items())

    def _menu_items(self) -> list[MenuItem]:
        items: list[MenuItem] = [
            MenuItem(self.get_status_label(), None, enabled=False),
            Menu.SEPARATOR,
        ]

        profiles = self._safe_profiles()
        if profiles:
            for profile in profiles:
                active = self._is_active_profile(profile)
                label = f"[ACTIVE] {profile.display_name}" if active else profile.display_name
                items.append(
                    MenuItem(
                        label,
                        self._connect_handler(profile),
                        enabled=self.connecting_to is None,
                        checked=lambda _item, p=profile: self._is_active_profile(p),
                    )
                )
        else:
            items.append(MenuItem("No profiles configured", None, enabled=False))

        items.extend(
            [
                Menu.SEPARATOR,
                MenuItem("Manage Profiles", self._tk_callback(self.show_manage_profiles)),
                MenuItem(
                    "Show Taskbar Status",
                    self._tk_callback(self.toggle_status_widget),
                    checked=lambda _item: self.status_widget.visible,
                ),
                MenuItem("Refresh Status", self._tk_callback(self.refresh_status_async)),
                MenuItem("⚠ Restart Adapter", self._tk_callback(self.restart_adapter)),
                Menu.SEPARATOR,
                MenuItem("Exit", self.exit),
            ]
        )
        return items

    def _safe_profiles(self) -> list[WifiProfile]:
        try:
            return self.store.load_profiles()
        except Exception:
            return []

    def _is_active_profile(self, profile: WifiProfile) -> bool:
        with self.status_lock:
            return self.current_status.connected and self.current_status.ssid == profile.ssid

    def _connect_handler(self, profile: WifiProfile) -> Callable:
        def handler(_icon: pystray.Icon, _item: MenuItem) -> None:
            self.root.after(0, self.connect_profile, profile)

        return handler

    def _tk_callback(self, callback: Callable) -> Callable:
        def handler(_icon: pystray.Icon, _item: MenuItem) -> None:
            self.root.after(0, callback)

        return handler

    def connect_profile(self, profile: WifiProfile) -> None:
        if self.connecting_to:
            return
        self.connecting_to = profile.ssid
        self.start_connectivity_indicator()
        self._log(f"Switching to profile '{profile.display_name}' ({profile.ssid})...")
        self.refresh_menu()
        threading.Thread(target=self._connect_worker, args=(profile,), daemon=True).start()

    def _connect_worker(self, profile: WifiProfile) -> None:
        try:
            status = self.wifi.connect(profile)
            self._set_status(status)
            self.root.after(0, self._log, f"Connected Wi-Fi status confirmed: {status.ssid}")
            result = self.wifi.check_connectivity(
                self.settings.ping_target,
                self.settings.ping_timeout_seconds,
            )
            for line in result.details:
                self.root.after(0, self._log, line)
            self.root.after(0, self._log, f"Connectivity result: {'online' if result.online else 'offline'}")
            self.root.after(0, self.finish_connectivity_indicator, result.online)
        except Exception as exc:
            self.root.after(0, self._show_error, "Wi-Fi connection failed", str(exc))
            self.root.after(0, self._log, f"Connection failed: {exc}")
            self._set_status(self.wifi.get_status())
            self.root.after(0, self.finish_connectivity_indicator, False)
        finally:
            self.connecting_to = None
            self.root.after(0, self.refresh_menu)

    def refresh_status_async(self) -> None:
        if self.refresh_in_progress:
            return
        self.refresh_in_progress = True
        threading.Thread(target=self._refresh_status_worker, daemon=True).start()

    def _refresh_status_worker(self) -> None:
        try:
            self._set_status(self.wifi.get_status())
        finally:
            self.refresh_in_progress = False
            self.root.after(0, self.refresh_menu)

    def _status_refresh_loop(self) -> None:
        if not self.connecting_to:
            self.refresh_status_async()
        self.root.after(5000, self._status_refresh_loop)

    def _set_status(self, status: WifiStatus) -> None:
        with self.status_lock:
            self.current_status = status

    def get_status_label(self) -> str:
        if self.connecting_to:
            return f"Connecting to {self.connecting_to}..."
        with self.status_lock:
            return self.current_status.label

    def refresh_menu(self) -> None:
        try:
            self.icon.menu = self._build_menu()
            self.icon.update_menu()
            self.icon.title = self.get_status_label()
        except Exception:
            pass

        self.status_widget.set_text(self.get_status_label())

        if self.profile_window.window and self.profile_window.window.winfo_exists():
            try:
                self.profile_window.refresh_status()
            except Exception:
                pass

    def show_manage_profiles(self) -> None:
        self.profile_window.show()

    def toggle_status_widget(self) -> None:
        self.status_widget.toggle()
        self.refresh_menu()

    def on_settings_changed(self) -> None:
        self.settings = self.settings_store.load_settings()
        self._apply_startup_setting(show_errors=True)

    def start_connectivity_indicator(self) -> None:
        self.status_widget.start_blink()

    def finish_connectivity_indicator(self, online: bool) -> None:
        self.status_widget.set_online(online)

    def _apply_startup_setting(self, show_errors: bool) -> None:
        try:
            self.startup_manager.set_enabled(self.settings.start_with_windows)
        except Exception as exc:
            if show_errors:
                self.root.after(0, self._show_error, "Startup setting failed", str(exc))

    def restart_adapter(self) -> None:
        confirmed = messagebox.askyesno(
            "Restart Adapter",
            "Restart the Wi-Fi adapter now? The current Wi-Fi connection will drop briefly.",
        )
        if not confirmed:
            return
        self.status_widget.set_online(False)
        threading.Thread(target=self._restart_adapter_worker, daemon=True).start()

    def _restart_adapter_worker(self) -> None:
        try:
            self.root.after(0, self._log, "Restarting Wi-Fi adapter...")
            self.wifi.restart_adapter()
            self._set_status(self.wifi.get_status())
            self.root.after(0, self._log, "Wi-Fi adapter restart finished.")
        except Exception as exc:
            self.root.after(0, self._show_error, "Restart Adapter failed", str(exc))
            self.root.after(0, self._log, f"Restart Adapter failed: {exc}")
        finally:
            self.root.after(0, self.refresh_menu)

    def _show_error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message)

    def _log(self, message: str) -> None:
        self.profile_window.add_log(message)

    def exit(self, _icon: pystray.Icon | None = None, _item: MenuItem | None = None) -> None:
        self.root.after(0, self._exit_on_tk)

    def _exit_on_tk(self) -> None:
        try:
            self.icon.stop()
        finally:
            self.root.quit()
            self.root.destroy()
