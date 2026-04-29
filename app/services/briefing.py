from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any


PROJECT_TYPE_PATTERNS = (
    ("apartment_reno", ("can ho", "chung cu", "apartment", "cai tao can ho", "reno")),
    ("shophouse", ("shophouse", "shop house", "nha pho kinh doanh")),
    ("home_office", ("home office", "van phong tai nha", "office tai nha", "vua o vua lam viec")),
    ("villa", ("biet thu", "villa")),
    ("townhouse", ("nha pho", "townhouse", "nha ong")),
)

STYLE_PATTERNS = (
    ("minimal_warm", ("modern minimal warm", "minimal warm", "toi gian am", "hien dai toi gian am", "minimal am")),
    ("modern_minimalist", ("toi gian", "minimalist", "modern minimalist")),
    ("tropical_modern", ("tropical", "nhiet doi", "tropical modern")),
    ("indochine", ("indochine", "dong duong")),
    ("luxury_modern", ("sang trong", "luxury", "cao cap")),
    ("modern", ("hien dai", "modern")),
)

ORIENTATION_PATTERNS = {
    "northeast": ("huong dong bac", "dong bac"),
    "northwest": ("huong tay bac", "tay bac"),
    "southeast": ("huong dong nam", "dong nam"),
    "southwest": ("huong tay nam", "tay nam"),
    "north": ("huong bac",),
    "south": ("huong nam",),
    "east": ("huong dong",),
    "west": ("huong tay",),
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
    "family_with_kids": ("tre em", "tre nho", "con nho", "em be"),
    "pet_friendly": ("thu cung", "cho meo", "pet"),
    "daylight_priority": ("nhieu anh sang", "lay sang", "anh sang tu nhien"),
    "ventilation_priority": ("thong gio", "gio tu nhien", "mat me"),
}

MATERIAL_PATTERNS = {
    "wood_stone": ("go", "da tu nhien", "go va da"),
    "warm_neutral": ("warm neutral", "trung tinh am"),
    "glass_metal": ("kinh", "kim loai", "glass", "metal"),
    "concrete_texture": ("be tong", "concrete", "xi mang"),
}

COLOR_PATTERNS = {
    "warm_neutral": ("warm neutral", "trung tinh am"),
    "earthy": ("nau dat", "earth tone", "mau dat"),
    "monochrome": ("monochrome", "den trang xam", "xam don sac"),
    "natural_green": ("xanh reu", "xanh la", "green"),
}

RENOVATION_SCOPE_PATTERNS = {
    "full": ("cai tao toan bo", "toan bo", "lam moi toan bo"),
    "partial": ("mot phan", "cai tao mot phan", "chi mot phan"),
}

PROJECT_TYPE_LABELS = {
    "townhouse": "Nhà phố",
    "villa": "Biệt thự",
    "apartment_reno": "Cải tạo căn hộ",
    "shophouse": "Shophouse",
    "home_office": "Nhà kết hợp văn phòng",
}

PROJECT_MODE_LABELS = {
    "new_build": "Xây mới",
    "renovation": "Cải tạo",
}

STYLE_LABELS = {
    "minimal_warm": "Tối giản ấm",
    "modern_minimalist": "Hiện đại tối giản",
    "modern": "Hiện đại",
    "tropical_modern": "Nhiệt đới hiện đại",
    "indochine": "Indochine",
    "luxury_modern": "Hiện đại sang trọng",
}

ORIENTATION_LABELS = {
    "north": "hướng Bắc",
    "south": "hướng Nam",
    "east": "hướng Đông",
    "west": "hướng Tây",
    "northeast": "hướng Đông Bắc",
    "northwest": "hướng Tây Bắc",
    "southeast": "hướng Đông Nam",
    "southwest": "hướng Tây Nam",
}

SPECIAL_REQUEST_LABELS = {
    "garage": "Gara ô tô",
    "balcony": "Ban công",
    "skylight": "Giếng trời",
    "prayer_room": "Phòng thờ",
    "home_office": "Phòng làm việc",
    "laundry": "Phòng giặt",
    "garden": "Sân vườn",
}

LIFESTYLE_LABELS = {
    "work_from_home": "Làm việc tại nhà",
    "elderly_friendly": "Có người lớn tuổi",
    "family_with_kids": "Gia đình có trẻ nhỏ",
    "pet_friendly": "Có thú cưng",
    "daylight_priority": "Ưu tiên ánh sáng tự nhiên",
    "ventilation_priority": "Ưu tiên thông gió",
}

MATERIAL_LABELS = {
    "wood_stone": "Gỗ và đá tự nhiên",
    "warm_neutral": "Vật liệu trung tính ấm",
    "glass_metal": "Kính và kim loại",
    "concrete_texture": "Bê tông / xi măng mộc",
}

