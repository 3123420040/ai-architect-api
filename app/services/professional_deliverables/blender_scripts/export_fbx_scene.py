from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-json", type=Path, required=True)
    parser.add_argument("--output-fbx", type=Path, required=True)
    argv = []
    if "--" in __import__("sys").argv:
        argv = __import__("sys").argv[__import__("sys").argv.index("--") + 1 :]
    return parser.parse_args(argv)


def rotate_xy(x: float, y: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    c = math.cos(angle)
    s = math.sin(angle)
    return (x * c - y * s, x * s + y * c)


def make_material(payload: dict) -> bpy.types.Material:
    material = bpy.data.materials.new(payload["name"])
    material.use_nodes = True
    nodes = material.node_tree.nodes
    principled = nodes.get("Principled BSDF")
    if principled is None:
        return material

    color = payload["base_color_rgba"]
    if "Base Color" in principled.inputs:
        principled.inputs["Base Color"].default_value = (
            color[0] / 255.0,
            color[1] / 255.0,
            color[2] / 255.0,
            color[3] / 255.0,
        )
    if "Roughness" in principled.inputs:
        principled.inputs["Roughness"].default_value = payload["roughness"] / 255.0
    if "Metallic" in principled.inputs:
        principled.inputs["Metallic"].default_value = payload["metallic"] / 255.0

    base_path = payload["texture_paths"].get("baseColor")
    if base_path:
        image = bpy.data.images.load(base_path)
        image.pack()
        tex = nodes.new(type="ShaderNodeTexImage")
        tex.name = f"{payload['name']}_baseColor"
        tex.image = image
        material.node_tree.links.new(tex.outputs["Color"], principled.inputs["Base Color"])
    return material


def box_mesh(element: dict) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int, int]], list[tuple[float, float]]]:
    sx, sy, sz = [value * 100.0 for value in element["size_m"]]
    cx, cy, cz = [value * 100.0 for value in element["center_m"]]
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    faces = [
        ((hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz), (hx, -hy, hz)),
        ((-hx, hy, -hz), (-hx, -hy, -hz), (-hx, -hy, hz), (-hx, hy, hz)),
        ((-hx, hy, -hz), (hx, hy, -hz), (hx, hy, hz), (-hx, hy, hz)),
        ((hx, -hy, -hz), (-hx, -hy, -hz), (-hx, -hy, hz), (hx, -hy, hz)),
        ((-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)),
        ((-hx, hy, -hz), (hx, hy, -hz), (hx, -hy, -hz), (-hx, -hy, -hz)),
    ]
    vertices: list[tuple[float, float, float]] = []
    face_indices: list[tuple[int, int, int, int]] = []
    uv_values: list[tuple[float, float]] = []
    uv_face = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for face in faces:
        base = len(vertices)
        for corner, uv in zip(face, uv_face):
            rx, ry = rotate_xy(corner[0], corner[1], element.get("rotation_z_degrees", 0.0))
            vertices.append((cx + rx, cy + ry, cz + corner[2]))
            uv_values.append(uv)
        face_indices.append((base, base + 1, base + 2, base + 3))
    return vertices, face_indices, uv_values


def build_scene(payload: dict) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.01
    scene.unit_settings.length_unit = "CENTIMETERS"

    materials = {material["name"]: make_material(material) for material in payload["materials"]}
    for element in payload["elements"]:
        vertices, faces, uv_values = box_mesh(element)
        mesh = bpy.data.meshes.new(element["name"])
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        uv_layer = mesh.uv_layers.new(name="UV0")
        for polygon in mesh.polygons:
            for loop_index in polygon.loop_indices:
                uv_layer.data[loop_index].uv = uv_values[mesh.loops[loop_index].vertex_index]
            polygon.use_smooth = False
        mesh.materials.append(materials[element["material_name"]])
        obj = bpy.data.objects.new(element["name"], mesh)
        obj["lod"] = element["lod"]
        obj["category"] = element["category"]
        obj["source_id"] = element["id"]
        bpy.context.collection.objects.link(obj)


def main() -> None:
    args = parse_args()
    payload = json.loads(args.scene_json.read_text(encoding="utf-8"))
    build_scene(payload)
    args.output_fbx.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=str(args.output_fbx),
        use_selection=False,
        object_types={"MESH"},
        axis_forward="-Y",
        axis_up="Z",
        global_scale=1.0,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        bake_space_transform=False,
        use_mesh_modifiers=True,
        mesh_smooth_type="FACE",
        use_tspace=True,
        path_mode="COPY",
        embed_textures=True,
        add_leaf_bones=False,
        use_custom_props=True,
    )


if __name__ == "__main__":
    main()
