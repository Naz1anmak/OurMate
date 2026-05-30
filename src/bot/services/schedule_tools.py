"""Тул-функции расписания для tool use + их JSON-схемы."""
import functools
import logging
from datetime import date, datetime
from typing import Optional, Tuple, Union

from src.bot.services.llm_tools import ToolRegistry, ToolSpec
from src.bot.services.schedule_service import ScheduleEvent, schedule_service
from src.config.settings import RUZ_WEEKS_AHEAD, TIMEZONE

logger = logging.getLogger(__name__)

WEEKDAY_NAMES = {0: "понедельник", 1: "вторник", 2: "среда", 3: "четверг",
                 4: "пятница", 5: "суббота", 6: "воскресенье"}

DEFAULT_MAX_DAYS = (RUZ_WEEKS_AHEAD + 1) * 7


def validate_date_range(
    date_from: str, date_to: str, *, max_days: int = DEFAULT_MAX_DAYS
) -> Tuple[bool, Union[Tuple[date, date], dict]]:
    """Парсит и валидирует ISO-диапазон. (True, (from, to)) или (False, {"error","hint"})."""
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except (ValueError, TypeError):
        return False, {"error": "bad_range", "hint": "Даты должны быть в формате YYYY-MM-DD."}
    if d_from > d_to:
        return False, {"error": "bad_range", "hint": "date_from позже date_to."}
    if (d_to - d_from).days > max_days:
        return False, {"error": "bad_range", "hint": f"Диапазон больше {max_days} дней."}
    return True, (d_from, d_to)


def _event_payload(e: ScheduleEvent) -> dict:
    return {
        "date": e.start.date().isoformat(),
        "weekday": WEEKDAY_NAMES[e.start.weekday()],
        "start": f"{e.start:%H:%M}",
        "end": f"{e.end:%H:%M}",
        "kind": e.kind,
        "summary": e.summary,
        "groups": sorted(g for g in e.groups if g),
    }


def _title_for(service: "ScheduleService", d: date, today: date) -> str:
    """Заголовок блока дня: сегодня/завтра — словом без числа, иначе «Пары в понедельник (01.06)»."""
    if d == today:
        return "Пары на сегодня"
    if d.toordinal() == today.toordinal() + 1:
        return "Пары на завтра"
    return f"Пары {service.weekday_with_preposition(d)} ({d:%d.%m})"


def _day_phrase(service: "ScheduleService", d: date, today: date) -> str:
    """Краткая форма дня для «пар нет»: сегодня/завтра без числа, иначе «в понедельник (01.06)»."""
    if d == today:
        return "сегодня"
    if d.toordinal() == today.toordinal() + 1:
        return "завтра"
    return f"{service.weekday_with_preposition(d)} ({d:%d.%m})"


async def get_schedule(
    date_from: str,
    date_to: str,
    *,
    tool_context: dict,
    service: "ScheduleService" = schedule_service,
    refresher=None,
    now: Optional[datetime] = None,
) -> dict:
    """Возвращает гибрид {formatted, events, empty} за дату/диапазон. Diff (если есть) — в _deferred."""
    ok, value = validate_date_range(date_from, date_to)
    if not ok:
        return value  # {"error": "bad_range", "hint": ...}
    d_from, d_to = value
    today = (now or datetime.now(service.timezone)).date()

    deferred: list[str] = []
    if tool_context.get("allow_refresh") and refresher is not None:
        try:
            result = await refresher.ensure_fresh("tool:get_schedule")
            if getattr(result, "diff_message", None):
                deferred.append(result.diff_message)
        except Exception as exc:  # noqa: BLE001  — старый снимок остаётся, не падаем
            logger.warning("ensure_fresh из тула упал: %s", exc)

    in_range = [e for e in service.events if d_from <= e.start.date() <= d_to]

    if not in_range:
        # Пусто — не ошибка: «пар нет» + ближайшие будущие пары. День называем словом для
        # сегодня/завтра и «день недели (дд.мм)» для остальных. Заголовок блока ближайших
        # пар якорим к СЕГОДНЯ (_title_for), а не к запрошенному дню, — иначе «завтра» из
        # блока схлопывается с «завтра» из вопроса и LLM путает дни.
        if d_from == d_to:
            day_label = _day_phrase(service, d_from, today)
        else:
            day_label = f"в период {d_from:%d.%m}–{d_to:%d.%m}"
        empty_text = service.get_no_pairs_message(day_label)
        next_date, next_events = service.get_next_classes_after(d_to)
        formatted = empty_text
        if next_date and next_events:
            formatted = f"{empty_text}\n\n{service.format_day_block(next_date, _title_for(service, next_date, today))}"
        out = {"formatted": formatted, "events": [], "empty": True}
        if deferred:
            out["_deferred"] = deferred
        return out

    # Есть события: по блоку на каждую дату диапазона, где есть пары.
    dates = sorted({e.start.date() for e in in_range})
    blocks = [service.format_day_block(d, _title_for(service, d, today)) for d in dates]
    out = {
        "formatted": "\n\n".join(b for b in blocks if b),
        "events": [_event_payload(e) for e in sorted(in_range, key=lambda e: e.start)],
        "empty": False,
    }
    if deferred:
        out["_deferred"] = deferred
    return out


