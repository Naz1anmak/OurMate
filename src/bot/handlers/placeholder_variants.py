"""Набор плейсхолдеров для стрим-ответов с кастомными эмодзи.

Тексты содержат unicode-эмодзи в начале; PremiumEmojiMiddleware на исходящих
сообщениях подставит <tg-emoji> теги, если ID есть в src.core.emoji.
"""
from dataclasses import dataclass
import random
from typing import List


@dataclass(frozen=True)
class PlaceholderVariant:
    """Текст плейсхолдера; эмодзи прокинутся middleware."""

    text: str


_PLACEHOLDER_VARIANTS: List[PlaceholderVariant] = [
    PlaceholderVariant("🧠 Мне понадобится немного времени, думаю над ответом..."),
    PlaceholderVariant("⌛ Одну секунду, формулирую мысль..."),
    PlaceholderVariant("💭 Обдумываю, чтобы ответить по делу..."),
    PlaceholderVariant("✏️ Проверяю факты, сейчас вернусь..."),
    PlaceholderVariant("🔎 Сверяю детали, почти готово..."),
    PlaceholderVariant("⚙️ Прокручиваю логику в голове..."),
    PlaceholderVariant("🧩 Осталась последняя деталь..."),
    PlaceholderVariant("💭 Привожу мысли в порядок..."),
    PlaceholderVariant("📚 Освежаю материалы, секунду..."),
    PlaceholderVariant("🤔 Хочу ответить точно, чуть-чуть подожди..."),
]


def pick_placeholder_variant() -> PlaceholderVariant:
    """Возвращает случайный плейсхолдер для стриминга."""
    return random.choice(_PLACEHOLDER_VARIANTS)
