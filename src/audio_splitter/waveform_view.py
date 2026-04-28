"""Waveform view widget.

Shows a downsampled min/max envelope of the loaded audio, a draggable
playhead, and a list of split markers. Emits Qt signals when the user
seeks or edits markers; the main window drives all state changes back
into the view via setters so the view stays a dumb renderer.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPen


# Target horizontal resolution for the downsampled envelope. Higher gives
# more detail but costs draw time; ~4000 keeps it crisp on big monitors
# without choking on a 60-minute file.
_ENVELOPE_BUCKETS = 4000


def _envelope(samples: np.ndarray, buckets: int = _ENVELOPE_BUCKETS):
    """Return (xs, mins, maxs) describing the min/max per bucket."""
    n = len(samples)
    if n == 0:
        return np.array([]), np.array([]), np.array([])
    buckets = min(buckets, n)
    edges = np.linspace(0, n, buckets + 1, dtype=np.int64)
    mins = np.empty(buckets, dtype=np.float32)
    maxs = np.empty(buckets, dtype=np.float32)
    for i in range(buckets):
        chunk = samples[edges[i]:edges[i + 1]]
        if chunk.size == 0:
            mins[i] = maxs[i] = 0.0
        else:
            mins[i] = float(chunk.min())
            maxs[i] = float(chunk.max())
    centers = (edges[:-1] + edges[1:]) / 2.0
    return centers, mins, maxs


class WaveformView(pg.PlotWidget):
    """Drag-aware waveform display.

    Signals:
        seek_requested(float seconds): user clicked on empty waveform area
        marker_added(float seconds): user double-clicked
        marker_moved(int marker_id, float seconds): finished dragging marker
        marker_removed(int marker_id): user right-clicked a marker
    """

    seek_requested = Signal(float)
    marker_added = Signal(float)
    marker_moved = Signal(int, float)
    marker_removed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent=parent, background="#101418")
        self.setMouseEnabled(x=True, y=False)
        self.hideAxis("left")
        self.showAxis("bottom")
        self.setMenuEnabled(False)
        self.setLabel("bottom", "Time", units="s")
        self.getPlotItem().getViewBox().setMouseMode(pg.ViewBox.RectMode)
        self.getPlotItem().getViewBox().setMouseEnabled(x=False, y=False)
        self.setYRange(-1.05, 1.05, padding=0)

        # Envelope drawn as filled region between mins and maxs.
        self._fill = pg.FillBetweenItem(
            pg.PlotCurveItem(pen=pg.mkPen(color="#5cb6ff", width=1)),
            pg.PlotCurveItem(pen=pg.mkPen(color="#5cb6ff", width=1)),
            brush=pg.mkBrush(QColor(92, 182, 255, 110)),
        )
        self.addItem(self._fill)
        self._top_curve: pg.PlotCurveItem = self._fill.curves[0]
        self._bot_curve: pg.PlotCurveItem = self._fill.curves[1]

        self._duration_s: float = 0.0
        self._sample_rate: int = 0

        # Playhead (red) — set movable so user can scrub.
        self._playhead = pg.InfiniteLine(
            pos=0.0,
            angle=90,
            movable=True,
            pen=pg.mkPen(color="#ff4040", width=2),
            hoverPen=pg.mkPen(color="#ff8080", width=3),
        )
        self.addItem(self._playhead)
        self._playhead.sigPositionChangeFinished.connect(self._on_playhead_moved)
        self._suppress_playhead_signal = False

        # Markers: id -> InfiniteLine
        self._markers: Dict[int, pg.InfiniteLine] = {}
        self._next_marker_id = 1

        # Hover label that follows the cursor.
        self._hover_label = pg.TextItem(color="#cccccc", anchor=(0, 1))
        self._hover_label.setZValue(10)
        self.addItem(self._hover_label, ignoreBounds=True)
        self._hover_label.hide()

        self.scene().sigMouseMoved.connect(self._on_mouse_moved)

    # ---------- public API ----------
    def show_audio(self, samples_mono: np.ndarray, sample_rate: int, duration_s: float) -> None:
        self._duration_s = duration_s
        self._sample_rate = sample_rate
        centers, mins, maxs = _envelope(samples_mono)
        if len(centers):
            xs = centers / float(sample_rate)
            self._top_curve.setData(xs, maxs)
            self._bot_curve.setData(xs, mins)
        else:
            self._top_curve.clear()
            self._bot_curve.clear()
        self.setXRange(0.0, max(duration_s, 0.001), padding=0)
        self.setYRange(-1.05, 1.05, padding=0)
        self.set_playhead(0.0)
        self.clear_markers()

    def set_playhead(self, seconds: float) -> None:
        seconds = max(0.0, min(seconds, self._duration_s))
        self._suppress_playhead_signal = True
        try:
            self._playhead.setPos(seconds)
        finally:
            self._suppress_playhead_signal = False

    @property
    def playhead_s(self) -> float:
        return float(self._playhead.value())

    def add_marker(self, seconds: float) -> int:
        mid = self._next_marker_id
        self._next_marker_id += 1
        line = pg.InfiniteLine(
            pos=seconds,
            angle=90,
            movable=True,
            pen=pg.mkPen(color="#ffd24d", width=2, style=Qt.DashLine),
            hoverPen=pg.mkPen(color="#ffe8a3", width=3, style=Qt.DashLine),
            label=f"#{mid}",
            labelOpts={"position": 0.96, "color": "#ffd24d", "movable": False},
        )
        line.marker_id = mid  # type: ignore[attr-defined]
        line.sigPositionChangeFinished.connect(lambda ln=line: self.marker_moved.emit(ln.marker_id, float(ln.value())))
        line.sigClicked = getattr(line, "sigClicked", None)
        self.addItem(line)
        self._markers[mid] = line
        # right-click to remove
        line.scene().sigMouseClicked.connect(self._maybe_remove_on_rightclick)
        return mid

    def clear_markers(self) -> None:
        for line in list(self._markers.values()):
            self.removeItem(line)
        self._markers.clear()

    def remove_marker(self, marker_id: int) -> None:
        line = self._markers.pop(marker_id, None)
        if line is not None:
            self.removeItem(line)

    def marker_positions(self) -> List[float]:
        return sorted(float(line.value()) for line in self._markers.values())

    # ---------- events ----------
    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802 (Qt)
        pos = self._scene_to_time(ev.position() if hasattr(ev, "position") else ev.pos())
        if pos is not None:
            self.marker_added.emit(pos)
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def mousePressEvent(self, ev) -> None:  # noqa: N802 (Qt)
        # Single left click on empty area: seek.
        if ev.button() == Qt.LeftButton:
            scene_pos = ev.position() if hasattr(ev, "position") else ev.pos()
            item = self.scene().itemAt(QPointF(scene_pos), self.transform())
            t = self._scene_to_time(scene_pos)
            if t is not None and not self._is_marker_or_playhead_under(scene_pos):
                self.seek_requested.emit(t)
                ev.accept()
                return
        super().mousePressEvent(ev)

    def _maybe_remove_on_rightclick(self, ev) -> None:
        if ev.button() != Qt.RightButton:
            return
        scene_pos = ev.scenePos()
        for mid, line in list(self._markers.items()):
            # Translate marker x into scene x; treat anything within a few pixels as a hit.
            px = self.getPlotItem().getViewBox().mapViewToScene(QPointF(line.value(), 0)).x()
            if abs(px - scene_pos.x()) <= 6:
                self.marker_removed.emit(mid)
                ev.accept()
                return

    def _on_playhead_moved(self) -> None:
        if self._suppress_playhead_signal:
            return
        self.seek_requested.emit(float(self._playhead.value()))

    def _on_mouse_moved(self, scene_pos) -> None:
        t = self._scene_to_time(scene_pos)
        if t is None:
            self._hover_label.hide()
            return
        view_pt = self.getPlotItem().getViewBox().mapSceneToView(scene_pos)
        self._hover_label.setPos(view_pt.x(), 1.0)
        self._hover_label.setText(_format_time(t))
        self._hover_label.show()

    # ---------- helpers ----------
    def _scene_to_time(self, scene_pos) -> float | None:
        vb = self.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(scene_pos):
            return None
        view_pt = vb.mapSceneToView(scene_pos)
        x = float(view_pt.x())
        if self._duration_s <= 0:
            return None
        return max(0.0, min(self._duration_s, x))

    def _is_marker_or_playhead_under(self, scene_pos) -> bool:
        vb = self.getPlotItem().getViewBox()
        targets = [self._playhead] + list(self._markers.values())
        for line in targets:
            px = vb.mapViewToScene(QPointF(line.value(), 0)).x()
            if abs(px - scene_pos.x()) <= 6:
                return True
        return False


def _format_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    m, s = divmod(seconds, 60.0)
    return f"{int(m):02d}:{s:06.3f}"
