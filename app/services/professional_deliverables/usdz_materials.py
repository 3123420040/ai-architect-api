from __future__ import annotations

from dataclasses import dataclass

from app.services.professional_deliverables.scene_contract import MaterialSpec

USD_PREVIEW_INPUTS = ("diffuseColor", "metallic", "roughness", "normal", "occlusion", "emissiveColor")


@dataclass(frozen=True)
class USDZMaterialPayload:
    material: MaterialSpec
    textures: dict[str, str]

    def as_dict(self) -> dict:
        return {
            "name": self.material.name,
            "workflow": "UsdPreviewSurface",
            "textures": self.textures,
        }


def usdz_texture_names(material: MaterialSpec) -> dict[str, str]:
    prefix = material.name
    return {
        "diffuseColor": f"textures/{prefix}_diffuseColor.png",
        "metallic": f"textures/{prefix}_metallic.png",
        "roughness": f"textures/{prefix}_roughness.png",
        "normal": f"textures/{prefix}_normal.png",
        "occlusion": f"textures/{prefix}_occlusion.png",
        "emissiveColor": f"textures/{prefix}_emissiveColor.png",
    }


def build_usdz_material_payloads(materials: tuple[MaterialSpec, ...]) -> tuple[USDZMaterialPayload, ...]:
    return tuple(USDZMaterialPayload(material=material, textures=usdz_texture_names(material)) for material in materials)
