"""Сравнение старого и нового снапшотов расписания."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from src.bot.services.schedule_service import ScheduleEvent


_WEEKDAYS = ["в понедельник", "во вторник", "в среду", "в четверг", "в пятницу", "в субботу", "в воскресенье"]


@dataclass
class DayDiff:
    date: date
    group_code: str
    added: list[ScheduleEvent] = field(default_factory=list)
    removed: list[ScheduleEvent] = field(default_factory=list)
    changed: list[tuple[ScheduleEvent, ScheduleEvent]] = field(default_factory=list)
    old_keys: frozenset = field(default_factory=frozenset)
    new_keys: frozenset = field(default_factory=frozenset)

    def is_empty(self) -> bool:
        return not self.added and not self.removed and not self.changed


@dataclass
class DiffSummary:
    is_appearance: bool = False
    days: list[DayDiff] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.is_appearance and not self.days


def compute_diff(
    per_group_old: dict[str, list[ScheduleEvent]],
    per_group_new: dict[str, list[ScheduleEvent]],
    *,
    from_date: date,
) -> DiffSummary:
    """Сравнивает старые и новые события per группа, только для дат >= from_date."""
    appearance_flags: list[bool] = []
    for code in per_group_new:
        old_future = [e for e in per_group_old.get(code, []) if e.start.date() >= from_date]
        new_future = [e for e in per_group_new.get(code, []) if e.start.date() >= from_date]
        appearance_flags.append(len(old_future) == 0 and len(new_future) > 0)
    is_appearance = bool(appearance_flags) and all(appearance_flags)

    if is_appearance:
        return DiffSummary(is_appearance=True, days=[])

    days: list[DayDiff] = []
    for code in per_group_new:
        old_future = [e for e in per_group_old.get(code, []) if e.start.date() >= from_date]
        new_future = [e for e in per_group_new.get(code, []) if e.start.date() >= from_date]

        old_keys = {e.key(): e for e in old_future}
        new_keys = {e.key(): e for e in new_future}

        added = [e for k, e in new_keys.items() if k not in old_keys]
        removed = [e for k, e in old_keys.items() if k not in new_keys]

        # changed — same (date, summary), but key differs
        changed: list[tuple[ScheduleEvent, ScheduleEvent]] = []
        added_remaining: list[ScheduleEvent] = []
        for e in added:
            match = next(
                (old_e for old_e in removed
                 if old_e.start.date() == e.start.date() and old_e.summary == e.summary),
                None,
            )
            if match:
                changed.append((match, e))
                removed.remove(match)
            else:
                added_remaining.append(e)

        # group by date
        by_date: dict[date, DayDiff] = {}
        for e in added_remaining:
            d = e.start.date()
            by_date.setdefault(d, DayDiff(date=d, group_code=code)).added.append(e)
        for e in removed:
            d = e.start.date()
            by_date.setdefault(d, DayDiff(date=d, group_code=code)).removed.append(e)
        for before, after in changed:
            d = after.start.date()
            by_date.setdefault(d, DayDiff(date=d, group_code=code)).changed.append((before, after))

        # обогащаем old_keys/new_keys per дата — для кластеризации в render
        for d, day_diff in by_date.items():
            day_diff.old_keys = frozenset(
                e.key() for e in old_future if e.start.date() == d
            )
            day_diff.new_keys = frozenset(
                e.key() for e in new_future if e.start.date() == d
            )

        days.extend(sorted(by_date.values(), key=lambda x: x.date))

    return DiffSummary(is_appearance=False, days=days)


def _is_time_only_change(before: ScheduleEvent, after: ScheduleEvent) -> bool:
    """True, если у пары изменилось только время (start/end), а место и тип те же."""
    return (
        before.location == after.location
        and before.kind == after.kind
        and (before.start, before.end) != (after.start, after.end)
    )


def _format_groups(codes: list[str]) -> str:
    """Форматирует список кодов групп: '40001' / '40001 и 40002' / '40001, 40002 и 40003'."""
    ordered = sorted(codes)
    if len(ordered) == 1:
        return ordered[0]
    if len(ordered) == 2:
        return f"{ordered[0]} и {ordered[1]}"
    return f"{', '.join(ordered[:-1])} и {ordered[-1]}"


def render(summary: DiffSummary, *, known_groups: frozenset[str]) -> str | None:
    """Формирует HTML-сообщение из DiffSummary для отправки в Telegram.

    Кластеризует DayDiff по (date, old_keys, new_keys): если у нескольких групп
    в этот день полностью совпадает состояние до и после — рендерим один блок
    на кластер. Суффикс 'для …' опускается, когда кластер покрывает все
    known_groups (одна группа в системе → тоже без суффикса).
    """
    if summary.is_empty():
        return None
    if summary.is_appearance:
        return "🗓️ Появилось расписание!"

    # Кластеризуем DayDiff по (date, old_keys, new_keys)
    clusters: dict[tuple[date, frozenset, frozenset], list[DayDiff]] = defaultdict(list)
    for d in summary.days:
        clusters[(d.date, d.old_keys, d.new_keys)].append(d)

    # Сортируем кластеры по дате, потом по отсортированному списку кодов
    sorted_keys = sorted(
        clusters.keys(),
        key=lambda k: (k[0], sorted(d.group_code for d in clusters[k])),
    )

    lines: list[str] = ["🗓️ Расписание обновилось", ""]
    for cluster_key in sorted_keys:
        cluster_date = cluster_key[0]
        diffs = clusters[cluster_key]
        codes = sorted({d.group_code for d in diffs})
        weekday = _WEEKDAYS[cluster_date.weekday()].capitalize()

        # Суффикс «для …» только если кластер не покрывает все known_groups.
        if known_groups and set(codes) == set(known_groups):
            suffix = ""
        else:
            suffix = f" для {_format_groups(codes)}"

        lines.append(f"<b>{weekday} ({cluster_date:%d.%m}){suffix}:</b>")

        # Внутри кластера дифы идентичны → берём первый
        rep = diffs[0]
        pair_blocks: list[str] = []
        for e in rep.added:
            pair_blocks.append(_format_event_line("✅", e))
        for e in rep.removed:
            pair_blocks.append(_format_event_line("❌", e))
        for before, after in rep.changed:
            emoji = "⏰" if _is_time_only_change(before, after) else "✏️"
            pair_blocks.append(_format_change_line(emoji, before, after))

        inner = "\n\n".join(pair_blocks)
        lines.append(f"<blockquote>{inner}</blockquote>")
        lines.append("")  # пустая строка между блоками дней

    return "\n".join(lines).rstrip()


def _format_event_line(emoji: str, e: ScheduleEvent) -> str:
    """'✅ HH:MM–HH:MM · Тип\\n<b>Предмет</b>' (или без '· Тип', если kind пуст)."""
    time_range = f"{e.start:%H:%M}–{e.end:%H:%M}"
    head = f"{emoji} {time_range} · {e.kind}" if e.kind else f"{emoji} {time_range}"
    return f"{head}\n<b>{e.summary}</b>"


def _format_change_line(emoji: str, before: ScheduleEvent, after: ScheduleEvent) -> str:
    """'⏰ HH:MM–HH:MM → HH:MM–HH:MM · Тип\\n<b>Предмет</b>'."""
    times = f"{before.start:%H:%M}–{before.end:%H:%M} → {after.start:%H:%M}–{after.end:%H:%M}"
    head = f"{emoji} {times} · {after.kind}" if after.kind else f"{emoji} {times}"
    return f"{head}\n<b>{after.summary}</b>"
