"""WebSocket server for the board. One turn, streamed end to end:

board -> server   {"type":"audio_start","rate":22050,"tts_rate":22050}, binary PCM frames while the button is held,
                  {"type":"audio_end"}   (or {"type":"audio_cancel"}; or {"text": "..."} to skip the STT)
server -> board   {"type":"stt","text"}, {"type":"emotion","emotion"}, {"type":"sentence","text"}, binary PCM frames
                  (the spoken reply, one sentence after another) and finally {"type":"done"} (or {"type":"error"}).

The LLM is streamed; each finished sentence goes to TTS at once, and the next sentences are synthesized while the
current one is still being sent, so the voice starts after the first sentence instead of after the whole reply.
"""
import asyncio
import json
import logging
import os

import websockets
from dotenv import load_dotenv

load_dotenv()

from agent import build_agent  # noqa: E402
from speech import SpeechClient  # noqa: E402
from streaming import ReplySplitter  # noqa: E402

log = logging.getLogger("server")
MAX_AUDIO = 22050 * 2 * 20  # bytes: never buffer more than ~20 s of speech from a board


def chunk_text(chunk) -> str:
    """Text of an AIMessageChunk (a plain string, or a list of content blocks); tool-call pieces have none."""
    content = chunk.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


async def llm_pieces(agent, history):
    """Yield the text of the agent's reply as the model writes it."""
    from langchain_core.messages import AIMessageChunk

    async for chunk, _meta in agent.astream({"messages": history}, stream_mode="messages"):
        if isinstance(chunk, AIMessageChunk):
            text = chunk_text(chunk)
            if text:
                yield text


class SentenceAudio:
    """Synthesizes one sentence in the background, so it is ready (or nearly) when the previous one finishes playing."""

    def __init__(self, speech, text, rate):
        self.frames: asyncio.Queue = asyncio.Queue()
        self.task = asyncio.create_task(self._run(speech, text, rate))

    async def _run(self, speech, text, rate):
        try:
            async for frame in speech.synth(text, rate):
                self.frames.put_nowait(frame)
        except Exception as e:  # reported to the board by whoever drains the queue
            self.frames.put_nowait(e)
        finally:
            self.frames.put_nowait(None)

    async def drain(self):
        while (item := await self.frames.get()) is not None:
            if isinstance(item, Exception):
                raise item
            yield item


async def run_turn(ws, agent, speech, history, text, tts_rate):
    """Answer `text`: stream the LLM, send the emotion at once, then speak sentence by sentence (if tts_rate)."""
    history.append({"role": "user", "content": text})
    queue: asyncio.Queue = asyncio.Queue()
    reply: list[str] = []

    async def produce():
        splitter = ReplySplitter()
        try:
            async for piece in llm_pieces(agent, history):
                reply.append(piece)
                for kind, value in splitter.feed(piece):
                    await handle(kind, value)
            for kind, value in splitter.finish():
                await handle(kind, value)
        finally:
            await queue.put(None)

    async def handle(kind, value):
        if kind == "emotion":
            await ws.send(json.dumps({"type": "emotion", "emotion": value}))
        else:
            await ws.send(json.dumps({"type": "sentence", "text": value}))
            if tts_rate:
                await queue.put(SentenceAudio(speech, value, tts_rate))

    async def send_audio():
        while (item := await queue.get()) is not None:
            async for frame in item.drain():
                await ws.send(frame)

    producer = asyncio.create_task(produce())
    try:
        await send_audio()
        await producer
    finally:
        producer.cancel()
    # keep the raw reply (with its tags) in the history so the model keeps using the tags
    history.append({"role": "assistant", "content": "".join(reply)})


async def handle_turn(ws, agent, speech, history, text, tts_rate):
    try:
        await run_turn(ws, agent, speech, history, text, tts_rate)
    except websockets.ConnectionClosed:
        raise
    except Exception as e:
        log.exception("turno falhou")
        if history and history[-1]["role"] == "user":
            history.pop()
        await ws.send(json.dumps({"type": "error", "message": str(e)[:200]}))
    await ws.send(json.dumps({"type": "done"}))


async def main():
    logging.basicConfig(level=logging.INFO)
    agent = build_agent()
    speech = SpeechClient()

    async def handler(ws):
        history = []  # per-connection history so the agent keeps the conversation context
        pcm, rate, tts_rate = bytearray(), 22050, 22050
        async for raw in ws:
            if isinstance(raw, bytes):
                if len(pcm) + len(raw) <= MAX_AUDIO:
                    pcm += raw
                continue
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "audio_start":
                pcm.clear()
                rate, tts_rate = int(msg.get("rate", 22050)), int(msg.get("tts_rate", 22050))
            elif kind == "audio_cancel":
                pcm.clear()
            elif kind == "audio_end":
                audio = bytes(pcm)
                pcm.clear()
                try:
                    text = await speech.transcribe(audio, rate) if audio else ""
                except Exception as e:
                    log.warning("STT falhou: %s", e)
                    await ws.send(json.dumps({"type": "error", "message": "stt: " + str(e)[:150]}))
                    await ws.send(json.dumps({"type": "done"}))
                    continue
                await ws.send(json.dumps({"type": "stt", "text": text}))
                if text:
                    await handle_turn(ws, agent, speech, history, text, tts_rate)
                else:
                    await ws.send(json.dumps({"type": "done"}))
            elif "text" in msg:  # text in, no STT; audio back only if the client asks for it (tts_rate)
                await handle_turn(ws, agent, speech, history, msg["text"], int(msg.get("tts_rate", 0)))

    async with websockets.serve(handler, os.getenv("HOST", "0.0.0.0"), int(os.getenv("PORT", 8765)),
                                   ping_interval=None, max_size=2**20):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
