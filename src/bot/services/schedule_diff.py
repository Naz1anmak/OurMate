"""Сравнение старого и нового снапшотов расписания."""
from dataclasses import dataclass, field
from datetime import date

from src.bot.services.schedule_service import ScheduleEvent


@dataclass
class DayDiff:
    date: date
    group_code: str
    added: list[ScheduleEvent] = field(default_factory=list)
    removed: list[ScheduleEvent] = field(default_factory=list)
    changed: list[tuple[ScheduleEvent, ScheduleEvent]] = field(default_factory=list)

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

        days.extend(sorted(by_date.values(), key=lambda x: x.date))

    return DiffSummary(is_appearance=False, days=days)
