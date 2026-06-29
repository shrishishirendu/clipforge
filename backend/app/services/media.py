"""Media engine — FFmpeg cut + concat (FR-20), behind the MediaEngine interface
(arch §10). Works on local files; the render worker handles storage I/O.

A single filter_complex pass trims each approved segment, normalises it to the
target height, and concatenates in order — accurate cuts (re-encode) so boundaries
land exactly where selection snapped them to silence (FR-15), not on keyframes.
"""
from __future__ import annotations

import os
import subprocess

from app.core.config import settings

_HEIGHTS = {"480p": 480, "720p": 720, "1080p": 1080}


class FFmpegMediaEngine:
    def __init__(self, ffmpeg_bin: str | None = None):
        self._ffmpeg = ffmpeg_bin or settings.ffmpeg_bin

    def render(self, source_path: str, segments: list[dict], output_path: str,
               resolution: str = "1080p") -> dict:
        if not segments:
            raise ValueError("no segments to render")
        height = _HEIGHTS.get(resolution, 1080)

        parts, concat_inputs = [], ""
        for i, seg in enumerate(segments):
            s, e = float(seg["start_sec"]), float(seg["end_sec"])
            parts.append(
                f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS,"
                f"scale=-2:{height}[v{i}]")
            parts.append(
                f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
            concat_inputs += f"[v{i}][a{i}]"
        filter_complex = ";".join(
            parts + [f"{concat_inputs}concat=n={len(segments)}:v=1:a=1[outv][outa]"])

        cmd = [
            self._ffmpeg, "-y", "-i", source_path,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
            "-movflags", "+faststart", output_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg render failed (exit {proc.returncode}): {proc.stderr[-800:]}")
        return {"size_bytes": os.path.getsize(output_path)}


def get_media_engine() -> FFmpegMediaEngine:
    """Factory for the configured media engine (arch §10)."""
    return FFmpegMediaEngine()
