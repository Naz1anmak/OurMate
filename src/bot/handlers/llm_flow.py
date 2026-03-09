"""Потоковая и финальная отправка ответов LLM."""
import asyncio
import time
import html as _html
import re

from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from aiogram.types import Message
from aiogram.methods import SendMessageDraft

from src.bot.services.llm_service import LLMService, LLMServiceError
from src.bot.services.context_service import context_service
import os

from src.config.settings import ENV, OWNER_CHAT_ID
from src.utils.log_utils import log_with_ts as _log
from src.utils.render_utils import render_html_with_code
from src.bot.handlers.placeholder_variants import pick_placeholder_variant
from src.utils.emoji_utils import make_custom_emoji_payload

ENV_VALUE = (os.getenv("ENV") or "").strip().lower()
# Если переменная окружения не задана, используем значение из settings (по умолчанию dev)
IS_DEV = ENV_VALUE in ("dev", "development") or str(ENV).strip().lower() in ("dev", "development")

ERROR_NOTICE_PLAIN = "⚠️ Не удалось получить ответ. Попробуй ещё раз через пару секунд."
ERROR_NOTICE_TEXT, ERROR_NOTICE_ENTITIES = make_custom_emoji_payload(
    ERROR_NOTICE_PLAIN,
    "5197170531379459422",
)

def _log_dev(message: str) -> None:
    if IS_DEV:
        _log(message)

def _ends_on_boundary(text: str) -> bool:
    """Проверяем, что буфер заканчивается на границе слова/предложения, чтобы не рвать слова."""
    if not text:
        return False
    last = text[-1]
    if last.isspace():
        return True
    return last in {".", "!", "?", ",", ";", ":", "…", ")", "]", "}" , "»"}

_SAFE_BOUNDARY_CHARS = set(" \n\t.,!?;:)]}»")

def _find_safe_flush_len(buffer: str, last_sent_len: int, search_back: int = 120) -> int:
    """Находит безопасный срез под отправку, отдавая предпочтение пробелам/знакам препинания."""
    start = max(last_sent_len, len(buffer) - search_back)
    for idx in range(len(buffer) - 1, start - 1, -1):
        if buffer[idx] in _SAFE_BOUNDARY_CHARS:
            return idx + 1
    return len(buffer)

_TAG_RE = re.compile(r"<[^>]+>")

def _visible_length(html_text: str) -> int:
    """Приблизительно считаем длину видимого текста (без тегов, с раскодированными сущностями)."""
    no_tags = _TAG_RE.sub("", html_text)
    return len(_html.unescape(no_tags))

def _trim_html(text: str, visible_limit: int = 4050, hard_limit: int = 4700) -> str:
    """Обрезаем с учётом видимой длины: теги не считаются, но есть жёсткий потолок по сырому HTML."""
    if _visible_length(text) <= visible_limit and len(text) <= hard_limit:
        return text

    # Сначала режем по жёсткому потолку, затем шагами, пока видимая длина не влезет.
    truncated = text[:hard_limit]
    while (_visible_length(truncated) > visible_limit or len(truncated) > hard_limit) and len(truncated) > 0:
        truncated = truncated[:-200]

    if not truncated:
        truncated = text[:visible_limit]

    return truncated.rstrip() + "…"

