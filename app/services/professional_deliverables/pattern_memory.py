from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectPattern:
    pattern_id: str
    name: str
    typology: str
    site_width_range_m: tuple[float, float]
    site_depth_range_m: tuple[float, float]
    style_fit: tuple[str, ...]
    family_program_fit: tuple[str, ...]
    stair_lightwell_position: str
    room_sequence: tuple[str, ...]
    facade_strategy: str
    known_tradeoffs: tuple[str, ...]
    feedback_tags: tuple[str, ...]

    def site_matches(self, width_m: float | None, depth_m: float | None) -> bool:
        if width_m is None or depth_m is None:
            return False
        return self.site_width_range_m[0] <= width_m <= self.site_width_range_m[1] and self.site_depth_range_m[0] <= depth_m <= self.site_depth_range_m[1]


def seed_patterns() -> tuple[ProjectPattern, ...]:
    return (
        ProjectPattern(
            pattern_id="townhouse_5x20_lightwell",
            name="5x20 townhouse with middle lightwell",
            typology="townhouse",
            site_width_range_m=(4.5, 5.8),
            site_depth_range_m=(18.0, 22.5),
            style_fit=("minimal_warm", "modern_tropical"),
            family_program_fit=("small_family", "low_maintenance", "garage_optional"),
            stair_lightwell_position="center stair with compact lightwell",
            room_sequence=("front_parking", "living", "stair_lightwell", "kitchen_dining", "rear_service"),
            facade_strategy="simple warm facade with balcony planter and shaded glazing",
            known_tradeoffs=("tight frontage limits side windows", "middle lightwell trades bedroom area for ventilation"),
            feedback_tags=("low_maintenance", "more_storage", "privacy_from_street"),
        ),
        ProjectPattern(
            pattern_id="townhouse_villa_7x25_green_core",
            name="7x25 townhouse/villa with green core",
            typology="townhouse_villa",
            site_width_range_m=(6.5, 8.0),
            site_depth_range_m=(23.0, 27.5),
            style_fit=("modern_tropical", "minimal_warm"),
            family_program_fit=("multigeneration_family", "four_bedrooms", "garage", "children_elderly"),
            stair_lightwell_position="central stair beside planted courtyard/lightwell",
            room_sequence=("front_yard_garage", "living", "green_core_stair", "kitchen_dining", "rear_service"),
            facade_strategy="deep overhangs, vertical screens, balcony greenery, and large shaded openings",
            known_tradeoffs=("front parking reduces living frontage", "green core needs area allocation on each floor"),
            feedback_tags=("more_greenery", "elderly_ground_floor_room", "open_kitchen"),
        ),
        ProjectPattern(
            pattern_id="villa_10x20_courtyard",
            name="10x20 villa with courtyard edge",
            typology="villa",
            site_width_range_m=(9.0, 11.5),
            site_depth_range_m=(18.0, 22.5),
            style_fit=("modern_tropical", "indochine_soft"),
            family_program_fit=("premium_family", "garden", "guest_room"),
            stair_lightwell_position="stair toward one side with courtyard view",
            room_sequence=("front_garden", "living_dining", "courtyard", "guest_bedroom", "service"),
            facade_strategy="layered volume, garden-facing openings, warm natural material accents",
            known_tradeoffs=("larger garden improves feel but lowers enclosed area", "wide frontage needs facade rhythm"),
            feedback_tags=("premium_feel", "garden_view", "quiet_bedrooms"),
        ),
        ProjectPattern(
            pattern_id="apartment_reno_warm_storage",
            name="Apartment renovation with warm storage wall",
            typology="apartment_renovation",
            site_width_range_m=(7.0, 14.0),
            site_depth_range_m=(7.0, 16.0),
            style_fit=("minimal_warm", "indochine_soft"),
            family_program_fit=("small_family", "storage", "renovation"),
            stair_lightwell_position="not applicable; preserve building core",
            room_sequence=("entry_storage", "living_dining", "open_or_semi_open_kitchen", "bedrooms", "laundry"),
            facade_strategy="interior-only material and lighting concept; external facade unchanged unless allowed",
            known_tradeoffs=("fixed shafts constrain wet area moves", "storage walls reduce apparent room width"),
            feedback_tags=("more_storage", "low_maintenance", "brighter_interior"),
        ),
        ProjectPattern(
            pattern_id="corner_lot_breeze_privacy",
            name="Corner lot with dual frontage and privacy filter",
            typology="corner_lot",
            site_width_range_m=(5.0, 12.0),
            site_depth_range_m=(15.0, 28.0),
            style_fit=("modern_tropical", "minimal_warm", "indochine_soft"),
            family_program_fit=("dual_access", "privacy", "green_buffer"),
            stair_lightwell_position="stair/lightwell placed away from the main corner view",
            room_sequence=("corner_buffer_garden", "living", "stair", "kitchen_dining", "private_rooms_above"),
            facade_strategy="two readable facades with privacy screens and controlled corner glazing",
            known_tradeoffs=("dual frontage improves light but increases privacy exposure", "corner setbacks may reduce buildable area"),
            feedback_tags=("privacy", "corner_identity", "cross_ventilation"),
        ),
    )


class PatternMemory:
    def __init__(self, patterns: tuple[ProjectPattern, ...] | None = None) -> None:
        self.patterns = patterns or seed_patterns()

    def retrieve(self, facts: dict[str, Any], *, style_id: str | None = None, limit: int = 3) -> tuple[ProjectPattern, ...]:
        scored: list[tuple[float, ProjectPattern]] = []
        width = _float_or_none(facts.get("width_m") or facts.get("lot_width_m"))
        depth = _float_or_none(facts.get("depth_m") or facts.get("lot_depth_m"))
        typology = str(facts.get("typology") or facts.get("project_type") or "").lower()
        bedrooms = _float_or_none(facts.get("bedrooms"))
        floors = _float_or_none(facts.get("floors") or facts.get("levels"))
        wants_garage = bool(facts.get("garage") or facts.get("parking"))
        family_size = _float_or_none(facts.get("occupants") or facts.get("occupant_count"))
        signals = {str(signal).lower() for signal in facts.get("signals", []) or []}

        for pattern in self.patterns:
            score = 0.0
            if pattern.site_matches(width, depth):
                score += 4.0
            if style_id and style_id in pattern.style_fit:
                score += 2.0
            if typology and typology in pattern.typology:
                score += 1.5
            if wants_garage and "garage" in pattern.family_program_fit:
                score += 1.0
            if bedrooms and bedrooms >= 4 and "four_bedrooms" in pattern.family_program_fit:
                score += 1.0
            if floors and floors >= 3 and pattern.typology in {"townhouse", "townhouse_villa"}:
                score += 0.6
            if family_size and family_size >= 5 and "multigeneration_family" in pattern.family_program_fit:
                score += 1.0
            score += len(signals.intersection(pattern.family_program_fit + pattern.feedback_tags)) * 0.5
            if score > 0:
                scored.append((score, pattern))

        scored.sort(key=lambda item: (-item[0], item[1].pattern_id))
        return tuple(pattern for _, pattern in scored[:limit])


def retrieve_patterns(facts: dict[str, Any], *, style_id: str | None = None, limit: int = 3) -> tuple[ProjectPattern, ...]:
    return PatternMemory().retrieve(facts, style_id=style_id, limit=limit)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
