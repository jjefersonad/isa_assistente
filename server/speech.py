"""Client for the speech API (api/): STT for the audio the board streams up, streaming TTS for the way back."""
import os
from collections.abc import AsyncIterator

import httpx

FRAME = 4096  # bytes of PCM per WebSocket frame to the board (~93 ms at 22050 Hz): one mouth movement per frame


class SpeechClient:
    def __init__(self, base_url=None):
        base = (base_url or os.getenv("SPEECH_URL") or "http://localhost:8800").rstrip("/")
        self.http = httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(60, connect=5))

    async def transcribe(self, pcm: bytes, rate: int) -> str:
        r = await self.http.post("/stt", params={"sample_rate": rate}, content=pcm,
                                 headers={"Content-Type": "application/octet-stream"})
        r.raise_for_status()
        return r.json().get("text", "").strip()

    async def synth(self, text: str, rate: int) -> AsyncIterator[bytes]:
        """PCM for `text` in FRAME-sized pieces, as the API produces it."""
        pending = bytearray()
        async with self.http.stream("POST", "/tts/stream", json={"text": text, "sample_rate": rate}) as r:
            if r.status_code != 200:
                await r.aread()
                raise httpx.HTTPStatusError(f"TTS {r.status_code}: {r.text[:120]}", request=r.request, response=r)
            async for chunk in r.aiter_bytes():
                pending += chunk
                while len(pending) >= FRAME:
                    yield bytes(pending[:FRAME])
                    del pending[:FRAME]
        if len(pending) > 1:
            yield bytes(pending[:len(pending) // 2 * 2])

    async def aclose(self):
        await self.http.aclose()
