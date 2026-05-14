"""Обработчик для групповых сообщений."""
import asyncio
import logging
import time

from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramNetworkError
from aiogram.types import Message

from src.bot.handlers.errors import notify_owner_error
from src.bot.services.llm_service import LLMService, LLMServiceError
from src.bot.services.context_service import context_service
from src.bot.services.birthday_service import birthday_service
from src.utils.text_utils import get_first_name_by_user_id
from src.utils.render_utils import render_html_with_code

logger = logging.getLogger(__name__)
from src.bot.handlers.chat_context import (
    should_process_message,
    extract_user_login,
    strip_bot_mention,
    build_group_llm_input,
    build_llm_messages,
)
from src.bot.handlers.llm_flow import (
    try_streaming_response,
    format_final_answer,
    _trim_html,
    ERROR_NOTICE_PLAIN,
)
from src.bot.handlers.placeholder_variants import pick_placeholder_variant

FALLBACK_EDIT_TIMEOUT_SEC = 6.0
_PROCESSED_GROUP_MESSAGES: dict[tuple[int, int], float] = {}
_PROCESSED_GROUP_TTL_SECONDS = 300.0
_LAST_GROUP_DEDUP_CLEANUP_TS = 0.0

def _cleanup_processed_group_messages(now_ts: float) -> None:
    global _LAST_GROUP_DEDUP_CLEANUP_TS
    if now_ts - _LAST_GROUP_DEDUP_CLEANUP_TS < 60:
        return
    _LAST_GROUP_DEDUP_CLEANUP_TS = now_ts
    stale_keys = [
        key
        for key, ts in _PROCESSED_GROUP_MESSAGES.items()
        if (now_ts - ts) > _PROCESSED_GROUP_TTL_SECONDS
    ]
    for key in stale_keys:
        _PROCESSED_GROUP_MESSAGES.pop(key, None)


async def _notify_owner_delivery_issue(
    message: Message,
    user_login_safe: str,
    final_answer: str,
    err: Exception,
) -> None:
    await notify_owner_error(
        message.bot,
        err,
        tg_id=message.from_user.id if message.from_user else None,
        username=message.from_user.username if message.from_user else None,
        context="Telegram delivery (group)",
        extra=f"chat_id={message.chat.id}; ответ: {final_answer[:300]}",
    )

async def handle_group_chat(message: Message, bot_username: str, bot_id: int):
    chat_id = message.chat.id
    text = message.text or ""
    text_for_llm = strip_bot_mention(text, bot_username)

    if not should_process_message(message, bot_username, bot_id):
        return

    # Дедупликация на случай повторной доставки одного и того же апдейта при сетевых сбоях polling.
    message_key = (chat_id, message.message_id)
    now_ts = time.monotonic()
    _cleanup_processed_group_messages(now_ts)
    prev_ts = _PROCESSED_GROUP_MESSAGES.get(message_key)
    if prev_ts is not None and (now_ts - prev_ts) <= _PROCESSED_GROUP_TTL_SECONDS:
        logger.warning(f"GR; Duplicate message skipped: chat_id={chat_id}, message_id={message.message_id}")
        return
    _PROCESSED_GROUP_MESSAGES[message_key] = now_ts

    user_login = extract_user_login(message, text, bot_username)
    user_name = message.from_user.full_name or str(message.from_user.id)
    user_login_safe = user_login or user_name
    reply_context_used = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id != bot_id
        and ((message.reply_to_message.text or message.reply_to_message.caption) or "").strip()
    )
    reply_context_from = ""
    if reply_context_used and message.reply_to_message and message.reply_to_message.from_user:
        reply_from_user = message.reply_to_message.from_user
        reply_context_from = (
            f"@{reply_from_user.username}"
            if reply_from_user.username
            else (reply_from_user.full_name or str(reply_from_user.id))
        )
    reply_context_note = f" + reply-context from {reply_context_from}" if reply_context_from else (" + reply-context" if reply_context_used else "")
    if user_login:
        logger.info(f"GR; От {user_login} ({user_name}){reply_context_note}: {text_for_llm}")
    else:
        logger.info(f"GR; От {user_name}{reply_context_note}: {text_for_llm}")

    first_name = get_first_name_by_user_id(message.from_user.id, birthday_service.users)
    existing_context = context_service.get_context(chat_id)
    has_context = bool(existing_context)
    llm_input_text = build_group_llm_input(message, text_for_llm, bot_id)
    messages = build_llm_messages(chat_id, llm_input_text)

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

    temp_msg = placeholder_msg
    if temp_msg is None and len(text_for_llm.strip()) >= 8 and (placeholder_msg is not None or text_for_llm.strip()):
        logger.warning("GR; Stream placeholder missing, creating new for fallback")
        try:
            placeholder = pick_placeholder_variant()
            temp_msg = await message.reply(placeholder.text, parse_mode="HTML")
        except Exception:
            temp_msg = None

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
        await _handle_llm_error_gr(message, user_login, chat_id, text_for_llm, llm_error, temp_msg)
        return

    final_answer = format_final_answer(first_name, answer_body, has_context)
    # В контекст сохраняем ответ без префикса имени
    context_service.save_context(chat_id, text_for_llm, format_final_answer("", answer_body, has_context))
    safe_answer = _trim_html(render_html_with_code(final_answer))

    if temp_msg:
        try:
            await asyncio.wait_for(
                message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=safe_answer,
                    parse_mode="HTML",
                ),
                timeout=FALLBACK_EDIT_TIMEOUT_SEC,
            )
            logger.info(f"GR; Бот (LLM) для {user_login_safe}: {final_answer}")
            return
        except TelegramRetryAfter as exc:
            logger.warning(f"GR; Fallback final edit throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=safe_answer,
                    parse_mode="HTML",
                )
                logger.info(f"GR; Бот (LLM) для {user_login_safe}: {final_answer}")
                return
            except Exception as retry_exc:
                logger.warning(f"GR; Fallback final edit failed after retry (status unknown): {retry_exc}")
                await _notify_owner_delivery_issue(message, user_login_safe, final_answer, retry_exc)
                return
        except asyncio.TimeoutError as exc:
            logger.warning(f"GR; Fallback final edit timeout ({FALLBACK_EDIT_TIMEOUT_SEC:.0f}s, status unknown)")
            await _notify_owner_delivery_issue(message, user_login_safe, final_answer, exc)
            return
        except TelegramNetworkError as exc:
            logger.warning(f"GR; Fallback final edit network failed (status unknown): {exc}")
            await _notify_owner_delivery_issue(message, user_login_safe, final_answer, exc)
            return
        except TelegramBadRequest as exc:
            if "message is too long" in str(exc).lower():
                try:
                    await message.reply(ERROR_NOTICE_PLAIN, parse_mode="HTML")
                except Exception:
                    pass
                return
            raise
        except Exception:
            logger.warning("GR; Fallback final edit failed; keeping placeholder and sending separate final message")

    await _send_response_gr(message, safe_answer, user_login, temp_msg)

