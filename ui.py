from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox
from typing import Callable

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X

from app_info import APP_CREATOR, APP_NAME, APP_VERSION
from profile_store import ProfileStore, WifiProfile
from settings_store import AppSettings, SettingsStore, StartupManager
from wifi_manager import WifiManager, WifiNetwork


class ProfileManagerWindow:
    def __init__(
        self,
        root: tb.Window,
        store: ProfileStore,
        settings_store: SettingsStore,
        startup_manager: StartupManager,
        wifi: WifiManager,
        on_profiles_changed: Callable[[], None],
        on_status_requested: Callable[[], str],
        on_settings_changed: Callable[[], None],
        on_connectivity_test_started: Callable[[], None],
        on_connectivity_test_finished: Callable[[bool], None],
        on_widget_position_changed: Callable[[int | None, int | None], None],
    ) -> None:
        self.root = root
        self.store = store
        self.settings_store = settings_store
        self.startup_manager = startup_manager
        self.wifi = wifi
        self.on_profiles_changed = on_profiles_changed
        self.on_status_requested = on_status_requested
        self.on_settings_changed = on_settings_changed
        self.on_connectivity_test_started = on_connectivity_test_started
        self.on_connectivity_test_finished = on_connectivity_test_finished
        self.on_widget_position_changed = on_widget_position_changed
        self.window: tb.Toplevel | None = None
        self.profiles: list[WifiProfile] = []
        self.selected_index: int | None = None
        self.pending_logs: list[str] = []

    def show(self) -> None:
        if self.window and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.refresh_profiles()
            self.refresh_settings()
            self.refresh_status()
            return

        self.window = tb.Toplevel(self.root)
        self.window.title(f"{APP_NAME} - Manage Profiles")
        self.window.geometry("1040x560")
        self.window.minsize(980, 520)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        container = tb.Frame(self.window, padding=14)
        container.pack(fill=BOTH, expand=True)

        header = tb.Frame(container)
        header.pack(fill=X, pady=(0, 10))
        self.status_var = tk.StringVar(value="Status: checking...")
        tb.Label(header, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).pack(
            side=LEFT
        )
        tb.Label(header, text=f"{APP_NAME} v{APP_VERSION}", bootstyle="secondary").pack(
            side=RIGHT
        )

        content = tb.Frame(container)
        content.pack(fill=BOTH, expand=True)

        left = tb.Frame(content)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 12))

        columns = ("display_name", "ssid", "security_type")
        self.tree = tb.Treeview(left, columns=columns, show="headings", height=8)
        self.tree.heading("display_name", text="Display Name")
        self.tree.heading("ssid", text="SSID")
        self.tree.heading("security_type", text="Security")
        self.tree.column("display_name", width=150)
        self.tree.column("ssid", width=230)
        self.tree.column("security_type", width=130)
        self.tree.pack(fill=X, expand=False)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        toolbar = tb.Frame(left)
        toolbar.pack(fill=X, pady=(10, 0))
        tb.Button(toolbar, text="Add", bootstyle="success", command=self.add_profile).pack(
            side=LEFT, padx=(0, 6)
        )
        tb.Button(toolbar, text="Edit", bootstyle="primary", command=self.edit_selected).pack(
            side=LEFT, padx=(0, 6)
        )
        tb.Button(toolbar, text="Delete", bootstyle="danger", command=self.delete_selected).pack(
            side=LEFT, padx=(0, 6)
        )
        tb.Button(toolbar, text="Scan WiFi", bootstyle="info", command=self.scan_wifi).pack(
            side=RIGHT
        )

        side_panel = tb.Frame(content)
        side_panel.pack(side=RIGHT, fill=BOTH, expand=False)

        form = tb.Labelframe(side_panel, text="Profile", padding=10)
        form.pack(fill=X, expand=False)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        self.display_name_var = tk.StringVar()
        self.ssid_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.security_var = tk.StringVar(value="WPA2-Personal")
        self.ping_target_var = tk.StringVar(value="siahtiri.ir")
        self.ping_timeout_var = tk.StringVar(value="250")
        self.widget_x_var = tk.StringVar()
        self.widget_y_var = tk.StringVar()
        self.startup_var = tk.BooleanVar(value=True)

        self._grid_field(form, "Display Name", self.display_name_var, 0, 0)
        self._grid_field(form, "SSID", self.ssid_var, 0, 1)
        self._grid_field(form, "Password", self.password_var, 1, 0, show="*")

        tb.Label(form, text="Security Type").grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(6, 2))
        security = tb.Combobox(
            form,
            textvariable=self.security_var,
            values=("WPA2-Personal", "WPA3-Personal"),
            state="readonly",
            width=18,
        )
        security.grid(row=3, column=1, sticky="ew", padx=(8, 0))

        tb.Label(form, text="Available Wi-Fi").grid(row=2, column=0, sticky="w", pady=(6, 2))
        self.network_var = tk.StringVar()
        self.network_combo = tb.Combobox(form, textvariable=self.network_var, values=(), width=18)
        self.network_combo.grid(row=3, column=0, sticky="ew")
        self.network_combo.bind("<<ComboboxSelected>>", self.on_network_selected)

        self.form_message_var = tk.StringVar(value="")
        tb.Label(form, textvariable=self.form_message_var, bootstyle="secondary").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        settings = tb.Labelframe(side_panel, text="Settings", padding=10)
        settings.pack(fill=X, expand=False, pady=(10, 0))
        settings.columnconfigure(0, weight=1)
        settings.columnconfigure(1, weight=1)

        tb.Label(settings, text="Ping Target").grid(row=0, column=0, sticky="w", pady=(0, 2))
        tb.Entry(settings, textvariable=self.ping_target_var, width=18).grid(
            row=1, column=0, sticky="ew", padx=(0, 8)
        )
        tb.Label(settings, text="Ping Timeout (seconds)").grid(
            row=0, column=1, sticky="w", pady=(0, 2)
        )
        tb.Entry(settings, textvariable=self.ping_timeout_var, width=18).grid(
            row=1, column=1, sticky="ew"
        )
        tb.Checkbutton(
            settings,
            text="Start with Windows",
            variable=self.startup_var,
            bootstyle="round-toggle",
        ).grid(row=2, column=0, sticky="w", pady=(10, 0))
        position_frame = tb.Frame(settings)
        position_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        position_frame.columnconfigure(0, weight=1)
        position_frame.columnconfigure(1, weight=1)
        position_frame.columnconfigure(2, weight=1)
        tb.Label(position_frame, text="Widget X").grid(row=0, column=0, sticky="w")
        tb.Label(position_frame, text="Widget Y").grid(row=0, column=1, sticky="w", padx=(8, 0))
        tb.Entry(position_frame, textvariable=self.widget_x_var, width=10).grid(
            row=1, column=0, sticky="ew"
        )
        tb.Entry(position_frame, textvariable=self.widget_y_var, width=10).grid(
            row=1, column=1, sticky="ew", padx=(8, 0)
        )
        tb.Button(
            position_frame,
            text="Apply Position",
            bootstyle="secondary",
            command=self.apply_widget_position,
        ).grid(row=1, column=2, sticky="ew", padx=(8, 0))
        tb.Label(settings, text=f"Creator: {APP_CREATOR}", bootstyle="secondary").grid(
            row=4, column=0, sticky="w", pady=(10, 0)
        )
        tb.Button(
            settings,
            text="Save Settings",
            bootstyle="secondary",
            command=self.save_settings,
        ).grid(row=5, column=0, sticky="ew", pady=(10, 0), padx=(0, 8))
        tb.Button(
            settings,
            text="Test Ping",
            bootstyle="info",
            command=self.test_ping,
        ).grid(row=5, column=1, sticky="ew", pady=(10, 0))

        log_frame = tb.Labelframe(left, text="Log", padding=8)
        log_frame.pack(fill=BOTH, expand=False, pady=(12, 0))
        self.log_text = tk.Text(
            log_frame,
            height=5,
            wrap="word",
            state="disabled",
            bg="#0f172a",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            font=("Consolas", 9),
        )
        self.log_text.pack(fill=BOTH, expand=True)
        for message in self.pending_logs:
            self._write_log(message)
        self.pending_logs.clear()

        self.refresh_profiles()
        self.refresh_settings()
        self.refresh_status()

    def _grid_field(
        self,
        parent: tb.Frame,
        label: str,
        variable: tk.StringVar,
        row_pair: int,
        column: int,
        show: str | None = None,
    ) -> None:
        row = row_pair * 2
        padx = (8, 0) if column else (0, 8)
        tb.Label(parent, text=label).grid(
            row=row,
            column=column,
            sticky="w",
            padx=padx,
            pady=(0 if row == 0 else 6, 2),
        )
        entry = tb.Entry(parent, textvariable=variable, show=show, width=18)
        entry.grid(row=row + 1, column=column, sticky="ew", padx=padx)

    def refresh_profiles(self) -> None:
        selected_index = self.selected_index
        self.profiles = self.store.load_profiles()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, profile in enumerate(self.profiles):
            self.tree.insert(
                "",
                END,
                iid=str(index),
                values=(profile.display_name, profile.ssid, profile.security_type),
            )
        if selected_index is not None and selected_index < len(self.profiles):
            self.tree.selection_set(str(selected_index))
            self.tree.focus(str(selected_index))

    def refresh_status(self) -> None:
        self.status_var.set(f"Status: {self.on_status_requested()}")

    def refresh_settings(self) -> None:
        settings = self.settings_store.load_settings()
        changed = False
        if (
            settings.status_widget_x is None
            or settings.status_widget_y is None
            or (settings.status_widget_x <= 0 and settings.status_widget_y <= 0)
        ):
            settings.status_widget_x = 1800
            settings.status_widget_y = 1000
            changed = True
        if changed:
            self.settings_store.save_settings(settings)

        self.ping_target_var.set(settings.ping_target)
        self.ping_timeout_var.set(str(settings.ping_timeout_seconds))
        self.widget_x_var.set(str(settings.status_widget_x))
        self.widget_y_var.set(str(settings.status_widget_y))
        registry_enabled = self.startup_manager.is_enabled()
        self.startup_var.set(settings.start_with_windows or registry_enabled)
        self.on_widget_position_changed(settings.status_widget_x, settings.status_widget_y)

    def on_tree_select(self, _event: object = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        self.selected_index = int(selected[0])
        profile = self.profiles[self.selected_index]
        self.display_name_var.set(profile.display_name)
        self.ssid_var.set(profile.ssid)
        self.password_var.set(profile.password)
        self.security_var.set(profile.security_type)

    def add_profile(self) -> None:
        if self._form_has_profile_data():
            self.selected_index = None
            self.save_form()
            return

        self.selected_index = None
        self.tree.selection_remove(self.tree.selection())
        self.display_name_var.set("")
        self.ssid_var.set("")
        self.password_var.set("")
        self.security_var.set("WPA2-Personal")
        self.form_message_var.set("Adding a new profile.")

    def _form_has_profile_data(self) -> bool:
        return any(
            value.strip()
            for value in (
                self.display_name_var.get(),
                self.ssid_var.get(),
                self.password_var.get(),
            )
        )

    def edit_selected(self) -> None:
        if self.selected_index is None:
            messagebox.showinfo("Edit profile", "Select a profile first.", parent=self.window)
            return
        self.save_form()
        self.form_message_var.set("Profile updated.")

    def delete_selected(self) -> None:
        if self.selected_index is None:
            messagebox.showinfo("Delete profile", "Select a profile first.", parent=self.window)
            return
        profile = self.profiles[self.selected_index]
        confirmed = messagebox.askyesno(
            "Delete profile",
            f"Delete '{profile.display_name}'?",
            parent=self.window,
        )
        if not confirmed:
            return
        del self.profiles[self.selected_index]
        self.store.save_profiles(self.profiles)
        self.selected_index = None
        self.refresh_profiles()
        self.on_profiles_changed()
        self.form_message_var.set("Profile deleted.")

    def save_form(self) -> None:
        profile = WifiProfile(
            display_name=self.display_name_var.get().strip(),
            ssid=self.ssid_var.get().strip(),
            password=self.password_var.get(),
            security_type=self.security_var.get().strip() or "WPA2-Personal",
        )
        try:
            profile.validate()
            if self.selected_index is None:
                self.profiles.append(profile)
            else:
                self.profiles[self.selected_index] = profile
            self.store.save_profiles(self.profiles)
        except Exception as exc:
            messagebox.showerror("Save profile", str(exc), parent=self.window)
            return

        self.refresh_profiles()
        if self.selected_index is None:
            self.selected_index = len(self.profiles) - 1
            if self.selected_index >= 0:
                self.tree.selection_set(str(self.selected_index))
                self.tree.focus(str(self.selected_index))
        self.on_profiles_changed()
        self.form_message_var.set("Profile saved.")

    def save_settings(self) -> None:
        try:
            timeout_seconds = int(self.ping_timeout_var.get().strip() or "250")
        except ValueError:
            messagebox.showerror("Save settings", "Ping timeout must be a number.", parent=self.window)
            return
        position = self._read_widget_position()
        if position is False:
            return
        widget_x, widget_y = position

        settings = AppSettings(
            ping_target=self.ping_target_var.get().strip() or "siahtiri.ir",
            ping_timeout_seconds=timeout_seconds,
            start_with_windows=self.startup_var.get(),
            creator=APP_CREATOR,
            status_widget_x=widget_x,
            status_widget_y=widget_y,
        )
        try:
            self.settings_store.save_settings(settings)
            self.on_settings_changed()
        except Exception as exc:
            messagebox.showerror("Save settings", str(exc), parent=self.window)
            return
        self.form_message_var.set("Settings saved.")
        self.on_widget_position_changed(widget_x, widget_y)
        self.add_log(
            f"Settings saved. Ping target: {settings.ping_target}, timeout: {settings.ping_timeout_seconds}s"
        )

    def apply_widget_position(self) -> None:
        if self._apply_widget_position_from_fields(show_log=True):
            self.form_message_var.set("Widget position applied.")

    def _apply_widget_position_from_fields(self, show_log: bool) -> bool:
        position = self._read_widget_position()
        if position is False:
            return False
        widget_x, widget_y = position
        settings = self.settings_store.load_settings()
        settings.status_widget_x = widget_x
        settings.status_widget_y = widget_y
        try:
            self.settings_store.save_settings(settings)
        except Exception as exc:
            messagebox.showerror("Apply position", str(exc), parent=self.window)
            return False
        self.on_widget_position_changed(widget_x, widget_y)
        if show_log:
            self.add_log(f"Widget position applied: x={widget_x}, y={widget_y}")
        return True

    def _read_widget_position(self) -> tuple[int | None, int | None] | bool:
        raw_x = self.widget_x_var.get().strip()
        raw_y = self.widget_y_var.get().strip()
        if not raw_x and not raw_y:
            return None, None
        if not raw_x or not raw_y:
            messagebox.showerror("Widget position", "Enter both Widget X and Widget Y.", parent=self.window)
            return False
        try:
            return int(raw_x), int(raw_y)
        except ValueError:
            messagebox.showerror("Widget position", "Widget X and Widget Y must be numbers.", parent=self.window)
            return False

    def test_ping(self) -> None:
        target = self.ping_target_var.get().strip() or "siahtiri.ir"
        try:
            timeout_seconds = int(self.ping_timeout_var.get().strip() or "250")
        except ValueError:
            messagebox.showerror("Test ping", "Ping timeout must be a number.", parent=self.window)
            return
        timeout_seconds = max(1, min(timeout_seconds, 600))
        self.add_log(f"Testing connectivity to {target} with {timeout_seconds}s timeout...")
        self.on_connectivity_test_started()
        threading.Thread(
            target=self._test_ping_worker,
            args=(target, timeout_seconds),
            daemon=True,
        ).start()

    def _test_ping_worker(self, target: str, timeout_seconds: int) -> None:
        result = self.wifi.check_connectivity(target, timeout_seconds)
        self.root.after(0, self._test_ping_done, result.online, result.details)

    def _test_ping_done(self, online: bool, details: list[str]) -> None:
        for line in details:
            self.add_log(line)
        self.add_log(f"Connectivity result: {'online' if online else 'offline'}")
        self.on_connectivity_test_finished(online)

    def scan_wifi(self) -> None:
        self.form_message_var.set("Scanning Wi-Fi networks...")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self) -> None:
        try:
            networks = self.wifi.scan_networks()
            self.root.after(0, self._scan_done, networks, None)
        except Exception as exc:
            self.root.after(0, self._scan_done, [], exc)

    def _scan_done(self, networks: list[WifiNetwork], error: Exception | None) -> None:
        if error:
            self.form_message_var.set("Scan failed.")
            messagebox.showerror("Scan Wi-Fi", str(error), parent=self.window)
            return
        self.network_combo.configure(values=[network.ssid for network in networks])
        self.form_message_var.set(f"Found {len(networks)} network(s).")

    def on_network_selected(self, _event: object = None) -> None:
        ssid = self.network_var.get().strip()
        if ssid:
            self.ssid_var.set(ssid)
            if not self.display_name_var.get().strip():
                self.display_name_var.set(ssid)

    def close(self) -> None:
        if not self._apply_widget_position_from_fields(show_log=False):
            return
        if self.window and self.window.winfo_exists():
            self.window.withdraw()

    def add_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        if not hasattr(self, "log_text") or not self.log_text.winfo_exists():
            self.pending_logs.append(message)
            return
        self._write_log(line)

    def _write_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(END, f"{line}\n")
        self.log_text.see(END)
        self.log_text.configure(state="disabled")
