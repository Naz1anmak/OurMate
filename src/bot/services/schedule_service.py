"""
Сервис работы с расписанием (ICS -> события).
Парсит все файлы по паттерну, кеширует и предоставляет пары на сегодня/завтра.
"""
import html
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from src.config.settings import (
    SCHEDULE_GROUPS_DIR,
    SCHEDULE_GROUP_NAME_PREFIX,
    SCHEDULE_CACHE_FILE,
    TIMEZONE,
    RUZ_GROUP_IDS,
)
from src.core.emoji import E

logger = logging.getLogger(__name__)

NO_PAIRS_TEMPLATES = [
    f"{E.NO_CLASS_BOOKS} Пар {{day}} нет, отдыхайте родные!",
    f"{E.NO_CLASS_SPARKLES} Пар {{day}} нет, удачного вам дня!",
    f"{E.NO_CLASS_SLEEP} Пар {{day}} нет, ловите передышку!",
    f"{E.NO_CLASS_HEART} Пар {{day}} нет, но я всегда рядом!",
    f"{E.NO_CLASS_PARTY} Пар {{day}} нет, самое время выспаться!",
    f"{E.NO_CLASS_CLOCK} Пар {{day}} нет, используйте время с пользой!",
    f"{E.NO_CLASS_SUN} Пар {{day}} нет, наслаждайтесь свободным днем!",
    f"{E.NO_CLASS_PHONE} Пар {{day}} нет, но я всегда на связи, родные!",
    f"{E.NO_CLASS_BOOK} Пар {{day}} нет, но можно повторить материал!",
    f"{E.NO_CLASS_CALENDAR} Пар {{day}} нет, планируйте свой день как хотите!",
    f"{E.NO_CLASS_GAME} Пар {{day}} нет, самое время заняться своими делами!",
    f"{E.NO_CLASS_BOOKS} Пар {{day}} нет, но я бы на вашем месте все равно поучился!",
]

