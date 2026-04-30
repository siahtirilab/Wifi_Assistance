from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes
from typing import Callable


SPI_GETWORKAREA = 0x0030
EDGE_MARGIN = 0
RIGHT_OFFSET = 6
TOPMOST_REFRESH_MS = 10000


class StatusWidget:
    def __init__(
        self,
        root: tk.Tk,
        initial_position: tuple[int, int] | None = None,
        on_position_changed: Callable[[int, int], None] | None = None,
    ) -> None:
        self.root = root
        self.window: tk.Toplevel | None = None
        self.initial_position = initial_position
        self.on_position_changed = on_position_changed
        self.label_var = tk.StringVar(value="Wi-Fi: checking...")
        self.dot: tk.Canvas | None = None
        self.dot_id: int | None = None
        self.blinking = False
        self._blink_job: str | None = None
        self._topmost_job: str | None = None
        self._blink_on = False
        self.visible = True

    def show(self) -> None:
        if self.window and self.window.winfo_exists():
            self.window.deiconify()
            self.visible = True
            self.restore_position()
            return

        self.window = tk.Toplevel(self.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#111827")
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)

        frame = tk.Frame(self.window, bg="#111827", padx=10, pady=6)
        frame.pack(fill="both", expand=True)

        dot = tk.Canvas(frame, width=8, height=8, bg="#111827", highlightthickness=0)
        self.dot = dot
        self.dot_id = dot.create_oval(1, 1, 7, 7, fill="#38bdf8", outline="")
        dot.pack(side="left", padx=(0, 6))

        label = tk.Label(
            frame,
            textvariable=self.label_var,
            bg="#111827",
            fg="#f9fafb",
            font=("Segoe UI", 7),
            anchor="w",
        )
        label.pack(side="left")

        for widget in (self.window, frame, dot, label):
            widget.bind("<Button-3>", lambda _event: self.hide())

        self.visible = True
        self.restore_position()
        self._ensure_topmost()

    def hide(self) -> None:
        self.visible = False
        self._cancel_topmost_job()
        if self.window and self.window.winfo_exists():
            self.window.withdraw()

    def toggle(self) -> None:
        if self.visible:
            self.hide()
        else:
            self.show()

    def set_text(self, text: str) -> None:
        compact = text.replace("Connected: ", "")
        if compact.startswith("Connecting to "):
            label = compact
        elif compact == "Disconnected":
            label = "Wi-Fi: Disconnected"
        elif compact:
            label = f"Wi-Fi: {compact}"
        else:
            label = "Wi-Fi: Unknown"

        self.label_var.set(label)
        if self.window and self.window.winfo_exists() and self.visible:
            self.window.update_idletasks()
            self._keep_on_screen()
            self._ensure_topmost()

    def set_online(self, online: bool | None) -> None:
        self.stop_blink()
        if not self.dot or not self.dot_id:
            return
        color = "#38bdf8" if online else "#6b7280"
        self.dot.itemconfigure(self.dot_id, fill=color)

    def start_blink(self) -> None:
        self.blinking = True
        self._blink_on = False
        self._blink()

    def stop_blink(self) -> None:
        self.blinking = False
        if self._blink_job:
            try:
                self.root.after_cancel(self._blink_job)
            except tk.TclError:
                pass
            self._blink_job = None

    def _blink(self) -> None:
        if not self.blinking or not self.dot or not self.dot_id:
            return
        self._blink_on = not self._blink_on
        color = "#9ca3af" if self._blink_on else "#4b5563"
        self.dot.itemconfigure(self.dot_id, fill=color)
        self._blink_job = self.root.after(450, self._blink)

    def position_near_taskbar(self) -> None:
        if not self.window:
            return
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        left, top, right, bottom = self._work_area()
        x = max(left, right - width - RIGHT_OFFSET)
        y = max(top, bottom - height - EDGE_MARGIN)
        self.window.geometry(f"+{x}+{y}")
        self._ensure_topmost()

    def restore_position(self) -> None:
        if not self.window:
            return
        self.window.update_idletasks()
        if self.initial_position is None:
            self.position_near_taskbar()
            return
        x, y = self.initial_position
        if x <= 0 and y <= 0:
            self.position_near_taskbar()
            return
        x, y = self._clamped_position(x, y)
        self.window.geometry(f"+{x}+{y}")
        self._ensure_topmost()

    def set_position(self, x: int, y: int) -> None:
        self.initial_position = (x, y)
        if not self.window or not self.window.winfo_exists():
            return
        self.window.update_idletasks()
        x, y = self._clamped_position(x, y)
        self.initial_position = (x, y)
        self.window.geometry(f"+{x}+{y}")
        self._ensure_topmost()

    def _work_area(self) -> tuple[int, int, int, int]:
        rect = wintypes.RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA,
            0,
            ctypes.byref(rect),
            0,
        )
        if ok:
            return rect.left, rect.top, rect.right, rect.bottom
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _ensure_topmost(self) -> None:
        if not self.window or not self.window.winfo_exists() or not self.visible:
            return
        try:
            self.window.attributes("-topmost", True)
            self.window.lift()
        except tk.TclError:
            return
        self._cancel_topmost_job()
        self._topmost_job = self.root.after(TOPMOST_REFRESH_MS, self._ensure_topmost)

    def _cancel_topmost_job(self) -> None:
        if self._topmost_job:
            try:
                self.root.after_cancel(self._topmost_job)
            except tk.TclError:
                pass
            self._topmost_job = None

    def _keep_on_screen(self) -> None:
        if not self.window:
            return
        x, y = self._clamped_position(self.window.winfo_x(), self.window.winfo_y())
        self.window.geometry(f"+{x}+{y}")

    def _clamped_position(self, x: int, y: int) -> tuple[int, int]:
        if not self.window:
            return x, y
        self.window.update_idletasks()
        width = self.window.winfo_width() or self.window.winfo_reqwidth()
        height = self.window.winfo_height() or self.window.winfo_reqheight()
        left, top, right, bottom = self._work_area()
        x = min(max(left, x), max(left, right - width))
        y = min(max(top, y), max(top, bottom - height))
        return x, y
