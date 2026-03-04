from __future__ import annotations

import asyncio
import logging
import random
from contextlib import suppress
from typing import Literal

from aiogram import F, Router
from aiogram.filters import Command
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
    deepseek_model_keyboard,
    image_type_keyboard,
    jo_ai_menu_keyboard,
    jo_chat_keyboard,
    kimi_result_keyboard,
)
from bot.keyboards.menu import ai_tools_keyboard, main_menu_keyboard
from bot.models.session import AIModelProfile, Feature, JoAIMode
from bot.services.ai_service import AIServiceError, ChatService, ImageGenerationService
from bot.services.session_manager import SessionManager

router = Router(name="jo_ai")
logger = logging.getLogger(__name__)

JO_AI_MENU_TEXT = (
    "AI Tools - Choose a mode:\n\n"
    "- JO AI Chat\n"
    "- Code Generator\n"
    "- Research\n"
    "- Prompt Generator\n"
    "- Image Generator\n"
    "- Kimi Image Describer\n"
    "- DeepSeek Models"
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

MODEL_PROFILE_LABELS = {
    AIModelProfile.DEEPSEEK_THINKING: "DeepSeek Thinking",
    AIModelProfile.DEEPSEEK_REASONING: "DeepSeek Reasoning",
}

ENGAGEMENT_LINES = (
    "Working on it...",
    "Analyzing your request...",
    "Optimizing the response...",
)


def _profile_options(profile: AIModelProfile, deepseek_api_key: str | None, deepseek_model: str) -> dict[str, object]:
    if profile == AIModelProfile.DEEPSEEK_THINKING:
        return {
            "model_override": deepseek_model,
            "api_key_override": deepseek_api_key,
            "thinking": True,
            "profile_prefix": "Thinking mode: explore alternatives, then provide a concise answer.",
        }
    return {
        "model_override": deepseek_model,
        "api_key_override": deepseek_api_key,
        "thinking": False,
        "profile_prefix": "Reasoning mode: use clear, logical, stepwise reasoning for accuracy.",
    }


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
            if mode != JoAIMode.KIMI_IMAGE_DESCRIBER:
                session.jo_ai_kimi_waiting_image = False


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
        await message.answer("JO AI Chat is active. Send any message.", reply_markup=jo_chat_keyboard())
        return
    if mode == JoAIMode.CODE:
        await message.answer("Code Generator mode is active. Describe the code you need.", reply_markup=jo_chat_keyboard())
        return
    if mode == JoAIMode.RESEARCH:
        await message.answer("Research mode is active. Send your topic/question.", reply_markup=jo_chat_keyboard())
        return
    if mode == JoAIMode.PROMPT:
        await message.answer(
            "Prompt Generator mode is active.\nStep 1/2: Tell me the prompt type (image, coding, video, research...).",
            reply_markup=jo_chat_keyboard(),
        )
        return
    if mode == JoAIMode.IMAGE:
        await message.answer("Image Generator mode is active. Choose image style:", reply_markup=image_type_keyboard())
        return
    await message.answer(
        "Kimi Image Describer is active.\nSend an image and I will describe what I see.",
        reply_markup=jo_chat_keyboard(),
    )


async def _maybe_send_engagement(message: Message) -> None:
    if random.random() < 0.35:
        await message.answer(random.choice(ENGAGEMENT_LINES))


def _is_kimi_unclear_result(error_text: str) -> bool:
    lower = error_text.lower()
    return "empty image description" in lower or "did not return image description choices" in lower


@router.message(Command("joai"))
@router.message(Command("chat"))
@router.message(Command("code"))
@router.message(Command("research"))
@router.message(Command("prompt"))
@router.message(Command("image"))
@router.message(Command("deepseek"))
@router.message(Command("kimi"))
@router.message(F.text == MENU_AI_CHAT)
@router.message(F.text == MENU_AI_CODE)
@router.message(F.text == MENU_AI_RESEARCH)
@router.message(F.text == MENU_AI_PROMPT)
@router.message(F.text == MENU_AI_IMAGE)
@router.message(F.text == MENU_AI_DEEPSEEK)
@router.message(F.text == MENU_AI_KIMI)
@router.message(F.text == MENU_AI_TOOLS)
@router.message(F.text == MENU_JO_AI)
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
    if text in {"/kimi", MENU_AI_KIMI.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.KIMI_IMAGE_DESCRIBER, session_manager, miniapp_url)
        return
    if text in {"/deepseek", MENU_AI_DEEPSEEK.lower()}:
        await message.answer("Choose DeepSeek profile:", reply_markup=deepseek_model_keyboard())
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
        await query.answer("Invalid image style.", show_alert=True)
        return
    image_type = parts[2]
    label = IMAGE_TYPE_LABELS.get(image_type)
    if not label:
        await query.answer("Unknown image style.", show_alert=True)
        return

    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.IMAGE:
            await query.answer("Image session expired. Send /image again.", show_alert=True)
            return
        session.jo_ai_image_type = image_type

    await query.answer(f"{label} selected.")
    if isinstance(query.message, Message):
        await query.message.answer(f"{label} selected.\nNow describe the image you want.", reply_markup=jo_chat_keyboard())


@router.callback_query(F.data.startswith("joaimodel:"))
async def choose_model_profile(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    value = (query.data or "").split(":")[-1]
    mapping = {
        "deepseek_thinking": AIModelProfile.DEEPSEEK_THINKING,
        "deepseek_reasoning": AIModelProfile.DEEPSEEK_REASONING,
    }
    profile = mapping.get(value)
    if not profile:
        await query.answer("Unknown model profile.", show_alert=True)
        return

    async with session_manager.lock(query.from_user.id) as session:
        session.ai_model_profile = profile
        session.active_feature = Feature.JO_AI
        session.jo_ai_mode = JoAIMode.CHAT

    label = MODEL_PROFILE_LABELS.get(profile, "Unknown")
    await query.answer(f"{label} selected.")
    if isinstance(query.message, Message):
        await query.message.answer(
            f"Profile set to <b>{label}</b>.\nJO AI Chat is active now. Send your message.",
            reply_markup=jo_chat_keyboard(),
        )


@router.callback_query(F.data.startswith("joai:"))
async def handle_jo_ai_action(query: CallbackQuery) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.answer("Unknown AI action. Please use menu buttons.", reply_markup=jo_ai_menu_keyboard())


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
        await message.answer("Please send text input.")
        return

    async with session_manager.lock(message.from_user.id) as session:
        mode = session.jo_ai_mode if session.active_feature == Feature.JO_AI else JoAIMode.MENU
        prompt_type = session.jo_ai_prompt_type
        image_type = session.jo_ai_image_type
        model_profile = session.ai_model_profile
        history_snapshot = [{"role": role, "content": content} for role, content in session.jo_ai_chat_history]
    profile_options = _profile_options(model_profile, deepseek_api_key, deepseek_model)
    profile_prefix = str(profile_options.get("profile_prefix", "")).strip()
    user_text = f"{profile_prefix}\n\n{text}" if profile_prefix else text

    if mode == JoAIMode.CHAT:
        await _process_chat_message(message, user_text, session_manager, chat_service, history_snapshot, "chat", profile_options)
        return
    if mode == JoAIMode.CODE:
        await _process_chat_message(message, user_text, session_manager, chat_service, [], "code", profile_options)
        return
    if mode == JoAIMode.RESEARCH:
        await _process_chat_message(message, user_text, session_manager, chat_service, [], "research", profile_options)
        return
    if mode == JoAIMode.PROMPT:
        await _process_prompt_message(message, user_text, session_manager, chat_service, prompt_type, profile_options)
        return
    if mode == JoAIMode.IMAGE:
        await _process_image_message(
            message, user_text, session_manager, chat_service, image_generation_service, image_type, profile_options
        )
        return
    if mode == JoAIMode.KIMI_IMAGE_DESCRIBER:
        await message.answer("Send an image so I can describe it.", reply_markup=jo_chat_keyboard())
        return

    await message.answer("Pick an AI mode first.", reply_markup=jo_ai_menu_keyboard())


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
        await message.answer("To describe images, first open Kimi Image Describer mode.", reply_markup=jo_chat_keyboard())
        return

    await message.answer("Analyzing your image now...")
    largest = message.photo[-1]
    async with session_manager.lock(message.from_user.id) as session:
        session.jo_ai_last_image_file_id = largest.file_id
    try:
        description = await _run_kimi_with_progress(
            message,
            _describe_kimi_file_id(message, chat_service, largest.file_id, kimi_api_key, kimi_model),
        )
    except AIServiceError as exc:
        if _is_kimi_unclear_result(str(exc)):
            await message.answer(
                "I couldn't clearly understand this image. Please try another image with better lighting or clarity.",
                reply_markup=kimi_result_keyboard(),
            )
            return
        if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            await message.answer(
                "Couldn't describe this image in time. Please try again.",
                reply_markup=kimi_result_keyboard(),
            )
            return
        await message.answer(
            "Kimi image describer is temporarily unavailable or timed out. Please try again shortly.",
            reply_markup=kimi_result_keyboard(),
        )
        return
    except Exception:
        logger.exception("Failed to download user image.")
        await message.answer("I could not read that image. Please send another one.")
        return

    if not description.strip():
        await message.answer(
            "I couldn't clearly understand this image. Please try another image.",
            reply_markup=kimi_result_keyboard(),
        )
        return

    await message.answer(description, reply_markup=kimi_result_keyboard())


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
        await query.answer("No image to retry. Send a new image first.", show_alert=True)
        return

    await query.answer("Retrying same image...")
    if isinstance(query.message, Message):
        await query.message.answer("Trying again on the same image...")
        try:
            description = await _run_kimi_with_progress(
                query.message,
                _describe_kimi_file_id(query.message, chat_service, last_file_id, kimi_api_key, kimi_model),
            )
        except AIServiceError as exc:
            if _is_kimi_unclear_result(str(exc)):
                await query.message.answer(
                    "I still couldn't clearly understand this image. Try a clearer image.",
                    reply_markup=kimi_result_keyboard(),
                )
            elif "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
                await query.message.answer(
                    "Couldn't describe this image in time. Please try again.",
                    reply_markup=kimi_result_keyboard(),
                )
            else:
                await query.message.answer(
                    "Kimi image describer is temporarily unavailable or timed out. Please try again shortly.",
                    reply_markup=kimi_result_keyboard(),
                )
            return
        except Exception:
            logger.exception("Unexpected Kimi retry callback error.")
            await query.message.answer(
                "I couldn't process that image now. Please try again shortly.",
                reply_markup=kimi_result_keyboard(),
            )
            return

        if not description.strip():
            await query.message.answer(
                "I still couldn't clearly understand this image. Try another image.",
                reply_markup=kimi_result_keyboard(),
            )
            return
        await query.message.answer(description, reply_markup=kimi_result_keyboard())


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
        return await asyncio.wait_for(asyncio.shield(task), timeout=15)
    except asyncio.TimeoutError:
        await message.answer(
            "Wait, we're retrying to figure out the image details. "
            "Usually if it takes this long it might not work."
        )
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=15)
        except asyncio.TimeoutError as exc:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise AIServiceError("Kimi image description timed out.") from exc


async def _process_chat_message(
    message: Message,
    user_text: str,
    session_manager: SessionManager,
    chat_service: ChatService,
    history: list[dict[str, str]],
    mode: Literal["chat", "code", "research", "prompt", "image_prompt"],
    profile_options: dict[str, object],
) -> None:
    await _maybe_send_engagement(message)
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            reply = await chat_service.generate_reply(
                user_text,
                history=history,
                mode=mode,
                model_override=profile_options.get("model_override"),  # type: ignore[arg-type]
                api_key_override=profile_options.get("api_key_override"),  # type: ignore[arg-type]
                thinking=bool(profile_options.get("thinking", False)),
            )
    except AIServiceError as exc:
        await message.answer(f"AI is unavailable right now.\n{exc}", reply_markup=jo_chat_keyboard())
        return
    except Exception:
        logger.exception("Unexpected JO AI error.")
        await message.answer("AI failed unexpectedly. Please try again.", reply_markup=jo_chat_keyboard())
        return

    if message.from_user:
        async with session_manager.lock(message.from_user.id) as session:
            if session.active_feature == Feature.JO_AI and session.jo_ai_mode == JoAIMode.CHAT:
                session.jo_ai_chat_history.append(("user", user_text))
                session.jo_ai_chat_history.append(("assistant", reply))
    await message.answer(reply, reply_markup=jo_chat_keyboard())


async def _process_prompt_message(
    message: Message,
    user_text: str,
    session_manager: SessionManager,
    chat_service: ChatService,
    current_prompt_type: str | None,
    profile_options: dict[str, object],
) -> None:
    if not message.from_user:
        return
    if not current_prompt_type:
        async with session_manager.lock(message.from_user.id) as session:
            if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.PROMPT:
                await message.answer("Prompt session expired. Send /prompt to start again.")
                return
            session.jo_ai_prompt_type = user_text
        await message.answer("Step 2/2: Describe what you want for that prompt type.", reply_markup=jo_chat_keyboard())
        return

    await _maybe_send_engagement(message)
    prompt_request = f"Prompt type: {current_prompt_type}\nUser goal/details: {user_text}\nGenerate one optimized prompt."
    try:
        prompt_output = await chat_service.generate_reply(
            prompt_request,
            history=[],
            mode="prompt",
            model_override=profile_options.get("model_override"),  # type: ignore[arg-type]
            api_key_override=profile_options.get("api_key_override"),  # type: ignore[arg-type]
            thinking=bool(profile_options.get("thinking", False)),
        )
    except AIServiceError as exc:
        await message.answer(f"Prompt generation failed.\n{exc}", reply_markup=jo_chat_keyboard())
        return
    except Exception:
        logger.exception("Unexpected prompt generation error.")
        await message.answer("Prompt generation failed unexpectedly. Please try again.", reply_markup=jo_chat_keyboard())
        return
    await message.answer(prompt_output, reply_markup=jo_chat_keyboard())


async def _process_image_message(
    message: Message,
    user_text: str,
    session_manager: SessionManager,
    chat_service: ChatService,
    image_generation_service: ImageGenerationService,
    current_image_type: str | None,
    profile_options: dict[str, object],
) -> None:
    if not current_image_type:
        await message.answer("Step 1/2: Choose an image style first.", reply_markup=image_type_keyboard())
        return
    await _maybe_send_engagement(message)

    style_label = IMAGE_TYPE_LABELS.get(current_image_type, current_image_type)
    style_hint = IMAGE_TYPE_STYLE_HINTS.get(current_image_type, "high quality image")
    prompt_request = (
        f"Image type: {style_label}\nStyle hints: {style_hint}\nUser description: {user_text}\n"
        "Generate one optimized image prompt with subject detail, lighting, environment, style and quality tags."
    )
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            optimized_prompt = await chat_service.generate_reply(
                prompt_request,
                history=[],
                mode="image_prompt",
                model_override=profile_options.get("model_override"),  # type: ignore[arg-type]
                api_key_override=profile_options.get("api_key_override"),  # type: ignore[arg-type]
                thinking=bool(profile_options.get("thinking", False)),
            )
    except AIServiceError as exc:
        await message.answer(f"Image prompt optimization failed.\n{exc}", reply_markup=jo_chat_keyboard())
        return
    except Exception:
        logger.exception("Unexpected image prompt optimization error.")
        await message.answer("Image optimization failed unexpectedly. Please try again.", reply_markup=jo_chat_keyboard())
        return

    cleaned_prompt = optimized_prompt.replace("Optimized Prompt:", "").strip() or optimized_prompt.strip()
    try:
        async with ChatActionSender.upload_photo(bot=message.bot, chat_id=message.chat.id):
            image_bytes = await image_generation_service.generate_image(cleaned_prompt)
    except AIServiceError as exc:
        await message.answer(
            "Image generation API is unavailable right now.\n"
            f"{exc}\n\nOptimized prompt:\n<code>{cleaned_prompt}</code>",
            reply_markup=jo_chat_keyboard(),
        )
        return
    except Exception:
        logger.exception("Unexpected image generation error.")
        await message.answer("Image generation failed unexpectedly. Please try again.", reply_markup=jo_chat_keyboard())
        return

    image_file = BufferedInputFile(image_bytes, filename="jo_ai_generated.png")
    await message.answer_photo(
        photo=image_file,
        caption=f"Style: {style_label}\nPrompt used:\n<code>{cleaned_prompt[:900]}</code>",
        reply_markup=jo_chat_keyboard(),
    )


@router.message(ActiveFeatureFilter(Feature.JO_AI))
async def jo_ai_unexpected_input(message: Message) -> None:
    await message.answer("Please send text, or send an image in Kimi Image Describer mode.", reply_markup=jo_ai_menu_keyboard())
