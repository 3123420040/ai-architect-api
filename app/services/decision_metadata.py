from __future__ import annotations

from typing import Any


def _contains_list_value(values: list[str], needle: str) -> bool:
    return any(needle in value.lower() for value in values)


def _build_degraded_reasons(brief: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    lot = brief.get("lot") or {}
    if not brief.get("project_type"):
        reasons.append("missing_project_type")
    if not lot.get("orientation"):
        reasons.append("missing_site_orientation")
    if not (lot.get("width_m") or lot.get("area_m2")):
        reasons.append("missing_site_size")
    rooms = brief.get("rooms") or {}
    if not (rooms.get("bedrooms") or brief.get("space_requests")):
        reasons.append("missing_program_detail")
    return reasons


def _fit_reasons(
    brief: dict[str, Any],
    strategy_profile: dict[str, Any],
    degraded_reasons: list[str],
) -> list[str]:
    lot = brief.get("lot") or {}
    reasons: list[str] = []
    strategy_key = str(strategy_profile.get("strategy_key") or "")
    orientation = str(lot.get("orientation") or "").lower()
    project_type = str(brief.get("project_type") or "")
    special_requests = [str(item) for item in brief.get("special_requests") or []]
    must_haves = [str(item) for item in brief.get("must_haves") or []]
    household = str(brief.get("household_profile") or "")

    if strategy_key == "daylight_first":
        if orientation:
            reasons.append(f"Tận dụng định hướng khu đất tốt hơn cho giải pháp ưu tiên lấy sáng ({orientation}).")
        reasons.append("Phù hợp brief đang ưu tiên cảm giác sáng, thoáng và thông gió hơn.")
    elif strategy_key == "privacy_first":
        reasons.append("Phù hợp nhu cầu tách lớp riêng tư và giảm nhìn xuyên từ ngoài vào.")
    elif strategy_key == "garage_priority":
        reasons.append("Giải pháp này ưu tiên xử lý gara và luồng tiếp cận tầng trệt rõ ràng hơn.")
    elif strategy_key == "garden_priority":
        reasons.append("Phù hợp khi trải nghiệm sân vườn và khoảng thở quanh nhà là ưu tiên lớn.")
    elif strategy_key == "multi_generation_separation":
        reasons.append("Phù hợp hộ gia đình nhiều thế hệ cần tách lớp sử dụng rõ hơn.")
    elif strategy_key == "storage_efficiency":
        reasons.append("Phù hợp brief cần nhiều lưu trữ và tối ưu diện tích hữu dụng.")
    elif strategy_key == "family_flow":
        reasons.append("Tập trung vào luồng sinh hoạt gia đình hằng ngày giữa bếp, ăn và không gian chung.")
    elif strategy_key == "mixed_use_zoning":
        reasons.append("Phù hợp shophouse cần tách lớp thương mại và khu ở rõ ràng hơn.")
    elif strategy_key == "work_life_separation":
        reasons.append("Phù hợp công trình nhà kết hợp làm việc cần giảm xung đột giữa hai luồng sử dụng.")
    elif strategy_key == "client_access_priority":
        reasons.append("Ưu tiên lối vào và trải nghiệm tiếp cận của khách hoặc đối tác bên ngoài.")

    if household:
        reasons.append(f"Đã bám vào bối cảnh sử dụng của hộ gia đình: {household}.")
    if "garage" in special_requests or _contains_list_value(must_haves, "gara"):
        reasons.append("Brief có yêu cầu gara nên phương án được cân đối theo luồng xe và luồng người.")
    if degraded_reasons:
        reasons.append("Một phần giải thích đang ở chế độ suy giảm vì brief vẫn còn dữ liệu chưa đủ khóa chặt.")

    return reasons[:3]


def _metrics(brief: dict[str, Any], geometry_summary: dict[str, Any]) -> dict[str, Any]:
    rooms = brief.get("rooms") or {}
    special_requests = [str(item) for item in brief.get("special_requests") or []]
    return {
        "floor_count": int(geometry_summary.get("levels") or brief.get("floors") or 0),
        "bedroom_count": int(rooms.get("bedrooms") or 0),
        "wc_count": int(rooms.get("bathrooms") or 0),
        "parking_count": 1 if "garage" in special_requests else 0,
        "estimated_gfa_m2": float(geometry_summary.get("total_floor_area_m2") or 0),
    }


def build_decision_metadata(
    brief: dict[str, Any],
    geometry_summary: dict[str, Any],
    strategy_profile: dict[str, Any],
) -> dict[str, Any]:
    degraded_reasons = _build_degraded_reasons(brief)
    degraded = len(degraded_reasons) > 0
    strategy_title = str(strategy_profile.get("title_vi") or "Phương án")
    strategy_summary = str(strategy_profile.get("summary_vi") or "Phương án đang được dựng theo chiến lược rule-based.")

    strengths = list(strategy_profile.get("strengths") or [])[:3]
    caveats = list(strategy_profile.get("caveats") or [])[:2]
    fit_reasons = _fit_reasons(brief, strategy_profile, degraded_reasons)
    metrics = _metrics(brief, geometry_summary)

    return {
        "option_title_vi": f"Phương án {strategy_title.lower()}",
        "option_summary_vi": strategy_summary,
        "fit_reasons": fit_reasons,
        "strengths": strengths,
        "caveats": caveats,
        "metrics": metrics,
        "quality_flags": {
            "brief_fit": "medium" if degraded else "good",
            "assumption_risk": "medium" if degraded else "low",
            "presentation_confidence": "medium" if degraded else "high",
        },
        "compare_axes": list(strategy_profile.get("compare_axes") or []),
        "degraded": degraded,
        "degraded_reasons": degraded_reasons,
    }
