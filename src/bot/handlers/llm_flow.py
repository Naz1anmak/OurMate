"""Потоковая и финальная отправка ответов LLM."""
import asyncio
import logging
import time
import html as _html
import re

from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from aiogram.types import Message
from aiogram.methods import SendMessageDraft

from src.bot.services.llm_service import LLMService, LLMServiceError, stream_with_tools
from src.bot.services.llm_tools import run_tool_loop, ToolLoopResult
from src.bot.services.context_service import context_service

from src.bot.handlers.errors import notify_owner_error
from src.utils.render_utils import render_html_with_code
from src.bot.handlers.placeholder_variants import pick_placeholder_variant
from src.core.emoji import E

logger = logging.getLogger(__name__)

ERROR_NOTICE_PLAIN = f"{E.WARNING} Не удалось получить ответ. Попробуй ещё раз через пару секунд."

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
    stream_edit_timeout_sec: float = 6.0,
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
        try:
            placeholder_msg = await message.reply(placeholder_variant.text, parse_mode="HTML")
            sent_any = True
            logger.debug(f"{tag}; Placeholder sent")
        except Exception as exc:
            logger.debug(f"{tag}; Placeholder send failed: {exc}")
            placeholder_msg = None
    elif use_draft_stream:
        # Генерируем уникальный draft_id на поток, чтобы не переиспользовать старые драфты
        draft_id = int(time.monotonic_ns() % 900_000_000) + (message.chat.id % 1000) + 1

    async def send_pm_no_reply(text: str, parse_mode: str | None = "HTML") -> Message:
        sent = await message.bot.send_message(
            chat_id=message.chat.id,
            text=text,
            parse_mode=parse_mode,
            allow_sending_without_reply=True,
        )
        return sent

    async def cleanup_placeholder_after_separate_send() -> None:
        """Удаляет старый плейсхолдер, если финал отправлен отдельным сообщением."""
        if not placeholder_msg or message.chat.type == "private":
            return
        try:
            await placeholder_msg.delete()
        except Exception:
            # Не блокируем успешный путь доставки из-за ошибки очистки старого сообщения.
            pass

    async def send_notice_custom_or_plain() -> bool:
        try:
            if is_group_chat:
                await message.reply(ERROR_NOTICE_PLAIN, parse_mode="HTML")
            else:
                await send_pm_no_reply(ERROR_NOTICE_PLAIN, parse_mode="HTML")
            return True
        except Exception as exc:
            logger.debug(f"{tag}; Notice send failed: {exc}")
            return False

    async def edit_placeholder_to_notice() -> bool:
        if not placeholder_msg:
            return False
        try:
            await message.bot.edit_message_text(
                chat_id=placeholder_msg.chat.id,
                message_id=placeholder_msg.message_id,
                text=ERROR_NOTICE_PLAIN,
                parse_mode="HTML",
            )
            return True
        except Exception as exc:
            logger.debug(f"{tag}; Notice edit failed: {exc}")
            return False

    async def notify_owner_delivery_issue(final_answer: str, err: Exception) -> None:
        """Шлет владельцу алерт о проблеме доставки ответа в Telegram."""
        await notify_owner_error(
            message.bot,
            err,
            tg_id=message.from_user.id if message.from_user else None,
            username=message.from_user.username if message.from_user else None,
            context=f"Telegram delivery ({tag} stream)",
            extra=f"chat_id={message.chat.id}; ответ: {final_answer[:300]}",
        )

    buffer_prefix = f"{first_name}, " if (first_name and not has_context and not is_group_chat) else ""
    buffer = buffer_prefix
    last_sent_len = len(buffer)
    lowercase_after_prefix = bool(buffer_prefix)
    last_flush = time.monotonic()
    edit_block_until = 0.0
    edit_count = 0
    first_flush_done = False
    min_first_flush_chars = max(min_edit_chars, 50)
    stream_edit_broken = False

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
                logger.info(f"{tag}; Stream abort: no tokens for {max_first_token_wait:.1f}s, fallback")
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

            can_flush = (placeholder_msg is not None or use_draft_stream) and not stream_edit_broken
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
                        await asyncio.wait_for(
                            message.bot(
                                SendMessageDraft(
                                    chat_id=message.chat.id,
                                    draft_id=draft_id or 1,
                                    text=rendered_buffer,
                                    parse_mode="HTML",
                                )
                            ),
                            timeout=stream_edit_timeout_sec,
                        )
                    else:
                        await asyncio.wait_for(
                            message.bot.edit_message_text(
                                chat_id=placeholder_msg.chat.id,
                                message_id=placeholder_msg.message_id,
                                text=rendered_buffer,
                                parse_mode="HTML",
                            ),
                            timeout=stream_edit_timeout_sec,
                        )
                    sent_any = True
                    edit_count += 1
                    first_flush_done = True
                    logger.debug(
                        f"{tag}; len_delta={len_delta} buf_len={len(buffer)} t_since={time_since_flush:.2f} reason={reason}"
                    )
                except TelegramRetryAfter as exc:
                    logger.debug(f"{tag}; Draft stream edit throttled: {exc}")
                    edit_block_until = time.monotonic() + exc.retry_after
                except asyncio.TimeoutError:
                    stream_edit_broken = True
                    logger.warning(f"{tag}; Stream edit timeout ({stream_edit_timeout_sec:.0f}s), continue without edits")
                except Exception as exc:
                    stream_edit_broken = True
                    logger.warning(f"{tag}; Stream edit failed, continue without edits: {exc}")
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
        response_log_kind = "LLM stream" if not stream_edit_broken else "LLM"
        # В группах сохраняем в контекст ответ без префикса имени,
        # чтобы история не засорялась чужими именами
        context_to_save = format_final_answer("", buffer, has_context) if is_group_chat else final_answer
        context_service.save_context(message.chat.id, text_for_llm, context_to_save)

        if placeholder_msg and not stream_edit_broken:
            try:
                await message.bot.edit_message_text(
                    chat_id=placeholder_msg.chat.id,
                    message_id=placeholder_msg.message_id,
                    text=safe_answer,
                    parse_mode="HTML",
                )
                sent_any = True
                logger.info(f"{tag}; Бот ({response_log_kind}) для {user_login_safe}: {final_answer}")
                finished_label = "placeholder" if use_placeholder else "edited message"
                logger.debug(f"{tag}; Stream finished via {finished_label}: edits={edit_count}, chars={len(buffer)}")
                return True, placeholder_msg
            except TelegramBadRequest as exc:
                tag = "GR" if is_group_chat else "PM"
                logger.debug(f"{tag}; Draft stream final edit bad HTML, retry plain: {exc}")
                safe_plain = _trim_html(_html.escape(final_answer))
                try:
                    await message.bot.edit_message_text(
                        chat_id=placeholder_msg.chat.id,
                        message_id=placeholder_msg.message_id,
                        text=safe_plain,
                        parse_mode="HTML",
                    )
                    sent_any = True
                    logger.info(f"{tag}; Бот ({response_log_kind}) для {user_login_safe}: {final_answer}")
                    return True, placeholder_msg
                except Exception as exc2:
                    logger.debug(f"{tag}; Draft stream plain retry failed: {exc2}")
                    # fall through to generic handling below
            except TelegramRetryAfter as exc:
                tag = "GR" if is_group_chat else "PM"
                logger.debug(f"{tag}; Draft stream final edit throttled: {exc}")
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
                    logger.info(f"{tag}; Бот ({response_log_kind}) для {user_login_safe}: {final_answer}")
                except Exception:
                    pass
                return True, placeholder_msg
            except Exception as exc:
                tag = "GR" if is_group_chat else "PM"
                logger.debug(f"{tag}; Draft stream final edit failed, sending notice: {exc}")
                notice_sent = await send_notice_custom_or_plain()
                sent_any = sent_any or notice_sent
                return True, placeholder_msg

        # Если потоковые edit'ы отвалились, пробуем один финальный edit того же плейсхолдера.
        # Это приоритетнее, чем отправлять второе отдельное сообщение в чат.
        if placeholder_msg and stream_edit_broken:
            try:
                await asyncio.wait_for(
                    message.bot.edit_message_text(
                        chat_id=placeholder_msg.chat.id,
                        message_id=placeholder_msg.message_id,
                        text=safe_answer,
                        parse_mode="HTML",
                    ),
                    timeout=stream_edit_timeout_sec,
                )
                sent_any = True
                logger.info(f"{tag}; Бот ({response_log_kind}) для {user_login_safe}: {final_answer}")
                logger.debug(f"{tag}; Stream recovered via final placeholder edit")
                return True, placeholder_msg
            except Exception as exc:
                logger.debug(f"{tag}; Stream recovery final edit failed, sending separate message: {exc}")

        try:
            if message.chat.type == "private":
                await send_pm_no_reply(safe_answer)
                sent_any = True
            else:
                await message.reply(safe_answer, parse_mode="HTML")
                sent_any = True
            await cleanup_placeholder_after_separate_send()
            logger.info(f"{tag}; Бот ({response_log_kind}) для {user_login_safe}: {final_answer}")
            logger.debug(f"{tag}; Stream finished direct send: edits={edit_count}, draft={use_draft_stream}, chars={len(buffer)}")
            return True, placeholder_msg
        except TelegramBadRequest as exc:
            tag = "GR" if is_group_chat else "PM"
            logger.debug(f"{tag}; Draft stream final send bad HTML, retry plain: {exc}")
            safe_plain = _trim_html(_html.escape(final_answer))
            try:
                if message.chat.type == "private":
                    await send_pm_no_reply(safe_plain, parse_mode=None)
                    sent_any = True
                else:
                    await message.reply(safe_plain, parse_mode="HTML")
                    sent_any = True
                await cleanup_placeholder_after_separate_send()
                logger.info(f"{tag}; Бот ({response_log_kind}) для {user_login_safe}: {final_answer}")
                return True, placeholder_msg
            except Exception as exc2:
                logger.info(f"{tag}; Бот ({response_log_kind}, delivery status unknown) для {user_login_safe}: {final_answer}")
                logger.warning(f"{tag}; Stream plain send failed (status unknown): {exc2}")
                await notify_owner_delivery_issue(final_answer, exc2)
                return True, placeholder_msg
        except TelegramRetryAfter as exc:
            tag = "GR" if is_group_chat else "PM"
            logger.debug(f"{tag}; Draft stream send throttled: {exc}")
            try:
                await asyncio.sleep(exc.retry_after)
                if message.chat.type == "private":
                    await send_pm_no_reply(safe_answer)
                    sent_any = True
                else:
                    await message.reply(safe_answer, parse_mode="HTML")
                    sent_any = True
                await cleanup_placeholder_after_separate_send()
                logger.info(f"{tag}; Бот ({response_log_kind}) для {user_login_safe}: {final_answer}")
                return True, placeholder_msg
            except Exception as exc:
                logger.info(f"{tag}; Бот ({response_log_kind}, delivery status unknown) для {user_login_safe}: {final_answer}")
                logger.warning(f"{tag}; Stream send failed after retry (status unknown): {exc}")
                await notify_owner_delivery_issue(final_answer, exc)
                return True, placeholder_msg
        except Exception as exc:
            tag = "GR" if is_group_chat else "PM"
            logger.info(f"{tag}; Бот ({response_log_kind}, delivery status unknown) для {user_login_safe}: {final_answer}")
            logger.warning(f"{tag}; Stream final send failed (status unknown): {exc}")
            await notify_owner_delivery_issue(final_answer, exc)
            return True, placeholder_msg
    except LLMServiceError as exc:
        tag = "GR" if is_group_chat else "PM"
        logger.debug(f"{tag}; Stream error, sending notice only: {exc}")

        notice_sent = False
        if placeholder_msg:
            notice_sent = await edit_placeholder_to_notice()
        else:
            notice_sent = await send_notice_custom_or_plain()

        if not notice_sent:
            return False, placeholder_msg

        await notify_owner_error(
            message.bot,
            exc,
            tg_id=message.from_user.id if message.from_user else None,
            username=message.from_user.username if message.from_user else None,
            context=f"LLM stream ({tag})",
            extra=f"chat_id={message.chat.id}; запрос: {text_for_llm[:300]}",
        )

        return True, placeholder_msg
    except Exception as exc:
        tag = "GR" if is_group_chat else "PM"
        # Если уже что-то отправили в поток, не дублируем ответ во fallback
        if sent_any:
            return True, placeholder_msg
        logger.warning(f"{tag}; Stream unexpected error, fallback: {exc}")
        return False, placeholder_msg
    finally:
        try:
            stop_event.set()
            await typing_task
        except Exception:
            pass


