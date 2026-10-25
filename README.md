# Isa — Agente de IA no ESP32-S3

Agente de IA conversacional (voz e display) numa placa ESP32-S3 com MicroPython. A placa é a "cara e os sentidos"
(display, microfone, alto-falante, Wi-Fi); o "cérebro" fica no PC. O agente se chama **Isa** e responde em português
do Brasil, com respostas curtas porque o display é pequeno.

## Arquitetura

O `deepagents` (LangChain) precisa de CPython completo (langchain, langgraph, pydantic) e **não roda em MicroPython**;
o modelo (LLM) roda na nuvem, no OpenRouter. Por isso o projeto é dividido em partes:

```
ESP32-S3 (MicroPython)                 PC (Python 3.12 + uv / Docker)                    nuvem
  display / microfone / alto-falante
        │  áudio (PCM, enquanto grava) ─►  server/  :8765   agente Isa ──HTTPS──►  OpenRouter (LLM, em stream)
        │                                   │  ├── /stt         ─►  api/  :8800  (Whisper)
        └◄── emoção + voz (PCM em stream) ◄─┘  └── /tts/stream  ─►  api/  :8800  (ElevenLabs > Supertonic > Piper)
```

- `firmware/`: cliente MicroPython na placa (display com rosto animado, Wi-Fi + portal, microfone ES8311, alto-falante).
- `server/`: agente WebSocket (Isa) — **orquestra o turno inteiro em streaming** (áudio da placa → STT → LLM → TTS → áudio
  de volta); histórico por conexão. A placa só fala com ele (`agent_url`).
- `api/`: API FastAPI de fala (STT `faster-whisper`; TTS ElevenLabs > Supertonic 3 > Piper, em CPU ou GPU) no PC/Docker; a placa só captura e toca áudio.

Fluxo de voz (push-to-talk), **em streaming nas três pontas**: segurar o BOOT grava e o áudio já vai subindo em blocos
de ~93 ms → ao soltar, o `server/` transcreve (`/stt`) → o LLM responde em stream → cada frase pronta vai ao
`/tts/stream` na hora (a próxima frase é sintetizada enquanto a anterior toca) → a placa toca os blocos de PCM conforme
chegam, com o rosto na emoção da resposta. A voz começa depois da **primeira frase**, não depois da resposta inteira.

Protocolo (um WebSocket, [server/main.py](server/main.py)): placa → servidor `{"type":"audio_start","rate","tts_rate"}`,
quadros binários de PCM, `{"type":"audio_end"}` (ou `audio_cancel`; `{"text": "..."}` pula o STT); servidor → placa
`{"type":"stt","text"}`, `{"type":"emotion","emotion"}`, `{"type":"sentence","text"}`, quadros binários de PCM e
`{"type":"done"}` (ou `{"type":"error","message"}` antes do `done`).

## Estado atual

- [x] Firmware MicroPython gravado e verificado (v1.29.0, variante `SPIRAM_OCT`).
- [x] Servidor `deepagents` + OpenRouter: **testado com chave real**; o agente identifica-se como **Isa**.
- [x] Driver do display [firmware/ili9341.py](firmware/ili9341.py): texto e orientação confirmados (`0x36 = 0x48`).
- [x] Rosto animado com olhos e boca ([firmware/face.py](firmware/face.py)): 8 poses, emoção escolhida pela Isa, boca
  que acompanha o volume da fala e **nenhum texto na tela** (exceto nas telas de configuração do Wi-Fi). Desenho
  conferido numa imagem extraída da placa; **animação e fala ainda não vistas/ouvidas pelo usuário**.
- [x] Wi-Fi + portal de configuração ([firmware/portal.py](firmware/portal.py)): fluxo completo (formulário no celular →
  reinício → conexão) **testado e funcionando**; guarda os dois endereços do PC (agente e voz).
- [x] Microfone (ES8311 I2C + I2S): `main.py` grava enquanto o BOOT é segurado; **transcrição testada com fala real**.
- [x] Streaming nas três pontas ([firmware/converse.py](firmware/converse.py), [server/main.py](server/main.py),
  [server/streaming.py](server/streaming.py)): áudio sobe enquanto grava, LLM em stream dividido em frases, TTS por frase
  e reprodução conforme chega (I2S TX + DAC do ES8311, half-duplex). **Testado na placa** com uma pergunta gravada:
  primeiro áudio 3,6 s depois do fim da pergunta (STT 1,1 s + LLM com ferramenta ~2,3 s + TTS 0,3 s) e depois a fala
  corre sem falhas (83 blocos, nenhum atrasado). Antes o áudio inteiro era sintetizado e baixado antes de tocar.
- [x] Voz local principal: **Supertonic 3, voz F1** (feminina), reserva do ElevenLabs quando os créditos acabam; ver "Como o `/tts` escolhe a voz". Piper (última reserva): `pt_BR-sage_13364-medium`; troca por [voice.py](voice.py) (`PIPER_VOICE` no `.env`),
  sem mudar o modelo nem o código. Também disponíveis em `api/models/`: `pt_BR-faber-medium` e `pt_BR-sage_13364-medium`
  (feminina).
- [x] API de fala local ([api/](api/)): `/stt` (faster-whisper) e `/tts` (Piper), testadas no PC, em Docker e **pela
  placa**.
- [x] TTS ElevenLabs: funcionando com a conta real (plano **Free**, 10.000 caracteres/mês) e a voz padrão **Matilda**
  (`XrExE9yKIg1WjnnlVkGX`). A Raquel (voz da biblioteca, em pt) dá 402 no plano Free; precisa de plano pago. O XTTS
  (`clonagem_audio`) foi removido: a API voltou a ser um único container.
- [ ] Palavra de ativação (wake word) para uso mãos livres.
- [ ] Fonte maior no display.

