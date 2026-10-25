"""Pure string helpers for the setup portal (no hardware imports, so they can be tested on CPython)."""


def unquote(s):
    parts = s.replace("+", " ").split("%")
    out = bytearray(parts[0].encode())
    for p in parts[1:]:
        try:
            if len(p) < 2:
                raise ValueError
            out.append(int(p[:2], 16))
            out.extend(p[2:].encode())
        except ValueError:
            out.extend(b"%" + p.encode())
    try:
        return bytes(out).decode()
    except UnicodeError:
        return bytes(out).decode("latin-1")


def parse_form(body):
    form = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            form[unquote(k)] = unquote(v)
    return form


def escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))
