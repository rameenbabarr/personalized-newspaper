from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import ROOT, TZ

LOG_DIR = ROOT / "logs"

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

_SECRET = re.compile(
    r"(?i)((?:key|token|api[_-]?key|password|secret|authorization)=)([^&\s'\"]+)"
)
_BEARER = re.compile(r"(?i)(bearer\s+)(\S+)")

_AGENT_COLORS = {
    "NewsChief": MAGENTA,
    "Writer": CYAN,
    "DeskEditor": BLUE,
    "DiaryClerk": YELLOW,
    "CopyChief": GREEN,
}

_path: Path | None = None
_file = None
_t0 = 0.0


def path() -> Path | None:
    return _path


def active() -> bool:
    return _file is not None


def start_run(label: str) -> Path:
    global _path, _file, _t0
    close()
    now = datetime.now(TZ)
    day = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%H%M%S")
    folder = LOG_DIR / day
    folder.mkdir(parents=True, exist_ok=True)
    _path = folder / f"{stamp}-{label}.log"
    _file = _path.open("w", encoding="utf-8")
    _t0 = time.monotonic()
    _write(f"The Rameen Times  run={label}  started={now.isoformat()}")
    _write(f"log file: {_path}")
    _write("")
    info(f"run started ({label})")
    return _path


def close() -> None:
    global _file
    if _file is not None:
        elapsed = time.monotonic() - _t0
        _file.write(f"\nfinished in {elapsed:.1f}s\n")
        _file.close()
        _file = None


def info(msg: str) -> None:
    _line("INFO", msg, BLUE)


def step(name: str, msg: str = "") -> None:
    text = f"{name}  {msg}".rstrip()
    _line("STEP", text, CYAN + BOLD)


def ok(msg: str) -> None:
    _line("OK", msg, GREEN)


def warn(msg: str) -> None:
    _line("WARN", msg, YELLOW)


def error(msg: str) -> None:
    _line("ERROR", msg, RED + BOLD)


def agent_in(name: str, system: str, user: str) -> None:
    if not active():
        return
    color = _agent_color(name)
    _line("IN", name, color + BOLD)
    _block("system", system, color)
    _block("user", _pretty(user), color)


def agent_out(name: str, payload: Any, *, elapsed: float | None = None) -> None:
    if not active():
        return
    color = _agent_color(name)
    suffix = f"  {elapsed:.1f}s" if elapsed is not None else ""
    _line("OUT", f"{name}{suffix}", color + BOLD)
    _block("result", _pretty(payload), color)


def agent_fail(name: str, exc: Exception, *, elapsed: float | None = None) -> None:
    suffix = f"  {elapsed:.1f}s" if elapsed is not None else ""
    error(f"{name} failed{suffix}: {exc}")


def _agent_color(name: str) -> str:
    for prefix, color in _AGENT_COLORS.items():
        if name == prefix or name.startswith(prefix + " "):
            return color
    return WHITE


def _redact(text: str) -> str:
    text = _SECRET.sub(r"\1***", text)
    return _BEARER.sub(r"\1***", text)


def _pretty(payload: Any) -> str:
    if hasattr(payload, "model_dump"):
        return json.dumps(payload.model_dump(mode="json"), indent=2, default=str)
    if isinstance(payload, str):
        try:
            return json.dumps(json.loads(payload), indent=2, default=str)
        except json.JSONDecodeError:
            return payload
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, indent=2, default=str)
    return str(payload)


def _use_color() -> bool:
    return sys.stdout.isatty()


def _ts() -> str:
    return datetime.now(TZ).strftime("%H:%M:%S")


def _line(kind: str, msg: str, color: str) -> None:
    msg = _redact(msg)
    plain = f"{_ts()}  {kind:<5}  {msg}"
    if _use_color():
        shown = f"{DIM}{_ts()}{RESET}  {color}{kind:<5}{RESET}  {msg}{RESET}"
    else:
        shown = plain
    print(shown)
    _write(plain)


def _block(label: str, body: str, color: str) -> None:
    for raw in _redact(body).splitlines() or [""]:
        plain = f"         {label}| {raw}"
        if _use_color():
            shown = f"         {color}{label}|{RESET} {raw}"
        else:
            shown = plain
        print(shown)
        _write(plain)
    _write("")


def _write(plain: str) -> None:
    if _file is None:
        return
    _file.write(plain + "\n")
    _file.flush()
