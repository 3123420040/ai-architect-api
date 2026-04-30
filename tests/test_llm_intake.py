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


def _json_blob(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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
    trace = turn["harness_trace"]
    assert trace["source"] == llm.LLM_SOURCE
    assert trace["provider_family"] == "openai_compat"
    assert trace["model"] == "kts"
    assert trace["prompt_id"] == "intake_structured_extraction_v1"
    assert trace["recent_history_count"] == 0
    assert trace["llm_response_byte_count"] > 0
    assert "project_type" in trace["parsed_payload_summary"]["brief_patch_keys"]
    assert "lot.width_m" in trace["merged_brief_changed_keys"]
    assert any(gate["name"] == "json_parse" and gate["status"] == "pass" for gate in trace["validation_gates"])
    assert turn["assistant_payload"]["source_metadata"]["trace_summary"] == trace
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
    trace = turn["harness_trace"]
    assert trace["source"] == llm.FALLBACK_SOURCE
    assert trace["fallback_reason"] == "invalid_json_after_retry"
    assert trace["llm_response_byte_count"] > 0
    assert any(gate["name"] == "json_parse_retry" and gate["status"] == "fail" for gate in trace["validation_gates"])
    assert "lot.width_m" in trace["merged_brief_changed_keys"]


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
    assert any(
        gate["name"] == "json_parse_retry" and gate["status"] == "pass"
        for gate in turn["harness_trace"]["validation_gates"]
    )


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
    trace = turn["harness_trace"]
    assert trace["source"] == llm.DETERMINISTIC_SOURCE
    assert trace["provider_family"] == "none"
    assert trace["model"] is None
    assert trace["llm_response_byte_count"] is None
    assert trace["parsed_payload_summary"] == {}
    assert "lot.width_m" in trace["merged_brief_changed_keys"]
    assert turn["assistant_payload"]["source_metadata"]["trace_summary"] == trace


def test_harness_trace_redacts_secret_like_values(monkeypatch):
    secret = "sk-liveSECRET123456"
    monkeypatch.setattr(llm.settings, "openai_compat_base_url", "https://llm.example.test/v1")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", secret)
    monkeypatch.setattr(llm.settings, "openai_compat_model", "kts")

    def fake_post(messages):
        raise RuntimeError(f"Authorization: Bearer {secret}; api_key={secret}; token=abc123SECRET")

    monkeypatch.setattr(llm, "_post_openai_compat", fake_post)
    turn = llm.generate_intake_turn("Nhà phố 5x20m, token=abc123SECRET", {}, [])
    persisted_blob = _json_blob(
        {
            "harness_trace": turn["harness_trace"],
            "source_metadata": turn["assistant_payload"]["source_metadata"],
        }
    )

    assert secret not in persisted_blob
    assert "Authorization: Bearer sk-liveSECRET123456" not in persisted_blob
    assert "token=abc123SECRET" not in persisted_blob
    assert "[REDACTED_SECRET]" in persisted_blob
