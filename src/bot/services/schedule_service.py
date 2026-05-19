"""
Сервис работы с расписанием (ICS -> события).
Парсит все файлы по паттерну, кеширует и предоставляет пары на сегодня/завтра.
"""
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, date, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from icalendar import Calendar

from src.config.settings import (
    SCHEDULE_FILES_PATTERN,
    SCHEDULE_GROUPS_DIR,
    SCHEDULE_GROUP_NAME_PREFIX,
    SCHEDULE_CACHE_FILE,
    TIMEZONE,
)

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
    "📖 Пар {day} нет, но можно повторить материал!",
    "🗓️ Пар {day} нет, планируйте свой день как хотите!",
    "🎮 Пар {day} нет, самое время заняться своими делами!",
    "📚 Пар {day} нет, но я бы на вашем месте все равно поучился!",
]

@dataclass
class ScheduleEvent:
    summary: str
    location: str
    start: datetime
    end: datetime
    groups: frozenset[str] = field(default_factory=lambda: frozenset({""}))

    def key(self) -> tuple:
        """Ключ идентичности для мёрджа дубликатов."""
        return (self.start, self.end, self.summary, self.location)

class ScheduleService:
    def __init__(self, timezone: ZoneInfo = TIMEZONE):
        self.timezone = timezone
        self.known_groups: frozenset[str] = frozenset({""})
        self.events: List[ScheduleEvent] = self._load_events()
        self._save_cache()

    def group_display_name(self, code: str) -> str:
        """Возвращает отображаемое имя группы по коду."""
        if not code:
            return ""
        return f"{SCHEDULE_GROUP_NAME_PREFIX}{code}"

    def _load_events(self) -> List[ScheduleEvent]:
        """Загружает события из multi-group подпапок или single-group fallback."""
        base = Path(SCHEDULE_GROUPS_DIR)
        group_codes = self._detect_group_codes(base)

        raw_events: List[ScheduleEvent] = []
        if group_codes:
            self.known_groups = frozenset(group_codes)
            self._warn_about_loose_files(base)
            for code in group_codes:
                raw_events.extend(self._load_group_events(base / code, code))
            logger.info(
                "Расписание: multi-group режим, группы: %s",
                ", ".join(sorted(group_codes)),
            )
        else:
            self.known_groups = frozenset({""})
            raw_events.extend(self._load_single_group_events())
            logger.info("Расписание: single-group режим (fallback)")

        merged = self._merge_duplicates(raw_events)
        merged.sort(key=lambda e: e.start)
        logger.info("Расписание загружено: %s событий", len(merged))
        return merged

    @staticmethod
    def _detect_group_codes(base: Path) -> List[str]:
        """Возвращает имена подпапок base, содержащих файлы calendar*.ics."""
        if not base.is_dir():
            return []
        codes: List[str] = []
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            if any(entry.glob("calendar*.ics")):
                codes.append(entry.name)
        return codes

    @staticmethod
    def _warn_about_loose_files(base: Path) -> None:
        """Логирует warning, если рядом с подпапками лежат свободные calendar*.ics."""
        loose = list(base.glob("calendar*.ics"))
        if loose:
            logger.warning(
                "Multi-group режим активен, но в %s найдены свободные файлы %s — "
                "они игнорируются. Переложите их в подпапку группы.",
                base, [p.name for p in loose],
            )

    def _load_group_events(self, group_dir: Path, code: str) -> List[ScheduleEvent]:
        """Парсит все calendar*.ics в подпапке группы, тегируя события её кодом."""
        events: List[ScheduleEvent] = []
        for ics_path in sorted(group_dir.glob("calendar*.ics")):
            try:
                parsed = self._parse_ics(ics_path)
                for ev in parsed:
                    ev.groups = frozenset({code})
                events.extend(parsed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не удалось разобрать %s: %s", ics_path, exc)
        return events

    def _load_single_group_events(self) -> List[ScheduleEvent]:
        """Single-group fallback: парсит по SCHEDULE_FILES_PATTERN, без тегов группы."""
        events: List[ScheduleEvent] = []
        pattern_path = Path(SCHEDULE_FILES_PATTERN)
        base_dir = pattern_path.parent if pattern_path.parent != Path('.') else Path.cwd()
        glob_pattern = pattern_path.name
        matched = sorted(base_dir.glob(glob_pattern))
        if not matched:
            logger.warning("Файлы расписания не найдены по шаблону '%s'", SCHEDULE_FILES_PATTERN)
        for ics_path in matched:
            try:
                events.extend(self._parse_ics(ics_path))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не удалось разобрать %s: %s", ics_path, exc)
        return events

    @staticmethod
    def _merge_duplicates(events: List[ScheduleEvent]) -> List[ScheduleEvent]:
        """Идентичные (start, end, summary, location) сливаются в одно с union(groups)."""
        buckets: Dict[tuple, ScheduleEvent] = {}
        for ev in events:
            k = ev.key()
            existing = buckets.get(k)
            if existing is None:
                buckets[k] = ev
            else:
                existing.groups = existing.groups | ev.groups
        return list(buckets.values())

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
        """Сохраняет события в JSON-кеш (для отладки и быстрого холодного старта)."""
        try:
            SCHEDULE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            serializable = [
                {
                    "summary": e.summary,
                    "location": e.location,
                    "start": e.start.isoformat(),
                    "end": e.end.isoformat(),
                    "groups": sorted(e.groups),
                }
                for e in self.events
            ]
            SCHEDULE_CACHE_FILE.write_text(
                json.dumps(serializable, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Кеш обновлён: %s событий → %s", len(self.events), SCHEDULE_CACHE_FILE)
        except Exception:
            # Кеш некритичен
            pass

    def _events_for_date(self, target_date: date) -> List[ScheduleEvent]:
        return [e for e in self.events if e.start.date() == target_date]

    def get_classes_for_date(self, target_date: date) -> List[ScheduleEvent]:
        return self._events_for_date(target_date)

    def get_todays_classes(self, timezone: ZoneInfo) -> List[ScheduleEvent]:
        today = datetime.now(timezone).date()
        return self._events_for_date(today)

    def get_effective_date(self, timezone: ZoneInfo) -> date:
        """Возвращает 'актуальную' дату: после последней пары переключаемся на завтра."""
        now = datetime.now(timezone)
        today = now.date()
        events = self._events_for_date(today)
        if not events:
            return today
        last_end = max(e.end for e in events)
        if now >= last_end:
            return date.fromordinal(today.toordinal() + 1)
        return today

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

        event_lines: List[str] = []
        for e in events:
            time_range = f"{e.start:%H:%M}-{e.end:%H:%M}"
            event_lines.append(f"• {time_range}")
            event_lines.append(f"— <b>{e.summary}</b>")

        if wrap_quote:
            list_block = "\n".join(event_lines)
            return "\n".join([title, f"<blockquote>{list_block}</blockquote>"])

        lines = [title, "", *event_lines]
        return "\n".join(lines)

    def format_next_classes_block(self, day: date, events: List[ScheduleEvent], base_date: date | None = None) -> str:
        """Формирует блок о ближайших будущих парах."""
        if base_date and day == date.fromordinal(base_date.toordinal() + 1):
            title = "<b>📌 Пары завтра:</b>"
        else:
            day_phrase = self.weekday_with_preposition(day)
            title = f"<b>📌 Следующие пары {day_phrase} ({day.strftime('%d.%m')}):</b>"
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
