from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from app.services.professional_deliverables.validators import GateResult

MASTER_VIDEO_MAX_BYTES = 200 * 1024 * 1024


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _tool(name: str, env_var: str, *, require_binary: bool) -> Path | None:
    candidates = []
    if os.environ.get(env_var):
        candidates.append(os.environ[env_var])
    candidates.append(name)
    for candidate in candidates:
        resolved = shutil.which(candidate) if not Path(candidate).exists() else candidate
        if resolved:
            return Path(resolved)
    if require_binary:
        raise FileNotFoundError(f"{env_var}/{name} was not found")
    return None


def _ffprobe(path: Path, *, require_binary: bool) -> dict | None:
    ffprobe = _tool("ffprobe", "FFPROBE_BIN", require_binary=require_binary)
    if ffprobe is None:
        return None
    result = _run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "ffprobe failed")
    return json.loads(result.stdout)


def _video_stream(report: dict) -> dict:
    for stream in report.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    raise ValueError("No video stream found")


def _fps(value: str) -> float:
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator)
    return float(value)


def validate_master_video_format(video_path: Path, report_path: Path, *, require_binary: bool) -> GateResult:
    if not video_path.exists():
        return GateResult("Master video format", "fail" if require_binary else "skipped", "master_4k.mp4 was not produced")
    try:
        report = _ffprobe(video_path, require_binary=require_binary)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return GateResult("Master video format", "fail" if require_binary else "skipped", str(exc))
    if report is None:
        return GateResult("Master video format", "skipped", "ffprobe unavailable locally; CI runs this gate")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    stream = _video_stream(report)
    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))
    fps = _fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0")
    codec = stream.get("codec_name")
    duration = float(stream.get("duration") or report.get("format", {}).get("duration") or 0)
    failures = []
    if width != 3840 or height != 2160:
        failures.append(f"resolution {width}x{height} != 3840x2160")
    if abs(fps - 30.0) > 0.001:
        failures.append(f"fps {fps:.3f} != 30.000")
    if codec != "h264":
        failures.append(f"codec {codec} != h264")
    if not 58.0 <= duration <= 62.0:
        failures.append(f"duration {duration:.3f}s outside [58, 62]")
    if failures:
        return GateResult("Master video format", "fail", "; ".join(failures))
    return GateResult("Master video format", "pass", f"{width}x{height}, {fps:.3f} fps, {codec}, {duration:.3f}s")


def _frame_rgb_sample(video_path: Path, timestamp_s: float, *, require_binary: bool) -> bytes | None:
    ffmpeg = _tool("ffmpeg", "FFMPEG_BIN", require_binary=require_binary)
    if ffmpeg is None:
        return None
    result = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-ss",
            f"{timestamp_s:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=64:36",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise ValueError(result.stderr.decode("utf-8", errors="ignore") or "ffmpeg frame sample failed")
    return result.stdout


def _is_all_black(frame: bytes) -> bool:
    if not frame:
        return True
    return max(frame) < 8 or (sum(frame) / len(frame) < 3 and len(set(frame[: min(len(frame), 4096)])) <= 3)


def validate_master_video_integrity(video_path: Path, report_path: Path, *, require_binary: bool) -> GateResult:
    if not video_path.exists():
        return GateResult("Master video integrity", "fail" if require_binary else "skipped", "master_4k.mp4 was not produced")
    ffmpeg = _tool("ffmpeg", "FFMPEG_BIN", require_binary=require_binary)
    if ffmpeg is None:
        return GateResult("Master video integrity", "skipped", "ffmpeg unavailable locally; CI runs this gate")
    decode = _run([str(ffmpeg), "-v", "error", "-i", str(video_path), "-f", "null", "-"])
    if decode.returncode != 0:
        return GateResult("Master video integrity", "fail", decode.stderr.strip()[:700])
    size = video_path.stat().st_size
    if size > MASTER_VIDEO_MAX_BYTES:
        return GateResult("Master video integrity", "fail", f"{size} bytes > {MASTER_VIDEO_MAX_BYTES}")
    try:
        first = _frame_rgb_sample(video_path, 0.5, require_binary=require_binary)
        last = _frame_rgb_sample(video_path, 59.0, require_binary=require_binary)
    except ValueError as exc:
        return GateResult("Master video integrity", "fail", str(exc))
    black = []
    if first is not None and _is_all_black(first):
        black.append("first second")
    if last is not None and _is_all_black(last):
        black.append("last second")
    report_path.write_text(
        json.dumps(
            {
                "size_bytes": size,
                "first_frame_sha256": hashlib.sha256(first or b"").hexdigest(),
                "last_frame_sha256": hashlib.sha256(last or b"").hexdigest(),
                "black_segments": black,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if black:
        return GateResult("Master video integrity", "fail", f"All-black frame detected in {black}")
    return GateResult("Master video integrity", "pass", f"decoder clean, {size} bytes, first/last frames non-black")


def frame_hashes(video_path: Path, timestamps_s: tuple[float, ...], *, require_binary: bool) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for timestamp in timestamps_s:
        frame = _frame_rgb_sample(video_path, timestamp, require_binary=require_binary)
        if frame is None:
            return {}
        hashes[f"{timestamp:.3f}"] = hashlib.sha256(frame).hexdigest()
    return hashes


def validate_camera_path_determinism(
    first_video: Path,
    second_video: Path,
    report_path: Path,
    *,
    require_binary: bool,
) -> GateResult:
    if not first_video.exists() or not second_video.exists():
        return GateResult(
            "Camera path determinism",
            "fail" if require_binary else "skipped",
            "Two rendered videos are required for determinism check",
        )
    try:
        first_probe = _ffprobe(first_video, require_binary=require_binary)
        second_probe = _ffprobe(second_video, require_binary=require_binary)
        if first_probe is None or second_probe is None:
            return GateResult("Camera path determinism", "skipped", "ffprobe unavailable locally; CI runs this gate")
        first_duration = float(_video_stream(first_probe).get("duration") or first_probe.get("format", {}).get("duration") or 0)
        second_duration = float(_video_stream(second_probe).get("duration") or second_probe.get("format", {}).get("duration") or 0)
        first_hashes = frame_hashes(first_video, (0.0, 30.0, 58.0), require_binary=require_binary)
        second_hashes = frame_hashes(second_video, (0.0, 30.0, 58.0), require_binary=require_binary)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return GateResult("Camera path determinism", "fail" if require_binary else "skipped", str(exc))
    report = {
        "first_duration": first_duration,
        "second_duration": second_duration,
        "first_hashes": first_hashes,
        "second_hashes": second_hashes,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if abs(first_duration - second_duration) > (1.0 / 30.0):
        return GateResult("Camera path determinism", "fail", f"duration mismatch {first_duration} vs {second_duration}")
    if first_hashes != second_hashes:
        return GateResult("Camera path determinism", "fail", "sample frame hashes differ at t=0,30,58")
    return GateResult("Camera path determinism", "pass", "duration and frame hashes match at t=0s, t=30s, t=58s")
