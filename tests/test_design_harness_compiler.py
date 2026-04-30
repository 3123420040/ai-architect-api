from __future__ import annotations

from app.services.design_harness.compiler import compile_concept_design_input, validate_concept_design_input
from app.services.design_harness.readiness import compute_design_harness_readiness
from app.services.design_harness.tools import DesignHarnessStyleTools


def _compile(brief: dict, *, latest_message: str = ""):
    readiness, assumptions = compute_design_harness_readiness(brief=brief, latest_message=latest_message)
    style_tools = DesignHarnessStyleTools().run(latest_message or "minimal warm home", brief_json=brief).as_dict()
    return compile_concept_design_input(
        project_id="project-1",
        project_name="Test project",
        brief=brief,
        readiness=readiness,
        assumptions=assumptions,
        style_tools=style_tools,
    )


def test_valid_low_communication_townhouse_emits_with_style_assumption():
    brief = {
        "project_type": "townhouse",
        "project_mode": "new_build",
        "lot": {"width_m": 5, "depth_m": 20, "access": "street_front"},
        "floors": 3,
        "rooms": {"bedrooms": 3, "bathrooms": 3},
        "design_goals": ["ấm, sáng, dễ ở"],
    }

    result = _compile(brief, latest_message="Nhà phố 5x20m, 3 tầng, 3 phòng ngủ, 3 WC, muốn ấm sáng")

    assert result.validation["status"] == "valid"
    assert result.concept_design_input is not None
    payload = result.concept_design_input
    assert payload["schema_version"] == "concept_design_input_v1"
    assert payload["project"]["concept_only"] is True
    assert payload["project"]["construction_ready"] is False
    assert payload["site"]["width_m"] == 5
    assert payload["program"]["floors"] == 3
    assert payload["style"]["style_id"]
    assert "style" in result.validation["assumptions_requiring_confirmation"]
    provenance_paths = {item["field_path"] for item in payload["provenance"]}
    assert {"site.width_m", "site.depth_m", "program.floors", "style.style_id"} <= provenance_paths


def test_missing_site_dimensions_blocks_landed_input():
    brief = {
        "project_type": "townhouse",
        "project_mode": "new_build",
        "floors": 3,
        "rooms": {"bedrooms": 3, "bathrooms": 2},
        "style": "modern_minimalist",
    }

    result = _compile(brief, latest_message="Nhà phố 3 tầng 3 phòng ngủ 2 WC")

    assert result.concept_design_input is None
    assert result.validation["status"] == "blocked"
    reason_codes = {item["code"] for item in result.validation["reasons"]}
    assert "critical_missing" in reason_codes
    assert "site.width_m" in result.validation["critical_missing"]


def test_valid_apartment_renovation_input():
    brief = {
        "project_type": "apartment_reno",
        "project_mode": "renovation",
        "lot": {"area_m2": 82},
        "rooms": {"bedrooms": 2, "bathrooms": 2},
        "renovation_scope": "full",
        "style": "indochine_soft",
        "must_not_haves": ["quá nhiều chi tiết tối"],
    }

    result = _compile(brief, latest_message="Cải tạo căn hộ 82m2, 2 phòng ngủ, 2 WC, indochine nhẹ")

    assert result.validation["status"] == "valid"
    payload = result.concept_design_input
    assert payload is not None
    assert payload["site"]["kind"] == "apartment_unit"
    assert payload["site"]["area_m2"] == 82
    assert payload["program"]["renovation_scope"] == "full"
    assert payload["project"]["construction_ready"] is False


def test_unsafe_claims_are_removed_or_blocked():
    payload = {
        "schema_version": "concept_design_input_v1",
        "project": {
            "project_id": "project-1",
            "project_name": "Unsafe",
            "project_type": "townhouse",
            "project_mode": "new_build",
            "concept_only": True,
            "construction_ready": True,
        },
        "site": {"kind": "land_lot", "width_m": 5, "depth_m": 20, "area_m2": 100},
        "program": {"floors": 3, "bedrooms": 3, "bathrooms": 3},
        "household": {"occupant_count": None, "profile": None, "priorities": []},
        "style": {"style_id": "minimal_warm", "confidence": 0.8, "evidence": ["permit ready"]},
        "layout_intent": {},
        "assumptions": [],
        "provenance": [
            {"field_path": "project.project_id", "source": "user", "confidence": 1.0, "evidence": []},
            {"field_path": "project.project_type", "source": "user", "confidence": 1.0, "evidence": []},
            {"field_path": "project.project_mode", "source": "user", "confidence": 1.0, "evidence": []},
            {"field_path": "project.concept_only", "source": "deterministic", "confidence": 1.0, "evidence": []},
            {"field_path": "project.construction_ready", "source": "deterministic", "confidence": 1.0, "evidence": []},
            {"field_path": "site.width_m", "source": "user", "confidence": 1.0, "evidence": []},
            {"field_path": "site.depth_m", "source": "user", "confidence": 1.0, "evidence": []},
            {"field_path": "program.floors", "source": "user", "confidence": 1.0, "evidence": []},
            {"field_path": "program.bedrooms", "source": "user", "confidence": 1.0, "evidence": []},
            {"field_path": "program.bathrooms", "source": "user", "confidence": 1.0, "evidence": []},
            {"field_path": "style.style_id", "source": "user", "confidence": 1.0, "evidence": []},
        ],
    }

    validation = validate_concept_design_input(payload, readiness={"status": "ready_for_concept_input"})

    assert validation["status"] == "blocked"
    reason_codes = {item["code"] for item in validation["reasons"]}
    assert "construction_ready_forbidden" in reason_codes
    assert "unsafe_scope_claim" in reason_codes
