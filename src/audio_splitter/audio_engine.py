"""Audio loading, playback, and split export.

The engine keeps the loaded audio in two forms:
    * `segment`: pydub AudioSegment — used for slicing/exporting (preserves
      original codec/sample width).
    * `samples`: float32 numpy array, mono-mixed and peak-normalized for
      display and playback (sounddevice plays this directly so the playhead
      and what you hear stay in lock-step).
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
import sounddevice as sd
from pydub import AudioSegment

from audio_splitter.ffmpeg_setup import configure as _configure_ffmpeg

_configure_ffmpeg()

SUPPORTED_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".aiff", ".aif"}


@dataclass
class LoadedAudio:
    path: Path
    segment: AudioSegment
    samples_mono: np.ndarray   # float32 in [-1, 1], mono mix for display
    samples_play: np.ndarray   # float32, original channel layout, for playback
    sample_rate: int
    channels: int

    @property
    def duration_s(self) -> float:
        return len(self.segment) / 1000.0

    @property
    def ext(self) -> str:
        return self.path.suffix.lower().lstrip(".")


def load_audio(path: str | os.PathLike) -> LoadedAudio:
    p = Path(path)
    if p.suffix.lower() not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported file type: {p.suffix}")

    # pydub picks the right decoder by extension.
    fmt = p.suffix.lower().lstrip(".")
    # m4a/aac/aiff need explicit format hints
    fmt_map = {"m4a": "mp4", "aif": "aiff"}
    seg = AudioSegment.from_file(str(p), format=fmt_map.get(fmt, fmt))

    raw = np.array(seg.get_array_of_samples())
    if seg.channels > 1:
        raw = raw.reshape((-1, seg.channels))

    # Normalize integer PCM to float32 in [-1, 1].
    max_int = float(1 << (8 * seg.sample_width - 1))
    samples_play = (raw.astype(np.float32) / max_int)

    if samples_play.ndim == 2:
        samples_mono = samples_play.mean(axis=1)
    else:
        samples_mono = samples_play

    return LoadedAudio(
        path=p,
        segment=seg,
        samples_mono=samples_mono.astype(np.float32, copy=False),
        samples_play=samples_play.astype(np.float32, copy=False),
        sample_rate=seg.frame_rate,
        channels=seg.channels,
    )


@dataclass
class _PlaybackState:
    playing: bool = False
    paused: bool = False
    position_frames: int = 0
    stream: Optional[sd.OutputStream] = field(default=None, repr=False)


class AudioPlayer:
    """Thin wrapper over sounddevice that exposes a frame-accurate playhead.

    The callback advances `position_frames`; callers poll `position_s` from
    the GUI timer. We hold a mutex around the position to avoid torn reads
    on the (rare) word-tear case.
    """

    def __init__(self) -> None:
        self._audio: Optional[LoadedAudio] = None
        self._state = _PlaybackState()
        self._lock = threading.Lock()
        self._on_finish: Optional[Callable[[], None]] = None

    # ---- lifecycle ----
    def set_audio(self, audio: LoadedAudio) -> None:
        self.stop()
        self._audio = audio
        with self._lock:
            self._state.position_frames = 0

    def set_on_finish(self, cb: Callable[[], None] | None) -> None:
        self._on_finish = cb

    # ---- transport ----
    def play(self) -> None:
        if self._audio is None:
            return
        if self._state.playing and not self._state.paused:
            return
        if self._state.playing and self._state.paused:
            # resume by toggling stream; we recreated below for simplicity
            self._state.paused = False
            return
        self._start_stream()

    def pause(self) -> None:
        if not self._state.playing:
            return
        self._state.paused = True
        self._teardown_stream()

    def stop(self) -> None:
        self._teardown_stream()
        with self._lock:
            self._state.position_frames = 0
        self._state.playing = False
        self._state.paused = False

    def toggle(self) -> None:
        if self._state.playing and not self._state.paused:
            self.pause()
        else:
            self.play()

    def seek(self, seconds: float) -> None:
        if self._audio is None:
            return
        was_playing = self._state.playing and not self._state.paused
        self._teardown_stream()
        frames = int(max(0.0, seconds) * self._audio.sample_rate)
        frames = min(frames, len(self._audio.samples_play) - 1)
        with self._lock:
            self._state.position_frames = frames
        if was_playing:
            self._start_stream()

    # ---- queries ----
    @property
    def is_playing(self) -> bool:
        return self._state.playing and not self._state.paused

    @property
    def position_s(self) -> float:
        if self._audio is None:
            return 0.0
        with self._lock:
            return self._state.position_frames / self._audio.sample_rate

    @property
    def duration_s(self) -> float:
        return self._audio.duration_s if self._audio else 0.0

    # ---- internals ----
    def _start_stream(self) -> None:
        assert self._audio is not None
        audio = self._audio
        data = audio.samples_play
        channels = audio.channels

        def callback(outdata, frames, time_info, status):  # noqa: ANN001 (sd signature)
            with self._lock:
                pos = self._state.position_frames
            end = pos + frames
            total = len(data)
            if pos >= total:
                outdata[:] = 0
                raise sd.CallbackStop()
            chunk = data[pos:end]
            if chunk.ndim == 1:
                # mono source -> shape (n,1)
                chunk = chunk[:, None]
            out_n = chunk.shape[0]
            outdata[:out_n] = chunk
            if out_n < frames:
                outdata[out_n:] = 0
            with self._lock:
                self._state.position_frames = pos + out_n
            if out_n < frames:
                raise sd.CallbackStop()

        def finished():
            self._state.playing = False
            self._state.paused = False
            if self._on_finish is not None:
                self._on_finish()

        self._state.stream = sd.OutputStream(
            samplerate=audio.sample_rate,
            channels=channels,
            dtype="float32",
            callback=callback,
            finished_callback=finished,
        )
        self._state.stream.start()
        self._state.playing = True
        self._state.paused = False

    def _teardown_stream(self) -> None:
        s = self._state.stream
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._state.stream = None


# ---------- export ----------

def split_segment(seg: AudioSegment, split_points_s: List[float]) -> List[AudioSegment]:
    """Slice `seg` at the given split points (seconds, in source timeline).

    Out-of-range and unordered points are clamped, sorted, and de-duplicated.
    Returns one or more AudioSegments. With N split points, returns N+1 pieces;
    with no split points, returns a single piece (the original).
    """
    duration_ms = len(seg)
    cuts_ms = sorted({
        max(0, min(duration_ms, int(round(p * 1000.0))))
        for p in split_points_s
    })
    # drop boundary duplicates that would yield empty segments
    cuts_ms = [c for c in cuts_ms if 0 < c < duration_ms]

    pieces: List[AudioSegment] = []
    last = 0
    for c in cuts_ms:
        pieces.append(seg[last:c])
        last = c
    pieces.append(seg[last:duration_ms])
    return pieces


def export_splits(
    audio: LoadedAudio,
    split_points_s: List[float],
    output_dir: str | os.PathLike,
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[Path]:
    """Write split files into `output_dir` as <stem>_<n>.<ext>.

    Output format matches the source extension where pydub supports it.
    Returns the list of written paths.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pieces = split_segment(audio.segment, split_points_s)
    stem = audio.path.stem
    ext = audio.path.suffix.lower().lstrip(".") or "wav"
    fmt_map = {"m4a": "ipod", "aif": "aiff"}
    export_fmt = fmt_map.get(ext, ext)

    written: List[Path] = []
    total = len(pieces)
    for i, piece in enumerate(pieces, start=1):
        out_path = out_dir / f"{stem}_{i}.{ext}"
        piece.export(str(out_path), format=export_fmt)
        written.append(out_path)
        if progress is not None:
            progress(i, total)
    return written
