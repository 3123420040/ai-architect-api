from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


STRUCTURAL_MARKERS = ("wall", "slab", "roof", "door", "window", "opening", "column")


def _mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def _triangle_count(objects: list[bpy.types.Object]) -> int:
    count = 0
    for obj in objects:
        mesh = obj.data
        for polygon in mesh.polygons:
            count += max(0, len(polygon.vertices) - 2)
    return count


def _bounds_xy(objects: list[bpy.types.Object]) -> tuple[float, float]:
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for obj in objects:
        for corner in obj.bound_box:
            world = obj.matrix_world @ __import__("mathutils").Vector(corner)
            min_x = min(min_x, world.x)
            min_y = min(min_y, world.y)
            max_x = max(max_x, world.x)
            max_y = max(max_y, world.y)
    return ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)


def _apply_lite_decimation(objects: list[bpy.types.Object], target_triangles: int) -> None:
    current = _triangle_count(objects)
    if current <= target_triangles:
        return
    decimatable = [
        obj
        for obj in objects
        if not any(marker in obj.name.lower() for marker in STRUCTURAL_MARKERS)
    ]
    if not decimatable:
        return
    ratio = max(0.1, min(1.0, target_triangles / current))
    for obj in decimatable:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        modifier = obj.modifiers.new("Sprint3LiteDecimate", "DECIMATE")
        modifier.ratio = ratio
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        obj.select_set(False)


def _usd_export_kwargs(filepath: Path) -> dict:
    properties = set(bpy.ops.wm.usd_export.get_rna_type().properties.keys())
    candidates = {
        "filepath": str(filepath),
        "selected_objects_only": False,
        "visible_objects_only": True,
        "export_animation": False,
        "export_uvmaps": True,
        "export_normals": True,
        "export_materials": False,
        "export_textures": False,
        "convert_orientation": True,
        "export_global_forward_selection": "NEGATIVE_Z",
        "export_global_up_selection": "Y",
        "root_prim_path": "/World",
        "convert_scene_units": "METERS",
        "meters_per_unit": 1.0,
        "triangulate_meshes": True,
    }
    return {key: value for key, value in candidates.items() if key == "filepath" or key in properties}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", required=True)
    parser.add_argument("--usd", required=True)
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--target-triangles", type=int, default=200000)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.import_scene.gltf(filepath=args.glb)

    objects = _mesh_objects()
    if not objects:
        raise SystemExit("GLB import produced no mesh objects")

    center_x, center_y = _bounds_xy(objects)
    for obj in objects:
        obj.location.x -= center_x
        obj.location.y -= center_y

    before_triangles = _triangle_count(objects)
    _apply_lite_decimation(objects, args.target_triangles)
    after_triangles = _triangle_count(objects)

    usd_path = Path(args.usd)
    usd_path.parent.mkdir(parents=True, exist_ok=True)
    export_result = bpy.ops.wm.usd_export(**_usd_export_kwargs(usd_path))
    if "FINISHED" not in export_result:
        raise SystemExit(f"USD export did not finish: {sorted(export_result)}")
    if not usd_path.exists() or usd_path.stat().st_size == 0:
        siblings = sorted(path.name for path in usd_path.parent.glob("*"))
        raise SystemExit(f"USD export did not create {usd_path}; package dir contains {siblings}")

    report = {
        "mesh_count": len(objects),
        "triangles_before": before_triangles,
        "triangles_after": after_triangles,
        "pivot_translation_m": [-center_x, -center_y, 0.0],
        "target_triangles": args.target_triangles,
        "usd_path": str(usd_path),
        "usd_size_bytes": usd_path.stat().st_size,
    }
    Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
