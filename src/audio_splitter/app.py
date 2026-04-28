"""QApplication entry point."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from audio_splitter.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Audio Splitter")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
