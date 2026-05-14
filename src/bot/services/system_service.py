"""Сервис для команд владельца, читающих логи бота.

Логи пишет RotatingFileHandler в data/logs/bot.log (см. src/utils/logging.py).
Команды `logs`/`full logs` берут tail этого файла с маркерами PM/GR/FP.
"""
from __future__ import annotations

import html
import logging
from collections import deque
from pathlib import Path

from src.utils.logging import LOG_FILE_PATH

logger = logging.getLogger(__name__)

MAX_TAIL_LINES = 500
MAX_RESPONSE_LEN = 4000


def _read_last_lines(path: Path, limit: int) -> list[str]:
    """Читает последние `limit` строк файла без загрузки его целиком."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return list(deque(fh, maxlen=limit))
    except OSError as exc:
        logger.warning("read_log_failed path=%s err=%s", path, exc)
        return []


def _filter_short_logs(lines: list[str]) -> list[str]:
    """Берёт только строки с маркерами PM;/GR;/FP; (формат пользовательских событий)."""
    return [line for line in lines if any(m in line for m in ("PM; ", "GR; ", "FP; "))]


def _format_lines_with_highlight_and_limit(
    lines: list[str],
    max_len: int,
    highlights: tuple[str, ...],
    emoji_map: dict[str, str] | None = None,
) -> str:
    """Форматирует строки HTML: маркер-эмодзи в начале, выделение жирным,
    обрезка с хвоста до max_len."""
    rendered_lines: list[str] = []

    def render_line(raw: str) -> str:
        prefix = ""
        matched_highlight = False
        found_marker = None
        markers: list[str] = []
        if emoji_map:
            markers.extend(emoji_map.keys())
        if highlights:
            markers.extend(highlights)
        for marker in markers:
            if marker in raw:
                found_marker = marker
                break
        if found_marker and emoji_map and found_marker in emoji_map:
            prefix = emoji_map[found_marker] + " "
        if found_marker and highlights and found_marker in highlights:
            matched_highlight = True

        full_line = prefix + raw.rstrip("\n")
        esc = html.escape(full_line)
        if matched_highlight:
            return f"<b>{esc}</b>\n"
        return f"{esc}\n"

    current_len = 0
    cutoff_reached = False
    for raw in reversed(lines):
        piece = render_line(raw)
        if current_len + len(piece) > max_len:
            cutoff_reached = True
            break
        rendered_lines.append(piece)
        current_len += len(piece)

    body = "".join(reversed(rendered_lines))
    if cutoff_reached:
        body = "... (обрезаны до лимита Telegram)\n" + body
    return body or "Нет строк для отображения"


class SystemService:
    """Команды владельца, работающие в docker-окружении (без systemctl/journalctl)."""

    @staticmethod
    def get_bot_logs() -> str:
        """Краткие логи: только строки с маркерами PM/GR/FP."""
        lines = _read_last_lines(LOG_FILE_PATH, MAX_TAIL_LINES)
        filtered = _filter_short_logs(lines)
        if not filtered:
            if not lines:
                return "📋 <b>Логи бота:</b>\n\nФайл логов пуст или недоступен."
            return "📋 <b>Логи бота:</b>\n\nНет строк с маркерами PM/GR/FP."

        body = _format_lines_with_highlight_and_limit(
            filtered,
            max_len=MAX_RESPONSE_LEN,
            highlights=(),
            emoji_map={"PM; ": "🔴", "GR; ": "🟡", "FP; ": "🟢"},
        )
        return "📋 <b>Логи бота:</b>\n\n<code>" + body + "</code>"

    @staticmethod
    def get_full_logs() -> str:
        """Полные логи: последние 200 строк со всеми уровнями."""
        lines = _read_last_lines(LOG_FILE_PATH, 200)
        if not lines:
            return "📋 <b>Полные логи бота:</b>\n\nФайл логов пуст или недоступен."

        body = _format_lines_with_highlight_and_limit(
            lines,
            max_len=MAX_RESPONSE_LEN,
            highlights=("PM; ", "GR; ", "FP; ", "src.bot."),
            emoji_map={"PM; ": "🔴", "GR; ": "🟡", "FP; ": "🟢"},
        )
        return "📋 <b>Полные логи бота:</b>\n\n" + body


system_service = SystemService()
