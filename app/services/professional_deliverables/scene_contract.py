from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from app.services.professional_deliverables.drawing_contract import DeliverableValidationError

LODLevel = Literal[100, 200, 300]
TextureSlot = Literal["baseColor", "metallicRoughness", "normal", "ao", "emissive"]
TextureCodec = Literal["uastc", "etc1s"]
MaterialTier = Literal["hero", "standard", "mobile"]

TEXTURE_SLOTS: tuple[TextureSlot, ...] = ("baseColor", "metallicRoughness", "normal", "ao", "emissive")
VALID_LOD_LEVELS = {100, 200, 300}
METAL_ROUGH_WORKFLOW = "metallic-roughness"


@dataclass(frozen=True)
class TextureChannels:
    base_color_rgba: tuple[int, int, int, int]
    roughness: int
    metallic: int
    normal_rgba: tuple[int, int, int, int] = (128, 128, 255, 255)
    ao: int = 255
    emissive_rgba: tuple[int, int, int, int] = (0, 0, 0, 255)

    @property
    def metallic_roughness_rgba(self) -> tuple[int, int, int, int]:
        return (0, self.roughness, self.metallic, 255)

    @property
    def ao_rgba(self) -> tuple[int, int, int, int]:
        return (self.ao, self.ao, self.ao, 255)


@dataclass(frozen=True)
class MaterialSpec:
    name: str
    asset: str
    part: str
    tier: MaterialTier
    resolution_px: int
    texture_codec: TextureCodec
    channels: TextureChannels
    workflow: str = METAL_ROUGH_WORKFLOW

    @property
    def resolution_label(self) -> Literal["1K", "2K", "4K"]:
        if self.resolution_px == 1024:
            return "1K"
        if self.resolution_px == 2048:
            return "2K"
        if self.resolution_px == 4096:
            return "4K"
        raise DeliverableValidationError(f"Unsupported texture resolution for {self.name}: {self.resolution_px}")

    def texture_stem(self, slot: TextureSlot) -> str:
        return f"{self.name}_{slot}"

    def texture_filename(self, slot: TextureSlot, *, extension: str) -> str:
        return f"{self.texture_stem(slot)}.{extension.lstrip('.')}"

    def texture_relative_path(self, slot: TextureSlot) -> str:
        return f"textures/{self.texture_filename(slot, extension='ktx2')}"

    def as_manifest_material(self) -> dict:
        return {
            "name": self.name,
            "workflow": self.workflow,
            "textures": {slot: self.texture_relative_path(slot) for slot in TEXTURE_SLOTS},
            "resolution": self.resolution_label,
            "texture_codec": self.texture_codec,
            "tier": self.tier,
        }


@dataclass(frozen=True)
class BoxMeshElement:
    id: str
    name: str
    category: str
    lod: LODLevel
    material_name: str
    center_m: tuple[float, float, float]
    size_m: tuple[float, float, float]
    rotation_z_degrees: float = 0.0

    def as_metadata(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "lod": self.lod,
            "material": self.material_name,
        }


@dataclass(frozen=True)
class SceneContract:
    project_id: str
    project_name: str
    elements: tuple[BoxMeshElement, ...]
    materials: tuple[MaterialSpec, ...]

    @property
    def lod_summary(self) -> dict[str, int]:
        return {
            "lod_100": sum(1 for element in self.elements if element.lod == 100),
            "lod_200": sum(1 for element in self.elements if element.lod == 200),
            "lod_300": sum(1 for element in self.elements if element.lod == 300),
        }

    @property
    def material_by_name(self) -> dict[str, MaterialSpec]:
        return {material.name: material for material in self.materials}

    @property
    def referenced_material_names(self) -> tuple[str, ...]:
        return tuple(sorted({element.material_name for element in self.elements}))

    @property
    def expected_extents_cm(self) -> tuple[float, float, float]:
        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")
        for element in self.elements:
            sx, sy, sz = [value * 100.0 for value in element.size_m]
            cx, cy, cz = [value * 100.0 for value in element.center_m]
            hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
            angle = math.radians(element.rotation_z_degrees)
            c = math.cos(angle)
            s = math.sin(angle)
            for x in (-hx, hx):
                for y in (-hy, hy):
                    rx = x * c - y * s
                    ry = x * s + y * c
                    min_x = min(min_x, cx + rx)
                    max_x = max(max_x, cx + rx)
                    min_y = min(min_y, cy + ry)
                    max_y = max(max_y, cy + ry)
                    min_z = min(min_z, cz - hz)
                    max_z = max(max_z, cz + hz)
        return (max_x - min_x, max_y - min_y, max_z - min_z)

    @property
    def extents_tolerance_cm(self) -> tuple[float, float, float]:
        return tuple(max(5.0, value * 0.02) for value in self.expected_extents_cm)

    def as_metadata_stub(self, *, ktx_command: str | None = None) -> dict:
        payload = {
            "project_id": self.project_id,
            "version": "0.2.0",
            "lod_summary": self.lod_summary,
            "material_list": [material.as_manifest_material() for material in self.materials],
            "scene_elements": [element.as_metadata() for element in self.elements],
            "fbx_validation": {
                "expected_material_names": list(self.referenced_material_names),
                "expected_extents_cm": [round(value, 3) for value in self.expected_extents_cm],
                "extents_tolerance_cm": [round(value, 3) for value in self.extents_tolerance_cm],
            },
            "agent_provenance": {
                "sprint": "2",
                "step": "3d-core-formats",
            },
        }
        if ktx_command:
            payload["agent_provenance"]["ktx_command"] = ktx_command
        return payload


def validate_scene_contract(scene: SceneContract) -> None:
    if not scene.elements:
        raise DeliverableValidationError("3D scene must contain at least one element")
    if not scene.materials:
        raise DeliverableValidationError("3D scene must contain at least one material")
    material_names = {material.name for material in scene.materials}
    for material in scene.materials:
        if not material.name.startswith("MAT_"):
            raise DeliverableValidationError(f"Material {material.name} must use MAT_<asset>_<part> naming")
        if material.workflow != METAL_ROUGH_WORKFLOW:
            raise DeliverableValidationError(f"Material {material.name} must use Metal-Roughness workflow")
        if material.resolution_px not in {1024, 2048, 4096}:
            raise DeliverableValidationError(f"Material {material.name} uses unsupported resolution")
        if material.tier == "hero" and material.resolution_px < 2048:
            raise DeliverableValidationError(f"Hero material {material.name} must be at least 2K")
        if material.tier == "mobile" and material.resolution_px > 1024:
            raise DeliverableValidationError(f"Mobile material {material.name} must be at most 1K")
        for channel_name, value in (
            ("roughness", material.channels.roughness),
            ("metallic", material.channels.metallic),
            ("ao", material.channels.ao),
        ):
            if not 0 <= value <= 255:
                raise DeliverableValidationError(f"{material.name} {channel_name} must be in 0..255")
    for element in scene.elements:
        if element.lod not in VALID_LOD_LEVELS:
            raise DeliverableValidationError(f"Element {element.id} has invalid LOD {element.lod}")
        if element.material_name not in material_names:
            raise DeliverableValidationError(f"Element {element.id} references unknown material {element.material_name}")
        if any(size <= 0 for size in element.size_m):
            raise DeliverableValidationError(f"Element {element.id} has non-positive dimensions")
