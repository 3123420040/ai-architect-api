from __future__ import annotations

from typing import Any

from app.services.design_harness.schemas import (
    HarnessStyleCandidateOutput,
    HarnessStyleToolOutput,
    HarnessToolEvidence,
)
from app.services.design_intelligence.customer_understanding import (
    CustomerUnderstanding,
    ReferenceImageDescriptor,
    parse_customer_understanding,
)
from app.services.design_intelligence.style_inference import (
    StyleCandidate,
    StyleEvidence,
    StyleInferenceResult,
    infer_style,
)
from app.services.professional_deliverables.pattern_memory import ProjectPattern, retrieve_patterns
from app.services.professional_deliverables.style_knowledge import (
    StyleKnowledgeBase,
    StyleProfile,
    normalize_signal,
    profile_dislike_matches,
    profile_reference_descriptor_matches,
)

STYLE_TOOL_SCHEMA_VERSION = "design_harness_style_tools_v1"
SOURCE_CUSTOMER_LANGUAGE = "customer_language"
SOURCE_REFERENCE_DESCRIPTOR = "reference_image_descriptor"
SOURCE_STYLE_PROFILE = "style_profile"
SOURCE_PATTERN_MEMORY = "pattern_memory"
SOURCE_EXPLICIT_DISLIKE = "explicit_dislike"


class DesignHarnessStyleTools:
    def __init__(self, knowledge_base: StyleKnowledgeBase | None = None) -> None:
        self.knowledge_base = knowledge_base or StyleKnowledgeBase.load_default()

    def parse_customer_understanding(
        self,
        message: str,
        *,
        reference_images: list[dict[str, Any] | ReferenceImageDescriptor] | tuple[dict[str, Any] | ReferenceImageDescriptor, ...] | None = None,
    ) -> CustomerUnderstanding:
        return parse_customer_understanding(message, reference_images=reference_images)

    def infer_style(self, understanding: CustomerUnderstanding) -> HarnessStyleToolOutput:
        result = infer_style(understanding, self.knowledge_base)
        return self._style_output(understanding=understanding, result=result)

    def retrieve_style_profile(self, style_id: str | None) -> dict[str, Any] | None:
        if not style_id:
            return None
        profile = self.knowledge_base.get(style_id)
        return _profile_payload(profile)

    def retrieve_pattern_memory(
        self,
        facts: dict[str, Any],
        *,
        style_id: str | None = None,
        limit: int = 3,
    ) -> tuple[dict[str, Any], ...]:
        return tuple(_pattern_payload(pattern) for pattern in retrieve_patterns(facts, style_id=style_id, limit=limit))

    def suppress_disliked_style_features(
        self,
        style_id: str | None,
        dislikes: list[str] | tuple[str, ...],
    ) -> tuple[dict[str, Any], ...]:
        if not style_id or not dislikes:
            return ()
        profile = self.knowledge_base.get(style_id)
        profile_matches = list(profile_dislike_matches(profile, tuple(dislikes)))
        profile_matches.extend(_generic_dislike_suppression(profile, tuple(dislikes), existing=profile_matches))
        return tuple(_with_source_tag(match, SOURCE_EXPLICIT_DISLIKE) for match in profile_matches)

    def run(
        self,
        message: str,
        *,
        brief_json: dict[str, Any] | None = None,
        reference_images: list[dict[str, Any] | ReferenceImageDescriptor] | tuple[dict[str, Any] | ReferenceImageDescriptor, ...] | None = None,
    ) -> HarnessStyleToolOutput:
        descriptors = tuple(reference_images or _reference_descriptors_from_brief(brief_json or {}))
        understanding = self.parse_customer_understanding(message, reference_images=descriptors)
        result = infer_style(understanding, self.knowledge_base)
        selected_style_id = result.selected_style_id
        style_profile = self.retrieve_style_profile(selected_style_id)
        facts = _pattern_facts(understanding)
        pattern_style_id = selected_style_id or _top_candidate_id(result, minimum_confidence=0.45)
        pattern_matches = self.retrieve_pattern_memory(facts, style_id=pattern_style_id)
        dislike_matches = self.suppress_disliked_style_features(selected_style_id or _top_candidate_id(result), understanding.dislikes)
        reference_matches = _reference_matches(self.knowledge_base, selected_style_id, understanding)
        return self._style_output(
            understanding=understanding,
            result=result,
            style_profile=style_profile,
            pattern_memory=pattern_matches,
            dislike_suppression=dislike_matches,
            reference_descriptor_matches=reference_matches,
        )

    def _style_output(
        self,
        *,
        understanding: CustomerUnderstanding,
        result: StyleInferenceResult,
        style_profile: dict[str, Any] | None = None,
        pattern_memory: tuple[dict[str, Any], ...] = (),
        dislike_suppression: tuple[dict[str, Any], ...] = (),
        reference_descriptor_matches: tuple[dict[str, Any], ...] = (),
    ) -> HarnessStyleToolOutput:
        candidates = tuple(_candidate_output(candidate) for candidate in result.candidates)
        evidence = tuple(item for candidate in candidates for item in candidate.evidence)
        evidence = _unique_evidence(
            (
                *evidence,
                *_understanding_evidence(understanding),
                *_tool_payload_evidence(pattern_memory, SOURCE_PATTERN_MEMORY),
                *_tool_payload_evidence(dislike_suppression, SOURCE_EXPLICIT_DISLIKE),
                *_tool_payload_evidence(reference_descriptor_matches, SOURCE_REFERENCE_DESCRIPTOR),
                *_style_profile_evidence(style_profile),
            )
        )
        confidence = candidates[0].confidence if candidates else 0.0
        source_tags = tuple(sorted({item.source_tag for item in evidence}))
        return HarnessStyleToolOutput(
            schema_version=STYLE_TOOL_SCHEMA_VERSION,
            selected_style_id=result.selected_style_id,
            candidates=candidates,
            evidence=evidence,
            source_tags=source_tags,
            confidence=confidence,
            needs_confirmation=result.needs_confirmation,
            confirmation_question=result.confirmation_question,
            customer_understanding=_understanding_payload(understanding),
            style_profile=style_profile,
            pattern_memory=pattern_memory,
            dislike_suppression=dislike_suppression,
            reference_descriptor_matches=reference_descriptor_matches,
        )


