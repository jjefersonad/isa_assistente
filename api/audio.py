import io
import wave

import numpy as np


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Linear-interpolation resampler, good enough for speech.

    Going down (44.1 kHz Supertonic -> 22.05 kHz board), a short windowed-sinc low-pass first: plain interpolation
    folds everything above the new Nyquist back into the audible band, which sounds harsh on "s" and "ch".
    """
    if src == dst or len(x) == 0:
        return x
    if dst < src:
        cutoff = 0.45 * dst / src  # cycles per input sample, a little under the new Nyquist
        t = np.arange(-32, 33)
        h = 2 * cutoff * np.sinc(2 * cutoff * t) * np.hamming(len(t))
        x = np.convolve(x, (h / h.sum()).astype(x.dtype), mode="same")
    n = int(len(x) * dst / src)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(x.dtype)


def decode(body: bytes, sample_rate: int) -> np.ndarray:
    """WAV (RIFF header) or raw 16-bit mono PCM at `sample_rate` -> float32 mono at 16 kHz."""
    if body[:4] == b"RIFF":
        with wave.open(io.BytesIO(body)) as w:
            if w.getsampwidth() != 2:
                raise ValueError("somente WAV de 16 bits")
            sample_rate, channels = w.getframerate(), w.getnchannels()
            pcm = w.readframes(w.getnframes())
        x = pcm16_to_float(pcm)
        if channels > 1:
            x = x.reshape(-1, channels).mean(axis=1)
    else:
        x = pcm16_to_float(body)
    return resample(x, sample_rate, 16000)


def encode_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()
