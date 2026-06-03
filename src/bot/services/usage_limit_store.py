"""SQLite-слой дневных счётчиков обращений (aiosqlite). Источник правды для лимитов и #10."""
import aiosqlite

from src.config.settings import USAGE_DB_PATH, USAGE_RETENTION_DAYS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_counters (
    scope TEXT    NOT NULL,   -- 'pm_user' | 'chat'
    key   INTEGER NOT NULL,   -- user_id (ЛС) | chat_id (группа)
    day   TEXT    NOT NULL,   -- 'YYYY-MM-DD' по МСК
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (scope, key, day)
);
"""


class UsageLimitStore:
    def __init__(self, db_path: str = USAGE_DB_PATH) -> None:
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

    async def get(self, scope: str, key: int, day: str) -> int:
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "SELECT count FROM usage_counters WHERE scope = ? AND key = ? AND day = ?",
                (scope, key, day))
            row = await cur.fetchone()
            return row["count"] if row else 0

    async def increment(self, scope: str, key: int, day: str) -> int:
        """Атомарный UPSERT +1. Возвращает новое значение счётчика."""
        async with self._db() as db:
            await self._setup(db)
            await db.execute(
                "INSERT INTO usage_counters (scope, key, day, count) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(scope, key, day) DO UPDATE SET count = count + 1",
                (scope, key, day))
            await db.commit()
            cur = await db.execute(
                "SELECT count FROM usage_counters WHERE scope = ? AND key = ? AND day = ?",
                (scope, key, day))
            row = await cur.fetchone()
            return row["count"]

    async def cleanup_old(self, *, days: int = USAGE_RETENTION_DAYS) -> int:
        """Удаляет строки старше N дней (по date('now')). Возвращает число удалённых."""
        async with self._db() as db:
            await self._setup(db)
            cur = await db.execute(
                "DELETE FROM usage_counters WHERE day < date('now', ?)",
                (f"-{days} days",))
            await db.commit()
            return cur.rowcount


# Singleton (как reminder_store / schedule_service)
usage_limit_store = UsageLimitStore()
