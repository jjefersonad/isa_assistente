import network
import time

import config


def connect(timeout_s=20):
    """Connect using config.json and return the IP. Raises OSError if unconfigured or on timeout."""
    cfg = config.load()
    if not cfg:
        raise OSError("Wi-Fi: sem configuracao")
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if not sta.isconnected():
        sta.connect(cfg["ssid"], cfg["password"])
        start = time.ticks_ms()
        while not sta.isconnected():
            if time.ticks_diff(time.ticks_ms(), start) > timeout_s * 1000:
                sta.disconnect()
                raise OSError("Wi-Fi: timeout ao conectar em " + cfg["ssid"])
            time.sleep_ms(200)
    # Wi-Fi power saving cut throughput by more than half (100 vs 245 KB/s); the board is USB powered anyway
    sta.config(pm=network.WLAN.PM_NONE)
    return sta.ifconfig()[0]
