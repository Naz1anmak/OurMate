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

# Предлоги/частицы из запроса предмета: их нельзя требовать к совпадению с названием («по физике»).
SUBJECT_STOPWORDS = frozenset({
    "по", "на", "в", "во", "о", "об", "обо", "про", "за", "для", "к", "ко", "с", "со", "у", "от", "из",
})

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


def _token_matches(token: str, words: list[str]) -> bool:
    """Слово запроса «совпадает» со словом названия: подстрока в любую сторону или общий префикс ≥5.

    Префикс гасит русскую морфологию окончаний («цифровой»/«цифровая», «аналитике»/«аналитика»),
    подстрока — сокращения и корни («баз» в «базы», «матан» в «матану»).
    """
    return any(
        token in w or w in token or (min(len(token), len(w)) >= 5 and token[:5] == w[:5])
        for w in words
    )


def _event_payload(e: ScheduleEvent) -> dict:
    payload = {
        "date": e.start.date().isoformat(),
        "weekday": WEEKDAY_NAMES[e.start.weekday()],
        "start": f"{e.start:%H:%M}",
        "end": f"{e.end:%H:%M}",
        "kind": e.kind,
        "summary": e.summary,
        "groups": sorted(g for g in e.groups if g),
        "lesson_groups": sorted(g for g in e.lesson_groups if g),
        "teachers": sorted(t for t in e.teachers if t),
    }
    if e.webinar_url:  # пустую (зачёты/экзамены без трансляции) не кладём — лишний шум
        payload["webinar_url"] = e.webinar_url
    return payload


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


async def find_classes_by_subject(
    subject: str,
    *,
    tool_context: dict,
    service: "ScheduleService" = schedule_service,
    refresher=None,
    now: Optional[datetime] = None,
) -> dict:
    """Все занятия по предмету — прошлые И будущие, отсортированы по дате; у каждого payload['past'].

    Матчинг по набору токенов: каждое слово запроса должно быть подстрокой названия. Это устойчивее
    к порядку слов и морфологии («баз»/«базы»), чем одна непрерывная подстрока, и не даёт экзамену
    «Базы данных» спрятаться мимо запроса. Прошлое возвращаем тоже — чтобы отвечать на «был ли уже
    зачёт/экзамен по X».
    """
    if tool_context.get("allow_refresh") and refresher is not None:
        try:
            await refresher.ensure_fresh("tool:find_classes_by_subject")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_fresh из find_classes_by_subject упал: %s", exc)

    today = (now or datetime.now(service.timezone)).date()
    raw = [t for t in subject.lower().split() if t]
    tokens = [t for t in raw if t not in SUBJECT_STOPWORDS] or raw  # не выкидываем всё, если предмет = стоп-слово
    if not tokens:
        return {"found": False, "events": []}

    matches = sorted(
        (e for e in service.events
         if all(_token_matches(tok, e.summary.lower().split()) for tok in tokens)),
        key=lambda e: e.start,
    )
    if not matches:
        return {"found": False, "events": []}

    # Если событий очень много — оставляем 20 ближайших к сегодня (свежее прошлое + ближайшее будущее,
    # включая будущий экзамен), затем снова по дате.
    if len(matches) > 20:
        matches = sorted(matches, key=lambda e: abs((e.start.date() - today).days))[:20]
        matches.sort(key=lambda e: e.start)

    events = []
    for e in matches:
        payload = _event_payload(e)
        payload["past"] = e.start.date() < today
        events.append(payload)
    return {"found": True, "events": events}


GET_SCHEDULE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_schedule",
        "description": (
            "Вернуть пары за конкретную дату или диапазон дат. Используй для вопросов "
            "«что в субботу», «пары завтра», «что на следующей неделе», а также для агрегатов "
            "вроде «во сколько последняя пара» (возьми сегодняшнюю дату и рассуди по events). "
            "Даты передавай в ISO YYYY-MM-DD, относительные («суббота», «завтра») сам переведи "
            "в даты от сегодняшней. "
            "У каждого события: groups — наши группы, у кого пара; lesson_groups — весь состав "
            "пары по RUZ (включая чужие параллели потока); teachers — преподаватели; webinar_url — "
            "ссылка на онлайн-трансляцию пары (есть не у всех пар; бывает и у зачётов/экзаменов). "
            "ВАЖНО: lesson_groups, teachers и webinar_url — справочный контекст, НЕ выводи их в "
            "обычный ответ. По умолчанию показывай только время, тип и предмет. Преподавателя называй "
            "ТОЛЬКО на прямой вопрос «кто ведёт», состав параллелей — ТОЛЬКО на «с кем у нас занятие» "
            "(бери lesson_groups за вычетом наших групп), ссылку на вебинар — ТОЛЬКО на «где пара»/"
            "«дай ссылку». Не упоминай эти поля по своей инициативе."
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

FIND_CLASSES_BY_SUBJECT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "find_classes_by_subject",
        "description": (
            "Найти все занятия по предмету — прошлые И будущие (отсортированы по дате): лекции, практики, "
            "зачёты, экзамены. У каждого события есть date, weekday, kind и past (true — занятие уже прошло). "
            "Используй для «когда следующая физика», «когда зачёт/экзамен по базам данных» (бери будущие "
            "события нужного kind), а также «был ли уже зачёт/экзамен по X», «что было по X» (смотри события "
            "с past=true). Учти: зачёт и экзамен — разные kind; если зачёта нет, но есть экзамен (или "
            "наоборот) — так и скажи. subject — название предмета или его часть, можно несколько слов. "
            "Также у события есть lesson_groups (весь состав пары по RUZ), teachers (преподаватели) и "
            "webinar_url (ссылка на онлайн-трансляцию, есть не всегда) — это справочный контекст для "
            "вопросов «с кем», «кто ведёт», «где пара»/«дай ссылку». НЕ выводи эти поля в ответ по "
            "своей инициативе — только если спросили именно про это."
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
    reg.register("find_classes_by_subject", ToolSpec(
        schema=FIND_CLASSES_BY_SUBJECT_SCHEMA,
        func=functools.partial(find_classes_by_subject, refresher=refresher),
        gate="schedule_allowed",
    ))
    return reg
