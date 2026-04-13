from __future__ import annotations

from typing import Any


STRATEGY_LIBRARY: dict[str, dict[str, Any]] = {
    "daylight_first": {
        "strategy_family": "space_quality",
        "title_vi": "Ưu tiên lấy sáng",
        "summary_vi": "Mở mặt thoáng và ưu tiên không gian sinh hoạt ở các vùng nhận sáng tốt hơn.",
        "differentiators": ["void_or_lightwell_priority", "front_and_rear_openings", "public_space_near_daylight"],
        "rule_overrides": {"building_depth_factor": 0.82, "front_zone_shift": -0.02, "core_zone_shift": -0.01, "x_split": 0.6},
        "fit_conditions": ["daylight_priority_present", "lot_depth_gte_16m"],
        "compare_axes": ["daylight", "openness", "circulation"],
        "strengths": [
            "Không gian sinh hoạt chung sáng và thoáng hơn.",
            "Tăng cảm giác rộng cho khu vực sử dụng chính.",
            "Hợp với nhà phố cần cải thiện độ sáng vùng giữa nhà.",
        ],
        "caveats": [
            "Cần kiểm soát nắng và riêng tư ở các mặt mở lớn.",
            "Một số diện tích kín cho kho hoặc phòng phụ có thể giảm.",
        ],
    },
    "privacy_first": {
        "strategy_family": "zoning",
        "title_vi": "Ưu tiên riêng tư",
        "summary_vi": "Tăng độ tách bạch giữa khu sinh hoạt chung và các không gian riêng tư.",
        "differentiators": ["buffered_entry", "private_rooms_deeper_in_plan", "compact_openings"],
        "rule_overrides": {"building_depth_factor": 0.88, "front_zone_shift": 0.015, "core_zone_shift": 0.01, "x_split": 0.54},
        "fit_conditions": ["multi_generation", "privacy_priority_present"],
        "compare_axes": ["privacy", "zoning", "circulation"],
        "strengths": [
            "Phân khu công cộng và riêng tư rõ hơn.",
            "Giảm nhìn xuyên từ ngoài vào các phòng riêng.",
            "Phù hợp gia đình nhiều thế hệ hoặc cần kiểm soát tiếng ồn.",
        ],
        "caveats": [
            "Không gian sinh hoạt chung có thể bớt mở hơn.",
            "Luồng đi lại có thể cần thêm vùng đệm hoặc hành lang.",
        ],
    },
    "garage_priority": {
        "strategy_family": "access",
        "title_vi": "Ưu tiên gara",
        "summary_vi": "Nhường nhiều ưu tiên cho gara và luồng vào nhà ngay từ tầng trệt.",
        "differentiators": ["expanded_front_zone", "vehicle_access_priority", "service_core_compact"],
        "rule_overrides": {"building_depth_factor": 0.87, "front_zone_shift": 0.03, "core_zone_shift": -0.005, "x_split": 0.62},
        "fit_conditions": ["garage_required"],
        "compare_axes": ["garage_layout", "circulation", "public_space"],
        "strengths": [
            "Gara thuận thao tác và rõ lối tiếp cận.",
            "Tầng trệt xử lý luồng xe và luồng người mạch lạc hơn.",
            "Phù hợp nhà phố hoặc shophouse cần chỗ đậu xe rõ ràng.",
        ],
        "caveats": [
            "Khu sinh hoạt tầng trệt có thể phải nhường diện tích.",
            "Mặt tiền cần cân đối giữa cửa xe và tính thẩm mỹ.",
        ],
    },
    "garden_priority": {
        "strategy_family": "site_relationship",
        "title_vi": "Ưu tiên sân vườn",
        "summary_vi": "Giữ nhiều khoảng trống hơn cho sân vườn và sự liên hệ giữa nhà với cảnh quan.",
        "differentiators": ["larger_front_back_buffers", "shallower_building_mass", "landscape_connection"],
        "rule_overrides": {"building_depth_factor": 0.78, "front_zone_shift": -0.015, "core_zone_shift": -0.005, "x_split": 0.58},
        "fit_conditions": ["villa_typology", "garden_priority_present"],
        "compare_axes": ["garden_connection", "daylight", "mass_distribution"],
        "strengths": [
            "Tăng chất lượng không gian mở và khoảng thở quanh nhà.",
            "Hợp biệt thự hoặc công trình ưu tiên trải nghiệm sân vườn.",
            "Tạo cảm giác ở rộng và thoáng hơn.",
        ],
        "caveats": [
            "Tổng diện tích sàn hữu dụng có thể giảm.",
            "Cần khu đất đủ sâu hoặc đủ rộng để phát huy hiệu quả.",
        ],
    },
    "multi_generation_separation": {
        "strategy_family": "household",
        "title_vi": "Tách lớp đa thế hệ",
        "summary_vi": "Ưu tiên phân tầng và tách lớp sử dụng cho gia đình nhiều thế hệ.",
        "differentiators": ["elder_room_priority", "zoned_household_stack", "clear_shared_private_split"],
        "rule_overrides": {"building_depth_factor": 0.85, "front_zone_shift": 0.01, "core_zone_shift": 0.015, "x_split": 0.57},
        "fit_conditions": ["multi_generation"],
        "compare_axes": ["privacy", "household_fit", "circulation"],
        "strengths": [
            "Phù hợp hơn cho gia đình nhiều thế hệ cùng ở.",
            "Giảm xung đột giữa không gian chung và không gian cần yên tĩnh.",
            "Dễ bố trí phòng cho người lớn tuổi hoặc khu riêng biệt hơn.",
        ],
        "caveats": [
            "Tổ chức mặt bằng phức tạp hơn phương án tập trung.",
            "Một số không gian có thể ít linh hoạt hơn nếu quy mô gia đình đổi.",
        ],
    },
    "storage_efficiency": {
        "strategy_family": "efficiency",
        "title_vi": "Ưu tiên lưu trữ",
        "summary_vi": "Tăng hiệu quả lưu trữ và gom các không gian phụ trợ gọn hơn trong mặt bằng.",
        "differentiators": ["compact_service_core", "storage_edges", "efficient_room_distribution"],
        "rule_overrides": {"building_depth_factor": 0.86, "front_zone_shift": 0.0, "core_zone_shift": 0.02, "x_split": 0.55},
        "fit_conditions": ["storage_priority_present"],
        "compare_axes": ["storage", "efficiency", "circulation"],
        "strengths": [
            "Khai thác diện tích gọn và thực dụng hơn.",
            "Phù hợp cải tạo căn hộ hoặc công trình diện tích hạn chế.",
            "Giảm diện tích chết trong lõi giao thông và khu phụ.",
        ],
        "caveats": [
            "Ít tạo cảm giác mở bằng phương án ưu tiên không gian.",
            "Cần kiểm soát để mặt bằng không trở nên quá chặt.",
        ],
    },
    "family_flow": {
        "strategy_family": "living_pattern",
        "title_vi": "Ưu tiên sinh hoạt gia đình",
        "summary_vi": "Tập trung vào luồng sinh hoạt hằng ngày giữa bếp, ăn, khách và các phòng ngủ.",
        "differentiators": ["shared_core", "family_adjacent_spaces", "balanced_private_access"],
        "rule_overrides": {"building_depth_factor": 0.84, "front_zone_shift": -0.01, "core_zone_shift": 0.0, "x_split": 0.56},
        "fit_conditions": ["family_with_kids", "family_priority_present"],
        "compare_axes": ["family_flow", "circulation", "shared_space"],
        "strengths": [
            "Luồng sử dụng hằng ngày trực quan và dễ ở hơn.",
            "Kết nối tốt giữa khu chung và khu nghỉ.",
            "Phù hợp công trình phục vụ gia đình ở ổn định lâu dài.",
        ],
        "caveats": [
            "Mức độ tách biệt từng khu chức năng có thể không cao bằng phương án ưu tiên riêng tư.",
        ],
    },
    "mixed_use_zoning": {
        "strategy_family": "mixed_use",
        "title_vi": "Phân khu mixed-use",
        "summary_vi": "Ưu tiên tách lớp thương mại và ở, giữ luồng riêng giữa khu khách và khu sinh hoạt.",
        "differentiators": ["commercial_frontage", "separate_residential_access", "buffered_mixed_use_core"],
        "rule_overrides": {"building_depth_factor": 0.9, "front_zone_shift": 0.035, "core_zone_shift": 0.01, "x_split": 0.59},
        "fit_conditions": ["shophouse_typology"],
        "compare_axes": ["mixed_use_zoning", "privacy", "frontage_use"],
        "strengths": [
            "Rõ hơn giữa vùng đón khách và vùng ở.",
            "Hợp shophouse cần dùng tầng trệt linh hoạt.",
            "Tăng cảm giác chuyên nghiệp cho mặt bằng mixed-use.",
        ],
        "caveats": [
            "Cần kiểm soát kỹ giao cắt giữa luồng kinh doanh và luồng gia đình.",
        ],
    },
    "work_life_separation": {
        "strategy_family": "hybrid_use",
        "title_vi": "Tách làm việc và sinh hoạt",
        "summary_vi": "Ưu tiên giảm xung đột giữa khu làm việc và khu ở trong công trình hybrid.",
        "differentiators": ["separate_entry_logic", "work_zone_buffer", "hybrid_stack"],
        "rule_overrides": {"building_depth_factor": 0.88, "front_zone_shift": 0.02, "core_zone_shift": 0.005, "x_split": 0.6},
        "fit_conditions": ["home_office_typology"],
        "compare_axes": ["work_life_split", "client_access", "privacy"],
        "strengths": [
            "Khu làm việc chuyên biệt hơn mà vẫn giữ được sự riêng tư cho phần ở.",
            "Phù hợp công trình nhà kết hợp văn phòng hoặc studio tại nhà.",
        ],
        "caveats": [
            "Một số diện tích phải nhường cho vùng đệm hoặc lối vào riêng.",
        ],
    },
    "client_access_priority": {
        "strategy_family": "hybrid_use",
        "title_vi": "Ưu tiên tiếp khách",
        "summary_vi": "Tập trung tối ưu lối vào, khu tiếp khách và trải nghiệm tiếp cận cho đối tượng bên ngoài.",
        "differentiators": ["entry_emphasis", "meeting_zone_front", "controlled_private_threshold"],
        "rule_overrides": {"building_depth_factor": 0.89, "front_zone_shift": 0.025, "core_zone_shift": -0.005, "x_split": 0.61},
        "fit_conditions": ["client_facing_use"],
        "compare_axes": ["client_access", "frontage_use", "privacy"],
        "strengths": [
            "Phù hợp công trình có khách ra vào thường xuyên.",
            "Tạo cảm giác tiếp cận chuyên nghiệp hơn ở mặt tiền và tầng đầu.",
        ],
        "caveats": [
            "Khu ở có thể phải lùi sâu hơn để giữ riêng tư.",
        ],
    },
}

