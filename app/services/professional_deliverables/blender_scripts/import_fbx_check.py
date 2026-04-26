from __future__ import annotations

import argparse
import json
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fbx", type=Path, required=True)
    parser.add_argument("--metadata-json", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    argv = []
    if "--" in __import__("sys").argv:
        argv = __import__("sys").argv[__import__("sys").argv.index("--") + 1 :]
    return parser.parse_args(argv)


def fail(report_path: Path, issues: list[str]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"status": "fail", "issues": issues}, indent=2), encoding="utf-8")
    raise SystemExit(1)


def material_has_texture(material: bpy.types.Material) -> bool:
    if not material.use_nodes:
        return False
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None):
            return True
    return False


def main() -> None:
    args = parse_args()
    metadata = json.loads(args.metadata_json.read_text(encoding="utf-8"))
    expected_meshes = len(metadata["scene_elements"])
    expected_materials = {material["name"] for material in metadata["material_list"]}
    issues: list[str] = []

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.import_scene.fbx(filepath=str(args.fbx))

    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(mesh_objects) != expected_meshes:
        issues.append(f"mesh count {len(mesh_objects)} != expected {expected_meshes}")

    imported_materials = {material.name.split(".")[0]: material for material in bpy.data.materials}
    missing_materials = sorted(expected_materials - set(imported_materials))
    if missing_materials:
        issues.append(f"missing materials: {missing_materials}")
    untextured = sorted(name for name, material in imported_materials.items() if name in expected_materials and not material_has_texture(material))
    if untextured:
        issues.append(f"materials without resolved image textures: {untextured}")

    min_x = min((obj.bound_box[i][0] + obj.location.x) for obj in mesh_objects for i in range(8)) if mesh_objects else 0.0
    max_x = max((obj.bound_box[i][0] + obj.location.x) for obj in mesh_objects for i in range(8)) if mesh_objects else 0.0
    min_y = min((obj.bound_box[i][1] + obj.location.y) for obj in mesh_objects for i in range(8)) if mesh_objects else 0.0
    max_y = max((obj.bound_box[i][1] + obj.location.y) for obj in mesh_objects for i in range(8)) if mesh_objects else 0.0
    min_z = min((obj.bound_box[i][2] + obj.location.z) for obj in mesh_objects for i in range(8)) if mesh_objects else 0.0
    max_z = max((obj.bound_box[i][2] + obj.location.z) for obj in mesh_objects for i in range(8)) if mesh_objects else 0.0
    extents = (max_x - min_x, max_y - min_y, max_z - min_z)
    if not (580 <= extents[0] <= 650 and 1580 <= extents[1] <= 1660 and 630 <= extents[2] <= 710):
        issues.append(f"units/up-axis check failed, extents={tuple(round(value, 2) for value in extents)} expected centimeters")

    uv_issues: list[str] = []
    for obj in mesh_objects:
        mesh = obj.data
        if not mesh.uv_layers:
            uv_issues.append(f"{obj.name}: missing UV0")
            continue
        uv_layer = mesh.uv_layers[0]
        for uv in uv_layer.data:
            if uv.uv.x < -1e-5 or uv.uv.x > 1.00001 or uv.uv.y < -1e-5 or uv.uv.y > 1.00001:
                uv_issues.append(f"{obj.name}: UV0 outside 0-1 ({uv.uv.x:.4f}, {uv.uv.y:.4f})")
                break
    if uv_issues:
        issues.extend(uv_issues[:20])

    if issues:
        fail(args.report_json, issues)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(
        json.dumps(
            {
                "status": "pass",
                "mesh_count": len(mesh_objects),
                "material_count": len(expected_materials),
                "extents_cm": [round(value, 3) for value in extents],
                "uv0_range": "0..1",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
