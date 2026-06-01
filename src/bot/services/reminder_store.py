"""SQLite-слой напоминаний (aiosqlite). Источник правды."""
import aiosqlite

from src.config.settings import REMINDER_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    text            TEXT NOT NULL,
    fire_at         TEXT NOT NULL,
    scope           TEXT NOT NULL,
    chat_id         INTEGER NOT NULL,
    author_id       INTEGER NOT NULL,
    card_message_id INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    pending_text    TEXT,
    pending_fire_at TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS reminder_subscribers (
    reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL,
    first_name  TEXT,
    username    TEXT,
    UNIQUE(reminder_id, user_id)
);
"""

# Статусы, при которых подписчики больше не нужны и должны быть удалены.
_TERMINAL_STATUSES = {"cancelled", "fired"}


class ReminderStore:
    def __init__(self, db_path: str = REMINDER_DB_PATH) -> None:
        self.db_path = db_path

    def _db(self) -> aiosqlite.Connection:
        """Возвращает контекстный менеджер соединения с нужными настройками."""
        return aiosqlite.connect(self.db_path)

    async def _setup(self, db: aiosqlite.Connection) -> None:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")

    async def init(self) -> None:
        async with self._db() as db:
            await self._setup(db)
            await db.executescript(_SCHEMA)
            await db.commit()

    async def add(self, *, text: str, fire_at: str, scope: str, chat_id: int,
                  author_id: int, status: str = "pending",
                  card_message_id: int | None = None) -> int:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "INSERT INTO reminders (text, fire_at, scope, chat_id, author_id, status, card_message_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (text, fire_at, scope, chat_id, author_id, status, card_message_id),
            )
            await db.commit()
            return cur.lastrowid

    async def get(self, reminder_id: int) -> dict | None:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def set_status(self, reminder_id: int, status: str) -> None:
        async with self._db() as db:
            await self._setup(db)
            await db.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
            # При переводе в терминальный статус подписчики больше не нужны:
            # ON DELETE CASCADE не срабатывает на UPDATE, поэтому удаляем явно.
            if status in _TERMINAL_STATUSES:
                await db.execute(
                    "DELETE FROM reminder_subscribers WHERE reminder_id = ?", (reminder_id,)
                )
            await db.commit()

    async def set_card_message_id(self, reminder_id: int, message_id: int) -> None:
        async with self._db() as db:
            await self._setup(db)
            await db.execute("UPDATE reminders SET card_message_id = ? WHERE id = ?",
                             (message_id, reminder_id))
            await db.commit()

    async def set_pending_update(self, reminder_id: int, *, text: str | None,
                                 fire_at: str | None) -> None:
        async with self._db() as db:
            await self._setup(db)
            await db.execute(
                "UPDATE reminders SET pending_text = ?, pending_fire_at = ? WHERE id = ?",
                (text, fire_at, reminder_id),
            )
            await db.commit()

    async def apply_pending_update(self, reminder_id: int) -> None:
        async with self._db() as db:
            await self._setup(db)
            await db.execute(
                "UPDATE reminders SET "
                "text = COALESCE(pending_text, text), "
                "fire_at = COALESCE(pending_fire_at, fire_at), "
                "pending_text = NULL, pending_fire_at = NULL WHERE id = ?",
                (reminder_id,),
            )
            await db.commit()

    async def clear_pending_update(self, reminder_id: int) -> None:
        await self.set_pending_update(reminder_id, text=None, fire_at=None)

    async def _list(self, where: str, params: tuple) -> list[dict]:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                f"SELECT * FROM reminders WHERE {where} ORDER BY fire_at", params)
            return [dict(r) for r in await cur.fetchall()]

    async def list_pending_for_chat(self, chat_id: int) -> list[dict]:
        return await self._list("status = 'pending' AND chat_id = ?", (chat_id,))

    async def list_pending_for_author(self, author_id: int) -> list[dict]:
        return await self._list(
            "status = 'pending' AND scope = 'self' AND author_id = ?", (author_id,))

    async def list_all_pending(self) -> list[dict]:
        return await self._list("status = 'pending'", ())

    async def toggle_subscriber(self, reminder_id: int, *, user_id: int,
                                first_name: str | None, username: str | None) -> bool:
        """True — подписан после вызова, False — отписан. Идемпотентно."""
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT 1 FROM reminder_subscribers WHERE reminder_id = ? AND user_id = ?",
                (reminder_id, user_id))
            exists = await cur.fetchone()
            if exists:
                await db.execute(
                    "DELETE FROM reminder_subscribers WHERE reminder_id = ? AND user_id = ?",
                    (reminder_id, user_id))
                await db.commit()
                return False
            await db.execute(
                "INSERT INTO reminder_subscribers (reminder_id, user_id, first_name, username) "
                "VALUES (?, ?, ?, ?)", (reminder_id, user_id, first_name, username))
            await db.commit()
            return True

    async def has_subscriber(self, reminder_id: int, user_id: int) -> bool:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT 1 FROM reminder_subscribers WHERE reminder_id = ? AND user_id = ?",
                (reminder_id, user_id))
            return await cur.fetchone() is not None

    async def count_subscribers(self, reminder_id: int) -> int:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT COUNT(*) AS c FROM reminder_subscribers WHERE reminder_id = ?",
                (reminder_id,))
            row = await cur.fetchone()
            return row["c"]

    async def list_subscribers(self, reminder_id: int) -> list[dict]:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT user_id, first_name, username FROM reminder_subscribers WHERE reminder_id = ?",
                (reminder_id,))
            return [dict(r) for r in await cur.fetchall()]


# Singleton (как schedule_service / birthday_service)
reminder_store = ReminderStore()
