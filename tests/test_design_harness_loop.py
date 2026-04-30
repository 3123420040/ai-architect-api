from __future__ import annotations

import json
from typing import Any

from app.schemas import ChatResponse
from app.services import llm
from app.services.design_harness import DesignIntakeHarnessLoop


def _configure_llm(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "openai_compat_base_url", "https://llm.example.test/v1")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "sk-test")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "kts")


def _disable_llm(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "openai_compat_base_url", "")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "kts")


def _chat_response(payload: dict[str, Any]) -> dict[str, Any]:
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


class FakeModelClient:
    def __init__(self) -> None:
        self.contexts: list[dict[str, Any]] = []

    def generate_turn(self, context: dict[str, Any]) -> dict[str, Any]:
        self.contexts.append(context)
        return {
            "assistant_response": "Mình đã ghi nhận nhu cầu nhà phố 5x20m.",
            "assistant_payload": {"summary": "Nhà phố 5x20m"},
            "brief_json": {"project_type": "townhouse", "lot": {"width_m": 5, "depth_m": 20}},
            "needs_follow_up": False,
            "source": "fake_model",
            "follow_up_topics": [],
            "conflicts": [],
            "clarification_state": {"readiness_label": "ready_for_confirmation"},
            "harness_trace": {
                "schema_version": "harness_trace_summary_v1",
                "source": "fake_model",
                "prompt_id": "fake_prompt",
                "validation_gates": [{"name": "fake_tool", "status": "pass"}],
            },
        }


def test_design_harness_loop_accepts_fake_model_without_live_provider():
    fake_model = FakeModelClient()
    result = DesignIntakeHarnessLoop(model_client=fake_model).run(
        "Nhà phố 5x20m",
        {},
        [{"role": "user", "content": "Tôi cần nhà phố"}],
    )

    legacy = result.as_legacy_turn()
    assert fake_model.contexts[0]["history_count"] == 1
    assert result.machine.source == "fake_model"
    assert result.machine.readiness["schema_version"] == "design_harness_readiness_v1"
    assert result.machine.readiness["field_statuses"]["site.width_m"]["status"] == "confirmed"
    assert result.machine.assumptions
    assert legacy["assistant_response"].startswith("Mình đã ghi nhận nhu cầu nhà phố 5x20m.")
    assert legacy["harness"]["harness_id"] == "design_intake_harness"
    assert legacy["harness"]["readiness"]["schema_version"] == "design_harness_readiness_v1"
    assert legacy["harness"]["assumptions"] == result.machine.assumptions
    assert legacy["harness_trace"]["validation_gates"][0]["name"] == "fake_tool"


def test_design_harness_loop_uses_deterministic_unconfigured_path(monkeypatch):
    _disable_llm(monkeypatch)

    def fail_if_called(messages):
        raise AssertionError("LLM should not be called without config")

    monkeypatch.setattr(llm, "_post_openai_compat", fail_if_called)
    result = DesignIntakeHarnessLoop().run("Nhà phố 5x20m, 3 tầng, 4 phòng ngủ, 3 WC", {}, [])

    assert result.source == llm.DETERMINISTIC_SOURCE
    assert result.brief_json["lot"]["width_m"] == 5
    assert result.harness_trace["source"] == llm.DETERMINISTIC_SOURCE
    assert result.harness_trace["provider_family"] == "none"
    assert "lot.width_m" in result.harness_trace["merged_brief_changed_keys"]
    assert result.machine.readiness["field_statuses"]["program.bathrooms"]["status"] == "confirmed"
    assert result.machine.concept_design_input is not None
    assert result.machine.concept_design_input["project"]["concept_only"] is True
    assert result.machine.concept_design_input["project"]["construction_ready"] is False
    assert result.machine.concept_input_validation["status"] == "valid"


