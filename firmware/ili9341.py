"""Minimal ILI9341 driver (240x320, SPI) drawing into a full-screen RGB565 framebuf."""
import framebuf
import time
from machine import Pin, SPI

W, H = 240, 320


def color565(r, g, b):
    # framebuf stores little-endian, the panel wants big-endian: swap the bytes
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((c & 0xFF) << 8) | (c >> 8)


class Display(framebuf.FrameBuffer):
    def __init__(self, sck=12, mosi=11, miso=13, cs=10, dc=46, bl=45, baudrate=40_000_000):
        self.buf = bytearray(W * H * 2)
        super().__init__(self.buf, W, H, framebuf.RGB565)
        self.spi = SPI(2, baudrate=baudrate, polarity=0, phase=0,
                       sck=Pin(sck), mosi=Pin(mosi), miso=Pin(miso))
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.dc = Pin(dc, Pin.OUT, value=0)
        self.bl = Pin(bl, Pin.OUT, value=0)
        self._init_panel()

    def _cmd(self, cmd, data=b""):
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes([cmd]))
        if data:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def _init_panel(self):
        # RST is tied to the ESP32-S3 reset, so a software reset is required
        self._cmd(0x01)
        time.sleep_ms(150)
        self._cmd(0x11)  # sleep out
        time.sleep_ms(120)
        self._cmd(0x3A, b"\x55")  # 16 bit/pixel
        self._cmd(0x36, b"\x48")  # portrait, BGR, MX (mirror X, this panel is wired mirrored)
        self._cmd(0x21)  # inversion on (IPS panels)
        self._cmd(0x29)  # display on

    def show(self):
        self._cmd(0x2A, b"\x00\x00" + (W - 1).to_bytes(2, "big"))
        self._cmd(0x2B, b"\x00\x00" + (H - 1).to_bytes(2, "big"))
        self._cmd(0x2C)
        self.cs(0)
        self.dc(1)
        self.spi.write(self.buf)
        self.cs(1)

    def show_rows(self, y0, y1):
        """Send only rows y0..y1-1 (the buffer is row-major, so they are contiguous): ~5x faster than show()."""
        self._cmd(0x2A, b"\x00\x00" + (W - 1).to_bytes(2, "big"))
        self._cmd(0x2B, y0.to_bytes(2, "big") + (y1 - 1).to_bytes(2, "big"))
        self._cmd(0x2C)
        self.cs(0)
        self.dc(1)
        self.spi.write(memoryview(self.buf)[y0 * W * 2:y1 * W * 2])
        self.cs(1)

    def backlight(self, on=True):
        self.bl(1 if on else 0)
