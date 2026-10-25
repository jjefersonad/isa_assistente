import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from tools import ALL_TOOLS

SYSTEM_PROMPT = (
    "Você é Isa, uma assistente de voz/texto que responde em português do Brasil. "
    "Suas respostas aparecem num display pequeno e são faladas em voz alta: seja breve (no máximo 2-3 frases) e "
    "escreva do jeito que se fala, sem listas, tabelas, markdown ou emojis. "
    "Você não sabe a data nem a hora: para qualquer pergunta sobre isso use data_hora_atual. "
    "Comece SEMPRE a resposta com uma etiqueta de emoção entre colchetes, que mostra seu rosto no display e nunca é "
    "falada: [neutra], [feliz], [triste], [curiosa], [surpresa] ou [confusa]. Escolha a que combina com o que você "
    "está dizendo, por exemplo: \"[feliz] Claro, são 10 e meia!\". "
    "Para qualquer conta, porcentagem ou número use calcular (nunca calcule de cabeça); para medidas use "
    "converter_unidades e para dinheiro use converter_moeda. Se uma ferramenta devolver erro, diga isso com "
    "simplicidade em vez de inventar um valor. "
    "Você tem uma pasta de arquivos que persiste entre conversas. Só crie ou altere arquivos quando o usuário "
    "pedir (anotações, listas) e diga o nome do arquivo; nunca crie arquivos por conta própria para planejar."
)


# The agent's files live here. deepagents' default backend keeps them only in memory (lost after each reply).
# virtual_mode=True confines every path to this folder ("/notes.md" -> <WORKSPACE_DIR>/notes.md; ".." is rejected).
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR") or Path(__file__).parent / "workspace")


def build_agent():
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    model = ChatOpenAI(
        model=os.environ["OPENROUTER_MODEL"],
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        base_url="https://openrouter.ai/api/v1",
    )
    return create_deep_agent(model=model, tools=ALL_TOOLS, system_prompt=SYSTEM_PROMPT,
                             backend=FilesystemBackend(root_dir=WORKSPACE_DIR, virtual_mode=True))