COLOR_LABELS = {
    "warm_neutral": "Tông trung tính ấm",
    "earthy": "Tông đất",
    "monochrome": "Đơn sắc",
    "natural_green": "Xanh tự nhiên",
}

RENOVATION_SCOPE_LABELS = {
    "full": "Cải tạo toàn bộ",
    "partial": "Cải tạo một phần",
}

SECTION_LABELS = {
    "project_type": "Loại hình",
    "site": "Hiện trạng / quy mô",
    "program": "Công năng",
    "lifestyle": "Người dùng & cách ở",
    "design_direction": "Định hướng thiết kế",
    "budget_schedule": "Ngân sách & tiến độ",
    "priorities": "Ưu tiên & điều cần tránh",
}

SECTION_STATUS_LABELS = {
    "missing": "Thiếu",
    "partial": "Tạm đủ",
    "complete": "Đã rõ",
    "conflict": "Mâu thuẫn",
}

READINESS_LABELS = {
    "needs_clarification": "Cần bổ sung",
    "ready_for_confirmation": "Sẵn sàng chốt",
}

PROJECT_RESET_KEYS = {
    "project_type",
    "project_mode",
    "lot",
    "floors",
    "rooms",
    "style",
    "material_direction",
    "color_direction",
    "budget_vnd",
    "timeline_months",
    "special_requests",
    "lifestyle_priorities",
    "must_haves",
    "must_not_haves",
    "occupant_count",
    "household_profile",
    "renovation_scope",
    "design_goals",
    "space_requests",
    "spatial_preferences",
    "notes",
}


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.lower())
    return "".join(character for character in normalized if unicodedata.category(character) != "Mn")


def _keyword_pattern(keyword: str) -> str:
    escaped = re.escape(keyword)
    return escaped.replace(r"\ ", r"\s+")


def _contains_keyword(normalized: str, keyword: str) -> bool:
    return re.search(rf"(?<!\w){_keyword_pattern(keyword)}(?!\w)", normalized) is not None


def _contains_any(normalized: str, keywords: tuple[str, ...]) -> bool:
    return any(_contains_keyword(normalized, keyword) for keyword in keywords)


def _match_first(normalized: str, patterns: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    for resolved, keywords in patterns:
        if _contains_any(normalized, keywords):
            return resolved
    return None


def _match_many(normalized: str, patterns: dict[str, tuple[str, ...]]) -> list[str]:
    return [resolved for resolved, keywords in patterns.items() if _contains_any(normalized, keywords)]


def _append_unique(brief: dict[str, Any], key: str, value: str) -> None:
    values = list(brief.get(key) or [])
    if value not in values:
        values.append(value)
    brief[key] = values


def _append_note(brief: dict[str, Any], value: str) -> None:
    notes = list(brief.get("notes") or [])
    if value not in notes:
        notes.append(value)
    brief["notes"] = notes


def _clean_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" .,;:")).strip()


def _priority_label(value: str) -> str:
    cleaned = _clean_phrase(value)
    if "anh sang" in cleaned and "thong gio" in cleaned:
        return "Nhiều ánh sáng tự nhiên và thông gió"
    if "khong gian bi" in cleaned or "phong toi" in cleaned:
        return "Tránh không gian bí, tối"
    return cleaned


def _merge_dict(existing: dict | None, incoming: dict | None) -> dict:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_brief(existing: dict | None, incoming: dict | None) -> dict:
    merged = copy.deepcopy(existing or {})
    for key, value in (incoming or {}).items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
            continue
        if isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = list(dict.fromkeys([*merged[key], *value]))
            continue
        merged[key] = value
    return merged


def _add_fact(facts: dict[str, dict[str, str]], key: str, label: str, value: str) -> None:
    if value:
        facts[key] = {"key": key, "label": label, "value": value}


def humanize_project_type(value: str | None) -> str:
    return PROJECT_TYPE_LABELS.get(value or "", value or "Chưa rõ")


def humanize_style(value: str | None) -> str:
    return STYLE_LABELS.get(value or "", value or "Chưa rõ")


def humanize_material(value: str | None) -> str:
    return MATERIAL_LABELS.get(value or "", value or "Chưa rõ")


def humanize_color(value: str | None) -> str:
    return COLOR_LABELS.get(value or "", value or "Chưa rõ")


def humanize_special_request(value: str) -> str:
    return SPECIAL_REQUEST_LABELS.get(value, value)


def humanize_lifestyle(value: str) -> str:
    return LIFESTYLE_LABELS.get(value, value)


def humanize_renovation_scope(value: str | None) -> str:
    return RENOVATION_SCOPE_LABELS.get(value or "", value or "Chưa rõ")


def _format_currency(value: int | float | None) -> str | None:
    if not value:
        return None
    return f"{round(float(value) / 1_000_000_000, 1)} tỷ VND"


