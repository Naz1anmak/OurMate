"""Обработчик для групповых сообщений."""
import asyncio
import time
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramNetworkError
from aiogram.types import Message

from src.config.settings import OWNER_CHAT_ID
from src.bot.services.llm_service import LLMService, LLMServiceError
from src.bot.services.context_service import context_service
from src.bot.services.birthday_service import birthday_service
from src.utils.text_utils import get_first_name_by_user_id
from src.utils.log_utils import log_with_ts as _log
from src.utils.render_utils import render_html_with_code
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
    ERROR_NOTICE_TEXT,
    ERROR_NOTICE_ENTITIES,
)
from src.bot.handlers.placeholder_variants import pick_placeholder_variant
from src.utils.emoji_utils import make_custom_emoji_payload

ERROR_CUSTOM_EMOJI_ID = "5447644880824181073"
FALLBACK_EDIT_TIMEOUT_SEC = 12.0
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
    notice = (
        "⚠️ Telegram delivery issue (group fallback)\n"
        f"От: {user_login_safe} (chat_id={message.chat.id}, type={message.chat.type})\n"
        f"Ответ (фрагмент): {final_answer[:500]}\n"
        f"Ошибка: {err}"
    )
    try:
        await message.bot.send_message(OWNER_CHAT_ID, notice)
    except Exception:
        pass

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
        _log(f"GR; Duplicate message skipped: chat_id={chat_id}, message_id={message.message_id}")
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
        _log(f"GR; От {user_login} ({user_name}){reply_context_note}: {text_for_llm}")
    else:
        _log(f"GR; От {user_name}{reply_context_note}: {text_for_llm}")

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
        _log("GR; Stream placeholder missing, creating new for fallback")
        try:
            placeholder = pick_placeholder_variant()
            placeholder_text, placeholder_entities = placeholder.reply_payload()
            temp_msg = await message.reply(placeholder_text, entities=placeholder_entities)
        except TelegramBadRequest as exc:
            _log(f"GR; Fallback placeholder custom emoji failed, plain retry: {exc}")
            try:
                temp_msg = await message.reply(placeholder_text)
            except Exception:
                temp_msg = None
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
            _log(f"GR; Бот (LLM) для {user_login_safe}: {final_answer}")
            return
        except TelegramRetryAfter as exc:
            _log(f"GR; Fallback final edit throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=safe_answer,
                    parse_mode="HTML",
                )
                _log(f"GR; Бот (LLM) для {user_login_safe}: {final_answer}")
                return
            except Exception as retry_exc:
                _log(f"GR; Fallback final edit failed after retry (status unknown): {retry_exc}")
                await _notify_owner_delivery_issue(message, user_login_safe, final_answer, retry_exc)
                return
        except asyncio.TimeoutError as exc:
            _log(f"GR; Fallback final edit timeout ({FALLBACK_EDIT_TIMEOUT_SEC:.0f}s, status unknown)")
            await _notify_owner_delivery_issue(message, user_login_safe, final_answer, exc)
            return
        except TelegramNetworkError as exc:
            _log(f"GR; Fallback final edit network failed (status unknown): {exc}")
            await _notify_owner_delivery_issue(message, user_login_safe, final_answer, exc)
            return
        except TelegramBadRequest as exc:
            if "message is too long" in str(exc).lower():
                try:
                    await message.reply(ERROR_NOTICE_TEXT, entities=ERROR_NOTICE_ENTITIES)
                except TelegramBadRequest:
                    try:
                        await message.reply(ERROR_NOTICE_PLAIN, parse_mode=None)
                    except Exception:
                        pass
                except Exception:
                    pass
                return
            raise
        except Exception:
            _log("GR; Fallback final edit failed; keeping placeholder and sending separate final message")

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
        _log(f"GR; Бот (LLM) для {user_login_safe}: {final_answer}")
    except TelegramBadRequest as exc:
        if "message is too long" in str(exc).lower():
            try:
                await message.reply(ERROR_NOTICE_TEXT, entities=ERROR_NOTICE_ENTITIES)
            except TelegramBadRequest:
                try:
                    await message.reply(ERROR_NOTICE_PLAIN, parse_mode=None)
                except Exception:
                    pass
            except Exception:
                pass
            return
        raise
    except TelegramRetryAfter as exc:
        _log(f"GR; Final send throttled: {exc}")
        try:
            await asyncio.sleep(exc.retry_after)
            await message.reply(final_answer, parse_mode="HTML")
            _log(f"GR; Бот (LLM) для {user_login_safe}: {final_answer}")
        except Exception:
            pass
    except TelegramNetworkError as exc:
        _log(f"GR; Final send network failed, placeholder stays as notice: {exc}")
        await _notify_owner_delivery_issue(message, user_login_safe, final_answer, exc)
        if temp_msg:
            try:
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=ERROR_NOTICE_TEXT,
                    entities=ERROR_NOTICE_ENTITIES,
                    parse_mode=None,
                )
            except TelegramBadRequest:
                try:
                    await message.bot.edit_message_text(
                        chat_id=temp_msg.chat.id,
                        message_id=temp_msg.message_id,
                        text=ERROR_NOTICE_PLAIN,
                        parse_mode=None,
                    )
                except Exception:
                    pass
            except Exception:
                pass
    except Exception as exc:
        # Не поднимаем исключение выше, чтобы не засорять aiogram.event огромным traceback при сетевых сбоях.
        _log(f"GR; Final send unexpected failure (suppressed): {exc}")
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
    _log(f"GR; Бот: LLM недоступен для {user_login_safe}: {llm_error}")
    fallback_text, fallback_entities = make_custom_emoji_payload(
        "⚠️ Я временно недоступен. Попробуй ещё раз через пару минут.",
        ERROR_CUSTOM_EMOJI_ID,
    )
    fallback_sent = False

    if temp_msg:
        try:
            await message.bot.edit_message_text(
                chat_id=temp_msg.chat.id,
                message_id=temp_msg.message_id,
                text=fallback_text,
                entities=fallback_entities,
            )
            fallback_sent = True
            temp_msg = None
        except TelegramRetryAfter as exc:
            _log(f"GR; Fallback error edit throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=fallback_text,
                    entities=fallback_entities,
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
            await message.reply(fallback_text, entities=fallback_entities)
        except Exception:
            pass

    owner_notice = (
        f"⚠️ LLM недоступен\n"
        f"От: {user_login_safe} (chat_id={chat_id}, type={message.chat.type})\n"
        f"Текст: {text_for_llm[:500]}\n"
        f"Ошибка: {llm_error}"
    )
    owner_entities = [fallback_entities[0]]
    try:
        await message.bot.send_message(OWNER_CHAT_ID, owner_notice, entities=owner_entities)
    except Exception:
        pass
