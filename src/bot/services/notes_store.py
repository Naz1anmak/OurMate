"""SQLite-слой списков/заметок (aiosqlite). Источник правды. Образцы — ping_store/reminder_store."""
import json

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
    undo_json       TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(chat_id, title_lower)
);

CREATE TABLE IF NOT EXISTS note_members (
    note_id       INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    username      TEXT,
    name_override TEXT,
    tg_name       TEXT,
    note          TEXT,
    position      INTEGER NOT NULL DEFAULT 0,
    added_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(note_id, user_id)
);
"""

# Колонки, добавленные после первого релиза, — донакатываем на существующую БД.
_MEMBER_MIGRATIONS = {
    "tg_name": "ALTER TABLE note_members ADD COLUMN tg_name TEXT",
    "position": "ALTER TABLE note_members ADD COLUMN position INTEGER NOT NULL DEFAULT 0",
}

_NOTE_MIGRATIONS = {
    "undo_json": "ALTER TABLE notes ADD COLUMN undo_json TEXT",
}


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
            await self._migrate(db)
            await db.commit()

    async def _migrate(self, db: aiosqlite.Connection) -> None:
        cur = await db.execute("PRAGMA table_info(note_members)")
        cols = {r["name"] for r in await cur.fetchall()}
        for col, ddl in _MEMBER_MIGRATIONS.items():
            if col not in cols:
                await db.execute(ddl)

        cur = await db.execute("PRAGMA table_info(notes)")
        note_cols = {r["name"] for r in await cur.fetchall()}
        for col, ddl in _NOTE_MIGRATIONS.items():
            if col not in note_cols:
                await db.execute(ddl)

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

    async def _next_position(self, db: aiosqlite.Connection, note_id: int) -> int:
        cur = await db.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS p FROM note_members WHERE note_id = ?",
            (note_id,))
        return int((await cur.fetchone())["p"])

    async def add_member(self, note_id: int, *, user_id: int, username: str | None,
                         name_override: str | None = None, tg_name: str | None = None) -> bool:
        async with self._db() as db:
            await self._setup(db)
            try:
                pos = await self._next_position(db, note_id)
                await db.execute(
                    "INSERT INTO note_members "
                    "(note_id, user_id, username, name_override, tg_name, position) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (note_id, user_id, username, name_override, tg_name, pos))
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def set_undo(self, note_id: int, *, action: str, author_id: int,
                       members: list[dict], reply_message_id: int | None = None) -> None:
        """Записать снапшот «до» последнего действия (перезаписывает прежний слот)."""
        payload = json.dumps({
            "action": action,
            "author_id": author_id,
            "reply_message_id": reply_message_id,
            "members": members,
        })
        async with self._db() as db:
            await self._setup(db)
            await db.execute(
                "UPDATE notes SET undo_json = ? WHERE id = ?", (payload, note_id))
            await db.commit()

    async def attach_undo_reply(self, note_id: int, reply_message_id: int) -> None:
        """Дописать id реплики с кнопкой в уже сохранённый снапшот."""
        snap = await self.get_undo(note_id)
        if snap is None:
            return
        snap["reply_message_id"] = reply_message_id
        async with self._db() as db:
            await self._setup(db)
            await db.execute(
                "UPDATE notes SET undo_json = ? WHERE id = ?", (json.dumps(snap), note_id))
            await db.commit()

    async def get_undo(self, note_id: int) -> dict | None:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT undo_json FROM notes WHERE id = ?", (note_id,))
            row = await cur.fetchone()
            if not row or not row["undo_json"]:
                return None
            return json.loads(row["undo_json"])

    async def clear_undo(self, note_id: int) -> None:
        async with self._db() as db:
            await self._setup(db)
            await db.execute(
                "UPDATE notes SET undo_json = NULL WHERE id = ?", (note_id,))
            await db.commit()

    # ── Участники ─────────────────────────────────────────────────────────
    async def members(self, note_id: int) -> list[dict]:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT user_id, username, name_override, tg_name, note FROM note_members "
                "WHERE note_id = ? ORDER BY position, added_at, rowid",
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

    async def toggle_member(self, note_id: int, *, user_id: int, username: str | None,
                            name_override: str | None = None, tg_name: str | None = None) -> bool:
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
            pos = await self._next_position(db, note_id)
            await db.execute(
                "INSERT INTO note_members "
                "(note_id, user_id, username, name_override, tg_name, position) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (note_id, user_id, username, name_override, tg_name, pos))
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

    async def move_member(self, note_id: int, user_id: int, new_index: int) -> bool:
        """Переставить участника на 1-based позицию new_index; остальных сдвинуть.
        Порядок целиком перенумеровывается 1..N. False — участника нет в списке."""
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT user_id FROM note_members WHERE note_id = ? "
                "ORDER BY position, added_at, rowid", (note_id,))
            ids = [r["user_id"] for r in await cur.fetchall()]
            if user_id not in ids:
                return False
            ids.remove(user_id)
            idx = max(0, min(new_index - 1, len(ids)))
            ids.insert(idx, user_id)
            for i, uid in enumerate(ids, 1):
                await db.execute(
                    "UPDATE note_members SET position = ? WHERE note_id = ? AND user_id = ?",
                    (i, note_id, uid))
            await db.commit()
            return True

    async def swap_members(self, note_id: int, user_id_a: int, user_id_b: int) -> bool:
        """Поменять местами двух участников. Порядок перенумеровывается 1..N.
        False — кого-то из двоих нет в списке."""
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT user_id FROM note_members WHERE note_id = ? "
                "ORDER BY position, added_at, rowid", (note_id,))
            ids = [r["user_id"] for r in await cur.fetchall()]
            if user_id_a not in ids or user_id_b not in ids or user_id_a == user_id_b:
                return False
            i, j = ids.index(user_id_a), ids.index(user_id_b)
            ids[i], ids[j] = ids[j], ids[i]
            for k, uid in enumerate(ids, 1):
                await db.execute(
                    "UPDATE note_members SET position = ? WHERE note_id = ? AND user_id = ?",
                    (k, note_id, uid))
            await db.commit()
            return True

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