def _format_site_detail(brief: dict[str, Any]) -> str | None:
    lot = brief.get("lot") or {}
    area = lot.get("area_m2")
    width = lot.get("width_m")
    depth = lot.get("depth_m")
    orientation = lot.get("orientation")
    orientation_label = ORIENTATION_LABELS.get(orientation)

    if brief.get("project_type") == "apartment_reno":
        if area and orientation_label:
            return f"Căn hộ {area} m², {orientation_label}"
        if area:
            return f"Căn hộ {area} m²"
        return None

    if width and depth and orientation_label:
        return f"{width}m x {depth}m, {orientation_label}"
    if width and depth:
        return f"{width}m x {depth}m"
    if area:
        return f"{area} m²"
    return None


def _format_program_detail(brief: dict[str, Any]) -> str | None:
    rooms = brief.get("rooms") or {}
    parts: list[str] = []
    if brief.get("project_type") != "apartment_reno" and brief.get("floors"):
        parts.append(f"{brief['floors']} tầng")
    if rooms.get("bedrooms"):
        parts.append(f"{rooms['bedrooms']} phòng ngủ")
    if rooms.get("bathrooms"):
        parts.append(f"{rooms['bathrooms']} WC")
    if brief.get("renovation_scope"):
        parts.append(humanize_renovation_scope(brief["renovation_scope"]))
    if brief.get("space_requests"):
        parts.extend(list(brief["space_requests"]))
    return ", ".join(parts) if parts else None


def _format_lifestyle_detail(brief: dict[str, Any]) -> str | None:
    parts: list[str] = []
    if brief.get("occupant_count"):
        parts.append(f"{brief['occupant_count']} người ở")
    if brief.get("household_profile"):
        parts.append(str(brief["household_profile"]))
    parts.extend(humanize_lifestyle(item) for item in brief.get("lifestyle_priorities") or [])
    return ", ".join(dict.fromkeys(parts)) if parts else None


def _format_design_detail(brief: dict[str, Any]) -> str | None:
    parts: list[str] = []
    if brief.get("style"):
        parts.append(humanize_style(brief["style"]))
    if brief.get("design_goals"):
        parts.extend(list(brief["design_goals"]))
    if brief.get("material_direction"):
        parts.append(humanize_material(brief["material_direction"]))
    if brief.get("color_direction"):
        parts.append(humanize_color(brief["color_direction"]))
    return ", ".join(dict.fromkeys(parts)) if parts else None


def _format_priority_detail(brief: dict[str, Any]) -> str | None:
    parts: list[str] = []
    parts.extend(list(brief.get("must_haves") or []))
    parts.extend(list(brief.get("must_not_haves") or []))
    parts.extend(humanize_special_request(item) for item in brief.get("special_requests") or [])
    parts.extend(list(brief.get("spatial_preferences") or []))
    return ", ".join(dict.fromkeys(parts)) if parts else None


def _section_status(*, complete: bool, partial: bool, conflicting: bool = False) -> str:
    if conflicting:
        return "conflict"
    if complete:
        return "complete"
    if partial:
        return "partial"
    return "missing"


