"""
Сервис работы с расписанием (ICS -> события).
Парсит все файлы по паттерну, кеширует и предоставляет пары на сегодня/завтра.
"""
import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, date, time
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from icalendar import Calendar

from src.config.settings import SCHEDULE_FILES_PATTERN, SCHEDULE_CACHE_FILE, TIMEZONE

logger = logging.getLogger(__name__)

NO_PAIRS_TEMPLATES = [
    "📚 Пар {day} нет, отдыхайте родные!",
    "✨ Пар {day} нет, удачного вам дня!",
    "💤 Пар {day} нет, ловите передышку!",
    "💚 Пар {day} нет, но я всегда рядом!",
    "🥳 Пар {day} нет, самое время выспаться!",
    "🕒 Пар {day} нет, используйте время с пользой!",
    "☀️ Пар {day} нет, наслаждайтесь свободным днем!",
    "📞 Пар {day} нет, но я всегда на связи, родные!",
    "📖 Пар {day} нет, но можно повторить материал 😉",
    "🗓️ Пар {day} нет, планируйте свой день как хотите!",
    "🛠️ Пар {day} нет, самое время заняться своими делами!",
    "📚 Пар {day} нет, но я бы на вашем месте все равно поучился!",
]

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

        matched_files = sorted(base_dir.glob(glob_pattern))
        if not matched_files:
            logger.warning("Файлы расписания не найдены по шаблону '%s'", SCHEDULE_FILES_PATTERN)

        for ics_path in matched_files:
            try:
                events.extend(self._parse_ics(ics_path))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не удалось разобрать файл расписания %s: %s", ics_path, exc)
                continue

        # Сортируем по времени начала
        events.sort(key=lambda e: e.start)
        logger.info("Расписание загружено: %s событий из %s файлов", len(events), len(matched_files))
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
            logger.info("Кеш обновлен: %s событий -> %s", len(self.events), SCHEDULE_CACHE_FILE)
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

    def get_next_classes_after(self, base_date: date) -> Tuple[Optional[date], List[ScheduleEvent]]:
        """
        Возвращает дату и список ближайших будущих пар после указанной даты.

        Args:
            base_date (date): Дата, после которой ищем ближайшие пары.

        Returns:
            Tuple[Optional[date], List[ScheduleEvent]]: (дата ближайших пар, список событий) или (None, [])
        """
        next_date = None
        for event in self.events:
            event_date = event.start.date()
            if event_date > base_date:
                next_date = event_date
                break

        if next_date is None:
            return None, []

        next_events = [e for e in self.events if e.start.date() == next_date]
        return next_date, next_events

    def format_classes(
        self,
        events: List[ScheduleEvent],
        title: str,
        empty_text: str,
        wrap_quote: bool = False,
    ) -> str:
        if not events:
            return empty_text

        event_lines: list[str] = []
        for e in events:
            time_range = f"{e.start:%H:%M}-{e.end:%H:%M}"
            event_lines.append(f"• {time_range}")
            event_lines.append(f"— <b>{e.summary}</b>")

        if wrap_quote:
            list_block = "\n".join(event_lines)
            return "\n".join([title, f"<blockquote>{list_block}</blockquote>"])

        lines = [title, "", *event_lines]
        return "\n".join(lines)

    def format_next_classes_block(self, day: date, events: List[ScheduleEvent]) -> str:
        """Формирует блок о ближайших будущих парах."""
        day_phrase = self.weekday_with_preposition(day)
        title = f"<b>📌 Следующие пары {day_phrase}:</b>"
        return self.format_classes(events, title, "", wrap_quote=True)

    def get_no_pairs_message(self, day_label: str) -> str:
        """Возвращает случайное сообщение об отсутствии пар на указанную дату."""
        template = random.choice(NO_PAIRS_TEMPLATES)
        return template.format(day=day_label)

    @staticmethod
    def weekday_with_preposition(day: date) -> str:
        """Возвращает фразу вида 'в понедельник', 'во вторник', ..."""
        mapping = {
            0: "в понедельник",
            1: "во вторник",
            2: "в среду",
            3: "в четверг",
            4: "в пятницу",
            5: "в субботу",
            6: "в воскресенье",
        }
        return mapping.get(day.weekday(), "в ближайший день")

# Глобальный экземпляр
schedule_service = ScheduleService()
