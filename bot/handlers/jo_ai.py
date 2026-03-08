from __future__ import annotations

import asyncio
from dataclasses import dataclass
import html
import logging
import random
import re
from contextlib import suppress
from typing import Literal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from bot.constants import (
    MENU_AI_CHAT,
    MENU_AI_CODE,
    MENU_AI_DEEPSEEK,
    MENU_AI_IMAGE,
    MENU_AI_KIMI,
    MENU_AI_PROMPT,
    MENU_AI_RESEARCH,
    MENU_AI_TOOLS,
    MENU_BUTTON_TEXTS,
    MENU_JO_AI,
)
from bot.filters.feature_filter import ActiveFeatureFilter
from bot.keyboards.jo_ai import (
    image_ratio_keyboard,
    image_type_keyboard,
    jo_ai_menu_keyboard,
    jo_chat_keyboard,
    kimi_result_keyboard,
)
from bot.keyboards.menu import ai_tools_keyboard, main_menu_keyboard
from bot.models.session import Feature, JoAIMode
from bot.security import BRANDING_LINE, DEVELOPER_HANDLE
from bot.services.ai_service import AIServiceError, ChatService, ImageGenerationService
from bot.services.session_manager import SessionManager
from bot.telegram_formatting import TelegramMessageFormatter

router = Router(name="jo_ai")
logger = logging.getLogger(__name__)

JO_AI_MENU_TEXT = (
    "🤖 <b>JO AI Tools</b>\n\n"
    "Choose a mode:\n"
    "• 💬 JO AI Chat\n"
    "• ⚡ Code Generator\n"
    "• 🔍 Research\n"
    "• ✨ Prompt Generator\n"
    "• 🎨 Image Generator\n"
    "• 🖼️ JO AI Vision\n"
    "• 🧠 Deep Analysis\n\n"
    "💡 Tip: Use /help any time for guidance."
)

IMAGE_TYPE_LABELS = {
    "realistic": "Realistic Image",
    "ai_art": "AI Art",
    "anime": "Anime Style",
    "cyberpunk": "Cyberpunk Style",
    "logo_icon": "Logo / Icon",
    "render_3d": "3D Render",
    "concept_art": "Concept Art",
}

IMAGE_TYPE_STYLE_HINTS = {
    "realistic": "photorealistic, natural textures, realistic camera lens, ultra detailed",
    "ai_art": "digital art, stylized illustration, painterly texture, artistic composition",
    "anime": "anime style, clean line art, expressive characters, vibrant colors",
    "cyberpunk": "cyberpunk, neon lighting, futuristic city, rain reflections, cinematic mood",
    "logo_icon": "minimal clean logo design, centered icon, vector style, brand-ready composition",
    "render_3d": "3D render, physically based materials, global illumination, high detail",
    "concept_art": "concept art, environment storytelling, dramatic composition, matte painting quality",
}

IMAGE_RATIO_LABELS = {
    "1:1": "1:1",
    "16:9": "16:9",
    "9:16": "9:16",
}

IMAGE_RATIO_TOKEN_MAP = {
    "1_1": "1:1",
    "16_9": "16:9",
    "9_16": "9:16",
}

IMAGE_RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "16:9": "1344x768",
    "9:16": "768x1344",
}

ENGAGEMENT_LINES = (
    "🤖 Thinking...",
    "🧠 Analyzing your request...",
    "⚡ Optimizing the response...",
    "✨ Crafting a clean answer...",
)

MODE_PROGRESS_TEXT = {
    "chat": "🤖 Thinking about your message...",
    "code": "⚡ Generating code...",
    "research": "🔍 Researching your topic...",
    "prompt": "✨ Building your prompt...",
    "image_prompt": "🧠 Optimizing image prompt...",
}

MODE_RESULT_TITLE = {
    "chat": "JO AI Reply",
    "code": "Code Result",
    "research": "Research Result",
    "prompt": "Prompt Result",
    "image_prompt": "Image Prompt Result",
}