def _candidate_output(candidate: StyleCandidate) -> HarnessStyleCandidateOutput:
    return HarnessStyleCandidateOutput(
        style_id=candidate.style_id,
        display_name=candidate.display_name,
        confidence=candidate.confidence,
        evidence=tuple(_style_evidence(item, confidence=candidate.confidence) for item in candidate.source_evidence),
    )


def _style_evidence(evidence: StyleEvidence, *, confidence: float) -> HarnessToolEvidence:
    source_tag = SOURCE_EXPLICIT_DISLIKE if evidence.polarity == SOURCE_EXPLICIT_DISLIKE else evidence.source
    return HarnessToolEvidence(
        signal=evidence.signal,
        source_tag=source_tag,
        polarity=evidence.polarity,
        confidence=confidence,
    )


def _understanding_payload(understanding: CustomerUnderstanding) -> dict[str, Any]:
    return {
        "project_type": understanding.project_type,
        "site_facts": understanding.site_facts,
        "family_lifestyle": understanding.family_lifestyle,
        "room_program_hints": understanding.room_program_hints,
        "style_signals": list(understanding.style_signals),
        "reference_image_descriptors": [_descriptor_payload(descriptor) for descriptor in understanding.reference_images],
        "image_signals": list(understanding.image_signals),
        "likes": list(understanding.likes),
        "dislikes": list(understanding.dislikes),
        "missing_blockers": list(understanding.missing_blockers),
        "assumptions": list(understanding.assumptions),
        "source_tags": _understanding_source_tags(understanding),
        "confidence": 1.0,
    }


def _descriptor_payload(descriptor: ReferenceImageDescriptor) -> dict[str, Any]:
    return {
        "description": descriptor.description,
        "style_hint": descriptor.style_hint,
        "visual_tags": list(descriptor.visual_tags),
        "materials": list(descriptor.materials),
        "colors": list(descriptor.colors),
        "spatial_features": list(descriptor.spatial_features),
        "source_tag": SOURCE_REFERENCE_DESCRIPTOR,
    }


