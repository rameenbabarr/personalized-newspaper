#!/bin/sh
# Linux morning run, called by the systemd user timer.
#
# Resolves its own repo root, so the checkout can live anywhere and the unit
# files are the only place a path is written down. Unlike the old launchd
# wrapper this sources no shell profile: systemd user services do not read
# ~/.zshrc or ~/.bashrc, so secrets come from the environment or from the .env
# file that src/config.py loads for any variable that is not already set.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if [ -x .venv/bin/python ]; then
    exec .venv/bin/python -m src.cli send
fi
exec python3 -m src.cli send
