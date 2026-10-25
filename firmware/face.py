"""Isa's face: two eyes and a mouth in the same style (white shapes, blue iris), drawn with framebuf primitives.

The eyes and the mouth live in separate horizontal bands, so each can be redrawn and sent to the panel on its own
(show_rows), which keeps the mouth animation fast while the audio plays.
"""
import math
import random
import time
from array import array

import _thread

from ili9341 import Display, color565

W = 240
BG = color565(0, 0, 0)
WHITE = color565(255, 255, 255)
IRIS = color565(40, 140, 255)
PUPIL = color565(0, 0, 0)

EYES_X = (66, 174)
EYE_Y = 108
RX, RY = 44, 56
IRIS_R = 25
EYE_BAND = (20, 190)

MOUTH_X, MOUTH_Y = 120, 232
MOUTH_BAND = (190, 290)
LINE_R = 4  # half the thickness of the mouth line

_DEFAULT = {"sl": 1.0, "sr": 1.0, "iris": 1.0, "shape": "round", "look": (0, 0), "mouth": "flat",
            "brows": ((26, 40, 106, 40, 5), (134, 40, 214, 40, 5))}  # every pose has brows: segments (x0, y0, x1, y1, arch)
POSES = {
    "neutra": {},
    "feliz": {"shape": "happy", "mouth": "smile", "brows": ((26, 36, 106, 36, 9), (134, 36, 214, 36, 9))},
    "triste": {"shape": "sad", "look": (0, 7), "mouth": "frown",
               "brows": ((26, 50, 106, 34, 0), (134, 34, 214, 50, 0))},  # inner ends up
    "curiosa": {"sl": 0.92, "sr": 1.12, "look": (9, -8), "mouth": "smirk",
                "brows": ((26, 44, 106, 46, 3), (134, 38, 214, 34, 12))},  # right one raised
    "surpresa": {"sl": 1.12, "sr": 1.12, "iris": 0.7, "mouth": "o",
                 "brows": ((26, 34, 106, 34, 10), (134, 34, 214, 34, 10))},
    "confusa": {"sl": 0.72, "sr": 1.0, "look": (-7, -4), "mouth": "wavy",
                "brows": ((26, 42, 106, 56, 0), (134, 36, 214, 36, 10))},  # one furrowed, one raised
    "ouvindo": {"sl": 1.1, "sr": 1.1, "iris": 1.1, "mouth": "dot",
                "brows": ((26, 36, 106, 36, 10), (134, 36, 214, 36, 10))},
    # like the "thinking" emoji: eyes up to the side, one brow furrowed (inner end low), the other arched up, tiny crooked mouth
    "pensando": {"look": (-15, -20), "mouth": "hmm", "brows": ((26, 44, 100, 58, 0), (148, 46, 214, 30, 10))},
}
_OPEN_W = {"smile": 40, "flat": 32, "frown": 26, "smirk": 32, "wavy": 28, "dot": 24}


