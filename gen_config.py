#!/usr/bin/env python3
"""Generate firmware/config.json for the ESP32 from the project .env.

Reads AGENT_URL and SPEECH_URL (and optional WIFI_SSID / WIFI_PASSWORD) and writes firmware/config.json,
which is ignored by git. Wi-Fi credentials already present in that file are kept when the .env does not
define them, so the file the board filled in through the setup portal is preserved.

Usage:
    ./gen_config.py
    mpremote cp firmware/config.json :    # then send it to the board
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(ROOT, ".env")
OUT = os.path.join(ROOT, "firmware", "config.json")


def read_env(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.split(" #", 1)[0].strip().strip('"').strip("'")
            env[key.strip()] = value
    return env


def normalize(url):
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = "http://" + url
    return url


def main():
    if not os.path.exists(ENV):
        sys.exit("no .env found; copy .env.example to .env first")
    env = read_env(ENV)

    agent_url = normalize(env.get("AGENT_URL", ""))
    speech_url = normalize(env.get("SPEECH_URL", ""))
    if not agent_url or not speech_url:
        sys.exit("set AGENT_URL and SPEECH_URL in .env (e.g. http://192.168.1.23:8765)")

    old = {}
    if os.path.exists(OUT):
        with open(OUT) as f:
            old = json.load(f)

    cfg = {
        "ssid": env.get("WIFI_SSID") or old.get("ssid", ""),
        "password": env.get("WIFI_PASSWORD") or old.get("password", ""),
        "agent_url": agent_url,
        "speech_url": speech_url,
    }

    if not cfg["ssid"]:
        sys.exit("no SSID: set WIFI_SSID in .env or keep an existing firmware/config.json")

    with open(OUT, "w") as f:
        json.dump(cfg, f)
    print("wrote", OUT)
    print(cfg)
    print("\nsend it to the board:  mpremote cp firmware/config.json :")


if __name__ == "__main__":
    main()
