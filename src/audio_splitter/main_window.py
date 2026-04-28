"""Main window: drag-drop, transport controls, shortcuts, export."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStatusBar,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from audio_splitter.audio_engine import (
    SUPPORTED_EXTS,
    AudioPlayer,
    LoadedAudio,
    export_splits,
    load_audio,
)
from audio_splitter.waveform_view import WaveformView, _format_time


_DROP_HINT = (
    "Drag and drop an audio file here\n"
    "(.wav .mp3 .ogg .flac .m4a .aac .aiff)\n\n"
    "Or use File → Open…"
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Audio Splitter")
        self.resize(1100, 520)
        self.setAcceptDrops(True)

        self._audio: Optional[LoadedAudio] = None
        self._player = AudioPlayer()
        self._player.set_on_finish(self._on_playback_finished)

        # ---------- central layout ----------
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # Drop hint sits behind the waveform view; the view is hidden until
        # a file is loaded. This way the empty state is always visible.
        self._drop_label = QLabel(_DROP_HINT, alignment=Qt.AlignCenter)
        self._drop_label.setStyleSheet(
            "QLabel { color: #c8d0d8; background:#101418; border:2px dashed #3a4654;"
            "         border-radius:8px; font-size:14pt; padding:32px; }"
        )
        outer.addWidget(self._drop_label, stretch=1)

        self._waveform = WaveformView(self)
        self._waveform.hide()
        outer.addWidget(self._waveform, stretch=1)

        self._waveform.seek_requested.connect(self._on_seek_requested)
        self._waveform.marker_added.connect(self._on_marker_added)
        self._waveform.marker_removed.connect(self._on_marker_removed)
        self._waveform.marker_moved.connect(lambda *_: self._refresh_status())

        # ---------- transport row ----------
        transport = QHBoxLayout()
        transport.setSpacing(8)

        style = self.style()
        self._btn_play = QPushButton(style.standardIcon(QStyle.SP_MediaPlay), " Play")
        self._btn_stop = QPushButton(style.standardIcon(QStyle.SP_MediaStop), " Stop")
        self._btn_split = QPushButton("Add Split (S)")
        self._btn_clear = QPushButton("Clear Splits")
        self._btn_save = QPushButton("Save Splits (Ctrl+S)")

        self._btn_play.clicked.connect(self._toggle_play)
        self._btn_stop.clicked.connect(self._stop)
        self._btn_split.clicked.connect(self._add_split_at_playhead)
        self._btn_clear.clicked.connect(self._clear_splits)
        self._btn_save.clicked.connect(self._save_splits)

        for b in (self._btn_play, self._btn_stop, self._btn_split, self._btn_clear, self._btn_save):
            b.setEnabled(False)
            transport.addWidget(b)

        transport.addStretch(1)
        transport.addWidget(QLabel("Vol"))
        # We don't actually attenuate samples (sounddevice doesn't expose a
        # cheap volume hook); instead, we scale the chunk in the callback by
        # multiplying. Implemented further below.
        self._volume = QSlider(Qt.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setValue(90)
        self._volume.setFixedWidth(120)
        self._volume.valueChanged.connect(self._on_volume_changed)
        transport.addWidget(self._volume)

        outer.addLayout(transport)

        # ---------- status bar ----------
        self._status = QStatusBar(self)
        self.setStatusBar(self._status)
        self._time_label = QLabel("00:00.000 / 00:00.000")
        self._status.addPermanentWidget(self._time_label)
        self._status.showMessage("Drop an audio file to begin.")

        # ---------- menu ----------
        self._build_menu()

        # ---------- shortcuts ----------
        # Ctrl+S and Ctrl+O are bound to QActions in the File menu; binding
        # them again here would yield an "Ambiguous shortcut" warning.
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._toggle_play)
        QShortcut(QKeySequence(Qt.Key_S), self, activated=self._add_split_at_playhead)
        QShortcut(QKeySequence(Qt.Key_Home), self, activated=lambda: self._seek_to(0.0))

        # ---------- 30 Hz playhead refresh ----------
        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

    # ---------- menu ----------
    def _build_menu(self) -> None:
        m_file = self.menuBar().addMenu("&File")
        act_open = QAction("&Open…", self, shortcut="Ctrl+O", triggered=self._open_file_dialog)
        act_save = QAction("&Save Splits", self, shortcut="Ctrl+S", triggered=self._save_splits)
        act_quit = QAction("&Quit", self, shortcut="Ctrl+Q", triggered=self.close)
        m_file.addAction(act_open)
        m_file.addAction(act_save)
        m_file.addSeparator()
        m_file.addAction(act_quit)

        m_help = self.menuBar().addMenu("&Help")
        m_help.addAction(QAction("&About…", self, triggered=self._show_about))

    # ---------- drag and drop ----------
    def dragEnterEvent(self, ev: QDragEnterEvent) -> None:  # noqa: N802 (Qt)
        if ev.mimeData().hasUrls() and any(_url_is_supported_audio(u) for u in ev.mimeData().urls()):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dropEvent(self, ev: QDropEvent) -> None:  # noqa: N802 (Qt)
        for url in ev.mimeData().urls():
            if _url_is_supported_audio(url):
                self._load_path(Path(url.toLocalFile()))
                ev.acceptProposedAction()
                return
        ev.ignore()

    # ---------- loading ----------
    def _open_file_dialog(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Open audio file", "", f"Audio ({exts});;All files (*.*)"
        )
        if path:
            self._load_path(Path(path))

    def _load_path(self, path: Path) -> None:
        self._status.showMessage(f"Loading {path.name}…")
        self.repaint()
        try:
            audio = load_audio(path)
        except Exception as e:  # decoding errors, missing codec, etc.
            traceback.print_exc()
            QMessageBox.critical(self, "Load failed", f"Could not load file:\n\n{e}")
            self._status.showMessage("Load failed.")
            return

        self._audio = audio
        if hasattr(self, "_audio_original_play"):
            del self._audio_original_play  # force volume handler to recapture
        self._player.set_audio(audio)
        # Apply current volume to fresh data.
        self._on_volume_changed(self._volume.value())
        self._waveform.show_audio(audio.samples_mono, audio.sample_rate, audio.duration_s)
        self._drop_label.hide()
        self._waveform.show()
        for b in (self._btn_play, self._btn_stop, self._btn_split, self._btn_clear, self._btn_save):
            b.setEnabled(True)
        self.setWindowTitle(f"Audio Splitter — {path.name}")
        self._refresh_status()

    # ---------- transport ----------
    def _toggle_play(self) -> None:
        if self._audio is None:
            return
        self._player.toggle()
        self._update_play_button()

    def _stop(self) -> None:
        self._player.stop()
        self._waveform.set_playhead(0.0)
        self._update_play_button()
        self._refresh_status()

    def _seek_to(self, seconds: float) -> None:
        if self._audio is None:
            return
        self._player.seek(seconds)
        self._waveform.set_playhead(self._player.position_s)
        self._refresh_status()

    def _on_seek_requested(self, seconds: float) -> None:
        self._seek_to(seconds)

    def _on_playback_finished(self) -> None:
        # Called from sounddevice's audio thread; bounce to GUI via timer.
        QTimer.singleShot(0, self._update_play_button)

    def _on_tick(self) -> None:
        if self._audio is None:
            return
        if self._player.is_playing:
            self._waveform.set_playhead(self._player.position_s)
        self._refresh_status()
        self._update_play_button()

    def _update_play_button(self) -> None:
        style = self.style()
        if self._player.is_playing:
            self._btn_play.setIcon(style.standardIcon(QStyle.SP_MediaPause))
            self._btn_play.setText(" Pause")
        else:
            self._btn_play.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
            self._btn_play.setText(" Play")

    def _on_volume_changed(self, value: int) -> None:
        # We swap the data the player sees by scaling a working copy. This
        # is cheap because it's a view-multiply on the float32 array, and
        # it's done once per slider tick — not per audio callback.
        if self._audio is None:
            return
        # The simplest, audibly-correct approach: temporarily restart the
        # stream with attenuated samples. Implemented by swapping
        # samples_play to a scaled array on the loaded audio.
        # Avoid editing the original — keep a private scaled copy.
        from audio_splitter.audio_engine import LoadedAudio  # local alias

        scale = max(0.0, min(1.0, value / 100.0))
        # Use the cached original we stash on self._audio.
        if not hasattr(self, "_audio_original_play"):
            self._audio_original_play = self._audio.samples_play
        scaled = self._audio_original_play * scale
        self._audio.samples_play = scaled.astype("float32", copy=False)
        # If currently playing, reseek to current position so the stream
        # picks up the new buffer (sounddevice copies on each callback).
        # In practice the callback already reads from samples_play each
        # call, so no reseek is needed.

    # ---------- splits ----------
    def _add_split_at_playhead(self) -> None:
        if self._audio is None:
            return
        pos = self._player.position_s
        if pos <= 0.0 or pos >= self._audio.duration_s:
            self._status.showMessage("Move the playhead inside the clip before adding a split.", 3000)
            return
        self._waveform.add_marker(pos)
        self._refresh_status()

    def _on_marker_added(self, seconds: float) -> None:
        self._waveform.add_marker(seconds)
        self._refresh_status()

    def _on_marker_removed(self, marker_id: int) -> None:
        self._waveform.remove_marker(marker_id)
        self._refresh_status()

    def _clear_splits(self) -> None:
        self._waveform.clear_markers()
        self._refresh_status()

    def _save_splits(self) -> None:
        if self._audio is None:
            self._status.showMessage("No audio loaded.", 3000)
            return
        markers = self._waveform.marker_positions()
        if not markers:
            ok = QMessageBox.question(
                self,
                "No splits",
                "No split markers placed. Export the file as-is to /output?",
            ) == QMessageBox.Yes
            if not ok:
                return

        out_dir = self._audio.path.parent / "output"
        try:
            self._status.showMessage(f"Exporting to {out_dir} …")
            self.repaint()

            def progress(i: int, total: int) -> None:
                self._status.showMessage(f"Exporting {i}/{total} …")
                self.repaint()

            written = export_splits(self._audio, markers, out_dir, progress=progress)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export failed", f"Could not export splits:\n\n{e}")
            self._status.showMessage("Export failed.")
            return

        self._status.showMessage(f"Wrote {len(written)} file(s) to {out_dir}", 8000)
        QMessageBox.information(
            self,
            "Splits saved",
            f"Wrote {len(written)} file(s) to:\n{out_dir}\n\n"
            + "\n".join(p.name for p in written),
        )

    # ---------- status ----------
    def _refresh_status(self) -> None:
        if self._audio is None:
            self._time_label.setText("00:00.000 / 00:00.000")
            return
        self._time_label.setText(
            f"{_format_time(self._player.position_s)} / {_format_time(self._audio.duration_s)}"
            f"   |   splits: {len(self._waveform.marker_positions())}"
        )

    # ---------- about ----------
    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Audio Splitter",
            "<b>Audio Splitter</b><br>"
            "Drag in an audio file, place split markers, save with Ctrl+S.<br><br>"
            "Shortcuts:<br>"
            "&nbsp;&nbsp;Space — play/pause<br>"
            "&nbsp;&nbsp;S — add split at playhead<br>"
            "&nbsp;&nbsp;Double-click waveform — add split there<br>"
            "&nbsp;&nbsp;Right-click marker — delete marker<br>"
            "&nbsp;&nbsp;Ctrl+S — save splits to ./output/<br>"
            "&nbsp;&nbsp;Ctrl+O — open file<br>"
            "&nbsp;&nbsp;Home — return to start<br>",
        )

    # ---------- close ----------
    def closeEvent(self, ev) -> None:  # noqa: N802 (Qt)
        self._tick.stop()
        self._player.stop()
        super().closeEvent(ev)


def _url_is_supported_audio(url: QUrl) -> bool:
    if not url.isLocalFile():
        return False
    suffix = Path(url.toLocalFile()).suffix.lower()
    return suffix in SUPPORTED_EXTS
