from __future__ import annotations

from app.services import llm
from app.services.design_harness import DesignIntakeHarnessLoop
from app.services.design_harness.readiness import compute_design_harness_readiness


def _disable_llm(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "openai_compat_base_url", "")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "kts")


def _run(message: str, monkeypatch, brief: dict | None = None):
    _disable_llm(monkeypatch)
    return DesignIntakeHarnessLoop().run(message, brief or {}, [])


def _assumption_map(result) -> dict[str, dict]:
    return {item["field_path"]: item for item in result.machine.assumptions}


def test_low_communication_5x20_townhouse_proposes_assumptions(monkeypatch):
    result = _run("Nhà phố 5x20m", monkeypatch)
    readiness = result.machine.readiness
    assumptions = _assumption_map(result)

    assert readiness["schema_version"] == "design_harness_readiness_v1"
    assert readiness["status"] == "missing_critical"
    assert readiness["field_statuses"]["project_type"]["status"] == "confirmed"
    assert readiness["field_statuses"]["site.width_m"]["status"] == "confirmed"
    assert readiness["field_statuses"]["site.depth_m"]["status"] == "confirmed"
    assert "floors" in readiness["critical_missing"]
    assert "program.bedrooms" in readiness["critical_missing"]
    assert "floors" in assumptions
    assert assumptions["floors"]["source"] == "pattern_memory"
    assert assumptions["style"]["source"] == "default"
    assert all(item["needs_confirmation"] for item in result.machine.assumptions)
    assert result.brief_json["lot"]["width_m"] == 5
    assert "floors" not in result.brief_json


def test_apartment_area_only_brief_keeps_program_blockers(monkeypatch):
    result = _run("Cải tạo căn hộ 82m2", monkeypatch)
    readiness = result.machine.readiness
    assumptions = _assumption_map(result)

    assert result.brief_json["project_type"] == "apartment_reno"
    assert readiness["field_statuses"]["site.area_m2"]["status"] == "confirmed"
    assert readiness["field_statuses"]["renovation_scope"]["status"] == "missing_critical"
    assert "renovation_scope" in readiness["critical_missing"]
    assert "program.bedrooms" in readiness["critical_missing"]
    assert assumptions["renovation_scope"]["source"] == "default"
    assert assumptions["program.bedrooms"]["source"] == "pattern_memory"
    assert readiness["safe_to_emit_concept_input"] is False


def test_missing_site_geometry_blocks_landed_concept_input(monkeypatch):
    result = _run("Nhà phố 3 tầng, 3 phòng ngủ, 2 WC, phong cach modern", monkeypatch)
    readiness = result.machine.readiness

    assert readiness["status"] == "missing_critical"
    assert readiness["field_statuses"]["site.width_m"]["status"] == "missing_critical"
    assert readiness["field_statuses"]["site.depth_m"]["status"] == "missing_critical"
    assert "site.width_m" in readiness["critical_missing"]
    assert "site.depth_m" in readiness["critical_missing"]
    assert readiness["field_statuses"]["style"]["status"] == "confirmed"


def test_inferred_style_needs_confirmation(monkeypatch):
    result = _run("Cải tạo căn hộ 90m2, muốn xanh tự nhiên, nhiều ánh sáng và thông gió", monkeypatch)
    readiness = result.machine.readiness
    assumptions = _assumption_map(result)

    assert readiness["field_statuses"]["style"]["status"] == "inferred"
    assert readiness["field_statuses"]["style"]["source"] == "style_profile"
    assert assumptions["style"]["value"] == "tropical_modern"
    assert assumptions["style"]["needs_confirmation"] is True
    assert "style" in readiness["assumptions_requiring_confirmation"]


def test_confirmed_facts_are_not_downgraded():
    brief = {
        "project_type": "townhouse",
        "project_mode": "new_build",
        "lot": {"width_m": 5, "depth_m": 20},
        "floors": 3,
        "rooms": {"bedrooms": 4, "bathrooms": 3},
        "style": "modern_minimalist",
    }
    readiness, assumptions = compute_design_harness_readiness(brief=brief, clarification_state={}, conflicts=[])

    assert readiness["field_statuses"]["style"]["status"] == "confirmed"
    assert readiness["field_statuses"]["project_mode"]["status"] == "confirmed"
    assert "style" not in {item["field_path"] for item in assumptions}
    assert "style" in readiness["confirmed_fields"]
    assert "style" not in readiness["inferred_fields"]
    assert "style" not in readiness["defaulted_fields"]


def test_unsafe_scope_remains_blocked(monkeypatch):
    result = _run(
        "Nhà phố 5x20m, 3 tầng, 3 phòng ngủ, 3 WC, phong cách hiện đại. "
        "Hãy xác nhận đủ để xin phép xây dựng, kiểm tra kết cấu và triển khai thi công.",
        monkeypatch,
    )
    readiness = result.machine.readiness

    assert readiness["status"] == "blocked_by_safety_scope"
    assert "safety_scope.unsafe_request" in readiness["conflicting_fields"]
    assert readiness["safe_to_emit_concept_input"] is False
    assert "construction_ready" not in result.brief_json
    assert "permit_ready" not in result.brief_json
