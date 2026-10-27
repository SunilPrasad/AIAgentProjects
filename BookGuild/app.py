"""Book Guild entry point.

    python app.py           open the desktop app
    python app.py --check   print which API keys were found, then exit
"""

from __future__ import annotations

import asyncio
import sys

from bookguild.config import load_settings


def print_key_check() -> int:
    settings = load_settings()
    for status in settings.key_statuses():
        mark = "found  " if status.found else "MISSING"
        kind = "required" if status.required else "optional"
        print(f"  [{mark}] {status.env_var:<22} ({kind})")
    return 1 if settings.missing_required_keys() else 0


def main() -> int:
    if "--check" in sys.argv:
        return print_key_check()

    import qasync
    from PySide6.QtWidgets import QApplication

    from bookguild.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    # qasync lets Qt and asyncio share one event loop, so AI calls run without freezing the window.
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(load_settings())
    window.showMaximized()
    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
