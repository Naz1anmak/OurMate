"""
Сервис для выполнения системных команд.
Позволяет владельцу бота управлять сервером через Telegram.
"""

import subprocess
import logging
from typing import Optional

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
            logger.info(f"Выполняется команда: {command}")
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
        command = "journalctl -u mybot | grep 'PM; \\|GR; \\|FP;' | tail -50"
        result, success = SystemService.execute_command(command)
        
        if success and result:
            return f"📋 <b>Логи бота (последние 50 сообщений):</b>\n\n<code>{result}</code>"
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
            # Ограничиваем длину сообщения
            if len(result) > 4000:
                result = result[:4000] + "\n\n... (логи обрезаны)"
            return f"📋 <b>Полные логи бота (последние 100 строк):</b>\n\n<code>{result}</code>"
        else:
            return f"❌ <b>Ошибка получения логов:</b>\n\n{result}"
    
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
        command = "systemctl status mybot --no-pager"
        result, success = SystemService.execute_command(command)
        
        if success and result:
            # Ограничиваем длину сообщения
            if len(result) > 4000:
                result = result[:4000] + "\n\n... (статус обрезан)"
            return f"📊 <b>Статус бота:</b>\n\n<code>{result}</code>"
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
