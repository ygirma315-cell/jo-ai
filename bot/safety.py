from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


_MAX_MATCHES = 8


@dataclass(frozen=True, slots=True)
class SafetyModerationResult:
    blocked: bool
    categories: tuple[str, ...] = ()
    matched_terms: tuple[str, ...] = ()


_GROK_UNSAFE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "nudity",
        re.compile(
            r"\b(nude|nudity|naked|topless|bottomless|areola|nipples?|without clothes|no clothes|see[- ]through|underboob|sideboob)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "sexual",
        re.compile(
            r"\b(sex|sexual|porn|pornographic|xxx|erotic|sensual|seductive|lingerie|stripper|striptease|orgasm|masturbat\w*|blow ?job|oral sex|anal sex)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "explicit",
        re.compile(
            r"\b(genitals?|vagina|penis|dick|cock|pussy|cum|semen|ejaculat\w*|adult content|nsfw)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "fetish",
        re.compile(
            r"\b(fetish|bdsm|bondage|dominatrix|submission|latex fetish|feet fetish|kink|roleplay sex)\b",
            re.IGNORECASE,
        ),
    ),
)


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in values:
        normalized = str(item or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)


def moderate_grok_generation_prompt(prompt: str | None) -> SafetyModerationResult:
    text = str(prompt or "").strip()
    if not text:
        return SafetyModerationResult(blocked=False)

    matched_categories: list[str] = []
    matched_terms: list[str] = []
    normalized = " ".join(text.split())
    for category, pattern in _GROK_UNSAFE_RULES:
        for found in pattern.finditer(normalized):
            matched_categories.append(category)
            matched_terms.append(found.group(0))
            if len(matched_terms) >= _MAX_MATCHES:
                break
        if len(matched_terms) >= _MAX_MATCHES:
            break

    unique_categories = _ordered_unique(matched_categories)
    unique_terms = _ordered_unique(matched_terms)[:_MAX_MATCHES]
    return SafetyModerationResult(
        blocked=bool(unique_categories),
        categories=unique_categories,
        matched_terms=unique_terms,
    )


def grok_safety_warning_text(media_type: Literal["image", "video"]) -> str:
    target = "image" if media_type == "image" else "video"
    return (
        f"Request blocked by safety policy. Grok {target} generation cannot be used for "
        "nude, sexual, explicit, or fetish content. Please rewrite the prompt with safe content."
    )


def grok_safety_warning_html(media_type: Literal["image", "video"]) -> str:
    target = "image" if media_type == "image" else "video"
    return (
        "Warning: <b>Request blocked by safety policy.</b>\n"
        f"Grok {target} generation does not allow nude, sexual, explicit, or fetish content.\n"
        "Please rewrite your prompt with safe content and try again."
    )


def grok_safety_reason_code(result: SafetyModerationResult) -> str:
    if not result.blocked:
        return ""
    categories = ",".join(result.categories) or "unsafe"
    return f"grok_safety_block:{categories}"
