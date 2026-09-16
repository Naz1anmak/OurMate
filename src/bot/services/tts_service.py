"""Синтез голосовых сообщений: текст → MiniMax t2a_v2 (mp3) → ffmpeg → OGG/Opus.

Модуль не знает про Telegram и LLM. OGG/Opus нужен, чтобы Telegram показал именно голосовое
(с waveform), а не аудиофайл; MiniMax такой формат не отдаёт.
"""
import asyncio
import logging
import ssl

import aiohttp
import certifi

from src.config.settings import (
    MINIMAX_API_BASE,
    MINIMAX_API_KEY,
    MINIMAX_TTS_MODEL,
    MINIMAX_VOICE_ID,
)

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SEC = 30
FFMPEG_TIMEOUT_SEC = 15


class TTSServiceError(Exception):
    """Ошибка синтеза голоса (сеть, API MiniMax или ffmpeg)."""


def is_voice_enabled() -> bool:
    """Голос включён, только когда заданы и ключ, и id клона."""
    return bool(MINIMAX_API_KEY and MINIMAX_VOICE_ID)


def parse_t2a_response(status: int, body: dict) -> bytes:
    """Достаёт mp3 из ответа t2a_v2. MiniMax отдаёт ошибки и при HTTP 200 — смотрим base_resp."""
    if status != 200:
        raise TTSServiceError(f"MiniMax t2a HTTP {status}: {str(body)[:300]}")
    base = body.get("base_resp") or {}
    trace_id = body.get("trace_id")
    if base.get("status_code") != 0:
        raise TTSServiceError(
            f"MiniMax t2a status_code={base.get('status_code')} {base.get('status_msg')} (trace_id={trace_id})")
    audio_hex = (body.get("data") or {}).get("audio")
    if not audio_hex:
        raise TTSServiceError(f"MiniMax t2a вернул пустое аудио (trace_id={trace_id})")
    try:
        return bytes.fromhex(audio_hex)
    except ValueError as exc:
        raise TTSServiceError(f"MiniMax t2a: битый hex аудио (trace_id={trace_id})") from exc


async def _request_t2a(text: str) -> tuple[int, dict]:
    payload = {
        "model": MINIMAX_TTS_MODEL,
        "text": text,
        "stream": False,
        "language_boost": "Russian",
        "output_format": "hex",
        "voice_setting": {"voice_id": MINIMAX_VOICE_ID, "speed": 1, "vol": 1, "pitch": 0},
        "audio_setting": {"format": "mp3", "sample_rate": 32000, "bitrate": 128000, "channel": 1},
    }
    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.post(f"{MINIMAX_API_BASE}/v1/t2a_v2", headers=headers, json=payload) as resp:
                try:
                    body = await resp.json(content_type=None)
                except ValueError:
                    body = {"raw": (await resp.text())[:300]}
                return resp.status, body
    except aiohttp.ClientError as exc:
        raise TTSServiceError(f"MiniMax t2a сетевая ошибка: {exc}") from exc
    except asyncio.TimeoutError as exc:
        raise TTSServiceError("MiniMax t2a таймаут") from exc


async def mp3_to_ogg(mp3: bytes) -> bytes:
    """mp3 → OGG/Opus моно через ffmpeg в пайпах, без временных файлов."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0", "-c:a", "libopus", "-b:a", "48k", "-ac", "1", "-f", "ogg", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(mp3), timeout=FFMPEG_TIMEOUT_SEC)
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise TTSServiceError("ffmpeg таймаут") from exc
    if proc.returncode != 0 or not out:
        raise TTSServiceError(f"ffmpeg код {proc.returncode}: {err.decode(errors='replace')[:300]}")
    return out


async def synthesize_voice(text: str) -> bytes:
    """Текст → готовые байты OGG/Opus для sendVoice."""
    status, body = await _request_t2a(text)
    mp3 = parse_t2a_response(status, body)
    return await mp3_to_ogg(mp3)
