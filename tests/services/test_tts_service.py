import shutil
import subprocess

import pytest

import src.bot.services.tts_service as tts
from src.bot.services.tts_service import TTSServiceError, parse_t2a_response


def _ok_body(hex_audio="494433"):
    return {"data": {"audio": hex_audio, "status": 2},
            "trace_id": "t1", "base_resp": {"status_code": 0, "status_msg": "success"}}


def test_parse_ok_returns_bytes():
    assert parse_t2a_response(200, _ok_body("494433")) == b"ID3"


def test_parse_http_error():
    with pytest.raises(TTSServiceError, match="HTTP 500"):
        parse_t2a_response(500, {})


def test_parse_status_code_nonzero_on_http_200():
    body = {"data": None, "trace_id": "t2",
            "base_resp": {"status_code": 1004, "status_msg": "auth failed"}}
    with pytest.raises(TTSServiceError, match="1004.*auth failed"):
        parse_t2a_response(200, body)


def test_parse_data_null():
    body = {"data": None, "trace_id": "t3", "base_resp": {"status_code": 0, "status_msg": "success"}}
    with pytest.raises(TTSServiceError, match="пустое аудио"):
        parse_t2a_response(200, body)


def test_parse_bad_hex():
    with pytest.raises(TTSServiceError, match="hex"):
        parse_t2a_response(200, _ok_body("zz"))


def test_is_voice_enabled(monkeypatch):
    monkeypatch.setattr(tts, "MINIMAX_API_KEY", "k")
    monkeypatch.setattr(tts, "MINIMAX_VOICE_ID", None)
    assert tts.is_voice_enabled() is False
    monkeypatch.setattr(tts, "MINIMAX_VOICE_ID", "v")
    assert tts.is_voice_enabled() is True


async def test_synthesize_voice_composes(monkeypatch):
    async def fake_request(text):
        assert text == "привет"
        return 200, _ok_body("494433")

    async def fake_convert(mp3):
        assert mp3 == b"ID3"
        return b"OggS"

    monkeypatch.setattr(tts, "_request_t2a", fake_request)
    monkeypatch.setattr(tts, "mp3_to_ogg", fake_convert)
    assert await tts.synthesize_voice("привет") == b"OggS"


async def test_mp3_to_ogg_timeout_waits_after_kill(monkeypatch):
    calls = []

    class FakeProc:
        def kill(self):
            calls.append("kill")

        async def wait(self):
            calls.append("wait")

        async def communicate(self, data):
            raise tts.asyncio.TimeoutError()

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(tts.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(TTSServiceError, match="таймаут"):
        await tts.mp3_to_ogg(b"ID3")
    assert calls == ["kill", "wait"]


async def test_mp3_to_ogg_nonzero_exit(monkeypatch):
    class FakeProc:
        returncode = 1
        async def communicate(self, data):
            return b"", b"boom"

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(tts.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(TTSServiceError, match="ffmpeg"):
        await tts.mp3_to_ogg(b"ID3")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg нет в окружении")
async def test_mp3_to_ogg_real_ffmpeg():
    mp3 = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=1", "-f", "mp3", "pipe:1"],
        capture_output=True, check=True).stdout
    ogg = await tts.mp3_to_ogg(mp3)
    assert ogg[:4] == b"OggS"


def test_prepare_speech_text_turns_dash_into_pause():
    assert tts.prepare_speech_text("Дела как у всех в сентябре — в аудитории") == \
        "Дела как у всех в сентябре <#0.3#> в аудитории"
    assert tts.prepare_speech_text("имя-отчество") == "имя-отчество"
