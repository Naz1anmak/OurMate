"""Набор плейсхолдеров для стрим-ответов с кастомными эмодзи.

Тексты содержат unicode-эмодзи в начале; PremiumEmojiMiddleware на исходящих
сообщениях подставит <tg-emoji> теги, если ID есть в src.core.emoji.
"""
from dataclasses import dataclass
import random
from typing import List

from src.core.emoji import E


@dataclass(frozen=True)
class PlaceholderVariant:
    """Текст плейсхолдера; эмодзи прокинутся middleware."""

    text: str


_PLACEHOLDER_VARIANTS: List[PlaceholderVariant] = [
    PlaceholderVariant(f"{E.THINK_BRAIN} Мне понадобится немного времени, думаю над ответом..."),
    PlaceholderVariant(f"{E.THINK_HOURGLASS} Одну секунду, формулирую мысль..."),
    PlaceholderVariant(f"{E.THINK_BUBBLE} Обдумываю, чтобы ответить по делу..."),
    PlaceholderVariant(f"{E.THINK_PENCIL} Проверяю факты, сейчас вернусь..."),
    PlaceholderVariant(f"{E.THINK_SEARCH} Сверяю детали, почти готово..."),
    PlaceholderVariant(f"{E.THINK_GEAR} Прокручиваю логику в голове..."),
    PlaceholderVariant(f"{E.THINK_PUZZLE} Осталась последняя деталь..."),
    PlaceholderVariant(f"{E.THINK_SHUSH} Привожу мысли в порядок..."),
    PlaceholderVariant(f"{E.TEACHER} Освежаю материалы, секунду..."),
    PlaceholderVariant(f"{E.THINK_QUESTION} Хочу ответить точно, чуть-чуть подожди..."),
]


def pick_placeholder_variant() -> PlaceholderVariant:
    """Возвращает случайный плейсхолдер для стриминга."""
    return random.choice(_PLACEHOLDER_VARIANTS)