TYPOLOGY_DEFAULTS = {
    "townhouse": ["daylight_first", "privacy_first", "garage_priority"],
    "villa": ["garden_priority", "multi_generation_separation", "daylight_first"],
    "apartment_reno": ["storage_efficiency", "family_flow", "daylight_first"],
    "shophouse": ["mixed_use_zoning", "privacy_first", "garage_priority"],
    "home_office": ["work_life_separation", "client_access_priority", "daylight_first"],
}


def _text_blob(brief: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("household_profile", "material_direction", "color_direction", "renovation_scope"):
        if brief.get(key):
            parts.append(str(brief[key]))
    for key in ("must_haves", "must_not_haves", "design_goals", "space_requests", "spatial_preferences"):
        values = brief.get(key) or []
        if isinstance(values, list):
            parts.extend(str(item) for item in values)
    return " ".join(parts).lower()


def build_program_synthesis(brief: dict[str, Any]) -> dict[str, Any]:
    lot = dict(brief.get("lot") or {})
    text_blob = _text_blob(brief)
    priorities: list[str] = []
    special_requests = [str(item) for item in brief.get("special_requests") or []]
    must_haves = [str(item) for item in brief.get("must_haves") or []]

    if "garage" in special_requests or "gara" in text_blob:
        priorities.append("garage")
    if "skylight" in special_requests or "anh sang" in text_blob or "ánh sáng" in text_blob:
        priorities.append("daylight")
    if "garden" in special_requests or "san vuon" in text_blob or "sân vườn" in text_blob:
        priorities.append("garden")
    if "3 thế hệ" in text_blob or "3 the he" in text_blob or "người lớn tuổi" in text_blob or "elder" in text_blob:
        priorities.append("multi_generation")
    if "lưu trữ" in text_blob or "luu tru" in text_blob:
        priorities.append("storage")
    if brief.get("project_type") == "home_office":
        priorities.append("client_access")

    required_spaces = ["living_room", "kitchen"]
    if "garage" in special_requests or "garage" in priorities:
        required_spaces.append("garage")
    if "prayer_room" in special_requests:
        required_spaces.append("prayer_room")
    if brief.get("project_type") == "home_office":
        required_spaces.append("work_zone")
    if brief.get("project_type") == "shophouse":
        required_spaces.append("frontage_commercial_zone")

    special_constraints: list[str] = []
    if "multi_generation" in priorities:
        special_constraints.append("ground_floor_elder_room")
    if brief.get("project_type") == "shophouse":
        special_constraints.append("separate_residential_access")
    if brief.get("project_type") == "home_office":
        special_constraints.append("work_life_split")

    return {
        "typology": str(brief.get("project_type") or "townhouse"),
        "project_mode": str(brief.get("project_mode") or "new_build"),
        "household_profile": str(brief.get("household_profile") or ""),
        "priority_tags": priorities,
        "required_spaces": required_spaces,
        "special_constraints": special_constraints,
        "lot_snapshot": {
            "width_m": lot.get("width_m"),
            "depth_m": lot.get("depth_m"),
            "area_m2": lot.get("area_m2"),
            "orientation": lot.get("orientation"),
        },
        "must_haves": must_haves,
    }


def _choose_strategy_keys(program_synthesis: dict[str, Any], num_options: int) -> list[str]:
    typology = str(program_synthesis.get("typology") or "townhouse")
    selected = list(TYPOLOGY_DEFAULTS.get(typology, TYPOLOGY_DEFAULTS["townhouse"]))
    priorities = set(str(item) for item in program_synthesis.get("priority_tags") or [])

    if "garage" in priorities and "garage_priority" not in selected:
        selected[0] = "garage_priority"
    if "garden" in priorities and typology == "villa":
        selected[0] = "garden_priority"
    if "multi_generation" in priorities and "multi_generation_separation" not in selected:
        selected[1] = "multi_generation_separation"
    if "storage" in priorities and typology == "apartment_reno":
        selected[0] = "storage_efficiency"
    if "client_access" in priorities and typology == "home_office":
        selected[1] = "client_access_priority"
    if "daylight" in priorities and "daylight_first" not in selected:
        selected[-1] = "daylight_first"

    unique: list[str] = []
    for key in selected:
        if key not in unique:
            unique.append(key)
    if len(unique) < num_options:
        for fallback in STRATEGY_LIBRARY:
            if fallback not in unique:
                unique.append(fallback)
            if len(unique) >= num_options:
                break
    return unique[:num_options]


def resolve_option_strategy_profiles(
    brief: dict[str, Any],
    program_synthesis: dict[str, Any],
    num_options: int = 3,
) -> list[dict[str, Any]]:
    strategy_keys = _choose_strategy_keys(program_synthesis, num_options)
    profiles: list[dict[str, Any]] = []

    for index, strategy_key in enumerate(strategy_keys):
        base = dict(STRATEGY_LIBRARY[strategy_key])
        profiles.append(
            {
                "strategy_key": strategy_key,
                "strategy_family": base["strategy_family"],
                "title_vi": base["title_vi"],
                "summary_vi": base["summary_vi"],
                "differentiators": list(base["differentiators"]),
                "rule_overrides": dict(base["rule_overrides"]),
                "fit_conditions": list(base.get("fit_conditions") or []),
                "compare_axes": list(base.get("compare_axes") or []),
                "strengths": list(base.get("strengths") or []),
                "caveats": list(base.get("caveats") or []),
                "confidence": "high" if len(program_synthesis.get("priority_tags") or []) >= 1 else "medium",
                "generation_source": "rule_based_phase5",
                "option_index": index,
                "typology": str(brief.get("project_type") or program_synthesis.get("typology") or "townhouse"),
            }
        )

    return profiles