def _section_payload(
    *,
    section_id: str,
    complete: bool,
    partial: bool,
    detail: str | None,
    required: bool,
    conflicting: bool = False,
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    status = _section_status(complete=complete, partial=partial, conflicting=conflicting)
    return {
        "id": section_id,
        "label": SECTION_LABELS[section_id],
        "required": required,
        "complete": complete and not conflicting,
        "status": status,
        "status_label": SECTION_STATUS_LABELS[status],
        "detail": detail,
        "missing_fields": missing_fields or [],
    }


def _reset_brief_for_context_switch(brief: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in brief.items() if key not in PROJECT_RESET_KEYS}


def analyze_message_to_brief(message: str, existing: dict | None = None) -> dict[str, Any]:
    previous = copy.deepcopy(existing or {})
    brief = copy.deepcopy(existing or {})
    normalized = _normalize_text(message)
    facts: dict[str, dict[str, str]] = {}
    conflicts: list[dict[str, str]] = []

    detected_project_type = _match_first(normalized, PROJECT_TYPE_PATTERNS)
    previous_project_type = previous.get("project_type")
    if detected_project_type and previous_project_type and detected_project_type != previous_project_type:
        brief = _reset_brief_for_context_switch(brief)
        conflicts.append(
            {
                "title": "Phát hiện đổi brief",
                "detail": (
                    f"Tin nhắn mới đang chuyển từ {humanize_project_type(previous_project_type)} "
                    f"sang {humanize_project_type(detected_project_type)}. Hệ thống sẽ ưu tiên brief mới nhất."
                ),
            }
        )

    if detected_project_type:
        brief["project_type"] = detected_project_type
        _add_fact(facts, "project_type", "Loại công trình", humanize_project_type(detected_project_type))

    if _contains_any(normalized, ("cai tao", "renovation", "sua chua", "reno")):
        brief["project_mode"] = "renovation"
        _add_fact(facts, "project_mode", "Phạm vi dự án", PROJECT_MODE_LABELS["renovation"])
    elif _contains_any(normalized, ("xay moi", "new build", "xay dung moi")):
        brief["project_mode"] = "new_build"
        _add_fact(facts, "project_mode", "Phạm vi dự án", PROJECT_MODE_LABELS["new_build"])

    lot = dict(brief.get("lot") or {})
    dims = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:x|×|\*|by)\s*(\d+(?:[.,]\d+)?)", normalized)
    if dims:
        width = float(dims.group(1).replace(",", "."))
        depth = float(dims.group(2).replace(",", "."))
        lot = _merge_dict(lot, {"width_m": width, "depth_m": depth, "area_m2": round(width * depth, 2)})
        _add_fact(facts, "lot_dims", "Kích thước", f"{width}m x {depth}m")

    if area_match := re.search(r"(\d+(?:[.,]\d+)?)\s*(m2|m²)", normalized):
        area = float(area_match.group(1).replace(",", "."))
        lot = _merge_dict(lot, {"area_m2": round(area, 2)})
        if brief.get("project_type") == "apartment_reno":
            _add_fact(facts, "lot_area", "Diện tích căn hộ", f"{round(area, 2)} m²")
        else:
            _add_fact(facts, "lot_area", "Diện tích", f"{round(area, 2)} m²")

    for orientation, keywords in ORIENTATION_PATTERNS.items():
        if _contains_any(normalized, keywords):
            lot = _merge_dict(lot, {"orientation": orientation})
            _add_fact(facts, "orientation", "Hướng chính", ORIENTATION_LABELS.get(orientation, orientation))
            break
    if lot:
        brief["lot"] = lot

    if floors := re.search(r"(\d+)\s*(tang|lau)", normalized):
        brief["floors"] = int(floors.group(1))
        _add_fact(facts, "floors", "Số tầng", f"{brief['floors']} tầng")

    rooms = dict(brief.get("rooms") or {})
    if bedrooms := re.search(r"(\d+)\s*(phong ngu|pn)", normalized):
        rooms["bedrooms"] = int(bedrooms.group(1))
        _add_fact(facts, "bedrooms", "Phòng ngủ", f"{rooms['bedrooms']} phòng ngủ")
    if bathrooms := re.search(r"(\d+)\s*(wc|ve sinh|phong tam|nha tam)", normalized):
        rooms["bathrooms"] = int(bathrooms.group(1))
        _add_fact(facts, "bathrooms", "WC", f"{rooms['bathrooms']} WC")
    if rooms:
        brief["rooms"] = rooms

    if budget := re.search(r"(\d+(?:[.,]\d+)?)\s*(ty|ti|ty dong|ti dong|ty vnd|ti vnd)", normalized):
        brief["budget_vnd"] = int(float(budget.group(1).replace(",", ".")) * 1_000_000_000)
        _add_fact(facts, "budget_vnd", "Ngân sách", _format_currency(brief["budget_vnd"]) or "")

    if timeline := re.search(r"(\d+)\s*(thang|month)", normalized):
        brief["timeline_months"] = int(timeline.group(1))
        _add_fact(facts, "timeline_months", "Tiến độ mong muốn", f"{brief['timeline_months']} tháng")

    if people := re.search(r"(\d+)\s*(nguoi|ng)", normalized):
        brief["occupant_count"] = int(people.group(1))
        _add_fact(facts, "occupant_count", "Số người ở", f"{brief['occupant_count']} người")

    if generations := re.search(r"(\d+)\s*the he", normalized):
        brief["household_profile"] = f"Gia đình {generations.group(1)} thế hệ"
        _add_fact(facts, "household_profile", "Hồ sơ hộ gia đình", brief["household_profile"])

    for scope, keywords in RENOVATION_SCOPE_PATTERNS.items():
        if _contains_any(normalized, keywords):
            brief["renovation_scope"] = scope
            _add_fact(facts, "renovation_scope", "Phạm vi cải tạo", humanize_renovation_scope(scope))
            break

    style = _match_first(normalized, STYLE_PATTERNS)
    if style:
        brief["style"] = style
        _add_fact(facts, "style", "Phong cách", humanize_style(style))

    material_direction = _match_first(normalized, tuple((key, value) for key, value in MATERIAL_PATTERNS.items()))
    if material_direction:
        brief["material_direction"] = material_direction
        _add_fact(facts, "material_direction", "Vật liệu", humanize_material(material_direction))

    color_direction = _match_first(normalized, tuple((key, value) for key, value in COLOR_PATTERNS.items()))
    if color_direction:
        brief["color_direction"] = color_direction
        _add_fact(facts, "color_direction", "Màu sắc", humanize_color(color_direction))

    for resolved in _match_many(normalized, SPECIAL_REQUEST_PATTERNS):
        _append_unique(brief, "special_requests", resolved)

    for resolved in _match_many(normalized, LIFESTYLE_PATTERNS):
        _append_unique(brief, "lifestyle_priorities", resolved)

    if _contains_any(normalized, ("phong lam viec", "home office")) and _contains_any(normalized, ("thu vien", "library")):
        _append_unique(brief, "space_requests", "Phòng làm việc kết hợp thư viện")
        _add_fact(facts, "space_requests", "Không gian đặc biệt", "Phòng làm việc kết hợp thư viện")

    if _contains_any(normalized, ("phong bep", "bep")) and _contains_any(normalized, ("phong khach",)) and _contains_any(normalized, ("noi lien", "lien thong")):
        _append_unique(brief, "spatial_preferences", "Bếp và phòng khách liên thông")
        _add_fact(facts, "open_plan", "Tổ chức không gian", "Bếp và phòng khách liên thông")

    if _contains_any(normalized, ("gan gui", "am ap")):
        _append_unique(brief, "design_goals", "Không gian gần gũi, ấm áp")
        _add_fact(facts, "warm_feel", "Cảm giác không gian", "Gần gũi, ấm áp")

    if _contains_any(normalized, ("xanh", "than thien tu nhien", "tu nhien")):
        _append_unique(brief, "design_goals", "Thiết kế xanh, gần gũi tự nhiên")

    if _contains_any(normalized, ("cua so",)) and _contains_any(normalized, ("nhin ra cay xanh", "nhin ra vuon", "nhin ra xanh")):
        _append_unique(brief, "spatial_preferences", "Cửa sổ nhìn ra cây xanh")
        _add_fact(facts, "window_view", "Ưu tiên tầm nhìn", "Cửa sổ nhìn ra cây xanh")

    if _contains_any(normalized, ("ban cong xanh",)):
        _append_unique(brief, "space_requests", "Ban công xanh")
        _add_fact(facts, "green_balcony", "Không gian đặc biệt", "Ban công xanh")

    if must_haves := re.search(r"(bat buoc|phai co|muon co)\s+(.+)", normalized):
        phrase = must_haves.group(2).strip()
        negative_split = re.search(r"\s+va\s+(tranh|khong muon|khong can|han che)\s+(.+)", phrase)
        if negative_split:
            must_phrase = phrase[: negative_split.start()].strip()
            negative_phrase = negative_split.group(2).strip()
            if must_phrase:
                _append_unique(brief, "must_haves", _priority_label(must_phrase))
            if negative_phrase:
                _append_unique(brief, "must_not_haves", _priority_label(negative_phrase))
        else:
            _append_unique(brief, "must_haves", _priority_label(phrase))
    if must_not_haves := re.search(r"(khong muon|tranh|khong can|han che)\s+(.+)", normalized):
        _append_unique(brief, "must_not_haves", _priority_label(must_not_haves.group(2).strip()))

    if brief.get("project_type") == "apartment_reno" and _contains_any(
        normalized,
        ("lo dat", "khu dat", "biet thu", "nha pho", "shophouse"),
    ):
        conflicts.append(
            {
                "title": "Ngữ cảnh công trình chưa khớp",
                "detail": "Brief hiện tại đang là cải tạo căn hộ nhưng tin nhắn mới lại nhắc tới lô đất / nhà ở riêng.",
            }
        )

    if previous.get("project_type") == "apartment_reno" and dims:
        conflicts.append(
            {
                "title": "Thông tin khu đất cần xác nhận lại",
                "detail": "Căn hộ thường không dùng kích thước lô đất để chốt brief. Nếu đây là dự án nhà ở mới, cần xác nhận đã đổi brief.",
            }
        )

    if not facts and message.strip():
        _append_note(brief, message.strip())

    return {
        "brief_json": brief,
        "captured_facts": list(facts.values()),
        "conflicts": conflicts,
        "project_switched": bool(conflicts and detected_project_type and previous_project_type and detected_project_type != previous_project_type),
    }


