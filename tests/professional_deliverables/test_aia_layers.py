from __future__ import annotations

from app.services.professional_deliverables.aia_layers import AIA_LAYER_BY_NAME, AIA_LAYERS


def test_aia_layer_dictionary_matches_prd_appendix_a_subset():
    assert len(AIA_LAYERS) == 25
    assert AIA_LAYER_BY_NAME["A-WALL"].color_name == "white"
    assert AIA_LAYER_BY_NAME["A-WALL"].aci_color == 7
    assert AIA_LAYER_BY_NAME["A-WALL"].lineweight_hundredths_mm == 50
    assert AIA_LAYER_BY_NAME["A-ANNO-DIMS"].color_name == "red"
    assert AIA_LAYER_BY_NAME["A-ANNO-DIMS"].aci_color == 1
    assert AIA_LAYER_BY_NAME["A-ANNO-DIMS"].lineweight_hundredths_mm == 25
    assert AIA_LAYER_BY_NAME["A-ANNO-NPLT"].plot is False
    assert AIA_LAYER_BY_NAME["L-SITE"].color_name == "brown"

