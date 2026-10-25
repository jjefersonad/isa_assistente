import httpx
import pytest

import tools


def test_datetime_is_portuguese_and_has_year():
    out = tools.data_hora_atual()
    assert any(d in out for d in tools._WEEKDAYS) and " de 20" in out and ":" in out


@pytest.mark.parametrize("expr,expected", [
    ("249.90 * 0.15", "37.485"), ("249,90 * 0,15", "37.485"), ("(1200 + 350) / 4", "387.5"),
    ("sqrt(144)", "12"), ("2 ** 10", "1024"), ("-3 + 10 % 4", "-1"), ("pi * 2", "6.283185307"),
])
def test_calcular_ok(expr, expected):
    assert tools.calcular(expr).endswith("= " + expected)


@pytest.mark.parametrize("expr", [
    "__import__('os').system('id')", "open('/etc/passwd')", "().__class__", "9 ** 9 ** 9", "'a' * 10",
    "x + 1", "lambda: 1", "sqrt(1, key=2)", "",
])
def test_calcular_rejects_unsafe(expr):
    assert tools.calcular(expr).startswith("Erro")


def test_calcular_div_zero():
    assert tools.calcular("1/0") == "Erro: divisão por zero."


def test_unidades():
    assert "= 41.8429 kilometer" in tools.converter_unidades(26, "mile", "kilometer")
    assert "= 77 degF" in tools.converter_unidades(25, "degC", "degF")
    assert "= 77 fahrenheit" in tools.converter_unidades(25, "celsius", "fahrenheit")
    assert tools.converter_unidades(1, "kilometer", "second").startswith("Erro")
    assert tools.converter_unidades(1, "nao_existe", "meter").startswith("Erro")


def test_moeda(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"date": "2026-10-06", "rates": {"BRL": 496.86}}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    assert tools.converter_moeda(100, "usd", "brl") == "100 USD = 496.86 BRL (cotação de 2026-10-06)"
    assert tools.converter_moeda(5, "BRL", "BRL") == "5 BRL = 5 BRL"


def test_moeda_offline(monkeypatch):
    def boom(*a, **k): raise httpx.ConnectError("sem rede")
    monkeypatch.setattr(httpx, "get", boom)
    assert tools.converter_moeda(1, "USD", "BRL").startswith("Erro")
