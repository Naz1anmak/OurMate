"""
Планировщик обновления закреплённого сообщения с расписанием.
"""
import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config.settings import (
    CHAT_ID,
    TIMEZONE,
    PINNED_SCHEDULE_ENABLED,
    PINNED_SCHEDULE_UPDATE_HOUR,
    PINNED_SCHEDULE_UPDATE_MINUTE,
    PINNED_SCHEDULE_MESSAGE_FILE,
    PINNED_SCHEDULE_DAYS_AHEAD,
)
from src.bot.services.schedule_service import schedule_service, ScheduleEvent
from src.core.emoji import E

logger = logging.getLogger(__name__)


class PinnedScheduleScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.refresher = None  # инжектится в setup.py
        self.scheduler = AsyncIOScheduler(
            timezone=TIMEZONE,
            job_defaults={
                "misfire_grace_time": 300,
                "coalesce": True,
            },
        )

    def start(self):
        if not PINNED_SCHEDULE_ENABLED:
            logger.info("Закреп расписания: отключено в конфиге")
            return

        self.scheduler.add_job(
            self._cron_job,
            CronTrigger(
                hour=PINNED_SCHEDULE_UPDATE_HOUR,
                minute=PINNED_SCHEDULE_UPDATE_MINUTE,
                timezone=TIMEZONE,
            ),
        )
        self.scheduler.start()
        asyncio.create_task(self._cron_job())  # сразу первый прогон
        logger.info("Закреп расписания: задача запланирована, сразу обновляем")

    async def _cron_job(self):
        if self.refresher is not None:
            try:
                result = await self.refresher.force_refresh("cron:pinned")
                if result.diff_message:
                    await self.bot.send_message(
                        CHAT_ID, result.diff_message,
                        parse_mode="HTML", disable_web_page_preview=True,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("cron:pinned refresh упал: %s", exc)
        await self._update_pinned_message()

    async def update_now(self):
        """Публичная обёртка: рендер закрепа БЕЗ refresh."""
        await self._update_pinned_message()

    async def _update_pinned_message(self):
        text = _build_pinned_text()

        pinned_id = _load_pinned_id(PINNED_SCHEDULE_MESSAGE_FILE)

        if text is None:
            # Нет будущих пар — удаляем сообщение, если было
            if pinned_id is not None:
                try:
                    await self.bot.delete_message(CHAT_ID, pinned_id)
                    logger.info("Закреп расписания удалён (нет будущих пар)")
                except Exception as exc:
                    logger.warning("Не удалось удалить закреп расписания: %s", exc)
                _clear_pinned_id(PINNED_SCHEDULE_MESSAGE_FILE)
            return

        if pinned_id is None:
            await self._send_and_pin(text)
            return

        try:
            await self.bot.edit_message_text(
                text,
                chat_id=CHAT_ID,
                message_id=pinned_id,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            logger.info("Закреп расписания обновлён")
        except TelegramForbiddenError:
            logger.warning("Нет прав на редактирование закрепа; пробуем отправить заново")
            await self._send_and_pin(text)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                logger.info("Закреп расписания: текст не изменился, пропускаем")
                return
            logger.warning("Не удалось отредактировать закреп расписания: %s; отправляем заново", exc)
            await self._send_and_pin(text)
        except Exception as exc:
            logger.warning("Не удалось отредактировать закреп расписания: %s; отправляем заново", exc)
            await self._send_and_pin(text)

    async def _send_and_pin(self, text: str):
        try:
            msg = await self.bot.send_message(
                CHAT_ID,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            try:
                await self.bot.pin_chat_message(CHAT_ID, msg.message_id)
            except Exception as exc:
                logger.warning("Не удалось закрепить сообщение с расписанием: %s", exc)
            _save_pinned_id(PINNED_SCHEDULE_MESSAGE_FILE, msg.message_id)
            logger.info("Закреп расписания отправлен и закреплён")
        except Exception as exc:
            logger.warning("Не удалось отправить закреп с расписанием: %s", exc)

    def stop(self):
        self.scheduler.shutdown()

def start_pinned_schedule_scheduler(bot: Bot):
    scheduler = PinnedScheduleScheduler(bot)
    scheduler.start()
    return scheduler

def _build_pinned_text() -> Optional[str]:
    """Формирует текст закреплённого сообщения. None => удалить закреп."""
    effective_date, day_label, base_title_today = schedule_service.get_effective_date_with_titles(TIMEZONE)
    today_events = schedule_service.get_classes_for_date(effective_date)
    lines: list[str] = []
    used_next_date: Optional[date] = None

    # Блок «Сегодня/Завтра»
    if today_events:
        lines.append(schedule_service.format_day_block(effective_date, base_title_today, icon_common=str(E.NO_CLASS_BOOKS)))
    else:
        base_empty = schedule_service.get_no_pairs_message(day_label)
        next_date, next_events = schedule_service.get_next_classes_after(effective_date)
        if next_date and next_events:
            next_block = schedule_service.format_next_classes_block(next_date, base_date=effective_date)
            used_next_date = next_date
            lines.append(f"{base_empty}\n\n{next_block}")
        else:
            return None

    # Следующие учебные дни, ограниченные PINNED_SCHEDULE_DAYS_AHEAD
    grouped = _group_events_from(effective_date, limit=PINNED_SCHEDULE_DAYS_AHEAD)
    for idx, (day, _events) in enumerate(grouped):
        if idx == 0 and today_events:
            continue  # уже вывели блок сегодня
        if used_next_date and day == used_next_date:
            continue  # уже показали в блоке «Следующие пары»
        lines.append("")
        lines.append(_format_day_block(day))

    return "\n".join([line for line in lines if line is not None])

def _group_events_from(start_date: date, *, limit: int) -> list[tuple[date, list[ScheduleEvent]]]:
    """Первые `limit` уникальных дат с событиями, начиная с start_date."""
    seen: list[date] = []
    for ev in schedule_service.events:
        d = ev.start.date()
        if d < start_date:
            continue
        if d not in seen:
            seen.append(d)
            if len(seen) >= limit:
                break
    return [(d, [e for e in schedule_service.events if e.start.date() == d]) for d in seen]

def _format_day_block(day: date) -> str:
    """Заголовок «Во вторник (DD.MM)» + блок(и) пар через сервис."""
    day_title = schedule_service.weekday_with_preposition(day).capitalize()
    base_title = f"{day_title} ({day.strftime('%d.%m')})"
    return schedule_service.format_day_block(day, base_title)

def _load_pinned_id(path: Path) -> Optional[int]:
    try:
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except Exception:
        return None

def _save_pinned_id(path: Path, message_id: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(message_id), encoding="utf-8")
    except Exception:
        pass

def _clear_pinned_id(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass
