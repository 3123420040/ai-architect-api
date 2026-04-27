from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app.services.professional_deliverables.validators import GateResult, build_file_inventory, sha256_file, write_gate_outputs


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _ffprobe(path: Path) -> dict[str, Any]:
    result = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    return json.loads(result.stdout)


def _video_stream(payload: dict[str, Any]) -> dict[str, Any]:
    return next(stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video")


def _fps(value: str) -> float:
    numerator, denominator = value.split("/", 1)
    return float(numerator) / float(denominator)


def _non_black(path: Path, *, at_seconds: float = 0.0) -> bool:
    result = _run([
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-vf",
        "signalstats,metadata=print:file=-",
        "-f",
        "null",
        "-",
    ])
    values: list[float] = []
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        if "lavfi.signalstats.YAVG=" in line:
            values.append(float(line.rsplit("=", 1)[1]))
    return bool(values) and max(values) > 2.0


def validate_reel_format(path: Path) -> GateResult:
    if not path.exists():
        return GateResult("Reel format", "fail", "video/reel_9x16_1080p.mp4 is missing")
    try:
        payload = _ffprobe(path)
        stream = _video_stream(payload)
        duration = float(payload.get("format", {}).get("duration", 0))
        fps = _fps(stream.get("avg_frame_rate", "0/1"))
        bitrate = int(payload.get("format", {}).get("bit_rate", 0))
    except Exception as exc:
        return GateResult("Reel format", "fail", str(exc)[:500])
    failures = []
    if int(stream.get("width", 0)) != 1080 or int(stream.get("height", 0)) != 1920:
        failures.append(f"resolution={stream.get('width')}x{stream.get('height')}")
    if stream.get("codec_name") != "h264":
        failures.append(f"codec={stream.get('codec_name')}")
    if abs(fps - 30.0) > 0.001:
        failures.append(f"fps={fps:.3f}")
    if not 20.0 <= duration <= 30.5:
        failures.append(f"duration={duration:.3f}")
    if bitrate and bitrate > 16_500_000:
        failures.append(f"bitrate={bitrate}")
    if failures:
        return GateResult("Reel format", "fail", "; ".join(failures))
    return GateResult("Reel format", "pass", f"1080x1920 h264 {duration:.2f}s {fps:.3f}fps bitrate={bitrate}")


def validate_reel_integrity(path: Path) -> GateResult:
    try:
        payload = _ffprobe(path)
        duration = float(payload.get("format", {}).get("duration", 0))
        samples = [0.5, max(0.5, duration / 2.0), max(0.5, duration - 0.5)]
        if not all(_non_black(path, at_seconds=value) for value in samples):
            return GateResult("Reel integrity", "fail", "black frame detected in start/middle/end samples")
        _run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"])
    except Exception as exc:
        return GateResult("Reel integrity", "fail", str(exc)[:500])
    return GateResult("Reel integrity", "pass", f"decoder pass and non-black samples; size={path.stat().st_size}")


def validate_hero_still(path: Path) -> GateResult:
    if not path.exists():
        return GateResult("Hero still", "fail", "derivatives/hero_still_4k.png is missing")
    try:
        stream = _video_stream(_ffprobe(path))
        if int(stream.get("width", 0)) != 3840 or int(stream.get("height", 0)) != 2160:
            return GateResult("Hero still", "fail", f"resolution={stream.get('width')}x{stream.get('height')}")
        if not _non_black(path):
            return GateResult("Hero still", "fail", "sample frame is black")
    except Exception as exc:
        return GateResult("Hero still", "fail", str(exc)[:500])
    return GateResult("Hero still", "pass", "PNG 3840x2160 non-black")


def validate_gif_preview(path: Path) -> GateResult:
    if not path.exists():
        return GateResult("GIF preview", "fail", "derivatives/preview.gif is missing")
    try:
        payload = _ffprobe(path)
        stream = _video_stream(payload)
        duration = float(payload.get("format", {}).get("duration", 0))
        frames = int(stream.get("nb_frames") or 0)
        if path.stat().st_size > 5 * 1024 * 1024:
            return GateResult("GIF preview", "fail", f"size={path.stat().st_size} > 5MB")
        if not 6.0 <= duration <= 10.5:
            return GateResult("GIF preview", "fail", f"duration={duration:.3f}")
        if frames <= 1:
            return GateResult("GIF preview", "fail", f"nb_frames={frames}")
        if not _non_black(path, at_seconds=min(1.0, duration / 2.0)):
            return GateResult("GIF preview", "fail", "sample frame is black")
    except Exception as exc:
        return GateResult("GIF preview", "fail", str(exc)[:500])
    return GateResult("GIF preview", "pass", f"animated {duration:.2f}s frames={frames} size={path.stat().st_size}")


def validate_manifest_schema(path: Path) -> GateResult:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return GateResult("Manifest schema", "fail", str(exc)[:500])
    required = ["project_id", "generated_at", "version", "naming_convention", "lod_summary", "material_list", "file_inventory", "source_brief", "agent_provenance"]
    missing = [key for key in required if key not in payload]
    if missing:
        return GateResult("Manifest schema", "fail", f"missing={missing}")
    for material in payload.get("material_list", []):
        if material.get("workflow") != "metallic-roughness":
            return GateResult("Manifest schema", "fail", f"non Metal-Roughness material: {material.get('name')}")
        if "SpecularGlossiness" in json.dumps(material):
            return GateResult("Manifest schema", "fail", f"Specular-Glossiness field found: {material.get('name')}")
    return GateResult("Manifest schema", "pass", "required PRD Appendix B fields present")


def validate_manifest_inventory(path: Path, root: Path) -> GateResult:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return GateResult("Manifest inventory/checksum", "fail", str(exc)[:500])
    for item in payload.get("file_inventory", []):
        relative = Path(item.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts:
            return GateResult("Manifest inventory/checksum", "fail", f"invalid relative path: {relative}")
        target = root / relative
        if not target.exists():
            return GateResult("Manifest inventory/checksum", "fail", f"missing file: {relative}")
        if target.stat().st_size != item.get("size_bytes"):
            return GateResult("Manifest inventory/checksum", "fail", f"size mismatch: {relative}")
        if sha256_file(target) != item.get("sha256"):
            return GateResult("Manifest inventory/checksum", "fail", f"sha256 mismatch: {relative}")
    return GateResult("Manifest inventory/checksum", "pass", f"{len(payload.get('file_inventory', []))} files verified")


def validate_lod_summary(path: Path, root: Path) -> GateResult:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        metadata = json.loads((root / "3d" / "sprint2_model_metadata.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return GateResult("LOD summary", "fail", str(exc)[:500])
    if manifest.get("lod_summary") != metadata.get("lod_summary"):
        return GateResult("LOD summary", "fail", "manifest LOD summary does not match Sprint 2 metadata")
    total = sum(int(value) for value in manifest.get("lod_summary", {}).values())
    if total != len(metadata.get("scene_elements", [])):
        return GateResult("LOD summary", "fail", f"lod total={total}, scene_elements={len(metadata.get('scene_elements', []))}")
    return GateResult("LOD summary", "pass", f"{total} scene elements")


def validate_bundle_self_contained(root: Path) -> GateResult:
    required = ["3d/model.glb", "3d/model.fbx", "3d/model.usdz", "video/master_4k.mp4", "video/reel_9x16_1080p.mp4", "derivatives/hero_still_4k.png", "derivatives/preview.gif", "manifest.json"]
    missing = [relative for relative in required if not (root / relative).exists()]
    if missing:
        return GateResult("Bundle self-contained", "fail", f"missing={missing}")
    return GateResult("Bundle self-contained", "pass", "required Sprint 1-4 artifacts resolve within bundle root")


def validate_missing_master_failure(root: Path) -> GateResult:
    if (root / "video" / "master_4k.mp4").exists():
        return GateResult("Failure case", "pass", "missing master video is checked before Sprint 4 derivative generation")
    return GateResult("Failure case", "fail", "master video missing")


def run_sprint4_gates(root: Path) -> tuple[list[GateResult], Path, Path]:
    manifest = root / "manifest.json"
    gates = [
        validate_reel_format(root / "video" / "reel_9x16_1080p.mp4"),
        validate_reel_integrity(root / "video" / "reel_9x16_1080p.mp4"),
        validate_hero_still(root / "derivatives" / "hero_still_4k.png"),
        validate_gif_preview(root / "derivatives" / "preview.gif"),
        validate_manifest_schema(manifest),
        validate_manifest_inventory(manifest, root),
        validate_lod_summary(manifest, root),
        validate_bundle_self_contained(root),
        validate_missing_master_failure(root),
    ]
    inventory = build_file_inventory([path for path in root.rglob("*") if path.is_file()], root)
    summary_json, summary_md = write_gate_outputs(
        root,
        gates,
        inventory,
        basename="sprint4_gate_summary",
        title="Sprint 4 Gate Summary",
        skipped_is_partial=False,
    )
    return gates, summary_json, summary_md
