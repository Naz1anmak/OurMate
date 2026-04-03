"""Обработчик для личных сообщений."""
import asyncio
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
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
    build_llm_messages,
)
from src.bot.handlers.llm_flow import try_streaming_response, format_final_answer
from src.utils.emoji_utils import make_custom_emoji_payload

ERROR_CUSTOM_EMOJI_ID = "5447644880824181073"
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
        _log(f"PM; От {user_login} ({user_name}): {text_for_llm}")
    else:
        _log(f"PM; От {user_name}: {text_for_llm}")

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

    _log(f"PM; Stream не прошёл — запускаю полный запрос для {user_login_safe}")
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
            _log(f"PM; Бот (LLM) для {user_login_safe}: {final_answer}")
            return
        except TelegramRetryAfter as exc:
            _log(f"PM; Fallback final edit throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=safe_answer,
                    parse_mode="HTML",
                )
                _log(f"PM; Бот (LLM) для {user_login_safe}: {final_answer}")
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
    _log(f"PM; Бот (LLM) для {user_login_safe}: {final_answer}")
    try:
        await message.answer(final_answer, parse_mode="HTML")
    except TelegramRetryAfter as exc:
        _log(f"PM; Final send throttled: {exc}")
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
    _log(f"PM; Бот: LLM недоступен для {user_login_safe}: {llm_error}")
    fallback_text, fallback_entities = make_custom_emoji_payload(
        ERROR_NOTICE_PLAIN_PM,
        ERROR_CUSTOM_EMOJI_ID,
    )
    fallback_sent = False

    async def _edit_notice() -> bool:
        if not temp_msg:
            return False
        try:
            await message.bot.edit_message_text(
                chat_id=temp_msg.chat.id,
                message_id=temp_msg.message_id,
                text=fallback_text,
                entities=fallback_entities,
                parse_mode=None,
            )
            return True
        except TelegramBadRequest as exc:
            _log(f"PM; Fallback notice edit custom failed, plain retry: {exc}")
            try:
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=ERROR_NOTICE_PLAIN_PM,
                    parse_mode=None,
                )
                return True
            except Exception as exc2:
                _log(f"PM; Fallback notice edit plain failed: {exc2}")
                return False
        except TelegramRetryAfter as exc:
            _log(f"PM; Fallback error edit throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                await message.bot.edit_message_text(
                    chat_id=temp_msg.chat.id,
                    message_id=temp_msg.message_id,
                    text=fallback_text,
                    entities=fallback_entities,
                    parse_mode=None,
                )
                return True
            except Exception:
                return False
        except Exception:
            return False

    async def _send_notice() -> bool:
        try:
            await message.answer(fallback_text, entities=fallback_entities, parse_mode=None)
            return True
        except TelegramBadRequest as exc:
            _log(f"PM; Fallback notice send custom failed, plain retry: {exc}")
            try:
                await message.answer(ERROR_NOTICE_PLAIN_PM, parse_mode=None)
                return True
            except Exception as exc2:
                _log(f"PM; Fallback notice plain send failed: {exc2}")
                return False
        except Exception:
            return False

    if temp_msg:
        fallback_sent = await _edit_notice()

    if not fallback_sent:
        fallback_sent = await _send_notice()

    owner_notice = (
        f"⚠️ LLM недоступен\n"
        f"От: {user_login_safe} (chat_id={chat_id}, type={message.chat.type})\n"
        f"Текст: {text_for_llm[:500]}\n"
        f"Ошибка: {llm_error}"
    )
    try:
        await message.bot.send_message(OWNER_CHAT_ID, owner_notice)
    except Exception:
        pass
