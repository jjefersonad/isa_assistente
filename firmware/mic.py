"""Push-to-talk capture through the ES8311 microphone (I2S RX, mono, 16-bit at es8311.RATE)."""
import time
from machine import I2C, I2S, Pin

import es8311

RATE = es8311.RATE
CHUNK = 4096  # bytes per read (~93 ms at RATE)
WARMUP = 2    # frames dropped after opening the bus, before the ADC settles

_I2C_SCL, _I2C_SDA = 15, 16
_I2S_SCK, _I2S_WS, _I2S_DIN = 5, 7, 6
_AMP_EN = 1   # active low: keep the speaker amp off while recording
_BOOT = 0


class Mic:
    def __init__(self, amp_en=_AMP_EN):
        i2c = I2C(0, scl=Pin(_I2C_SCL), sda=Pin(_I2C_SDA), freq=400000)
        self.codec = es8311.ES8311(i2c)
        self.codec.init()
        self.amp = Pin(amp_en, Pin.OUT, value=1)
        self.i2s = None

    def _open(self):
        """Open the I2S bus, returning True only on the first call (when a warm-up is needed)."""
        if self.i2s is not None:
            return False
        self.amp(1)
        self.i2s = I2S(0, sck=Pin(_I2S_SCK), ws=Pin(_I2S_WS), sd=Pin(_I2S_DIN),
                       mode=I2S.RX, bits=16, format=I2S.MONO, rate=RATE, ibuf=8192)
        return True

    def close(self):
        if self.i2s:
            self.i2s.deinit()
            self.i2s = None

    def _read(self):
        buf = bytearray(CHUNK)
        self.i2s.readinto(buf)
        return buf

    def record(self, held, max_s=15):
        """Record while `held()` is true, up to max_s. Returns bytes of 16-bit mono PCM at RATE."""
        if self._open():
            for _ in range(WARMUP):
                self._read()
        chunks = []
        deadline = time.ticks_add(time.ticks_ms(), max_s * 1000)
        while held() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            chunks.append(self._read())
        return b"".join(chunks)

    def stream(self, held, send, max_s=15):
        """Like record(), but hands every chunk to `send(chunk)` as it is captured instead of keeping it, so the audio
        is already on its way to the server when the button is released. Returns the number of bytes sent."""
        if self._open():
            for _ in range(WARMUP):
                self._read()
        total = 0
        deadline = time.ticks_add(time.ticks_ms(), max_s * 1000)
        while held() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            chunk = self._read()
            send(chunk)
            total += len(chunk)
        return total

    def record_for(self, seconds):
        """Record a fixed duration (used by tests, no button)."""
        end = time.ticks_add(time.ticks_ms(), seconds * 1000)
        return self.record(lambda: time.ticks_diff(end, time.ticks_ms()) > 0, max_s=seconds)


def boot_button():
    return Pin(_BOOT, Pin.IN, Pin.PULL_UP)
