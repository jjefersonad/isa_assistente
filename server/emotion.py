"""The model opens each reply with an emotion tag like "[feliz]". Split it off so the board can show it and TTS never
speaks it."""
import re

EMOTIONS = ("neutra", "feliz", "triste", "curiosa", "surpresa", "confusa")
DEFAULT = "neutra"

_LEADING = re.compile(r"^\s*\[\s*([^\]\n]{1,20}?)\s*\]\s*")
_ANY_TAG = re.compile(r"\s*\[\s*(?:%s)\s*\]\s*" % "|".join(EMOTIONS), re.IGNORECASE)


def split_emotion(reply: str) -> tuple[str, str]:
    """Return (spoken text, emotion). Unknown or missing tags give "neutra"; stray known tags are removed."""
    emotion = DEFAULT
    m = _LEADING.match(reply)
    if m:
        tag = m.group(1).lower()
        if tag in EMOTIONS:
            emotion = tag
            reply = reply[m.end():]
    return _ANY_TAG.sub(" ", reply).strip(), emotion
