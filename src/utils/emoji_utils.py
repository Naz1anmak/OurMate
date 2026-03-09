from typing import List, Tuple

from aiogram.types import MessageEntity

def make_custom_emoji_payload(text: str, custom_emoji_id: str, emoji_prefix: str | None = None) -> Tuple[str, List[MessageEntity]]:
    """Собирает текст и сущности с кастомным эмодзи в начале сообщения.

    Telegram считает offset/length в UTF-16 code units, поэтому берём префикс
    (emoji_prefix, либо первый токен до пробела, либо первый символ) и считаем
    его длину в UTF-16, чтобы не порвать суррогатные пары.
    """
    prefix = emoji_prefix or (text.split(" ", 1)[0] if " " in text else text[:1])
    length_utf16 = max(1, len(prefix.encode("utf-16-le")) // 2)

    entity = MessageEntity(
        type="custom_emoji",
        offset=0,
        length=length_utf16,
        custom_emoji_id=custom_emoji_id,
    )
    return text, [entity]
