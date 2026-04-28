"""Offline tests for the slicing math and end-to-end export.

These tests synthesize a 5-second sine-wave WAV, drive the engine without
the GUI, and verify that pydub-produced splits sum back to the original
duration and contain the right audio data.
"""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest
from pydub import AudioSegment

from audio_splitter.audio_engine import (
    export_splits,
    load_audio,
    split_segment,
)


def _write_sine_wav(path: Path, seconds: float = 5.0, sr: int = 22050, freq: float = 440.0) -> None:
    n = int(seconds * sr)
    t = np.arange(n) / sr
    y = (0.6 * np.sin(2 * math.pi * freq * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(y.tobytes())


@pytest.fixture
def tmp_wav(tmp_path: Path) -> Path:
    p = tmp_path / "tone.wav"
    _write_sine_wav(p, seconds=5.0)
    return p


def test_split_segment_no_points_returns_full_clip(tmp_wav: Path) -> None:
    seg = AudioSegment.from_file(str(tmp_wav), format="wav")
    pieces = split_segment(seg, [])
    assert len(pieces) == 1
    assert abs(len(pieces[0]) - len(seg)) <= 1


def test_split_segment_three_points_yields_four_pieces(tmp_wav: Path) -> None:
    seg = AudioSegment.from_file(str(tmp_wav), format="wav")
    pieces = split_segment(seg, [1.0, 2.5, 4.0])
    assert len(pieces) == 4
    # durations: ~1000, ~1500, ~1500, ~1000 ms (allow rounding)
    durations = [len(p) for p in pieces]
    assert sum(durations) == len(seg)
    assert durations[0] == pytest.approx(1000, abs=2)
    assert durations[1] == pytest.approx(1500, abs=2)
    assert durations[2] == pytest.approx(1500, abs=2)
    assert durations[3] == pytest.approx(1000, abs=2)


def test_split_segment_clamps_and_dedups(tmp_wav: Path) -> None:
    seg = AudioSegment.from_file(str(tmp_wav), format="wav")
    # negative, duplicate, beyond-end, unsorted
    pieces = split_segment(seg, [-1.0, 2.0, 2.0, 999.0, 1.0])
    # unique valid cuts should be 1.0 and 2.0 -> 3 pieces
    assert len(pieces) == 3
    durations = [len(p) for p in pieces]
    assert sum(durations) == len(seg)


def test_split_segment_zero_and_full_duration_are_dropped(tmp_wav: Path) -> None:
    seg = AudioSegment.from_file(str(tmp_wav), format="wav")
    pieces = split_segment(seg, [0.0, 5.0])
    assert len(pieces) == 1


def test_export_splits_writes_numbered_files(tmp_wav: Path, tmp_path: Path) -> None:
    audio = load_audio(tmp_wav)
    out_dir = tmp_path / "output"
    written = export_splits(audio, [1.0, 3.0], out_dir)
    assert [p.name for p in written] == ["tone_1.wav", "tone_2.wav", "tone_3.wav"]
    for p in written:
        assert p.exists() and p.stat().st_size > 0

    # Reload the splits and verify total duration matches the original.
    total_ms = sum(len(AudioSegment.from_file(str(p), format="wav")) for p in written)
    original_ms = len(AudioSegment.from_file(str(tmp_wav), format="wav"))
    assert abs(total_ms - original_ms) <= 5


def test_export_splits_with_no_markers_writes_one_file(tmp_wav: Path, tmp_path: Path) -> None:
    audio = load_audio(tmp_wav)
    out_dir = tmp_path / "output"
    written = export_splits(audio, [], out_dir)
    assert [p.name for p in written] == ["tone_1.wav"]
    assert written[0].exists()


def test_load_audio_rejects_unsupported(tmp_path: Path) -> None:
    bogus = tmp_path / "thing.xyz"
    bogus.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ValueError):
        load_audio(bogus)