def _profile_payload(profile: StyleProfile) -> dict[str, Any]:
    return {
        "style_id": profile.style_id,
        "display_name": profile.display_name,
        "version": profile.version,
        "aliases": list(profile.aliases),
        "facade_intent": profile.facade_intent,
        "spatial_rules": profile.spatial_rules,
        "room_defaults": profile.room_defaults,
        "opening_rules": profile.opening_rules,
        "default_rules": profile.default_rules,
        "facade_rules": profile.facade_rules,
        "facade_expression": profile.facade_expression,
        "material_palette": profile.material_palette,
        "material_assumptions": list(profile.material_assumptions),
        "drawing_rules": profile.drawing_rules,
        "drawing_notes": list(profile.drawing_notes),
        "avoid_rules": list(profile.avoid_rules),
        "validation_rules": list(profile.validation_rules),
        "explanation": profile.customer_explanation(),
        "source_tag": SOURCE_STYLE_PROFILE,
        "confidence": 1.0,
    }


def _pattern_payload(pattern: ProjectPattern) -> dict[str, Any]:
    return {
        "pattern_id": pattern.pattern_id,
        "name": pattern.name,
        "typology": pattern.typology,
        "style_fit": list(pattern.style_fit),
        "family_program_fit": list(pattern.family_program_fit),
        "stair_lightwell_position": pattern.stair_lightwell_position,
        "room_sequence": list(pattern.room_sequence),
        "facade_strategy": pattern.facade_strategy,
        "known_tradeoffs": list(pattern.known_tradeoffs),
        "feedback_tags": list(pattern.feedback_tags),
        "source_tag": SOURCE_PATTERN_MEMORY,
        "confidence": 0.7,
    }


def _pattern_facts(understanding: CustomerUnderstanding) -> dict[str, Any]:
    facts = {
        **understanding.site_facts,
        **understanding.room_program_hints,
        "occupant_count": understanding.family_lifestyle.get("occupant_count"),
        "occupants": understanding.family_lifestyle.get("occupant_count"),
        "signals": [
            *(understanding.family_lifestyle.get("priorities") or []),
            *(understanding.room_program_hints.get("must_haves") or []),
        ],
    }
    return {key: value for key, value in facts.items() if value not in (None, "", [], ())}


def _reference_descriptors_from_brief(brief_json: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    descriptors: list[dict[str, Any]] = []
    for key in ("reference_images", "reference_image_descriptors", "style_reference_descriptors"):
        descriptors.extend(_dict_items(brief_json.get(key)))
    design_direction = brief_json.get("design_direction")
    if isinstance(design_direction, dict):
        for key in ("reference_images", "reference_image_descriptors", "style_reference_descriptors"):
            descriptors.extend(_dict_items(design_direction.get(key)))
    return tuple(descriptors)


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list | tuple):
        return [item for item in value if isinstance(item, dict)]
    return []


def _top_candidate_id(result: StyleInferenceResult, minimum_confidence: float = 0.0) -> str | None:
    if not result.candidates:
        return None
    top = result.candidates[0]
    return top.style_id if top.confidence >= minimum_confidence else None


def _reference_matches(
    knowledge_base: StyleKnowledgeBase,
    selected_style_id: str | None,
    understanding: CustomerUnderstanding,
) -> tuple[dict[str, Any], ...]:
    if not selected_style_id or not understanding.image_signals:
        return ()
    profile = knowledge_base.get(selected_style_id)
    return tuple(_with_source_tag(match, SOURCE_REFERENCE_DESCRIPTOR) for match in profile_reference_descriptor_matches(profile, understanding.image_signals))


