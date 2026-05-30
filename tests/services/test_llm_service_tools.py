import pytest
from src.bot.services.llm_service import accumulate_tool_calls

def test_accumulate_tool_calls_across_deltas():
    acc = {}
    # дельты приходят фрагментами: имя в первой, аргументы по кускам
    accumulate_tool_calls(acc, [{"index": 0, "id": "tc1", "type": "function",
                                 "function": {"name": "get_schedule", "arguments": '{"date_from":"2026-'}}])
    accumulate_tool_calls(acc, [{"index": 0, "function": {"arguments": '06-01","date_to":"2026-06-01"}'}}])
    calls = [acc[i] for i in sorted(acc)]
    assert calls[0]["id"] == "tc1"
    assert calls[0]["function"]["name"] == "get_schedule"
    assert calls[0]["function"]["arguments"] == '{"date_from":"2026-06-01","date_to":"2026-06-01"}'
