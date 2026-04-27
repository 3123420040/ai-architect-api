from __future__ import annotations

from app.services.professional_deliverables.camera_path import build_camera_path
from app.services.professional_deliverables.golden_fixture import build_golden_townhouse
from app.services.professional_deliverables.scene_builder import build_scene_from_project
from app.services.professional_deliverables.video_renderer import CI_FAST_4K, PRODUCTION_4K_CYCLES_GPU
from app.services.professional_deliverables.video_validators import _fps, _is_all_black


def test_camera_path_has_required_narrative_and_no_wall_collisions() -> None:
    scene = build_scene_from_project(build_golden_townhouse())
    path = build_camera_path(scene)

    assert path.duration_s == 60.0
    assert [keyframe.label for keyframe in path.keyframes[:5]] == [
        "Exterior approach",
        "Phòng khách",
        "Bếp và ăn",
        "Phòng ngủ chính",
        "Exterior closing",
    ]
    assert path.collision_warnings == ()


def test_render_profiles_lock_ci_and_production_settings() -> None:
    assert CI_FAST_4K.width == 3840
    assert CI_FAST_4K.height == 2160
    assert CI_FAST_4K.fps == 30
    assert CI_FAST_4K.duration_s == 60.0
    assert PRODUCTION_4K_CYCLES_GPU["renderer"] == "CYCLES"
    assert PRODUCTION_4K_CYCLES_GPU["samples"] == 96


def test_video_validator_helpers_parse_fps_and_black_frames() -> None:
    assert abs(_fps("30000/1000") - 30.0) < 0.001
    assert _is_all_black(b"\x00" * 256)
    assert not _is_all_black(bytes([30, 40, 50]) * 128)