async def send_tool_loop_extras(message, *, deferred_messages: list[str], denial: str | None) -> None:
    """Отправляет заглушку отказа ИЛИ отложенные сообщения (diff) после основного ответа."""
    if denial:
        try:
            await message.answer(denial, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Не удалось отправить заглушку отказа: %s", exc)
        return
    for text in deferred_messages:
        try:
            await message.answer(text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Не удалось отправить отложенное сообщение: %s", exc)


class StreamRenderer:
    """Живой стрим: группа — эдиты плейсхолдера, ЛС — драфты. feed() — приёмник токенов."""

    def __init__(self, message, *, prefix: str = ""):
        self.message = message
        self.is_group = message.chat.type in ("group", "supergroup")
        self.use_draft = message.chat.type == "private"
        self.placeholder = None
        self.draft_id = int(time.monotonic_ns() % 900_000_000) + 1
        self.buffer = prefix
        self.last_sent_len = len(prefix)
        self.last_flush = 0.0
        self.min_interval = 1.2 if self.is_group else 0.8
        self.min_chars = 110 if self.is_group else 50

    async def start(self, placeholder_text: str) -> None:
        """В группе показывает заглушку ожидания; в ЛС стрим идёт драфтами без отдельного плейсхолдера."""
        if self.is_group:
            try:
                self.placeholder = await self.message.reply(placeholder_text, parse_mode="HTML")
            except Exception as exc:  # noqa: BLE001
                logger.debug("StreamRenderer start failed: %s", exc)
                self.placeholder = None

    async def feed(self, token: str) -> None:
        self.buffer += token
        now = time.monotonic()
        if (len(self.buffer) - self.last_sent_len) < self.min_chars and (now - self.last_flush) < self.min_interval:
            return
        await self._render(self.buffer)
        self.last_sent_len = len(self.buffer)
        self.last_flush = now

    async def _render(self, text: str) -> None:
        rendered = _trim_html(render_html_with_code(text))
        try:
            if self.use_draft:
                await self.message.bot(SendMessageDraft(chat_id=self.message.chat.id,
                                                        draft_id=self.draft_id,
                                                        text=rendered, parse_mode="HTML"))
            elif self.placeholder:
                await self.message.bot.edit_message_text(chat_id=self.placeholder.chat.id,
                                                         message_id=self.placeholder.message_id,
                                                         text=rendered, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            logger.debug("StreamRenderer render failed: %s", exc)

    async def finalize(self, final_text: str) -> bool:
        """Фиксирует финал: эдит плейсхолдера (группа) или реальное сообщение (ЛС — драфт эфемерен)."""
        safe = _trim_html(render_html_with_code(final_text))
        try:
            if self.use_draft:
                await self.message.answer(safe, parse_mode="HTML")
            elif self.placeholder:
                await self.message.bot.edit_message_text(chat_id=self.placeholder.chat.id,
                                                         message_id=self.placeholder.message_id,
                                                         text=safe, parse_mode="HTML")
            else:
                await self.message.reply(safe, parse_mode="HTML")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("StreamRenderer finalize failed: %s", exc)
            return False


SCHEDULE_PRESENTATION_NOTE = (
    "Если вызвал get_schedule или find_next_class и показываешь пары: поле formatted в результате — "
    "это уже готовый блок расписания (HTML с цитатой <blockquote>, как в команде «пары»). Выведи его "
    "ДОСЛОВНО, как есть, не переписывая пары, не меняя теги и не оборачивая в кодовый блок, и НЕ добавляя "
    "свой заголовок с датой — дата уже внутри блока. До или после блока можно добавить короткую живую "
    "фразу, но дату в ней не повторяй. Поле events — только для подсчётов (например, «во сколько последняя "
    "пара»), его в ответ не выводи."
)


def _inject_system_note(messages: list, note: str) -> list:
    """Вставляет system-заметку после ведущих system-сообщений, не мутируя исходный список."""
    msgs = list(messages)
    at = 0
    while at < len(msgs) and msgs[at].get("role") == "system":
        at += 1
    msgs.insert(at, {"role": "system", "content": note})
    return msgs


async def run_schedule_aware_response(
    message,
    messages: list,
    first_name: str,
    user_login: str,
    text_for_llm: str,
    has_context: bool,
    tool_context: dict,
    registry,
) -> bool:
    """Тул-флоу со стримом: фаза1 (стрим болтовни / детект tool_calls) → run_tool_loop → стрим финала + deferred."""
    is_group_chat = message.chat.type in ("group", "supergroup")
    messages = _inject_system_note(messages, SCHEDULE_PRESENTATION_NOTE)
    prefix = f"{first_name}, " if (first_name and not has_context and not is_group_chat) else ""
    renderer = StreamRenderer(message, prefix=prefix)
    await renderer.start(pick_placeholder_variant().text)

    # Один и тот же приёмник на обе фазы: болтовня и финал стримятся; тул-фазы content не дают.
    async def llm_call(msgs, tools):
        return await stream_with_tools(msgs, tools, on_content_token=renderer.feed)

    try:
        result: ToolLoopResult = await run_tool_loop(
            messages, tool_context, registry=registry, llm_call=llm_call)
    except LLMServiceError as exc:
        logger.warning("tool-flow LLM error: %s", exc)
        await renderer.finalize(ERROR_NOTICE_PLAIN)
        return True

    if result.denial:
        await renderer.finalize(result.denial)
        return True

    final_answer = format_final_answer(first_name, result.text or "", has_context)
    context_service.save_context(
        message.chat.id, text_for_llm,
        format_final_answer("", result.text or "", has_context) if is_group_chat else final_answer)

    if not await renderer.finalize(final_answer):
        return False

    await send_tool_loop_extras(message, deferred_messages=result.deferred_messages, denial=None)
    logger.info("%s; Бот (tool-flow) для %s: %s", "GR" if is_group_chat else "PM",
                user_login or "?", final_answer)
    return True
