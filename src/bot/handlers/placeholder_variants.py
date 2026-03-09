"""Набор плейсхолдеров для стрим-ответов с кастомными эмодзи."""
from dataclasses import dataclass
import random
from typing import List, Tuple

from src.utils.emoji_utils import make_custom_emoji_payload


@dataclass(frozen=True)
class PlaceholderVariant:
    """Описывает плейсхолдер с кастомным эмодзи и текстом."""

    text: str
    custom_emoji_id: str

    def reply_payload(self) -> Tuple[str, List | None]:
        """Возвращает текст и сущности для ответа с кастомным эмодзи."""
        try:
            return make_custom_emoji_payload(self.text, self.custom_emoji_id)
        except Exception:
            return self.text, None

_PLACEHOLDER_VARIANTS: List[PlaceholderVariant] = [
    PlaceholderVariant(text="🧠 Мне понадобится немного времени, думаю над ответом...", custom_emoji_id="5237799019329105246"),
    PlaceholderVariant(text="⌛ Одну секунду, формулирую мысль...", custom_emoji_id="5451646226975955576"),
    PlaceholderVariant(text="💭 Обдумываю, чтобы ответить по делу...", custom_emoji_id="5465143921912846619"),
    PlaceholderVariant(text="✏️ Проверяю факты, сейчас вернусь...", custom_emoji_id="5334673106202010226"),
    PlaceholderVariant(text="🔎 Сверяю детали, почти готово...", custom_emoji_id="5188311512791393083"),
    PlaceholderVariant(text="⚙️ Прокручиваю логику в голове...", custom_emoji_id="5341715473882955310"),
    PlaceholderVariant(text="🧩 Осталась последняя деталь...", custom_emoji_id="5265120027853481187"),
    PlaceholderVariant(text="💭 Привожу мысли в порядок...", custom_emoji_id="5359628193336669414"),
    PlaceholderVariant(text="📚 Освежаю материалы, секунду...", custom_emoji_id="5373098009640836781"),
    PlaceholderVariant(text="🤔 Хочу ответить точно, чуть-чуть подожди...", custom_emoji_id="5368809197032971971"),
]

def pick_placeholder_variant() -> PlaceholderVariant:
    """Возвращает случайный плейсхолдер для стриминга."""
    return random.choice(_PLACEHOLDER_VARIANTS)
