from __future__ import annotations

import html
from collections.abc import Mapping
from typing import Any

from version import VERSION

MODEL_LABELS: tuple[tuple[str, str], ...] = (
    ("chat", "Chat"),
    ("code", "Code"),
    ("image", "Image"),
    ("deepseek", "DeepSeek"),
    ("kimi", "Kimi"),
)


def build_runtime_info(
    *,
    chat_model: str,
    code_model: str,
    image_model: str,
    deepseek_model: str | None = None,
    kimi_model: str | None = None,
    deploy: Mapping[str, object] | None = None,
    service: Mapping[str, object] | None = None,
    checks: Mapping[str, object] | None = None,
    uptime_seconds: int | float | None = None,
) -> dict[str, Any]:
    models: dict[str, str] = {}
    values = (
        ("chat", chat_model),
        ("code", code_model),
        ("image", image_model),
        ("deepseek", deepseek_model),
        ("kimi", kimi_model),
    )
    for key, value in values:
        normalized = str(value or "").strip()
        if normalized:
            models[key] = normalized

    payload: dict[str, Any] = {
        "ok": True,
        "status": "ok",
        "version": VERSION,
        "models": models,
    }
    if deploy:
        payload["deploy"] = dict(deploy)
    if service:
        payload["service"] = dict(service)
    if checks:
        payload["checks"] = dict(checks)
    if uptime_seconds is not None:
        payload["uptime_seconds"] = round(float(uptime_seconds), 2)
    return payload


def format_runtime_info_html(runtime_info: Mapping[str, object], active_profile: str | None = None) -> str:
    version = str(runtime_info.get("version", "") or "").strip() or "unknown"
    lines = [
        "<b>Version / Models</b>",
        "",
        f"<b>Version:</b> <code>{html.escape(version)}</code>",
    ]

    normalized_profile = str(active_profile or "").strip()
    if normalized_profile:
        lines.extend(
            [
                "",
                f"<b>Active profile:</b> <code>{html.escape(normalized_profile)}</code>",
            ]
        )

    models = runtime_info.get("models")
    if isinstance(models, Mapping) and models:
        lines.extend(["", "<b>Models</b>"])
        for key, label in MODEL_LABELS:
            value = models.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"- <b>{label}:</b> <code>{html.escape(value.strip())}</code>")

    return "\n".join(lines)
