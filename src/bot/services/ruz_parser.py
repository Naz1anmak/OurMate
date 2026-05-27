"""Парсинг lessons из JSON-расписания в ScheduleEvent, нормализация типа занятия."""
import json
import logging
import os
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from src.bot.services.schedule_service import ScheduleEvent
from src.config.settings import SCHEDULE_GROUPS_DIR, TIMEZONE

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
    """Конвертирует список raw lessons из JSON-расписания → ScheduleEvent. Битые пропускает."""
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


def save_schedule(code: str, events: list[ScheduleEvent], *, fetched_at: datetime) -> None:
    """Атомарно пишет schedule.json. .tmp + rename — на случай прерывания."""
    group_dir = Path(SCHEDULE_GROUPS_DIR) / code
    group_dir.mkdir(parents=True, exist_ok=True)
    target = group_dir / "schedule.json"
    tmp = group_dir / "schedule.json.tmp"

    payload = {
        "fetched_at": fetched_at.isoformat(),
        "events": [
            {
                "summary": e.summary,
                "kind": e.kind,
                "location": e.location,
                "start": e.start.isoformat(),
                "end": e.end.isoformat(),
            }
            for e in events
        ],
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def load_schedule(code: str) -> tuple[datetime | None, list[ScheduleEvent]]:
    """Читает schedule.json. При отсутствии/повреждении — (None, [])."""
    target = Path(SCHEDULE_GROUPS_DIR) / code / "schedule.json"
    if not target.exists():
        return None, []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(raw["fetched_at"])
        events: list[ScheduleEvent] = []
        for item in raw.get("events", []):
            events.append(ScheduleEvent(
                summary=item["summary"],
                location=item.get("location", ""),
                start=datetime.fromisoformat(item["start"]),
                end=datetime.fromisoformat(item["end"]),
                kind=item.get("kind", ""),
            ))
        return fetched, events
    except Exception as exc:  # noqa: BLE001
        logger.warning("schedule.json %s повреждён или нечитаем: %s", target, exc)
        return None, []
