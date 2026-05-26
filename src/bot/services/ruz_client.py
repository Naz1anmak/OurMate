"""HTTP-клиент к JSON-API RUZ СПбПУ."""
import logging
from datetime import date

import aiohttp

logger = logging.getLogger(__name__)


class RuzError(Exception):
    """Ошибка обращения к RUZ (сеть, 5xx, невалидный JSON)."""


class RuzClient:
    def __init__(self, base_url: str, faculty_id: int, timeout: int):
        self.base_url = base_url.rstrip("/")
        self.faculty_id = faculty_id
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def fetch_week(self, group_id: int, monday: date) -> list[dict]:
        """Возвращает плоский список lessons за неделю с подмешанным __date."""
        url = f"{self.base_url}/api/v1/ruz/scheduler/{group_id}?date={monday:%Y-%m-%d}"

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status >= 500:
                            raise RuzError(f"HTTP {resp.status} от RUZ")
                        if resp.status != 200:
                            raise RuzError(f"HTTP {resp.status} от RUZ (без retry)")
                        data = await resp.json()
                        return self._flatten(data)
            except RuzError as exc:
                last_exc = exc
                if attempt == 0:
                    logger.warning("RUZ %s упал (попытка %s): %s, повторяю", url, attempt + 1, exc)
                    continue
                raise
            except (aiohttp.ClientError, TimeoutError) as exc:
                last_exc = RuzError(f"сеть: {exc}")
                if attempt == 0:
                    logger.warning("RUZ %s сеть (попытка %s): %s, повторяю", url, attempt + 1, exc)
                    continue
                raise last_exc
        raise last_exc or RuzError("неизвестная ошибка")

    @staticmethod
    def _flatten(data: dict) -> list[dict]:
        out: list[dict] = []
        for day in data.get("days", []):
            day_date = day.get("date")
            for lesson in day.get("lessons", []):
                lesson_with_date = dict(lesson)
                lesson_with_date["__date"] = day_date
                out.append(lesson_with_date)
        return out

    def public_url(self, group_id: int, monday: date) -> str:
        """Frontend URL для гиперссылки в сообщениях об ошибке."""
        # Без zero-padding в дате, как в реальной ссылке RUZ
        d = f"{monday.year}-{monday.month}-{monday.day}"
        return f"{self.base_url}/faculty/{self.faculty_id}/groups/{group_id}?date={d}"