## Hardware

Placa **ES3N28P** (LCDWiki, "2.8inch ESP32-S3 Display"): ESP32-S3, display IPS 2.8" 240x320 ILI9341 (SPI), **sem touch**
neste SKU, microfone, codec ES8311 + amplificador FM8002E, LED RGB WS2812, slot microSD, carga de bateria.

Confirmado por `esptool flash-id`: ESP32-S3 (QFN56, rev v0.2), 16 MB de flash (quad), 8 MB de PSRAM **octal** embutida
(~8,3 MB de heap livre no MicroPython), USB nativo (USB-Serial/JTAG).

Documentação: <https://www.lcdwiki.com/2.8inch_ESP32-S3_Display> (esquemático, manual e demos MicroPython em
`lcdwiki.com/res/ES3C28P/`).

### Pinos

| Função | GPIO |
|---|---|
| LCD SCLK / MOSI / MISO | 12 / 11 / 13 |
| LCD CS / DC | 10 / 46 |
| LCD backlight (alto = ligado) | 45 |
| LCD RST | ligado ao reset do ESP32-S3 (sem GPIO; o driver faz software reset `0x01`) |
| Codec ES8311 I2C SDA / SCL | 16 / 15 |
| I2S MCLK / BCLK / WS / DIN (mic) / DOUT (alto-falante) | 4 / 5 / 7 / 6 / 8 |
| Habilita amplificador (ativo em **nível baixo**) | 1 |
| LED RGB WS2812 | 42 |
| Botão BOOT | 0 |
| ADC da bateria | 9 |
| microSD | IO38-IO48 (compartilha 42, 45 e 46 com LED e LCD; cuidado ao usar) |

O touch FT6336G (IO15/16/17/18) existe só em outras versões da placa; neste SKU não há touch.

## Ambiente de desenvolvimento

### VS Code

O editor não conhece módulos do MicroPython (`machine`, `framebuf`, `network`). Para autocomplete e sem avisos de import:

```sh
uv venv .venv-ide --python 3.12
uv pip install --python .venv-ide/bin/python micropython-esp32-stubs   # versão 1.29.0, igual ao firmware
```

[pyrightconfig.json](pyrightconfig.json) usa esses stubs só em `firmware/` (via `extraPaths`) e o `server/.venv` em
`server/`. Não use `stubPath`: é global e faria o servidor enxergar o `socket`/`random` do MicroPython. Limitação: o
`time` dos stubs perde para o do CPython, então `time.sleep_ms` fica sem autocomplete (o aviso está desligado em
`firmware/`). Extensão sugerida para enviar código à placa: MicroPico (`paulober.pico-w-go`); ela precisa do grupo
`dialout` (reinicie o VS Code) e **usa a serial com exclusividade**: desconecte-a antes de usar `mpremote`.

Ferramentas instaladas com `uv tool install mpremote esptool` (ficam em `~/.local/bin`; garanta que está no `PATH`).

`.vscode/launch.json` depura o servidor (F5, usa `server/.env`). O código da placa não roda no PC, então
`.vscode/tasks.json` traz tarefas (Ctrl+Shift+P, "Tasks: Run Task") que chamam o `mpremote` via `sg dialout`: enviar ou
rodar o arquivo atual, enviar tudo e reiniciar, e abrir o REPL.

### Acesso à porta serial

A placa aparece em `/dev/ttyACM0` (grupo `dialout`). O usuário foi adicionado ao grupo com
`sudo usermod -aG dialout $USER`, mas sessões abertas antes disso não herdam o grupo. Até reiniciar a sessão, prefixe
os comandos com `sg dialout -c "..."`:

```sh
sg dialout -c "mpremote connect /dev/ttyACM0 exec 'print(1)'"
```

O `/dev/ttyACM0` **reenumera** quando a placa reinicia em outro modo USB (`303a:1001` no bootloader, `303a:4001` com
MicroPython), então permissões dadas com `chmod` se perdem.

### Se a placa travar no USB

Se o `mpremote` passar a falhar com `could not enter raw repl` (ou `OSError: [Errno 71] Protocol error`) e a placa não
responder nem a Ctrl-C, o reset por software não resolve: **desconecte e reconecte o cabo USB** (ou aperte o RST). O
`main.py` reinicia sozinho no power cycle. A suspeita é o vaivém de objetos `I2S` (criar/destruir várias vezes em
testes); o fluxo normal cria um `Mic` e reusa. Depois de qualquer `mpremote exec`, a placa fica no REPL — rode
`mpremote connect /dev/ttyACM0 exec 'machine.reset()'` para voltar ao `main.py`.

### Gravar o firmware MicroPython

Firmware baixado em `firmware/bin/` (ignorado pelo git) de
<https://micropython.org/download/ESP32_GENERIC_S3/>. Esta placa tem PSRAM octal, portanto use a variante
`SPIRAM_OCT`:

```sh
cd firmware/bin
esptool --port /dev/ttyACM0 erase-flash
esptool --port /dev/ttyACM0 --baud 460800 write-flash 0 ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin
```

Se a gravação falhar no meio, repita sem `--baud 460800`. Se a placa não entrar em modo de gravação, segure BOOT (IO0)
e reconecte o USB.

### Enviar e rodar código na placa

```sh
cd firmware
sg dialout -c "mpremote cp ili9341.py :"     # copia um arquivo
sg dialout -c "mpremote run teste.py"        # roda um script sem gravá-lo
sg dialout -c "mpremote"                     # REPL interativo
```

Wi-Fi funciona: o scan encontra redes 2,4 GHz (o ESP32-S3 não usa 5 GHz).

## Firmware: display

