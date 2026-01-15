"""
Сервис для выполнения системных команд.
Позволяет владельцу бота управлять сервером через Telegram.
"""
import subprocess
import logging
from typing import Optional
import html

logger = logging.getLogger(__name__)

class SystemService:
    """
    Сервис для выполнения системных команд на сервере.
    Предоставляет безопасный интерфейс для управления ботом.
    """
    
    @staticmethod
    def execute_command(command: str) -> tuple[str, bool]:
        """
        Выполняет системную команду и возвращает результат.
        
        Args:
            command (str): Команда для выполнения
            
        Returns:
            tuple[str, bool]: (результат, успех выполнения)
        """
        try:
            # logger.info(f"Выполняется команда: {command}")
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30  # Таймаут 30 секунд
            )
            
            if result.returncode == 0:
                return result.stdout.strip(), True
            else:
                error_msg = f"Ошибка выполнения команды: {result.stderr.strip()}"
                logger.error(error_msg)
                return error_msg, False
                
        except subprocess.TimeoutExpired:
            error_msg = "Команда превысила лимит времени (30 секунд)"
            logger.error(error_msg)
            return error_msg, False
        except Exception as e:
            error_msg = f"Ошибка выполнения команды: {str(e)}"
            logger.error(error_msg)
            return error_msg, False
    
    @staticmethod
    def get_bot_logs() -> str:
        """
        Получает логи бота (только PM, GR, FP сообщения).
        
        Returns:
            str: Отфильтрованные логи
        """
        command = "journalctl -u mybot --no-pager | grep 'PM; \\|GR; \\|FP;' | tail -50"
        result, success = SystemService.execute_command(command)

        if success and result:
            # Краткие логи: добавляем цветные маркеры и обрезаем с конца
            body = SystemService._format_lines_with_highlight_and_limit(
                result.splitlines(),
                max_len=3800,
                highlights=(),
                emoji_map={"PM;": "🔴", "GR;": "🟡", "FP;": "🟢"},
            )
            return "📋 <b>Логи бота (последние 50 сообщений):</b>\n\n<code>" + body + "</code>"
        elif success:
            return "📋 <b>Логи бота:</b>\n\nНет сообщений для отображения"
        else:
            return f"❌ <b>Ошибка получения логов:</b>\n\n{result}"
    
    @staticmethod
    def get_full_logs() -> str:
        """
        Получает полные логи бота.
        
        Returns:
            str: Полные логи
        """
        command = "journalctl -u mybot --no-pager -n 100"
        result, success = SystemService.execute_command(command)

        if success and result:
            body = SystemService._format_lines_with_highlight_and_limit(
                result.splitlines(),
                max_len=3800,
                highlights=("PM;", "GR;", "FP;"),
                emoji_map={"PM;": "🔴", "GR;": "🟡", "FP;": "🟢"},
            )
            # Без <code>, чтобы работало жирное выделение важных строк
            return "📋 <b>Полные логи бота (последние 100 строк):</b>\n\n" + body
        else:
            return f"❌ <b>Ошибка получения логов:</b>\n\n{result}"

    @staticmethod
    def _format_lines_with_highlight_and_limit(
        lines: list[str],
        max_len: int,
        highlights: tuple[str, ...],
        emoji_map: dict[str, str] | None = None,
    ) -> str:
        """
        Форматирует строки HTML: делает жирными строки с маркерами и обрезает с конца.

        - Каждая строка HTML-экранируется
        - Строки с любым из маркеров в `highlights` оборачиваются в <b>
        - Строки соединяются через <br>
        - Итоговая длина ограничивается `max_len`, начиная с хвоста
        """
        rendered_lines: list[str] = []

        def render_line(raw: str) -> str:
            prefix = ""
            matched_highlight = False
            found_marker = None
            if emoji_map or highlights:
                for marker in (emoji_map.keys() if emoji_map else highlights):
                    if marker in raw:
                        found_marker = marker
                        break
                if found_marker and emoji_map and found_marker in emoji_map:
                    prefix = emoji_map[found_marker] + " "
                if found_marker and highlights and found_marker in highlights:
                    matched_highlight = True

            full_line = prefix + raw
            esc = html.escape(full_line)
            if matched_highlight:
                return f"<b>{esc}</b>\n"
            return f"{esc}\n"

        # Набираем строки с конца, пока не упремся в лимит
        current_len = 0
        cutoff_reached = False
        for raw in reversed(lines):
            piece = render_line(raw)
            piece_len = len(piece)
            if current_len + piece_len > max_len:
                cutoff_reached = True
                break
            rendered_lines.append(piece)
            current_len += piece_len

        body = "".join(reversed(rendered_lines))
        if cutoff_reached:
            body = "... (логи обрезаны, показан конец)\n" + body
        return body or "Нет строк для отображения"
    
    @staticmethod
    def stop_bot() -> str:
        """
        Останавливает бота.
        
        Returns:
            str: Результат операции
        """
        command = "systemctl stop mybot"
        result, success = SystemService.execute_command(command)
        
        if success:
            return "🛑 <b>Бот остановлен</b>\n\nКоманда выполнена успешно"
        else:
            return f"❌ <b>Ошибка остановки бота:</b>\n\n{result}"
    
    @staticmethod
    def get_bot_status() -> str:
        """
        Получает статус бота.
        
        Returns:
            str: Статус бота
        """
        command = "systemctl status mybot --no-pager --lines=0"
        result, success = SystemService.execute_command(command)
        
        if success and result:
            # Экранируем и обрезаем с конца, показывая самый свежий фрагмент статуса
            escaped = html.escape(result)
            max_len = 3800
            if len(escaped) > max_len:
                escaped = "... (статус обрезан, показан конец)\n" + escaped[-max_len:]
            return f"📊 <b>Статус бота:</b>\n\n<code>{escaped}</code>"
        else:
            return f"❌ <b>Ошибка получения статуса:</b>\n\n{result}"
    
    @staticmethod
    def get_system_info() -> str:
        """
        Получает информацию о системе.
        
        Returns:
            str: Информация о системе
        """
        commands = [
            ("uptime", "Время работы системы"),
            ("free -h", "Использование памяти"),
            ("df -h /", "Использование диска"),
            ("ps aux | grep mybot | grep -v grep", "Процессы бота")
        ]
        
        result_parts = []
        for command, description in commands:
            output, success = SystemService.execute_command(command)
            if success and output:
                result_parts.append(f"<b>{description}:</b>\n<code>{output}</code>")
        
        if result_parts:
            return "🖥️ <b>Информация о системе:</b>\n\n" + "\n\n".join(result_parts)
        else:
            return "❌ <b>Ошибка получения информации о системе</b>"


# Создаем глобальный экземпляр сервиса
system_service = SystemService()
