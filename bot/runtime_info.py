from __future__ import annotations

import html
from typing import Any

from bot.security import BRANDING_LINE, DEVELOPER_HANDLE, SAFE_PUBLIC_VERSION_NOTE, build_safe_version_summary
from version import VERSION


def build_runtime_info(
    *,
    version: str = VERSION,
    web_version: str | None = None,
) -> dict[str, Any]:
    return build_safe_version_summary(bot_version=version, web_version=web_version)


def format_runtime_info_html(runtime_info: dict[str, object], active_profile: str | None = None) -> str:
    version = str(runtime_info.get("version", "") or "").strip() or "unknown"
    web_version = str(runtime_info.get("web_version", "") or "").strip()
    latest_release = runtime_info.get("latest_release")
    latest_version = ""
    latest_title = ""
    latest_items: list[str] = []
    if isinstance(latest_release, dict):
        latest_version = str(latest_release.get("version", "") or "").strip()
        latest_title = str(latest_release.get("title", "") or "").strip()
        raw_items = latest_release.get("items", [])
        if isinstance(raw_items, (list, tuple)):
            latest_items = [str(item).strip() for item in raw_items if str(item).strip()]

    lines = [
        "<b>JO AI Version</b>",
        "",
        html.escape(BRANDING_LINE),
        f"<b>Developer:</b> <code>{html.escape(DEVELOPER_HANDLE)}</code>",
        f"<b>Bot version:</b> <code>{html.escape(version)}</code>",
    ]

    if web_version:
        lines.append(f"<b>Web app version:</b> <code>{html.escape(web_version)}</code>")
    if active_profile:
        lines.append(f"<b>Active mode profile:</b> <code>{html.escape(str(active_profile).strip())}</code>")
    if latest_version or latest_title or latest_items:
        lines.extend(
            [
                "",
                "<b>Latest update</b>",
                f"<b>Release:</b> <code>{html.escape(latest_version or web_version or version)}</code>",
            ]
        )
        if latest_title:
            lines.append(html.escape(latest_title))
        for item in latest_items[:3]:
            lines.append(f"• {html.escape(item)}")
    lines.extend(
        [
            "",
            html.escape(SAFE_PUBLIC_VERSION_NOTE),
            f"For JO API access, contact the developer {html.escape(DEVELOPER_HANDLE)}.",
        ]
    )

    return "\n".join(lines)


def format_release_summary_html(runtime_info: dict[str, object]) -> str:
    version = str(runtime_info.get("version", "") or "").strip() or "unknown"
    web_version = str(runtime_info.get("web_version", "") or "").strip()
    latest_release = runtime_info.get("latest_release")
    latest_version = web_version or version
    latest_title = ""
    latest_items: list[str] = []

    if isinstance(latest_release, dict):
        latest_version = str(latest_release.get("version", "") or latest_version).strip() or latest_version
        latest_title = str(latest_release.get("title", "") or "").strip()
        raw_items = latest_release.get("items", [])
        if isinstance(raw_items, (list, tuple)):
            latest_items = [str(item).strip() for item in raw_items if str(item).strip()]

    lines = [
        "<b>Latest JO AI update</b>",
        f"<b>Bot:</b> <code>{html.escape(version)}</code>",
        f"<b>Current release:</b> <code>{html.escape(latest_version)}</code>",
    ]
    if web_version:
        lines.append(f"<b>Web:</b> <code>{html.escape(web_version)}</code>")
    if latest_title:
        lines.extend(["", html.escape(latest_title)])
    for item in latest_items[:3]:
        lines.append(f"• {html.escape(item)}")
    return "\n".join(lines)
