"""Setup portal: the board opens its own Wi-Fi, serves a form at http://192.168.4.1 and saves config.json."""
import network
import socket
import time
from machine import reset

import config
import httpform

AP_SSID = "Agente-IA-Setup"
AP_IP = "192.168.4.1"

PAGE = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Agente IA</title>
<style>body{{font-family:sans-serif;max-width:420px;margin:1.5em auto;padding:0 1em}}
label{{display:block;margin-top:1em;font-weight:bold}}input,button{{width:100%;padding:.6em;font-size:1em;
box-sizing:border-box;margin-top:.3em}}button{{margin-top:1.5em;background:#2874f0;color:#fff;border:0;border-radius:6px}}
.err{{color:#c00}}</style></head><body><h2>Configurar o Agente IA</h2>{msg}
<form method="post" action="/save">
<label>Rede Wi-Fi (2,4 GHz)</label><input name="ssid" list="nets" value="{ssid}" required autocomplete="off">
<datalist id="nets">{options}</datalist>
<label>Senha do Wi-Fi</label><input name="password" type="password" value="{password}">
<label>Endereco do agente (PC)</label><input name="agent_url" value="{agent_url}" placeholder="http://192.168.1.23:8765" required>
<label>Endereco da voz (PC)</label><input name="speech_url" value="{speech_url}" placeholder="http://192.168.1.23:8800" required>
<button>Salvar e reiniciar</button></form></body></html>"""

SAVED = ("<!doctype html><html lang=pt-br><head><meta charset=utf-8>"
         "<meta name=viewport content='width=device-width,initial-scale=1'></head>"
         "<body style='font-family:sans-serif;text-align:center;margin-top:3em'>"
         "<h2>Salvo!</h2><p>A placa vai reiniciar e conectar em <b>{ssid}</b>.</p></body></html>")


def scan():
    """Visible SSIDs, strongest first. Must run before the AP starts."""
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    try:
        nets = sta.scan()
    except OSError:
        return []
    names = []
    for n in sorted(nets, key=lambda n: -n[3]):
        name = n[0].decode("utf-8", "ignore")
        if name and name not in names:
            names.append(name)
    return names


def start_ap():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_SSID, authmode=network.AUTH_OPEN)
    return ap


def _read_request(cl):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = cl.recv(512)
        if not chunk:
            break
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    method, path = lines[0].split(" ")[:2]
    length = 0
    for line in lines[1:]:
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1])
    while len(body) < length:
        chunk = cl.recv(512)
        if not chunk:
            break
        body += chunk
    return method, path, body.decode()


def _send(cl, body, status="200 OK", extra=""):
    body = body.encode()
    cl.sendall(("HTTP/1.1 %s\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: %d\r\n"
                "Connection: close\r\n%s\r\n" % (status, len(body), extra)).encode())
    cl.sendall(body)


def _page(nets, cfg, msg=""):
    cfg = cfg or {}
    options = "".join('<option value="%s">' % httpform.escape(n) for n in nets)
    return PAGE.format(msg=msg, options=options, ssid=httpform.escape(cfg.get("ssid", "")),
                       password=httpform.escape(cfg.get("password", "")),
                       agent_url=httpform.escape(cfg.get("agent_url", "")),
                       speech_url=httpform.escape(cfg.get("speech_url", "")))


def _url(s):
    """Accept 'ip:port' or 'http://ip:port' and normalize to a URL."""
    s = s.strip().rstrip("/")
    return s if "://" in s else "http://" + s


def run(on_ready=None):
    """Block serving the form until the user saves; then reset the board."""
    nets = scan()
    start_ap()
    if on_ready:
        on_ready(AP_SSID, AP_IP)
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", 80))
    srv.listen(2)
    while True:
        cl, _ = srv.accept()
        try:
            cl.settimeout(5)
            method, path, body = _read_request(cl)
            if method == "POST" and path == "/save":
                form = httpform.parse_form(body)
                ssid = form.get("ssid", "").strip()
                agent_url = _url(form.get("agent_url", ""))
                speech_url = _url(form.get("speech_url", ""))
                if not ssid or not agent_url or not speech_url:
                    _send(cl, _page(nets, form, '<p class="err">Preencha a rede e os dois enderecos.</p>'))
                    continue
                config.save({"ssid": ssid, "password": form.get("password", ""),
                             "agent_url": agent_url, "speech_url": speech_url})
                _send(cl, SAVED.format(ssid=httpform.escape(ssid)))
                cl.close()
                time.sleep(2)
                reset()
            elif path == "/":
                _send(cl, _page(nets, config.load()))
            else:
                # captive-portal probes (e.g. /generate_204) and anything else: send to the form
                _send(cl, "", "302 Found", "Location: http://%s/\r\n" % AP_IP)
        except (OSError, ValueError):
            pass
        finally:
            cl.close()
