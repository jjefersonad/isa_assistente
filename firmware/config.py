import json
import os

FILE = "config.json"


def load():
    """Return the saved config dict, or None if missing/corrupt."""
    try:
        with open(FILE) as f:
            cfg = json.load(f)
        return cfg if cfg.get("ssid") else None
    except (OSError, ValueError):
        return None


def save(cfg):
    with open(FILE, "w") as f:
        json.dump(cfg, f)


def clear():
    try:
        os.remove(FILE)
    except OSError:
        pass
