"""Speech API: POST /stt (audio -> text, local Whisper) and POST /tts, /tts/stream (text -> audio).

TTS backends, tried in this order until one works (TTS_BACKEND=auto):
  eleven      ElevenLabs (cloud, most natural; needs key + voice id, monthly credits)
  supertonic  Supertonic 3 (local ONNX, ~99M params, natural female voices; CPU, or GPU with onnxruntime-gpu)
  piper       Piper (local, robotic but always available)
Whisper and Supertonic use the GPU when there is one (DEVICE=auto) and the CPU otherwise.
"""
import itertools
import logging
import os
import threading
import time
import wave
from contextlib import asynccontextmanager

import audio
import httpx
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from faster_whisper import WhisperModel
from piper import PiperVoice
from pydantic import BaseModel, Field

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("speech")
models = {}

DEVICE = os.getenv("DEVICE", "auto")  # auto | cpu | cuda

# Optional ElevenLabs backend. Needs both the key and a voice id.
ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "")
ELEVEN_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ELEVEN_BASE_URL = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io").rstrip("/")
ELEVEN_RATES = (16000, 22050, 24000)  # raw PCM rates available on every plan (44.1 kHz needs Pro)
# Out of credits (401 quota_exceeded), no plan (402) or rate limited (429): skip ElevenLabs for a while instead of
# paying a failed round trip (~0.5 s) on every sentence of every reply.
ELEVEN_COOLDOWN = float(os.getenv("ELEVENLABS_COOLDOWN_S", "600"))
_eleven_off_until = 0.0

SUPERTONIC_VOICE = os.getenv("SUPERTONIC_VOICE", "F1")  # F1-F5 female, M1-M5 male; empty disables the backend
SUPERTONIC_SPEED = float(os.getenv("SUPERTONIC_SPEED", "1.05"))
SUPERTONIC_STEPS = int(os.getenv("SUPERTONIC_STEPS", "8"))  # more steps: a bit better, slower
_supertonic_lock = threading.Lock()  # one ONNX run at a time: concurrent runs only fight for the same cores

BACKENDS = ("eleven", "supertonic", "piper")


def _onnx_providers() -> list[str]:
    import onnxruntime as ort

    if hasattr(ort, "preload_dlls"):  # onnxruntime-gpu[cuda,cudnn]: load the CUDA libraries installed by pip
        try:
            ort.preload_dlls()
        except Exception as e:  # no GPU libraries: the CPU is used
            log.info("preload_dlls: %s", e)
    available = ort.get_available_providers()
    wanted = ["CUDAExecutionProvider", "CPUExecutionProvider"] if DEVICE != "cpu" else ["CPUExecutionProvider"]
    return [p for p in wanted if p in available] or ["CPUExecutionProvider"]


def _load_supertonic():
    import supertonic.loader
    from supertonic import TTS

    # The package hard-codes the CPU provider; this is its only switch. It keeps the ones onnxruntime really has.
    supertonic.loader.DEFAULT_ONNX_PROVIDERS = _onnx_providers()
    t = TTS(model="supertonic-3", auto_download=True)
    return t, t.get_voice_style(voice_name=SUPERTONIC_VOICE)


@asynccontextmanager
async def lifespan(_: FastAPI):
    models["stt"] = WhisperModel(
        os.getenv("WHISPER_MODEL", "small"),
        device=DEVICE,
        compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
    )
    log.info("whisper em %s", models["stt"].model.device)
    models["tts"] = PiperVoice.load(os.getenv("PIPER_VOICE", "models/pt_BR-faber-medium.onnx"))
    if SUPERTONIC_VOICE:
        try:
            models["supertonic"] = _load_supertonic()
            log.info("supertonic voz %s, providers %s", SUPERTONIC_VOICE,
                     models["supertonic"][0].model.dp_ort.get_providers())
        except Exception:
            log.exception("supertonic indisponível; seguindo sem ele")
    yield
    models.clear()


app = FastAPI(title="Speech API", lifespan=lifespan)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    sample_rate: int | None = Field(None, ge=8000, le=48000, description="default: voice native rate")
    format: str = Field("wav", pattern="^(wav|pcm)$", description="pcm = raw 16-bit mono little-endian")
    backend: str | None = Field(None, pattern="^(eleven|supertonic|piper)$",
                                 description="default: env TTS_BACKEND (auto = the first that works)")


class TTSStreamRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    sample_rate: int = Field(22050, ge=8000, le=48000)
    backend: str | None = Field(None, pattern="^(eleven|supertonic|piper)$")


@app.get("/health")
def health():
    return {"status": "ok", "tts": _chain(None)}


# Inference is CPU-bound: /tts is a plain `def` (FastAPI runs it in a thread pool) and /stt hands the work to the pool
# explicitly, because it must be `async` to read the raw request body.
@app.post("/stt")
async def stt(request: Request, sample_rate: int = Query(16000, ge=8000, le=48000)):
    """Body: WAV file, or raw 16-bit mono PCM at `sample_rate`. Returns {"text": ...}."""
    body = await request.body()
    if not body:
        raise HTTPException(400, "corpo vazio")
    try:
        samples = audio.decode(body, sample_rate)
    except (ValueError, EOFError, wave.Error) as e:
        raise HTTPException(400, f"áudio inválido: {e}")
    return await run_in_threadpool(_transcribe, samples)


def _transcribe(samples: np.ndarray):
    segments, info = models["stt"].transcribe(
        samples, language=os.getenv("WHISPER_LANGUAGE", "pt"), vad_filter=True, beam_size=1
    )
    return {"text": " ".join(s.text.strip() for s in segments).strip(), "duration": round(info.duration, 2)}


# ---- backend chain ------------------------------------------------------------------------------------------------
def _configured(backend: str) -> bool:
    if backend == "eleven":
        return bool(ELEVEN_KEY and ELEVEN_VOICE) and time.monotonic() >= _eleven_off_until
    if backend == "supertonic":
        return "supertonic" in models
    return backend == "piper"


def _chain(requested: str | None) -> list[str]:
    """Backends to try in order. An explicit one is tried first, then the rest of the chain as fallback."""
    wanted = requested or os.getenv("TTS_BACKEND", "auto")
    order = BACKENDS if wanted == "auto" else (wanted,) + tuple(b for b in BACKENDS if b != wanted)
    return [b for b in order if _configured(b)]


def _failed(backend: str, e: Exception):
    global _eleven_off_until
    # httpx puts the status line (e.g. 401/402/429) in the message; request headers (the API key) are not included
    log.warning("%s TTS falhou (%s)", backend, e)
    if backend == "eleven" and isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 402, 429):
        _eleven_off_until = time.monotonic() + ELEVEN_COOLDOWN
        log.warning("ElevenLabs desligado por %.0f s (sem créditos ou limite)", ELEVEN_COOLDOWN)


def _to_pcm(x: np.ndarray) -> bytes:
    return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


# ---- Piper ----------------------------------------------------------------------------------------------------------
def _synth_piper(text: str) -> tuple[np.ndarray, int]:
    voice = models["tts"]
    chunks = list(voice.synthesize(text))
    if not chunks:
        return np.zeros(0, np.float32), voice.config.sample_rate
    return np.concatenate([c.audio_float_array for c in chunks]), chunks[0].sample_rate


def _piper_stream(text: str, rate: int):
    """One block of PCM per sentence Piper finishes, so the first sentence leaves before the rest is synthesized."""
    for c in models["tts"].synthesize(text):
        yield _to_pcm(audio.resample(c.audio_float_array, c.sample_rate, rate))


# ---- Supertonic -----------------------------------------------------------------------------------------------------
def _supertonic_text(t, text: str) -> str:
    """The model rejects the whole text if any character is unknown to it (emoji, some symbols): blank those out."""
    ok, bad = t.model.text_processor.validate_text(text)
    return text if ok else "".join(" " if c in bad else c for c in text)


def _synth_supertonic(text: str) -> tuple[np.ndarray, int]:
    t, style = models["supertonic"]
    with _supertonic_lock:
        wav, _ = t.synthesize(_supertonic_text(t, text), voice_style=style, lang="pt",
                              total_steps=SUPERTONIC_STEPS, speed=SUPERTONIC_SPEED)
    return np.asarray(wav, np.float32).reshape(-1), t.sample_rate


