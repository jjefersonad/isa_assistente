"""Play the reply through the ES8311 DAC as it arrives: the server streams PCM frames, the Speaker writes each one to I2S.

Half-duplex: the caller must stop the microphone (Mic.close) first, so the board does not hear itself.
"""
from machine import I2S, Pin

import es8311

_I2S_SCK, _I2S_WS, _I2S_DOUT = 5, 7, 8
_AMP_EN = 1  # active low: 0 enables the speaker amplifier
_REF_MIN = 6.0  # energy that counts as the loudest speech until something louder is heard (silence must not open the mouth)
_REF_DECAY = 0.97  # the reference forgets loud blocks slowly, so a quieter voice still moves the mouth
_PART = 2048  # bytes per mouth update (~46 ms): one 93 ms block is too coarse for the mouth to follow the syllables
_IBUF = 16384
_VOLUME = 80


def _energy(chunk):
    """Mean loudness (0..127) of 16-bit little-endian PCM. memoryview.cast does not exist in MicroPython, so read the
    high byte of every 8th sample (2's complement: bytes above 127 are negative): cheap and precise enough.
    The mean, not the peak: speech peaks near full scale in every block, which kept the mouth wide open."""
    total = n = 0
    for j in range(1, len(chunk), 16):
        h = chunk[j]
        total += 256 - h if h > 127 else h
        n += 1
    return total / n if n else 0


class Speaker:
    """I2S TX with the amplifier on only while open. write() blocks while the DMA buffer is full, which is what paces
    the network stream to the speed of the audio.

    `on_level(x)` is called after each frame with its loudness (0..1), to animate the mouth.
    """

    def __init__(self, codec, rate=None, on_level=None):
        self.codec = codec
        self.rate = rate or es8311.RATE
        self.on_level = on_level
        self.level = 0.0
        self.ref = _REF_MIN
        self.i2s = None
        self.amp = None

    def start(self):
        self.codec.volume(_VOLUME)
        self.amp = Pin(_AMP_EN, Pin.OUT, value=1)
        self.i2s = I2S(0, sck=Pin(_I2S_SCK), ws=Pin(_I2S_WS), sd=Pin(_I2S_DOUT),
                       mode=I2S.TX, bits=16, format=I2S.MONO, rate=self.rate, ibuf=_IBUF)
        self.amp(0)

    def write(self, frame):
        n = len(frame) // 2 * 2  # I2S wants whole 16-bit samples
        view = memoryview(frame)[:n]
        for i in range(0, n, _PART):
            part = view[i:i + _PART]
            self.i2s.write(part)
            if self.on_level:
                e = _energy(part)
                self.ref = max(_REF_MIN, self.ref * _REF_DECAY, e)
                self.level = 0.4 * self.level + 0.6 * min(1.0, e / self.ref)
                self.on_level(self.level)

    def stop(self):
        if not self.i2s:
            return
        try:
            self.i2s.write(bytes(_IBUF))  # silence, so the audio still queued in the DMA buffer is not cut by deinit()
        finally:
            self.i2s.deinit()
            self.i2s = None
            self.amp(1)