class Face:
    def __init__(self, display):
        self.d = display
        self.pose = "neutra"
        self.look = None  # None = use the pose's own gaze
        self._p = self._params("neutra")
        self._thinking = False
        self._think_done = True
        self._last_blink = time.ticks_ms()

    @staticmethod
    def _params(name):
        p = dict(_DEFAULT)
        p.update(POSES.get(name, {}))
        return p

    def set_pose(self, name, redraw=True):
        self.pose = name if name in POSES else "neutra"
        self._p = self._params(self.pose)
        self.look = None
        if redraw:
            self.draw()

    # ---- eyes -------------------------------------------------------------------------------------------------
    def _eye(self, cx, side, scale, openness, look):
        d, p = self.d, self._p
        rx = int(RX * (1 + (scale - 1) * 0.3))
        ry = max(int(RY * scale * openness), 2)
        d.ellipse(cx, EYE_Y, rx, ry, WHITE, True)
        if p["shape"] == "happy":
            # cover the lower part: what is left is a white crescent, a closed smiling eye
            d.ellipse(cx, EYE_Y + int(RY * 0.55), rx + 4, int(RY * 0.95), BG, True)
            return
        ir = int(IRIS_R * p["iris"])
        iry = max(int(ir * openness), 1)
        lx = max(-(rx - ir - 4), min(rx - ir - 4, look[0]))
        ly = max(-(ry - iry - 4), min(ry - iry - 4, int(look[1] * openness)))
        d.ellipse(cx + lx, EYE_Y + ly, ir, iry, IRIS, True)
        d.ellipse(cx + lx, EYE_Y + ly, max(ir // 2, 1), max(iry // 2, 1), PUPIL, True)
        if p["shape"] == "sad":
            # droopy upper lid: cover the top corner on the outer side of each eye
            o, t = side * (rx + 4), -ry - 4
            d.poly(cx, EYE_Y, array("h", [o, t, -o, t, o, -int(ry * 0.15)]), BG, True)

    def _brow(self, x0, y0, x1, y1, bulge):
        """Thick line from (x0, y0) to (x1, y1); a positive `bulge` arches it upward."""
        n = max(abs(x1 - x0), abs(y1 - y0)) // 3 + 1
        for i in range(n + 1):
            t = i / n
            y = y0 + (y1 - y0) * t - bulge * 4 * t * (1 - t)
            self.d.ellipse(int(x0 + (x1 - x0) * t), int(y), LINE_R - 1, LINE_R - 1, WHITE, True)

    def eyes(self, openness=1.0):
        d, p = self.d, self._p
        look = self.look if self.look is not None else p["look"]
        y0, y1 = EYE_BAND
        d.fill_rect(0, y0, W, y1 - y0, BG)
        self._eye(EYES_X[0], -1, p["sl"], openness, look)
        self._eye(EYES_X[1], 1, p["sr"], openness, look)
        if p["brows"]:
            for brow in p["brows"]:
                self._brow(*brow)
        d.show_rows(y0, y1)

    def blink(self):
        if self._p["shape"] == "happy":
            return
        for o in (0.65, 0.3, 0.05, 0.4, 0.8, 1.0):
            self.eyes(o)
        self._last_blink = time.ticks_ms()

    # ---- mouth ------------------------------------------------------------------------------------------------
    def _curve(self, w, amp, tilt=0, dx=0):
        for x in range(-w, w + 1, 2):
            u = x / w
            y = MOUTH_Y + int(amp * (1 - u * u) + tilt * u)
            self.d.ellipse(MOUTH_X + dx + x, y, LINE_R, LINE_R, WHITE, True)

    def _wavy(self, w, phase):
        for x in range(-w, w + 1, 2):
            y = MOUTH_Y + int(5 * math.sin(x / 7 + phase))
            self.d.ellipse(MOUTH_X + x, y, LINE_R, LINE_R, WHITE, True)

    def _open(self, rx, ry):
        d = self.d
        d.ellipse(MOUTH_X, MOUTH_Y, rx, ry, WHITE, True)
        if ry > 9:
            d.ellipse(MOUTH_X, MOUTH_Y, rx - 6, ry - 6, BG, True)
            if ry > 18:  # blue tongue, same colour as the irises
                d.ellipse(MOUTH_X, MOUTH_Y + int((ry - 6) * 0.5), int((rx - 6) * 0.55), int((ry - 6) * 0.4),
                          IRIS, True)

    def mouth(self, amp=None, phase=0.0):
        """Closed mouth for the current pose, or open by `amp` (0..1) while speaking."""
        d, kind = self.d, self._p["mouth"]
        y0, y1 = MOUTH_BAND
        d.fill_rect(0, y0, W, y1 - y0, BG)
        if kind == "o":
            self._open(21, 26 + int((amp or 0) * 8))
        elif amp is not None and amp > 0.08:
            self._open(_OPEN_W[kind], 5 + int(amp * 34))
        elif kind == "smile":
            self._curve(34, 12)
        elif kind == "frown":
            self._curve(30, -10)
        elif kind == "smirk":
            self._curve(28, 6, -6)
        elif kind == "wavy":
            self._wavy(32, phase)
        elif kind == "hmm":
            self._curve(15, -3, 5, -12)  # tiny, slightly crooked frown, a bit to the left
        elif kind == "dot":
            self._curve(10, 0)
        else:
            self._curve(24, 0)
        d.show_rows(y0, y1)

    def draw(self):
        self.eyes()
        self.mouth()

    # ---- behaviours -------------------------------------------------------------------------------------------
    @staticmethod
    def _wait(ms, until):
        end = time.ticks_add(time.ticks_ms(), ms)
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            if until and until():
                return False
            time.sleep_ms(30)
        return True

    def idle(self, until=None, seconds=None):
        """Glance around and blink at random until `until()` is true (or `seconds` pass)."""
        start = time.ticks_ms()
        while seconds is None or time.ticks_diff(time.ticks_ms(), start) < seconds * 1000:
            if until and until():
                return
            base = self._p["look"]
            self.look = (base[0] + random.randint(-10, 10), base[1] + random.randint(-6, 6))
            self.eyes()
            if not self._wait(random.randint(1200, 3500), until):
                break
            self.blink()
        self.look = None

    def hold(self, ms):
        time.sleep_ms(ms)

    def speak_level(self, level):
        """Call between audio chunks with the loudness (0..1): opens the mouth, blinks now and then."""
        self.mouth(level)
        if time.ticks_diff(time.ticks_ms(), self._last_blink) > random.randint(3500, 6000):
            self.blink()

    # ---- thinking animation, run on the second core while the main thread waits for the network -----------------
    def _think_loop(self):
        """The face stays still on purpose (eyes darting around and a wobbling mouth looked frantic); a slow blink every
        few seconds is the only sign of life."""
        next_blink = time.ticks_add(time.ticks_ms(), 2400)
        try:
            self.draw()
            while self._thinking:
                time.sleep_ms(30)
                if time.ticks_diff(time.ticks_ms(), next_blink) >= 0 and self._thinking:
                    self.blink()
                    next_blink = time.ticks_add(time.ticks_ms(), random.randint(2200, 3600))
        finally:
            self._think_done = True

    def think_start(self):
        self.set_pose("pensando", redraw=False)
        self._thinking, self._think_done = True, False
        _thread.stack_size(8192)
        _thread.start_new_thread(self._think_loop, ())

    def think_stop(self):
        self._thinking = False
        while not self._think_done:
            time.sleep_ms(10)
        self.look = None


if __name__ == "__main__":
    d = Display()
    d.backlight(True)
    d.fill(BG)
    d.show()
    f = Face(d)
    for name in ("neutra", "feliz", "triste", "curiosa", "surpresa", "confusa", "ouvindo", "pensando"):
        f.set_pose(name)
        time.sleep(1.2)