def format_final_answer(first_name: str, answer_body: str, has_context: bool) -> str:
    """Форматирует финальный ответ с обращением по имени, если контекст пуст."""
    if not first_name or has_context:
        return answer_body

    normalized = answer_body.lstrip()

    lowered_name = first_name.lower()

    # Если модель начала с имени без запятой — оставляем как есть
    if normalized.lower().startswith(lowered_name) and not normalized.lower().startswith(f"{lowered_name},"):
        return answer_body

    # Если ответ уже начинается с имени — корректируем разделитель (нужен перенос для списков)
    if normalized.lower().startswith(f"{lowered_name},"):
        rest = normalized[len(first_name) :]
        if rest.startswith(","):
            rest = rest[1:]
        rest = rest.lstrip()

        needs_newline = rest.startswith(("▎", "•", "-", "*"))
        separator = "\n" if needs_newline else " "

        if rest:
            rest = rest[:1].lower() + rest[1:]

        return f"{first_name},{separator}{rest}"

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
    min_edit_interval_group: float = 1.2,
    min_edit_interval_pm: float = 0.8,
    min_edit_chars_group: int = 110,
    min_edit_chars_pm: int = 50,
    max_edits_group: int = 15,
    max_first_token_wait: float = 15.0,
) -> tuple[bool, Message | None]:
    """Пытается отправить стрим-ответ (ЛС и группы), редактируя одно сообщение.

    Плейсхолдер используется, если запрос длиннее порога (по умолчанию 40 символов).
    """
    is_group_chat = message.chat.type in ("group", "supergroup")
    use_draft_stream = message.chat.type == "private"
    user_login_safe = user_login or (message.from_user.full_name if message.from_user else "") or str(message.from_user.id if message.from_user else message.chat.id)
    min_edit_interval = min_edit_interval_group if is_group_chat else min_edit_interval_pm
    tag = "GR" if is_group_chat else "PM"
    min_edit_chars = min_edit_chars_group if is_group_chat else min_edit_chars_pm

    # В группах стримим всегда, плейсхолдер ставим только если вопрос не совсем короткий; в ЛС — drafts.
    text_len = len(text_for_llm.strip())
    if (not is_group_chat) and (not use_draft_stream):
        return False, None

    use_placeholder = is_group_chat and text_len >= 8  # короткие без заглушки
    placeholder_msg: Message | None = None
    sent_any = False
    start_time = time.monotonic()
    first_token_at: float | None = None
    draft_id: int | None = None

    if use_placeholder:
        placeholder_variant = pick_placeholder_variant()
        placeholder_text, placeholder_entities = placeholder_variant.reply_payload()
        try:
            placeholder_msg = await message.reply(placeholder_text, entities=placeholder_entities)
            sent_any = True
            _log_dev(f"{tag}; Placeholder sent with custom emoji")
        except Exception as exc:
            _log_dev(f"{tag}; Placeholder send failed, retry plain: {exc}")
            try:
                placeholder_msg = await message.reply(placeholder_text)
                sent_any = True
                _log_dev(f"{tag}; Placeholder sent without entities")
            except Exception as exc2:
                _log_dev(f"{tag}; Placeholder plain send failed: {exc2}")
                placeholder_msg = None
    elif use_draft_stream:
        # Генерируем уникальный draft_id на поток, чтобы не переиспользовать старые драфты
        draft_id = int(time.monotonic_ns() % 900_000_000) + (message.chat.id % 1000) + 1

    async def send_pm_no_reply(text: str, entities: list | None = None, parse_mode: str | None = "HTML") -> Message:
        sent = await message.bot.send_message(
            chat_id=message.chat.id,
            text=text,
            parse_mode=parse_mode,
            allow_sending_without_reply=True,
            entities=entities,
        )
        return sent

    async def send_notice_custom_or_plain() -> bool:
        try:
            if is_group_chat:
                await message.reply(ERROR_NOTICE_TEXT, entities=ERROR_NOTICE_ENTITIES)
            else:
                await send_pm_no_reply(ERROR_NOTICE_TEXT, ERROR_NOTICE_ENTITIES, parse_mode=None)
            return True
        except TelegramBadRequest as exc:
            _log_dev(f"{tag}; Notice custom emoji failed, fallback plain: {exc}")
            try:
                if is_group_chat:
                    await message.reply(ERROR_NOTICE_PLAIN, parse_mode=None)
                else:
                    await send_pm_no_reply(ERROR_NOTICE_PLAIN, parse_mode=None)
                return True
            except Exception as exc2:
                _log_dev(f"{tag}; Plain notice send failed: {exc2}")
                return False
        except Exception as exc:
            _log_dev(f"{tag}; Notice send unexpected failure: {exc}")
            return False

    async def edit_placeholder_to_notice() -> bool:
        if not placeholder_msg:
            return False
        try:
            await message.bot.edit_message_text(
                chat_id=placeholder_msg.chat.id,
                message_id=placeholder_msg.message_id,
                text=ERROR_NOTICE_TEXT,
                entities=ERROR_NOTICE_ENTITIES,
                parse_mode=None,
            )
            return True
        except TelegramBadRequest as exc:
            _log_dev(f"{tag}; Notice edit custom emoji failed, fallback plain: {exc}")
            try:
                await message.bot.edit_message_text(
                    chat_id=placeholder_msg.chat.id,
                    message_id=placeholder_msg.message_id,
                    text=ERROR_NOTICE_PLAIN,
                    parse_mode=None,
                )
                return True
            except Exception as exc2:
                _log_dev(f"{tag}; Notice edit plain send failed: {exc2}")
                return False
        except Exception as exc:
            _log_dev(f"{tag}; Notice edit unexpected failure: {exc}")
            return False

    buffer_prefix = f"{first_name}, " if (first_name and not has_context) else ""
    buffer = buffer_prefix
    last_sent_len = len(buffer)
    lowercase_after_prefix = bool(buffer_prefix)
    last_flush = time.monotonic()
    edit_block_until = 0.0
    edit_count = 0
    first_flush_done = False
    min_first_flush_chars = max(min_edit_chars, 50)

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
                _log_dev(f"{tag}; Stream abort: no tokens for {max_first_token_wait:.1f}s")
                return False, placeholder_msg

            buffer += token
            if first_token_at is None:
                first_token_at = time.monotonic()
            now = time.monotonic()

            if placeholder_msg is None and buffer and use_placeholder:
                try:
                    rendered_buffer = _trim_html(render_html_with_code(buffer))
                    placeholder_msg = await message.reply(rendered_buffer, parse_mode="HTML")
                    sent_any = True
                    last_sent_len = len(buffer)
                    last_flush = now
                    continue
                except Exception:
                    return False, placeholder_msg

            effective_min_edit_interval = min_edit_interval
            time_since_flush = now - last_flush
            len_delta = len(buffer) - last_sent_len
            boundary_ok = _ends_on_boundary(buffer)
            hard_timeout = effective_min_edit_interval * 4.0  # дольше ждём конца слова/предложения
            min_chunk_force = max(8, int(min_edit_chars * 0.4))  # не шлём совсем крошечные куски при таймауте

            can_flush = placeholder_msg is not None or use_draft_stream
            allow_non_boundary = is_group_chat  # в ЛС драфты не рвём середину слова, кроме аварийного таймаута

            if lowercase_after_prefix and len(buffer) > len(buffer_prefix):
                # Понижаем регистр первого символа после обращения
                prefix_len = len(buffer_prefix)
                tail = buffer[prefix_len:]
                for idx, ch in enumerate(tail):
                    if not ch.isspace():
                        buffer = buffer_prefix + tail[:idx] + ch.lower() + tail[idx + 1 :]
                        lowercase_after_prefix = False
                        break

            reason = None
            if boundary_ok and len_delta >= min_edit_chars:
                reason = "boundary+chars"
            elif boundary_ok and time_since_flush >= effective_min_edit_interval:
                reason = "boundary+interval"
            elif allow_non_boundary and len_delta >= min_edit_chars:
                reason = "nonboundary+chars"
            elif time_since_flush >= hard_timeout and len_delta >= min_chunk_force:
                reason = "hard_timeout"

            if (not first_flush_done) and reason in {"boundary+chars", "boundary+interval", "nonboundary+chars"}:
                if len(buffer) < min_first_flush_chars:
                    reason = None

            if (
                can_flush
                and now >= edit_block_until
                and reason is not None
                and (not is_group_chat or edit_count < max_edits_group)
            ):
                flush_buffer = buffer
                if reason in {"nonboundary+chars", "hard_timeout"} and not boundary_ok:
                    safe_flush_len = _find_safe_flush_len(buffer, last_sent_len)
                    if safe_flush_len > last_sent_len:
                        flush_buffer = buffer[:safe_flush_len]
                try:
                    rendered_buffer = _trim_html(render_html_with_code(flush_buffer))
                    if use_draft_stream:
                        await message.bot(
                            SendMessageDraft(
                                chat_id=message.chat.id,
                                draft_id=draft_id or 1,
                                text=rendered_buffer,
                                parse_mode="HTML",
                            )
                        )
                    else:
                        await message.bot.edit_message_text(
                            chat_id=placeholder_msg.chat.id,
                            message_id=placeholder_msg.message_id,
                            text=rendered_buffer,
                            parse_mode="HTML",
                        )
                    sent_any = True
                    edit_count += 1
                    first_flush_done = True
                    if IS_DEV:
                        _log_dev(
                            f"{tag}; len_delta={len_delta} buf_len={len(buffer)} t_since={time_since_flush:.2f} reason={reason}"
                        )
                except TelegramRetryAfter as exc:
                    _log_dev(f"{tag}; Draft stream edit throttled: {exc}")
                    edit_block_until = time.monotonic() + exc.retry_after
                except Exception as exc:
                    _log_dev(f"{tag}; Draft stream edit failed, fallback: {exc}")
                    return False, placeholder_msg
                else:
                    last_sent_len = len(flush_buffer)
                    last_flush = now

        if not buffer:
            return False, placeholder_msg

        if edit_block_until and time.monotonic() < edit_block_until:
            try:
                await asyncio.sleep(edit_block_until - time.monotonic())
            except Exception:
                pass

        final_answer = format_final_answer(first_name, buffer, has_context)
        safe_answer = _trim_html(render_html_with_code(final_answer))
        context_service.save_context(message.chat.id, text_for_llm, final_answer)
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
                finished_label = "placeholder" if use_placeholder else "edited message"
                _log_dev(f"{tag}; Stream finished via {finished_label}: edits={edit_count}, chars={len(buffer)}")
                return True, placeholder_msg
            except TelegramBadRequest as exc:
                tag = "GR" if is_group_chat else "PM"
                _log_dev(f"{tag}; Draft stream final edit bad HTML, retry plain: {exc}")
                safe_plain = _trim_html(_html.escape(final_answer))
                try:
                    await message.bot.edit_message_text(
                        chat_id=placeholder_msg.chat.id,
                        message_id=placeholder_msg.message_id,
                        text=safe_plain,
                        parse_mode="HTML",
                    )
                    sent_any = True
                    return True, placeholder_msg
                except Exception as exc2:
                    _log_dev(f"{tag}; Draft stream plain retry failed: {exc2}")
                    # fall through to generic handling below
            except TelegramRetryAfter as exc:
                tag = "GR" if is_group_chat else "PM"
                _log_dev(f"{tag}; Draft stream final edit throttled: {exc}")
                try:
                    await asyncio.sleep(exc.retry_after)
                except Exception:
                    pass
                try:
                    if message.chat.type == "private":
                        await send_pm_no_reply(safe_answer)
                        sent_any = True
                    else:
                        await message.reply(safe_answer, parse_mode="HTML")
                        sent_any = True
                except Exception:
                    pass
                return True, placeholder_msg
            except Exception as exc:
                tag = "GR" if is_group_chat else "PM"
                _log_dev(f"{tag}; Draft stream final edit failed, sending notice: {exc}")
                notice_sent = await send_notice_custom_or_plain()
                sent_any = sent_any or notice_sent
                return True, placeholder_msg

        try:
            if message.chat.type == "private":
                await send_pm_no_reply(safe_answer)
                sent_any = True
            else:
                await message.reply(safe_answer, parse_mode="HTML")
                sent_any = True
            _log_dev(f"{tag}; Stream finished direct send: edits={edit_count}, draft={use_draft_stream}, chars={len(buffer)}")
            return True, placeholder_msg
        except TelegramBadRequest as exc:
            tag = "GR" if is_group_chat else "PM"
            _log_dev(f"{tag}; Draft stream final send bad HTML, retry plain: {exc}")
            safe_plain = _trim_html(_html.escape(final_answer))
            try:
                if message.chat.type == "private":
                    await send_pm_no_reply(safe_plain, parse_mode=None)
                    sent_any = True
                else:
                    await message.reply(safe_plain, parse_mode="HTML")
                    sent_any = True
                return True, placeholder_msg
            except Exception as exc2:
                _log_dev(f"{tag}; Draft stream plain send failed: {exc2}")
                return False, placeholder_msg
        except TelegramRetryAfter as exc:
            tag = "GR" if is_group_chat else "PM"
            _log_dev(f"{tag}; Draft stream send throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                if message.chat.type == "private":
                    await send_pm_no_reply(safe_answer)
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
        tag = "GR" if is_group_chat else "PM"
        _log_dev(f"{tag}; Stream error, sending notice only: {exc}")

        owner_notice = (
            "⚠️ LLM stream ошибка\n"
            f"От: {user_login_safe} (chat_id={message.chat.id}, type={message.chat.type})\n"
            f"Текст: {text_for_llm[:500]}\n"
            f"Ошибка: {exc}"
        )

        notice_sent = False
        if placeholder_msg:
            notice_sent = await edit_placeholder_to_notice()
        else:
            notice_sent = await send_notice_custom_or_plain()

        if not notice_sent:
            return False, placeholder_msg

        try:
            await message.bot.send_message(OWNER_CHAT_ID, owner_notice)
        except Exception as exc2:
            _log_dev(f"{tag}; Owner notice failed: {exc2}")

        return True, placeholder_msg
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
