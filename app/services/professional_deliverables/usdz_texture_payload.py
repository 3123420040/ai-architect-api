from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.professional_deliverables.ktx2_encoder import (
    ExternalToolError,
    KTXTool,
    extract_ktx_rgba8_sample,
    validate_ktx,
)
from app.services.professional_deliverables.scene_contract import MaterialSpec, TEXTURE_SLOTS, TextureSlot
from app.services.professional_deliverables.texture_authoring import write_solid_rgba_png
from app.services.professional_deliverables.usdz_materials import build_usdz_material_payloads


@dataclass(frozen=True)
class USDZTexturePayload:
    material_name: str
    files: dict[str, Path]
    resolution_px: int


def _sample_slot(tool: KTXTool, ktx_path: Path, temp_dir: Path, *, material_name: str, slot: TextureSlot) -> tuple[int, int, int, int]:
    validate_ktx(tool, ktx_path)
    return extract_ktx_rgba8_sample(tool, ktx_path, temp_dir / f"{material_name}_{slot}.rgba")


def build_usdz_texture_payload(
    materials: tuple[MaterialSpec, ...],
    textures_dir: Path,
    payload_dir: Path,
    temp_dir: Path,
    *,
    ktx_tool: KTXTool,
    max_resolution_px: int,
) -> tuple[USDZTexturePayload, ...]:
    payload_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[USDZTexturePayload] = []
    payloads = {payload.material.name: payload for payload in build_usdz_material_payloads(materials)}
    for material in materials:
        resolution = min(material.resolution_px, max_resolution_px)
        slot_samples: dict[TextureSlot, tuple[int, int, int, int]] = {}
        for slot in TEXTURE_SLOTS:
            ktx_path = textures_dir / material.texture_filename(slot, extension="ktx2")
            if not ktx_path.exists():
                raise ExternalToolError(f"Missing Sprint 2 KTX2 texture for USDZ payload: {ktx_path}")
            slot_samples[slot] = _sample_slot(ktx_tool, ktx_path, temp_dir, material_name=material.name, slot=slot)

        payload_files: dict[str, Path] = {}
        texture_names = payloads[material.name].textures

        diffuse = payload_dir / Path(texture_names["diffuseColor"]).name
        write_solid_rgba_png(diffuse, size_px=resolution, color=slot_samples["baseColor"])
        payload_files["diffuseColor"] = diffuse

        mr = slot_samples["metallicRoughness"]
        metallic = payload_dir / Path(texture_names["metallic"]).name
        roughness = payload_dir / Path(texture_names["roughness"]).name
        write_solid_rgba_png(metallic, size_px=resolution, color=(mr[2], mr[2], mr[2], 255))
        write_solid_rgba_png(roughness, size_px=resolution, color=(mr[1], mr[1], mr[1], 255))
        payload_files["metallic"] = metallic
        payload_files["roughness"] = roughness

        normal = payload_dir / Path(texture_names["normal"]).name
        write_solid_rgba_png(normal, size_px=resolution, color=slot_samples["normal"])
        payload_files["normal"] = normal

        ao = slot_samples["ao"]
        occlusion = payload_dir / Path(texture_names["occlusion"]).name
        write_solid_rgba_png(occlusion, size_px=resolution, color=(ao[0], ao[0], ao[0], 255))
        payload_files["occlusion"] = occlusion

        emissive = payload_dir / Path(texture_names["emissiveColor"]).name
        write_solid_rgba_png(emissive, size_px=resolution, color=slot_samples["emissive"])
        payload_files["emissiveColor"] = emissive

        outputs.append(USDZTexturePayload(material_name=material.name, files=payload_files, resolution_px=resolution))
    return tuple(outputs)