MAX_REPLY_CHARS = 3300
CODE_FENCE_PATTERN = re.compile(r"```(?P<lang>[a-zA-Z0-9_+#.-]*)\n(?P<code>[\s\S]*?)```", re.MULTILINE)
CHAT_HISTORY_ENTRY_MAX_CHARS = 1800
LONG_CODE_ATTACHMENT_THRESHOLD = 2800
EXTREME_CODE_LENGTH_THRESHOLD = 16000
MAX_CODE_UPLOAD_BYTES = 1_500_000
DEBUG_INTENT_PATTERN = re.compile(
    r"\b(debug|fix|error|exception|traceback|bug|issue|crash|failing|failure|broken|not working)\b",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class ParsedCodeReply:
    title: str
    explanation_lines: list[str]
    code: str
    lang: str
    run_steps: list[str]
    notes_lines: list[str]


def _default_mode_options() -> dict[str, object]:
    return {
        "model_override": None,
        "api_key_override": None,
        "thinking": False,
        "mode_prefix": "",
    }


def _deep_analysis_mode_options(deepseek_api_key: str | None, deepseek_model: str) -> dict[str, object]:
    mode_options = _default_mode_options()
    mode_options["thinking"] = True
    mode_options["mode_prefix"] = (
        "Deep analysis mode: think carefully, consider tradeoffs, then provide a clear final answer."
    )
    if (deepseek_api_key or "").strip():
        mode_options["api_key_override"] = deepseek_api_key
        mode_options["model_override"] = deepseek_model
    return mode_options


async def _show_jo_ai_menu(message: Message) -> None:
    await message.answer(JO_AI_MENU_TEXT, reply_markup=ai_tools_keyboard())


async def _switch_to_jo_ai_mode(user_id: int, mode: JoAIMode, session_manager: SessionManager) -> None:
    async with session_manager.lock(user_id) as session:
        if session.active_feature == Feature.JO_AI:
            session.jo_ai_mode = mode
            if mode != JoAIMode.CHAT:
                session.jo_ai_chat_history.clear()
            if mode != JoAIMode.PROMPT:
                session.jo_ai_prompt_type = None
            if mode != JoAIMode.IMAGE:
                session.jo_ai_image_type = None
                session.jo_ai_image_ratio = None
            if mode != JoAIMode.KIMI_IMAGE_DESCRIBER:
                session.jo_ai_kimi_waiting_image = False
            if mode != JoAIMode.CODE:
                session.jo_ai_code_waiting_file = False
                session.jo_ai_code_file_name = None
                session.jo_ai_code_file_content = None


async def _activate_mode(
    message: Message,
    user_id: int,
    mode: JoAIMode,
    session_manager: SessionManager,
    miniapp_url: str | None,
) -> None:
    transition = await session_manager.switch_feature(user_id, Feature.JO_AI)
    await _switch_to_jo_ai_mode(user_id, mode, session_manager)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))

    if mode == JoAIMode.CHAT:
        await message.answer(
            "💬 <b>JO AI Chat is active</b>\n\n"
            "🧠 Ask me anything and I will respond clearly.\n"
            "💡 Need options? Use /help.",
            reply_markup=jo_chat_keyboard(),
        )
        return
    if mode == JoAIMode.CODE:
        await message.answer(
            "⚡ <b>Code Generator is active</b>\n\n"
            "Describe what you want to build, including language/framework.\n"
            "📌 Example: \"Create a Python FastAPI health endpoint.\"\n\n"
            "🛠 For debug/fix requests, upload the code file first.",
            reply_markup=jo_chat_keyboard(),
        )
        return
    if mode == JoAIMode.RESEARCH:
        await message.answer(
            "🔍 <b>Research mode is active</b>\n\n"
            "Send a topic/question and I will provide structured insights.\n"
            "🎯 Include context for better results.",
            reply_markup=jo_chat_keyboard(),
        )
        return
    if mode == JoAIMode.DEEP_ANALYSIS:
        await message.answer(
            "🧠 <b>Deep Analysis is active</b>\n\n"
            "Send your question and I will analyze it deeply with careful reasoning.\n"
            "No extra mode selection is needed.",
            reply_markup=jo_chat_keyboard(),
        )
        return
    if mode == JoAIMode.PROMPT:
        await message.answer(
            "✨ <b>Prompt Generator is active</b>\n\n"
            "Step 1/2: Tell me the prompt type\n"
            "📌 Examples: image, coding, video, research.",
            reply_markup=jo_chat_keyboard(),
        )
        return
    if mode == JoAIMode.IMAGE:
        await message.answer(
            "🎨 <b>Image Generator is active</b>\n\n"
            "Step 1/3: Choose an image style below.",
            reply_markup=image_type_keyboard(),
        )
        return
    if mode == JoAIMode.KIMI_IMAGE_DESCRIBER:
        await message.answer(
            "🖼️ <b>JO AI Vision is active</b>\n\n"
            "Send an image and I will describe what I see.\n"
            "💡 Optional: include a text instruction with the photo.",
            reply_markup=jo_chat_keyboard(),
        )
        return

    await message.answer("🤖 Select a JO AI mode to continue.", reply_markup=jo_ai_menu_keyboard())


async def _maybe_send_engagement(message: Message) -> None:
    if random.random() < 0.35:
        await message.answer(random.choice(ENGAGEMENT_LINES))


def _is_kimi_unclear_result(error_text: str) -> bool:
    lower = error_text.lower()
    return "empty image description" in lower or "did not return image description choices" in lower


def _split_sentences(text: str, max_items: int = 5) -> list[str]:
    normalized = " ".join(text.replace("\r", "\n").split())
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", normalized)
    lines = [part.strip() for part in parts if part.strip()]
    return lines[:max_items] if lines else [normalized]


def _clean_list_block(block: str, max_items: int = 6) -> list[str]:
    stripped_lines = [line.strip() for line in block.splitlines() if line.strip()]
    cleaned_lines: list[str] = []
    for line in stripped_lines:
        cleaned = re.sub(r"^(?:[-*]|\d+[.)])\s*", "", line).strip()
        if cleaned:
            cleaned_lines.append(cleaned)
    if cleaned_lines:
        return cleaned_lines[:max_items]

    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", block) if item.strip()]
    if len(paragraphs) > 1:
        return paragraphs[:max_items]
    return _split_sentences(block, max_items=max_items)


