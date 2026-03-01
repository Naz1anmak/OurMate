"""Потоковая и финальная отправка ответов LLM."""

import asyncio
import random
import time

from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import Message

from src.bot.services.llm_service import LLMService, LLMServiceError
from src.bot.services.context_service import context_service
import os

from src.config.settings import ENV
from src.utils.log_utils import log_with_ts as _log
from src.utils.render_utils import render_html_with_code

ENV_VALUE = (os.getenv("ENV") or "").strip().lower()
IS_DEV = ENV_VALUE in ("dev", "development")

def _log_dev(message: str) -> None:
    if IS_DEV:
        _log(message)

def format_final_answer(first_name: str, answer_body: str, has_context: bool) -> str:
    """Форматирует финальный ответ с обращением по имени, если контекст пуст."""
    if not first_name or has_context:
        return answer_body

    normalized = answer_body.lstrip()

    # Если модель уже начала с имени, не дублируем обращение
    lowered_name = first_name.lower()
    if normalized.lower().startswith((lowered_name, f"{lowered_name},")):
        return answer_body

    # Если ответ начинается с заголовка/маркера, ставим перенос строки, иначе — пробел
    needs_newline = normalized.startswith(("▎", "•", "-", "*"))
    separator = "\n" if needs_newline else " "

    if normalized:
        normalized = normalized[:1].lower() + normalized[1:]

    return f"{first_name},{separator}{normalized}"

