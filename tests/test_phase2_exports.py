from __future__ import annotations

import json

from app.services.exporter import (
    build_dxf_bytes,
    build_ifc_bytes,
    build_schedule_csvs,
    build_schedule_rows,
    build_sheet_bundle,
    export_phase2_package,
    validate_package_bundle,
)
from app.services.geometry import build_geometry_v2
from app.services.storage import absolute_path


def test_geometry_v2_sheet_bundle_contains_phase2_outputs():
    geometry = build_geometry_v2(
        {
            "project_name": "Phase 2 Demo",
            "lot": {"width_m": 5, "depth_m": 20, "orientation": "south"},
            "floors": 4,
            "style": "modern_minimalist",
        },
        option_index=1,
    )
    bundle = build_sheet_bundle("Phase 2 Demo", 2, geometry)
    quality = validate_package_bundle(bundle)

    assert geometry["$schema"] == "ai-architect-geometry-v2"
    assert len(bundle["sheets"]) >= 12
    sheet_types = {sheet["type"] for sheet in bundle["sheets"]}
    assert {"elevation_south", "elevation_north", "elevation_east", "elevation_west"} <= sheet_types
    assert {"section_s1", "section_s2"} <= sheet_types
    assert {"schedule_openings", "schedule_rooms"} <= sheet_types
    assert {"key_detail_wall_roof", "key_detail_stair_threshold"} <= sheet_types
    assert set(bundle["top_level_exports"]) == {
        "pdf",
        "svg",
        "dxf",
        "ifc",
        "manifest",
        "door_csv",
        "window_csv",
        "room_csv",
    }
    assert quality["status"] == "pass"


def test_phase2_export_package_persists_all_assets():
    geometry = build_geometry_v2(
        {
            "project_name": "Phase 2 Demo",
            "lot": {"width_m": 5, "depth_m": 20, "orientation": "south"},
            "floors": 4,
            "style": "modern_minimalist",
        },
        option_index=0,
    )

    package = export_phase2_package(
        project_id="project-phase2",
        project_name="Phase 2 Demo",
        version_id="version-phase2",
        version_number=2,
        brief_json={"lot": {"width_m": 5, "depth_m": 20}, "floors": 4, "style": "modern_minimalist"},
        geometry_json=geometry,
    )

    export_urls = package["export_urls"]
    assert set(export_urls) == {
        "pdf",
        "svg",
        "dxf",
        "ifc",
        "manifest",
        "door_csv",
        "window_csv",
        "room_csv",
    }
    assert absolute_path(export_urls["pdf"]).read_bytes().startswith(b"%PDF")
    assert absolute_path(export_urls["dxf"]).read_bytes()
    assert absolute_path(export_urls["ifc"]).read_bytes().startswith(b"ISO-10303-21;")

    manifest = json.loads(absolute_path(export_urls["manifest"]).read_text(encoding="utf-8"))
    assert manifest["exports"]["combined_pdf"] == export_urls["pdf"]
    assert manifest["exports"]["dxf"] == export_urls["dxf"]
    assert manifest["exports"]["ifc"] == export_urls["ifc"]
    assert manifest["status"] == "review"
    assert manifest["deliverable_preset"] == "technical_neutral"
    assert len(manifest["sheets"]) >= 12
    assert any(sheet["type"].startswith("key_detail") for sheet in manifest["sheets"])

    files_manifest = package["files_manifest"]
    assert any(item["type"] == "pdf" for item in files_manifest)
    assert any(item["type"] == "dxf" for item in files_manifest)
    assert any(item["type"] == "ifc" for item in files_manifest)
    assert any(item["type"] == "csv" for item in files_manifest)
    assert any(item["name"].endswith(".svg") for item in files_manifest)


def test_schedule_and_interop_builders_return_content():
    geometry = build_geometry_v2(
        {"lot": {"width_m": 5, "depth_m": 20}, "floors": 4, "style": "tropical_modern"},
        option_index=2,
    )
    rows = build_schedule_rows(geometry)
    csvs = build_schedule_csvs(geometry)

    assert rows["door"]
    assert rows["window"]
    assert any(item.get("row_type") == "level_total" for item in rows["room"])
    assert any(item.get("row_type") == "building_total" for item in rows["room"])

    assert csvs["door"].startswith("mark,room,type")
    assert csvs["window"].startswith("mark,room,type")
    assert csvs["room"].startswith("row_type,id,room_name")

    assert build_dxf_bytes("Demo", 1, geometry)
    assert build_ifc_bytes("Demo", 1, geometry).startswith(b"ISO-10303-21;")