async def _send_response_gr(
    message: Message,
    final_answer: str,
    user_login: str,
    temp_msg: Message | None = None,
):
    user_login_safe = user_login or message.from_user.full_name or str(message.from_user.id)
    try:
        await message.reply(final_answer, parse_mode="HTML")
        logger.info(f"GR; Бот (LLM) для {user_login_safe}: {final_answer}")
    except TelegramBadRequest as exc:
        if "message is too long" in str(exc).lower():
            try:
                await message.reply(ERROR_NOTICE_PLAIN, parse_mode="HTML")
            except Exception:
                pass
            return
        raise
    except TelegramRetryAfter as exc:
        logger.warning(f"GR; Final send throttled: {exc}")
        try:
            await asyncio.sleep(exc.retry_after)
            await message.reply(final_answer, parse_mode="HTML")
            logger.info(f"GR; Бот (LLM) для {user_login_safe}: {final_answer}")
        except Exception:
            pass
    except TelegramNetworkError as exc:
        logger.warning(f"GR; Final send network failed, placeholder stays as notice: {exc}")
        await _notify_owner_delivery_issue(message, user_login_safe, final_answer, exc)
        if temp_msg:
            try:
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=ERROR_NOTICE_PLAIN,
                    parse_mode="HTML",
                )
            except Exception:
                pass
    except Exception as exc:
        # Не поднимаем исключение выше, чтобы не засорять aiogram.event огромным traceback при сетевых сбоях.
        logger.warning(f"GR; Final send unexpected failure (suppressed): {exc}")
        await _notify_owner_delivery_issue(message, user_login_safe, final_answer, exc)

async def _handle_llm_error_gr(
    message: Message,
    user_login: str,
    chat_id: int,
    text_for_llm: str,
    llm_error: str,
    temp_msg: Message | None = None,
):
    user_login_safe = user_login or message.from_user.full_name or str(message.from_user.id)
    logger.warning(f"GR; Бот: LLM недоступен для {user_login_safe}: {llm_error}")
    fallback_text = "⚠️ Я временно недоступен. Попробуй ещё раз через пару минут."
    fallback_sent = False

    if temp_msg:
        try:
            await message.bot.edit_message_text(
                chat_id=temp_msg.chat.id,
                message_id=temp_msg.message_id,
                text=fallback_text,
                parse_mode="HTML",
            )
            fallback_sent = True
            temp_msg = None
        except TelegramRetryAfter as exc:
            logger.warning(f"GR; Fallback error edit throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=fallback_text,
                    parse_mode="HTML",
                )
                fallback_sent = True
                temp_msg = None
            except Exception:
                pass
        except Exception:
            try:
                await temp_msg.delete()
            except Exception:
                pass

    if not fallback_sent:
        try:
            await message.reply(fallback_text, parse_mode="HTML")
        except Exception:
            pass

    await notify_owner_error(
        message.bot,
        Exception(llm_error),
        tg_id=message.from_user.id if message.from_user else None,
        username=message.from_user.username if message.from_user else None,
        context="LLM недоступен (GR)",
        extra=f"chat_id={chat_id}; запрос: {text_for_llm[:300]}",
    )
