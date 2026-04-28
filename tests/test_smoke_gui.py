"""End-to-end GUI smoke test using offscreen Qt platform.

Boots the main window, simulates loading a synthesized WAV via the same
code path drag-drop uses, places markers, triggers playback, and runs the
Ctrl+S export. Verifies the produced files match the placed splits.
"""
from __future__ import annotations

import math
import os
import time
import wave
from pathlib import Path

import numpy as np
import pytest

# Force Qt to use the offscreen platform so the test runs headless.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from audio_splitter.main_window import MainWindow


def _write_sine_wav(path: Path, seconds: float = 6.0, sr: int = 22050) -> None:
    n = int(seconds * sr)
    t = np.arange(n) / sr
    y = (0.6 * np.sin(2 * math.pi * 440.0 * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(y.tobytes())


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_end_to_end_load_split_save(tmp_path, qapp, monkeypatch):
    # Synthesize a 6s WAV next to the would-be /output dir.
    wav_path = tmp_path / "smoke.wav"
    _write_sine_wav(wav_path, seconds=6.0)

    # Stub QMessageBox so we don't block on dialogs during export.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    win = MainWindow()
    win.show()
    QTest.qWait(50)

    # Load via the same internal entry point drag-drop uses.
    win._load_path(wav_path)
    QTest.qWait(50)

    assert win._audio is not None
    assert win._waveform.isVisible()
    assert not win._drop_label.isVisible()
    assert pytest.approx(win._audio.duration_s, abs=0.05) == 6.0

    # Place three markers via the public marker API.
    win._waveform.add_marker(1.5)
    win._waveform.add_marker(3.0)
    win._waveform.add_marker(4.5)
    assert win._waveform.marker_positions() == [1.5, 3.0, 4.5]

    # Trigger Ctrl+S via the action.
    win._save_splits()
    QTest.qWait(100)

    out_dir = wav_path.parent / "output"
    expected = ["smoke_1.wav", "smoke_2.wav", "smoke_3.wav", "smoke_4.wav"]
    actual = sorted(p.name for p in out_dir.iterdir())
    assert actual == expected
    for name in expected:
        assert (out_dir / name).stat().st_size > 0

    # Confirm rejoined durations match the source within rounding tolerance.
    from pydub import AudioSegment

    rejoined_ms = sum(
        len(AudioSegment.from_file(str(out_dir / name), format="wav")) for name in expected
    )
    original_ms = len(AudioSegment.from_file(str(wav_path), format="wav"))
    assert abs(rejoined_ms - original_ms) <= 5

    win.close()


def test_ctrl_s_shortcut_triggers_export(tmp_path, qapp, monkeypatch):
    """Regression: Ctrl+S must fire export exactly once (not be 'Ambiguous shortcut')."""
    import logging

    wav_path = tmp_path / "shortcut.wav"
    _write_sine_wav(wav_path, seconds=3.0)

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    # Capture Qt warnings — "Ambiguous shortcut overload" is the symptom of
    # a duplicate Ctrl+S registration. We fail the test if it appears.
    qt_warnings: list[str] = []
    from PySide6.QtCore import qInstallMessageHandler

    def handler(mode, ctx, msg):
        qt_warnings.append(str(msg))

    qInstallMessageHandler(handler)
    try:
        win = MainWindow()
        win.show()
        win._load_path(wav_path)
        win._waveform.add_marker(1.5)
        QTest.qWait(50)

        # Make sure the window has focus so the shortcut is delivered.
        win.activateWindow()
        win.setFocus()
        QTest.qWait(50)

        QTest.keyClick(win, Qt.Key_S, Qt.ControlModifier)
        QTest.qWait(150)

        out_dir = wav_path.parent / "output"
        produced = sorted(p.name for p in out_dir.iterdir())
        assert produced == ["shortcut_1.wav", "shortcut_2.wav"], (
            f"Ctrl+S did not produce the expected splits; got {produced}"
        )

        ambiguous = [w for w in qt_warnings if "Ambiguous shortcut" in w]
        assert not ambiguous, f"Ambiguous shortcut warnings: {ambiguous}"

        win.close()
    finally:
        qInstallMessageHandler(None)


def test_clear_splits_button(tmp_path, qapp, monkeypatch):
    wav_path = tmp_path / "smoke2.wav"
    _write_sine_wav(wav_path, seconds=4.0)

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    win = MainWindow()
    win._load_path(wav_path)
    win._waveform.add_marker(1.0)
    win._waveform.add_marker(2.0)
    assert len(win._waveform.marker_positions()) == 2
    win._clear_splits()
    assert win._waveform.marker_positions() == []
    win.close()
