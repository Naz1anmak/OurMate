"""Обработчик для личных сообщений."""
import asyncio
import logging

from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from aiogram.types import Message

from src.bot.services.llm_service import LLMService, LLMServiceError
from src.bot.services.context_service import context_service
from src.bot.services.birthday_service import birthday_service
from src.utils.text_utils import get_first_name_by_user_id
from src.utils.render_utils import render_html_with_code
from src.bot.handlers.chat_context import (
    should_process_message,
    extract_user_login,
    strip_bot_mention,
    build_llm_messages,
)
from src.bot.handlers.errors import notify_owner_error
from src.bot.handlers.llm_flow import try_streaming_response, format_final_answer

logger = logging.getLogger(__name__)

ERROR_NOTICE_PLAIN_PM = "⚠️ LLM временно недоступен. Попробуй ещё раз через пару минут."

async def handle_private_chat(message: Message, bot_username: str, bot_id: int):
    chat_id = message.chat.id
    text = message.text or ""
    text_for_llm = strip_bot_mention(text, bot_username)

    if not should_process_message(message, bot_username, bot_id):
        return

    user_login = extract_user_login(message, text, bot_username)
    user_name = message.from_user.full_name or str(message.from_user.id)
    user_login_safe = user_login or user_name
    if user_login:
        logger.info(f"PM; От {user_login} ({user_name}): {text_for_llm}")
    else:
        logger.info(f"PM; От {user_name}: {text_for_llm}")

    first_name = get_first_name_by_user_id(message.from_user.id, birthday_service.users)
    existing_context = context_service.get_context(chat_id)
    has_context = bool(existing_context)
    messages = build_llm_messages(chat_id, text_for_llm)

    streamed, placeholder_msg = await try_streaming_response(
        message,
        messages,
        first_name,
        user_login,
        text_for_llm,
        has_context,
    )
    if streamed:
        return

    logger.warning(f"PM; Stream не прошёл — запускаю полный запрос для {user_login_safe}")
    stop_event = asyncio.Event()

    async def _typing_indicator():
        try:
            while not stop_event.is_set():
                await message.bot.send_chat_action(message.chat.id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except Exception:
            pass

    answer_body = None
    llm_error = None
    typing_task = asyncio.create_task(_typing_indicator())
    try:
        answer_body = await asyncio.to_thread(LLMService.send_chat_request, messages)
    except LLMServiceError as exc:
        llm_error = f"LLMServiceError: {exc}"
    except Exception as exc:
        llm_error = f"Unexpected LLM error: {exc}"
    finally:
        stop_event.set()
        try:
            await typing_task
        except Exception:
            pass

    if llm_error:
        await _handle_llm_error_pm(message, user_login, chat_id, text_for_llm, llm_error, placeholder_msg)
        return

    final_answer = format_final_answer(first_name, answer_body, has_context)
    context_service.save_context(chat_id, text_for_llm, final_answer)
    safe_answer = render_html_with_code(final_answer)

    temp_msg = placeholder_msg  # в PM плейсхолдер обычно нет, но поддержим редактирование, если был
    if temp_msg:
        try:
            await message.bot.edit_message_text(
                chat_id=temp_msg.chat.id,
                message_id=temp_msg.message_id,
                text=safe_answer,
                parse_mode="HTML",
            )
            logger.info(f"PM; Бот (LLM) для {user_login_safe}: {final_answer}")
            return
        except TelegramRetryAfter as exc:
            logger.warning(f"PM; Fallback final edit throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=safe_answer,
                    parse_mode="HTML",
                )
                logger.info(f"PM; Бот (LLM) для {user_login_safe}: {final_answer}")
                return
            except Exception:
                pass
        except Exception:
            try:
                await temp_msg.delete()
            except Exception:
                pass

    await _send_response_pm(message, safe_answer, user_login, text)

async def _send_response_pm(message: Message, final_answer: str, user_login: str, original_text: str):
    user_login_safe = user_login or message.from_user.full_name or str(message.from_user.id)
    logger.info(f"PM; Бот (LLM) для {user_login_safe}: {final_answer}")
    try:
        await message.answer(final_answer, parse_mode="HTML")
    except TelegramRetryAfter as exc:
        logger.warning(f"PM; Final send throttled: {exc}")
        try:
            await asyncio.sleep(exc.retry_after)
            await message.answer(final_answer, parse_mode="HTML")
        except Exception:
            pass

async def _handle_llm_error_pm(
    message: Message,
    user_login: str,
    chat_id: int,
    text_for_llm: str,
    llm_error: str,
    temp_msg: Message | None = None,
):
    user_login_safe = user_login or message.from_user.full_name or str(message.from_user.id)
    logger.warning(f"PM; Бот: LLM недоступен для {user_login_safe}: {llm_error}")
    fallback_sent = False

    async def _edit_notice() -> bool:
        if not temp_msg:
            return False
        try:
            await message.bot.edit_message_text(
                chat_id=temp_msg.chat.id,
                message_id=temp_msg.message_id,
                text=ERROR_NOTICE_PLAIN_PM,
                parse_mode="HTML",
            )
            return True
        except TelegramRetryAfter as exc:
            logger.warning(f"PM; Fallback error edit throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=ERROR_NOTICE_PLAIN_PM,
                    parse_mode="HTML",
                )
                return True
            except Exception:
                return False
        except Exception:
            return False

    async def _send_notice() -> bool:
        try:
            await message.answer(ERROR_NOTICE_PLAIN_PM, parse_mode="HTML")
            return True
        except Exception as exc:
            logger.warning(f"PM; Fallback notice send failed: {exc}")
            return False

    if temp_msg:
        fallback_sent = await _edit_notice()

    if not fallback_sent:
        fallback_sent = await _send_notice()

    await notify_owner_error(
        message.bot,
        Exception(llm_error),
        tg_id=message.from_user.id if message.from_user else None,
        username=message.from_user.username if message.from_user else None,
        context="LLM недоступен (PM)",
        extra=f"chat_id={chat_id}; запрос: {text_for_llm[:300]}",
    )
