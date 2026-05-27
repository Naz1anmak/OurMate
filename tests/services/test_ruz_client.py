import json
from datetime import date
from pathlib import Path

import pytest
from aioresponses import aioresponses

from src.bot.services.ruz_client import RuzClient, RuzError

FIXTURE = json.loads((Path(__file__).parent.parent / "fixtures" / "ruz_week_sample.json").read_text())


@pytest.mark.asyncio
async def test_fetch_week_returns_flat_list_of_lessons_with_day_date():
    client = RuzClient(base_url="https://ruz.example", faculty_id=125, timeout=5)
    with aioresponses() as m:
        m.get("https://ruz.example/api/v1/ruz/scheduler/99000?date=2026-05-25", payload=FIXTURE)
        lessons = await client.fetch_week(99000, date(2026, 5, 25))
    assert len(lessons) == 2
    assert lessons[0]["subject"] == "Subject A"
    assert lessons[0]["__date"] == "2026-05-26"  # подмешиваем day.date


@pytest.mark.asyncio
async def test_fetch_week_raises_on_500():
    client = RuzClient(base_url="https://ruz.example", faculty_id=125, timeout=5)
    with aioresponses() as m:
        # Один retry → нужны два ответа
        m.get("https://ruz.example/api/v1/ruz/scheduler/99000?date=2026-05-25", status=500)
        m.get("https://ruz.example/api/v1/ruz/scheduler/99000?date=2026-05-25", status=500)
        with pytest.raises(RuzError):
            await client.fetch_week(99000, date(2026, 5, 25))


@pytest.mark.asyncio
async def test_fetch_week_retries_once_on_500_then_succeeds():
    client = RuzClient(base_url="https://ruz.example", faculty_id=125, timeout=5)
    with aioresponses() as m:
        m.get("https://ruz.example/api/v1/ruz/scheduler/99000?date=2026-05-25", status=500)
        m.get("https://ruz.example/api/v1/ruz/scheduler/99000?date=2026-05-25", payload=FIXTURE)
        lessons = await client.fetch_week(99000, date(2026, 5, 25))
    assert len(lessons) == 2


def test_public_url_format():
    client = RuzClient(base_url="https://ruz.example", faculty_id=125, timeout=5)
    url = client.public_url(99000, date(2026, 5, 25))
    # Без zero-padding в дате, как в реальном RUZ
    assert url == "https://ruz.example/faculty/125/groups/99000?date=2026-5-25"
