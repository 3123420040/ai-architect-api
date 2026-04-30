from __future__ import annotations

import json

from app.services import llm


def _configure_llm(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "openai_compat_base_url", "https://llm.example.test/v1")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "sk-test")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "kts")


def _disable_llm(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "openai_compat_base_url", "")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "kts")


def _chat_response(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def test_llm_is_configured_requires_base_url_key_and_model(monkeypatch):
    _disable_llm(monkeypatch)
    assert llm.llm_is_configured() is False

    _configure_llm(monkeypatch)
    assert llm.llm_is_configured() is True


def test_generate_intake_turn_uses_llm_patch_when_configured(monkeypatch):
    _configure_llm(monkeypatch)

    def fake_post(messages):
        assert messages[0]["role"] == "system"
        assert "intake extraction" in messages[0]["content"]
        assert "latest_user_message" in messages[1]["content"]
        return _chat_response(
            {
                "brief_patch": {
                    "project_type": "villa",
                    "location": "Lâm Đồng",
                    "lot": {
                        "width_m": 10,
                        "depth_m": 11,
                        "area_m2": 200,
                        "buildable_area_m2": 110,
                    },
                    "floors": 2,
                    "rooms": {"bedrooms": 3, "bathrooms": 2, "workspaces": 1},
                    "space_requests": ["Phòng đọc", "Phòng làm việc riêng"],
                    "design_goals": ["Thiết kế xanh, gần gũi tự nhiên"],
                },
                "captured_facts": [
                    {"key": "bathrooms", "label": "WC", "value": "2 WC"},
                    {"key": "buildable_area", "label": "Diện tích xây dựng", "value": "110 m²"},
                ],
                "conflicts": [],
                "confidence": 0.86,
            }
        )

    monkeypatch.setattr(llm, "_post_openai_compat", fake_post)
    turn = llm.generate_intake_turn(
        "nhà vườn ở Lâm Đồng, diện tích tổng 200 m2, diện tích xây dựng 110 m2, 10*11, 2 lầu, 3 phòng ngủ, 2 nhà vệ sinh, phòng đọc và làm việc riêng",
        {},
        [],
    )

    brief = turn["brief_json"]
    assert turn["source"] == llm.LLM_SOURCE
    assert turn["assistant_payload"]["source_metadata"]["model"] == "kts"
    assert brief["project_type"] == "villa"
    assert brief["location"] == "Lâm Đồng"
    assert brief["lot"]["buildable_area_m2"] == 110
    assert brief["rooms"]["bathrooms"] == 2
    assert "Phòng đọc" in brief["space_requests"]
    assert "Phòng làm việc riêng" in brief["space_requests"]


def test_generate_intake_turn_falls_back_when_llm_output_is_invalid(monkeypatch):
    _configure_llm(monkeypatch)
    monkeypatch.setattr(llm, "_post_openai_compat", lambda messages: {"choices": [{"message": {"content": "not json"}}]})

    turn = llm.generate_intake_turn("Nhà phố 5x20m, 3 tầng, 4 phòng ngủ, 3 WC", {}, [])

    assert turn["source"] == llm.FALLBACK_SOURCE
    assert turn["brief_json"]["lot"]["width_m"] == 5
    assert turn["brief_json"]["rooms"]["bathrooms"] == 3
    assert "fallback_reason" in turn["assistant_payload"]["source_metadata"]


def test_generate_intake_turn_retries_non_json_llm_output_once(monkeypatch):
    _configure_llm(monkeypatch)
    calls: list[list[dict[str, str]]] = []

    def fake_post(messages):
        calls.append(messages)
        if len(calls) == 1:
            return {"choices": [{"message": {"content": "Mình đã hiểu brief, dưới đây là JSON:"}}]}
        return _chat_response(
            {
                "brief_patch": {
                    "project_type": "villa",
                    "rooms": {"bathrooms": 2},
                },
                "captured_facts": [{"key": "bathrooms", "label": "WC", "value": "2 WC"}],
                "conflicts": [],
                "confidence": 0.7,
            }
        )

    monkeypatch.setattr(llm, "_post_openai_compat", fake_post)
    turn = llm.generate_intake_turn("Nhà vườn có 2 WC", {}, [])

    assert len(calls) == 2
    assert "Return ONLY the JSON object" in calls[1][-1]["content"]
    assert turn["source"] == llm.LLM_SOURCE
    assert turn["brief_json"]["project_type"] == "villa"
    assert turn["brief_json"]["rooms"]["bathrooms"] == 2


def test_llm_patch_drops_unsafe_and_unknown_fields(monkeypatch):
    _configure_llm(monkeypatch)
    monkeypatch.setattr(
        llm,
        "_post_openai_compat",
        lambda messages: _chat_response(
            {
                "brief_patch": {
                    "project_type": "townhouse",
                    "construction_ready": True,
                    "permit_ready": True,
                    "lot": {"width_m": 5, "depth_m": 20, "legal_compliant": True},
                    "unknown": "drop me",
                },
                "captured_facts": [],
                "conflicts": [],
                "confidence": 0.8,
            }
        ),
    )

    turn = llm.generate_intake_turn("Nhà phố 5x20m", {}, [])
    brief = turn["brief_json"]

    assert turn["source"] == llm.LLM_SOURCE
    assert brief["project_type"] == "townhouse"
    assert brief["lot"]["width_m"] == 5
    assert "construction_ready" not in brief
    assert "permit_ready" not in brief
    assert "legal_compliant" not in brief["lot"]
    assert "unknown" not in brief


def test_generate_intake_turn_does_not_call_llm_when_unconfigured(monkeypatch):
    _disable_llm(monkeypatch)

    def fail_if_called(messages):
        raise AssertionError("LLM should not be called without config")

    monkeypatch.setattr(llm, "_post_openai_compat", fail_if_called)
    turn = llm.generate_intake_turn("Nhà phố 5x20m, 3 tầng, 4 phòng ngủ, 3 WC", {}, [])

    assert turn["source"] == llm.DETERMINISTIC_SOURCE
    assert turn["brief_json"]["lot"]["width_m"] == 5
