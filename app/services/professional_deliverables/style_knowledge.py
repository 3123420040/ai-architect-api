from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class StyleKnowledgeError(ValueError):
    pass


PROFILE_DIR = Path(__file__).with_name("style_profiles")

REQUIRED_PROFILE_FIELDS = (
    "style_id",
    "display_name",
    "version",
    "aliases",
    "customer_language_signals",
    "visual_signals",
    "spatial_rules",
    "room_defaults",
    "opening_rules",
    "default_rules",
    "facade_intent",
    "facade_rules",
    "facade_expression",
    "material_palette",
    "material_assumptions",
    "drawing_rules",
    "drawing_notes",
    "avoid_rules",
    "dislike_suppression",
    "reference_descriptor_mappings",
    "validation_rules",
    "explanation_templates",
)

UNSAFE_SCOPE_TERMS = (
    "issued " + "for construction",
    "permit " + "approved",
    "structural " + "design",
    "mep " + "design",
    "code " + "compliant",
    "code " + "compliance",
    "construction " + "ready",
    "legal " + "compliance",
    "geotechnical " + "report",
    "permit " + "drawings",
    "ban ve " + "thi cong",
    "ho so " + "xin phep",
    "thiet ke " + "ket cau",
    "thiet ke " + "dien nuoc",
    "bao cao " + "dia chat",
    "phap ly " + "day du",
    "dat " + "quy chuan",
)


def normalize_signal(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.lower()).replace("đ", "d")
    without_marks = "".join(character for character in normalized if unicodedata.category(character) != "Mn")
    return " ".join(without_marks.replace("-", " ").replace("_", " ").split())


def _require_non_empty_sequence(payload: dict[str, Any], field_name: str) -> tuple[str, ...]:
    value = payload.get(field_name)
    if not isinstance(value, list) or not value:
        raise StyleKnowledgeError(f"Style profile {payload.get('style_id') or '<unknown>'} missing {field_name}")
    return tuple(str(item) for item in value if str(item).strip())


