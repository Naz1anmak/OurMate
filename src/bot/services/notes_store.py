"""SQLite-слой списков/заметок (aiosqlite). Источник правды. Образцы — ping_store/reminder_store."""
import aiosqlite

from src.config.settings import NOTES_DB_PATH, NOTES_RETENTION_DAYS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL,
    title           TEXT    NOT NULL,
    title_lower     TEXT    NOT NULL,
    author_id       INTEGER NOT NULL,
    formal          INTEGER NOT NULL DEFAULT 0,
    card_message_id INTEGER,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(chat_id, title_lower)
);

CREATE TABLE IF NOT EXISTS note_members (
    note_id       INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    username      TEXT,
    name_override TEXT,
    note          TEXT,
    added_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(note_id, user_id)
);
"""


class NotesStore:
    def __init__(self, db_path: str = NOTES_DB_PATH) -> None:
        self.db_path = db_path

    def _db(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.db_path)

    async def _setup(self, db: aiosqlite.Connection) -> None:
        db.row_factory = aiosqlite.Row

    async def init(self) -> None:
        async with self._db() as db:
            await self._setup(db)
            await db.executescript(_SCHEMA)
            await db.commit()

    # ── Списки ────────────────────────────────────────────────────────────
    async def create(self, *, chat_id: int, title: str, author_id: int,
                     formal: bool) -> int | None:
        """INSERT нового списка. При конфликте UNIQUE(chat_id, title) → None."""
        async with self._db() as db:
            await self._setup(db)
            try:
                cur = await db.execute(
                    "INSERT INTO notes (chat_id, title, title_lower, author_id, formal) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (chat_id, title, title.lower(), author_id, 1 if formal else 0))
                await db.commit()
                return cur.lastrowid
            except aiosqlite.IntegrityError:
                return None

    async def get(self, note_id: int) -> dict | None:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_by_title(self, chat_id: int, title: str) -> dict | None:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT * FROM notes WHERE chat_id = ? AND title_lower = ?",
                (chat_id, title.lower()))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def list_for_chat(self, chat_id: int) -> list[dict]:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT n.*, "
                "(SELECT COUNT(*) FROM note_members m WHERE m.note_id = n.id) AS member_count "
                "FROM notes n WHERE n.chat_id = ? ORDER BY n.created_at",
                (chat_id,))
            return [dict(r) for r in await cur.fetchall()]

    async def set_formal(self, note_id: int, formal: bool) -> bool:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "UPDATE notes SET formal = ? WHERE id = ?",
                (1 if formal else 0, note_id))
            await db.commit()
            return cur.rowcount > 0

    # add_member нужна уже здесь (тест counts). Полный набор участников — Task 3.
    async def add_member(self, note_id: int, *, user_id: int,
                         username: str | None, name_override: str | None = None) -> bool:
        async with self._db() as db:
            await self._setup(db)
            try:
                await db.execute(
                    "INSERT INTO note_members (note_id, user_id, username, name_override) "
                    "VALUES (?, ?, ?, ?)",
                    (note_id, user_id, username, name_override))
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    # ── Участники ─────────────────────────────────────────────────────────
    async def members(self, note_id: int) -> list[dict]:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT user_id, username, name_override, note FROM note_members "
                "WHERE note_id = ? ORDER BY added_at, rowid",
                (note_id,))
            return [dict(r) for r in await cur.fetchall()]

    async def count(self, note_id: int) -> int:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT COUNT(*) AS n FROM note_members WHERE note_id = ?", (note_id,))
            row = await cur.fetchone()
            return int(row["n"])

    async def is_member(self, note_id: int, user_id: int) -> bool:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT 1 FROM note_members WHERE note_id = ? AND user_id = ?",
                (note_id, user_id))
            return await cur.fetchone() is not None

    async def toggle_member(self, note_id: int, *, user_id: int,
                            username: str | None, name_override: str | None = None) -> bool:
        """True — записан после вызова, False — вышел. Идемпотентно. Уточнение не трогаем."""
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT 1 FROM note_members WHERE note_id = ? AND user_id = ?",
                (note_id, user_id))
            if await cur.fetchone():
                await db.execute(
                    "DELETE FROM note_members WHERE note_id = ? AND user_id = ?",
                    (note_id, user_id))
                await db.commit()
                return False
            await db.execute(
                "INSERT INTO note_members (note_id, user_id, username, name_override) "
                "VALUES (?, ?, ?, ?)", (note_id, user_id, username, name_override))
            await db.commit()
            return True

    async def set_note(self, note_id: int, user_id: int, note: str) -> bool:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "UPDATE note_members SET note = ? WHERE note_id = ? AND user_id = ?",
                (note, note_id, user_id))
            await db.commit()
            return cur.rowcount > 0

    async def set_name(self, note_id: int, user_id: int, name_override: str) -> bool:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "UPDATE note_members SET name_override = ? WHERE note_id = ? AND user_id = ?",
                (name_override, note_id, user_id))
            await db.commit()
            return cur.rowcount > 0

    async def remove_member(self, note_id: int, user_id: int) -> bool:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "DELETE FROM note_members WHERE note_id = ? AND user_id = ?",
                (note_id, user_id))
            await db.commit()
            return cur.rowcount > 0

    async def set_card_message(self, note_id: int, message_id: int) -> bool:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "UPDATE notes SET card_message_id = ? WHERE id = ?", (message_id, note_id))
            await db.commit()
            return cur.rowcount > 0

    async def get_by_card_message(self, chat_id: int, message_id: int) -> dict | None:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT * FROM notes WHERE chat_id = ? AND card_message_id = ?",
                (chat_id, message_id))
            row = await cur.fetchone()
            return dict(row) if row else None

    # ── Управление списком ────────────────────────────────────────────────
    async def delete(self, note_id: int) -> bool:
        async with self._db() as db:
            await self._setup(db)
            await db.execute("DELETE FROM note_members WHERE note_id = ?", (note_id,))
            cur = await db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            await db.commit()
            return cur.rowcount > 0

    async def clear(self, note_id: int) -> int:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute("DELETE FROM note_members WHERE note_id = ?", (note_id,))
            await db.commit()
            return cur.rowcount

    async def rename(self, note_id: int, new_title: str) -> bool:
        async with self._db() as db:
            await self._setup(db)
            try:
                cur = await db.execute(
                    "UPDATE notes SET title = ?, title_lower = ? WHERE id = ?",
                    (new_title, new_title.lower(), note_id))
                await db.commit()
                return cur.rowcount > 0
            except aiosqlite.IntegrityError:
                return False

    async def remove_member_everywhere(self, chat_id: int, user_id: int) -> int:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "DELETE FROM note_members WHERE user_id = ? AND note_id IN "
                "(SELECT id FROM notes WHERE chat_id = ?)",
                (user_id, chat_id))
            await db.commit()
            return cur.rowcount

    async def cleanup_old(self, *, days: int = NOTES_RETENTION_DAYS) -> int:
        """Удаляет списки старше N дней (по created_at) вместе с их участниками."""
        async with self._db() as db:
            await self._setup(db)
            await db.execute(
                "DELETE FROM note_members WHERE note_id IN "
                "(SELECT id FROM notes WHERE created_at < datetime('now', ?))",
                (f"-{days} days",))
            cur = await db.execute(
                "DELETE FROM notes WHERE created_at < datetime('now', ?)",
                (f"-{days} days",))
            await db.commit()
            return cur.rowcount


notes_store = NotesStore()
