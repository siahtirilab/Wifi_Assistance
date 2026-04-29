from __future__ import annotations

import sys

from app_info import APP_NAME
from tray_app import TrayApp


def main() -> int:
    if sys.platform != "win32":
        print(f"{APP_NAME} is designed for Windows only.")
        return 1

    app = TrayApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
