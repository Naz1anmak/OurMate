"""Парсинг lessons из JSON RUZ в ScheduleEvent, нормализация типа занятия."""
import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from src.bot.services.schedule_service import ScheduleEvent
from src.config.settings import TIMEZONE

logger = logging.getLogger(__name__)

_KIND_MAP = {
    "Лекции": "Лекция",
    "Практические занятия": "Практика",
    "Лабораторные работы": "Лаб.",
    "Экзамен": "Экзамен",
    "Зачёт": "Зачёт",
}


def normalize_kind(raw: str | None) -> str:
    if not raw:
        return ""
    return _KIND_MAP.get(raw.strip(), raw.strip())


def parse_lessons(raw_lessons: list[dict]) -> list[ScheduleEvent]:
    """Конвертирует список raw lessons RUZ → ScheduleEvent. Битые записи пропускает."""
    events: list[ScheduleEvent] = []
    for lesson in raw_lessons:
        try:
            day_str = lesson["__date"]  # "2026-05-26"
            day = date.fromisoformat(day_str)
            t_start = _parse_time(lesson["time_start"])
            t_end = _parse_time(lesson["time_end"])
            start = datetime.combine(day, t_start, tzinfo=TIMEZONE)
            end = datetime.combine(day, t_end, tzinfo=TIMEZONE)
            summary = (lesson.get("subject") or "").strip()
            kind = normalize_kind((lesson.get("typeObj") or {}).get("name"))
            location = _format_location(lesson.get("auditories") or [])
            events.append(ScheduleEvent(
                summary=summary,
                location=location,
                start=start,
                end=end,
                kind=kind,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Пропускаю битый lesson %r: %s", lesson.get("subject"), exc)
            continue
    return events


def _parse_time(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def _format_location(auditories: list[dict]) -> str:
    if not auditories:
        return ""
    first = auditories[0]
    name = (first.get("name") or "").strip()
    building = ((first.get("building") or {}).get("name") or "").strip()
    parts = [p for p in (name, building) if p]
    return ", ".join(parts)
