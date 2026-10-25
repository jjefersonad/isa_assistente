#!/usr/bin/env python3
"""Switch the Piper TTS voice used by api/ without touching the model or the code.

A voice is an .onnx + .onnx.json pair in api/models (mounted at /models/piper inside the container).
The active one is named by PIPER_VOICE in .env. After changing it, recreate the container.

Usage:
    ./voice.py list                                   # voices already in api/models
    ./voice.py use <stem>                             # set PIPER_VOICE to <stem>.onnx
    ./voice.py add <hf_repo> <path> [revision]         # download <path>.onnx[.json] from Hugging Face and use it
                                                       # <path> may be nested (official voices are)
                                                       # e.g. ./voice.py add rhasspy/piper-voices pt/pt_BR/jeff/medium/pt_BR-jeff-medium

Then: docker compose up -d
"""
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(ROOT, "api", "models")
ENV = os.path.join(ROOT, ".env")
CONTAINER_DIR = "/models/piper"


def active_stem():
    try:
        with open(ENV) as f:
            for line in f:
                if line.strip().startswith("PIPER_VOICE="):
                    return os.path.basename(line.split("=", 1)[1].strip()).replace(".onnx", "")
    except OSError:
        pass
    return None


def set_env(stem):
    path = os.path.join(CONTAINER_DIR, stem + ".onnx")
    lines, done = [], False
    if os.path.exists(ENV):
        with open(ENV) as f:
            lines = f.readlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("PIPER_VOICE="):
            lines[i] = "PIPER_VOICE=%s\n" % path
            done = True
    if not done:
        lines.append("PIPER_VOICE=%s\n" % path)
    with open(ENV, "w") as f:
        f.writelines(lines)
    print("PIPER_VOICE ->", path)


def cmd_list():
    cur = active_stem()
    for name in sorted(os.listdir(MODELS)):
        if name.endswith(".onnx"):
            stem = name[:-5]
            print("*" if stem == cur else " ", stem)


def cmd_use(args):
    stem = args[0]
    if not os.path.exists(os.path.join(MODELS, stem + ".onnx")):
        sys.exit("nao achei %s.onnx em api/models (veja ./voice.py list)" % stem)
    set_env(stem)
    print("agora: docker compose up -d")


def cmd_add(args):
    repo, path = args[0], args[1]
    rev = args[2] if len(args) > 2 else "main"
    stem = path.rstrip("/").split("/")[-1]
    base = "https://huggingface.co/%s/resolve/%s" % (repo, rev)
    for suffix in (".onnx", ".onnx.json"):
        dest = os.path.join(MODELS, stem + suffix)
        url = base + "/" + path + suffix
        print("baixando", url)
        urllib.request.urlretrieve(url, dest)
        print("  ->", dest, os.path.getsize(dest), "bytes")
    set_env(stem)
    print("agora: docker compose up -d")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "list":
        cmd_list()
    elif cmd == "use" and args:
        cmd_use(args)
    elif cmd == "add" and len(args) >= 2:
        cmd_add(args)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