[firmware/ili9341.py](firmware/ili9341.py): classe `Display` que herda de `framebuf.FrameBuffer` (RGB565, buffer de
240x320x2 = 150 KB na PSRAM). Desenhe com os métodos do `framebuf` (`fill`, `text`, `fill_rect`...) e chame `show()`
para enviar tudo por SPI (40 MHz).

- Use `color565(r, g, b)` do módulo: ele já troca os bytes, pois o `framebuf` é little-endian e o painel espera
  big-endian.
- Comando `0x36` = `0x48` (BGR + MX): o bit MX corrigiu o texto espelhado que aparecia com `0x08`. Outros ajustes: ordem BGR/RGB e orientação no mesmo comando e `0x21` (inversão, ligada
  por ser painel IPS).
- O texto do `framebuf` usa fonte 8x8 fixa; para texto maior será preciso escalar ou usar fonte própria.

## Firmware: rosto (olhos e boca)

[firmware/face.py](firmware/face.py): dois olhos (elipse branca, íris azul, pupila) e uma boca no mesmo estilo (linha
branca grossa; ao abrir vira uma elipse branca com o interior preto e uma língua azul, a cor da íris), tudo com as
primitivas do `framebuf`, sem imagens. **A tela não mostra texto**: a placa não tem touch para rolar, então o estado é
sempre expressão. A única exceção são as telas de configuração do Wi-Fi (nome da rede e endereço do portal), que não têm
outro jeito de aparecer.

Olhos e boca ficam em **faixas horizontais separadas** (`EYE_BAND`, `MOUTH_BAND`) e `Display.show_rows()` envia só as
linhas da faixa (o buffer é por linha, então são contíguas): olhos ~22 ms por quadro, boca ~13-15 ms (a tela inteira
levava 39 ms). É isso que deixa a boca acompanhar a fala.

| Pose | Olhos | Sobrancelhas | Boca | Quando |
|---|---|---|---|---|
| `neutra` | redondos | levemente arqueadas | linha curta | ocioso (pisca e olha em volta) |
| `feliz` | arcos fechados `^ ^` | altas e arqueadas | sorriso | emoção da Isa |
| `triste` | pálpebra caída para fora, olhar baixo | pontas internas para cima | curva para baixo | emoção; erro de rede/STT/agente |
| `curiosa` | tamanhos diferentes, olhar para cima/lado | a direita bem erguida | meio sorriso torto | emoção |
| `surpresa` | maiores, íris pequena | altas e arqueadas | "o" | emoção |
| `confusa` | um olho menor | uma franzida, outra erguida | ondulada | emoção; "não entendi", fala curta demais |
| `ouvindo` | bem abertos | erguidas, atentas | linha curta | enquanto o BOOT está apertado |
| `pensando` | olhar **fixo** para cima e para o lado, pisca devagar | uma franzida, outra arqueada (como o emoji 🤔) | linha pequena e torta | do fim da gravação até o áudio estar pronto |

- **Emoção:** a Isa abre cada resposta com uma etiqueta (`[feliz]`, `[triste]`, `[curiosa]`, `[surpresa]`, `[confusa]`,
  `[neutra]`). O [server/emotion.py](server/emotion.py) separa a etiqueta e envia `{"reply", "emotion"}`; a etiqueta
  **não** vai para o TTS. Sem etiqueta ou com uma desconhecida, vale `neutra`. A etiqueta fica no histórico da conversa
  para o modelo continuar usando.
- **Boca na fala:** `tts.play(..., on_level=face.speak_level)` chama o rosto a cada trecho de ~93 ms com o volume (0 a 1,
  lido do byte alto das amostras); a boca abre em proporção e o rosto pisca de vez em quando. Medido com fala real: 47
  trechos, volume de 0,06 a 0,97, no máximo 15 ms por quadro.
- **"Pensando" em paralelo:** `think_start()/think_stop()` rodam a animação numa segunda thread (`_thread`, o ESP32-S3
  tem 2 núcleos) enquanto a thread principal espera a rede (STT, agente e download do áudio). Funcionou na placa.
  A primeira versão (olhos indo de um lado a outro e boca ondulando) parecia agitada demais; a segunda (três pontos
  tipo "digitando...") foi trocada por uma expressão parada inspirada no emoji 🤔 (sobrancelhas assimétricas, olhar para
  cima e para o lado, boca pequena e torta), com só uma piscada lenta a cada ~2-4 s como sinal de vida. Foi a que o
  usuário aprovou.
- `play()` agora termina escrevendo ~370 ms de silêncio: sem isso `deinit()` podia cortar o final da fala que ainda
  estava no buffer de DMA.
- **Sobrancelhas em todas as poses:** `brows` é uma tupla de segmentos `(x0, y0, x1, y1, arco)` desenhados como linhas
  grossas na faixa dos olhos; `_DEFAULT` tem as da pose neutra e cada pose da tabela `POSES` troca as suas. Ficam acima de
  y≈23 para caberem na faixa (`EYE_BAND` começa em 20).
- **Ajustes:** posições e tamanhos (`EYE_Y`, `RX`, `RY`, `MOUTH_Y`, `LINE_R`) e a tabela `POSES` ficam no topo do arquivo.
  O desenho pode ser conferido sem olhar a placa: desenhar na placa, extrair `d.buf` em base64 pelo `mpremote` e
  convertê-lo em PNG (RGB565 big-endian).
- **Telas do boot:** não há mais "Segure BOOT..." escrito; durante os 3 s iniciais o rosto fica ocioso e quem segurar o
  BOOT entra no portal.

### main.py da placa

[firmware/main.py](firmware/main.py) é executado pelo MicroPython a cada boot. Ele faz o fluxo de boot (BOOT/portal,
Wi-Fi), instancia o `Mic` e entra no **laço de voz**: `face.idle(until=botão)` mantém o rosto vivo e é interrompido
assim que o BOOT é pressionado; então `listen()` grava, transcreve, consulta o agente, baixa o áudio e fala com a boca
animada. Não confundir com `server/main.py`, que roda no PC.

