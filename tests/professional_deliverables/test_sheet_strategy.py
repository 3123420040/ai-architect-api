from __future__ import annotations

import pytest

from app.services.professional_deliverables.drawing_contract import DeliverableValidationError
from app.services.professional_deliverables.golden_fixture import build_golden_townhouse
from app.services.professional_deliverables.sheet_assembler import assemble_sheet_set


def test_golden_fixture_uses_per_floor_sheet_strategy():
    sheets = assemble_sheet_set(build_golden_townhouse())
    assert [sheet.filename_stem for sheet in sheets] == [
        "A-100-site",
        "A-101-F1-floorplan",
        "A-101-F2-floorplan",
        "A-201-elevations",
        "A-301-sections",
    ]
    assert len(sheets) == 5


def test_incomplete_project_without_roof_is_rejected():
    project = build_golden_townhouse()
    incomplete = project.__class__(
        **{
            **project.__dict__,
            "roof_outline": (),
        }
    )
    with pytest.raises(DeliverableValidationError, match="roof outline"):
        assemble_sheet_set(incomplete)

