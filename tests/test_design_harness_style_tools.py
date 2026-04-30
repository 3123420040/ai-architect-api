from __future__ import annotations

import pytest

from app.services.design_harness import DesignHarnessStyleTools, DesignIntakeHarnessLoop
from app.services.professional_deliverables.style_knowledge import StyleKnowledgeError, StyleProfile


def test_minimal_warm_from_low_communication_language():
    output = DesignHarnessStyleTools().run(
        "Nha pho 5x20m, gia dinh tre, muon nha gon am, de don, it bao tri."
    ).as_dict()

    assert output["selected_style_id"] == "minimal_warm"
    assert output["confidence"] >= 0.55
    assert "customer_language" in output["source_tags"]
    assert output["style_profile"]["source_tag"] == "style_profile"
    assert output["candidates"][0]["style_id"] == "minimal_warm"


def test_modern_tropical_from_greenery_and_daylight_language():
    output = DesignHarnessStyleTools().run(
        "Nha 7x25m, 3 tang, 4 phong ngu, muon hien dai thoang, nhieu anh sang, gio tu nhien va nhieu cay."
    ).as_dict()

    assert output["selected_style_id"] == "modern_tropical"
    assert "customer_language" in output["source_tags"]
    assert any(pattern["pattern_id"] == "townhouse_villa_7x25_green_core" for pattern in output["pattern_memory"])
    assert any(item["source_tag"] == "pattern_memory" for item in output["evidence"])


def test_indochine_from_reference_descriptor_only():
    output = DesignHarnessStyleTools().run(
        "Can ho 95m2 cho gia dinh nho, muon nha am va co chut chat rieng.",
        reference_images=[
            {
                "style_hint": "soft indochine",
                "visual_tags": ["arched opening", "rattan", "pattern tile"],
                "materials": ["dark wood accent", "cream wall"],
            }
        ],
    ).as_dict()

    assert output["selected_style_id"] == "indochine_soft"
    assert "reference_image_descriptor" in output["source_tags"]
    assert output["reference_descriptor_matches"]
    assert not any("image analysis" in item["signal"].lower() for item in output["evidence"])


def test_explicit_dislike_suppresses_style_and_features():
    output = DesignHarnessStyleTools().run(
        "Can ho 95m2, thich gon am, khong thich dong duong, khong thich qua nhieu kinh, "
        "cold/dark palette, overly decorative Indochine va ngai cham cay.",
        reference_images=[
            {
                "style_hint": "indochine soft",
                "visual_tags": ["arches", "rattan", "pattern tile"],
            }
        ],
    ).as_dict()

    assert output["selected_style_id"] != "indochine_soft"
    indochine = next(candidate for candidate in output["candidates"] if candidate["style_id"] == "indochine_soft")
    assert indochine["confidence"] == 0
    assert any(item["source_tag"] == "explicit_dislike" for item in indochine["evidence"])
    suppressed_features = {item["feature"] for item in output["dislike_suppression"]}
    assert {"large_glass", "cold_dark_palette", "high_maintenance_greenery"} <= suppressed_features


def test_ambiguous_style_asks_confirmation():
    output = DesignHarnessStyleTools().run("Nha cho gia dinh tre, muon dep va de o.").as_dict()

    assert output["selected_style_id"] is None
    assert output["needs_confirmation"] is True
    assert output["confirmation_question"]
    assert output["candidates"]


def test_harness_loop_exposes_style_tools_without_live_llm(monkeypatch):
    from app.services import llm

    monkeypatch.setattr(llm.settings, "openai_compat_base_url", "")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "kts")

    result = DesignIntakeHarnessLoop().run(
        "Nha pho 5x20m, gia dinh tre, muon nha gon am, de don, it bao tri.",
        {},
        [],
    )
    style_tools = result.as_legacy_turn()["harness_machine_output"]["style_tools"]

    assert style_tools["schema_version"] == "design_harness_style_tools_v1"
    assert style_tools["selected_style_id"] == "minimal_warm"
    assert any(gate["name"] == "style_pattern_tools" for gate in result.harness_trace["validation_gates"])


def test_unsafe_profile_content_stays_blocked():
    payload = {
        "style_id": "unsafe",
        "display_name": "Unsafe",
        "version": "test",
        "aliases": ["unsafe"],
        "customer_language_signals": ["unsafe"],
        "visual_signals": ["unsafe"],
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
        "explanation_templates": {"style_summary": "This is code compliant and construction ready."},
    }

    with pytest.raises(StyleKnowledgeError):
        StyleProfile.from_dict(payload)
