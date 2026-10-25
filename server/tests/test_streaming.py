import asyncio
import json

import pytest

import main
from streaming import ReplySplitter


def run(pieces, final=True):
    s, out = ReplySplitter(), []
    for p in pieces:
        out += s.feed(p)
    return out + (s.finish() if final else [])


def test_emotion_then_sentences():
    out = run(["[fel", "iz] Cla", "ro! Sao dez", " e meia. Mais alguma", " coisa?"])
    assert out == [("emotion", "feliz"), ("sentence", "Claro! Sao dez e meia."), ("sentence", "Mais alguma coisa?")]


def test_emotion_is_sent_before_the_first_sentence_ends():
    s = ReplySplitter()
    assert s.feed("[triste] Sinto mu") == [("emotion", "triste")]


def test_decimals_and_short_fragments_are_not_cut():
    assert run(["O total e 3.5 reais. Oi! Tudo bem por ai? "]) == [
        ("sentence", "O total e 3.5 reais."), ("sentence", "Oi! Tudo bem por ai?")]


def test_unknown_tag_and_brackets_stay_text():
    assert run(["[desconhecida] Oi gente"]) == [("sentence", "[desconhecida] Oi gente")]
    assert run(["Sao [10] horas agora."]) == [("sentence", "Sao [10] horas agora.")]


def test_stray_tag_inside_a_sentence_is_removed():
    assert run(["Oi, [feliz] tudo bem com voce?"]) == [("sentence", "Oi, tudo bem com voce?")]


def test_second_tag_after_a_sentence_changes_the_emotion_in_order():
    out = run(["[neutra] Vou ver isso agora. ", "[feliz] Pronto, achei o arquivo!"])
    assert out == [("emotion", "neutra"), ("sentence", "Vou ver isso agora."), ("emotion", "feliz"),
                   ("sentence", "Pronto, achei o arquivo!")]


def test_waits_for_a_partial_tag_but_not_forever():
    s = ReplySplitter()
    assert s.feed("[sur") == []
    assert s.finish() == [("sentence", "[sur")]


def test_empty():
    assert run([]) == [] and run(["[neutra]"]) == [("emotion", "neutra")]


# ---- the whole turn, with a fake model and a fake TTS -------------------------------------------------------------
class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, m):
        self.sent.append(m)


class FakeSpeech:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    async def synth(self, text, rate):
        self.calls.append(text)
        n = len(self.calls)  # which sentence this is, in the order the synthesis was started
        if text == self.fail_on:
            raise RuntimeError("tts caiu")
        for i in range(2):
            await asyncio.sleep(0)
            yield bytes([n, i]) * 2048


class FakeAgent:
    def __init__(self, pieces):
        self.pieces = pieces

    async def astream(self, state, stream_mode):
        from langchain_core.messages import AIMessageChunk
        for p in self.pieces:
            yield AIMessageChunk(content=p), {}


def kinds(ws):
    return [json.loads(m)["type"] if isinstance(m, str) else "audio" for m in ws.sent]


def test_turn_streams_emotion_sentences_and_audio_in_order():
    ws, speech, history = FakeWS(), FakeSpeech(), []
    agent = FakeAgent(["[feliz] Claro, ", "pode falar. ", "Estou ouvindo você!"])
    asyncio.run(main.run_turn(ws, agent, speech, history, "oi", 22050))
    assert speech.calls == ["Claro, pode falar.", "Estou ouvindo você!"]
    assert kinds(ws)[0] == "emotion"
    audio = [m for m in ws.sent if isinstance(m, bytes)]
    assert len(audio) == 4 and audio[0][0] == 1 and audio[-1][0] == 2  # sentence 1's frames before sentence 2's
    assert history[-1] == {"role": "assistant", "content": "[feliz] Claro, pode falar. Estou ouvindo você!"}


def test_turn_without_tts_rate_sends_text_only():
    ws, speech = FakeWS(), FakeSpeech()
    asyncio.run(main.run_turn(ws, FakeAgent(["[neutra] Tudo certo por aqui."]), speech, [], "oi", 0))
    assert speech.calls == [] and "audio" not in kinds(ws)


def test_tts_failure_is_reported_and_turn_still_ends():
    ws, history = FakeWS(), []
    asyncio.run(main.handle_turn(ws, FakeAgent(["[neutra] Isso vai falhar agora."]), FakeSpeech("Isso vai falhar agora."),
                                 history, "oi", 22050))
    assert kinds(ws)[-2:] == ["error", "done"] and history == []


def test_chunk_text_ignores_tool_call_blocks():
    from langchain_core.messages import AIMessageChunk
    assert main.chunk_text(AIMessageChunk(content=[{"type": "text", "text": "oi"}, {"type": "tool_use", "id": "x"}])) == "oi"
    assert main.chunk_text(AIMessageChunk(content="")) == ""