def _collect_named_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    labels = {
        "title": "title",
        "explanation": "explanation",
        "code language": "code language",
        "how to run": "how to run",
        "notes": "notes",
        "summary": "summary",
        "details": "details",
        "risks/tradeoffs": "risks/tradeoffs",
        "risks and tradeoffs": "risks/tradeoffs",
        "next steps": "next steps",
    }
    current_label: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, current_label
        if current_label is None:
            return
        payload = "\n".join(buffer).strip()
        if payload:
            sections[current_label] = _clean_list_block(payload, max_items=8)
        buffer = []
        current_label = None

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        match = re.match(
            r"^(Title|Explanation|Code Language|How to run|Notes|Summary|Details|Risks/Tradeoffs|Risks and Tradeoffs|Next Steps)\s*:\s*(.*)$",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            flush()
            current_label = labels[match.group(1).lower()]
            inline_value = match.group(2).strip()
            if inline_value:
                buffer.append(inline_value)
            continue
        if current_label is not None:
            buffer.append(raw_line)
    flush()
    return sections


def _guess_code_language(code: str, fallback: str = "text") -> str:
    sample = code.strip().lower()
    if not sample:
        return fallback
    if sample.startswith("<!doctype html") or "<html" in sample:
        return "html"
    if sample.startswith("{") and '"name"' in sample:
        return "json"
    if "def " in sample or "import " in sample or "print(" in sample:
        return "python"
    if "console.log" in sample or "const " in sample or "function " in sample:
        return "javascript"
    if "public class " in sample:
        return "java"
    if "select " in sample or "insert into " in sample:
        return "sql"
    if "package main" in sample or "fmt." in sample:
        return "go"
    return fallback


def _default_run_steps(lang: str) -> list[str]:
    language = (lang or "text").lower()
    defaults = {
        "python": ["Save the file as output.py.", "Install dependencies if required.", "Run python output.py."],
        "javascript": ["Save the file as output.js.", "Install dependencies if required.", "Run node output.js."],
        "typescript": ["Save the file as output.ts.", "Install dependencies if required.", "Run it with your TypeScript toolchain."],
        "html": ["Save the file as output.html.", "Open the file in a browser.", "Use browser developer tools if you need to debug it."],
        "css": ["Save the file as output.css.", "Link it from your HTML file.", "Reload the page to verify the styles."],
        "sql": ["Open your SQL client.", "Paste the query into a new editor tab.", "Run it against the intended database."],
    }
    return defaults.get(language, ["Save the output to a file.", "Run it with the appropriate tool for this language."])


def _extract_code_body(reply_text: str) -> tuple[str, str]:
    fence_match = CODE_FENCE_PATTERN.search(reply_text)
    if fence_match:
        return fence_match.group("code").rstrip(), (fence_match.group("lang") or "").strip().lower()

    code_heading = re.search(r"(?im)^Code\s*:\s*$", reply_text)
    if not code_heading:
        return reply_text.strip(), ""

    trailing = reply_text[code_heading.end() :].strip()
    next_heading = re.search(
        r"(?im)^(How to run|Notes|Summary|Details|Risks/Tradeoffs|Risks and Tradeoffs|Next Steps)\s*:",
        trailing,
    )
    if next_heading:
        trailing = trailing[: next_heading.start()].strip()
    return trailing, ""


def _parse_code_reply(reply_text: str, fallback_title: str) -> ParsedCodeReply:
    code, fenced_lang = _extract_code_body(reply_text)
    text_without_code = CODE_FENCE_PATTERN.sub("", reply_text, count=1).strip()
    named_sections = _collect_named_sections(text_without_code)

    title = (named_sections.get("title") or [fallback_title])[0]
    explanation_lines = named_sections.get("explanation") or _clean_list_block(text_without_code, max_items=4)
    lang = fenced_lang or (named_sections.get("code language") or [""])[0].strip().lower()
    lang = _guess_code_language(code, fallback=lang or "text")
    run_steps = named_sections.get("how to run") or _default_run_steps(lang)
    notes_lines = named_sections.get("notes") or []

    if not explanation_lines:
        explanation_lines = [
            f"Generated a {lang} example tailored to your request.",
            "Review the configuration and dependencies before running it.",
        ]

    return ParsedCodeReply(
        title=title,
        explanation_lines=explanation_lines,
        code=code.strip(),
        lang=lang,
        run_steps=run_steps,
        notes_lines=notes_lines,
    )


def _friendly_error_text(title: str, exc: Exception | None = None) -> str:
    message = (
        f"⚠️ <b>{title}</b>\n"
        f"{BRANDING_LINE}\n"
        "Please try again in a moment.\n"
        f"For JO API access, contact {DEVELOPER_HANDLE}."
    )
    if exc is not None:
        logger.warning("JO AI request failed.")
    return message


def _compact_history_entry(text: str, limit: int = CHAT_HISTORY_ENTRY_MAX_CHARS) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}\n...[truncated for context]..."


def _is_code_debug_request(text: str) -> bool:
    return bool(DEBUG_INTENT_PATTERN.search(text or ""))


def _code_filename_for_language(lang: str) -> str:
    mapping = {
        "python": "output.py",
        "py": "output.py",
        "javascript": "output.js",
        "js": "output.js",
        "typescript": "output.ts",
        "ts": "output.ts",
        "cpp": "output.cpp",
        "c++": "output.cpp",
        "c": "output.c",
        "java": "Main.java",
        "go": "main.go",
        "html": "index.html",
        "css": "styles.css",
        "sql": "output.sql",
        "json": "output.json",
        "xml": "output.xml",
        "yaml": "output.yml",
        "yml": "output.yml",
        "bash": "script.sh",
        "sh": "script.sh",
        "php": "output.php",
        "rust": "main.rs",
    }
    key = (lang or "").strip().lower()
    return mapping.get(key, "output.txt")


def _file_is_code_like(file_name: str) -> bool:
    normalized = (file_name or "").lower()
    allowed_suffixes = (
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".cpp",
        ".cc",
        ".cxx",
        ".c",
        ".cs",
        ".go",
        ".rs",
        ".php",
        ".rb",
        ".swift",
        ".kt",
        ".m",
        ".mm",
        ".sql",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".sh",
        ".bat",
        ".ps1",
        ".txt",
        ".md",
        ".env",
    )
    return normalized.endswith(allowed_suffixes)


def _decode_uploaded_code_file(data: bytes) -> str | None:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        text = decoded.strip()
        if text:
            return text
    return None


def _build_code_debug_request(user_text: str, file_name: str, file_content: str) -> str:
    max_chars = 70_000
    normalized_code = file_content.strip()
    if len(normalized_code) > max_chars:
        normalized_code = normalized_code[:max_chars].rstrip() + "\n...[truncated for analysis]"
    return (
        f"Debug request:\n{user_text}\n\n"
        f"Target file: {file_name}\n\n"
        "Return the corrected version of this file as one complete file.\n"
        "Also include a short explanation of what was fixed.\n\n"
        f"```text\n{normalized_code}\n```"
    )


