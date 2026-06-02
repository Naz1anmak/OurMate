"""Координатор обновления расписания через API: TTL, lock, diff."""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.bot.services.schedule_client import ScheduleClient, ScheduleError
from src.bot.services.schedule_parser import load_schedule, parse_lessons, save_schedule
from src.bot.services.schedule_diff import compute_diff, render
from src.bot.services.schedule_service import ScheduleEvent, ScheduleService
from src.config.settings import TIMEZONE

logger = logging.getLogger(__name__)


@dataclass
class RefreshResult:
    updated_groups: list[str] = field(default_factory=list)
    skipped_groups: list[str] = field(default_factory=list)
    failed_groups: list[str] = field(default_factory=list)
    diff_message: str | None = None
    last_fetched_at: dict[str, datetime] = field(default_factory=dict)


class ScheduleRefresher:
    def __init__(
        self,
        *,
        client: ScheduleClient,
        schedule_service: ScheduleService,
        group_ids: dict[str, int],
        weeks_ahead: int,
        lazy_ttl_min: int,
    ):
        self.client = client
        self.schedule_service = schedule_service
        self.group_ids = group_ids
        self.weeks_ahead = weeks_ahead
        self.lazy_ttl = timedelta(minutes=lazy_ttl_min)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, code: str) -> asyncio.Lock:
        if code not in self._locks:
            self._locks[code] = asyncio.Lock()
        return self._locks[code]

    def _all_codes(self) -> list[str]:
        """Список кодов групп для обновления = ключи self.group_ids (env-конфиг).

        Источник правды — env, а не `data/`.iterdir(): на чистой установке подпапки
        `data/<CODE>/` ещё не существуют, и iterdir вернул бы пустой список →
        refresh никогда бы не позвал save_schedule → папка не создалась бы → dead-lock.
        save_schedule сам делает mkdir(parents=True, exist_ok=True) при первом успехе.
        """
        return sorted(self.group_ids.keys())

    async def ensure_fresh(self, reason: str) -> RefreshResult:
        now = datetime.now(TIMEZONE)
        codes = self._all_codes()
        stale: list[str] = []
        for code in codes:
            fetched, _ = load_schedule(code)
            if fetched is None or now - fetched > self.lazy_ttl:
                stale.append(code)
        if not stale:
            logger.info("ensure_fresh(%s): все группы свежее TTL, skip", reason)
            return RefreshResult(skipped_groups=codes)
        return await self._run(reason, only_codes=stale)

    async def force_refresh(self, reason: str) -> RefreshResult:
        return await self._run(reason, only_codes=None)

    async def _run(self, reason: str, only_codes: list[str] | None) -> RefreshResult:
        codes = only_codes if only_codes is not None else self._all_codes()
        logger.info("refresh(%s): группы %s", reason, codes)

        result = RefreshResult()
        per_group_old: dict[str, list[ScheduleEvent]] = {}
        per_group_new: dict[str, list[ScheduleEvent]] = {}
        first_loads: set[str] = set()

        async def _process(code: str):
            async with self._lock_for(code):
                old_fetched, old_events = load_schedule(code)
                if old_fetched is None:
                    first_loads.add(code)
                per_group_old[code] = old_events

                today = datetime.now(TIMEZONE).date()
                monday = today - timedelta(days=today.weekday())
                weeks = [monday + timedelta(days=7 * i) for i in range(self.weeks_ahead + 1)]

                new_events: list[ScheduleEvent] = []
                errors = 0
                for w in weeks:
                    try:
                        raw = await self.client.fetch_week(self.group_ids[code], w)
                        new_events.extend(parse_lessons(raw))
                    except ScheduleError as exc:
                        errors += 1
                        logger.warning("refresh %s неделя %s упала: %s", code, w, exc)

                if errors >= len(weeks):
                    result.failed_groups.append(code)
                    per_group_new[code] = old_events
                    return

                save_schedule(code, new_events, fetched_at=datetime.now(TIMEZONE))
                per_group_new[code] = new_events
                result.updated_groups.append(code)
                result.last_fetched_at[code] = datetime.now(TIMEZONE)

        await asyncio.gather(*(_process(c) for c in codes))

        # reload в сервисе только если что-то реально обновили
        if result.updated_groups:
            self.schedule_service.reload()

        # diff: для групп, которые НЕ были first-load
        diffable_old: dict[str, list[ScheduleEvent]] = {}
        diffable_new: dict[str, list[ScheduleEvent]] = {}
        for code in result.updated_groups:
            if code in first_loads:
                continue
            diffable_old[code] = per_group_old[code]
            diffable_new[code] = per_group_new[code]

        if diffable_new:
            today = datetime.now(TIMEZONE).date()
            summary = compute_diff(diffable_old, diffable_new, from_date=today)
            result.diff_message = render(
                summary,
                known_groups=self.schedule_service.known_groups,
            )

        return result
