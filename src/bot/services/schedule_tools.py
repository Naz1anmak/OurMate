"""Тул-функции расписания для tool use + их JSON-схемы."""
import logging
from datetime import date, datetime
from typing import Optional, Tuple, Union

from src.bot.services.llm_tools import ToolSpec
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
        "location": e.location,
        "groups": sorted(g for g in e.groups if g),
    }


def _title_for(service: "ScheduleService", d: date) -> str:
    today = datetime.now(service.timezone).date()
    if d == today:
        return "Пары на сегодня"
    if d.toordinal() == today.toordinal() + 1:
        return "Пары на завтра"
    return f"Пары {service.weekday_with_preposition(d)} ({d:%d.%m})"


async def get_schedule(
    date_from: str,
    date_to: str,
    *,
    tool_context: dict,
    service: "ScheduleService" = schedule_service,
    refresher=None,
) -> dict:
    """Возвращает гибрид {formatted, events, empty} за дату/диапазон. Diff (если есть) — в _deferred."""
    ok, value = validate_date_range(date_from, date_to)
    if not ok:
        return value  # {"error": "bad_range", "hint": ...}
    d_from, d_to = value

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
        # Пусто — не ошибка: «пар нет» + ближайшие будущие пары (как команда «пары»).
        label = "сегодня" if d_from == datetime.now(service.timezone).date() else _title_for(service, d_from).lower()
        empty_text = service.get_no_pairs_message(label if label in ("сегодня", "завтра") else "в этот день")
        next_date, next_events = service.get_next_classes_after(d_to)
        formatted = empty_text
        if next_date and next_events:
            formatted = f"{empty_text}\n\n{service.format_next_classes_block(next_date, base_date=d_to)}"
        out = {"formatted": formatted, "events": [], "empty": True}
        if deferred:
            out["_deferred"] = deferred
        return out

    # Есть события: по блоку на каждую дату диапазона, где есть пары.
    dates = sorted({e.start.date() for e in in_range})
    blocks = [service.format_day_block(d, _title_for(service, d)) for d in dates]
    out = {
        "formatted": "\n\n".join(b for b in blocks if b),
        "events": [_event_payload(e) for e in sorted(in_range, key=lambda e: e.start)],
        "empty": False,
    }
    if deferred:
        out["_deferred"] = deferred
    return out
