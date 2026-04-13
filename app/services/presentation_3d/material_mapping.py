from __future__ import annotations

from typing import Any


def build_material_mapping(brief_json: dict[str, Any], geometry: dict[str, Any]) -> dict[str, Any]:
    style = str((brief_json or {}).get("style") or "modern_minimalist")
    room_finishes = {
        room["id"]: room.get("finishes") or {}
        for room in geometry.get("rooms", [])
        if room.get("id")
    }
    return {
        "style_profile": style,
        "room_finishes": room_finishes,
        "lighting_preset": "warm_daylight" if "warm" in style.lower() else "neutral_daylight",
        "landscape_preset": "tropical_soft" if "tropical" in style.lower() else "urban_clean",
        "furniture_density_preset": "client_presentation",
    }
