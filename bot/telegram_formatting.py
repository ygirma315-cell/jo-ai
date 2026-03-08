from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup

MAX_TEXT_MESSAGE_CHARS = 3500
MAX_CODE_PREVIEW_LINES = 200
MAX_CODE_PREVIEW_CHARS = 3500
MAX_HTML_CHUNK_ESCAPED_CHARS = 3200
CODE_FENCE_PATTERN = re.compile(r"```(?P<lang>[a-zA-Z0-9_+#.-]*)\n(?P<code>[\s\S]*?)```", re.MULTILINE)

_MDV2_SPECIAL_CHARS = set("\\_*[]()~`>#+-=|{}.!")
_LANGUAGE_EXTENSIONS = {
    "bash": "sh",
    "c": "c",
    "cpp": "cpp",
    "csharp": "cs",
    "css": "css",
    "go": "go",
    "html": "html",
    "java": "java",
    "javascript": "js",
    "js": "js",
    "json": "json",
    "markdown": "md",
    "md": "md",
    "php": "php",
    "python": "py",
    "py": "py",
    "rust": "rs",
    "shell": "sh",
    "sh": "sh",
    "sql": "sql",
    "text": "txt",
    "ts": "ts",
    "typescript": "ts",
    "xml": "xml",
    "yaml": "yml",
    "yml": "yml",
}


def escape_md(text: str) -> str:
    escaped: list[str] = []
    for char in text.replace("\r\n", "\n").replace("\r", "\n"):
        if char in _MDV2_SPECIAL_CHARS:
            escaped.append(f"\\{char}")
        else:
            escaped.append(char)
    return "".join(escaped)


def _clean_lines(lines: Sequence[str] | None) -> list[str]:
    if not lines:
        return []
    return [line.strip() for line in lines if line and line.strip()]


def _markdown_heading(text: str) -> str:
    return f"*{escape_md(text)}*"


def _bullet_lines(lines: Sequence[str]) -> str:
    return "\n".join(f"\\- {escape_md(line)}" for line in _clean_lines(lines))


def _numbered_lines(lines: Sequence[str]) -> str:
    cleaned = _clean_lines(lines)
    return "\n".join(f"{index}\\. {escape_md(line)}" for index, line in enumerate(cleaned, start=1))


def _sanitize_code_preview(code: str) -> tuple[str, bool]:
    preview = code.replace("\r\n", "\n").replace("\r", "\n")
    preview_lines = preview.splitlines()
    was_truncated = len(preview) > MAX_CODE_PREVIEW_CHARS or len(preview_lines) > MAX_CODE_PREVIEW_LINES

    if len(preview_lines) > MAX_CODE_PREVIEW_LINES:
        preview = "\n".join(preview_lines[:MAX_CODE_PREVIEW_LINES])
    if len(preview) > MAX_CODE_PREVIEW_CHARS:
        preview = preview[:MAX_CODE_PREVIEW_CHARS].rsplit("\n", 1)[0] or preview[:MAX_CODE_PREVIEW_CHARS]

    fence_modified = "```" in preview
    if fence_modified:
        preview = preview.replace("```", "``\\`")
    return preview.rstrip("\n"), was_truncated or fence_modified


def _code_block(code: str, lang: str) -> str:
    language = re.sub(r"[^a-zA-Z0-9_+#.-]", "", (lang or "text").strip().lower()) or "text"
    return f"```{language}\n{code}\n```"


def _split_section_lines(section_title: str, lines: Sequence[str], numbered: bool) -> list[str]:
    cleaned = _clean_lines(lines)
    if not cleaned:
        return []

    messages: list[str] = []
    current: list[str] = [_markdown_heading(section_title)]
    for index, line in enumerate(cleaned, start=1):
        rendered = f"{index}\\. {escape_md(line)}" if numbered else f"\\- {escape_md(line)}"
        candidate = "\n\n".join(current[:1]) + "\n" + "\n".join(current[1:] + [rendered])
        if len(candidate) > MAX_TEXT_MESSAGE_CHARS and len(current) > 1:
            messages.append("\n".join(current))
            current = [_markdown_heading(section_title), rendered]
        else:
            current.append(rendered)
    if len(current) > 1:
        messages.append("\n".join(current))
    return messages


