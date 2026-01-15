"""
Сервис работы с расписанием (ICS -> события).
Парсит все файлы по паттерну, кеширует и предоставляет пары на сегодня/завтра.
"""

import json
from dataclasses import dataclass
from datetime import datetime, date, time
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

from icalendar import Calendar

from src.config.settings import SCHEDULE_FILES_PATTERN, SCHEDULE_CACHE_FILE, TIMEZONE


@dataclass
class ScheduleEvent:
    summary: str
    location: str
    start: datetime
    end: datetime


class ScheduleService:
    def __init__(self, timezone: ZoneInfo = TIMEZONE):
        self.timezone = timezone
        self.events: List[ScheduleEvent] = self._load_events()
        self._save_cache()

    def _load_events(self) -> List[ScheduleEvent]:
        events: List[ScheduleEvent] = []
        pattern_path = Path(SCHEDULE_FILES_PATTERN)
        base_dir = pattern_path.parent if pattern_path.parent != Path('.') else Path.cwd()
        glob_pattern = pattern_path.name

        for ics_path in sorted(base_dir.glob(glob_pattern)):
            try:
                events.extend(self._parse_ics(ics_path))
            except Exception:
                continue

        # Сортируем по времени начала
        events.sort(key=lambda e: e.start)
        return events

    def _parse_ics(self, ics_path: Path) -> List[ScheduleEvent]:
        parsed_events: List[ScheduleEvent] = []
        data = ics_path.read_text(encoding="utf-8")
        cal = Calendar.from_ical(data)

        for component in cal.walk():
            if component.name != "VEVENT":
                continue

            dtstart = component.get("dtstart")
            dtend = component.get("dtend")
            summary = str(component.get("summary", "")).strip()
            location = str(component.get("location", "")).strip()

            if not dtstart:
                continue

            start_dt = self._to_tz(dtstart.dt)
            end_dt = self._to_tz(dtend.dt if dtend else dtstart.dt)

            parsed_events.append(
                ScheduleEvent(
                    summary=summary,
                    location=location,
                    start=start_dt,
                    end=end_dt,
                )
            )
        return parsed_events

    def _to_tz(self, dt) -> datetime:
        """Приводит дату/время к self.timezone."""
        if isinstance(dt, date) and not isinstance(dt, datetime):
            # День без времени — считаем с 00:00
            dt = datetime.combine(dt, time.min)
        if dt.tzinfo is None:
            # Если без tzinfo, считаем что это UTC
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(self.timezone)

    def _save_cache(self) -> None:
        """Сохраняет кеш событий в JSON (для отладки и возможного быстрого доступа)."""
        try:
            SCHEDULE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            serializable = [
                {
                    "summary": e.summary,
                    "location": e.location,
                    "start": e.start.isoformat(),
                    "end": e.end.isoformat(),
                }
                for e in self.events
            ]
            SCHEDULE_CACHE_FILE.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            # Кеш не критичен
            pass

    def _events_for_date(self, target_date: date) -> List[ScheduleEvent]:
        return [e for e in self.events if e.start.date() == target_date]

    def get_todays_classes(self, timezone: ZoneInfo) -> List[ScheduleEvent]:
        today = datetime.now(timezone).date()
        return self._events_for_date(today)

    def get_tomorrows_classes(self, timezone: ZoneInfo) -> List[ScheduleEvent]:
        today = datetime.now(timezone).date()
        tomorrow = date.fromordinal(today.toordinal() + 1)
        return self._events_for_date(tomorrow)

    def format_classes(self, events: List[ScheduleEvent], title: str, empty_text: str) -> str:
        if not events:
            return empty_text

        lines = [title, ""]
        for e in events:
            time_range = f"{e.start:%H:%M}-{e.end:%H:%M}"
            lines.append(f"• {time_range}")
            lines.append(f"— <b>{e.summary}</b>")
        return "\n".join(lines)


# Глобальный экземпляр
schedule_service = ScheduleService()
