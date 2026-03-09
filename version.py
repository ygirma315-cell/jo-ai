from __future__ import annotations

from typing import Any

VERSION = "v1.5.0"
WEB_VERSION = "v1.5.0"

RELEASES: tuple[dict[str, Any], ...] = (
    {
        "version": WEB_VERSION,
        "title": "Major mini app and Telegram bot organization update",
        "items": (
            "The mini app now opens directly on AI tool selection, uses a more stable fixed chat layout, and keeps code upload compact beside the composer.",
            "Telegram bot flow now uses paired Back and Main Menu buttons, removes utilities/games/calculator, and jumps uploaded images straight into Vision.",
            "Code generation now pushes complex requests toward fuller system outputs, while TTS adds richer voice-style choices and clearer clone-status messaging.",
        ),
    },
    {
        "version": "v1.4.0",
        "title": "Premium mobile chat refresh",
        "items": (
            "All JO AI chat pages now use a cleaner bordered layout with a much larger conversation panel and a smaller pinned composer.",
            "Mobile webviews now respect the shrinking visible viewport better, so the input stays visible and part of the conversation remains on-screen above the keyboard.",
            "Client-side stale history and cached API base values are reset on new frontend releases, and both the website and bot now show the current version with an update summary.",
        ),
    },
    {
        "version": "v1.3.2",
        "title": "Security hardening and safer public branding",
        "items": (
            "Public version info now stays branded while internal backend, model, and API details remain hidden.",
            "Vision requests now use generic JO AI routing instead of older provider-specific wording.",
            "Support links and public copy now point users to @grpbuyer3 for JO API access.",
        ),
    },
    {
        "version": "v1.3.1",
        "title": "Fixed mobile composer and cleaner welcome polish",
        "items": (
            "Tool pages now keep a stable chat view with a fixed bottom composer and a Send button pinned to the right.",
            "Only the conversation thread scrolls, while the input area stays compact and clearer inside Telegram mobile.",
            "The welcome screen now uses a cleaner JO AI icon treatment instead of the older eye emoji.",
        ),
    },
    {
        "version": "v1.3.0",
        "title": "Shared chat app redesign",
        "items": (
            "All AI tool pages now use one clean chat-style layout with a compact header and bottom composer.",
            "Message flow, thinking states, and scrolling are smoother on mobile and inside Telegram.",
            "Image, prompt, code, research, and vision tools now share the same calmer design system.",
        ),
    },
)


def latest_release() -> dict[str, Any]:
    return dict(RELEASES[0]) if RELEASES else {"version": WEB_VERSION, "title": "", "items": ()}


def public_releases(limit: int | None = None) -> list[dict[str, Any]]:
    selected = RELEASES if limit is None else RELEASES[: max(0, limit)]
    normalized: list[dict[str, Any]] = []
    for release in selected:
        normalized.append(
            {
                "version": str(release.get("version", "") or "").strip(),
                "title": str(release.get("title", "") or "").strip(),
                "items": [str(item).strip() for item in release.get("items", ()) if str(item).strip()],
            }
        )
    return normalized


def latest_release_lines(limit: int = 3) -> list[str]:
    items = public_releases(limit=1)[0].get("items", []) if RELEASES else []
    return [str(item).strip() for item in items[: max(0, limit)] if str(item).strip()]
