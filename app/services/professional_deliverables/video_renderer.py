from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.services.professional_deliverables.blender_runner import BlenderToolError, run_blender_script
from app.services.professional_deliverables.camera_path import CameraPath

RENDER_SCRIPT = Path(__file__).resolve().parent / "blender_scripts" / "render_master_video.py"


class VideoRenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoRenderProfile:
    name: str
    width: int
    height: int
    fps: int
    duration_s: float
    codec: str
    crf: int
    preset: str


CI_FAST_4K = VideoRenderProfile(
    name="CI_FAST_4K",
    width=3840,
    height=2160,
    fps=30,
    duration_s=60.0,
    codec="libx264",
    crf=30,
    preset="ultrafast",
)

PRODUCTION_4K_CYCLES_GPU = {
    "renderer": "CYCLES",
    "device": "GPU",
    "samples": 96,
    "denoiser": "OPENIMAGEDENOISE",
    "max_bounces": 6,
    "diffuse_bounces": 3,
    "glossy_bounces": 3,
    "transparent_max_bounces": 4,
    "color_management": {
        "view_transform": "AgX",
        "look": "Medium High Contrast",
        "exposure": 0.0,
        "gamma": 1.0,
        "display_device": "sRGB",
    },
}


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def discover_ffmpeg(*, require_binary: bool) -> Path | None:
    candidates = []
    if os.environ.get("FFMPEG_BIN"):
        candidates.append(os.environ["FFMPEG_BIN"])
    candidates.append("ffmpeg")
    for candidate in candidates:
        resolved = shutil.which(candidate) if not Path(candidate).exists() else candidate
        if resolved:
            return Path(resolved)
    if require_binary:
        raise VideoRenderError("FFMPEG_BIN/ffmpeg was not found")
    return None


def _encode_stills(stills_report: Path, output_mp4: Path, profile: VideoRenderProfile, *, require_binary: bool) -> Path | None:
    ffmpeg = discover_ffmpeg(require_binary=require_binary)
    if ffmpeg is None:
        return None
    report = json.loads(stills_report.read_text(encoding="utf-8"))
    stills = report["stills"]
    command = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error"]
    filters: list[str] = []
    labels: list[str] = []
    for index, still in enumerate(stills):
        command.extend(["-loop", "1", "-t", f"{still['duration_s']:.3f}", "-i", still["path"]])
        label = f"v{index}"
        labels.append(f"[{label}]")
        filters.append(
            f"[{index}:v]fps={profile.fps},scale={profile.width}:{profile.height},setsar=1,format=yuv420p[{label}]"
        )
    filter_complex = ";".join(filters) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[outv]"
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-r",
            str(profile.fps),
            "-c:v",
            profile.codec,
            "-preset",
            profile.preset,
            "-crf",
            str(profile.crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-threads",
            "1",
            str(output_mp4),
        ]
    )
    result = _run(command)
    if result.returncode != 0:
        detail = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if line.strip())
        raise VideoRenderError(f"ffmpeg encode failed: {detail}")
    return output_mp4


def render_master_video(
    glb_path: Path,
    camera_path: CameraPath,
    video_dir: Path,
    work_dir: Path,
    *,
    require_external_tools: bool,
    profile: VideoRenderProfile = CI_FAST_4K,
) -> Path | None:
    if not glb_path.exists():
        raise VideoRenderError(f"Source GLB not found: {glb_path}")
    video_dir.mkdir(parents=True, exist_ok=True)
    camera_path_json = video_dir / "camera_path.json"
    camera_path_json.write_text(json.dumps(camera_path.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    stills_dir = work_dir / f"stills-{profile.name.lower()}"
    stills_report = video_dir / "render_stills_report.json"
    try:
        blender = run_blender_script(
            RENDER_SCRIPT,
            [
                "--glb",
                str(glb_path),
                "--camera-path-json",
                str(camera_path_json),
                "--stills-dir",
                str(stills_dir),
                "--report-json",
                str(stills_report),
            ],
            require_binary=require_external_tools,
        )
    except BlenderToolError as exc:
        raise VideoRenderError(str(exc)) from exc
    if blender is None:
        return None
    return _encode_stills(stills_report, video_dir / "master_4k.mp4", profile, require_binary=require_external_tools)