`face.idle()` é um laço (ticks de 30 ms) que mantém o REPL ocupado: use Ctrl-C no `mpremote` para interromper;
`mpremote cp` interrompe o programa sozinho.

## Firmware: Wi-Fi e portal de configuração

Não há credenciais no código. Elas ficam em `config.json` na flash da placa (ignorado pelo git), gravado pelo portal:

```json
{"ssid": "...", "password": "...", "agent_url": "http://IP:8765", "speech_url": "http://IP:8800"}
```

São **dois endereços** no PC: `agent_url` é o agente WebSocket (`server/`, porta 8765) e `speech_url` é o serviço de voz
(`api/`, `/stt` e `/tts`, porta 8800). Nada do OpenRouter fica na placa — quem o acessa é o `server/`.

O `config.json` também pode ser gerado do `.env` da raiz, que é a fonte única: `AGENT_URL` e `SPEECH_URL`. Rode
[gen_config.py](gen_config.py) e envie o arquivo para a placa (`mpremote cp firmware/config.json :`). As credenciais de
Wi-Fi já gravadas na placa são mantidas se `WIFI_SSID`/`WIFI_PASSWORD` não estiverem no `.env` (que é ignorado pelo git).

Fluxo do [main.py](firmware/main.py) a cada boot:
1. Mostra "Segure BOOT para configurar o Wi-Fi" por 3 s. Se o BOOT (IO0) for pressionado, abre o portal. Segure o
   botão **depois** de ligar: com BOOT pressionado durante o reset o chip entra em modo de gravação.
2. Sem `config.json`: abre o portal.
3. Com `config.json`: conecta (20 s de timeout) e mostra o IP. Se falhar, abre o portal (o arquivo é mantido; reiniciar
   tenta de novo).
4. Entra no laço de voz (rosto + push-to-talk).

Portal ([firmware/portal.py](firmware/portal.py)): a placa cria a rede aberta **`Agente-IA-Setup`**, o display mostra
`http://192.168.4.1`, e a página lista as redes encontradas (o campo aceita digitar redes ocultas) e pede a senha e os
dois endereços (agente e voz; aceita `ip:porta` ou `http://ip:porta`). Ao salvar, grava `config.json` e reinicia.
Requisições desconhecidas (testes de portal cativo dos celulares) são redirecionadas ao formulário; não há servidor DNS,
então abra o endereço manualmente se o celular não abrir a página sozinho. O formulário vem preenchido com a
configuração atual, inclusive a senha.

Arquivos: [wifi.py](firmware/wifi.py) (`connect()` devolve o IP ou levanta `OSError` e desliga a economia de energia do
Wi-Fi, `PM_NONE`: com ela a leitura caía de ~245 para ~100 KB/s; o sinal medido era fraco, -79 dBm),
[config.py](firmware/config.py) (`load`/`save`/`clear`) e [httpform.py](firmware/httpform.py) (decodificação do
formulário, sem imports de hardware, testável no CPython). Só redes 2,4 GHz.

## Firmware: voz (microfone, agente e playback)

O microfone passa pelo codec ES8311 (I2C em 0x18, [es8311.py](firmware/es8311.py)). O `machine.I2S` do MicroPython
**não gera MCLK** no ESP32-S3 (passar `mck=` dá `TypeError`), então o codec usa o clock do próprio BCLK: a taxa é
**22050 Hz** (BCLK = 22050 × 16 × 2 = 705600 Hz, valor presente na tabela de coeficientes do ES8311) e o `/stt`
reamostra para 16 kHz.

- [es8311.py](firmware/es8311.py): `ES8311.init()` reseta e configura o clock (MCLK a partir do BCLK), o formato I2S
  slave de 16 bits e o microfone analógico com ganho máximo; `volume(pct)` controla o volume do DAC (alto-falante).
- [mic.py](firmware/mic.py): `Mic` cria o codec e o I2S RX (mono, 16 bits). `record(held, max_s)` grava enquanto
  `held()` for verdadeiro; na primeira vez descarta os primeiros quadros até o ADC estabilizar. `boot_button()` devolve
  o BOOT (IO0).
- [ws.py](firmware/ws.py): cliente WebSocket mínimo (handshake + quadros de texto e **binários**, resposta a ping); o
  módulo `websocket` da placa é só um wrapper de stream, sem handshake, por isso não é usado. Os quadros da placa levam
  chave de máscara **zero** (o bit de máscara é obrigatório, o valor da chave não): fazer XOR byte a byte em Python custava
  ~20 ms por bloco de 4 KB, mais que o tempo do microfone para enchê-lo. A recepção lê num buffer reaproveitado
  (`readinto`, sem alocar por bloco) e `alive()` detecta que o servidor fechou a conexão enquanto ociosa.
- [mic.py](firmware/mic.py): `stream(held, send)` entrega cada bloco ao `send` enquanto grava (em vez de acumular).
- [tts.py](firmware/tts.py): `Speaker` (I2S TX) com `start()`, `write(bloco)` e `stop()`; só liga o amplificador enquanto
  toca. `write` bloqueia quando o buffer de DMA enche, e é isso que ajusta o ritmo da rede ao do áudio. `on_level` anima a
  boca a cada bloco.
- [converse.py](firmware/converse.py): um turno de voz pelo WebSocket (`turn()`), com a conexão mantida entre turnos (o
  servidor guarda o histórico por conexão). Falhas de rede levantam `OSError` e a próxima conversa reconecta.
