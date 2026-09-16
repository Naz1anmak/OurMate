"""Потоковая и финальная отправка ответов LLM."""
import logging
from collections import deque
import time
import html as _html
import re

from aiogram.types import BufferedInputFile, Message
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessageDraft
from aiogram.enums import ChatAction
from aiogram.utils.chat_action import ChatActionSender

from src.bot.services.llm_service import LLMServiceError, stream_with_tools
from src.bot.services.llm_tools import run_tool_loop, ToolLoopResult
from src.bot.services.context_service import context_service
from src.bot.services.usage_limit import enforce_usage_limit
from src.bot.services.tts_service import TTSServiceError, is_voice_enabled, synthesize_voice
from src.config.settings import VOICE_MIN_CHARS

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

# Парные маркеры markdown в порядке разбора: fence раньше одиночного backtick, ** раньше *.
_STREAM_MARKERS = ("```", "**", "__", "`", "*", "_")


def _stream_safe_prefix(text: str) -> str:
    """Обрезает промежуточный кадр стрима до места, где разметка целая.

    `render_html_with_code` конвертирует только закрытые пары, поэтому недописанное `**жирное`
    показалось бы голыми звёздочками, а следующий кадр их схлопнул — отсюда мигание. Незакрытый
    маркер откусываем вместе с хвостом; если маркеров нет — отрезаем последнее слово, чтобы кадр
    не обрывался на его середине. Финал через эту обрезку не идёт: там текст уже полный.
    """
    for marker in _STREAM_MARKERS:
        if text.count(marker) % 2:
            return text[:text.rfind(marker)].rstrip()

    if not text or text[-1].isspace():
        return text.rstrip()
    cut = max(text.rfind(" "), text.rfind("\n"))
    return text[:cut].rstrip() if cut > 0 else ""


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

VOICE_MARKER = "[voice]"

# Теги эмоций и паузы MiniMax (speech-2.8): в голосе звучат, в тексте — мусор.
_VOICE_TAG_RE = re.compile(
    r"\s*\((?:laughs|chuckle|coughs|clear-throat|groans|breath|pant|inhale|exhale|gasps|sniffs|"
    r"sighs|snorts|burps|lip-smacking|humming|hissing|emm|sneezes)\)"
    r"|\s*<#\d+(?:\.\d+)?#>")


def detect_voice_marker(text: str) -> bool | None:
    """По началу ответа: True — голос, False — текст, None — рано судить (пришла часть маркера)."""
    head = text.lstrip()
    if head.startswith(VOICE_MARKER):
        return True
    if VOICE_MARKER.startswith(head):
        return None
    return False


def strip_voice_marker(text: str) -> tuple[bool, str]:
    """Срезает маркер [voice] в начале ответа. Маркер не в начале — не маркер."""
    head = text.lstrip()
    if head.startswith(VOICE_MARKER):
        return True, head[len(VOICE_MARKER):].lstrip()
    return False, text


def strip_voice_tags(text: str) -> str:
    """Убирает теги эмоций и паузы, когда голосовой ответ всё-таки уходит текстом."""
    return _VOICE_TAG_RE.sub("", text).strip()


def _voice_audience_allowed(tool_context: dict, is_group_chat: bool) -> bool:
    """Голос разрешён этой аудитории: любая группа, либо в ЛС — владелец/whitelisted."""
    return is_group_chat or bool(tool_context.get("is_owner") or tool_context.get("is_whitelisted_private"))


