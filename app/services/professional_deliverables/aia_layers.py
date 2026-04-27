from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AIALayerSpec:
    name: str
    color_name: str
    aci_color: int
    lineweight_mm: float | None
    description: str
    plot: bool = True

    @property
    def lineweight_hundredths_mm(self) -> int | None:
        if self.lineweight_mm is None:
            return None
        return int(round(self.lineweight_mm * 100))


AIA_LAYERS: tuple[AIALayerSpec, ...] = (
    AIALayerSpec("A-WALL", "white", 7, 0.50, "Wall, full height"),
    AIALayerSpec("A-WALL-PRHT", "gray", 8, 0.35, "Wall, partial height"),
    AIALayerSpec("A-DOOR", "yellow", 2, 0.25, "Door symbols"),
    AIALayerSpec("A-DOOR-IDEN", "yellow", 2, 0.18, "Door tag/ID"),
    AIALayerSpec("A-GLAZ", "cyan", 4, 0.25, "Window/glazing"),
    AIALayerSpec("A-FURN", "green", 3, 0.18, "Furniture"),
    AIALayerSpec("A-FLOR-FIXT", "green", 3, 0.18, "Floor-mounted fixtures"),
    AIALayerSpec("A-AREA", "magenta", 6, 0.13, "Room area boundary"),
    AIALayerSpec("A-AREA-IDEN", "magenta", 6, 0.13, "Room name/area label"),
    AIALayerSpec("A-ROOF", "white", 7, 0.35, "Roof outline"),
    AIALayerSpec("A-ANNO-DIMS", "red", 1, 0.25, "Dimensions"),
    AIALayerSpec("A-ANNO-TEXT", "red", 1, 0.25, "Text annotations"),
    AIALayerSpec("A-ANNO-NPLT", "red", 1, None, "Construction lines", plot=False),
    AIALayerSpec("A-ANNO-TTLB", "white", 7, 0.50, "Title block"),
    AIALayerSpec("A-ANNO-NORTH", "red", 1, 0.25, "North arrow"),
    AIALayerSpec("A-ELEV-OTLN", "white", 7, 0.50, "Elevation outline"),
    AIALayerSpec("A-SECT-MCUT", "white", 7, 0.70, "Section cut line"),
    AIALayerSpec("A-SECT-OTLN", "white", 7, 0.50, "Section outline beyond cut"),
    AIALayerSpec("S-COLS", "white", 7, 0.50, "Structural columns"),
    AIALayerSpec("S-BEAM", "white", 7, 0.50, "Beams"),
    AIALayerSpec("S-FNDN", "white", 7, 0.50, "Foundation"),
    AIALayerSpec("E-LITE", "yellow", 2, 0.18, "Lighting fixtures"),
    AIALayerSpec("P-FIXT", "cyan", 4, 0.18, "Plumbing fixtures"),
    AIALayerSpec("L-PLNT", "green", 3, 0.18, "Landscape/planting"),
    AIALayerSpec("L-SITE", "brown", 30, 0.25, "Site boundary"),
)

AIA_LAYER_BY_NAME = {layer.name: layer for layer in AIA_LAYERS}

REQUIRED_RECOGNITION_LAYERS = {
    "A-WALL",
    "A-DOOR",
    "A-GLAZ",
    "A-FURN",
    "A-AREA",
    "A-ANNO-DIMS",
    "A-ANNO-TEXT",
    "A-ROOF",
    "S-COLS",
}


def apply_aia_layers(doc) -> None:
    for spec in AIA_LAYERS:
        if spec.name in doc.layers:
            layer = doc.layers.get(spec.name)
        else:
            layer = doc.layers.add(spec.name)
        layer.dxf.color = spec.aci_color
        if spec.lineweight_hundredths_mm is not None:
            layer.dxf.lineweight = spec.lineweight_hundredths_mm
        layer.dxf.plot = 1 if spec.plot else 0


def validate_aia_layer_table(doc) -> list[str]:
    issues: list[str] = []
    for spec in AIA_LAYERS:
        if spec.name not in doc.layers:
            issues.append(f"missing layer {spec.name}")
            continue
        layer = doc.layers.get(spec.name)
        if layer.dxf.color != spec.aci_color:
            issues.append(f"{spec.name} color {layer.dxf.color} != {spec.aci_color}")
        if spec.lineweight_hundredths_mm is not None and layer.dxf.lineweight != spec.lineweight_hundredths_mm:
            issues.append(
                f"{spec.name} lineweight {layer.dxf.lineweight} != {spec.lineweight_hundredths_mm}"
            )
        if int(layer.dxf.plot) != (1 if spec.plot else 0):
            issues.append(f"{spec.name} plot flag {layer.dxf.plot} != {1 if spec.plot else 0}")
    return issues


def validate_entity_layers(entities: Iterable) -> list[str]:
    issues: list[str] = []
    allowed = set(AIA_LAYER_BY_NAME)
    for entity in entities:
        layer = getattr(entity.dxf, "layer", None)
        if not layer:
            continue
        if layer == "0":
            issues.append(f"{entity.dxftype()} entity is on layer 0")
        elif layer not in allowed:
            issues.append(f"{entity.dxftype()} entity uses non-AIA layer {layer}")
    return issues

