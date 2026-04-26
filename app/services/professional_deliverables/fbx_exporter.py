from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.services.professional_deliverables.blender_runner import BlenderTool, run_blender_script
from app.services.professional_deliverables.scene_contract import SceneContract, TEXTURE_SLOTS, TextureSlot
from app.services.professional_deliverables.texture_authoring import AuthoredTexture

SCRIPT_PATH = Path(__file__).resolve().parent / "blender_scripts" / "export_fbx_scene.py"

FBX_PRESET_TWINMOTION: dict[str, Any] = {
    "units": "cm",
    "axis_up": "Z",
    "source_axis": "Y-up",
    "embed_media": True,
    "smoothing_groups": True,
    "triangulate": False,
    "apply_unit_scale": True,
    "global_scale": 1.0,
}


@dataclass(frozen=True)
class FBXExportResult:
    fbx_path: Path
    blender_tool: BlenderTool | None
    preset: dict[str, Any]


def _scene_payload(scene: SceneContract, authored: dict[str, dict[TextureSlot, AuthoredTexture]]) -> dict[str, Any]:
    return {
        "project_id": scene.project_id,
        "project_name": scene.project_name,
        "elements": [asdict(element) for element in scene.elements],
        "materials": [
            {
                "name": material.name,
                "base_color_rgba": material.channels.base_color_rgba,
                "roughness": material.channels.roughness,
                "metallic": material.channels.metallic,
                "texture_paths": {
                    slot: str(authored[material.name][slot].source_path)
                    for slot in TEXTURE_SLOTS
                },
            }
            for material in scene.materials
        ],
        "preset": FBX_PRESET_TWINMOTION,
    }


def export_fbx(
    scene: SceneContract,
    authored: dict[str, dict[TextureSlot, AuthoredTexture]],
    output_path: Path,
    *,
    require_binary: bool,
) -> FBXExportResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sprint2-fbx-payload-") as temp_name:
        payload_path = Path(temp_name) / "scene.json"
        payload_path.write_text(json.dumps(_scene_payload(scene, authored), indent=2), encoding="utf-8")
        blender = run_blender_script(
            SCRIPT_PATH,
            ["--scene-json", str(payload_path), "--output-fbx", str(output_path)],
            require_binary=require_binary,
        )
    return FBXExportResult(fbx_path=output_path, blender_tool=blender, preset=FBX_PRESET_TWINMOTION)
