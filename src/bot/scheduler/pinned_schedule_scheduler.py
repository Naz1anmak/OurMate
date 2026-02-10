"""
Планировщик обновления закреплённого сообщения с расписанием.
"""
import asyncio
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config.settings import (
    CHAT_ID,
    TIMEZONE,
    PINNED_SCHEDULE_ENABLED,
    PINNED_SCHEDULE_UPDATE_HOUR,
    PINNED_SCHEDULE_UPDATE_MINUTE,
    PINNED_SCHEDULE_MESSAGE_FILE,
)
from src.bot.services.schedule_service import schedule_service, ScheduleEvent
from src.utils.log_utils import log_with_ts as _log


class PinnedScheduleScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    def start(self):
        if not PINNED_SCHEDULE_ENABLED:
            _log("[SYSTEM] Закреп расписания: отключено в конфиге")
            return

        self.scheduler.add_job(
            self._update_pinned_message,
            CronTrigger(
                hour=PINNED_SCHEDULE_UPDATE_HOUR,
                minute=PINNED_SCHEDULE_UPDATE_MINUTE,
                timezone=TIMEZONE,
            ),
        )
        self.scheduler.start()
        asyncio.create_task(self._update_pinned_message())
        _log("[SYSTEM] Закреп расписания: задача запланирована, сразу обновляем")

    async def _update_pinned_message(self):
        today = datetime.now(TIMEZONE).date()
        text = _build_pinned_text(today)

        pinned_id = _load_pinned_id(PINNED_SCHEDULE_MESSAGE_FILE)

        if text is None:
            # Нет будущих пар — удаляем сообщение, если было
            if pinned_id is not None:
                try:
                    await self.bot.delete_message(CHAT_ID, pinned_id)
                    _log("[SYSTEM] Закреп расписания удалён (нет будущих пар)")
                except Exception as exc:
                    _log(f"[SYSTEM] Не удалось удалить закреп расписания: {exc}")
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
            _log("[SYSTEM] Закреп расписания обновлён")
        except TelegramForbiddenError:
            _log("[SYSTEM] Нет прав на редактирование закрепа; пробуем отправить заново")
            await self._send_and_pin(text)
        except Exception as exc:
            _log(f"[SYSTEM] Не удалось отредактировать закреп расписания: {exc}; отправляем заново")
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
                _log(f"[SYSTEM] Не удалось закрепить сообщение с расписанием: {exc}")
            _save_pinned_id(PINNED_SCHEDULE_MESSAGE_FILE, msg.message_id)
            _log("[SYSTEM] Закреп расписания отправлен и закреплён")
        except Exception as exc:
            _log(f"[SYSTEM] Не удалось отправить закреп с расписанием: {exc}")

    def stop(self):
        self.scheduler.shutdown()

def start_pinned_schedule_scheduler(bot: Bot):
    scheduler = PinnedScheduleScheduler(bot)
    scheduler.start()
    return scheduler

def _build_pinned_text(today: date) -> Optional[str]:
    """Формирует текст закреплённого сообщения. None => ничего не отправлять/удалить."""
    effective_date = schedule_service.get_effective_date(TIMEZONE)
    today_events = schedule_service.get_classes_for_date(effective_date)
    lines = []
    used_next_date: Optional[date] = None
    day_label = "завтра" if effective_date == date.fromordinal(today.toordinal() + 1) else "сегодня"
    title = "📚 Пары на завтра:" if day_label == "завтра" else "📚 Пары сегодня:"

    # Блок на сегодня
    if today_events:
        lines.append(schedule_service.format_classes(today_events, title, "", wrap_quote=True))
    else:
        base_empty = schedule_service.get_no_pairs_message(day_label)
        next_date, next_events = schedule_service.get_next_classes_after(effective_date)
        if next_date and next_events:
            next_block = schedule_service.format_next_classes_block(next_date, next_events, base_date=effective_date)
            used_next_date = next_date
            lines.append(f"{base_empty}\n\n{next_block}")
        else:
            # Вообще нет будущих пар — вернуть None, чтобы удалить сообщение
            return None

    # Полный список по дням, начиная с сегодня
    grouped = _group_events_from(effective_date)
    if grouped:
        # Между блоками — пустая строка
        for idx, (day, events) in enumerate(grouped):
            if idx == 0 and today_events:
                continue  # уже вывели блок сегодня
            if used_next_date and day == used_next_date:
                continue  # пропускаем день, который уже показали в блоке "Следующие пары"
            lines.append("")
            lines.append(_format_day_block(day, events))

    # Внизу предупреждение
    warning = "<b><i>❗️ Расписание для з5130903/40002</i></b>"
    lines.append("")
    lines.append(warning)

    return "\n".join([line for line in lines if line is not None])

def _group_events_from(start_date: date) -> list[tuple[date, list[ScheduleEvent]]]:
    """Собирает пары по датам, начиная с start_date, отсортированно."""
    dates = sorted({e.start.date() for e in schedule_service.events if e.start.date() >= start_date})
    grouped = []
    for d in dates:
        grouped.append((d, [e for e in schedule_service.events if e.start.date() == d]))
    return grouped

def _format_day_block(day: date, events: list[ScheduleEvent]) -> str:
    day_title = schedule_service.weekday_with_preposition(day).capitalize()
    header = f"<b>📌 {day_title} ({day.strftime('%d.%m')}):</b>"
    body = schedule_service.format_classes(events, header, "", wrap_quote=True)
    return body

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
