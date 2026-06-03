"""Дружелюбные тексты ответа при исчерпании дневного лимита обращений.

Тексты содержат unicode-эмодзи; PremiumEmojiMiddleware подставит <tg-emoji> по символу.
Отправлять с parse_mode="HTML" (иначе сырой tg-emoji тег)."""
from dataclasses import dataclass
import random
from typing import List

from src.core.emoji import E


@dataclass(frozen=True)
class LimitVariant:
    """Текст блок-сообщения; эмодзи прокинутся middleware."""

    text: str


_LIMIT_VARIANTS: List[LimitVariant] = [
    LimitVariant(f"{E.NO_CLASS_SLEEP} На сегодня сил отвечать больше не осталось — давай завтра."),
    LimitVariant(f"{E.NO_CLASS_SUN} Мой рабочий день закончен, до завтра!"),
    LimitVariant(f"{E.NO_CLASS_CLOCK} Я сегодня уже наговорился, продолжим завтра."),
    LimitVariant(f"{E.ALARM_CLOCK} Лимит на сегодня исчерпан — возвращайся утром, буду свеж."),
    LimitVariant(f"{E.NO_CLASS_HEART} Всё, на сегодня я выдохся. Завтра снова на связи."),
]


def pick_limit_variant() -> LimitVariant:
    """Возвращает случайный текст блок-сообщения."""
    return random.choice(_LIMIT_VARIANTS)
