from __future__ import annotations

from dataclasses import dataclass

from app.services.professional_deliverables.scene_contract import BoxMeshElement, SceneContract


@dataclass(frozen=True)
class CameraKeyframe:
    time_s: float
    label: str
    position_m: tuple[float, float, float]
    target_m: tuple[float, float, float]
    focal_length_mm: float = 24.0

    def as_dict(self) -> dict:
        return {
            "time_s": self.time_s,
            "label": self.label,
            "position_m": list(self.position_m),
            "target_m": list(self.target_m),
            "focal_length_mm": self.focal_length_mm,
        }


@dataclass(frozen=True)
class CameraPath:
    duration_s: float
    fps: int
    keyframes: tuple[CameraKeyframe, ...]
    collision_warnings: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "duration_s": self.duration_s,
            "fps": self.fps,
            "keyframes": [keyframe.as_dict() for keyframe in self.keyframes],
            "collision_warnings": list(self.collision_warnings),
        }


def _scene_bounds(scene: SceneContract) -> tuple[float, float, float, float, float, float]:
    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    for element in scene.elements:
        for axis in range(3):
            center = element.center_m[axis]
            half = element.size_m[axis] / 2.0
            mins[axis] = min(mins[axis], center - half)
            maxs[axis] = max(maxs[axis], center + half)
    return (mins[0], mins[1], mins[2], maxs[0], maxs[1], maxs[2])


def _inside_axis_aligned_box(point: tuple[float, float, float], element: BoxMeshElement, *, margin_m: float = 0.0) -> bool:
    return all(
        element.center_m[axis] - element.size_m[axis] / 2.0 - margin_m
        <= point[axis]
        <= element.center_m[axis] + element.size_m[axis] / 2.0 + margin_m
        for axis in range(3)
    )


def camera_collision_warnings(scene: SceneContract, keyframes: tuple[CameraKeyframe, ...]) -> tuple[str, ...]:
    warnings: list[str] = []
    wall_elements = tuple(element for element in scene.elements if element.category == "wall")
    for keyframe in keyframes:
        for wall in wall_elements:
            if _inside_axis_aligned_box(keyframe.position_m, wall):
                warnings.append(f"{keyframe.label} at {keyframe.time_s:.1f}s intersects {wall.id}")
    return tuple(warnings)


def build_camera_path(scene: SceneContract, *, fps: int = 30) -> CameraPath:
    min_x, min_y, _min_z, max_x, max_y, max_z = _scene_bounds(scene)
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    width = max_x - min_x
    depth = max_y - min_y
    eye = 1.55
    f2_z = 3.2 + eye

    keyframes = (
        CameraKeyframe(
            time_s=0.0,
            label="Exterior approach",
            position_m=(center_x, min_y - max(4.5, width), 3.8),
            target_m=(center_x, center_y, min(max_z, 4.2)),
            focal_length_mm=28.0,
        ),
        CameraKeyframe(
            time_s=15.0,
            label="Phòng khách",
            position_m=(center_x, min_y + depth * 0.18, eye),
            target_m=(center_x, min_y + depth * 0.28, eye),
            focal_length_mm=22.0,
        ),
        CameraKeyframe(
            time_s=28.0,
            label="Bếp và ăn",
            position_m=(center_x, min_y + depth * 0.42, eye),
            target_m=(center_x, min_y + depth * 0.52, eye),
            focal_length_mm=22.0,
        ),
        CameraKeyframe(
            time_s=42.0,
            label="Phòng ngủ chính",
            position_m=(center_x, min_y + depth * 0.18, f2_z),
            target_m=(center_x, min_y + depth * 0.30, f2_z),
            focal_length_mm=24.0,
        ),
        CameraKeyframe(
            time_s=50.0,
            label="Exterior closing",
            position_m=(max_x + max(5.0, width), min_y - max(3.5, width * 0.7), max_z * 0.62),
            target_m=(center_x, center_y, max_z * 0.48),
            focal_length_mm=35.0,
        ),
        CameraKeyframe(
            time_s=60.0,
            label="Exterior closing hold",
            position_m=(max_x + max(5.2, width), min_y - max(4.0, width * 0.8), max_z * 0.7),
            target_m=(center_x, center_y, max_z * 0.5),
            focal_length_mm=35.0,
        ),
    )
    return CameraPath(
        duration_s=60.0,
        fps=fps,
        keyframes=keyframes,
        collision_warnings=camera_collision_warnings(scene, keyframes),
    )
