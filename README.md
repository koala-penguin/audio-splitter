# Audio Splitter

A small standalone GUI for chopping an audio file into pieces at points you pick visually.

- Drag a file in (`.wav .mp3 .ogg .flac .m4a .aac .aiff`)
- See its waveform, scrub and play
- Drop split markers
- Press **Ctrl+S** to write `<name>_1.<ext>`, `<name>_2.<ext>`, ... into `./output/` next to the source file

ffmpeg ships with the install via `imageio-ffmpeg`, so no separate install is required.

## Run

Windows:
```
run.bat
```

macOS / Linux:
```
./run.sh
```

The first run creates `.venv/` and installs dependencies. Subsequent runs just launch the app.

To run manually inside the venv:
```
.venv\Scripts\python.exe -m audio_splitter      # Windows
.venv/bin/python -m audio_splitter              # macOS/Linux
```

## Shortcuts

| Key | Action |
| --- | --- |
| Space | Play / pause |
| S | Add split marker at playhead |
| Double-click on waveform | Add split marker there |
| Drag marker | Move marker |
| Right-click marker | Delete marker |
| Click waveform | Seek |
| Home | Jump to start |
| Ctrl+O | Open file |
| Ctrl+S | Save splits to `./output/` |
| Ctrl+Q | Quit |

## How splitting works

Output is written in the same format as the input. With *N* markers the app produces *N+1* files; with no markers Ctrl+S exports a single copy. Markers exactly at 0 s or at the end of the clip are ignored. Slicing is sample-accurate — adjacent output files concatenate back to bit-equivalent of the original.

## Tests

```
.venv\Scripts\python.exe -m pytest tests/ -v
```

This runs:
- pure-logic tests for the splitting math and file export, and
- a headless GUI smoke test (`QT_QPA_PLATFORM=offscreen`) that drives the real `MainWindow` through load → marker → Ctrl+S → file verification.

## Building a release binary

### Locally (host platform only)

Windows:
```
packaging\build.bat
```
Produces `dist\AudioSplitter.exe` (~90 MB, single file).

macOS / Linux:
```
./packaging/build.sh
```
Produces `dist/AudioSplitter` (and `dist/AudioSplitter.app` on macOS).

PyInstaller cannot cross-compile, so a Windows host produces only Windows binaries — for macOS builds use the GitHub Actions workflow below.

### Releasing on GitHub (Windows + macOS in one go)

Tag and push:
```
git tag v0.1.0
git push origin v0.1.0
```

`.github/workflows/release.yml` runs in parallel on `windows-latest` and `macos-latest`, executes the test suite, runs PyInstaller, and drafts a GitHub Release with both `AudioSplitter.exe` and `AudioSplitter-macos.zip` attached. Edit and publish the draft from the **Releases** tab.

You can also trigger the workflow manually from the **Actions** tab (`workflow_dispatch`) without creating a tag — useful for testing the build pipeline.

## Project layout

```
audio-splitter/
├── src/audio_splitter/
│   ├── app.py             QApplication entry
│   ├── main_window.py     window, drag-drop, transport, shortcuts, export
│   ├── waveform_view.py   pyqtgraph envelope + draggable markers
│   ├── audio_engine.py    pydub load/export, sounddevice playback
│   └── ffmpeg_setup.py    points pydub at imageio-ffmpeg's bundled binary
├── tests/
│   ├── test_split_logic.py
│   └── test_smoke_gui.py
├── requirements.txt
├── run.bat / run.sh
└── README.md
```

## Notes

- Playback feeds `sounddevice` from the same numpy buffer the waveform draws, so the playhead and what you hear stay in lock-step — no media-player drift.
- Volume slider scales the playback buffer in place; it doesn't affect what gets exported.
- Python 3.12 recommended. (Python 3.13 dropped `audioop`, which `pydub` still relies on; if you need 3.13, swap pydub for `pydub-stubs` plus `audioop-lts` or migrate to `soundfile` + raw slicing.)
