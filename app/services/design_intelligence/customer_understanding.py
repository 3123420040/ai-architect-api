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
            visual_tags=_tuple(payload.get("visual_tags") or payload.get("style_signals") or payload.get("tags")),
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
    project_type: str | None
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
    "modern tropical",
    "hien dai",
    "hien dai am",
    "hien dai xanh mat",
    "toi gian",
    "toi gian am",
    "am",
    "am sang",
    "xanh",
    "xanh mat",
    "nhieu cay",
    "thoang",
    "mat me",
    "nhiet doi",
    "indochine",
    "dong duong",
    "dong duong nhe",
    "co dien nhe",
    "may tre",
    "gach bong",
    "vom",
    "go toi",
    "mau kem",
    "gan gui tu nhien",
    "low maintenance",
    "it bao tri",
    "de don",
    "gon",
    "khong cau ky",
    "trung tinh",
)

LIKE_KEYWORDS = ("thich", "muon", "uu tien", "mong muon", "mong", "can co", "can them")
DISLIKE_KEYWORDS = ("khong thich", "khong muon", "khong can", "tranh", "han che", "ngai")


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
    dislikes = tuple(dict.fromkeys((*_extract_preference_phrases(normalized, DISLIKE_KEYWORDS), *_extract_dislike_style_features(normalized))))
    image_signals = tuple(dict.fromkeys(signal for image in images for signal in image.signals()))
    missing_blockers = _missing_blockers(site_facts)
    assumptions = _assumptions(site_facts, room_program, images)

    return CustomerUnderstanding(
        original_text=message,
        normalized_text=normalized,
        project_type=site_facts.get("project_type"),
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
    lot_match = _first_match(
        normalized,
        (
            r"(?<!\d)(\d+(?:[\.,]\d+)?)\s*(?:x|\*)\s*(\d+(?:[\.,]\d+)?)\s*m?",
            r"(?:ngang|rong|mat tien|frontage)\s*(\d+(?:[\.,]\d+)?)\s*m?.{0,24}?(?:sau|dai|depth)\s*(\d+(?:[\.,]\d+)?)\s*m?",
        ),
    )
    if lot_match:
        width = _number(lot_match.group(1))
        depth = _number(lot_match.group(2))
        site["width_m"] = width
        site["depth_m"] = depth
        site["area_m2"] = round(width * depth, 2)
        site["shape"] = "assumed_rectangle"
    area_match = re.search(r"(?<!\d)(\d+(?:[\.,]\d+)?)\s*(?:m2|m²|met vuong)", normalized)
    if area_match and "area_m2" not in site:
        site["area_m2"] = _number(area_match.group(1))
    orientation_map = {
        "northeast": ("huong dong bac", "dong bac"),
        "northwest": ("huong tay bac", "tay bac"),
        "southeast": ("huong dong nam", "dong nam"),
        "southwest": ("huong tay nam", "tay nam"),
        "north": ("huong bac",),
        "south": ("huong nam",),
        "east": ("huong dong",),
        "west": ("huong tay",),
    }
    for orientation, keywords in orientation_map.items():
        if any(keyword in normalized for keyword in keywords):
            site["orientation"] = orientation
            break
    if any(keyword in normalized for keyword in ("hem", "ngo nho", "alley")):
        site["access_context"] = "alley"
        site["access_edge"] = "front"
    if any(keyword in normalized for keyword in ("mat tien", "duong lon", "street front")):
        site["access_context"] = "street_front"
        site["access_edge"] = "front"
    if any(keyword in normalized for keyword in ("lo goc", "dat goc", "corner lot")):
        site["access_context"] = "corner"
        site["access_edge"] = "front_and_side"
    if any(keyword in normalized for keyword in ("cai tao", "sua lai", "renovation", "reno")):
        site["existing_context"] = "renovation"
    if any(keyword in normalized for keyword in ("nha cu", "hien trang", "as built")):
        site["existing_context"] = "existing_structure_or_as_built_needed"

    if any(keyword in normalized for keyword in ("can ho", "chung cu", "apartment", "flat", "studio")):
        site["project_type"] = "apartment_renovation"
        site["project_type_source"] = "user_fact"
    elif any(keyword in normalized for keyword in ("lo goc", "dat goc", "corner lot")):
        site["project_type"] = "corner_lot"
        site["project_type_source"] = "user_fact"
    elif any(keyword in normalized for keyword in ("biet thu", "villa")):
        site["project_type"] = "villa"
        site["project_type_source"] = "user_fact"
    elif any(keyword in normalized for keyword in ("nha pho", "nha ong", "townhouse")):
        site["project_type"] = "townhouse"
        site["project_type_source"] = "user_fact"
    elif "width_m" in site:
        site["project_type"] = "townhouse" if site["width_m"] <= 8.0 else "villa"
        site["project_type_source"] = "inferred_from_lot_dimensions"
    return site


def _extract_room_program(normalized: str) -> dict[str, Any]:
    program: dict[str, Any] = {}
    if "studio" in normalized:
        program["studio"] = True
    floors_match = re.search(r"(\d+)\s*(?:tang|lau|floor)", normalized)
    if floors_match:
        program["floors"] = int(floors_match.group(1))
    split_floor_match = re.search(r"tret\s*(?:\+|va)?\s*(\d+)\s*lau", normalized)
    if split_floor_match:
        program["floors"] = int(split_floor_match.group(1)) + 1
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
    if any(keyword in normalized for keyword in ("shophouse", "kinh doanh", "mat bang", "cua hang", "home business")):
        program["business_front"] = True
    if any(keyword in normalized for keyword in ("linh hoat", "da nang", "flexible", "guest/work", "khach lam viec")):
        program["flexible_space"] = True
    if any(keyword in normalized for keyword in ("san vuon", "vuon", "nhieu cay", "greenery")):
        program["greenery"] = True
    if any(keyword in normalized for keyword in ("luu tru", "kho", "tu do", "storage")):
        program["storage"] = True
    if any(keyword in normalized for keyword in ("ban cong", "balcony", "logia")):
        program["balcony"] = True
    if any(keyword in normalized for keyword in ("san thuong", "terrace", "mai xanh", "roof garden")):
        program["terrace"] = True
    if any(keyword in normalized for keyword in ("bep mo", "open kitchen", "lien thong bep")):
        program["open_kitchen"] = True
    if any(keyword in normalized for keyword in ("thang may", "elevator", "lift")):
        program["elevator"] = True
    must_haves = _collect_present(
        normalized,
        {
            "garage": ("gara", "garage", "dau xe", "o to"),
            "greenery": ("san vuon", "vuon", "nhieu cay", "greenery"),
            "storage": ("luu tru", "kho", "tu do", "storage"),
            "home_office": ("phong lam viec", "home office", "lam viec tai nha"),
            "laundry": ("phong giat", "giat phoi", "laundry"),
            "business_front": ("shophouse", "kinh doanh", "mat bang", "cua hang", "home business"),
        },
    )
    if must_haves:
        program["must_haves"] = must_haves
    return program


def _extract_family_lifestyle(normalized: str) -> dict[str, Any]:
    lifestyle: dict[str, Any] = {}
    occupant_match = re.search(r"(\d+)\s*(?:nguoi|thanh vien)", normalized)
    if occupant_match:
        lifestyle["occupant_count"] = int(occupant_match.group(1))
    couple_children_match = re.search(r"vo chong\s*(\d+)\s*con", normalized)
    if couple_children_match and "occupant_count" not in lifestyle:
        lifestyle["occupant_count"] = int(couple_children_match.group(1)) + 2
    if any(keyword in normalized for keyword in ("ong ba", "nguoi gia", "lon tuoi")):
        lifestyle["has_elders"] = True
    if any(keyword in normalized for keyword in ("tre nho", "tre em", "con nho", "em be")):
        lifestyle["has_children"] = True
    elif re.search(r"\d+\s*con", normalized):
        lifestyle["has_children"] = True
    if any(keyword in normalized for keyword in ("lam viec tai nha", "work from home", "wfh")):
        lifestyle["work_from_home"] = True
    if any(keyword in normalized for keyword in ("thu cung", "cho meo", "pet")):
        lifestyle["has_pets"] = True
    if any(keyword in normalized for keyword in ("gia dinh nho", "vo chong", "family nho")):
        lifestyle["household_type"] = "small_family"
    elif any(keyword in normalized for keyword in ("gia dinh tre", "cap vo chong tre")):
        lifestyle["household_type"] = "young_family"
    elif any(keyword in normalized for keyword in ("ong ba", "3 the he", "ba the he")):
        lifestyle["household_type"] = "multigeneration_family"
    priorities: list[str] = []
    if any(keyword in normalized for keyword in ("nhieu anh sang", "lay sang", "anh sang tu nhien")):
        priorities.append("daylight")
    if any(keyword in normalized for keyword in ("thong gio", "mat me", "gio tu nhien", "thoang")):
        priorities.append("ventilation")
    if any(keyword in normalized for keyword in ("it bao tri", "low maintenance", "de don")):
        priorities.append("low_maintenance")
    if any(keyword in normalized for keyword in ("rieng tu", "kin dao", "privacy")):
        priorities.append("privacy")
    if any(keyword in normalized for keyword in ("nhieu luu tru", "luu tru", "kho", "tu do")):
        priorities.append("storage")
    if any(keyword in normalized for keyword in ("bep mo", "open kitchen", "sinh hoat chung", "tiep khach", "social living")):
        priorities.append("open_social")
    if any(keyword in normalized for keyword in ("nhieu cay", "xanh", "vuon", "greenery")):
        priorities.append("greenery")
    if any(keyword in normalized for keyword in ("am sang", "sang trong", "cao cap", "premium")):
        priorities.append("premium_feel")
    if any(keyword in normalized for keyword in ("tiet kiem", "ngan sach", "budget")):
        priorities.append("budget_sensitive")
    if priorities:
        lifestyle["priorities"] = list(dict.fromkeys(priorities))
    return lifestyle


def _extract_style_signals(normalized: str) -> tuple[str, ...]:
    return tuple(keyword for keyword in STYLE_SIGNAL_KEYWORDS if _contains(normalized, keyword))


def _extract_preference_phrases(normalized: str, markers: tuple[str, ...]) -> tuple[str, ...]:
    phrases: list[str] = []
    for marker in markers:
        for match in re.finditer(rf"(?<!\w){re.escape(marker)}(?!\w)\s+([^.;,\n]+)", normalized):
            prefix = normalized[max(0, match.start() - 8) : match.start()].strip()
            if marker in {"thich", "muon"} and prefix.endswith(("khong", "dung")):
                continue
            phrase = match.group(1).strip()
            if phrase:
                phrases.append(phrase[:80])
    return tuple(dict.fromkeys(phrases))


def _extract_dislike_style_features(normalized: str) -> tuple[str, ...]:
    features: list[str] = []
    negative_context = any(marker in normalized for marker in DISLIKE_KEYWORDS)
    feature_groups = {
        "too much glass": ("qua nhieu kinh", "nhieu kinh", "less glass", "giam kinh", "bot kinh", "it kinh", "unshaded glass"),
        "cold facade": ("mat tien lanh", "cold facade", "it lanh", "bot lanh"),
        "cold/dark palette": ("cold dark palette", "cold/dark palette", "palette lanh toi", "mau lanh toi", "tone lanh toi", "toi lanh"),
        "glossy dark finishes": ("vat lieu toi bong", "toi bong", "glossy dark", "dark glossy"),
        "dark interior": ("noi that toi", "dark interior", "kin toi", "dong kin", "closed interior"),
        "overly decorative indochine": ("overly decorative indochine", "indochine qua cau ky", "dong duong qua cau ky", "qua nhieu chi tiet dong duong", "too ornate indochine"),
        "high-maintenance greenery": ("high maintenance greenery", "cay can cham nhieu", "cay can bao tri nhieu", "vuon kho cham", "ngai cham cay", "khong muon cham cay"),
        "closed kitchen": ("bep kin", "closed kitchen"),
        "narrow corridors": ("hanh lang hep", "narrow corridor", "narrow corridors"),
    }
    for label, keywords in feature_groups.items():
        if not any(keyword in normalized for keyword in keywords):
            continue
        if negative_context or label in {"too much glass", "cold facade"}:
            features.append(label)
    return tuple(dict.fromkeys(features))


def _missing_blockers(site_facts: dict[str, Any]) -> tuple[str, ...]:
    blockers: list[str] = []
    has_dimensions = "width_m" in site_facts and "depth_m" in site_facts
    has_apartment_area = site_facts.get("project_type") == "apartment_renovation" and "area_m2" in site_facts
    if not has_dimensions and not has_apartment_area:
        blockers.append("lot_width_depth_or_apartment_area")
    return tuple(blockers)


def _assumptions(site_facts: dict[str, Any], room_program: dict[str, Any], reference_images: tuple[ReferenceImageDescriptor, ...]) -> tuple[str, ...]:
    assumptions: list[str] = []
    if site_facts.get("shape") == "assumed_rectangle":
        assumptions.append("Assume rectangular lot from stated width and depth until a site plan is provided.")
    if site_facts.get("project_type_source") == "inferred_from_lot_dimensions":
        assumptions.append(f"Assume project type is {site_facts.get('project_type')} from lot dimensions until the homeowner confirms.")
    if site_facts.get("project_type") == "apartment_renovation" and "area_m2" in site_facts and ("width_m" not in site_facts or "depth_m" not in site_facts):
        assumptions.append("Assume a simple apartment rectangle from stated area until an as-built plan is provided.")
    if "orientation" not in site_facts:
        assumptions.append("Assume generic orientation and front access until site orientation/access is provided.")
    if "floors" not in room_program:
        if site_facts.get("project_type") == "apartment_renovation":
            assumptions.append("Assume one concept level for apartment renovation unless the homeowner says otherwise.")
        else:
            assumptions.append("Assume concept floor count from typology and lot proportions until the homeowner confirms.")
    if "bedrooms" not in room_program:
        assumptions.append("Assume room counts can be drafted from family size and confirmed later.")
    if room_program.get("studio"):
        assumptions.append("Treat studio planning as flexible living/sleeping zones, not separate enclosed bedrooms.")
    if "garage" in room_program:
        assumptions.append("Resolve parking as a concept front-yard/garage zone, not a vehicle engineering layout.")
    if room_program.get("business_front"):
        assumptions.append("Treat front business/service area as concept zoning only, not legal or licensing guidance.")
    if room_program.get("home_office"):
        assumptions.append("Place work-from-home as a concept zone until acoustic and privacy needs are confirmed.")
    if reference_images:
        assumptions.append("Treat reference images as structured descriptors only; no real image analysis is performed yet.")
    return tuple(assumptions)


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _first_match(normalized: str, patterns: tuple[str, ...]) -> re.Match[str] | None:
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match
    return None


def _number(value: str) -> float:
    return float(value.replace(",", "."))


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _collect_present(normalized: str, groups: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(key for key, keywords in groups.items() if any(keyword in normalized for keyword in keywords))