def _build_next_prompts(brief: dict[str, Any], conflicts: list[dict[str, str]]) -> list[dict[str, str]]:
    prompts: list[dict[str, str]] = []
    project_type = brief.get("project_type")
    lot = brief.get("lot") or {}
    rooms = brief.get("rooms") or {}

    if conflicts:
        prompts.append(
            {
                "key": "active_brief",
                "question": f"Anh/chị xác nhận giúp: mình đang chốt brief cho {humanize_project_type(project_type)} đúng không?",
                "hint": "Xác nhận đúng loại dự án trước khi đi tiếp để không trộn dữ liệu cũ.",
                "example": humanize_project_type(project_type),
            }
        )

    if not project_type:
        prompts.append(
            {
                "key": "project_type",
                "question": "Đây là nhà phố, biệt thự, cải tạo căn hộ, shophouse hay nhà kết hợp văn phòng?",
                "hint": "Loại công trình quyết định bộ câu hỏi và chuẩn đầu ra tiếp theo.",
                "example": "Cải tạo căn hộ 95 m²",
            }
        )

    if project_type == "apartment_reno":
        if not lot.get("area_m2"):
            prompts.append(
                {
                    "key": "area_m2",
                    "question": "Căn hộ có diện tích bao nhiêu m² và hiện trạng đang muốn cải tạo toàn bộ hay một phần?",
                    "hint": "Diện tích và phạm vi cải tạo là dữ liệu cốt lõi để khóa hiện trạng.",
                    "example": "95 m², cải tạo toàn bộ",
                }
            )
        elif not brief.get("renovation_scope"):
            prompts.append(
                {
                    "key": "renovation_scope",
                    "question": "Anh/chị muốn cải tạo toàn bộ hay chỉ một phần căn hộ?",
                    "hint": "Cần chốt phạm vi để tránh over-scope.",
                    "example": "Cải tạo toàn bộ",
                }
            )
    else:
        if not (lot.get("width_m") and lot.get("depth_m")):
            prompts.append(
                {
                    "key": "lot_dims",
                    "question": "Khu đất rộng x sâu bao nhiêu và hướng chính của công trình là gì?",
                    "hint": "Kích thước khu đất là điều kiện tiên quyết để lên công năng chuẩn.",
                    "example": "5x20m, hướng Nam",
                }
            )

    if project_type == "apartment_reno":
        if not rooms.get("bedrooms") or not rooms.get("bathrooms"):
            prompts.append(
                {
                    "key": "room_counts",
                    "question": "Căn hộ cần mấy phòng ngủ và mấy WC sau khi cải tạo?",
                    "hint": "Cần chốt số phòng để khóa công năng chính.",
                    "example": "4 phòng ngủ, 3 WC",
                }
            )
    else:
        if not brief.get("floors") or not rooms.get("bedrooms") or not rooms.get("bathrooms"):
            prompts.append(
                {
                    "key": "program",
                    "question": "Anh/chị muốn bố trí mấy tầng, mấy phòng ngủ, mấy WC và có không gian đặc biệt nào?",
                    "hint": "Công năng chính càng rõ thì phương án càng bám nhu cầu thật.",
                    "example": "4 tầng, 4 phòng ngủ, 3 WC, có gara và phòng thờ",
                }
            )

    if not brief.get("occupant_count") and not brief.get("household_profile"):
        prompts.append(
            {
                "key": "occupants",
                "question": "Nhà sẽ có bao nhiêu người ở và có ai cần nhu cầu sử dụng riêng không?",
                "hint": "Ví dụ: người lớn tuổi, trẻ nhỏ, làm việc tại nhà, cần nhiều lưu trữ.",
                "example": "6 người, có góc làm việc tại nhà",
            }
        )

    if not brief.get("style") and not brief.get("design_goals"):
        prompts.append(
            {
                "key": "design_direction",
                "question": "Anh/chị muốn không gian theo phong cách và cảm giác nào?",
                "hint": "Có thể mô tả bằng từ khóa như hiện đại ấm, xanh tự nhiên, tối giản, sang trọng.",
                "example": "Hiện đại ấm, xanh và gần gũi tự nhiên",
            }
        )

    if not brief.get("budget_vnd") or not brief.get("timeline_months"):
        prompts.append(
            {
                "key": "budget_schedule",
                "question": "Ngân sách dự kiến và mốc thời gian mong muốn là gì?",
                "hint": "Cần đủ cả ngân sách và tiến độ để tránh đề xuất lệch kỳ vọng.",
                "example": "7 tỷ, hoàn thành trong 2 tháng",
            }
        )

    if not brief.get("must_haves") and not brief.get("must_not_haves"):
        prompts.append(
            {
                "key": "priorities",
                "question": "Anh/chị có điều bắt buộc phải có hoặc điều chắc chắn cần tránh không?",
                "hint": "Ví dụ: phải có nhiều lưu trữ, không muốn bếp kín, tránh tone quá tối.",
                "example": "Bắt buộc nhiều lưu trữ, tránh không gian bí",
            }
        )

    unique_prompts: list[dict[str, str]] = []
    seen: set[str] = set()
    for prompt in prompts:
        if prompt["key"] in seen:
            continue
        seen.add(prompt["key"])
        unique_prompts.append(prompt)
    return unique_prompts[:3]


