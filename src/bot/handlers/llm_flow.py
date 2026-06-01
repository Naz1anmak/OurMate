"""Потоковая и финальная отправка ответов LLM."""
import logging
import time
import html as _html
import re

from aiogram.types import Message
from aiogram.methods import SendMessageDraft

from src.bot.services.llm_service import LLMServiceError, stream_with_tools
from src.bot.services.llm_tools import run_tool_loop, ToolLoopResult
from src.bot.services.context_service import context_service

from src.bot.handlers.errors import notify_owner_error
from src.utils.render_utils import render_html_with_code
from src.bot.handlers.placeholder_variants import pick_placeholder_variant
from src.core.emoji import E

logger = logging.getLogger(__name__)

ERROR_NOTICE_PLAIN = f"{E.WARNING} Не удалось получить ответ. Попробуй ещё раз через пару секунд."

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


# Тул-специфичные заглушки на момент исполнения тула (только группа).
TOOL_INDICATORS = {
    "web_search": f"{E.THINK_SEARCH} Ищу в интернете…",
    "create_reminder": f"{E.REMINDER} Создаю напоминание…",
    "list_reminders": f"{E.REMINDER} Смотрю напоминания…",
    "update_reminder": f"{E.REMINDER} Меняю напоминание…",
    "cancel_reminder": f"{E.REMINDER} Отменяю напоминание…",
}


