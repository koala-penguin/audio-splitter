"""Wire pydub up to the ffmpeg binary bundled by imageio-ffmpeg.

pydub normally shells out to a system-wide `ffmpeg`. We don't want users
to install ffmpeg separately, so we ask imageio-ffmpeg for its bundled
binary and hand both the converter path and an ffprobe path to pydub.
imageio-ffmpeg doesn't ship ffprobe, but pydub only requires ffprobe for
metadata reads we don't use — for decode/encode the converter is enough,
and we set ffprobe to the same binary as a harmless fallback.
"""
from __future__ import annotations

import imageio_ffmpeg
from pydub import AudioSegment


def configure() -> str:
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    AudioSegment.converter = ffmpeg_path
    AudioSegment.ffmpeg = ffmpeg_path
    AudioSegment.ffprobe = ffmpeg_path
    return ffmpeg_path
