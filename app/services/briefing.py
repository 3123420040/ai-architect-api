from __future__ import annotations

import re
import unicodedata
from typing import Any


PROJECT_TYPE_PATTERNS = (
    ("apartment_reno", ("can ho", "chung cu", "apartment", "reno")),
    ("shophouse", ("shophouse", "shop house", "nha pho kinh doanh")),
    ("home_office", ("home office", "van phong tai nha", "office tai nha", "vua o vua lam viec")),
    ("villa", ("biet thu", "villa")),
    ("townhouse", ("nha pho", "townhouse", "nha ong")),
)

STYLE_PATTERNS = (
    ("modern_minimalist", ("toi gian", "minimalist", "modern minimalist")),
    ("tropical_modern", ("tropical", "nhiet doi", "tropical modern")),
    ("indochine", ("indochine", "dong duong")),
    ("luxury_modern", ("sang trong", "luxury", "cao cap")),
    ("modern", ("hien dai", "modern")),
)

ORIENTATION_PATTERNS = {
    "north": ("huong bac", "bac"),
    "south": ("huong nam", "nam"),
    "east": ("huong dong", "dong"),
    "west": ("huong tay", "tay"),
    "northeast": ("dong bac",),
    "northwest": ("tay bac",),
    "southeast": ("dong nam",),
    "southwest": ("tay nam",),
}

SPECIAL_REQUEST_PATTERNS = {
    "garage": ("gara", "garage"),
    "balcony": ("ban cong", "balcony"),
    "skylight": ("gieng troi", "skylight"),
    "prayer_room": ("phong tho",),
    "home_office": ("phong lam viec", "home office", "van phong"),
    "laundry": ("phong giat", "laundry"),
    "garden": ("san vuon", "vuon", "garden"),
}

LIFESTYLE_PATTERNS = {
    "work_from_home": ("lam viec tai nha", "work from home", "wfh"),
    "elderly_friendly": ("nguoi gia", "ong ba", "cha me lon tuoi"),
    "family_with_kids": ("tre em", "con nho", "em be"),
    "pet_friendly": ("thu cung", "cho meo", "pet"),
    "daylight_priority": ("nhieu anh sang", "lay sang", "anh sang tu nhien"),
    "ventilation_priority": ("thong gio", "gio tu nhien", "mat me"),
}

MATERIAL_PATTERNS = {
    "wood_stone": ("go", "da tu nhien", "go va da"),
    "warm_neutral": ("be", "warm neutral", "trung tinh am"),
    "glass_metal": ("kinh", "kim loai", "glass", "metal"),
    "concrete_texture": ("be tong", "concrete", "xi mang"),
}

COLOR_PATTERNS = {
    "warm_neutral": ("be", "kem", "warm neutral", "trung tinh am"),
    "earthy": ("nau dat", "earth tone", "mau dat"),
    "monochrome": ("den trang xam", "monochrome", "xam"),
    "natural_green": ("xanh reu", "xanh la", "green"),
}

SECTION_LABELS = {
    "project_type": "Loại công trình",
    "site": "Thông tin khu đất",
    "program": "Chương trình công năng",
    "lifestyle": "Nhu cầu sử dụng",
    "design_direction": "Định hướng thiết kế",
    "budget_schedule": "Ngân sách và tiến độ",
    "priorities": "Ưu tiên và điều cần tránh",
}

SECTION_QUESTIONS = {
    "project_type": "Đây là nhà phố, biệt thự, cải tạo căn hộ, shophouse hay nhà kết hợp văn phòng?",
    "site": "Kích thước khu đất và hướng chính của công trình là gì?",
    "program": "Anh/chị cần bao nhiêu tầng, phòng ngủ, WC và không gian đặc biệt nào?",
    "lifestyle": "Gia đình sẽ sử dụng công trình như thế nào: có người lớn tuổi, trẻ nhỏ, làm việc tại nhà hay ưu tiên ánh sáng, thông gió?",
    "design_direction": "Phong cách, vật liệu hoặc cảm giác thiết kế mong muốn là gì?",
    "budget_schedule": "Ngân sách dự kiến và mốc thời gian mong muốn là gì?",
    "priorities": "Anh/chị có điều bắt buộc phải có hoặc điều chắc chắn không muốn đưa vào phương án không?",
}


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.lower())
    return "".join(character for character in normalized if unicodedata.category(character) != "Mn")