async def _send_code_generator_reply(
    message: Message,
    formatter: TelegramMessageFormatter,
    reply_text: str,
    reply_markup,
) -> None:
    normalized_reply = reply_text.strip() or "No output generated."
    parsed = _parse_code_reply(normalized_reply, MODE_RESULT_TITLE["code"])
    code_body = parsed.code.strip() or normalized_reply
    code_lang = parsed.lang or _guess_code_language(code_body, fallback="text")
    file_name = _code_filename_for_language(code_lang)
    attach_full_file = len(code_body) >= LONG_CODE_ATTACHMENT_THRESHOLD or len(normalized_reply) >= MAX_REPLY_CHARS
    is_extremely_long = len(code_body) >= EXTREME_CODE_LENGTH_THRESHOLD

    if is_extremely_long:
        summary_lines = parsed.explanation_lines or _clean_list_block(normalized_reply, max_items=4)
        starter_snippet = code_body[:900].rstrip()
        summary_text = "Full code is attached as one file.\n\nSummary:\n" + "\n".join(
            f"- {line}" for line in summary_lines[:6]
        )
        if starter_snippet:
            summary_text += f"\n\nStarter snippet:\n```{code_lang}\n{starter_snippet}\n```"
        await formatter.send_paginated_text_response(
            chat_id=message.chat.id,
            title="Code Result",
            body_text=summary_text,
            reply_markup=reply_markup,
        )
    else:
        await formatter.send_rich_response(
            chat_id=message.chat.id,
            title="Code Result",
            raw_text=normalized_reply,
            reply_markup=reply_markup,
        )

    if attach_full_file:
        code_file = BufferedInputFile(code_body.encode("utf-8"), filename=file_name)
        await message.bot.send_document(
            chat_id=message.chat.id,
            document=code_file,
            caption=f"📎 Full code file attached: {file_name}",
        )


async def _send_progress_message(message: Message, text: str) -> Message | None:
    try:
        return await message.answer(text)
    except Exception:
        return None


async def _clear_progress_message(progress_message: Message | None) -> None:
    if progress_message is None:
        return
    with suppress(TelegramBadRequest):
        await progress_message.delete()


async def _send_styled_ai_reply(
    message: Message,
    mode: Literal["chat", "code", "research", "prompt", "image_prompt"],
    reply_text: str,
    reply_markup,
) -> None:
    await _send_formatted_ai_reply(message, mode, reply_text, reply_markup)


async def _send_formatted_ai_reply(
    message: Message,
    mode: Literal["chat", "code", "research", "prompt", "image_prompt"],
    reply_text: str,
    reply_markup,
) -> None:
    formatter = TelegramMessageFormatter(message.bot)
    normalized_reply = reply_text.strip() or "No output generated."
    title = MODE_RESULT_TITLE.get(mode, "AI Result")

    if mode == "code":
        await _send_code_generator_reply(message, formatter, normalized_reply, reply_markup)
        return

    if CODE_FENCE_PATTERN.search(normalized_reply):
        await formatter.send_rich_response(chat_id=message.chat.id, title=title, raw_text=normalized_reply, reply_markup=reply_markup)
        return

    await formatter.send_paginated_text_response(
        chat_id=message.chat.id,
        title=title,
        body_text=normalized_reply,
        reply_markup=reply_markup,
    )


@router.message(Command("joai"))
@router.message(Command("chat"))
@router.message(Command("code"))
@router.message(Command("research"))
@router.message(Command("prompt"))
@router.message(Command("image"))
@router.message(Command("deepseek"))
@router.message(Command("analysis"))
@router.message(Command("kimi"))
@router.message(Command("vision"))
@router.message(F.text == MENU_AI_CHAT)
@router.message(F.text == "JO AI Chat")
@router.message(F.text == MENU_AI_CODE)
@router.message(F.text == "Code Generator")
@router.message(F.text == MENU_AI_RESEARCH)
@router.message(F.text == "Research")
@router.message(F.text == MENU_AI_PROMPT)
@router.message(F.text == "Prompt Generator")
@router.message(F.text == MENU_AI_IMAGE)
@router.message(F.text == "Image Generator")
@router.message(F.text == MENU_AI_DEEPSEEK)
@router.message(F.text == MENU_AI_KIMI)
@router.message(F.text == MENU_AI_TOOLS)
@router.message(F.text == "AI Tools")
@router.message(F.text == MENU_JO_AI)
@router.message(F.text == "Jo AI")
async def open_jo_ai_menu(message: Message, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not message.from_user:
        return

    text = (message.text or "").strip().lower()
    if text in {"/chat", MENU_AI_CHAT.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.CHAT, session_manager, miniapp_url)
        return
    if text in {"/code", MENU_AI_CODE.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.CODE, session_manager, miniapp_url)
        return
    if text in {"/research", MENU_AI_RESEARCH.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.RESEARCH, session_manager, miniapp_url)
        return
    if text in {"/prompt", MENU_AI_PROMPT.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.PROMPT, session_manager, miniapp_url)
        return
    if text in {"/image", MENU_AI_IMAGE.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.IMAGE, session_manager, miniapp_url)
        return
    if text in {"/kimi", "/vision", MENU_AI_KIMI.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.KIMI_IMAGE_DESCRIBER, session_manager, miniapp_url)
        return
    if text in {"/deepseek", "/analysis", MENU_AI_DEEPSEEK.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.DEEP_ANALYSIS, session_manager, miniapp_url)
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.AI_TOOLS_MENU)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await _show_jo_ai_menu(message)