def _default_filename(lang: str) -> str:
    key = (lang or "text").strip().lower()
    extension = _LANGUAGE_EXTENSIONS.get(key, "txt")
    return f"output.{extension}"


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _max_raw_prefix_for_escaped_limit(text: str, limit: int) -> int:
    if not text or limit <= 0:
        return 0
    low, high = 1, len(text)
    best = 0
    while low <= high:
        mid = (low + high) // 2
        escaped_len = len(_escape_html(text[:mid]))
        if escaped_len <= limit:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best


def _split_for_html_limit(text: str, escaped_limit: int = MAX_HTML_CHUNK_ESCAPED_CHARS) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized:
        return [""]

    chunks: list[str] = []
    index = 0
    size = len(normalized)

    while index < size:
        remaining = normalized[index:]
        if len(_escape_html(remaining)) <= escaped_limit:
            chunks.append(remaining)
            break

        prefix_size = _max_raw_prefix_for_escaped_limit(remaining, escaped_limit)
        if prefix_size <= 0:
            # Fallback for extremely dense escaped content.
            prefix_size = 1
        prefix = remaining[:prefix_size]

        split_at = prefix.rfind("\n")
        if split_at < max(1, int(prefix_size * 0.4)):
            split_at = prefix.rfind(" ")
        if split_at <= 0:
            split_at = prefix_size

        chunk = remaining[:split_at]
        chunks.append(chunk)
        index += split_at
        while index < size and normalized[index] == "\n":
            index += 1

    return [item for item in chunks if item]


def _safe_code_language(lang: str) -> str:
    language = re.sub(r"[^a-zA-Z0-9_+#.-]", "", (lang or "text").strip().lower())
    return language or "text"


def _split_rich_segments(text: str) -> list[tuple[str, str, str]]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    segments: list[tuple[str, str, str]] = []
    cursor = 0
    for match in CODE_FENCE_PATTERN.finditer(normalized):
        if match.start() > cursor:
            plain_text = normalized[cursor : match.start()]
            if plain_text.strip():
                segments.append(("text", "", plain_text))
        code = (match.group("code") or "").rstrip("\n")
        if code:
            segments.append(("code", _safe_code_language(match.group("lang") or "text"), code))
        cursor = match.end()
    tail = normalized[cursor:]
    if tail.strip():
        segments.append(("text", "", tail))
    return segments


def run_markdown_sanity_checks() -> None:
    sample_text = r"_*[]()~`>#+-=|{}.! plain"
    escaped = escape_md(sample_text)
    for char in "_*[]()~`>#+-=|{}.!":
        needle = f"\\{char}"
        if needle not in escaped:
            raise AssertionError(f"Missing MarkdownV2 escape for {char!r}")

    preview, requires_file = _sanitize_code_preview("print('hello')\n")
    if preview != "print('hello')" or requires_file:
        raise AssertionError("Unexpected code preview sanitization result.")

    preview_with_fence, requires_file = _sanitize_code_preview("print('```')\n")
    if "```" in preview_with_fence or not requires_file:
        raise AssertionError("Code fence sanitization failed.")


