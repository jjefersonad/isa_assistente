"""Tools the voice agent can call. Each returns a short plain-text result that the model turns into speech."""
import ast
import math
import operator
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pint

_WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
           "novembro", "dezembro"]


def data_hora_atual() -> str:
    """Retorna a data e a hora atuais (dia da semana, dia, mês, ano e horário). Use sempre que o usuário perguntar
    que horas são, que dia é hoje, dia da semana, mês ou ano, ou precisar calcular algo relativo a hoje."""
    now = datetime.now(ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo")))
    return (f"{_WEEKDAYS[now.weekday()]}, {now.day} de {_MONTHS[now.month - 1]} de {now.year}, "
            f"{now.hour:02d}:{now.minute:02d}")


_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max}
_CONSTS = {"pi": math.pi, "e": math.e}
_MAX_POW = 1000


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW:
            raise ValueError("expoente grande demais")
        return _BINARY[type(node.op)](left, right)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS
            and not node.keywords):
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError("expressão não permitida")


def calcular(expressao: str) -> str:
    """Calcula uma expressão matemática com precisão. Use SEMPRE para contas, porcentagens, juros, divisões de conta
    e médias, em vez de calcular de cabeça. Escreva a expressão em Python com ponto decimal: '249.90 * 0.15' para 15%
    de 249,90; '(1200 + 350) / 4'; 'sqrt(144)'; '2 ** 10'. Operadores: + - * / // % ** e funções sqrt, abs, round,
    min, max, constantes pi e e."""
    try:
        value = _eval(ast.parse(expressao.strip().replace(",", "."), mode="eval"))
    except ZeroDivisionError:
        return "Erro: divisão por zero."
    except (ValueError, SyntaxError, TypeError, OverflowError) as exc:
        return f"Erro: não consegui calcular '{expressao}' ({exc})."
    return f"{expressao} = {value:.10g}"


_ureg = pint.UnitRegistry()


def converter_unidades(valor: float, de: str, para: str) -> str:
    """Converte um valor entre unidades de medida (comprimento, massa, volume, velocidade, temperatura, área, tempo,
    energia...). Os nomes das unidades devem ser em inglês, no singular: kilometer, meter, mile, foot, inch,
    kilogram, gram, pound, ounce, liter, gallon, celsius, fahrenheit, kelvin, kilometer/hour, mile/hour, hectare,
    acre, hour, minute. Para dinheiro use converter_moeda."""
    try:
        result = _ureg.Quantity(valor, de).to(para)
    except (pint.errors.PintError, ValueError, AttributeError) as exc:
        return f"Erro: não consegui converter de '{de}' para '{para}' ({type(exc).__name__})."
    return f"{valor:g} {de} = {result.magnitude:.6g} {para}"


def converter_moeda(valor: float, de: str, para: str) -> str:
    """Converte dinheiro entre moedas usando a cotação de referência mais recente (Banco Central Europeu, atualizada
    uma vez por dia útil, não é cotação em tempo real). Use códigos de 3 letras: USD, BRL, EUR, GBP, JPY, CAD, AUD,
    CHF, CNY, MXN. Exemplo: converter_moeda(100, 'USD', 'BRL')."""
    de, para = de.strip().upper(), para.strip().upper()
    if de == para:
        return f"{valor:g} {de} = {valor:g} {para}"
    try:
        r = httpx.get("https://api.frankfurter.dev/v1/latest", timeout=8,
                      params={"amount": valor, "base": de, "symbols": para})
        r.raise_for_status()
        data = r.json()
        return f"{valor:g} {de} = {data['rates'][para]:.2f} {para} (cotação de {data['date']})"
    except (httpx.HTTPError, KeyError, ValueError):
        return f"Erro: não consegui obter a cotação de {de} para {para} agora (moeda não suportada ou sem internet)."


ALL_TOOLS = [data_hora_atual, calcular, converter_unidades, converter_moeda]