- [main.py](firmware/main.py): alterna o rosto ocioso com o push-to-talk — segurar o BOOT mostra a pose `ouvindo` e
  grava; ao soltar, a pose `pensando` fica ativa até o primeiro bloco de áudio; então o rosto assume a **emoção** da
  resposta e **fala** com a boca acompanhando o volume. Falhas viram expressão (rede/agente/STT
  fora do ar: `triste`; não entendi ou fala menor que ~0,5 s: `confusa`). Os detalhes do rosto estão em "Firmware:
  rosto".
- O amplificador (IO1, ativo em **nível baixo**) fica desligado durante a captura e é ligado só no playback; como o I2S
  é half-duplex (o RX é fechado antes de tocar), a placa não escuta a própria voz.

## Servidor

Requer `uv` e Python 3.12.

```sh
cd server
cp .env.example .env     # preencha OPENROUTER_API_KEY
uv run python main.py    # escuta em 0.0.0.0:8765
```

- [server/agent.py](server/agent.py): `create_deep_agent` com `ChatOpenAI` apontando para
  `https://openrouter.ai/api/v1`. O **system prompt** define o agente como **Isa** e pede respostas curtas em português,
  pois o display é pequeno. Depois de editar o prompt, **reinicie o `server/`** (o import acontece no boot).
- [server/main.py](server/main.py): servidor WebSocket que conduz o turno em streaming (protocolo no começo deste
  README). `agent.astream` entrega o texto do LLM; o [server/streaming.py](server/streaming.py) (`ReplySplitter`) separa a
  etiqueta de emoção (enviada assim que aparece, antes da 1ª frase terminar) e fecha frases só quando há espaço depois da
  pontuação (não corta "3.5"; trechos com menos de 12 caracteres se juntam à frase seguinte). Cada frase vira uma
  `SentenceAudio` sintetizada em segundo plano. [server/speech.py](server/speech.py) é o cliente da API de voz
  (`SPEECH_URL`, padrão `http://localhost:8800`). O histórico é mantido por conexão. Testes: `cd server && PYTHONPATH=. uv run pytest`.
