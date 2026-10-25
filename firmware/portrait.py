"""Isa's 3D-style portrait, same interface as face.Face (set_pose, idle, hold, speak_level, think_start/stop).

Images are made on the PC by tools/build_avatar.py. Everything is loaded into RAM at start (the board has 8 MB of PSRAM),
so showing a pose is a memory copy plus one SPI transfer.

There is a single full image, the neutral face. Every pose, emotion and speech frame is that face plus an *eye piece*
(eyes and brows) and a *mouth piece*, pasted at fixed boxes. The head therefore never moves or changes size between
poses (swapping whole generated images made it jump a few pixels each time), and blinking and the talking mouth only
swap small pieces (~10 ms per frame), in every pose.
"""
import framebuf
import random
import time

import _thread

W = 240
EMOTIONS = ("feliz", "triste", "curiosa", "surpresa", "confusa")
EYES = (40, 88, 200, 172)    # x0, y0, x1, y1: must match tools/build_avatar.py
MOUTH = (72, 184, 168, 240)
_DIR = "/avatar/"
# pose -> (eye piece, mouth piece)
_POSES = {"neutra": ("neutra", "fechada"), "ouvindo": ("neutra", "fechada"), "pensando": ("pensando", "pensando")}
for _e in EMOTIONS:
    _POSES[_e] = (_e, _e)
_NO_BLINK = ("feliz",)       # the happy eyes are already closed arcs


def _load(name, size):
    buf = bytearray(size)
    with open(_DIR + name + ".raw", "rb") as f:
        if f.readinto(buf) != size:
            raise OSError("avatar/%s.raw incompleto" % name)
    return buf


class Portrait:
    def __init__(self, display):
        self.d = display
        self._ew, self._eh = EYES[2] - EYES[0], EYES[3] - EYES[1]
        self._mw, self._mh = MOUTH[2] - MOUTH[0], MOUTH[3] - MOUTH[1]
        self.neutral = _load("neutra", W * 320 * 2)
        # pieces are FrameBuffers over the raw bytes (already in panel byte order, like the display buffer)
        self.eyes = {n: self._piece("e_" + n, self._ew, self._eh)
                     for n in ("neutra", "pensando", "meio", "pisca") + EMOTIONS}
        self.mouths = {n: self._piece("m_" + n, self._mw, self._mh)
                       for n in ("fechada", "a", "o", "e", "u", "pensando") + EMOTIONS}
        self.pose = "neutra"
        self._eyes_shown = "neutra"
        self._mouth_shown = None
        self._thinking = False
        self._think_done = True
        self._last_blink = time.ticks_ms()
        self.set_pose("neutra")

    @staticmethod
    def _piece(name, w, h):
        return framebuf.FrameBuffer(_load(name, w * h * 2), w, h, framebuf.RGB565)

    # ---- drawing ----------------------------------------------------------------------------------------------
    # FrameBuffer.blit copies in C. Do NOT assign slices row by row (buf[a:b] = ...): each one costs ~3 ms here,
    # because MicroPython moves the rest of the 150 KB buffer, so a 52-row mouth took 160 ms instead of ~1 ms.
    def _eyes(self, name, show=True):
        self.d.blit(self.eyes[name], EYES[0], EYES[1])
        self._eyes_shown = name
        if show:
            self.d.show_rows(EYES[1], EYES[3])

    def _mouth(self, name, show=True):
        self.d.blit(self.mouths[name], MOUTH[0], MOUTH[1])
        self._mouth_shown = name
        if show:
            self.d.show_rows(MOUTH[1], MOUTH[3])

    def set_pose(self, name, redraw=True):
        if name not in _POSES:
            name = "neutra"
        self.pose = name
        self._mouth_shown = None
        if not redraw:
            return
        eyes, mouth = _POSES[name]
        self.d.buf[:] = self.neutral
        self._eyes(eyes, show=False)
        self._mouth(mouth, show=False)
        self.d.show()

    def draw(self):
        self.set_pose(self.pose)

    # ---- blinking -----------------------------------------------------------------------------------------------
    def blink(self):
        if self.pose in _NO_BLINK:
            return
        own = _POSES[self.pose][0]
        for name in ("meio", "pisca", "meio", own):
            self._eyes(name)
        self._last_blink = time.ticks_ms()

    @staticmethod
    def _wait(ms, until):
        end = time.ticks_add(time.ticks_ms(), ms)
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            if until and until():
                return False
            time.sleep_ms(30)
        return True

    def idle(self, until=None, seconds=None):
        """Blink at random intervals until `until()` is true (or `seconds` pass)."""
        start = time.ticks_ms()
        while seconds is None or time.ticks_diff(time.ticks_ms(), start) < seconds * 1000:
            if until and until():
                return
            if not self._wait(random.randint(2000, 4500), until):
                return
            self.blink()

    def hold(self, ms):
        time.sleep_ms(ms)

    # ---- speech: the mouth follows the loudness -----------------------------------------------------------------
    @staticmethod
    def _mouth_for(level):
        if level < 0.2:
            return "fechada"
        if level < 0.4:
            return "u"
        if level < 0.6:
            return "o"
        if level < 0.8:
            return "e"
        return "a"

    def speak_level(self, level):
        """Call between audio chunks with the loudness (0..1)."""
        # closed means the neutral closed mouth, not the pose's own: the happy smile shows teeth and looked like an open mouth
        want = self._mouth_for(level)
        if want != self._mouth_shown:
            self._mouth(want)
        if time.ticks_diff(time.ticks_ms(), self._last_blink) > random.randint(3500, 6000):
            self.blink()

    # ---- thinking: the pose stays still, with a slow blink ------------------------------------------------------
    def _think_loop(self):
        next_blink = time.ticks_add(time.ticks_ms(), 2400)
        try:
            while self._thinking:
                time.sleep_ms(30)
                if time.ticks_diff(time.ticks_ms(), next_blink) >= 0 and self._thinking:
                    self.blink()
                    next_blink = time.ticks_add(time.ticks_ms(), random.randint(2200, 3600))
        finally:
            self._think_done = True

    def think_start(self):
        self.set_pose("pensando")
        self._thinking, self._think_done = True, False
        _thread.stack_size(8192)
        _thread.start_new_thread(self._think_loop, ())

    def think_stop(self):
        self._thinking = False
        while not self._think_done:
            time.sleep_ms(10)
