from __future__ import annotations

import re

from version import latest_release, public_releases

DEVELOPER_HANDLE = "@grpbuyer3"
BRANDING_LINE = "Created by JO AI"
SAFE_PUBLIC_SUPPORT_LINE = f"{BRANDING_LINE}. Contact {DEVELOPER_HANDLE} to get the JO API."
SAFE_INTERNAL_DETAILS_REFUSAL = (
    "I can't share internal backend or API details. "
    f"For JO API access, contact the developer {DEVELOPER_HANDLE}."
)
SAFE_SERVICE_UNAVAILABLE_MESSAGE = (
    f"{BRANDING_LINE}. JO AI is temporarily unavailable. "
    f"Contact {DEVELOPER_HANDLE} if you need JO API access."
)
SAFE_PUBLIC_VERSION_NOTE = "Internal backend, provider, and model details are not shared."

_SENSITIVE_TARGETS = re.compile(
    r"""
    \b(
        system(?:\s|-)?prompt|
        hidden(?:\s|-)?prompt|
        hidden(?:\s|-)?instructions?|
        developer(?:\s|-)?message|
        chain(?:\s|-)?of(?:\s|-)?thought|
        reasoning(?:\s|-)?trace|
        config(?:uration)?|
        \.env|
        env(?:ironment)?(?:\s|-)?vars?|
        environment(?:\s|-)?variables?|
        api(?:\s|-)?keys?|
        access(?:\s|-)?tokens?|
        bearer|
        authorization|
        headers?|
        secrets?|
        credentials?|
        webhook(?:\s|-)?secret|
        backend|
        provider|
        stack|
        architecture|
        endpoints?|
        runtime|
        model(?:\s|-)?name|
        model(?:\s|-)?version|
        exact(?:\s|-)?model|
        hidden(?:\s|-)?settings?
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_EXTRACTION_VERBS = re.compile(
    r"\b(reveal|show|tell|dump|print|display|list|return|output|extract|share|expose|leak|give|send)\b",
    re.IGNORECASE,
)

_INSTRUCTION_BYPASS = re.compile(
    r"\b(ignore|bypass|override|forget|disregard)\b[\s\S]{0,80}\b(instructions|rules|system|developer|policy|guardrails?)\b",
    re.IGNORECASE,
)

_SELF_DISCLOSURE = re.compile(
    r"""
    \b(
        what|which|who|where|how
    )\b
    [\s\S]{0,40}
    \b(
        model|provider|backend|api|endpoint|stack|architecture|version
    )\b
    [\s\S]{0,40}
    \b(
        you|your|jo\s+ai|this\s+bot|the\s+bot|the\s+website|the\s+mini\s+app|the\s+backend
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SELF_CONTEXT = re.compile(
    r"\b(you|your|jo\s+ai|this\s+bot|the\s+bot|the\s+website|the\s+mini\s+app|the\s+backend)\b",
    re.IGNORECASE,
)

_PROVIDER_NAMES = re.compile(
    r"\b(nvidia|openai|anthropic|moonshot|deepseek|render|onrender|llama|flux|kimi)\b",
    re.IGNORECASE,
)

_TOKEN_DUMP = re.compile(
    r"\b(print|show|dump|reveal|list)\b[\s\S]{0,40}\b(token|secret|credential|authorization|bearer|header)\b",
    re.IGNORECASE,
)


def contains_internal_detail_request(*parts: str | None) -> bool:
    text = "\n".join(str(part or "").strip() for part in parts if part).strip()
    if not text:
        return False

    if _INSTRUCTION_BYPASS.search(text):
        return True
    if _TOKEN_DUMP.search(text):
        return True
    if _SELF_DISCLOSURE.search(text):
        return True
    if _EXTRACTION_VERBS.search(text) and _SENSITIVE_TARGETS.search(text):
        return True
    if _SELF_CONTEXT.search(text) and (_SENSITIVE_TARGETS.search(text) or _PROVIDER_NAMES.search(text)):
        return True
    return False


def build_safe_version_summary(*, bot_version: str, web_version: str | None = None) -> dict[str, object]:
    latest = latest_release()
    payload: dict[str, object] = {
        "ok": True,
        "status": "ok",
        "version": str(bot_version or "").strip() or "unknown",
        "branding": BRANDING_LINE,
        "developer": DEVELOPER_HANDLE,
        "note": SAFE_PUBLIC_VERSION_NOTE,
        "latest_release": latest,
        "releases": public_releases(limit=4),
    }
    normalized_web = str(web_version or "").strip()
    if normalized_web:
        payload["web_version"] = normalized_web
    return payload
