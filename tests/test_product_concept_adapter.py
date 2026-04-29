from __future__ import annotations

from copy import deepcopy

from app.services.design_intelligence.product_concept_adapter import adapt_live_design_version_to_concept_source
from app.services.geometry import build_geometry_v2
from app.services.professional_deliverables.concept_pdf_generator import concept_model_to_drawing_project
from tests.test_flows import complete_brief_payload


def _selected_5x20_geometry():
    brief = complete_brief_payload()
    brief["lot"] = {"width_m": 5, "depth_m": 20, "orientation": "south"}
    brief["floors"] = 3
    brief["style"] = "minimal_warm"
    return brief, build_geometry_v2(brief)


def test_adapter_preserves_selected_5x20_geometry_over_brief_values():
    source_brief, geometry = _selected_5x20_geometry()
    conflicting_project_brief = deepcopy(source_brief)
    conflicting_project_brief["lot"] = {"width_m": 7, "depth_m": 25, "orientation": "east"}
    conflicting_project_brief["floors"] = 4

    result = adapt_live_design_version_to_concept_source(
        project_id="project-5x20",
        project_name="Selected Geometry House",
        brief_json=conflicting_project_brief,
        geometry_json=geometry,
        version_id="version-selected",
    )

    assert result.is_ready
    assert result.source is not None
    assert result.source.drawing_project.lot_width_m == 5
    assert result.source.drawing_project.lot_depth_m == 20
    assert result.source.drawing_project.storeys == 3
    assert result.source.concept_model.site.width_m.value == 5
    assert result.source.concept_model.site.depth_m.value == 20
    assert result.source.drawing_package.qa_bounds["lot_width_m"] == 5
    assert result.source.drawing_package.qa_bounds["lot_depth_m"] == 20
    assert result.source.provenance["geometry_authority"] == "DesignVersion.geometry_json"


def test_adapter_room_floor_wall_opening_fixture_counts_match_input_geometry():
    brief, geometry = _selected_5x20_geometry()

    result = adapt_live_design_version_to_concept_source(
        project_id="project-counts",
        project_name="Selected Geometry Counts",
        brief_json=brief,
        geometry_json=geometry,
        version_id="version-counts",
    )

    assert result.is_ready
    concept = result.source.concept_model
    assert len(concept.levels) == len([level for level in geometry["levels"] if level["type"] == "floor"])
    assert len(concept.rooms) == len(geometry["rooms"])
    assert len(concept.walls) == len(geometry["walls"])
    assert len(concept.openings) == len(geometry["openings"])
    assert len(concept.fixtures) == len(geometry["fixtures"])
    assert result.source.drawing_package.qa_bounds["room_count"] == len(geometry["rooms"])
    assert result.source.drawing_package.qa_bounds["opening_count"] == len(geometry["openings"])


def test_adapter_uses_live_style_and_assumptions_without_overriding_geometry():
    brief, geometry = _selected_5x20_geometry()
    brief["lot"] = {"width_m": 9, "depth_m": 30, "orientation": "west"}

    result = adapt_live_design_version_to_concept_source(
        project_id="project-style",
        project_name="Selected Style House",
        brief_json=brief,
        geometry_json=geometry,
        resolved_style_params={
            "style_id": "minimal_warm",
            "style_name": "Live Minimal Warm",
            "facade_intent": "Quiet warm frontage from live metadata.",
            "drawing_notes": ["Live low-maintenance drawing note."],
            "assumptions": ["Live style assumption from resolved metadata."],
            "confidence": 0.91,
        },
        generation_metadata={
            "decision_metadata": {
                "fit_reasons": ["Live strategy fit reason."],
                "caveats": ["Live metadata caveat stays visible."],
            }
        },
        version_id="version-style",
    )

    assert result.is_ready
    concept = result.source.concept_model
    package = result.source.drawing_package
    notes_sheet = package.sheets_by_kind("assumptions_style_notes")[0]
    assert concept.style.value == "minimal_warm"
    assert concept.facade.strategy.value == "Quiet warm frontage from live metadata."
    assert concept.site.width_m.value == 5
    assert concept.site.depth_m.value == 20
    assert "Live low-maintenance drawing note." in notes_sheet.style_notes
    assert "Live strategy fit reason." in notes_sheet.style_notes
    assumption_notes = {assumption.customer_visible_explanation for assumption in concept.assumptions}
    assert "Live style assumption from resolved metadata." in assumption_notes
    assert "Live metadata caveat stays visible." in assumption_notes


def test_adapter_preserves_opening_spans_when_round_tripping_to_drawing_project():
    brief, geometry = _selected_5x20_geometry()

    result = adapt_live_design_version_to_concept_source(
        project_id="project-openings",
        project_name="Opening Span House",
        brief_json=brief,
        geometry_json=geometry,
        version_id="version-openings",
    )

    assert result.is_ready
    source_opening = result.source.drawing_project.openings[0]
    round_trip = concept_model_to_drawing_project(result.source.concept_model, project_name="Opening Span House")
    round_trip_opening = next(opening for opening in round_trip.openings if opening.id == source_opening.id)
    assert round_trip_opening.start == source_opening.start
    assert round_trip_opening.end == source_opening.end


def test_missing_or_unsupported_geometry_marks_fallback_explicitly():
    brief, geometry = _selected_5x20_geometry()
    missing_site = deepcopy(geometry)
    missing_site["site"].pop("boundary")

    blocked = adapt_live_design_version_to_concept_source(
        project_id="project-blocked",
        project_name="Blocked House",
        brief_json=brief,
        geometry_json=missing_site,
    )

    assert blocked.status == "blocked"
    assert blocked.source is None
    assert blocked.fallback_required is True
    assert blocked.fallback_reason
    assert blocked.blocker_reasons[0].code == "geometry_contract_blocked"

    unsupported = adapt_live_design_version_to_concept_source(
        project_id="project-unsupported",
        project_name="Unsupported House",
        brief_json=brief,
        geometry_json={"$schema": "external-model"},
    )

    assert unsupported.status == "unsupported"
    assert unsupported.source is None
    assert unsupported.fallback_required is True
    assert unsupported.blocker_reasons[0].field == "geometry_json.$schema"