def merge_brief(existing: dict | None, incoming: dict | None) -> dict:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_brief(merged[key], value)
        else:
            merged[key] = value
    return merged


def _append_unique(brief: dict[str, Any], key: str, value: str) -> None:
    values = list(brief.get(key) or [])
    if value not in values:
        values.append(value)
    brief[key] = values


def _match_first(normalized: str, patterns: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    for resolved, keywords in patterns:
        if any(keyword in normalized for keyword in keywords):
            return resolved
    return None


def parse_message_to_brief(message: str, existing: dict | None = None) -> dict:
    brief = dict(existing or {})
    normalized = _normalize_text(message)

    project_type = _match_first(normalized, PROJECT_TYPE_PATTERNS)
    if project_type:
        brief["project_type"] = project_type

    if any(keyword in normalized for keyword in ("cai tao", "reno", "renovation", "sua chua")):
        brief["project_mode"] = "renovation"
    elif any(keyword in normalized for keyword in ("xay moi", "new build", "xay dung moi")):
        brief["project_mode"] = "new_build"

    if dims := re.search(r"(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)", normalized):
        width = float(dims.group(1).replace(",", "."))
        depth = float(dims.group(2).replace(",", "."))
        brief["lot"] = merge_brief(
            brief.get("lot"),
            {
                "width_m": width,
                "depth_m": depth,
                "area_m2": round(width * depth, 2),
            },
        )

    for orientation, keywords in ORIENTATION_PATTERNS.items():
        if any(keyword in normalized for keyword in keywords):
            brief["lot"] = merge_brief(brief.get("lot"), {"orientation": orientation})
            break

    if floors := re.search(r"(\d+)\s*tang", normalized):
        brief["floors"] = int(floors.group(1))

    rooms = dict(brief.get("rooms") or {})
    if bedrooms := re.search(r"(\d+)\s*(phong ngu|pn)", normalized):
        rooms["bedrooms"] = int(bedrooms.group(1))
    if bathrooms := re.search(r"(\d+)\s*(wc|ve sinh|phong tam)", normalized):
        rooms["bathrooms"] = int(bathrooms.group(1))
    if rooms:
        brief["rooms"] = rooms

    if budget := re.search(r"(\d+(?:[.,]\d+)?)\s*(ty|ti|ty dong|ti dong)", normalized):
        brief["budget_vnd"] = int(float(budget.group(1).replace(",", ".")) * 1_000_000_000)

    if timeline := re.search(r"(\d+)\s*(thang|month)", normalized):
        brief["timeline_months"] = int(timeline.group(1))

    style = _match_first(normalized, STYLE_PATTERNS)
    if style:
        brief["style"] = style

    material_direction = _match_first(normalized, tuple((key, value) for key, value in MATERIAL_PATTERNS.items()))
    if material_direction:
        brief["material_direction"] = material_direction

    color_direction = _match_first(normalized, tuple((key, value) for key, value in COLOR_PATTERNS.items()))
    if color_direction:
        brief["color_direction"] = color_direction

    for resolved, keywords in SPECIAL_REQUEST_PATTERNS.items():
        if any(keyword in normalized for keyword in keywords):
            _append_unique(brief, "special_requests", resolved)

    for resolved, keywords in LIFESTYLE_PATTERNS.items():
        if any(keyword in normalized for keyword in keywords):
            _append_unique(brief, "lifestyle_priorities", resolved)

    if must_haves := re.search(r"(bat buoc|phai co|muon co)\s+(.+)", normalized):
        _append_unique(brief, "must_haves", must_haves.group(2).strip())
    if must_not_haves := re.search(r"(khong muon|tranh|khong can)\s+(.+)", normalized):
        _append_unique(brief, "must_not_haves", must_not_haves.group(2).strip())

    return brief


def build_clarification_state(brief: dict | None) -> dict[str, Any]:
    resolved = brief or {}
    lot = resolved.get("lot") or {}
    rooms = resolved.get("rooms") or {}

    sections = [
        {
            "id": "project_type",
            "label": SECTION_LABELS["project_type"],
            "required": True,
            "complete": bool(resolved.get("project_type")),
            "detail": resolved.get("project_type"),
        },
        {
            "id": "site",
            "label": SECTION_LABELS["site"],
            "required": True,
            "complete": bool(lot.get("width_m") and lot.get("depth_m")),
            "detail": (
                f"{lot.get('width_m')}m x {lot.get('depth_m')}m"
                if lot.get("width_m") and lot.get("depth_m")
                else None
            ),
        },
        {
            "id": "program",
            "label": SECTION_LABELS["program"],
            "required": True,
            "complete": bool(resolved.get("floors") and (rooms.get("bedrooms") or rooms.get("bathrooms"))),
            "detail": (
                f"{resolved.get('floors', '?')} tầng, {rooms.get('bedrooms', '?')} phòng ngủ, {rooms.get('bathrooms', '?')} WC"
                if resolved.get("floors") or rooms
                else None
            ),
        },
        {
            "id": "lifestyle",
            "label": SECTION_LABELS["lifestyle"],
            "required": False,
            "complete": bool(resolved.get("lifestyle_priorities") or resolved.get("special_requests") or resolved.get("notes")),
            "detail": ", ".join((resolved.get("lifestyle_priorities") or []) + (resolved.get("special_requests") or [])) or resolved.get("notes"),
        },
        {
            "id": "design_direction",
            "label": SECTION_LABELS["design_direction"],
            "required": True,
            "complete": bool(resolved.get("style")),
            "detail": resolved.get("style"),
        },
        {
            "id": "budget_schedule",
            "label": SECTION_LABELS["budget_schedule"],
            "required": True,
            "complete": bool(resolved.get("budget_vnd")),
            "detail": (
                f"{round(float(resolved['budget_vnd']) / 1_000_000_000, 1)} tỷ VND"
                if resolved.get("budget_vnd")
                else None
            ),
        },
        {
            "id": "priorities",
            "label": SECTION_LABELS["priorities"],
            "required": False,
            "complete": bool(resolved.get("must_haves") or resolved.get("must_not_haves")),
            "detail": ", ".join((resolved.get("must_haves") or []) + (resolved.get("must_not_haves") or [])) or None,
        },
    ]

    completed_count = sum(1 for section in sections if section["complete"])
    critical_missing = [section for section in sections if section["required"] and not section["complete"]]
    advisory_missing = [section for section in sections if not section["required"] and not section["complete"]]

    return {
        "readiness_label": "ready_for_confirmation" if not critical_missing else "needs_clarification",
        "completion_ratio": round(completed_count / len(sections), 2),
        "completed_sections": completed_count,
        "total_sections": len(sections),
        "blocking_missing": [section["label"] for section in critical_missing],
        "advisory_missing": [section["label"] for section in advisory_missing],
        "next_questions": [SECTION_QUESTIONS[section["id"]] for section in (critical_missing + advisory_missing)[:3]],
        "sections": sections,
        "summary": {
            "project_type": resolved.get("project_type"),
            "site": sections[1]["detail"],
            "program": sections[2]["detail"],
            "style": resolved.get("style"),
            "material_direction": resolved.get("material_direction"),
            "color_direction": resolved.get("color_direction"),
            "budget_vnd": resolved.get("budget_vnd"),
        },
    }


def missing_brief_fields(brief: dict | None) -> list[str]:
    state = build_clarification_state(brief)
    return state["blocking_missing"] + state["advisory_missing"]


def generate_ai_follow_up(brief: dict | None) -> tuple[str, bool]:
    state = build_clarification_state(brief)
    if state["readiness_label"] == "ready_for_confirmation":
        if state["advisory_missing"]:
            return (
                "Tôi đã có đủ thông tin cốt lõi để chốt brief. Nếu muốn làm rõ thêm, anh/chị có thể bổ sung về nhu cầu sử dụng hoặc các ưu tiên cần tránh trước khi xác nhận.",
                False,
            )
        return (
            "Tôi đã tổng hợp đủ brief để xác nhận. Anh/chị có thể rà lại bảng yêu cầu, chỉnh sửa nếu cần rồi chuyển sang bước tạo phương án.",
            False,
        )

    prompts = state["next_questions"]
    joined = " ".join(prompts[:3])
    return (
        f"Tôi đã ghi nhận một phần yêu cầu. Để khóa brief chắc hơn, anh/chị vui lòng bổ sung giúp tôi: {joined}",
        True,
    )
