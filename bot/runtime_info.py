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
    lines.extend(
        [
            "",
            html.escape(SAFE_PUBLIC_VERSION_NOTE),
            f"For JO API access, contact the developer {html.escape(DEVELOPER_HANDLE)}.",
        ]
    )

    return "\n".join(lines)
