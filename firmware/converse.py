"""One voice turn with the PC agent over a single WebSocket, streamed in both directions (protocol in server/main.py).

While the button is held the microphone chunks go up as they are captured; the reply comes back as the emotion, then
PCM frames that are played as they arrive, so the voice starts after the first sentence instead of after the whole reply.
"""
import json

import config
import es8311
import mic
import tts
import ws

OK, TOO_SHORT, NOT_UNDERSTOOD, FAILED = "ok", "short", "empty", "error"
_conn = None


def _endpoint(url):
    rest = url.split("://", 1)[-1]
    hostport, _, path = rest.partition("/")
    host, _, port = hostport.partition(":")
    return host, int(port or 80), "/" + path


def _connection():
    """The open connection (kept between turns: the server holds the conversation history per connection)."""
    global _conn
    if _conn is not None and not _conn.alive():
        _drop()
    if _conn is None:
        url = (config.load() or {}).get("agent_url")
        if not url:
            raise OSError("agent_url nao configurada")
        host, port, path = _endpoint(url)
        conn = ws.WebSocket(host, port, path)
        conn.connect()
        _conn = conn
    return _conn


def _drop():
    global _conn
    if _conn:
        _conn.close()
        _conn = None


def turn(m, face, button):
    """Record while `button` is held, stream it up, play the streamed reply with the face. Returns one of the status
    constants above; raises OSError if the network failed (the connection is dropped, the next turn reconnects)."""
    conn = _connection()
    face.set_pose("ouvindo")
    try:
        conn.send(json.dumps({"type": "audio_start", "rate": mic.RATE, "tts_rate": es8311.RATE}))
        sent = m.stream(lambda: button.value() == 0, conn.send_bytes)
        if sent < mic.RATE:  # shorter than ~0.5 s: ignore
            conn.send(json.dumps({"type": "audio_cancel"}))
            return TOO_SHORT
        conn.send(json.dumps({"type": "audio_end"}))
        return _reply(conn, m, face)
    except OSError:
        _drop()
        raise


def _reply(conn, m, face):
    face.think_start()  # the eyes blink slowly in a second thread while this one waits for the network
    thinking, speaker = True, None
    text, emotion, error = "", "neutra", None
    try:
        while True:
            msg = conn.recv()
            if isinstance(msg, str):
                data = json.loads(msg)
                kind = data.get("type")
                if kind == "stt":
                    text = data.get("text", "")
                elif kind == "emotion":
                    emotion = data.get("emotion", "neutra")
                    if speaker:  # a new tag in the middle of the reply
                        face.set_pose(emotion)
                elif kind == "error":
                    error = data.get("message", "erro")
                    print("Erro do servidor:", error)
                elif kind == "done":
                    break
                continue
            if speaker is None:  # first audio frame: stop thinking, show the emotion, start talking
                if thinking:
                    face.think_stop()
                    thinking = False
                face.set_pose(emotion)
                m.close()  # stop the microphone so the board does not hear its own voice
                speaker = tts.Speaker(m.codec, on_level=face.speak_level)
                speaker.start()
            speaker.write(msg)
    finally:
        if thinking:
            face.think_stop()
        if speaker:
            speaker.stop()
    if speaker:
        return OK
    return FAILED if error else NOT_UNDERSTOOD
