from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

MAX_TEXT_MESSAGE_CHARS = 3500
MAX_CODE_PREVIEW_LINES = 200
MAX_CODE_PREVIEW_CHARS = 3500

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
        cleaned_explanations = _clean_lines(explanation_lines)
        cleaned_run_steps = _clean_lines(run_steps)
        cleaned_notes = _clean_lines(notes_lines)

        preview, needs_attachment = _sanitize_code_preview(code)
        title_and_explanation = [_markdown_heading(title)]
        if cleaned_explanations:
            title_and_explanation.extend(["", _markdown_heading("Explanation"), _bullet_lines(cleaned_explanations)])
        await self.bot.send_message(
            chat_id=chat_id,
            text="\n".join(title_and_explanation),
            parse_mode=ParseMode.MARKDOWN_V2,
        )

        await self.bot.send_message(
            chat_id=chat_id,
            text="\n".join((_markdown_heading("Code"), _code_block(preview, lang))),
            parse_mode=ParseMode.MARKDOWN_V2,
        )

        if needs_attachment:
            attachment_name = filename or _default_filename(lang)
            document = BufferedInputFile(code.encode("utf-8"), filename=attachment_name)
            await self.bot.send_document(
                chat_id=chat_id,
                document=document,
                caption=_markdown_heading("Full code file"),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            cleaned_notes = ["Preview only in chat. Use the attached file for the complete code.", *cleaned_notes]

        run_parts = [_markdown_heading("How to run"), _numbered_lines(cleaned_run_steps)]
        if cleaned_notes:
            run_parts.extend(["", _markdown_heading("Notes / Common fixes"), _bullet_lines(cleaned_notes)])
        await self.bot.send_message(
            chat_id=chat_id,
            text="\n".join(part for part in run_parts if part),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup,
        )
