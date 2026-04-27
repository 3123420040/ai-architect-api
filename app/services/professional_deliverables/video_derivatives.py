from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class VideoDerivativeError(RuntimeError):
    pass


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise VideoDerivativeError(f"Required tool not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise VideoDerivativeError(detail[:1200]) from exc


def _duration_seconds(path: Path) -> float:
    result = _run([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ])
    payload = json.loads(result.stdout)
    return float(payload["format"]["duration"])


def derive_sprint4_video_outputs(bundle_root: Path) -> dict[str, Path]:
    master = bundle_root / "video" / "master_4k.mp4"
    if not master.exists():
        raise VideoDerivativeError("Missing required master video: video/master_4k.mp4")
    if not shutil.which("ffmpeg"):
        raise VideoDerivativeError("Required tool not found: ffmpeg")
    if not shutil.which("ffprobe"):
        raise VideoDerivativeError("Required tool not found: ffprobe")

    video_dir = bundle_root / "video"
    derivatives_dir = bundle_root / "derivatives"
    derivatives_dir.mkdir(parents=True, exist_ok=True)
    reel = video_dir / "reel_9x16_1080p.mp4"
    hero = derivatives_dir / "hero_still_4k.png"
    preview = derivatives_dir / "preview.gif"

    duration = _duration_seconds(master)
    reel_duration = min(30.0, max(20.0, duration - 0.5))
    reel_start = 0.0 if duration <= reel_duration else min(10.0, max(0.0, (duration - reel_duration) / 2.0))
    hero_time = min(10.0, max(0.0, duration / 2.0))
    gif_duration = min(8.0, max(6.0, duration - 0.5))
    gif_start = 6.0 if duration >= 14.0 else max(0.0, duration - gif_duration - 0.25)

    _run([
        "ffmpeg",
        "-y",
        "-ss",
        f"{reel_start:.3f}",
        "-i",
        str(master),
        "-t",
        f"{reel_duration:.3f}",
        "-vf",
        "crop=min(iw\\,ih*9/16):ih:(iw-min(iw\\,ih*9/16))/2:0,scale=1080:1920,fps=30,setsar=1",
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-b:v",
        "12M",
        "-maxrate",
        "15M",
        "-bufsize",
        "24M",
        "-movflags",
        "+faststart",
        "-an",
        str(reel),
    ])
    _run([
        "ffmpeg",
        "-y",
        "-ss",
        f"{hero_time:.3f}",
        "-i",
        str(master),
        "-frames:v",
        "1",
        "-vf",
        "scale=3840:2160:force_original_aspect_ratio=decrease,pad=3840:2160:(ow-iw)/2:(oh-ih)/2",
        str(hero),
    ])
    _run([
        "ffmpeg",
        "-y",
        "-ss",
        f"{gif_start:.3f}",
        "-i",
        str(master),
        "-t",
        f"{gif_duration:.3f}",
        "-vf",
        "fps=8,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=64[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5",
        "-loop",
        "0",
        str(preview),
    ])
    if preview.stat().st_size > 5 * 1024 * 1024:
        _run([
            "ffmpeg",
            "-y",
            "-ss",
            f"{gif_start:.3f}",
            "-i",
            str(master),
            "-t",
            "6.000",
            "-vf",
            "fps=6,scale=360:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=48[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5",
            "-loop",
            "0",
            str(preview),
        ])
    return {"reel": reel, "hero_still": hero, "gif_preview": preview}
