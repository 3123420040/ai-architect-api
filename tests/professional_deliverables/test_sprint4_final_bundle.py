from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.professional_deliverables.manifest_builder import build_manifest
from app.services.professional_deliverables.sprint4_validators import run_sprint4_gates
from app.services.professional_deliverables.video_derivatives import derive_sprint4_video_outputs


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required for Sprint 4 derivative gates",
)


def _write_master(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=3840x2160:rate=30:duration=20.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _write_bundle_root(root: Path) -> None:
    for relative in ["2d/bundle.pdf", "2d/A-101-F1-floorplan.dxf", "3d/model.glb", "3d/model.fbx", "3d/model.usdz"]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"artifact")
    (root / "3d" / "sprint2_model_metadata.json").write_text(
        json.dumps(
            {
                "lod_summary": {"lod_100": 1, "lod_200": 2, "lod_300": 3},
                "scene_elements": [{"id": str(index)} for index in range(6)],
                "material_list": [
                    {
                        "name": "MAT_wall_plaster",
                        "workflow": "metallic-roughness",
                        "textures": {},
                        "resolution": "2K",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_sprint4_derivatives_manifest_and_gates(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_bundle_root(root)
    _write_master(root / "video" / "master_4k.mp4")

    outputs = derive_sprint4_video_outputs(root)
    manifest = build_manifest(root, project_id="project-1", source_brief={"style": "tropical"})
    gates, summary_json, summary_md = run_sprint4_gates(root)

    assert outputs["reel"].relative_to(root).as_posix() == "video/reel_9x16_1080p.mp4"
    assert outputs["hero_still"].exists()
    assert outputs["gif_preview"].stat().st_size <= 5 * 1024 * 1024
    assert manifest.exists()
    assert summary_json.exists()
    assert summary_md.exists()
    assert all(gate.status == "pass" for gate in gates)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    paths = {item["path"] for item in payload["file_inventory"]}
    assert "video/reel_9x16_1080p.mp4" in paths
    assert "derivatives/hero_still_4k.png" in paths
    assert "derivatives/preview.gif" in paths
    assert all(not Path(path).is_absolute() for path in paths)


def test_sprint4_missing_master_fails(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_bundle_root(root)

    with pytest.raises(Exception, match="master"):
        derive_sprint4_video_outputs(root)
