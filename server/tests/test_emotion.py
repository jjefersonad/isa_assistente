import pytest

from emotion import split_emotion


@pytest.mark.parametrize("raw,text,emotion", [
    ("[feliz] Oi! Tudo bem?", "Oi! Tudo bem?", "feliz"),
    ("  [Triste]   Sinto muito.", "Sinto muito.", "triste"),
    ("[ curiosa ]Me conta mais", "Me conta mais", "curiosa"),
    ("Sem etiqueta nenhuma.", "Sem etiqueta nenhuma.", "neutra"),
    ("[desconhecida] Oi", "[desconhecida] Oi", "neutra"),
    ("[feliz] Oi [triste] tchau", "Oi tchau", "feliz"),
    ("[neutra]", "", "neutra"),
    ("", "", "neutra"),
    ("São [10] horas", "São [10] horas", "neutra"),
])
def test_split_emotion(raw, text, emotion):
    assert split_emotion(raw) == (text, emotion)