@dataclass(slots=True)
class TelegramMessageFormatter:
    bot: Bot

    async def _send_html_chunk(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )

    async def send_paginated_text_response(
        self,
        *,
        chat_id: int,
        title: str,
        body_text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        normalized = body_text.strip() or "No output generated."
        chunks = _split_for_html_limit(normalized)
        total = len(chunks)

        for index, chunk in enumerate(chunks):
            if total > 1:
                heading = f"{title} (Part {index + 1}/{total})"
            else:
                heading = title
            is_last = index == total - 1
            payload = f"<b>{_escape_html(heading)}</b>\n\n{_escape_html(chunk)}"
            await self._send_html_chunk(
                chat_id=chat_id,
                text=payload,
                reply_markup=reply_markup if is_last else None,
            )

    async def send_rich_response(
        self,
        *,
        chat_id: int,
        title: str,
        raw_text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        normalized = raw_text.strip() or "No output generated."
        segments = _split_rich_segments(normalized)
        if not segments:
            await self.send_paginated_text_response(
                chat_id=chat_id,
                title=title,
                body_text=normalized,
                reply_markup=reply_markup,
            )
            return

        await self._send_html_chunk(chat_id=chat_id, text=f"<b>{_escape_html(title)}</b>")

        total_code_blocks = sum(1 for segment_type, _, _ in segments if segment_type == "code")
        seen_code_blocks = 0
        for segment_index, (segment_type, lang, content) in enumerate(segments):
            is_last_segment = segment_index == len(segments) - 1
            chunks = _split_for_html_limit(content)
            for chunk_index, chunk in enumerate(chunks):
                is_last_chunk = chunk_index == len(chunks) - 1
                is_final_message = is_last_segment and is_last_chunk
                if segment_type == "code":
                    if chunk_index == 0:
                        seen_code_blocks += 1
                    code_label = "Code" if total_code_blocks <= 1 else f"Code Block {seen_code_blocks}/{total_code_blocks}"
                    if len(chunks) > 1:
                        code_label = f"{code_label} (Part {chunk_index + 1}/{len(chunks)})"
                    payload = (
                        f"<b>{_escape_html(code_label)}</b>\n"
                        f"<pre><code class=\"language-{_safe_code_language(lang)}\">{_escape_html(chunk)}</code></pre>"
                    )
                else:
                    payload = _escape_html(chunk)
                await self._send_html_chunk(
                    chat_id=chat_id,
                    text=payload,
                    reply_markup=reply_markup if is_final_message else None,
                )

    async def send_structured_response(
        self,
        chat_id: int,
        title: str,
        sections: Sequence[tuple[str, Sequence[str]]],
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        cleaned_sections = [(section_title, _clean_lines(lines)) for section_title, lines in sections if _clean_lines(lines)]
        title_block = _markdown_heading(title)

        body_parts: list[str] = [title_block]
        for section_title, lines in cleaned_sections:
            body_parts.append("")
            body_parts.append(_markdown_heading(section_title))
            body_parts.append(_bullet_lines(lines))

        body = "\n".join(part for part in body_parts if part is not None)
        if len(body) <= MAX_TEXT_MESSAGE_CHARS:
            await self.bot.send_message(
                chat_id=chat_id,
                text=body,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup,
            )
            return

        await self.bot.send_message(chat_id=chat_id, text=title_block, parse_mode=ParseMode.MARKDOWN_V2)
        pending_sections = list(cleaned_sections)
        for section_index, (section_title, lines) in enumerate(pending_sections):
            section_chunks = _split_section_lines(section_title, lines, numbered=False)
            for chunk_index, chunk in enumerate(section_chunks):
                is_last_chunk = section_index == len(pending_sections) - 1 and chunk_index == len(section_chunks) - 1
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=reply_markup if is_last_chunk else None,
                )

    async def send_code_response(
        self,
        chat_id: int,
        title: str,
        explanation_lines: Sequence[str],
        code: str,
        lang: str,
        run_steps: Sequence[str],
        notes_lines: Sequence[str] | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        filename: str | None = None,
    ) -> None:
        _ = filename
        cleaned_explanations = _clean_lines(explanation_lines)
        cleaned_run_steps = _clean_lines(run_steps)
        cleaned_notes = _clean_lines(notes_lines)

        intro_blocks: list[str] = []
        if cleaned_explanations:
            intro_blocks.append("Explanation:\n" + "\n".join(f"- {line}" for line in cleaned_explanations))
        if intro_blocks:
            await self.send_paginated_text_response(
                chat_id=chat_id,
                title=title,
                body_text="\n\n".join(intro_blocks),
            )
        else:
            await self._send_html_chunk(
                chat_id=chat_id,
                text=f"<b>{_escape_html(title)}</b>",
            )

        code_chunks = _split_for_html_limit(code or "# No code was generated.")
        has_footer = bool(cleaned_run_steps or cleaned_notes)
        for index, chunk in enumerate(code_chunks):
            label = "Code" if len(code_chunks) == 1 else f"Code (Part {index + 1}/{len(code_chunks)})"
            is_last_code_chunk = index == len(code_chunks) - 1
            payload = (
                f"<b>{_escape_html(label)}</b>\n"
                f"<pre><code class=\"language-{_safe_code_language(lang)}\">{_escape_html(chunk)}</code></pre>"
            )
            await self._send_html_chunk(
                chat_id=chat_id,
                text=payload,
                reply_markup=reply_markup if is_last_code_chunk and not has_footer else None,
            )

        footer_parts: list[str] = []
        if cleaned_run_steps:
            footer_parts.append("How to run:\n" + "\n".join(f"{index}. {line}" for index, line in enumerate(cleaned_run_steps, start=1)))
        if cleaned_notes:
            footer_parts.append("Notes:\n" + "\n".join(f"- {line}" for line in cleaned_notes))
        if footer_parts:
            await self.send_paginated_text_response(
                chat_id=chat_id,
                title="Execution Guide",
                body_text="\n\n".join(footer_parts),
                reply_markup=reply_markup,
            )
