from __future__ import annotations

import tkinter as tk


class StatusWidget:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.window: tk.Toplevel | None = None
        self.label_var = tk.StringVar(value="Wi-Fi: checking...")
        self.dot: tk.Canvas | None = None
        self.dot_id: int | None = None
        self.blinking = False
        self._blink_job: str | None = None
        self._blink_on = False
        self.visible = True
        self._drag_x = 0
        self._drag_y = 0

    def show(self) -> None:
        if self.window and self.window.winfo_exists():
            self.window.deiconify()
            self.visible = True
            self.position_near_taskbar()
            return

        self.window = tk.Toplevel(self.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#111827")
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)

        frame = tk.Frame(self.window, bg="#111827", padx=8, pady=4)
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
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<Button-3>", lambda _event: self.hide())

        self.visible = True
        self.position_near_taskbar()

    def hide(self) -> None:
        self.visible = False
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
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = max(0, screen_width - width - 110)
        y = max(0, screen_height - height - 42)
        self.window.geometry(f"+{x}+{y}")

    def _keep_on_screen(self) -> None:
        if not self.window:
            return
        x = self.window.winfo_x()
        y = self.window.winfo_y()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = min(max(0, x), max(0, screen_width - width))
        y = min(max(0, y), max(0, screen_height - height))
        self.window.geometry(f"+{x}+{y}")

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_x = event.x
        self._drag_y = event.y

    def _drag(self, event: tk.Event) -> None:
        if not self.window:
            return
        x = self.window.winfo_x() + event.x - self._drag_x
        y = self.window.winfo_y() + event.y - self._drag_y
        self.window.geometry(f"+{x}+{y}")