@router.message(Command("exit_chat"))
async def exit_chat_command(message: Message, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not message.from_user:
        return
    transition = await session_manager.switch_feature(message.from_user.id, Feature.AI_TOOLS_MENU)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer("↩️ Exited current mode. Returning to AI tools menu.")
    await _show_jo_ai_menu(message)


@router.callback_query(F.data == "joai:menu")
async def open_jo_ai_submenu_callback(
    query: CallbackQuery,
    session_manager: SessionManager,
    miniapp_url: str | None,
) -> None:
    if not query.from_user:
        await query.answer()
        return
    transition = await session_manager.switch_feature(query.from_user.id, Feature.AI_TOOLS_MENU)
    await query.answer()
    if isinstance(query.message, Message):
        if transition.notice:
            await query.message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
        await _show_jo_ai_menu(query.message)


@router.callback_query(F.data == "joai:chat")
async def enable_jo_chat(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.CHAT, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:code")
async def enable_code_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.CODE, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:research")
async def enable_research_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.RESEARCH, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:deep_analysis")
async def enable_deep_analysis_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.DEEP_ANALYSIS, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:prompt")
async def enable_prompt_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.PROMPT, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:image")
async def enable_image_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.IMAGE, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:kimi")
async def enable_kimi_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.KIMI_IMAGE_DESCRIBER, session_manager, miniapp_url)


@router.callback_query(F.data.startswith("joaiimg:type:"))
async def choose_image_type(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) != 3:
        await query.answer("⚠️ Invalid image style.", show_alert=True)
        return
    image_type = parts[2]
    label = IMAGE_TYPE_LABELS.get(image_type)
    if not label:
        await query.answer("⚠️ Unknown image style.", show_alert=True)
        return

    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.IMAGE:
            await query.answer("⏳ Image session expired. Send /image again.", show_alert=True)
            return
        session.jo_ai_image_type = image_type
        session.jo_ai_image_ratio = None

    await query.answer(f"✅ {label} selected.")
    if isinstance(query.message, Message):
        await query.message.answer(
            f"✅ <b>{label}</b> selected.\n\n"
            "Step 2/3: Choose an aspect ratio.\n"
            "Available ratios: 1:1, 16:9, 9:16.",
            reply_markup=image_ratio_keyboard(),
        )


@router.callback_query(F.data.startswith("joaiimg:ratio:"))
async def choose_image_ratio(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) != 3:
        await query.answer("⚠️ Invalid ratio option.", show_alert=True)
        return
    ratio = IMAGE_RATIO_TOKEN_MAP.get(parts[2])
    if not ratio:
        await query.answer("⚠️ Unsupported ratio.", show_alert=True)
        return

    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.IMAGE:
            await query.answer("⏳ Image session expired. Send /image again.", show_alert=True)
            return
        if not session.jo_ai_image_type:
            await query.answer("Pick an image style first.", show_alert=True)
            return
        session.jo_ai_image_ratio = ratio

    await query.answer(f"✅ Ratio {ratio} selected.")
    if isinstance(query.message, Message):
        await query.message.answer(
            f"✅ Ratio <b>{ratio}</b> selected.\n\n"
            "Step 3/3: Describe the image you want me to create.\n"
            "🎯 Be specific for better results.",
            reply_markup=jo_chat_keyboard(),
        )


@router.callback_query(F.data.startswith("joai:"))
async def handle_jo_ai_action(query: CallbackQuery) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.answer(
            "⚠️ Unknown AI action.\nPlease use the buttons below.",
            reply_markup=jo_ai_menu_keyboard(),
        )


@router.message(
    ActiveFeatureFilter(Feature.JO_AI),
    F.text,
    ~F.text.in_(MENU_BUTTON_TEXTS),
    ~F.text.startswith("/"),
)
async def handle_jo_ai_text(
    message: Message,
    session_manager: SessionManager,
    chat_service: ChatService,
    image_generation_service: ImageGenerationService,
    deepseek_api_key: str | None,
    deepseek_model: str,
) -> None:
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("✍️ Please send a text message to continue.")
        return

    async with session_manager.lock(message.from_user.id) as session:
        mode = session.jo_ai_mode if session.active_feature == Feature.JO_AI else JoAIMode.MENU
        prompt_type = session.jo_ai_prompt_type
        image_type = session.jo_ai_image_type
        image_ratio = session.jo_ai_image_ratio
        code_file_name = session.jo_ai_code_file_name
        code_file_content = session.jo_ai_code_file_content
        history_snapshot = [{"role": role, "content": content} for role, content in session.jo_ai_chat_history]

    mode_options = _default_mode_options()
    user_text = text

    if mode == JoAIMode.CHAT:
        await _process_chat_message(message, user_text, session_manager, chat_service, history_snapshot, "chat", mode_options)
        return

    if mode == JoAIMode.CODE:
        debug_request = _is_code_debug_request(text)
        if debug_request and not code_file_content:
            async with session_manager.lock(message.from_user.id) as session:
                session.jo_ai_code_waiting_file = True
            await message.answer(
                "🛠 To debug or fix code, upload the file first in Code Generator mode.\n"
                "Then send your debug request.",
                reply_markup=jo_chat_keyboard(),
            )
            return

        if debug_request and code_file_content:
            user_text = _build_code_debug_request(text, code_file_name or "uploaded_code.txt", code_file_content)
        elif code_file_content and text.lower() in {"analyze file", "analyze", "review file"}:
            user_text = (
                f"Analyze this uploaded code file and suggest fixes.\n"
                f"Target file: {code_file_name or 'uploaded_code.txt'}\n\n"
                f"```text\n{code_file_content}\n```"
            )

        await _process_chat_message(message, user_text, session_manager, chat_service, [], "code", mode_options)
        return

    if mode == JoAIMode.RESEARCH:
        await _process_chat_message(message, user_text, session_manager, chat_service, [], "research", mode_options)
        return
    if mode == JoAIMode.DEEP_ANALYSIS:
        mode_options = _deep_analysis_mode_options(deepseek_api_key, deepseek_model)
        mode_prefix = str(mode_options.get("mode_prefix", "")).strip()
        deep_text = f"{mode_prefix}\n\n{text}" if mode_prefix else text
        await _process_chat_message(message, deep_text, session_manager, chat_service, [], "research", mode_options)
        return

    if mode == JoAIMode.PROMPT:
        await _process_prompt_message(message, user_text, session_manager, chat_service, prompt_type, mode_options)
        return
    if mode == JoAIMode.IMAGE:
        await _process_image_message(
            message,
            user_text,
            session_manager,
            chat_service,
            image_generation_service,
            image_type,
            image_ratio,
            mode_options,
        )
        return
    if mode == JoAIMode.KIMI_IMAGE_DESCRIBER:
        await message.answer(
            "🖼️ Send an image and I will describe it.\n"
            "💡 You can also include a short instruction.",
            reply_markup=jo_chat_keyboard(),
        )
        return

    await message.answer(
        "🤖 Pick an AI mode first from the menu below.",
        reply_markup=jo_ai_menu_keyboard(),
    )


@router.message(ActiveFeatureFilter(Feature.JO_AI), F.document)
async def handle_code_document_upload(
    message: Message,
    session_manager: SessionManager,
    chat_service: ChatService,
) -> None:
    if not message.from_user or not message.document:
        return

    async with session_manager.lock(message.from_user.id) as session:
        mode = session.jo_ai_mode if session.active_feature == Feature.JO_AI else JoAIMode.MENU

    if mode != JoAIMode.CODE:
        await message.answer(
            "📎 File upload analysis is available only in <b>Code Generator</b> mode.",
            reply_markup=jo_chat_keyboard(),
        )
        return

    document = message.document
    file_name = document.file_name or "uploaded_code.txt"
    file_size = int(document.file_size or 0)
    if file_size > MAX_CODE_UPLOAD_BYTES:
        await message.answer(
            "⚠️ File is too large for code analysis here.\nPlease upload a file smaller than 1.5MB.",
            reply_markup=jo_chat_keyboard(),
        )
        return
    if not _file_is_code_like(file_name):
        await message.answer(
            "⚠️ Please upload a source-code or text file for debugging.",
            reply_markup=jo_chat_keyboard(),
        )
        return

    progress_message = await _send_progress_message(message, "📥 Reading uploaded code file...")
    try:
        file = await message.bot.get_file(document.file_id)
        downloaded = await message.bot.download_file(file.file_path)
        raw_bytes = downloaded.read()
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Failed to download uploaded code file.")
        await message.answer("⚠️ I could not read that file. Please upload it again.")
        return

    decoded = _decode_uploaded_code_file(raw_bytes)
    if not decoded:
        await _clear_progress_message(progress_message)
        await message.answer(
            "⚠️ I couldn't decode that file as text code.\nUpload a plain text source file.",
            reply_markup=jo_chat_keyboard(),
        )
        return

    async with session_manager.lock(message.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.CODE:
            await _clear_progress_message(progress_message)
            await message.answer("⏳ Code session expired. Send /code and try again.")
            return
        session.jo_ai_code_file_name = file_name
        session.jo_ai_code_file_content = decoded
        session.jo_ai_code_waiting_file = False

    await _clear_progress_message(progress_message)
    caption_text = (message.caption or "").strip()
    if caption_text:
        mode_options = _default_mode_options()
        if _is_code_debug_request(caption_text):
            user_text = _build_code_debug_request(caption_text, file_name, decoded)
        else:
            user_text = (
                f"Use this uploaded file as the main context.\n"
                f"File: {file_name}\n"
                f"User request: {caption_text}\n\n"
                f"```text\n{decoded}\n```"
            )
        await _process_chat_message(message, user_text, session_manager, chat_service, [], "code", mode_options)
        return

    await message.answer(
        f"✅ File received: <b>{html.escape(file_name)}</b>\n"
        "Now send what you want me to debug or fix.",
        reply_markup=jo_chat_keyboard(),
    )


@router.message(ActiveFeatureFilter(Feature.JO_AI), F.photo)
async def handle_kimi_photo(
    message: Message,
    session_manager: SessionManager,
    chat_service: ChatService,
    kimi_api_key: str | None,
    kimi_model: str,
) -> None:
    if not message.from_user or not message.photo:
        return
    async with session_manager.lock(message.from_user.id) as session:
        mode = session.jo_ai_mode if session.active_feature == Feature.JO_AI else JoAIMode.MENU
    if mode != JoAIMode.KIMI_IMAGE_DESCRIBER:
        await message.answer(
            "🖼️ To describe images, first open <b>JO AI Vision</b> mode.",
            reply_markup=jo_chat_keyboard(),
        )
        return

    progress_message = await _send_progress_message(message, "🖼️ Analyzing your image...")
    largest = message.photo[-1]
    async with session_manager.lock(message.from_user.id) as session:
        session.jo_ai_last_image_file_id = largest.file_id
    try:
        description = await _run_kimi_with_progress(
            message,
            _describe_kimi_file_id(message, chat_service, largest.file_id, kimi_api_key, kimi_model),
        )
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        if _is_kimi_unclear_result(str(exc)):
            await message.answer(
                "🤔 I couldn't clearly understand this image.\n"
                "Try another image with better lighting or clarity.",
                reply_markup=kimi_result_keyboard(),
            )
            return
        if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            await message.answer(
                "⏳ I couldn't describe this image in time.\nPlease try again.",
                reply_markup=kimi_result_keyboard(),
            )
            return
        await message.answer(
            _friendly_error_text("JO AI Vision is temporarily unavailable", exc),
            reply_markup=kimi_result_keyboard(),
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Failed to download user image.")
        await message.answer("⚠️ I couldn't read that image file.\nPlease send another one.")
        return

    await _clear_progress_message(progress_message)
    if not description.strip():
        await message.answer(
            "🤔 I couldn't clearly understand this image.\nPlease try another image.",
            reply_markup=kimi_result_keyboard(),
        )
        return

    await _send_formatted_ai_reply(message, "chat", description, kimi_result_keyboard())


@router.callback_query(F.data == "joai:kimi_retry")
async def kimi_retry_same_image(
    query: CallbackQuery,
    session_manager: SessionManager,
    chat_service: ChatService,
    kimi_api_key: str | None,
    kimi_model: str,
) -> None:
    if not query.from_user:
        await query.answer()
        return

    async with session_manager.lock(query.from_user.id) as session:
        last_file_id = session.jo_ai_last_image_file_id
        mode = session.jo_ai_mode if session.active_feature == Feature.JO_AI else JoAIMode.MENU

    if mode != JoAIMode.KIMI_IMAGE_DESCRIBER or not last_file_id:
        await query.answer("⚠️ No image to retry. Send a new image first.", show_alert=True)
        return

    await query.answer("🔁 Retrying same image...")
    if isinstance(query.message, Message):
        progress_message = await _send_progress_message(query.message, "🖼️ Re-analyzing the same image...")
        try:
            description = await _run_kimi_with_progress(
                query.message,
                _describe_kimi_file_id(query.message, chat_service, last_file_id, kimi_api_key, kimi_model),
            )
        except AIServiceError as exc:
            await _clear_progress_message(progress_message)
            if _is_kimi_unclear_result(str(exc)):
                await query.message.answer(
                    "🤔 I still couldn't clearly understand this image.\nTry a clearer image.",
                    reply_markup=kimi_result_keyboard(),
                )
            elif "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
                await query.message.answer(
                    "⏳ I couldn't describe this image in time.\nPlease try again.",
                    reply_markup=kimi_result_keyboard(),
                )
            else:
                await query.message.answer(
                    _friendly_error_text("JO AI Vision is temporarily unavailable", exc),
                    reply_markup=kimi_result_keyboard(),
                )
            return
        except Exception:
            await _clear_progress_message(progress_message)
            logger.exception("Unexpected vision retry callback error.")
            await query.message.answer(
                "⚠️ I couldn't process that image right now.\nPlease try again shortly.",
                reply_markup=kimi_result_keyboard(),
            )
            return

        await _clear_progress_message(progress_message)
        if not description.strip():
            await query.message.answer(
                "🤔 I still couldn't clearly understand this image.\nTry another image.",
                reply_markup=kimi_result_keyboard(),
            )
            return
        await _send_formatted_ai_reply(query.message, "chat", description, kimi_result_keyboard())


async def _describe_kimi_file_id(
    message: Message,
    chat_service: ChatService,
    file_id: str,
    kimi_api_key: str | None,
    kimi_model: str,
) -> str:
    file = await message.bot.get_file(file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    image_bytes = file_bytes.read()

    prompt = "Describe what you see in this image briefly and clearly."
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            return await chat_service.generate_reply_with_image(
                prompt,
                image_bytes,
                mode="image_describe",
                model_override=kimi_model,
                api_key_override=kimi_api_key,
                thinking=False,
            )
    except AIServiceError:
        # Retry once with a simpler, object-focused instruction.
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            return await chat_service.generate_reply_with_image(
                "What is the main object in this image?",
                image_bytes,
                mode="image_describe",
                model_override=kimi_model,
                api_key_override=kimi_api_key,
                thinking=False,
            )


async def _run_kimi_with_progress(message: Message, work_coro) -> str:
    task = asyncio.create_task(work_coro)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=25)
    except asyncio.TimeoutError:
        await message.answer(
            "⏳ Still working on it...\n"
            "I'm retrying once to extract the image details."
        )
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=25)
        except asyncio.TimeoutError as exc:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise AIServiceError("Vision request timed out.") from exc


async def _process_chat_message(
    message: Message,
    user_text: str,
    session_manager: SessionManager,
    chat_service: ChatService,
    history: list[dict[str, str]],
    mode: Literal["chat", "code", "research", "prompt", "image_prompt"],
    mode_options: dict[str, object],
) -> None:
    show_progress_message = mode not in {"chat", "code"}
    if show_progress_message:
        await _maybe_send_engagement(message)
    progress_message: Message | None = None
    if show_progress_message:
        progress_text = MODE_PROGRESS_TEXT.get(mode, "🤖 Working on it...")
        progress_message = await _send_progress_message(message, progress_text)
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            reply = await chat_service.generate_reply(
                user_text,
                history=history,
                mode=mode,
                model_override=mode_options.get("model_override"),  # type: ignore[arg-type]
                api_key_override=mode_options.get("api_key_override"),  # type: ignore[arg-type]
                thinking=bool(mode_options.get("thinking", False)),
            )
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        await message.answer(_friendly_error_text("AI is unavailable right now", exc), reply_markup=jo_chat_keyboard())
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected JO AI error.")
        await message.answer(_friendly_error_text("Unexpected AI failure"), reply_markup=jo_chat_keyboard())
        return

    await _clear_progress_message(progress_message)
    if message.from_user:
        async with session_manager.lock(message.from_user.id) as session:
            if session.active_feature == Feature.JO_AI and session.jo_ai_mode == JoAIMode.CHAT:
                session.jo_ai_chat_history.append(("user", _compact_history_entry(user_text)))
                session.jo_ai_chat_history.append(("assistant", _compact_history_entry(reply)))
    await _send_formatted_ai_reply(message, mode, reply, jo_chat_keyboard())


async def _process_prompt_message(
    message: Message,
    user_text: str,
    session_manager: SessionManager,
    chat_service: ChatService,
    current_prompt_type: str | None,
    mode_options: dict[str, object],
) -> None:
    if not message.from_user:
        return
    if not current_prompt_type:
        async with session_manager.lock(message.from_user.id) as session:
            if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.PROMPT:
                await message.answer("⏳ Prompt session expired. Send /prompt to start again.")
                return
            session.jo_ai_prompt_type = user_text
        await message.answer(
            "✅ Prompt type saved.\n\n"
            "Step 2/2: Describe what you want for that prompt type.\n"
            "🎯 Include audience, tone, and constraints if possible.",
            reply_markup=jo_chat_keyboard(),
        )
        return

    await _maybe_send_engagement(message)
    prompt_request = f"Prompt type: {current_prompt_type}\nUser goal/details: {user_text}\nGenerate one optimized prompt."
    progress_message = await _send_progress_message(message, "✨ Generating your optimized prompt...")
    try:
        prompt_output = await chat_service.generate_reply(
            prompt_request,
            history=[],
            mode="prompt",
            model_override=mode_options.get("model_override"),  # type: ignore[arg-type]
            api_key_override=mode_options.get("api_key_override"),  # type: ignore[arg-type]
            thinking=bool(mode_options.get("thinking", False)),
        )
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        await message.answer(_friendly_error_text("Prompt generation failed", exc), reply_markup=jo_chat_keyboard())
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected prompt generation error.")
        await message.answer(_friendly_error_text("Unexpected prompt generation error"), reply_markup=jo_chat_keyboard())
        return
    await _clear_progress_message(progress_message)
    await _send_formatted_ai_reply(message, "prompt", prompt_output, jo_chat_keyboard())


async def _process_image_message(
    message: Message,
    user_text: str,
    session_manager: SessionManager,
    chat_service: ChatService,
    image_generation_service: ImageGenerationService,
    current_image_type: str | None,
    current_image_ratio: str | None,
    mode_options: dict[str, object],
) -> None:
    if not current_image_type:
        await message.answer(
            "🎨 Step 1/3: Choose an image style first.",
            reply_markup=image_type_keyboard(),
        )
        return
    if current_image_ratio not in IMAGE_RATIO_TO_SIZE:
        await message.answer(
            "📐 Step 2/3: Choose an aspect ratio first.",
            reply_markup=image_ratio_keyboard(),
        )
        return
    await _maybe_send_engagement(message)

    style_label = IMAGE_TYPE_LABELS.get(current_image_type, current_image_type)
    ratio_label = IMAGE_RATIO_LABELS.get(current_image_ratio, "1:1")
    image_size = IMAGE_RATIO_TO_SIZE.get(current_image_ratio, IMAGE_RATIO_TO_SIZE["1:1"])
    style_hint = IMAGE_TYPE_STYLE_HINTS.get(current_image_type, "high quality image")
    prompt_request = (
        f"Image type: {style_label}\n"
        f"Aspect ratio: {ratio_label}\n"
        f"Style hints: {style_hint}\n"
        f"User description: {user_text}\n"
        "Generate one optimized image prompt with subject detail, lighting, environment, style and quality tags."
    )
    progress_message = await _send_progress_message(message, "🧠 Optimizing your image prompt...")
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            optimized_prompt = await chat_service.generate_reply(
                prompt_request,
                history=[],
                mode="image_prompt",
                model_override=mode_options.get("model_override"),  # type: ignore[arg-type]
                api_key_override=mode_options.get("api_key_override"),  # type: ignore[arg-type]
                thinking=bool(mode_options.get("thinking", False)),
            )
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        await message.answer(_friendly_error_text("Image prompt optimization failed", exc), reply_markup=jo_chat_keyboard())
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected image prompt optimization error.")
        await message.answer(_friendly_error_text("Unexpected image optimization error"), reply_markup=jo_chat_keyboard())
        return

    cleaned_prompt = optimized_prompt.replace("Optimized Prompt:", "").strip() or optimized_prompt.strip()
    if progress_message is not None:
        with suppress(TelegramBadRequest):
            await progress_message.edit_text("🎨 Creating your image...")
    try:
        async with ChatActionSender.upload_photo(bot=message.bot, chat_id=message.chat.id):
            generated = await image_generation_service.generate_image(
                cleaned_prompt,
                size=image_size,
                ratio=ratio_label,
            )
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        await message.answer(
            (
                "⚠️ <b>Image generation is temporarily unavailable.</b>\n"
                f"{BRANDING_LINE}\n"
                "You can still use this optimized prompt manually:\n\n"
                f"<code>{html.escape(cleaned_prompt)}</code>\n\n"
                f"For JO API access, contact {DEVELOPER_HANDLE}."
            ),
            reply_markup=jo_chat_keyboard(),
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected image generation error.")
        await message.answer(_friendly_error_text("Unexpected image generation error"), reply_markup=jo_chat_keyboard())
        return

    await _clear_progress_message(progress_message)
    if generated.image_bytes:
        image_file = BufferedInputFile(generated.image_bytes, filename="jo_ai_generated.png")
        await message.answer_photo(
            photo=image_file,
            caption=(
                "🎉 <b>Your image is ready</b>\n\n"
                f"🎨 Style: <b>{html.escape(style_label)}</b>\n"
                f"📐 Ratio: <b>{html.escape(ratio_label)}</b>\n"
                "📌 Prompt used:\n"
                f"<code>{html.escape(cleaned_prompt[:900])}</code>"
            ),
            reply_markup=jo_chat_keyboard(),
        )
        return

    if generated.image_url:
        await message.answer_photo(
            photo=generated.image_url,
            caption=(
                "🎉 <b>Your image is ready</b>\n\n"
                f"🎨 Style: <b>{html.escape(style_label)}</b>\n"
                f"📐 Ratio: <b>{html.escape(ratio_label)}</b>\n"
                "📌 Prompt used:\n"
                f"<code>{html.escape(cleaned_prompt[:900])}</code>"
            ),
            reply_markup=jo_chat_keyboard(),
        )
        return

    await message.answer(
        _friendly_error_text("Image generation is temporarily unavailable"),
        reply_markup=jo_chat_keyboard(),
    )


@router.message(ActiveFeatureFilter(Feature.JO_AI))
async def jo_ai_unexpected_input(message: Message) -> None:
    await message.answer(
        "📩 Send text in the current JO AI mode.\n"
        "📎 In Code Generator mode, you can upload a code file for debug/fix.\n"
        "🖼️ In Vision mode, send an image.\n"
        "💡 You can switch mode anytime.",
        reply_markup=jo_ai_menu_keyboard(),
    )
