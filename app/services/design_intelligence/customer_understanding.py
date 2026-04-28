from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.professional_deliverables.style_knowledge import normalize_signal


@dataclass(frozen=True)
class ReferenceImageDescriptor:
    description: str | None = None
    style_hint: str | None = None
    visual_tags: tuple[str, ...] = field(default_factory=tuple)
    materials: tuple[str, ...] = field(default_factory=tuple)
    colors: tuple[str, ...] = field(default_factory=tuple)
    spatial_features: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | ReferenceImageDescriptor) -> ReferenceImageDescriptor:
        if isinstance(payload, ReferenceImageDescriptor):
            return payload
        return cls(
            description=str(payload.get("description") or "") or None,
            style_hint=str(payload.get("style_hint") or "") or None,
            visual_tags=_tuple(payload.get("visual_tags") or payload.get("tags")),
            materials=_tuple(payload.get("materials")),
            colors=_tuple(payload.get("colors")),
            spatial_features=_tuple(payload.get("spatial_features") or payload.get("features")),
        )

    def signals(self) -> tuple[str, ...]:
        return tuple(
            signal
            for signal in (
                *(self.visual_tags or ()),
                *(self.materials or ()),
                *(self.colors or ()),
                *(self.spatial_features or ()),
                self.style_hint or "",
                self.description or "",
            )
            if signal
        )


@dataclass(frozen=True)
class CustomerUnderstanding:
    original_text: str
    normalized_text: str
    site_facts: dict[str, Any]
    family_lifestyle: dict[str, Any]
    room_program_hints: dict[str, Any]
    style_signals: tuple[str, ...]
    reference_images: tuple[ReferenceImageDescriptor, ...]
    image_signals: tuple[str, ...]
    likes: tuple[str, ...]
    dislikes: tuple[str, ...]
    missing_blockers: tuple[str, ...]
    assumptions: tuple[str, ...]


STYLE_SIGNAL_KEYWORDS = (
    "hien dai",
    "toi gian",
    "am",
    "xanh",
    "nhieu cay",
    "thoang",
    "nhiet doi",
    "indochine",
    "dong duong",
    "gan gui tu nhien",
    "low maintenance",
    "it bao tri",
)

LIKE_KEYWORDS = ("thich", "muon", "uu tien", "can", "mong muon")
DISLIKE_KEYWORDS = ("khong thich", "khong muon", "tranh", "han che", "ngai")


def parse_customer_understanding(
    message: str,
    reference_images: list[dict[str, Any] | ReferenceImageDescriptor] | tuple[dict[str, Any] | ReferenceImageDescriptor, ...] | None = None,
) -> CustomerUnderstanding:
    normalized = normalize_signal(message)
    images = tuple(ReferenceImageDescriptor.from_payload(payload) for payload in (reference_images or ()))
    site_facts = _extract_site_facts(normalized)
    room_program = _extract_room_program(normalized)
    family_lifestyle = _extract_family_lifestyle(normalized)
    style_signals = _extract_style_signals(normalized)
    likes = _extract_preference_phrases(normalized, LIKE_KEYWORDS)
    dislikes = _extract_preference_phrases(normalized, DISLIKE_KEYWORDS)
    image_signals = tuple(dict.fromkeys(signal for image in images for signal in image.signals()))
    missing_blockers = _missing_blockers(site_facts)
    assumptions = _assumptions(site_facts, room_program)

    return CustomerUnderstanding(
        original_text=message,
        normalized_text=normalized,
        site_facts=site_facts,
        family_lifestyle=family_lifestyle,
        room_program_hints=room_program,
        style_signals=style_signals,
        reference_images=images,
        image_signals=image_signals,
        likes=likes,
        dislikes=dislikes,
        missing_blockers=missing_blockers,
        assumptions=assumptions,
    )


def _extract_site_facts(normalized: str) -> dict[str, Any]:
    site: dict[str, Any] = {}
    lot_match = re.search(r"(?<!\d)(\d+(?:[\.,]\d+)?)\s*(?:x|\*)\s*(\d+(?:[\.,]\d+)?)\s*m?", normalized)
    if lot_match:
        width = float(lot_match.group(1).replace(",", "."))
        depth = float(lot_match.group(2).replace(",", "."))
        site["width_m"] = width
        site["depth_m"] = depth
        site["area_m2"] = round(width * depth, 2)
        site["shape"] = "assumed_rectangle"
    area_match = re.search(r"(?<!\d)(\d+(?:[\.,]\d+)?)\s*(?:m2|m²|met vuong)", normalized)
    if area_match and "area_m2" not in site:
        site["area_m2"] = float(area_match.group(1).replace(",", "."))
    orientation_map = {
        "north": ("huong bac",),
        "south": ("huong nam",),
        "east": ("huong dong",),
        "west": ("huong tay",),
        "northeast": ("huong dong bac", "dong bac"),
        "northwest": ("huong tay bac", "tay bac"),
        "southeast": ("huong dong nam", "dong nam"),
        "southwest": ("huong tay nam", "tay nam"),
    }
    for orientation, keywords in orientation_map.items():
        if any(keyword in normalized for keyword in keywords):
            site["orientation"] = orientation
            break
    if any(keyword in normalized for keyword in ("can ho", "chung cu", "apartment")):
        site["project_type"] = "apartment_renovation"
    elif any(keyword in normalized for keyword in ("biet thu", "villa")):
        site["project_type"] = "villa"
    elif any(keyword in normalized for keyword in ("nha pho", "nha ong", "townhouse")):
        site["project_type"] = "townhouse"
    elif "width_m" in site:
        site["project_type"] = "townhouse"
    return site


