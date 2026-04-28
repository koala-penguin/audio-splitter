"""Capture a representative screenshot of the AudioSplitter GUI.

Synthesizes a short audio clip with varying amplitude (so the waveform
isn't a flat blob), loads it into the real MainWindow, places three
markers, then uses QWidget.grab() to render the window to PNG.

Output: docs/screenshot.png
"""
from __future__ import annotations

import math
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from audio_splitter.main_window import MainWindow


def _synthesize_demo_wav(path: Path, seconds: float = 30.0, sr: int = 22050) -> None:
    """Three musical 'sections' at different amplitudes so the waveform reads."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    wave_data = np.zeros(n, dtype=np.float32)

    # Section 1 (0-10s): quiet 220 Hz with a soft envelope.
    s1 = (t < 10.0)
    env1 = np.clip(t[s1] / 1.5, 0, 1) * np.clip((10.0 - t[s1]) / 1.5, 0, 1)
    wave_data[s1] = 0.35 * env1 * np.sin(2 * math.pi * 220 * t[s1])

    # Section 2 (10-20s): louder dyad (440 + 660 Hz).
    s2 = (t >= 10.0) & (t < 20.0)
    env2 = np.clip((t[s2] - 10.0) / 0.8, 0, 1) * np.clip((20.0 - t[s2]) / 0.8, 0, 1)
    wave_data[s2] = 0.7 * env2 * (
        0.5 * np.sin(2 * math.pi * 440 * t[s2])
        + 0.5 * np.sin(2 * math.pi * 660 * t[s2])
    )

    # Section 3 (20-30s): sweep from 660 down to 220 Hz, decaying.
    s3 = (t >= 20.0)
    local = t[s3] - 20.0
    freq = 660 - (660 - 220) * (local / 10.0)
    env3 = np.clip(local / 0.6, 0, 1) * np.exp(-local / 6.0)
    wave_data[s3] = 0.6 * env3 * np.sin(2 * math.pi * freq * local)

    pcm = (np.clip(wave_data, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def main() -> int:
    docs_dir = ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    out_png = docs_dir / "screenshot.png"
    demo_wav = docs_dir / "_demo_for_screenshot.wav"

    _synthesize_demo_wav(demo_wav)

    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1100, 520)
    win.show()
    win._load_path(demo_wav)

    # A few interestingly-spaced markers to show the feature.
    for t in (8.5, 15.0, 23.5):
        win._waveform.add_marker(t)

    # Park the playhead at a non-zero spot so the red line is visible.
    win._player.seek(12.7)
    win._waveform.set_playhead(12.7)
    win._refresh_status()
    win._status.showMessage(
        "Click waveform to seek  |  Space play/pause  |  S add split  |  Ctrl+S save"
    )

    # Let Qt finish layout/paint before grabbing.
    def capture() -> None:
        pixmap = win.grab()
        ok = pixmap.save(str(out_png), "PNG")
        if not ok:
            print(f"[screenshot] FAILED to write {out_png}", file=sys.stderr)
            app.exit(1)
            return
        size_kb = out_png.stat().st_size // 1024
        print(f"[screenshot] wrote {out_png} ({size_kb} KB, {pixmap.width()}x{pixmap.height()})")
        app.quit()

    QTimer.singleShot(400, capture)
    rc = app.exec()

    # Clean up the demo wav; keep only the screenshot.
    try:
        demo_wav.unlink()
    except OSError:
        pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
