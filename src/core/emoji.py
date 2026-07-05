"""Семантические эмодзи проекта.

Каждое эмодзи имеет unicode-fallback (всегда работает) и опциональный premium_id.
Middleware заменяет unicode на <tg-emoji emoji-id="..."> в исходящих сообщениях:
если у клиента есть Telegram Premium — он увидит анимированный custom emoji,
у остальных останется обычный unicode.

premium_id=None  ← оставить unicode без замены
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Emoji:
    unicode: str
    premium_id: str | None = None

    def __str__(self) -> str:
        return self.unicode


class E:
    """Все эмодзи проекта. premium_id у заполненных — ID из Telegram."""

    # ── 🤖 Общие / команды ─────────────────────────────────────
    ROBOT = Emoji("🤖", premium_id="5372981976804366741")
    CHAT = Emoji("💬", premium_id="5443038326535759644")
    LINK = Emoji("🔗", premium_id="5375129357373165375")
    START = Emoji("📲", premium_id="5406809207947142040")

    # ── ❕ Подсказки / статусы ─────────────────────────────────
    INFO = Emoji("❕", premium_id="5220197908342648622")
    INFO_ALT = Emoji("ℹ️", premium_id="5334544901428229844")
    IDEA = Emoji("💡", premium_id="5472146462362048818")
    CHECK = Emoji("✅", premium_id="5427009714745517609")
    CROSS = Emoji("❌", premium_id="5465665476971471368")
    WARNING = Emoji("⚠️", premium_id="5447644880824181073")
    BAN = Emoji("🚫")

    # ── 🛠 Системные / админские ───────────────────────────────
    CLIPBOARD = Emoji("📋", premium_id="5258389041006518073")
    PARTY = Emoji("🎉", premium_id="5436040291507247633")

    # ── 🧠 Placeholder варианты (LLM «думает…») ────────────────
    THINK_BRAIN = Emoji("🧠", premium_id="5237799019329105246")
    THINK_HOURGLASS = Emoji("⌛", premium_id="5451646226975955576")
    THINK_BUBBLE = Emoji("💭", premium_id="5465143921912846619")
    THINK_SHUSH = Emoji("🤫", premium_id="5359628193336669414")
    THINK_PENCIL = Emoji("✏️", premium_id="5334673106202010226")
    THINK_SEARCH = Emoji("🔎", premium_id="5188311512791393083")
    THINK_GEAR = Emoji("⚙️", premium_id="5341715473882955310")
    THINK_PUZZLE = Emoji("🧩", premium_id="5265120027853481187")
    THINK_QUESTION = Emoji("🤔", premium_id="5368809197032971971")

    # ── 📅 «Пар нет» (расписание) ──────────────────────────────
    NO_CLASS_BOOKS = Emoji("📚", premium_id="5472178859300363509")
    NO_CLASS_SPARKLES = Emoji("✨", premium_id="5463297803235113601")
    NO_CLASS_SLEEP = Emoji("💤", premium_id="5451959871257713464")
    NO_CLASS_HEART = Emoji("💚", premium_id="5449505950283078474")
    NO_CLASS_PARTY = Emoji("🥳", premium_id="5328273248448686763")
    NO_CLASS_CLOCK = Emoji("🕒", premium_id="5454415424319931791")
    NO_CLASS_SUN = Emoji("☀️", premium_id="5469947168523558652")
    NO_CLASS_PHONE = Emoji("📞", premium_id="5318779098686826724")
    NO_CLASS_BOOK = Emoji("📖", premium_id="5226512880362332956")
    NO_CLASS_CALENDAR = Emoji("🗓️", premium_id="5413879192267805083")
    NO_CLASS_GAME = Emoji("🎮", premium_id="5319247469165433798")

    # ── 📌 Расписание (заголовки) ──────────────────────────────
    PIN = Emoji("📌", premium_id="5465482434055260820")
    ALERT = Emoji("❗️", premium_id="5224495199215963724")
    TEACHER = Emoji("👨‍🏫", premium_id="5373098009640836781")

    # ── Diff расписания ────────────────────────────────────────
    ALARM_CLOCK = Emoji("⏰", premium_id="5413704112220949842")
    NEW = Emoji("🆕", premium_id="5361979468887893611")

    # ── 🔔 Напоминания / пинг-лист ─────────────────────────────
    REMINDER = Emoji("🔔", premium_id="5242628160297641831")

    # ── Списки / очереди ───────────────────────────────────────
    POINT_UP = Emoji("👆", premium_id="5172475985550902005")


ALL_EMOJI: tuple[Emoji, ...] = tuple(
    v for v in vars(E).values() if isinstance(v, Emoji)
)