def build_clarification_state(brief: dict | None, conflicts: list[dict[str, str]] | None = None) -> dict[str, Any]:
    resolved = copy.deepcopy(brief or {})
    active_conflicts = list(conflicts or [])
    lot = resolved.get("lot") or {}
    rooms = resolved.get("rooms") or {}
    project_type = resolved.get("project_type")

    site_complete = bool(lot.get("area_m2")) if project_type == "apartment_reno" else bool(lot.get("width_m") and lot.get("depth_m"))
    site_partial = bool(lot.get("area_m2") or lot.get("width_m") or lot.get("depth_m") or lot.get("orientation"))
    program_complete = (
        bool(rooms.get("bedrooms") and rooms.get("bathrooms") and resolved.get("renovation_scope"))
        if project_type == "apartment_reno"
        else bool(resolved.get("floors") and rooms.get("bedrooms") and rooms.get("bathrooms"))
    )
    program_partial = bool(resolved.get("floors") or rooms.get("bedrooms") or rooms.get("bathrooms") or resolved.get("renovation_scope"))
    lifestyle_complete = bool(resolved.get("occupant_count") or resolved.get("household_profile") or resolved.get("lifestyle_priorities"))
    lifestyle_partial = lifestyle_complete or bool(resolved.get("space_requests") or resolved.get("spatial_preferences"))
    design_complete = bool(resolved.get("style") or resolved.get("design_goals"))
    design_partial = design_complete or bool(resolved.get("material_direction") or resolved.get("color_direction"))
    budget_complete = bool(resolved.get("budget_vnd") and resolved.get("timeline_months"))
    budget_partial = bool(resolved.get("budget_vnd") or resolved.get("timeline_months"))
    priorities_complete = bool(
        resolved.get("must_haves")
        or resolved.get("must_not_haves")
        or resolved.get("special_requests")
        or resolved.get("spatial_preferences")
    )

    sections = [
        _section_payload(
            section_id="project_type",
            complete=bool(project_type),
            partial=bool(project_type),
            detail=humanize_project_type(project_type) if project_type else None,
            required=True,
            conflicting=bool(active_conflicts and not project_type),
            missing_fields=["Loại công trình"] if not project_type else [],
        ),
        _section_payload(
            section_id="site",
            complete=site_complete,
            partial=site_partial,
            detail=_format_site_detail(resolved),
            required=True,
            conflicting=bool(active_conflicts and project_type == "apartment_reno" and lot.get("width_m") and lot.get("depth_m")),
            missing_fields=["Diện tích / hiện trạng"] if not site_complete else [],
        ),
        _section_payload(
            section_id="program",
            complete=program_complete,
            partial=program_partial,
            detail=_format_program_detail(resolved),
            required=True,
            missing_fields=(
                ["Số phòng và phạm vi cải tạo"]
                if project_type == "apartment_reno" and not program_complete
                else ["Số tầng, phòng ngủ, WC"] if not program_complete else []
            ),
        ),
        _section_payload(
            section_id="lifestyle",
            complete=lifestyle_complete,
            partial=lifestyle_partial,
            detail=_format_lifestyle_detail(resolved),
            required=False,
        ),
        _section_payload(
            section_id="design_direction",
            complete=design_complete,
            partial=design_partial,
            detail=_format_design_detail(resolved),
            required=True,
            missing_fields=["Phong cách / cảm giác thiết kế"] if not design_complete else [],
        ),
        _section_payload(
            section_id="budget_schedule",
            complete=budget_complete,
            partial=budget_partial,
            detail=", ".join(
                item
                for item in [
                    _format_currency(resolved.get("budget_vnd")),
                    f"{resolved['timeline_months']} tháng" if resolved.get("timeline_months") else None,
                ]
                if item
            )
            or None,
            required=True,
            missing_fields=["Ngân sách và tiến độ"] if not budget_complete else [],
        ),
        _section_payload(
            section_id="priorities",
            complete=priorities_complete,
            partial=priorities_complete,
            detail=_format_priority_detail(resolved),
            required=False,
        ),
    ]

    completed_count = sum(1 for section in sections if section["status"] == "complete")
    blocking_missing = [section["label"] for section in sections if section["required"] and section["status"] != "complete"]
    advisory_missing = [section["label"] for section in sections if not section["required"] and section["status"] == "missing"]
    next_prompts = _build_next_prompts(resolved, active_conflicts)

    readiness_label = "ready_for_confirmation" if not blocking_missing and not active_conflicts else "needs_clarification"

    return {
        "readiness_label": readiness_label,
        "readiness_text": READINESS_LABELS[readiness_label],
        "completion_ratio": round(completed_count / len(sections), 2),
        "completed_sections": completed_count,
        "total_sections": len(sections),
        "blocking_missing": blocking_missing,
        "advisory_missing": advisory_missing,
        "next_questions": [prompt["question"] for prompt in next_prompts],
        "next_prompts": next_prompts,
        "conflicts": active_conflicts,
        "sections": sections,
        "summary": {
            "project_type": humanize_project_type(project_type) if project_type else None,
            "project_mode": PROJECT_MODE_LABELS.get(resolved.get("project_mode"), resolved.get("project_mode")),
            "site": _format_site_detail(resolved),
            "program": _format_program_detail(resolved),
            "lifestyle": _format_lifestyle_detail(resolved),
            "design_direction": _format_design_detail(resolved),
            "budget": _format_currency(resolved.get("budget_vnd")),
            "timeline": f"{resolved['timeline_months']} tháng" if resolved.get("timeline_months") else None,
            "must_haves": list(resolved.get("must_haves") or []),
            "must_not_haves": list(resolved.get("must_not_haves") or []),
            "special_requests": [humanize_special_request(item) for item in resolved.get("special_requests") or []],
            "design_goals": list(resolved.get("design_goals") or []),
            "space_requests": list(resolved.get("space_requests") or []),
            "spatial_preferences": list(resolved.get("spatial_preferences") or []),
        },
    }