def _generic_dislike_suppression(
    profile: StyleProfile,
    dislikes: tuple[str, ...],
    *,
    existing: list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    normalized = tuple(normalize_signal(item) for item in dislikes if item)
    existing_features = {str(item.get("feature")) for item in existing}
    matches: list[dict[str, Any]] = []
    generic_rules = (
        (
            "cold_dark_palette",
            ("cold dark palette", "cold/dark palette", "palette lanh toi", "mau lanh toi", "tone lanh toi", "toi lanh"),
            "warm neutral base, matte surfaces, and lighter accents",
            "Suppress cold/dark palette cues when the homeowner dislikes them.",
        ),
        (
            "overly_decorative_indochine",
            ("overly decorative indochine", "indochine qua cau ky", "dong duong qua cau ky", "qua nhieu chi tiet dong duong", "too ornate indochine"),
            "restrained Indochine accents with simplified arch/screen moments",
            "Suppress ornate Indochine interpretation and keep heritage cues light.",
        ),
        (
            "high_maintenance_greenery",
            ("high maintenance greenery", "cay can cham nhieu", "cay can bao tri nhieu", "vuon kho cham", "ngai cham cay", "khong muon cham cay"),
            "low-maintenance planters or optional green cues",
            "Suppress maintenance-heavy planting while preserving a lighter green intent if useful.",
        ),
    )
    for feature, keywords, replacement, note in generic_rules:
        if feature in existing_features:
            continue
        matched_terms = tuple(keyword for keyword in keywords if any(_contains_dislike(value, keyword) for value in normalized))
        if not matched_terms:
            continue
        if feature == "overly_decorative_indochine" and profile.style_id != "indochine_soft":
            continue
        matches.append(
            {
                "feature": feature,
                "matched_terms": matched_terms,
                "replacement": replacement,
                "note": note,
                "drawing_note": note,
                "source": SOURCE_EXPLICIT_DISLIKE,
                "style_id": profile.style_id,
                "assumption": True,
            }
        )
    return tuple(matches)


def _contains_dislike(value: str, keyword: str) -> bool:
    normalized_keyword = normalize_signal(keyword)
    return normalized_keyword in value or value in normalized_keyword


def _with_source_tag(payload: dict[str, Any], source_tag: str) -> dict[str, Any]:
    item = dict(payload)
    item["source_tag"] = source_tag
    return item


def _understanding_evidence(understanding: CustomerUnderstanding) -> tuple[HarnessToolEvidence, ...]:
    evidence: list[HarnessToolEvidence] = []
    if understanding.original_text.strip():
        evidence.append(HarnessToolEvidence(signal="homeowner_message", source_tag=SOURCE_CUSTOMER_LANGUAGE, confidence=1.0))
    for signal in understanding.style_signals:
        evidence.append(HarnessToolEvidence(signal=signal, source_tag=SOURCE_CUSTOMER_LANGUAGE, confidence=1.0))
    for signal in understanding.image_signals:
        evidence.append(HarnessToolEvidence(signal=signal, source_tag=SOURCE_REFERENCE_DESCRIPTOR, confidence=1.0))
    for dislike in understanding.dislikes:
        evidence.append(HarnessToolEvidence(signal=dislike, source_tag=SOURCE_EXPLICIT_DISLIKE, polarity=SOURCE_EXPLICIT_DISLIKE, confidence=1.0))
    return tuple(evidence)


def _tool_payload_evidence(payloads: tuple[dict[str, Any], ...], source_tag: str) -> tuple[HarnessToolEvidence, ...]:
    evidence: list[HarnessToolEvidence] = []
    for payload in payloads:
        signal = str(payload.get("feature") or payload.get("pattern_id") or payload.get("name") or "")
        if signal:
            evidence.append(HarnessToolEvidence(signal=signal, source_tag=source_tag, confidence=float(payload.get("confidence") or 0.7)))
        for term in payload.get("matched_terms") or ():
            evidence.append(HarnessToolEvidence(signal=str(term), source_tag=source_tag, confidence=float(payload.get("confidence") or 0.7)))
    return tuple(evidence)


def _style_profile_evidence(style_profile: dict[str, Any] | None) -> tuple[HarnessToolEvidence, ...]:
    if not style_profile:
        return ()
    return (
        HarnessToolEvidence(
            signal=str(style_profile.get("style_id") or ""),
            source_tag=SOURCE_STYLE_PROFILE,
            confidence=float(style_profile.get("confidence") or 1.0),
        ),
    )


def _understanding_source_tags(understanding: CustomerUnderstanding) -> list[str]:
    tags = {SOURCE_CUSTOMER_LANGUAGE}
    if understanding.reference_images or understanding.image_signals:
        tags.add(SOURCE_REFERENCE_DESCRIPTOR)
    if understanding.dislikes:
        tags.add(SOURCE_EXPLICIT_DISLIKE)
    return sorted(tags)


def _unique_evidence(items: tuple[HarnessToolEvidence, ...]) -> tuple[HarnessToolEvidence, ...]:
    deduped: dict[tuple[str, str, str], HarnessToolEvidence] = {}
    for item in items:
        if not item.signal:
            continue
        deduped.setdefault((item.signal, item.source_tag, item.polarity), item)
    return tuple(deduped.values())


def style_tool_output_as_dict(output: HarnessStyleToolOutput) -> dict[str, Any]:
    return output.as_dict()
