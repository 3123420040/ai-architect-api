from __future__ import annotations

from dataclasses import dataclass

from app.services.design_intelligence.customer_understanding import CustomerUnderstanding
from app.services.professional_deliverables.style_knowledge import StyleKnowledgeBase, StyleProfile, normalize_signal


@dataclass(frozen=True)
class StyleCandidate:
    style_id: str
    display_name: str
    confidence: float
    evidence: tuple[str, ...]


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
        raw_score, evidence = kb.score_profile(profile, text_signals=text_signals, visual_signals=image_signals)
        penalty, dislike_evidence = _dislike_penalty(profile, understanding.dislikes)
        score = max(0.0, raw_score - penalty)
        confidence = _confidence(score, has_image_signals=bool(image_signals))
        candidates.append(
            StyleCandidate(
                style_id=profile.style_id,
                display_name=profile.display_name,
                confidence=confidence,
                evidence=tuple(dict.fromkeys((*evidence, *dislike_evidence))),
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
    denominator = 8.0 if has_image_signals else 7.0
    return round(min(0.92, score / denominator), 2)


def _dislike_penalty(profile: StyleProfile, dislikes: tuple[str, ...]) -> tuple[float, tuple[str, ...]]:
    if not dislikes:
        return 0.0, ()
    normalized_dislikes = [normalize_signal(dislike) for dislike in dislikes]
    profile_terms = (
        normalize_signal(profile.style_id),
        *profile.normalized_aliases,
        *profile.normalized_customer_signals,
        *profile.normalized_visual_signals,
    )
    matched = tuple(term for term in profile_terms if any(term and term in dislike for dislike in normalized_dislikes))
    if matched:
        return 4.0, tuple(f"explicit_dislike:{term}" for term in dict.fromkeys(matched))
    return 0.0, ()


def _confirmation_question(candidates: list[StyleCandidate]) -> str:
    if len(candidates) >= 2 and candidates[0].confidence > 0 and candidates[1].confidence > 0:
        return f"Em đang thấy hai hướng hợp: {candidates[0].display_name} hoặc {candidates[1].display_name}. Anh/chị thích hướng nào hơn?"
    return "Anh/chị thích nhà theo cảm giác xanh mát hiện đại, tối giản ấm, hay Indochine nhẹ hơn?"
