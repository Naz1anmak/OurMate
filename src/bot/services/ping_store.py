"""SQLite-слой пинг-листа (aiosqlite). Источник правды. Образец — reminder_store."""
import aiosqlite

from src.config.settings import PING_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ping_members (
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    first_name TEXT,
    username   TEXT,
    joined_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(chat_id, user_id)
);
"""


class PingStore:
    def __init__(self, db_path: str = PING_DB_PATH) -> None:
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

    async def join(self, *, chat_id: int, user_id: int,
                   first_name: str | None, username: str | None) -> None:
        async with self._db() as db:
            await self._setup(db)
            await db.execute(
                "INSERT INTO ping_members (chat_id, user_id, first_name, username) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
                "first_name = excluded.first_name, username = excluded.username",
                (chat_id, user_id, first_name, username),
            )
            await db.commit()

    async def leave(self, chat_id: int, user_id: int) -> bool:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "DELETE FROM ping_members WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def count(self, chat_id: int) -> int:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT COUNT(*) AS n FROM ping_members WHERE chat_id = ?", (chat_id,)
            )
            row = await cur.fetchone()
            return int(row["n"])

    async def list_members(self, chat_id: int) -> list[dict]:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT user_id, first_name, username FROM ping_members "
                "WHERE chat_id = ? ORDER BY joined_at",
                (chat_id,),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def is_member(self, chat_id: int, user_id: int) -> bool:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT 1 FROM ping_members WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            return await cur.fetchone() is not None


ping_store = PingStore()
