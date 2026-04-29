from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.design_intelligence.customer_understanding import CustomerUnderstanding
from app.services.professional_deliverables.style_knowledge import StyleKnowledgeBase, StyleProfile, normalize_signal


@dataclass(frozen=True)
class StyleEvidence:
    signal: str
    source: str
    polarity: str = "positive"


@dataclass(frozen=True)
class StyleCandidate:
    style_id: str
    display_name: str
    confidence: float
    evidence: tuple[str, ...]
    source_evidence: tuple[StyleEvidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StyleInferenceResult:
    candidates: tuple[StyleCandidate, ...]
    selected_style_id: str | None
    needs_confirmation: bool
    confirmation_question: str | None

    @property
    def style_candidates(self) -> tuple[StyleCandidate, ...]:
        return self.candidates


def infer_style(
    understanding: CustomerUnderstanding,
    knowledge_base: StyleKnowledgeBase | None = None,
) -> StyleInferenceResult:
    kb = knowledge_base or StyleKnowledgeBase.load_default()
    text_signals = (
        understanding.original_text,
        understanding.normalized_text,
        *understanding.style_signals,
        *understanding.likes,
    )
    image_signals = understanding.image_signals
    candidates: list[StyleCandidate] = []

    for profile in kb.all():
        raw_score, positive_evidence = _score_profile_with_sources(profile, text_signals=text_signals, visual_signals=image_signals)
        dislike_evidence = _dislike_evidence(profile, understanding.dislikes)
        score = 0.0 if dislike_evidence else raw_score
        confidence = _confidence(score, has_image_signals=bool(image_signals))
        all_source_evidence = (*positive_evidence, *dislike_evidence)
        candidates.append(
            StyleCandidate(
                style_id=profile.style_id,
                display_name=profile.display_name,
                confidence=confidence,
                evidence=tuple(dict.fromkeys(_evidence_label(item) for item in all_source_evidence)),
                source_evidence=tuple(dict.fromkeys(all_source_evidence)),
            )
        )

    candidates.sort(key=lambda candidate: (-candidate.confidence, candidate.style_id))
    top = candidates[0] if candidates else None
    runner_up = candidates[1] if len(candidates) > 1 else None
    needs_confirmation = top is None or top.confidence < 0.55 or (runner_up is not None and top.confidence - runner_up.confidence < 0.12)
    selected_style_id = None if needs_confirmation else top.style_id
    return StyleInferenceResult(
        candidates=tuple(candidates),
        selected_style_id=selected_style_id,
        needs_confirmation=needs_confirmation,
        confirmation_question=_confirmation_question(candidates) if needs_confirmation else None,
    )


def _confidence(score: float, *, has_image_signals: bool) -> float:
    if score <= 0:
        return 0.0
    denominator = 8.5 if has_image_signals else 7.5
    return round(min(0.92, score / denominator), 2)


def _score_profile_with_sources(
    profile: StyleProfile,
    *,
    text_signals: list[str] | tuple[str, ...],
    visual_signals: list[str] | tuple[str, ...] = (),
) -> tuple[float, tuple[StyleEvidence, ...]]:
    normalized_text = [normalize_signal(signal) for signal in text_signals if signal]
    normalized_visual = [normalize_signal(signal) for signal in visual_signals if signal]
    evidence: list[StyleEvidence] = []
    score = 0.0

    for signal in profile.normalized_aliases:
        if _any_contains(normalized_text, signal):
            score += 3.0
            evidence.append(StyleEvidence(signal=signal, source="customer_language"))
    for signal in profile.normalized_customer_signals:
        if _any_contains(normalized_text, signal):
            score += 1.7
            evidence.append(StyleEvidence(signal=signal, source="customer_language"))
    for signal in profile.normalized_aliases:
        if _any_contains(normalized_visual, signal):
            score += 2.2
            evidence.append(StyleEvidence(signal=signal, source="reference_image_descriptor"))
    for signal in profile.normalized_visual_signals:
        if _any_contains(normalized_visual, signal):
            score += 1.4
            evidence.append(StyleEvidence(signal=signal, source="reference_image_descriptor"))
    return score, tuple(dict.fromkeys(evidence))


def _dislike_evidence(profile: StyleProfile, dislikes: tuple[str, ...]) -> tuple[StyleEvidence, ...]:
    if not dislikes:
        return ()
    normalized_dislikes = [normalize_signal(dislike) for dislike in dislikes]
    profile_terms = (
        normalize_signal(profile.style_id),
        *profile.normalized_aliases,
        *profile.normalized_customer_signals,
        *profile.normalized_visual_signals,
    )
    matched = tuple(term for term in profile_terms if any(term and _contains(dislike, term) for dislike in normalized_dislikes))
    return tuple(StyleEvidence(signal=term, source="customer_language", polarity="explicit_dislike") for term in dict.fromkeys(matched))


def _confirmation_question(candidates: list[StyleCandidate]) -> str:
    if len(candidates) >= 2 and candidates[0].confidence > 0 and candidates[1].confidence > 0:
        return f"Em đang thấy hai hướng hợp: {candidates[0].display_name} hoặc {candidates[1].display_name}. Anh/chị thích hướng nào hơn?"
    return "Anh/chị thích nhà theo cảm giác xanh mát hiện đại, tối giản ấm, hay Indochine nhẹ hơn?"


def _any_contains(values: list[str], signal: str) -> bool:
    return any(_contains(value, signal) for value in values)


def _contains(value: str, signal: str) -> bool:
    if not signal:
        return False
    return re.search(rf"(?<!\w){re.escape(signal)}(?!\w)", value) is not None


def _evidence_label(evidence: StyleEvidence) -> str:
    if evidence.polarity == "explicit_dislike":
        return f"explicit_dislike:{evidence.signal}"
    return evidence.signal
