"""Turn the LLM's token stream into things the board can act on as soon as they exist: the emotion (from the leading
"[feliz]" tag) and whole sentences, each of which goes to TTS while the model is still writing the next one."""
import re

from emotion import EMOTIONS

MIN_SENTENCE = 12  # shorter pieces ("Oi!", "Sr.") are merged with the next one: TTS sounds choppy on fragments

_TAG = re.compile(r"\[\s*(%s)\s*\]\s*" % "|".join(EMOTIONS), re.IGNORECASE)
_ANY_TAG = re.compile(r"\s*\[\s*(?:%s)\s*\]\s*" % "|".join(EMOTIONS), re.IGNORECASE)
_BOUNDARY = re.compile(r"(?<=[.!?…])\s+|\n+")
_MAX_TAG = 24  # "[ surpresa ]" fits; a "[" with no "]" in this many characters is plain text


class ReplySplitter:
    """feed() the model's text pieces; get back ("emotion", name) and ("sentence", text) events, in order.

    A sentence is only closed when whitespace follows its final punctuation, so "3.5" or "R$ 1.200" are never cut.
    A tag is only an emotion at the start of a sentence, which keeps the events in order.
    """

    def __init__(self):
        self.buf = ""

    def feed(self, text):
        self.buf += text
        return self._drain(final=False)

    def finish(self):
        return self._drain(final=True)

    def _drain(self, final):
        out = []
        while True:
            self.buf = self.buf.lstrip()
            m = _TAG.match(self.buf)
            if m:
                out.append(("emotion", m.group(1).lower()))
                self.buf = self.buf[m.end():]
                continue
            if not final and self.buf.startswith("[") and "]" not in self.buf and len(self.buf) < _MAX_TAG:
                break  # possibly the start of a tag still arriving
            cut = self._cut(final)
            if cut is None:
                break
            sentence, self.buf = self.buf[:cut], self.buf[cut:]
            sentence = _ANY_TAG.sub(" ", sentence).strip()
            if sentence:
                out.append(("sentence", sentence))
        return out

    def _cut(self, final):
        for m in _BOUNDARY.finditer(self.buf):
            if len(self.buf[:m.start()].strip()) >= MIN_SENTENCE:
                return m.start()
        return len(self.buf) if final and self.buf.strip() else None