async def try_streaming_response(
    message: Message,
    messages: list,
    first_name: str,
    user_login: str,
    text_for_llm: str,
    has_context: bool,
    use_placeholder_threshold: int = 40,
    min_edit_interval_group: float = 1.2,
    min_edit_interval_pm: float = 0.6,
    min_edit_chars_group: int = 110,
    min_edit_chars_pm: int = 50,
    max_edits_group: int = 15,
    max_first_token_wait: float = 15.0,
) -> tuple[bool, Message | None]:
    """Пытается отправить стрим-ответ (ЛС и группы), редактируя одно сообщение.

    Плейсхолдер используется, если запрос длиннее порога (по умолчанию 40 символов).
    """
    is_group_chat = message.chat.type in ("group", "supergroup")
    user_login_safe = user_login or (message.from_user.full_name if message.from_user else "") or str(message.from_user.id if message.from_user else message.chat.id)
    min_edit_interval = min_edit_interval_group if is_group_chat else min_edit_interval_pm
    # Адаптивная задержка редактирования: начинаем быстрее, затем плавно замедляемся, чтобы не ловить FLOOD
    interval_growth = 0.35 if is_group_chat else 0.2
    interval_cap = 3.0 if is_group_chat else 1.5
    min_edit_chars = min_edit_chars_group if is_group_chat else min_edit_chars_pm

    # В группах всегда ставим плейсхолдер, чтобы не ждать первый токен
    text_len = len(text_for_llm.strip())
    if is_group_chat and text_len < 8:
        return False, None
    use_placeholder = (is_group_chat and text_len >= 8) or (not is_group_chat and text_len > use_placeholder_threshold)
    placeholder_msg: Message | None = None
    sent_any = False
    start_time = time.monotonic()
    first_token_at: float | None = None

    if use_placeholder:
        placeholder_text = random.choice(
            [
                "🧠 Мне понадобится немного времени, думаю над ответом...",
                "⌛ Одну секунду, формулирую мысль...",
                "💭 Обдумываю, чтобы ответить по делу...",
                "✏️ Проверяю факты, сейчас вернусь...",
                "🔎 Сверяю детали, почти готово...",
                "⚙️ Прокручиваю логику в голове...",
                "🧩 Осталась последняя деталь...",
                "🌀 Привожу мысли в порядок...",
                "📚 Освежаю материалы, секунду...",
                "🤔 Хочу ответить точно, чуть-чуть подожди...",
            ]
        )
        try:
            if message.chat.type == "private":
                placeholder_msg = await message.answer(placeholder_text)
                sent_any = True
            else:
                placeholder_msg = await message.reply(placeholder_text)
                sent_any = True
        except Exception:
            placeholder_msg = None

    buffer = ""
    last_sent_len = 0
    last_flush = time.monotonic()
    edit_block_until = 0.0
    edit_count = 0

    stop_event = asyncio.Event()

    async def _typing_indicator():
        try:
            while not stop_event.is_set():
                await message.bot.send_chat_action(message.chat.id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except Exception:
            pass

    typing_task = asyncio.create_task(_typing_indicator())

    try:
        async for token in LLMService.stream_chat_request(messages):
            if not token:
                continue

            # Если совсем нет первых токенов дольше порога — отказываемся от стрима
            if first_token_at is None and (time.monotonic() - start_time) >= max_first_token_wait:
                tag = "GR" if is_group_chat else "PM"
                _log_dev(f"{tag}; Stream abort: no tokens for {max_first_token_wait:.1f}s")
                return False, placeholder_msg

            buffer += token
            if first_token_at is None:
                first_token_at = time.monotonic()
            now = time.monotonic()

            if placeholder_msg is None and buffer and use_placeholder:
                try:
                    rendered_buffer = render_html_with_code(buffer)
                    if message.chat.type == "private":
                        placeholder_msg = await message.answer(rendered_buffer, parse_mode="HTML")
                    else:
                        placeholder_msg = await message.reply(rendered_buffer, parse_mode="HTML")
                    sent_any = True
                    last_sent_len = len(buffer)
                    last_flush = now
                    continue
                except Exception:
                    return False, placeholder_msg

            effective_min_edit_interval = min(min_edit_interval + edit_count * interval_growth, interval_cap)

            if (
                placeholder_msg
                and now >= edit_block_until
                and ((len(buffer) - last_sent_len) >= min_edit_chars or (now - last_flush) >= effective_min_edit_interval)
                and (not is_group_chat or edit_count < max_edits_group)
            ):
                try:
                    rendered_buffer = render_html_with_code(buffer)
                    await message.bot.edit_message_text(
                        chat_id=placeholder_msg.chat.id,
                        message_id=placeholder_msg.message_id,
                        text=rendered_buffer,
                        parse_mode="HTML",
                    )
                    sent_any = True
                    edit_count += 1
                except TelegramRetryAfter as exc:
                    tag = "GR" if is_group_chat else "PM"
                    _log_dev(f"{tag}; Draft stream edit throttled: {exc}")
                    edit_block_until = time.monotonic() + exc.retry_after
                except Exception as exc:
                    tag = "GR" if is_group_chat else "PM"
                    _log_dev(f"{tag}; Draft stream edit failed, fallback: {exc}")
                    return False, placeholder_msg
                else:
                    last_sent_len = len(buffer)
                    last_flush = now

        if not buffer:
            return False, placeholder_msg

        if edit_block_until and time.monotonic() < edit_block_until:
            try:
                await asyncio.sleep(edit_block_until - time.monotonic())
            except Exception:
                pass

        final_answer = format_final_answer(first_name, buffer, has_context)
        safe_answer = render_html_with_code(final_answer)
        context_service.save_context(message.chat.id, text_for_llm, final_answer)
        tag = "GR" if is_group_chat else "PM"
        _log(f"{tag}; Бот (LLM stream) для {user_login_safe}: {final_answer}")

        if placeholder_msg:
            try:
                await message.bot.edit_message_text(
                    chat_id=placeholder_msg.chat.id,
                    message_id=placeholder_msg.message_id,
                    text=safe_answer,
                    parse_mode="HTML",
                )
                sent_any = True
                return True, placeholder_msg
            except TelegramRetryAfter as exc:
                tag = "GR" if is_group_chat else "PM"
                _log_dev(f"{tag}; Draft stream final edit throttled: {exc}")
                try:
                    await asyncio.sleep(exc.retry_after)
                except Exception:
                    pass
                try:
                    if message.chat.type == "private":
                        await message.answer(safe_answer, parse_mode="HTML")
                        sent_any = True
                    else:
                        await message.reply(safe_answer, parse_mode="HTML")
                        sent_any = True
                except Exception:
                    pass
                return True, placeholder_msg
            except Exception as exc:
                tag = "GR" if is_group_chat else "PM"
                _log_dev(f"{tag}; Draft stream final edit failed, fallback: {exc}")
                return False, placeholder_msg

        try:
            if message.chat.type == "private":
                await message.answer(safe_answer, parse_mode="HTML")
                sent_any = True
            else:
                await message.reply(safe_answer, parse_mode="HTML")
                sent_any = True
            return True, placeholder_msg
        except TelegramRetryAfter as exc:
            tag = "GR" if is_group_chat else "PM"
            _log_dev(f"{tag}; Draft stream send throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                if message.chat.type == "private":
                    await message.answer(safe_answer, parse_mode="HTML")
                    sent_any = True
                else:
                    await message.reply(safe_answer, parse_mode="HTML")
                    sent_any = True
                return True, placeholder_msg
            except Exception as exc:
                _log_dev(f"{tag}; Draft stream send failed after retry, fallback: {exc}")
                return False, placeholder_msg
        except Exception as exc:
            tag = "GR" if is_group_chat else "PM"
            _log_dev(f"{tag}; Draft stream final send failed, fallback: {exc}")
            return False, placeholder_msg

    except LLMServiceError as exc:
        if buffer:
            final_answer = format_final_answer(first_name, buffer, has_context)
            safe_answer = render_html_with_code(final_answer)
            context_service.save_context(message.chat.id, text_for_llm, final_answer)
            tag = "GR" if is_group_chat else "PM"
            _log(f"{tag}; Бот (LLM stream partial): {final_answer}")
            try:
                if placeholder_msg:
                    await message.bot.edit_message_text(
                        chat_id=placeholder_msg.chat.id,
                        message_id=placeholder_msg.message_id,
                        text=safe_answer,
                        parse_mode="HTML",
                    )
                    sent_any = True
                else:
                    if message.chat.type == "private":
                        await message.answer(safe_answer, parse_mode="HTML")
                        sent_any = True
                    else:
                        await message.reply(safe_answer, parse_mode="HTML")
                        sent_any = True
            except TelegramRetryAfter as exc:
                tag = "GR" if is_group_chat else "PM"
                _log_dev(f"{tag}; Draft stream partial edit throttled: {exc}")
                return False, placeholder_msg
            except Exception as exc:
                tag = "GR" if is_group_chat else "PM"
                _log_dev(f"{tag}; Draft stream partial edit failed, fallback: {exc}")
                return False, placeholder_msg
            return True, placeholder_msg

        tag = "GR" if is_group_chat else "PM"
        # Нет буфера: логируем и передаем плейсхолдер во fallback, чтобы не создавать второй
        _log_dev(f"{tag}; Stream failed without tokens: {exc}")
        return False, placeholder_msg
    except Exception as exc:
        tag = "GR" if is_group_chat else "PM"
        # Если уже что-то отправили в поток, не дублируем ответ во fallback
        if sent_any:
            return True, placeholder_msg
        _log_dev(f"{tag}; Stream unexpected error, fallback: {exc}")
        return False, placeholder_msg
    finally:
        try:
            stop_event.set()
            await typing_task
        except Exception:
            pass