async def find_next_class(
    subject: str,
    *,
    tool_context: dict,
    service: "ScheduleService" = schedule_service,
    refresher=None,
    now: Optional[datetime] = None,
) -> dict:
    """Все будущие пары, чьё summary содержит subject (подстрока, регистронезависимо), отсортированные по дате.

    Возвращает весь список предстоящих занятий по предмету (практики, лекции, зачёты, экзамены),
    а не только ближайшее, — чтобы по виду пары можно было ответить на «когда экзамен/зачёт по X».
    """
    if tool_context.get("allow_refresh") and refresher is not None:
        try:
            await refresher.ensure_fresh("tool:find_next_class")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_fresh из find_next_class упал: %s", exc)

    now = now or datetime.now(service.timezone)
    from_date = now.date()
    needle = " ".join(subject.lower().split())

    matches = [
        e for e in sorted(service.events, key=lambda e: e.start)
        if e.start.date() >= from_date and needle in " ".join(e.summary.lower().split())
    ]
    if not matches:
        return {"found": False, "events": []}

    return {"found": True, "events": [_event_payload(e) for e in matches[:20]]}


GET_SCHEDULE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_schedule",
        "description": (
            "Вернуть пары за конкретную дату или диапазон дат. Используй для вопросов "
            "«что в субботу», «пары завтра», «что на следующей неделе», а также для агрегатов "
            "вроде «во сколько последняя пара» (возьми сегодняшнюю дату и рассуди по events). "
            "Даты передавай в ISO YYYY-MM-DD, относительные («суббота», «завтра») сам переведи "
            "в даты от сегодняшней."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Начало диапазона, ISO YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Конец диапазона включительно, ISO YYYY-MM-DD. Для одного дня = date_from."},
            },
            "required": ["date_from", "date_to"],
        },
    },
}

FIND_NEXT_CLASS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "find_next_class",
        "description": (
            "Вернуть все предстоящие занятия по предмету (отсортированы по дате): практики, лекции, "
            "зачёты, экзамены. Используй для «когда следующая физика», «когда экзамен по базам данных», "
            "«когда зачёт по матану» — потом сам выбери нужное занятие по полю kind (Лекция/Практика/"
            "Зачет/Экзамен). subject — название предмета или его часть."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Название предмета или его часть."},
            },
            "required": ["subject"],
        },
    },
}


def build_schedule_registry(*, refresher) -> ToolRegistry:
    """Собирает реестр с тулами расписания, привязанными к глобальному schedule_service и refresher."""
    reg = ToolRegistry()
    reg.register("get_schedule", ToolSpec(
        schema=GET_SCHEDULE_SCHEMA,
        func=functools.partial(get_schedule, refresher=refresher),
        gate="schedule_allowed",
    ))
    reg.register("find_next_class", ToolSpec(
        schema=FIND_NEXT_CLASS_SCHEMA,
        func=functools.partial(find_next_class, refresher=refresher),
        gate="schedule_allowed",
    ))
    return reg