def test_design_harness_loop_uses_configured_llm_path(monkeypatch):
    _configure_llm(monkeypatch)

    def fake_post(messages):
        assert messages[0]["role"] == "system"
        assert "latest_user_message" in messages[1]["content"]
        return _chat_response(
            {
                "brief_patch": {
                    "project_type": "villa",
                    "location": "Lâm Đồng",
                    "lot": {"width_m": 10, "depth_m": 11, "buildable_area_m2": 110},
                    "rooms": {"bathrooms": 2, "workspaces": 1},
                },
                "captured_facts": [{"key": "bathrooms", "label": "WC", "value": "2 WC"}],
                "conflicts": [],
                "confidence": 0.86,
            }
        )

    monkeypatch.setattr(llm, "_post_openai_compat", fake_post)
    result = DesignIntakeHarnessLoop().run("Nhà vườn Lâm Đồng 10x11m, xây 110m2, 2 WC", {}, [])

    assert result.source == llm.LLM_SOURCE
    assert result.brief_json["project_type"] == "villa"
    assert result.brief_json["lot"]["buildable_area_m2"] == 110
    assert result.harness_trace["provider_family"] == "openai_compat"
    assert any(gate["name"] == "json_parse" and gate["status"] == "pass" for gate in result.harness_trace["validation_gates"])


def test_design_harness_loop_falls_back_through_harness(monkeypatch):
    _configure_llm(monkeypatch)
    monkeypatch.setattr(llm, "_post_openai_compat", lambda messages: {"choices": [{"message": {"content": "not json"}}]})

    result = DesignIntakeHarnessLoop().run("Nhà phố 5x20m, 3 tầng, 4 phòng ngủ, 3 WC", {}, [])

    assert result.source == llm.FALLBACK_SOURCE
    assert result.brief_json["lot"]["width_m"] == 5
    assert result.harness_trace["source"] == llm.FALLBACK_SOURCE
    assert result.harness_trace["fallback_reason"] == "invalid_json_after_retry"
    assert any(
        gate["name"] == "json_parse_retry" and gate["status"] == "fail"
        for gate in result.harness_trace["validation_gates"]
    )


def test_design_harness_legacy_turn_fits_old_chat_response_contract(monkeypatch):
    _disable_llm(monkeypatch)
    turn = DesignIntakeHarnessLoop().run("Nhà phố 5x20m, 3 tầng, 4 phòng ngủ, 3 WC", {}, []).as_legacy_turn()
    response = ChatResponse(
        session_id="test-session",
        status="processed",
        response=turn["assistant_response"],
        brief_json=turn["brief_json"],
        needs_follow_up=turn["needs_follow_up"],
        follow_up_topics=turn["follow_up_topics"],
        source=turn["source"],
        assistant_payload=turn["assistant_payload"],
        conflicts=turn["conflicts"],
        clarification_state=turn["clarification_state"],
        brief_contract_state="draft",
        brief_contract_label="Đang làm rõ",
        brief_can_lock=False,
        harness=turn["harness"],
    )

    payload = response.model_dump()
    assert "harness_trace" not in payload
    assert payload["response"] == turn["assistant_response"]
    assert payload["brief_json"]["lot"]["width_m"] == 5
    assert payload["harness"]["harness_id"] == "design_intake_harness"
    assert payload["harness"]["readiness"]["schema_version"] == "design_harness_readiness_v1"
    assert payload["harness"]["concept_input_available"] is True
    assert payload["harness"]["concept_design_input"]["schema_version"] == "concept_design_input_v1"
    assert isinstance(payload["harness"]["assumptions"], list)
    assert {
        "session_id",
        "status",
        "response",
        "brief_json",
        "needs_follow_up",
        "follow_up_topics",
        "source",
        "assistant_payload",
        "conflicts",
        "clarification_state",
        "brief_contract_state",
        "brief_contract_label",
        "brief_can_lock",
    } <= set(payload)


def test_design_harness_blocks_concept_input_when_critical_missing(monkeypatch):
    _disable_llm(monkeypatch)
    result = DesignIntakeHarnessLoop().run("Nhà phố 3 tầng, 3 phòng ngủ, 2 WC, phong cách modern", {}, [])

    assert result.machine.concept_design_input is None
    assert result.machine.concept_input_validation["status"] == "blocked"
    assert "site.width_m" in result.machine.concept_input_validation["critical_missing"]
    assert result.as_legacy_turn()["harness"]["concept_input_available"] is False


def test_design_harness_blocks_unsafe_concept_input(monkeypatch):
    _disable_llm(monkeypatch)
    result = DesignIntakeHarnessLoop().run(
        "Nhà phố 5x20m, 3 tầng, 3 phòng ngủ, 3 WC, xác nhận đủ xin phép và thi công.",
        {},
        [],
    )

    assert result.machine.readiness["status"] == "blocked_by_safety_scope"
    assert result.machine.concept_design_input is None
    assert result.machine.concept_input_validation["status"] == "blocked"
