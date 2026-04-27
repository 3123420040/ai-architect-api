from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector


def _look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _configure_scene() -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 3840
    scene.render.resolution_y = 2160
    scene.render.fps = 30
    scene.frame_start = 1
    scene.frame_end = 1800
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    if hasattr(scene.display, "render_aa"):
        scene.display.render_aa = "OFF"
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.color = (0.78, 0.84, 0.9)


def _assign_fallback_colors() -> None:
    palette = {
        "wall": (0.82, 0.83, 0.78, 1.0),
        "floor": (0.58, 0.56, 0.50, 1.0),
        "roof": (0.58, 0.20, 0.14, 1.0),
        "glass": (0.34, 0.58, 0.68, 0.75),
        "door": (0.48, 0.26, 0.12, 1.0),
        "site": (0.25, 0.44, 0.28, 1.0),
        "furniture": (0.22, 0.42, 0.36, 1.0),
    }
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        key = next((name for name in palette if name in obj.name.lower()), "wall")
        material = bpy.data.materials.new(f"{obj.name}_ci_material")
        material.diffuse_color = palette[key]
        obj.data.materials.clear()
        obj.data.materials.append(material)


def _safe_import_glb(glb_path: str) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.import_scene.gltf(filepath=glb_path)
    if not any(obj.type == "MESH" for obj in bpy.context.scene.objects):
        raise SystemExit("GLB import produced no mesh objects")
    _assign_fallback_colors()


def _create_camera() -> bpy.types.Object:
    camera_data = bpy.data.cameras.new("Sprint3Camera")
    camera = bpy.data.objects.new("Sprint3Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    return camera


def _create_light() -> None:
    sun_data = bpy.data.lights.new("TropicalDaylight", "SUN")
    sun = bpy.data.objects.new("TropicalDaylight", sun_data)
    sun.rotation_euler = (math.radians(45), 0, math.radians(135))
    sun_data.energy = 2.0
    bpy.context.collection.objects.link(sun)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", required=True)
    parser.add_argument("--camera-path-json", required=True)
    parser.add_argument("--stills-dir", required=True)
    parser.add_argument("--report-json", required=True)
    args = parser.parse_args()

    _configure_scene()
    _safe_import_glb(args.glb)
    _create_light()
    camera = _create_camera()

    camera_path = json.loads(Path(args.camera_path_json).read_text(encoding="utf-8"))
    keyframes = camera_path["keyframes"]
    stills_dir = Path(args.stills_dir)
    stills_dir.mkdir(parents=True, exist_ok=True)
    stills: list[dict] = []
    for index, keyframe in enumerate(keyframes[:-1]):
        camera.location = keyframe["position_m"]
        camera.data.lens = keyframe.get("focal_length_mm", 24.0)
        _look_at(camera, tuple(keyframe["target_m"]))
        bpy.context.scene.frame_set(max(1, int(keyframe["time_s"] * 30) + 1))
        bpy.context.scene.render.filepath = str(stills_dir / f"still_{index:02d}.png")
        bpy.ops.render.render(write_still=True)
        duration = keyframes[index + 1]["time_s"] - keyframe["time_s"]
        stills.append(
            {
                "path": bpy.context.scene.render.filepath,
                "duration_s": duration,
                "label": keyframe["label"],
            }
        )

    Path(args.report_json).write_text(
        json.dumps(
            {
                "renderer": "BLENDER_WORKBENCH",
                "determinism": "Workbench render anti-aliasing disabled where supported; ffmpeg uses threads=1.",
                "stills": stills,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
