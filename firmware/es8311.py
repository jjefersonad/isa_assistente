"""ES8311 codec over I2C. The ESP32-S3 is the I2S master; the codec takes its clock from BCLK,
since MicroPython's machine.I2S has no MCLK output on this port."""
import time

ADDR = 0x18
RATE = 22050  # BCLK = 22050 * 16 * 2 = 705600 Hz, a rate present in the ES8311 clock table

# Clock dividers for RATE (16-bit), from the ES8311 coefficient table (mclk 705600, rate 22050).
_PRE_DIV, _PRE_MULTI = 0x01, 0x03
_ADC_DIV, _DAC_DIV = 0x01, 0x01
_FS_MODE = 0x00
_LRCK_H, _LRCK_L = 0x00, 0xFF
_BCLK_DIV = 0x04
_ADC_OSR, _DAC_OSR = 0x10, 0x10


class ES8311:
    def __init__(self, i2c, addr=ADDR):
        self.i2c = i2c
        self.addr = addr

    def _w(self, reg, val):
        self.i2c.writeto_mem(self.addr, reg, bytes([val & 0xFF]))

    def _r(self, reg):
        return self.i2c.readfrom_mem(self.addr, reg, 1)[0]

    def init(self, digital_mic=False):
        # software reset, then power on
        self._w(0x00, 0x1F)
        time.sleep_ms(20)
        self._w(0x00, 0x00)
        self._w(0x00, 0x80)
        # clocks on, MCLK taken from BCLK, SCLK not inverted
        self._w(0x01, 0xBF)
        self._w(0x06, self._r(0x06) & ~(1 << 5))
        # dividers for RATE
        self._w(0x02, (self._r(0x02) & 0x07) | ((_PRE_DIV - 1) << 5) | (_PRE_MULTI << 3))
        self._w(0x03, (_FS_MODE << 6) | _ADC_OSR)
        self._w(0x04, _DAC_OSR)
        self._w(0x05, ((_ADC_DIV - 1) << 4) | (_DAC_DIV - 1))
        self._w(0x06, (self._r(0x06) & 0xE0) | (_BCLK_DIV - 1))
        self._w(0x07, (self._r(0x07) & 0xC0) | _LRCK_H)
        self._w(0x08, _LRCK_L)
        # I2S slave, 16-bit in and out
        self._w(0x00, self._r(0x00) & 0xBF)
        self._w(0x09, 0x0C)
        self._w(0x0A, 0x0C)
        # power up analog circuitry and DAC
        self._w(0x0D, 0x01)
        self._w(0x0E, 0x02)
        self._w(0x12, 0x00)
        self._w(0x13, 0x10)
        self._w(0x1C, 0x6A)
        self._w(0x37, 0x08)
        # microphone: analog input, max PGA gain
        self._w(0x17, 0xFF)
        self._w(0x14, 0x1A | (0x40 if digital_mic else 0))

    def volume(self, pct):
        """DAC (speaker) volume, 0-100."""
        pct = max(0, min(100, pct))
        self._w(0x32, 0 if pct == 0 else (pct * 256 // 100) - 1)

    def id(self):
        return self._r(0xFD), self._r(0xFE), self._r(0xFF)