def missing_brief_fields(brief: dict | None, conflicts: list[dict[str, str]] | None = None) -> list[str]:
    state = build_clarification_state(brief, conflicts)
    return state["blocking_missing"] + state["advisory_missing"]


def build_assistant_payload(message: str, analysis: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    captured_facts = analysis.get("captured_facts") or []
    conflicts = state.get("conflicts") or []
    readiness_label = state["readiness_label"]

    if conflicts:
        headline = "Mình cần chốt lại đúng brief trước khi đi tiếp"
        lead = "Tin nhắn mới đang làm lệch ngữ cảnh dự án, nên mình ưu tiên khóa lại brief đang theo trước khi hỏi thêm."
    elif readiness_label == "ready_for_confirmation":
        headline = "Brief đã đủ để rà soát và xác nhận"
        lead = "Mình đã gom đủ các dữ liệu cốt lõi. Anh/chị chỉ cần rà lại tóm tắt dưới đây trước khi chốt brief."
    else:
        headline = "Mình đã cập nhật brief"
        lead = "Mình đã ghi nhận các ý chính mới và giữ lại những phần còn thiếu cần hỏi tiếp theo đúng thứ tự ưu tiên."

    closing = (
        "Anh/chị có thể trả lời ngắn từng ý, mình sẽ cập nhật ngay vào brief."
        if readiness_label != "ready_for_confirmation"
        else "Nếu nội dung này đã đúng, anh/chị có thể xác nhận brief để chuyển sang bước phương án."
    )

    return {
        "headline": headline,
        "lead": lead,
        "captured_facts": captured_facts[:6],
        "summary_cards": [
            {"label": "Loại công trình", "value": state["summary"].get("project_type")},
            {"label": "Quy mô / hiện trạng", "value": state["summary"].get("site")},
            {"label": "Công năng", "value": state["summary"].get("program")},
            {"label": "Định hướng", "value": state["summary"].get("design_direction")},
            {"label": "Ngân sách", "value": state["summary"].get("budget")},
            {"label": "Tiến độ", "value": state["summary"].get("timeline")},
        ],
        "conflicts": conflicts,
        "next_prompts": state.get("next_prompts", []),
        "closing": closing,
    }


def render_assistant_response(payload: dict[str, Any]) -> str:
    lines = [f"**{payload['headline']}**", "", payload["lead"]]

    captured_facts = [fact for fact in payload.get("captured_facts", []) if fact.get("value")]
    if captured_facts:
        lines.extend(["", "Đã ghi nhận trong lượt này:"])
        lines.extend(f"- **{fact['label']}**: {fact['value']}" for fact in captured_facts)

    summary_cards = [card for card in payload.get("summary_cards", []) if card.get("value")]
    if summary_cards:
        lines.extend(["", "Tóm tắt brief đang hoạt động:"])
        lines.extend(f"- **{card['label']}**: {card['value']}" for card in summary_cards[:5])

    conflicts = payload.get("conflicts") or []
    if conflicts:
        lines.extend(["", "Điểm cần xác nhận lại:"])
        lines.extend(f"- **{item['title']}**: {item['detail']}" for item in conflicts)

    prompts = payload.get("next_prompts") or []
    if prompts:
        lines.extend(["", "Mình cần chốt tiếp các ý sau:"])
        lines.extend(f"{index}. {prompt['question']}" for index, prompt in enumerate(prompts, start=1))

    lines.extend(["", payload["closing"]])
    return "\n".join(lines).strip()


def parse_message_to_brief(message: str, existing: dict | None = None) -> dict:
    return analyze_message_to_brief(message, existing)["brief_json"]


def generate_ai_follow_up(brief: dict | None, conflicts: list[dict[str, str]] | None = None) -> tuple[str, bool]:
    state = build_clarification_state(brief, conflicts)
    payload = build_assistant_payload("", {"captured_facts": [], "conflicts": conflicts or []}, state)
    return render_assistant_response(payload), state["readiness_label"] != "ready_for_confirmation"