class StreamRenderer:
    """Живой стрим: группа — эдиты плейсхолдера, ЛС — драфты. feed() — приёмник токенов."""

    def __init__(self, message, *, prefix: str = ""):
        self.message = message
        self.is_group = message.chat.type in ("group", "supergroup")
        self.use_draft = message.chat.type == "private"
        self.placeholder = None
        self.streamed = False
        # Затвор: пока закрыт, токены копятся в буфер, но НЕ показываются. Открываем его только
        # когда пошёл тул (open_gate). Так болтовня фазы-1 не мелькает в плейсхолдере/драфте,
        # если reply окажется tool-call'ом (её пришлось бы стирать — это и было мигание).
        self.gate_open = False
        self.draft_id = int(time.monotonic_ns() % 900_000_000) + 1
        self.prefix = prefix
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

    async def show_tool_indicator(self, tool_name: str) -> None:
        """В группе подменяет плейсхолдер на тул-индикатор (web_search и т.п.). В ЛС — ничего."""
        text = TOOL_INDICATORS.get(tool_name)
        if not text or not self.is_group or not self.placeholder:
            return
        try:
            await self.message.bot.edit_message_text(
                chat_id=self.placeholder.chat.id,
                message_id=self.placeholder.message_id,
                text=text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            logger.debug("show_tool_indicator failed: %s", exc)

    def open_gate(self) -> None:
        """Открывает живой стрим (зовём при старте тула). Буфер сбрасываем на префикс — добитая
        до тула болтовня не должна примешаться к пост-тульному ответу (web_search и т.п.)."""
        self.gate_open = True
        self.buffer = self.prefix
        self.last_sent_len = len(self.prefix)

    async def feed(self, token: str) -> None:
        self.buffer += token
        if not self.gate_open:
            return  # затвор закрыт — копим молча, пока не ясно, не tool-call ли это (см. open_gate)
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
                self.streamed = True
            elif self.placeholder:
                await self.message.bot.edit_message_text(chat_id=self.placeholder.chat.id,
                                                         message_id=self.placeholder.message_id,
                                                         text=rendered, parse_mode="HTML",
                                                         disable_web_page_preview=True)
                self.streamed = True
        except Exception as exc:  # noqa: BLE001
            logger.debug("StreamRenderer render failed: %s", exc)

    async def discard(self) -> None:
        """Убирает индикатор: сообщение уже отправил тул, болтовня LLM не нужна.
        В группе — удаляем плейсхолдер ожидания; в ЛС — гасим повисший драфт (пустым)."""
        if self.placeholder:
            try:
                await self.message.bot.delete_message(
                    self.placeholder.chat.id, self.placeholder.message_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("StreamRenderer discard failed: %s", exc)
            self.placeholder = None
        elif self.use_draft and self.streamed:
            try:
                await self.message.bot(SendMessageDraft(
                    chat_id=self.message.chat.id, draft_id=self.draft_id, text=""))
            except Exception as exc:  # noqa: BLE001
                logger.debug("StreamRenderer draft clear failed: %s", exc)

    async def finalize(self, final_text: str) -> bool:
        """Фиксирует финал: эдит плейсхолдера (группа) или реальное сообщение (ЛС — драфт эфемерен)."""
        safe = _trim_html(render_html_with_code(final_text))
        try:
            if self.use_draft:
                await self.message.answer(safe, parse_mode="HTML", disable_web_page_preview=True)
            elif self.placeholder:
                await self.message.bot.edit_message_text(chat_id=self.placeholder.chat.id,
                                                         message_id=self.placeholder.message_id,
                                                         text=safe, parse_mode="HTML",
                                                         disable_web_page_preview=True)
            else:
                await self.message.reply(safe, parse_mode="HTML", disable_web_page_preview=True)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("StreamRenderer finalize failed: %s", exc)
            return False


SCHEDULE_PRESENTATION_NOTE = (
    "Когда показываешь пары из get_schedule или find_classes_by_subject, переоформляй их в своём обычном стиле "
    "(подзаголовок с ▎, пункты с •). НЕ вставляй в ответ HTML-теги (<b>, <blockquote>) и не копируй поле "
    "formatted дословно — это сырая разметка, она не отрисуется. Дату дня называй один раз (в подзаголовке "
    "блока), не повторяй её во вводной фразе. Если в нужный день пар нет — скажи это один раз, без повторов."
)

WEB_SEARCH_NOTE = (
    "Если для ответа нужны свежие/проверяемые факты (новости, что вышло, курсы, погода, события) "
    "или пользователь просит «загугли …», «найди в интернете …», «поищи …» — вызови web_search. "
    "Бери факты из его выдачи, не выдумывай. Для точных/новостных/спорных вопросов в конце дай "
    "блок «Источники» с 2–3 ссылками в markdown-формате [название](url). Для бытового и быстрого "
    "(погода, простой факт) — обычный ответ без ссылок. Если поиск не дал результата или вернул "
    "ошибку — честно скажи, что найти не удалось."
)

REMINDER_NOTE = (
    "Если пользователь просит создать/изменить/отменить/показать напоминание — ОБЯЗАТЕЛЬНО вызови "
    "соответствующий тул напоминаний. Относительное время («через 10 минут», «через две минуты», "
    "«через час», «через полчаса») — это полноценная просьба о напоминании: посчитай момент от "
    "контекста времени и передай в when_iso готовой датой-временем. НИКОГДА не пиши «сделано», "
    "«напомню», «поставил» БЕЗ вызова тула — без вызова напоминание не создаётся, и это будет ложь. "
    "Карточку, подтверждение и список бот отправляет сам отдельным сообщением; ты отвечай ОДНОЙ "
    "короткой фразой, не пересказывая детали и не выдумывая время."
)


def _flow_label(*, streamed: bool, called_tools: list[str]) -> str:
    """Метка для лога: ось доставки (LLM / LLM stream) + факт вызова тулов."""
    delivery = "LLM stream" if streamed else "LLM"
    parts = [delivery]
    if called_tools:
        parts.append(f"tool: {', '.join(called_tools)}")
    return "; ".join(parts)


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
    messages = _inject_system_note(messages, WEB_SEARCH_NOTE)
    messages = _inject_system_note(messages, REMINDER_NOTE)
    prefix = f"{first_name}, " if (first_name and not has_context and not is_group_chat) else ""
    renderer = StreamRenderer(message, prefix=prefix)
    await renderer.start(pick_placeholder_variant().text)

    # Один и тот же приёмник на обе фазы: токены копятся в буфер, но до старта тула затвор
    # закрыт (болтовня не показывается). Откроется в on_tool_start — тогда стримим пост-тульный ответ.
    async def llm_call(msgs, tools):
        return await stream_with_tools(msgs, tools, on_content_token=renderer.feed)

    async def on_tool_start(name: str) -> None:
        renderer.open_gate()
        await renderer.show_tool_indicator(name)

    try:
        result: ToolLoopResult = await run_tool_loop(
            messages, tool_context, registry=registry, llm_call=llm_call,
            max_tool_rounds=2, on_tool_start=on_tool_start)
    except LLMServiceError as exc:
        logger.warning("tool-flow LLM error: %s", exc)
        await renderer.finalize(ERROR_NOTICE_PLAIN)
        await notify_owner_error(
            message.bot, exc,
            tg_id=message.from_user.id if message.from_user else None,
            username=message.from_user.username if message.from_user else None,
            context=f"LLM tool-flow ({'GR' if is_group_chat else 'PM'})",
            extra=f"chat_id={message.chat.id}; запрос: {text_for_llm[:300]}")
        return True

    if result.denial:
        await renderer.finalize(result.denial)
        return True

    final_answer = format_final_answer(first_name, result.text or "", has_context)
    # При подавленном финале (тул сам отправил карточку) в контекст кладём служебную пометку
    # тула вместо пустого ответа — чтобы продолжения («перенеси на 16:00») имели опору.
    if result.suppress_text and result.context_note:
        context_answer = result.context_note
    elif is_group_chat:
        context_answer = format_final_answer("", result.text or "", has_context)
    else:
        context_answer = final_answer
    context_service.save_context(message.chat.id, text_for_llm, context_answer)

    # Тул уже отправил готовое сообщение (карточка/подтверждение напоминания) — финальную
    # фразу LLM не показываем, только убираем плейсхолдер ожидания. Контекст уже сохранён выше.
    if result.suppress_text:
        await renderer.discard()
        await send_tool_loop_extras(message, deferred_messages=result.deferred_messages, denial=None)
        logger.info("%s; Бот (tool: %s) для %s: [тихо — сообщение отправил тул]",
                    "GR" if is_group_chat else "PM",
                    ", ".join(result.called_tools) or "?", user_login or "?")
        return True

    if not await renderer.finalize(final_answer):
        logger.warning("%s; tool-flow finalize не доставил ответ для %s",
                       "GR" if is_group_chat else "PM", user_login or "?")
        await notify_owner_error(
            message.bot, Exception("finalize failed"),
            tg_id=message.from_user.id if message.from_user else None,
            username=message.from_user.username if message.from_user else None,
            context=f"Telegram delivery tool-flow ({'GR' if is_group_chat else 'PM'})",
            extra=f"chat_id={message.chat.id}; ответ: {final_answer[:300]}")
        return True

    await send_tool_loop_extras(message, deferred_messages=result.deferred_messages, denial=None)
    flow_label = _flow_label(streamed=renderer.streamed, called_tools=result.called_tools)
    logger.info("%s; Бот (%s) для %s: %s", "GR" if is_group_chat else "PM",
                flow_label, user_login or "?", final_answer)
    return True
