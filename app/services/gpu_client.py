from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.core.config import settings


def _fallback_option(project_id: str, option_index: int, brief_json: dict) -> dict:
    width = brief_json.get("lot", {}).get("width_m", 5)
    depth = brief_json.get("lot", {}).get("depth_m", 20)
    floors = brief_json.get("floors", 3)
    style = brief_json.get("style", "modern")
    accent = ["#a94f2d", "#205d67", "#6f5b2e"][option_index % 3]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="720" viewBox="0 0 960 720">
<rect width="960" height="720" fill="#fffaf1"/>
<rect x="90" y="120" width="780" height="480" rx="32" fill="#f2e6d5" stroke="{accent}" stroke-width="8"/>
<rect x="130" y="160" width="280" height="180" rx="20" fill="#ffffff" stroke="{accent}" stroke-width="4"/>
<rect x="450" y="160" width="370" height="180" rx="20" fill="#ffffff" stroke="{accent}" stroke-width="4"/>
<rect x="130" y="380" width="200" height="160" rx="20" fill="#ffffff" stroke="{accent}" stroke-width="4"/>
<rect x="370" y="380" width="200" height="160" rx="20" fill="#ffffff" stroke="{accent}" stroke-width="4"/>
<rect x="610" y="380" width="210" height="160" rx="20" fill="#ffffff" stroke="{accent}" stroke-width="4"/>
<text x="130" y="70" fill="#1c160f" font-size="36" font-family="Arial">KTC KTS - Option {chr(65 + option_index)}</text>
<text x="130" y="100" fill="#5f5446" font-size="20" font-family="Arial">{style} | {width}m x {depth}m | {floors} tang</text>
<text x="170" y="250" fill="#1c160f" font-size="28" font-family="Arial">Phong khach</text>
<text x="540" y="250" fill="#1c160f" font-size="28" font-family="Arial">Bep + An</text>
<text x="165" y="470" fill="#1c160f" font-size="28" font-family="Arial">Ngu 1</text>
<text x="405" y="470" fill="#1c160f" font-size="28" font-family="Arial">Ngu 2</text>
<text x="660" y="470" fill="#1c160f" font-size="28" font-family="Arial">WC + Kho</text>
</svg>"""
    return {
        "label": f"Option {chr(65 + option_index)}",
        "description": f"Phuong an {option_index + 1} cho {project_id}",
        "svg": svg,
        "pipeline": "svg-fallback-v1",
        "seed": 1000 + option_index,
        "duration_ms": 350 + (option_index * 80),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _fallback_render(brief_json: dict, render_index: int) -> str:
    style = brief_json.get("style", "modern_minimalist")
    project_type = brief_json.get("project_type", "townhouse")
    accent = ["#a94f2d", "#205d67"][render_index % 2]
    title = "Phoi canh ngoai that" if render_index == 0 else "Phoi canh khong gian chinh"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
<rect width="1280" height="720" fill="#f7f1e7"/>
<rect x="72" y="72" width="1136" height="576" rx="32" fill="#fffaf2" stroke="{accent}" stroke-width="6"/>
<rect x="160" y="180" width="960" height="320" rx="28" fill="#efe4d3" stroke="#1c160f" stroke-width="4"/>
<rect x="220" y="250" width="220" height="180" rx="16" fill="#fffaf2" stroke="#1c160f" stroke-width="4"/>
<rect x="500" y="220" width="260" height="210" rx="16" fill="#fffaf2" stroke="#1c160f" stroke-width="4"/>
<rect x="820" y="250" width="220" height="180" rx="16" fill="#fffaf2" stroke="#1c160f" stroke-width="4"/>
<text x="160" y="120" fill="#1c160f" font-size="34" font-family="Arial">{title}</text>
<text x="160" y="155" fill="#5f5446" font-size="20" font-family="Arial">{project_type} | {style} | KTC KTS preview</text>
<text x="260" y="345" fill="#1c160f" font-size="26" font-family="Arial">Khoi chinh</text>
<text x="560" y="335" fill="#1c160f" font-size="26" font-family="Arial">Khong gian trung tam</text>
<text x="860" y="345" fill="#1c160f" font-size="26" font-family="Arial">Khoi phu tro</text>
</svg>"""


def generate_floorplans(project_id: str, brief_json: dict, num_options: int) -> list[dict]:
    payload = {
        "project_id": project_id,
        "prompt": brief_json.get("style", "modern"),
        "brief_json": brief_json,
        "num_options": num_options,
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(f"{settings.gpu_service_url}/generate/floor-plan", json=payload)
            response.raise_for_status()
            data = response.json()
            options = data.get("options")
            if options:
                return options
    except Exception:  # noqa: BLE001
        pass

    return [_fallback_option(project_id, index, brief_json) for index in range(num_options)]


def derive_3d_assets(version_id: str, brief_json: dict, floor_plan_url: str | None) -> dict:
    payload = {
        "version_id": version_id,
        "brief_json": brief_json,
        "floor_plan_url": floor_plan_url,
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(f"{settings.gpu_service_url}/derive/model", json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("model_gltf"):
                if not data.get("renders"):
                    data["renders"] = [_fallback_render(brief_json, 0), _fallback_render(brief_json, 1)]
                return data
    except Exception:  # noqa: BLE001
        pass

    return {
        "model_gltf": {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {}, "mode": 4}]}],
        },
        "renders": [_fallback_render(brief_json, 0), _fallback_render(brief_json, 1)],
    }


def render_presentation_bundle(*, bundle_id: str, scene_spec: dict, render_preset: str) -> dict:
    payload = {
        "bundle_id": bundle_id,
        "scene_spec": scene_spec,
        "render_preset": render_preset,
        "requested_outputs": {"scene_glb": True, "stills": True, "video": True},
    }
    with httpx.Client(timeout=120.0) as client:
        response = client.post(f"{settings.gpu_service_url}/presentation/render", json=payload)
        response.raise_for_status()
        return response.json()
