"""Boot the app on the real Qt platform and quit after 800ms.

Used to confirm that the windowed launch path works on the user's box —
the offscreen smoke test in test_smoke_gui.py covers the logic, this one
covers the visual init that offscreen skips. Not a pytest target.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from audio_splitter.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    QTimer.singleShot(800, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