def _extract_room_program(normalized: str) -> dict[str, Any]:
    program: dict[str, Any] = {}
    floors_match = re.search(r"(\d+)\s*(?:tang|lau|floor)", normalized)
    if floors_match:
        program["floors"] = int(floors_match.group(1))
    bedrooms_match = re.search(r"(\d+)\s*(?:phong ngu|pn|bedroom)", normalized)
    if bedrooms_match:
        program["bedrooms"] = int(bedrooms_match.group(1))
    bathrooms_match = re.search(r"(\d+)\s*(?:wc|ve sinh|toilet|phong tam)", normalized)
    if bathrooms_match:
        program["bathrooms"] = int(bathrooms_match.group(1))
    if any(keyword in normalized for keyword in ("gara", "garage", "dau xe", "o to")):
        program["garage"] = True
    if "phong tho" in normalized:
        program["prayer_room"] = True
    if any(keyword in normalized for keyword in ("phong giat", "giat phoi", "laundry")):
        program["laundry"] = True
    if any(keyword in normalized for keyword in ("phong lam viec", "home office", "lam viec tai nha")):
        program["home_office"] = True
    if any(keyword in normalized for keyword in ("san vuon", "vuon", "nhieu cay", "greenery")):
        program["greenery"] = True
    return program


def _extract_family_lifestyle(normalized: str) -> dict[str, Any]:
    lifestyle: dict[str, Any] = {}
    occupant_match = re.search(r"(\d+)\s*(?:nguoi|thanh vien)", normalized)
    if occupant_match:
        lifestyle["occupant_count"] = int(occupant_match.group(1))
    if any(keyword in normalized for keyword in ("ong ba", "nguoi gia", "lon tuoi")):
        lifestyle["has_elders"] = True
    if any(keyword in normalized for keyword in ("tre nho", "tre em", "con nho", "em be")):
        lifestyle["has_children"] = True
    if any(keyword in normalized for keyword in ("lam viec tai nha", "work from home", "wfh")):
        lifestyle["work_from_home"] = True
    priorities: list[str] = []
    if any(keyword in normalized for keyword in ("nhieu anh sang", "lay sang", "anh sang tu nhien")):
        priorities.append("daylight")
    if any(keyword in normalized for keyword in ("thong gio", "mat me", "gio tu nhien", "thoang")):
        priorities.append("ventilation")
    if any(keyword in normalized for keyword in ("it bao tri", "low maintenance", "de don")):
        priorities.append("low_maintenance")
    if priorities:
        lifestyle["priorities"] = priorities
    return lifestyle


def _extract_style_signals(normalized: str) -> tuple[str, ...]:
    return tuple(keyword for keyword in STYLE_SIGNAL_KEYWORDS if keyword in normalized)


def _extract_preference_phrases(normalized: str, markers: tuple[str, ...]) -> tuple[str, ...]:
    phrases: list[str] = []
    for marker in markers:
        for match in re.finditer(rf"{re.escape(marker)}\s+([^.;,\n]+)", normalized):
            phrase = match.group(1).strip()
            if phrase:
                phrases.append(phrase[:80])
    return tuple(dict.fromkeys(phrases))


def _missing_blockers(site_facts: dict[str, Any]) -> tuple[str, ...]:
    blockers: list[str] = []
    if "area_m2" not in site_facts and ("width_m" not in site_facts or "depth_m" not in site_facts):
        blockers.append("lot_size_or_apartment_area")
    return tuple(blockers)


def _assumptions(site_facts: dict[str, Any], room_program: dict[str, Any]) -> tuple[str, ...]:
    assumptions: list[str] = []
    if site_facts.get("shape") == "assumed_rectangle":
        assumptions.append("Assume rectangular lot from stated width and depth until a site plan is provided.")
    if "garage" in room_program:
        assumptions.append("Resolve parking as a concept front-yard/garage zone, not a vehicle engineering layout.")
    return tuple(assumptions)


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if str(item).strip())
