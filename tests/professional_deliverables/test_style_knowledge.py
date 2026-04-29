from __future__ import annotations

import pytest

from app.services.professional_deliverables.pattern_memory import PatternMemory, retrieve_patterns, seed_patterns
from app.services.professional_deliverables.style_knowledge import (
    REQUIRED_PROFILE_FIELDS,
    StyleKnowledgeBase,
    StyleKnowledgeError,
    StyleProfile,
    load_style_profiles,
    profile_dislike_matches,
    profile_reference_descriptor_matches,
)


def test_style_profiles_load_and_validate_required_fields():
    profiles = load_style_profiles()

    assert {"modern_tropical", "minimal_warm", "indochine_soft"} <= set(profiles)
    for profile in profiles.values():
        payload = profile.__dict__
        for field_name in REQUIRED_PROFILE_FIELDS:
            assert payload[field_name]


@pytest.mark.parametrize("style_id", ["modern_tropical", "minimal_warm", "indochine_soft"])
def test_initial_profiles_include_required_rule_groups(style_id: str):
    profile = StyleKnowledgeBase.load_default().get(style_id)

    assert profile.aliases
    assert profile.customer_language_signals
    assert profile.visual_signals
    assert profile.spatial_rules["primary_strategy"]
    assert profile.room_defaults
    assert profile.opening_rules["window_to_wall_ratio"]
    assert profile.default_rules["homeowner_question_policy"]
    assert profile.facade_intent
    assert profile.facade_rules["massing"]
    assert profile.facade_expression["rhythm"]
    assert profile.material_palette["base"]
    assert profile.material_assumptions
    assert profile.drawing_rules["plan_notes"]
    assert profile.drawing_notes
    assert profile.avoid_rules
    assert profile.dislike_suppression
    assert profile.reference_descriptor_mappings
    assert profile.validation_rules
    assert profile.customer_explanation()
    assert "technical dimensions" in profile.default_rules["homeowner_question_policy"]


def test_style_profiles_map_explicit_dislikes_to_suppressed_features():
    profile = StyleKnowledgeBase.load_default().get("modern_tropical")
    matches = profile_dislike_matches(profile, ("khong thich qua nhieu kinh", "mat tien lanh"))

    assert {match["feature"] for match in matches} >= {"large_glass"}
    glass = next(match for match in matches if match["feature"] == "large_glass")
    assert glass["source"] == "explicit_dislike"
    assert glass["assumption"] is True
    assert "shade" in glass["replacement"] or "screen" in glass["replacement"]


def test_style_profiles_map_reference_descriptors_without_image_analysis_claim():
    profile = StyleKnowledgeBase.load_default().get("indochine_soft")
    matches = profile_reference_descriptor_matches(
        profile,
        ("arches", "wood", "rattan", "neutral palette", "textured screens"),
    )

    features = {match["feature"] for match in matches}
    assert {"soft_arch", "rattan_timber_screen"} <= features
    assert all(match["source"] == "reference_image_descriptor" for match in matches)
    assert not any("analysis" in match["drawing_note"].lower() for match in matches)


def test_pattern_memory_retrieves_7x25_modern_tropical_townhouse():
    matches = retrieve_patterns(
        {
            "width_m": 7,
            "depth_m": 25,
            "project_type": "townhouse",
            "floors": 3,
            "bedrooms": 4,
            "garage": True,
            "occupants": 6,
            "signals": ["children_elderly"],
        },
        style_id="modern_tropical",
    )

    assert matches
    assert matches[0].pattern_id == "townhouse_villa_7x25_green_core"
    assert "green core" in matches[0].name.lower()


def test_pattern_memory_contains_required_seed_scenarios():
    pattern_ids = {pattern.pattern_id for pattern in seed_patterns()}

    assert {
        "townhouse_5x20_lightwell",
        "townhouse_villa_7x25_green_core",
        "villa_10x20_courtyard",
        "apartment_reno_warm_storage",
        "corner_lot_breeze_privacy",
    } <= pattern_ids
    assert PatternMemory().retrieve({"width_m": 10, "depth_m": 20, "project_type": "villa"}, style_id="modern_tropical")


def test_style_profile_rejects_unsafe_scope_claims():
    payload = {
        "style_id": "bad",
        "display_name": "Bad",
        "version": "test",
        "aliases": ["bad"],
        "customer_language_signals": ["bad"],
        "visual_signals": ["bad"],
        "spatial_rules": {"primary_strategy": "x"},
        "room_defaults": {"living": {}},
        "opening_rules": {"window_to_wall_ratio": "moderate"},
        "default_rules": {"homeowner_question_policy": "x"},
        "facade_intent": "x",
        "facade_rules": {"massing": "x"},
        "facade_expression": {"rhythm": "x"},
        "material_palette": {"base": ["x"]},
        "material_assumptions": ["x"],
        "drawing_rules": {"plan_notes": ["x"]},
        "drawing_notes": ["x"],
        "avoid_rules": ["x"],
        "dislike_suppression": {"x": {"keywords": ["x"]}},
        "reference_descriptor_mappings": {"x": {"keywords": ["x"]}},
        "validation_rules": ["issued " + "for construction"],
        "explanation_templates": {"style_summary": "x"},
    }

    with pytest.raises(StyleKnowledgeError):
        StyleProfile.from_dict(payload)


def test_style_profile_rejects_professional_scope_claims_in_any_field():
    payload = {
        "style_id": "bad_scope",
        "display_name": "Bad Scope",
        "version": "test",
        "aliases": ["bad"],
        "customer_language_signals": ["bad"],
        "visual_signals": ["bad"],
        "spatial_rules": {"primary_strategy": "x"},
        "room_defaults": {"living": {}},
        "opening_rules": {"window_to_wall_ratio": "moderate"},
        "default_rules": {"homeowner_question_policy": "x"},
        "facade_intent": "x",
        "facade_rules": {"massing": "x"},
        "facade_expression": {"rhythm": "x"},
        "material_palette": {"base": ["x"]},
        "material_assumptions": ["x"],
        "drawing_rules": {"plan_notes": ["x"]},
        "drawing_notes": ["x"],
        "avoid_rules": ["x"],
        "dislike_suppression": {"x": {"keywords": ["x"]}},
        "reference_descriptor_mappings": {"x": {"keywords": ["x"]}},
        "validation_rules": ["x"],
        "explanation_templates": {"style_summary": "This produces permit drawings and code compliance."},
    }

    with pytest.raises(StyleKnowledgeError):
        StyleProfile.from_dict(payload)