@dataclass
class ScheduleEvent:
    summary: str
    location: str
    start: datetime
    end: datetime
    groups: frozenset[str] = field(default_factory=lambda: frozenset({""}))
    kind: str = ""

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
        """Загружает события из data/<code>/schedule.json для каждой подпапки группы."""
        base = Path(SCHEDULE_GROUPS_DIR)
        codes = self._detect_group_codes(base)
        self.known_groups = frozenset(codes) if codes else frozenset({""})

        raw_events: List[ScheduleEvent] = []
        for code in codes:
            events = self._read_schedule_json(base / code / "schedule.json", code)
            raw_events.extend(events)

        merged = self._merge_duplicates(raw_events)
        merged.sort(key=lambda e: e.start)
        logger.info("Расписание загружено: %s событий из %s групп", len(merged), len(codes))
        return merged

    @staticmethod
    def _read_schedule_json(path: Path, code: str) -> List[ScheduleEvent]:
        """Читает schedule.json для одной группы. При отсутствии/ошибке — [].

        Локальная десериализация (не через ruz_parser.load_schedule), чтобы не зависеть
        от ruz_parser: ruz_parser импортирует ScheduleEvent отсюда → циклический импорт
        ломает загрузку модуля при первой инициализации.
        """
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            events: List[ScheduleEvent] = []
            for item in raw.get("events", []):
                events.append(ScheduleEvent(
                    summary=item["summary"],
                    location=item.get("location", ""),
                    start=datetime.fromisoformat(item["start"]),
                    end=datetime.fromisoformat(item["end"]),
                    kind=item.get("kind", ""),
                    groups=frozenset({code}),
                ))
            return events
        except Exception:
            logger.warning("schedule.json %s повреждён или нечитаем", path)
            return []

    @staticmethod
    def _detect_group_codes(base: Path) -> List[str]:
        """Подпапки data/, отвечающие группам. При непустом RUZ_GROUP_IDS — только из whitelist
        (чтобы сёстры-папки вроде data/logs/ не считались за группу)."""
        if not base.is_dir():
            return []
        candidates = sorted(
            entry.name for entry in base.iterdir()
            if entry.is_dir() and not entry.name.startswith(".") and entry.name != "cache"
        )
        if RUZ_GROUP_IDS:
            return [c for c in candidates if c in RUZ_GROUP_IDS]
        return candidates

    def reload(self) -> None:
        """Пересоздаёт events из schedule.json без рестарта."""
        self.events = self._load_events()
        self._save_cache()

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

    def get_effective_date_with_titles(self, timezone: ZoneInfo) -> Tuple[date, str, str]:
        """Актуальная дата + day_label ('сегодня'/'завтра') + заголовок ('Пары на …').

        Единая точка вычисления для рассылки, закрепа и команды «пары»:
        после последней пары катимся на завтра (см. get_effective_date).
        """
        effective_date = self.get_effective_date(timezone)
        today = datetime.now(timezone).date()
        day_label = "завтра" if effective_date == date.fromordinal(today.toordinal() + 1) else "сегодня"
        base_title = "Пары на завтра" if day_label == "завтра" else "Пары на сегодня"
        return effective_date, day_label, base_title

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

    def _events_by_group_for_date(self, target_date: date) -> Dict[str, List[ScheduleEvent]]:
        """Для каждой известной группы — её события на эту дату.

        Для single-group возвращает {"": [...]}.
        """
        day_events = self._events_for_date(target_date)
        result: Dict[str, List[ScheduleEvent]] = {code: [] for code in self.known_groups}
        for ev in day_events:
            for code in ev.groups:
                if code in result:
                    result[code].append(ev)
        for code in result:
            result[code].sort(key=lambda e: e.start)
        return result

    def _day_is_common(self, by_group: Dict[str, List[ScheduleEvent]]) -> bool:
        """True, если у всех групп множества (start, end, summary, location) совпадают."""
        if len(by_group) <= 1:
            return True
        iterator = iter(by_group.values())
        first_keys = {ev.key() for ev in next(iterator)}
        for events in iterator:
            if {ev.key() for ev in events} != first_keys:
                return False
        return True

    def format_day_block(
        self,
        target_date: date,
        base_title: str,
        *,
        icon_common: str = str(E.PIN),
        empty_text: str = "",
    ) -> str:
        """Рендерит блок дня для multi-group / single-group.

        - День общий → один блок: f"<b>{icon_common} {base_title}:</b>" + blockquote с парами.
        - День различается → по одному блоку на группу:
          f"<b>❗️ {base_title} для {display_name}:</b>" + blockquote.
        - Если у группы пар нет — внутри blockquote строка "Пар нет".
        - Если у всей единственной группы пар нет и empty_text задан — возвращает empty_text.
        """
        by_group = self._events_by_group_for_date(target_date)
        all_empty = all(not evs for evs in by_group.values())

        # Single-group: если пусто и есть empty_text — отдаём его (back-compat поведения).
        if self.known_groups == frozenset({""}) and all_empty:
            return empty_text

        if self._day_is_common(by_group):
            events = next(iter(by_group.values())) if by_group else []
            if not events and empty_text:
                return empty_text
            return self._render_single_block(
                f"{icon_common} {base_title}",
                events,
                empty_fallback=empty_text or "Пар нет",
            )

        # Different day → per-group blocks
        blocks: list[str] = []
        for code in sorted(by_group.keys()):
            events = by_group[code]
            display = self.group_display_name(code)
            title = f"{E.ALERT} {base_title} для {display}"
            blocks.append(self._render_single_block(title, events, empty_fallback="Пар нет"))
        return "\n\n".join(blocks)

    @staticmethod
    def _render_single_block(
        title: str,
        events: List[ScheduleEvent],
        *,
        empty_fallback: str = "",
    ) -> str:
        """Один заголовок + blockquote со списком пар (или empty_fallback внутри blockquote)."""
        header = f"<b>{title}:</b>"
        if not events:
            inner = empty_fallback or ""
            if not inner:
                return header
            return f"{header}\n<blockquote>{inner}</blockquote>"
        blocks: list[str] = []
        for e in events:
            time_range = f"{e.start:%H:%M}–{e.end:%H:%M}"
            head = f"{time_range} · {e.kind}" if e.kind else time_range
            blocks.append(f"{head}\n<b>{html.escape(e.summary)}</b>")
        inner = "\n\n".join(blocks)
        return f"{header}\n<blockquote>{inner}</blockquote>"

    def format_next_classes_block(self, day: date, base_date: date | None = None) -> str:
        """Блок «следующие пары» — общий или per-group по логике format_day_block."""
        if base_date and day == date.fromordinal(base_date.toordinal() + 1):
            base_title = "Пары завтра"
        else:
            day_phrase = self.weekday_with_preposition(day)
            base_title = f"Следующие пары {day_phrase} ({day.strftime('%d.%m')})"
        return self.format_day_block(day, base_title)

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
