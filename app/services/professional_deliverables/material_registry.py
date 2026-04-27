from __future__ import annotations

from app.services.professional_deliverables.scene_contract import MaterialSpec, TextureChannels


GOLDEN_MATERIALS: tuple[MaterialSpec, ...] = (
    MaterialSpec(
        name="MAT_building_wall",
        asset="building",
        part="wall",
        tier="hero",
        resolution_px=2048,
        texture_codec="uastc",
        channels=TextureChannels(base_color_rgba=(224, 226, 216, 255), roughness=184, metallic=0, ao=238),
    ),
    MaterialSpec(
        name="MAT_building_floor",
        asset="building",
        part="floor",
        tier="hero",
        resolution_px=2048,
        texture_codec="uastc",
        channels=TextureChannels(base_color_rgba=(186, 184, 171, 255), roughness=154, metallic=0, ao=230),
    ),
    MaterialSpec(
        name="MAT_building_roof",
        asset="building",
        part="roof",
        tier="hero",
        resolution_px=4096,
        texture_codec="uastc",
        channels=TextureChannels(base_color_rgba=(151, 64, 45, 255), roughness=206, metallic=0, ao=226),
    ),
    MaterialSpec(
        name="MAT_opening_glass",
        asset="opening",
        part="glass",
        tier="standard",
        resolution_px=2048,
        texture_codec="uastc",
        channels=TextureChannels(
            base_color_rgba=(154, 196, 213, 180),
            roughness=42,
            metallic=0,
            ao=245,
            emissive_rgba=(6, 10, 12, 255),
        ),
    ),
    MaterialSpec(
        name="MAT_opening_door",
        asset="opening",
        part="door",
        tier="standard",
        resolution_px=2048,
        texture_codec="uastc",
        channels=TextureChannels(base_color_rgba=(126, 82, 48, 255), roughness=138, metallic=0, ao=225),
    ),
    MaterialSpec(
        name="MAT_fixture_plumbing",
        asset="fixture",
        part="plumbing",
        tier="standard",
        resolution_px=2048,
        texture_codec="uastc",
        channels=TextureChannels(base_color_rgba=(235, 238, 236, 255), roughness=86, metallic=0, ao=242),
    ),
    MaterialSpec(
        name="MAT_fixture_furniture",
        asset="fixture",
        part="furniture",
        tier="mobile",
        resolution_px=1024,
        texture_codec="etc1s",
        channels=TextureChannels(base_color_rgba=(89, 120, 111, 255), roughness=168, metallic=0, ao=232),
    ),
    MaterialSpec(
        name="MAT_site_ground",
        asset="site",
        part="ground",
        tier="standard",
        resolution_px=2048,
        texture_codec="etc1s",
        channels=TextureChannels(base_color_rgba=(97, 126, 87, 255), roughness=212, metallic=0, ao=218),
    ),
    MaterialSpec(
        name="MAT_site_vegetation",
        asset="site",
        part="vegetation",
        tier="mobile",
        resolution_px=1024,
        texture_codec="etc1s",
        channels=TextureChannels(base_color_rgba=(45, 116, 72, 255), roughness=190, metallic=0, ao=226),
    ),
)


def golden_materials_by_name() -> dict[str, MaterialSpec]:
    return {material.name: material for material in GOLDEN_MATERIALS}