def _require_mapping(payload: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = payload.get(field_name)
    if not isinstance(value, dict) or not value:
        raise StyleKnowledgeError(f"Style profile {payload.get('style_id') or '<unknown>'} missing {field_name}")
    return dict(value)


def _require_text(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise StyleKnowledgeError(f"Style profile {payload.get('style_id') or '<unknown>'} missing {field_name}")
    return value


def _assert_safe_scope(payload: dict[str, Any]) -> None:
    searchable = normalize_signal(json.dumps(payload, ensure_ascii=False))
    for term in UNSAFE_SCOPE_TERMS:
        if normalize_signal(term) in searchable:
            raise StyleKnowledgeError(f"Style profile {payload.get('style_id')} contains unsafe scope claim: {term}")


@dataclass(frozen=True)
class StyleProfile:
    style_id: str
    display_name: str
    version: str
    aliases: tuple[str, ...]
    customer_language_signals: tuple[str, ...]
    visual_signals: tuple[str, ...]
    spatial_rules: dict[str, Any]
    room_defaults: dict[str, Any]
    opening_rules: dict[str, Any]
    default_rules: dict[str, Any]
    facade_intent: str
    facade_rules: dict[str, Any]
    facade_expression: dict[str, Any]
    material_palette: dict[str, Any]
    material_assumptions: tuple[str, ...]
    drawing_rules: dict[str, Any]
    drawing_notes: tuple[str, ...]
    avoid_rules: tuple[str, ...]
    dislike_suppression: dict[str, Any]
    reference_descriptor_mappings: dict[str, Any]
    validation_rules: tuple[str, ...]
    explanation_templates: dict[str, str]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StyleProfile:
        missing = [field for field in REQUIRED_PROFILE_FIELDS if field not in payload]
        if missing:
            raise StyleKnowledgeError(f"Style profile missing required fields: {', '.join(missing)}")
        _assert_safe_scope(payload)
        templates = _require_mapping(payload, "explanation_templates")
        return cls(
            style_id=str(payload["style_id"]),
            display_name=str(payload["display_name"]),
            version=str(payload["version"]),
            aliases=_require_non_empty_sequence(payload, "aliases"),
            customer_language_signals=_require_non_empty_sequence(payload, "customer_language_signals"),
            visual_signals=_require_non_empty_sequence(payload, "visual_signals"),
            spatial_rules=_require_mapping(payload, "spatial_rules"),
            room_defaults=_require_mapping(payload, "room_defaults"),
            opening_rules=_require_mapping(payload, "opening_rules"),
            default_rules=_require_mapping(payload, "default_rules"),
            facade_intent=_require_text(payload, "facade_intent"),
            facade_rules=_require_mapping(payload, "facade_rules"),
            facade_expression=_require_mapping(payload, "facade_expression"),
            material_palette=_require_mapping(payload, "material_palette"),
            material_assumptions=_require_non_empty_sequence(payload, "material_assumptions"),
            drawing_rules=_require_mapping(payload, "drawing_rules"),
            drawing_notes=_require_non_empty_sequence(payload, "drawing_notes"),
            avoid_rules=_require_non_empty_sequence(payload, "avoid_rules"),
            dislike_suppression=_require_mapping(payload, "dislike_suppression"),
            reference_descriptor_mappings=_require_mapping(payload, "reference_descriptor_mappings"),
            validation_rules=_require_non_empty_sequence(payload, "validation_rules"),
            explanation_templates={str(key): str(value) for key, value in templates.items()},
        )

    @property
    def normalized_aliases(self) -> tuple[str, ...]:
        return tuple(normalize_signal(alias) for alias in self.aliases)

    @property
    def normalized_customer_signals(self) -> tuple[str, ...]:
        return tuple(normalize_signal(signal) for signal in self.customer_language_signals)

    @property
    def normalized_visual_signals(self) -> tuple[str, ...]:
        return tuple(normalize_signal(signal) for signal in self.visual_signals)

    def matches_identifier(self, value: str) -> bool:
        normalized = normalize_signal(value)
        return normalized == normalize_signal(self.style_id) or normalized in self.normalized_aliases

    def customer_explanation(self, key: str = "style_summary") -> str:
        return self.explanation_templates.get(key) or self.explanation_templates.get("style_summary") or self.display_name


def load_style_profiles(profile_dir: Path | None = None) -> dict[str, StyleProfile]:
    directory = profile_dir or PROFILE_DIR
    if not directory.exists():
        raise StyleKnowledgeError(f"Style profile directory does not exist: {directory}")
    profiles: dict[str, StyleProfile] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        profile = StyleProfile.from_dict(payload)
        if profile.style_id in profiles:
            raise StyleKnowledgeError(f"Duplicate style profile id: {profile.style_id}")
        profiles[profile.style_id] = profile
    if not profiles:
        raise StyleKnowledgeError("No style profiles found")
    return profiles


class StyleKnowledgeBase:
    def __init__(self, profiles: dict[str, StyleProfile] | None = None) -> None:
        self.profiles = profiles or load_style_profiles()

    @classmethod
    def load_default(cls) -> StyleKnowledgeBase:
        return cls(load_style_profiles())

    def get(self, style_id_or_alias: str) -> StyleProfile:
        for profile in self.profiles.values():
            if profile.matches_identifier(style_id_or_alias):
                return profile
        raise StyleKnowledgeError(f"Unknown style profile: {style_id_or_alias}")

    def all(self) -> tuple[StyleProfile, ...]:
        return tuple(self.profiles[style_id] for style_id in sorted(self.profiles))

    def score_profile(self, profile: StyleProfile, *, text_signals: list[str] | tuple[str, ...], visual_signals: list[str] | tuple[str, ...] = ()) -> tuple[float, tuple[str, ...]]:
        normalized_text = [normalize_signal(signal) for signal in text_signals if signal]
        normalized_visual = [normalize_signal(signal) for signal in visual_signals if signal]
        evidence: list[str] = []
        score = 0.0

        for signal in profile.normalized_customer_signals + profile.normalized_aliases:
            if any(signal in text for text in normalized_text):
                score += 2.0
                evidence.append(signal)
        for signal in profile.normalized_visual_signals:
            if any(signal in visual for visual in normalized_visual):
                score += 1.4
                evidence.append(signal)
        return score, tuple(dict.fromkeys(evidence))


def profile_dislike_matches(profile: StyleProfile, dislikes: list[str] | tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    normalized_dislikes = [normalize_signal(dislike) for dislike in dislikes if dislike]
    if not normalized_dislikes:
        return ()
    matches: list[dict[str, Any]] = []
    for feature, rule in profile.dislike_suppression.items():
        if not isinstance(rule, dict):
            continue
        keywords = _rule_keywords(rule)
        matched_terms = _matched_terms(normalized_dislikes, keywords)
        if not matched_terms:
            continue
        matches.append(
            {
                "feature": str(feature),
                "matched_terms": matched_terms,
                "replacement": str(rule.get("replacement") or ""),
                "note": str(rule.get("note") or ""),
                "drawing_note": str(rule.get("drawing_note") or rule.get("note") or ""),
                "source": "explicit_dislike",
                "style_id": profile.style_id,
                "assumption": True,
            }
        )
    return tuple(matches)


def profile_reference_descriptor_matches(profile: StyleProfile, reference_signals: list[str] | tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    normalized_signals = [normalize_signal(signal) for signal in reference_signals if signal]
    if not normalized_signals:
        return ()
    matches: list[dict[str, Any]] = []
    for feature, rule in profile.reference_descriptor_mappings.items():
        if not isinstance(rule, dict):
            continue
        keywords = _rule_keywords(rule)
        matched_terms = _matched_terms(normalized_signals, keywords)
        if not matched_terms:
            continue
        matches.append(
            {
                "feature": str(feature),
                "matched_terms": matched_terms,
                "facade_mark": str(rule.get("facade_mark") or ""),
                "material_note": str(rule.get("material_note") or ""),
                "drawing_note": str(rule.get("drawing_note") or rule.get("material_note") or ""),
                "source": "reference_image_descriptor",
                "style_id": profile.style_id,
                "assumption": True,
            }
        )
    return tuple(matches)


def _rule_keywords(rule: dict[str, Any]) -> tuple[str, ...]:
    raw = rule.get("keywords") or ()
    if isinstance(raw, str):
        return (normalize_signal(raw),)
    return tuple(normalize_signal(item) for item in raw if str(item).strip())


def _matched_terms(values: list[str], keywords: tuple[str, ...]) -> tuple[str, ...]:
    matched: list[str] = []
    for value in values:
        for keyword in keywords:
            if _flex_contains(value, keyword):
                matched.append(keyword)
    return tuple(dict.fromkeys(matched))


def _flex_contains(value: str, keyword: str) -> bool:
    if not value or not keyword:
        return False
    return keyword in value or value in keyword
