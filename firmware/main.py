import sys
import time
from machine import Pin

import config
import converse
import mic
import portal
import wifi
from face import Face
from ili9341 import Display, color565

WHITE = color565(255, 255, 255)
YELLOW = color565(255, 255, 0)

d = Display()
d.backlight(True)
try:  # the 3D-style portrait if its images are on the board, else the shapes face
    from portrait import Portrait
    face = Portrait(d)
except (ImportError, OSError) as e:
    print("retrato indisponivel, usando o rosto de formas:", e)
    face = Face(d)


def status(lines, color=WHITE):
    """Plain text, only for the Wi-Fi setup screens: there is no other way to show the network name and address."""
    d.fill(0)
    for i, line in enumerate(lines):
        d.text(line, 10, 120 + i * 16, color)
    d.show()


def boot_held(seconds=3):
    """True if BOOT (IO0) is pressed during the startup window. Hold it *after* power-up, not while resetting."""
    btn = Pin(0, Pin.IN, Pin.PULL_UP)
    face.set_pose("neutra")
    face.idle(until=lambda: btn.value() == 0, seconds=seconds)
    return btn.value() == 0


def open_portal(reason):
    def ready(ssid, ip):
        status([reason, "", "Conecte o celular na", "rede:", "  " + ssid, "", "e abra:", "  http://" + ip], YELLOW)

    portal.run(ready)


def react(pose, ms):
    """Show a pose for a moment (errors, "didn't catch that") and go back to the neutral face."""
    face.set_pose(pose)
    face.hold(ms)
    face.set_pose("neutra")


def listen(m, button):
    """Push-to-talk: the audio streams up while BOOT is held and the spoken reply streams back (see converse.py)."""
    try:
        result = converse.turn(m, face, button)
    except OSError as e:
        print("Erro:", e)
        react("triste", 2000)
        return
    if result == converse.OK:
        face.hold(1200)
        face.set_pose("neutra")
    elif result == converse.TOO_SHORT:
        react("confusa", 1000)
    elif result == converse.NOT_UNDERSTOOD:
        react("confusa", 1500)
    else:
        react("triste", 2000)


if boot_held():
    open_portal("Configuracao")
elif not config.load():
    open_portal("Sem configuracao")
else:
    face.think_start()
    try:
        ip = wifi.connect()
        print("Wi-Fi ok:", ip)
    except OSError as e:
        print(e)
        ip = None
    finally:
        face.think_stop()
    if ip is None:
        open_portal("Wi-Fi falhou")

m = mic.Mic()
button = mic.boot_button()
face.set_pose("neutra")

while True:
    face.idle(until=lambda: button.value() == 0)
    try:
        listen(m, button)
    except Exception as e:  # an uncaught error would end main.py and leave the face frozen on its last frame
        sys.print_exception(e)
        face.think_stop()  # no-op unless the animation thread is still running
        react("triste", 2000)