- Variáveis (`server/.env`): `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (hoje `deepseek/deepseek-v4.1-flash`), `HOST`,
  `PORT`.
- O ESP32 precisa alcançar o PC pela rede local: use o IP do PC e libere as portas **8765** (agente) e **8800** (voz) no
  firewall. O `server/` não guarda áudio nem fala com a placa fora do WebSocket.

### Arquivos do agente (pasta persistente)

Por padrão o `deepagents` guarda os arquivos que o agente "cria" num sistema de arquivos **virtual na memória**
(`StateBackend`): eles não vão para o disco e somem quando a resposta termina. Agora o [server/agent.py](server/agent.py)
usa `FilesystemBackend(root_dir=WORKSPACE_DIR, virtual_mode=True)`:

- **Onde ficam:** `server/workspace/` (ignorada pelo git); outra pasta com `WORKSPACE_DIR` no `server/.env`.
- **Persistem** entre conversas e reinícios: testado, um arquivo criado numa conversa foi lido em outra, nova e sem
  histórico.
- **Confinado:** `virtual_mode=True` trata `/nota.md` como `<pasta>/nota.md` e rejeita `..`; pedir `../../fora.txt` foi
  recusado e nada foi criado fora da pasta. O backend não executa comandos, só lê e escreve texto.
- O prompt manda criar arquivos **só quando o usuário pedir** e dizer o nome, para a Isa não gastar tempo com arquivos de
  planejamento no meio de uma resposta falada.
- O `server/` roda direto no PC (não em Docker). Se um dia for para um container, a pasta vira um **volume** montado em
  `WORKSPACE_DIR`, senão os arquivos se perdem ao recriar o container.

### Ferramentas do agente

[server/tools.py](server/tools.py), passadas ao agente em `create_deep_agent(tools=...)`. Cada uma devolve texto curto
que o modelo transforma em fala; erros voltam como texto ("Erro: ...") para o modelo explicar, em vez de inventar.

| Ferramenta | Para quê | Observações |
|---|---|---|
| `data_hora_atual` | data, dia da semana e hora | fuso por `TIMEZONE` (padrão `America/Sao_Paulo`) |
| `calcular` | contas, porcentagens | avalia a expressão por AST (só números, `+ - * / // % **`, `sqrt abs round min max`, `pi e`); rejeita qualquer outra coisa e expoente > 1000 |
| `converter_unidades` | medidas e temperatura | usa `pint`; nomes das unidades em inglês (`mile`, `kilometer`, `celsius`...) |
| `converter_moeda` | dinheiro | [Frankfurter](https://frankfurter.dev) (cotação de referência do BCE, atualizada 1× por dia útil, **não é em tempo real**); sem chave |

Testes: `cd server && uv run python -m pytest` (21 testes, sem rede; o câmbio é simulado). Com o modelo real, cada
pergunta usou a ferramenta certa (hora, 15% de 249,90, 26 milhas em km, 100 dólares em reais, 25 °C em °F) e a pergunta
de conhecimento geral não usou nenhuma. Cada chamada de ferramenta soma ~1-3 s à resposta. O prompt do agente pede
fala natural, sem markdown, e para nunca calcular de cabeça.


## API de fala (STT e TTS locais)

Serviço separado em [api/](api/) (FastAPI, mesmo monorepo). Roda no PC, sem custo por uso e sem enviar áudio para
fora. O Whisper não roda no ESP32-S3 (modelo de dezenas de MB, PyTorch e CPU de 240 MHz), por isso a placa só captura e
toca áudio.

```sh
cd api
uv sync
uv run python -m piper.download_voices --download-dir models pt_BR-jeff-medium   # voz oficial (~63 MB), uma vez
cp .env.example .env
uv run uvicorn app:app --host 0.0.0.0 --port 8800
```

Na primeira execução o `faster-whisper` baixa o modelo `small` (~460 MB) para `~/.cache/huggingface`.

| Endpoint | Entrada | Saída |
|---|---|---|
| `GET /health` | | `{"status": "ok"}` |
| `POST /stt?sample_rate=16000` | corpo = WAV, ou PCM cru 16-bit mono little-endian na taxa indicada | `{"text": "...", "duration": s}` |
| `POST /tts/stream` | JSON `{"text", "sample_rate"?, "backend"?}` | PCM cru 16-bit mono **enviado enquanto é gerado** (chunked); cadeia ElevenLabs `/stream` > Supertonic > Piper |
| `POST /tts` | JSON `{"text", "sample_rate"?, "format"?}` com `format` = `wav` ou `pcm` | WAV, ou PCM cru com o cabeçalho `X-Sample-Rate` |

- O `/stt` aceita WAV de 16 bits (mono ou estéreo, qualquer taxa) ou PCM cru, e converte para 16 kHz mono. É o formato
  que o microfone da placa entregará, sem precisar montar cabeçalho WAV no ESP32.
- O `/tts` segue a cadeia ElevenLabs > Supertonic > Piper (ver "Como o `/tts` escolhe a voz"). Com `sample_rate` ele
  reamostra para a taxa do codec da placa (interpolação linear, com filtro passa-baixa ao descer de taxa).
- Configuração em `api/.env`: `WHISPER_MODEL`, `WHISPER_COMPUTE_TYPE`, `WHISPER_LANGUAGE`; a voz Piper vem do
  `PIPER_VOICE` do `.env` da raiz (o `docker-compose.yml` repassa; ver "Trocar a voz").
- O Whisper roda em CPU (`int8`), sem GPU: a API fica leve (~1,1 GB entre venv, modelo e voz). Medido: ~1,1 s para
  transcrever 4 s.
- Testado: texto → `/tts` → `/stt` devolve o texto com pequenas diferenças, e entradas inválidas respondem 400/422.
  Com a placa, o ciclo completo (falar no microfone → display/resposta falada) foi validado com fala real.

## Docker

[docker-compose.yml](docker-compose.yml) na raiz sobe os serviços de fala. Configuração em `.env` (copie de
[.env.example](.env.example); defina `APP_UID`/`APP_GID` com `id -u` e `id -g`, para o container não criar arquivos de
root no seu cache do Hugging Face). O mesmo `.env` guarda `AGENT_URL`/`SPEECH_URL` usados por
[gen_config.py](gen_config.py) para gerar o `config.json` da placa (ver "Wi-Fi e portal de configuração"); a porta
interna do container é fixa em 8800, então `SPEECH_PORT` (mapeamento no host) deve bater com a porta do `SPEECH_URL`.

```sh
docker compose up -d --build      # api (STT + TTS) em http://<ip-do-pc>:8800
docker compose down
```

- **`api`** ([api/Dockerfile](api/Dockerfile), 1,2 GB): único container. Os modelos não ficam na imagem: a voz Piper
  vem de `api/models/` e o modelo do Whisper do `~/.cache/huggingface` do host (`HF_CACHE`), ambos por bind mount.
  **A API não tem autenticação e escuta em 0.0.0.0**: qualquer máquina da rede local pode usá-la (e, com o ElevenLabs
  ligado, gastar os caracteres da sua assinatura).
- O container usa o fuso `TZ=America/Sao_Paulo` (padrão do compose; antes ficava em UTC, com 3 h de diferença nos logs).
  A ferramenta de data/hora do agente (`server/`, que roda no PC) usa `TIMEZONE`, também `America/Sao_Paulo` por padrão, e
  independe do fuso do sistema; o `tzdata` está nas dependências para funcionar também em imagens enxutas.
- A chave do ElevenLabs (`ELEVENLABS_API_KEY`) é segredo: fica só no `.env` (fora do git) e é repassada ao container
  como variável de ambiente.

### Como o `/tts` escolhe a voz

`/tts` e `/tts/stream` tentam os backends **em cadeia**, até um funcionar: **ElevenLabs** (nuvem, o mais natural; precisa de
chave e créditos) → **Supertonic 3** (local, voz feminina `F1`) → **Piper** (local, sempre disponível). `backend` no corpo
(`eleven`, `supertonic` ou `piper`) põe esse na frente; sem ele vale `TTS_BACKEND` (padrão `auto`). O cabeçalho
`X-TTS-Backend` diz qual voz foi usada e `GET /health` lista a cadeia atual.

- **Sem créditos no ElevenLabs** (o plano Free tem 10.000 caracteres/mês; acabando, ele responde **401**), 402 ou 429: o
  ElevenLabs sai da cadeia por `ELEVENLABS_COOLDOWN_S` (600 s). Sem isso cada frase de cada resposta pagava ~0,5 s de uma
  tentativa falha antes de cair para a próxima voz.
- **Supertonic 3** ([Supertone/supertonic-3](https://huggingface.co/Supertone/supertonic-3), pacote `supertonic`): ONNX,
  ~99M parâmetros, 31 idiomas (`pt`), 10 vozes (F1-F5 femininas, M1-M5 masculinas). Escolhido ouvindo amostras contra
  Piper (jeff, sage) e Kokoro (`pf_dora`). O modelo (~390 MB) é baixado na primeira subida para `SUPERTONIC_CACHE`
  (padrão `~/.cache/supertonic3`, montado no container). Gera a 44,1 kHz; `audio.resample` passa um filtro passa-baixa
  antes de descer para os 22,05 kHz da placa. Caracteres que ele não conhece (emoji etc.) viram espaço: senão ele recusa
  a frase inteira. Ajustes: `SUPERTONIC_VOICE`, `SUPERTONIC_SPEED` (1,05), `SUPERTONIC_STEPS` (8). **Atenção:** o
  repositório oficial foi arquivado em jul/2026 (sem novas versões) e os pesos são OpenRAIL-M.
- **Medido** (frase de 3,2 s): CPU 1,19 s com 8 passos, 0,85 s com 5 passos; **GPU (RTX 3050) 0,06 s**. Pico de RAM do
  Supertonic ~650 MB; o container inteiro (Whisper + Piper + Supertonic) ~1 GB na CPU.

**CPU ou GPU:** `DEVICE=auto` (padrão) usa a GPU quando o container a enxerga e a CPU caso contrário, no Whisper e no
Supertonic. A imagem padrão é só CPU; para GPU (precisa do NVIDIA Container Toolkit no host):

```sh
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

O `GPU=1` troca o `onnxruntime` pelo `onnxruntime-gpu[cuda,cudnn]` e instala as bibliotecas CUDA 12/cuDNN 9 do Whisper.
A imagem passa de ~1,2 GB para **~10 GB**. Medido na GPU: STT de 5,7 s de fala em 0,15 s (CPU ~1,1 s) e TTS em 0,06 s por
frase. O container tem `mem_limit` (`API_MEM_LIMIT`, padrão 4g): se um modelo estourar, morre só ele, não o PC.

**Modelos pesados (XTTS, Chatterbox, Qwen3-TTS):** testar sempre com limite de memória. Um teste do XTTS-v2 fora do
container (PyTorch + CUDA) esgotou a RAM do PC (23 GB, 18 já em uso) e foi preciso reiniciar. Pela pesquisa, Chatterbox
multilingual é "impraticável na CPU" e o Qwen3-TTS fica no limite do tempo real; para um servidor só com CPU, não servem.

ElevenLabs (`POST /v1/text-to-speech/{voice_id}`, cabeçalho `xi-api-key`): a API pede PCM cru de 16, 22,05 ou 24 kHz (o
mais próximo, acima da taxa pedida) e reamostra para a taxa da placa; 44,1 kHz exige plano Pro, então não é usado. O
modelo padrão é `eleven_multilingual_v2` (`ELEVENLABS_MODEL`). Cada requisição consome caracteres do plano. Testado com
um servidor simulado (rota, cabeçalho, formato PCM, 400 sem configuração) e com a conta real (Matilda). O
ElevenLabs leva ~2,2 s para uma frase de ~7 s, contra ~0,6 s do Piper local. Vozes da biblioteca (como a Raquel, `402
paid_plan_required`) exigem plano pago; voz padrão funciona no Free.

**XTTS removido:** o container `tts-clone` (voz clonada a partir do projeto `clonagem_audio`) foi retirado. Para quem
quiser retomar: o `requirements.txt` daquele projeto não fixa versões e quebra com as atuais (`transformers` 5.x removeu
`BeamSearchScorer`; funcionou com `torch` 2.5.1, `torchaudio` 2.5.1 e `transformers` 4.40.2); o serviço nunca move o
modelo para a GPU (faltava `.to("cuda")`); grava o WAV a 22050 Hz enquanto o XTTS v2 gera a 24000 Hz (suspeita não
confirmada); e o modelo é distribuído sob a licença CPML do Coqui (uso não comercial).

### Trocar a voz (Piper)

A voz é só um **estilo**: o motor Piper e todo o código não mudam. É um par `.onnx` + `.onnx.json` em `api/models/`
(montado em `/models/piper` no container); o ativo é o `PIPER_VOICE` do `.env`. O [voice.py](voice.py) ajuda:

```sh
./voice.py list                                    # vozes em api/models
./voice.py use pt_BR-faber-medium                  # troca a voz ativa
./voice.py add rhasspy/piper-voices pt/pt_BR/jeff/medium/pt_BR-jeff-medium   # baixa e ativa (caminho interno do repo)
docker compose up -d                               # recria o container com a voz nova
```

Onde ouvir/baixar vozes:

- **Prévia de todas as vozes Piper** (buscar por idioma e tocar): <https://sahadebjit13.github.io/piper-tts-preview/>
- **Amostras oficiais do Piper** (uma por voz): <https://rhasspy.github.io/piper-samples/>
- **Lista oficial pt_BR** (`cadu`, `edresson`, `faber`, `jeff`): <https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR>
- **Vozes comunitárias pt-BR** (ex.: `sage`, feminina): <https://huggingface.co/collections/srxz/vozes-tts-pt-br-piper>
- **Mais vozes pt_BR/pt_PT** (`dii-high`, `miro-high`, ...): <https://k2-fsa.github.io/sherpa/onnx/tts/all/Portuguese/index.html>

### STT: referência do `jeff_ai`

A rota `/api/attachments/{id}/transcribe` do `jeff_ai` exige autenticação, Postgres e storage, então não serve à placa.
O que ela faz de fato é `faster-whisper` `small`, `int8`, CPU, `language=pt`, `beam_size=1`, com conversão por ffmpeg
para WAV 16 kHz mono antes. O `/stt` daqui usa o mesmo motor e as mesmas configurações; não usa ffmpeg porque a placa
envia PCM/WAV. Se um dia a placa enviar outro formato (ogg, webm), falta essa conversão.

## Rosto 3D (retrato)

Opção ao lado do rosto de formas ([firmware/face.py](firmware/face.py)): uma personagem 3D estilizada, montada a partir
de imagens pré-renderizadas. O ESP32-S3 não renderiza 3D nem recebe vídeo (a placa baixa ~250 KB/s e um quadro cru de
240x320 tem 150 KB), então a placa só **troca imagens e peças**. O [main.py](firmware/main.py) usa o
[portrait.py](firmware/portrait.py) se `/avatar/` estiver na placa; senão cai no rosto de formas.

- **Origem das imagens:** geradas por IA a partir de uma referência (estilo Pixar, óculos, trança), em fundo verde. A
  fonte atual é uma **sprite sheet de 12 quadros** (3 colunas x 4 linhas, numa só geração) em
  `design/avatar/folha_sprite.jpg`, na ordem: 1 piscando, 2 meio fechado, 3 boca "a", 4 "o", 5 "e", 6 "u", 7 feliz,
  8 triste, 9 surpresa, 10 curiosa, 11 pensando, 12 séria (usada como face neutra). **Falta o quadro "confusa"** (o prompt
  tinha 13 itens e saíram 12): por enquanto vem da primeira folha (`folha_original.jpg`, quadro 15, outra geração, com
  traço um pouco diferente). `design/` e `firmware/avatar/` estão no `.gitignore`: a referência parece de banco de
  imagens, confira a licença.
- **Por que a sprite sheet é melhor:** medido nos óculos, a variação de tamanho entre quadros caiu de 11% (folha antiga) para
  4%, os quadros têm ~25% mais resolução (óculos de ~205 px contra ~164 px) e, principalmente, as bocas "a/o/e/u" têm os
  **mesmos olhos** da face neutra, o que a folha antiga não tinha (os olhos pulavam ao trocar a imagem inteira).
- **Topo do cabelo:** as cabeças encostam na borda da célula e, em 5 quadros, a copa saía cortada reta; o gerador usa o topo
  do quadro neutro nos outros (mistura entre as linhas 76 e 90 da tela).
- **Gerar os arquivos:** `uv run --no-project --with pillow --with numpy --with scipy --with opencv-python-headless python tools/build_avatar.py`.
  O [tools/build_avatar.py](tools/build_avatar.py) recorta a grade, remove o verde (com limpeza do contorno), alinha as
  cabeças pela moldura dos óculos e depois **registra cada quadro sobre o neutro** (`register()`: ECC com deslocamento +
  rotação, só sobre cabeça, cabelo e óculos, sem boca nem queixo; sobravam 3 a 10 px e ~1° entre quadros) e converte para RGB565 big-endian
  com *dither* ordenado (disfarça as faixas de cor da pele). Saída: `firmware/avatar/*.raw`, 21 arquivos, 0,5 MB (apaga os `.raw` antigos de imagem inteira).
- **Enviar à placa:** `cd firmware && mpremote mkdir :avatar; for f in avatar/*.raw; do mpremote cp $f :$f; done` e
  `mpremote cp portrait.py :`. A placa tem 13,9 MB livres no flash.
- **Como monta o rosto:** tudo é carregado na RAM no boot (~0,5 MB; há 8 MB de PSRAM). Existe **uma só imagem inteira**, a
  neutra; **toda** pose, emoção e quadro de fala é a face neutra + peça dos olhos (olhos e sobrancelhas, 160x84) + peça da
  boca (96x56), coladas em caixas fixas. Assim a **cabeça nunca se move nem muda de tamanho** entre poses (o desalinhamento
  vinha de trocar a imagem inteira da tela: cada imagem gerada tinha a cabeça alguns pixels diferente).
  - **Fala:** a energia **média** de cada trecho de ~46 ms (não o pico: a voz sai perto do máximo em todo bloco e a boca
    ficava sempre no "a"), normalizada por uma referência que se adapta ao volume, escolhe a boca (fechada, "u", "o", "e",
    "a"); a emoção continua nos olhos. "Fechada" ao falar é sempre a boca neutra: a da emoção `feliz` mostra os dentes e
    parecia boca aberta. Na fala de teste: 36% fechada, o resto distribuído entre as quatro vogais.
  - **Piscada** em todas as poses, menos `feliz` (os olhos já são arcos fechados).
- **Peças com máscara (corrigido após testar na placa):** a primeira versão colava retângulos e apareceram sobrancelhas
  duplicadas (a caixa dos olhos começava abaixo das sobrancelhas mais altas) e a boca "quebrada" (o retângulo cortava o
  contorno do queixo e do cabelo, que muda um pouco entre as imagens geradas). Agora cada peça só substitui os pixels que
  realmente mudam em relação à neutra (diferença > 60 na soma RGB, dilatada e suavizada), e a boca fica limitada a uma
  elipse em volta dos lábios (`MOUTH_ZONE`; menor para o `pensando`, cuja imagem tem uma covinha no queixo). Conferido nos
  quadros extraídos da placa em cinco bocas e vários volumes.
- **Medido na placa** (antes, no modo de imagens inteiras: pose 44 ms, troca de boca ~7 ms): o framebuffer extraído da placa
  em `feliz`, `confusa` + boca "a" e `triste` + boca "u" ficou idêntico ao da simulação no PC, com a cabeça no mesmo lugar.
- **Armadilha do MicroPython:** atribuir fatias linha a linha (`buf[a:b] = ...`) custa ~3 ms **por linha** (move o resto
  do buffer de 150 KB): a primeira versão levava 160 ms para trocar a boca. Usar `FrameBuffer.blit`, que copia em C
  (160 ms -> ~7 ms).
- **Limites:** o tom da pele muda um pouco entre as imagens geradas e, como só olhos e boca vêm de cada quadro, qualquer
  detalhe fora das caixas (bochechas, cabelo) fica sempre o da neutra. Se uma emoção nova precisar de algo fora delas, é
  preciso ampliar `EYES`/`MOUTH` (em `tools/build_avatar.py` **e** em `firmware/portrait.py`, que devem coincidir).
- **Numeração das 16 expressões (os rótulos da folha se repetem):** 1 piscando, 2 meio fechado, 3 boca "a", 4 e 5 boca
  "o", 6 boca "e", 7 e 8 boca "u", 9 feliz, 10 triste, 11 e 13 surpresa, 12 surpresa preocupada, 14 curiosa, 15 confusa,
  16 pensando.