def should_send_voice(*, is_voice: bool, text: str, called_tools: list[str],
                      tool_context: dict, is_group_chat: bool) -> bool:
    """Голос — только по маркеру модели, без тулов, не короче порога; в ЛС — владельцу и whitelisted."""
    if not (is_voice and is_voice_enabled()) or called_tools:
        return False
    if len(strip_voice_tags(text)) < VOICE_MIN_CHARS:
        return False
    return _voice_audience_allowed(tool_context, is_group_chat)


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

    # Telegram даёт ~20 эдитов в минуту на групповой чат, причём окно скользящее. Бюджет стрима
    # держим ниже с запасом на плейсхолдер, тул-индикатор и — главное — финальный эдит, который
    # обязан пройти. Короткий ответ в бюджет укладывается целиком и тормозов не замечает;
    # длинный упирается в потолок, и пауза между эдитами растёт сама собой.
    EDIT_BUDGET_PER_MIN = 14
    EDIT_WINDOW_SEC = 60.0

    def __init__(self, message, *, prefix: str = "", detect_voice: bool = False):
        self.message = message
        self.is_group = message.chat.type in ("group", "supergroup")
        self.use_draft = message.chat.type == "private"
        self.placeholder = None
        self.streamed = False
        self.draft_id = int(time.monotonic_ns() % 900_000_000) + 1
        self.prefix = prefix
        self.buffer = prefix
        self.last_sent_len = len(prefix)
        self.last_flush = 0.0
        # Голос: None — ещё не ясно по началу ответа, True — ответ уйдёт голосовым (стрим молчит),
        # False — обычный текст. detect_voice=False — детект выключен, стрим как раньше.
        self.detect_voice = detect_voice
        self.voice_mode: bool | None = None
        self._voice_action: ChatActionSender | None = None
        # Базовая частота: оба порога обязательны (см. feed). Держим её высокой — короткий ответ
        # должен рисоваться живо; от превышения лимита защищает бюджет окна, а не эти пороги.
        self.min_interval = 1.0 if self.is_group else 0.5
        self.min_chars = 100 if self.is_group else 40
        # Отметки эдитов за последнюю минуту: лимит Telegram скользящий, поэтому и учёт скользящий.
        self._edits: deque[float] = deque()
        self._now = time.monotonic

    async def start(self, placeholder_text: str) -> None:
        """В группе показывает заглушку ожидания; в ЛС стрим идёт драфтами без отдельного плейсхолдера."""
        if self.is_group:
            try:
                self.placeholder = await self.message.reply(placeholder_text, parse_mode="HTML")
            except Exception as exc:  # noqa: BLE001
                logger.debug("StreamRenderer start failed: %s", exc)
                self.placeholder = None

    async def show_tool_indicator(self, tool_name: str) -> None:
        """В группе подменяет плейсхолдер на тул-индикатор (web_search и т.п.). В ЛС — ничего.
        Если плейсхолдера уже нет (например, discard() убрал его при входе в voice-режим на
        раунде 1) — создаём заново тем же способом, что start(), иначе индикатор тула и
        последующий стрим второго раунда молча теряются."""
        text = TOOL_INDICATORS.get(tool_name)
        if not text or not self.is_group:
            return
        try:
            if self.placeholder:
                await self.message.bot.edit_message_text(
                    chat_id=self.placeholder.chat.id,
                    message_id=self.placeholder.message_id,
                    text=text, parse_mode="HTML")
            else:
                self.placeholder = await self.message.reply(text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            logger.debug("show_tool_indicator failed: %s", exc)

    async def _enter_voice_mode(self) -> None:
        """Убираем «Думаю…» и держим в шапке «записывает голосовое», пока не придёт аудио."""
        await self.discard()
        if self._voice_action is None:
            self._voice_action = ChatActionSender(
                bot=self.message.bot, chat_id=self.message.chat.id, action=ChatAction.RECORD_VOICE)
            try:
                await self._voice_action.__aenter__()
            except Exception as exc:  # noqa: BLE001
                logger.debug("StreamRenderer voice action start failed: %s", exc)
                self._voice_action = None

    async def stop_voice_action(self) -> None:
        """Гасит фоновый chat action. Идемпотентно."""
        if self._voice_action is None:
            return
        action, self._voice_action = self._voice_action, None
        try:
            await action.__aexit__(None, None, None)
        except Exception as exc:  # noqa: BLE001
            logger.debug("StreamRenderer voice action stop failed: %s", exc)

    def reset_buffer(self) -> None:
        """Сброс буфера на префикс при старте тула: до-тульная болтовня не должна примешаться
        к пост-тульному ответу следующего раунда (web_search и т.п.)."""
        self.buffer = self.prefix
        self.last_sent_len = len(self.prefix)
        self.voice_mode = None

    def _budget_left(self, now: float) -> bool:
        """Есть ли в скользящем окне место под ещё один эдит. В ЛС бюджет не считаем: там драфты,
        они в лимит сообщений не идут."""
        if self.use_draft:
            return True
        while self._edits and now - self._edits[0] > self.EDIT_WINDOW_SEC:
            self._edits.popleft()
        return len(self._edits) < self.EDIT_BUDGET_PER_MIN

    async def feed(self, token: str) -> None:
        self.buffer += token
        if self.detect_voice and self.voice_mode is None:
            decided = detect_voice_marker(self.buffer[len(self.prefix):])
            if decided is None:
                return  # пришла только часть маркера — ничего не показываем
            self.voice_mode = decided
            if decided:
                await self._enter_voice_mode()
        if self.voice_mode:
            return  # голосовой ответ: токены копятся, кадры не рисуем
        now = self._now()
        # Раньше здесь было `and`: хватало набежавших символов, и поле по времени не работало
        # вовсе — длинный ответ уходил десятками эдитов и ловил флуд-контроль на финале.
        if (len(self.buffer) - self.last_sent_len) < self.min_chars or (now - self.last_flush) < self.min_interval:
            return
        safe = _stream_safe_prefix(self.buffer)
        if len(safe) <= self.last_sent_len:
            # Весь прирост — внутри незакрытой разметки: показывать нечего, бюджет не тратим.
            return
        if not self._budget_left(now):
            # Бюджет минуты выбран: молчим, буфер продолжает копиться — ничего не теряется,
            # а освободившееся место окно отдаст само, когда старые эдиты из него выпадут.
            return
        self._edits.append(now)
        await self._render(safe)
        # Считаем по показанному, а не по буферу: иначе недописанный хвост учитывался бы как
        # отрисованный и следующий кадр ждал бы лишние min_chars.
        self.last_sent_len = len(safe)
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
        except TelegramRetryAfter as exc:
            # Упёрлись в флуд-контроль: молчим до конца окна, иначе добиваем бюджет впустую
            # и рискуем потерять финальную доставку.
            self.last_flush = self._now() + exc.retry_after
            logger.debug("StreamRenderer render: флуд-контроль, пауза %s с", exc.retry_after)
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
            # Гасим драфт пустым текстом ТОЛЬКО если мы его реально открыли (что-то отрисовали).
            # Иначе слать пустой SendMessageDraft нельзя — он сам прилетит пустым пузырём после
            # карточки тула. Нет драфта — нечего гасить.
            try:
                await self.message.bot(SendMessageDraft(
                    chat_id=self.message.chat.id, draft_id=self.draft_id, text=""))
            except Exception as exc:  # noqa: BLE001
                logger.debug("StreamRenderer draft clear failed: %s", exc)

    async def finalize(self, final_text: str) -> bool:
        """Фиксирует финал: эдит плейсхолдера (группа) или реальное сообщение (ЛС — драфт эфемерен)."""
        await self.stop_voice_action()
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
        except TelegramRetryAfter as exc:
            logger.warning("StreamRenderer finalize: флуд-контроль (retry_after=%s), шлём отдельным сообщением",
                           exc.retry_after)
            return await self._finalize_as_new_message(safe)
        except Exception as exc:  # noqa: BLE001
            logger.warning("StreamRenderer finalize failed: %s", exc)
            return False

    async def _finalize_as_new_message(self, safe: str) -> bool:
        """Фолбэк на флуд-контроле: лимит на новые сообщения отдельный и стримом не выбран,
        поэтому ответ доставляем отдельным сообщением, а недорисованный плейсхолдер убираем."""
        try:
            await self.message.reply(safe, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("StreamRenderer finalize fallback failed: %s", exc)
            return False
        if self.placeholder:
            try:
                await self.message.bot.delete_message(
                    self.placeholder.chat.id, self.placeholder.message_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("StreamRenderer finalize fallback: плейсхолдер не убран (%s)", exc)
            self.placeholder = None
        return True


SCHEDULE_PRESENTATION_NOTE = (
    "Расписание: если пользователь спрашивает о парах, занятиях или расписании (сегодня, завтра, "
    "в конкретный день, «что у нас», «есть ли пары» и т.п.) — ОБЯЗАТЕЛЬНО вызови get_schedule. "
    "Никогда не отвечай о расписании по памяти, предположению или из-за дня недели — "
    "только по данным тула. Суббота, воскресенье и праздники не означают автоматически «пар нет»: "
    "экзамены и зачёты бывают в любой день. "
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

NOTES_NOTE = (
    "Любое действие со списком/очередью (создать, показать, добавить/убрать/переставить/поменять "
    "местами участника, задать имя или примечание, удалить/очистить) выполняется ТОЛЬКО через "
    "вызов соответствующего тула списков. НИКОГДА не пиши сам строку в квадратных скобках вида "
    "«[… добавлен]», «[примечание добавлено]», «[создан список]» и не сообщай, что действие "
    "выполнено, БЕЗ вызова тула — такие строки в истории это внутренние записи о прошлых вызовах, "
    "а НЕ образец для твоего ответа; без вызова тула действие НЕ происходит, и это будет ложь. "
    "Если в одном сообщении просят несколько действий (например добавить и сразу дать примечание) "
    "— вызови нужные тулы по очереди, не ограничивайся текстом. Карточку бот перерисует сам; "
    "ты отвечай одной короткой фразой."
)

VOICE_NOTE = (
    "Голосовые ответы. Если обращение НЕ техническое — болтовня, шутка, подкол, приветствие, "
    "просьба ответить дерзко или с характером — и для ответа не нужен ни один тул, начни ответ "
    f"с отдельной первой строки {VOICE_MARKER}, а дальше напиши реплику, которую произнесут вслух: "
    "живым разговорным языком, без markdown, списков, эмодзи, ссылок и обращения по имени в начале. "
    "Для живости можно вставить 1–2 звука там, где так сказал бы человек: (chuckle) — смешок, "
    "(emm) — «э-э» перед мыслью; не в самом начале реплики. Изредка пауза <#0.5#>. Другие звуки "
    "в скобках не используй и не ставь их подряд. Голос меняет только форму ответа: характер, манеру и правила общения "
    "из основного промпта сохраняй. "
    f"Технические и учебные вопросы, расписание, списки, напоминания, поиск — БЕЗ {VOICE_MARKER}, "
    "обычным текстовым ответом."
)


def _flow_label(*, streamed: bool, called_tools: list[str], voice: bool = False) -> str:
    """Метка для лога: ось доставки (LLM / LLM stream / LLM voice) + факт вызова тулов."""
    delivery = "LLM voice" if voice else ("LLM stream" if streamed else "LLM")
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


async def _deliver_voice(message, text: str, *, is_group_chat: bool) -> bool:
    """Синтез и отправка голосового. False — не вышло, вызывающий шлёт тот же ответ текстом."""
    tg_id = message.from_user.id if message.from_user else None
    username = message.from_user.username if message.from_user else None
    label = "GR" if is_group_chat else "PM"
    try:
        voice = BufferedInputFile(await synthesize_voice(text), filename="voice.ogg")
        if is_group_chat:
            await message.reply_voice(voice)
        else:
            await message.answer_voice(voice)
        return True
    except TelegramBadRequest as exc:
        if "VOICE_MESSAGES_FORBIDDEN" in str(exc):
            # Пользователь запретил себе голосовые — это не сбой, просто отвечаем текстом.
            logger.info("%s; голосовые запрещены у получателя, шлём текст", label)
            return False
        await notify_owner_error(message.bot, exc, tg_id=tg_id, username=username,
                                 context=f"Telegram voice delivery ({label})",
                                 extra=f"chat_id={message.chat.id}")
        return False
    except Exception as exc:  # noqa: BLE001 — TTSServiceError и любой сбой доставки → текстовый фолбэк
        logger.warning("%s; голосовой ответ не отправлен: %s", label, exc)
        await notify_owner_error(message.bot, exc, tg_id=tg_id, username=username,
                                 context=f"TTS ({label})", extra=f"chat_id={message.chat.id}")
        return False


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
    if await enforce_usage_limit(message, tool_context):
        return True  # дневной лимит исчерпан — блок отправлен, LLM не трогаем
    is_group_chat = message.chat.type in ("group", "supergroup")
    messages = _inject_system_note(messages, SCHEDULE_PRESENTATION_NOTE)
    messages = _inject_system_note(messages, WEB_SEARCH_NOTE)
    messages = _inject_system_note(messages, REMINDER_NOTE)
    messages = _inject_system_note(messages, NOTES_NOTE)
    voice_enabled = is_voice_enabled()
    if voice_enabled:
        messages = _inject_system_note(messages, VOICE_NOTE)
    prefix = f"{first_name}, " if (first_name and not has_context and not is_group_chat) else ""
    detect_voice = voice_enabled and _voice_audience_allowed(tool_context, is_group_chat)
    renderer = StreamRenderer(message, prefix=prefix, detect_voice=detect_voice)
    await renderer.start(pick_placeholder_variant().text)

    # Один и тот же приёмник на обе фазы стрима. На старте тула буфер сбрасывается (reset_buffer),
    # чтобы до-тульная болтовня раунда 1 не примешалась к пост-тульному ответу второго раунда.
    async def llm_call(msgs, tools):
        return await stream_with_tools(msgs, tools, on_content_token=renderer.feed)

    async def on_tool_start(name: str) -> None:
        # Раунд 1 мог решить, что ответ голосовой (voice_mode=True) и уйти в фоновый chat action —
        # гасим его перед вторым раундом, иначе «записывает голосовое» повиснет поверх тул-индикатора.
        await renderer.stop_voice_action()
        renderer.reset_buffer()
        await renderer.show_tool_indicator(name)

    # На любом выходе из тела ниже (штатный return, необработанное исключение, CancelledError)
    # обязаны погасить фоновый chat action «записывает голосовое» — иначе он висит вечно.
    # stop_voice_action идемпотентен, повторный явный вызов внутри тела не мешает.
    try:
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

        # Маркер [voice] срезаем всегда (даже при выключенной фиче); теги эмоций в тексте — мусор.
        is_voice, answer_text = strip_voice_marker(result.text or "")
        text_body = strip_voice_tags(answer_text) if is_voice else answer_text
        final_answer = format_final_answer(first_name, text_body, has_context)
        # При подавленном финале (тул сам отправил карточку) в контекст кладём служебную пометку
        # тула вместо пустого ответа — чтобы продолжения («перенеси на 16:00») имели опору.
        if result.suppress_text and result.context_note:
            context_answer = result.context_note
        elif is_group_chat:
            context_answer = format_final_answer("", text_body, has_context)
        else:
            context_answer = format_final_answer(first_name, text_body, has_context)
        context_service.save_context(message.chat.id, text_for_llm, context_answer)

        # Тул уже отправил готовое сообщение (карточка/подтверждение напоминания) — финальную
        # фразу LLM не показываем, только убираем плейсхолдер ожидания. Контекст уже сохранён выше.
        if result.suppress_text:
            await renderer.stop_voice_action()
            await renderer.discard()
            await send_tool_loop_extras(message, deferred_messages=result.deferred_messages, denial=None)
            logger.info("%s; Бот (tool: %s) для %s: [тихо — тул отправил сообщение сам]",
                        "GR" if is_group_chat else "PM",
                        ", ".join(result.called_tools) or "?", user_login or "?")
            return True

        if should_send_voice(is_voice=is_voice, text=answer_text, called_tools=result.called_tools,
                             tool_context=tool_context, is_group_chat=is_group_chat):
            delivered = await _deliver_voice(message, answer_text, is_group_chat=is_group_chat)
            if delivered:
                await renderer.stop_voice_action()
                await renderer.discard()  # идемпотентно: «Думаю…» могло остаться, если маркер не прошёл через feed
                await send_tool_loop_extras(message, deferred_messages=result.deferred_messages, denial=None)
                logger.info("%s; Бот (%s) для %s: %s", "GR" if is_group_chat else "PM",
                            _flow_label(streamed=False, called_tools=result.called_tools, voice=True),
                            user_login or "?", answer_text)
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
    finally:
        await renderer.stop_voice_action()