def _supertonic_stream(text: str, rate: int):
    # the server already sends one sentence per request, so a whole-text synthesis is a sentence (~0.2-0.5 s on CPU)
    x, src = _synth_supertonic(text)
    yield _to_pcm(audio.resample(x, src, rate))


# ---- ElevenLabs ---------------------------------------------------------------------------------------------------
def _synth_eleven(text: str, want_rate: int | None) -> tuple[np.ndarray, int]:
    """ElevenLabs text-to-speech, raw 16-bit PCM at the available rate closest above `want_rate`."""
    rate = next((r for r in ELEVEN_RATES if r >= (want_rate or 0)), ELEVEN_RATES[-1])
    r = httpx.post(
        f"{ELEVEN_BASE_URL}/v1/text-to-speech/{ELEVEN_VOICE}",
        params={"output_format": f"pcm_{rate}"},
        headers={"xi-api-key": ELEVEN_KEY},
        json={"text": text, "model_id": ELEVEN_MODEL},
        timeout=30,
    )
    r.raise_for_status()
    return audio.pcm16_to_float(r.content), rate


def _eleven_stream(text: str, rate: int):
    """ElevenLabs streaming endpoint: PCM arrives while it is still being generated."""
    src = next((r for r in ELEVEN_RATES if r >= rate), ELEVEN_RATES[-1])
    with httpx.stream(
        "POST", f"{ELEVEN_BASE_URL}/v1/text-to-speech/{ELEVEN_VOICE}/stream",
        params={"output_format": f"pcm_{src}"}, headers={"xi-api-key": ELEVEN_KEY},
        json={"text": text, "model_id": ELEVEN_MODEL}, timeout=30,
    ) as r:
        r.raise_for_status()
        carry = b""
        for chunk in r.iter_bytes(4096):
            chunk = carry + chunk
            carry = chunk[len(chunk) // 2 * 2:]  # a 16-bit sample may be split across network chunks
            chunk = chunk[:len(chunk) // 2 * 2]
            if chunk:
                yield chunk if src == rate else _to_pcm(audio.resample(audio.pcm16_to_float(chunk), src, rate))


_SYNTH = {"eleven": lambda text, rate: _synth_eleven(text, rate), "supertonic": lambda text, rate: _synth_supertonic(text),
          "piper": lambda text, rate: _synth_piper(text)}
_STREAM = {"eleven": _eleven_stream, "supertonic": _supertonic_stream, "piper": _piper_stream}
_ERRORS = (httpx.HTTPError, OSError, wave.Error, ValueError, RuntimeError)


@app.post("/tts")
def tts(req: TTSRequest):
    chain = _chain(req.backend)
    if not chain:
        raise HTTPException(400, "nenhum backend de TTS configurado")
    for used in chain:
        try:
            x, src = _SYNTH[used](req.text, req.sample_rate)
            break
        except _ERRORS as e:
            _failed(used, e)
    else:
        raise HTTPException(502, "todos os backends de TTS falharam")
    rate = req.sample_rate or src
    pcm = _to_pcm(audio.resample(x, src, rate))
    headers = {"X-TTS-Backend": used, "X-Sample-Rate": str(rate)}
    if req.format == "pcm":
        return Response(pcm, media_type="application/octet-stream", headers=headers)
    return Response(audio.encode_wav(pcm, rate), media_type="audio/wav", headers=headers)


@app.post("/tts/stream")
def tts_stream(req: TTSStreamRequest):
    """Raw 16-bit mono little-endian PCM at `sample_rate`, sent as it is produced (chunked, no Content-Length)."""
    chain = _chain(req.backend)
    if not chain:
        raise HTTPException(400, "nenhum backend de TTS configurado")
    for used in chain:
        try:
            gen = _STREAM[used](req.text, req.sample_rate)
            # pull the first block now: a failure must fall back to the next backend, not cut the audio
            stream = itertools.chain([next(gen)], gen)
            break
        except StopIteration:
            stream = iter(())
            break
        except _ERRORS as e:
            _failed(used, e)
    else:
        raise HTTPException(502, "todos os backends de TTS falharam")
    return StreamingResponse(stream, media_type="application/octet-stream",
                             headers={"X-TTS-Backend": used, "X-Sample-Rate": str(req.sample_rate)})
