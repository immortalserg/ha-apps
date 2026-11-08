#!/usr/bin/env python3
"""Home Assistant Supervisor configuration bridge for LibreTranslate."""
import json
import os
import pathlib
import subprocess
import sys

DATA = pathlib.Path("/data")
OPTIONS = DATA / "options.json"
MODEL_ROOT = pathlib.Path("/home/libretranslate/.local")
CACHE_ROOT = pathlib.Path("/home/libretranslate/.cache")


def configure(options):
    languages = str(options.get("languages", "en,fr,de,ru")).strip()
    if not languages or any(not lang.replace("-", "").isalpha() for lang in languages.split(",")):
        raise ValueError("languages must be comma-separated language codes")
    char_limit = int(options.get("char_limit", 15000))
    req_limit = int(options.get("req_limit", 30))
    threads = int(options.get("threads", 2))
    if not 100 <= char_limit <= 50000 or not 1 <= req_limit <= 10000 or not 1 <= threads <= 16:
        raise ValueError("Invalid LibreTranslate limits")
    # Keep Argos model downloads on the persistent Home Assistant /data volume.
    # Set XDG directories rather than modifying paths in the upstream image.
    models = DATA / "models"
    cache = DATA / "cache"
    models.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "HOME": "/home/libretranslate",
        "XDG_DATA_HOME": str(models),
        "XDG_CACHE_HOME": str(cache),
        "LT_HOST": "0.0.0.0",
        "LT_PORT": "5000",
        "LT_LOAD_ONLY": languages,
        "LT_CHAR_LIMIT": str(char_limit),
        "LT_REQ_LIMIT": str(req_limit),
        "LT_THREADS": str(threads),
        "LT_UPDATE_MODELS": "true" if options.get("update_models", False) else "false",
    })
    return env


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    options = json.loads(OPTIONS.read_text(encoding="utf-8")) if OPTIONS.exists() else {}
    env = configure(options)
    print("Starting LibreTranslate on port 5000; models stored in /data/models", flush=True)
    # Upstream Docker image provides its own virtual environment and executable.
    os.execvpe("/app/venv/bin/libretranslate", ["libretranslate"], env)


if __name__ == "__main__":
    main()
