from __future__ import annotations

import importlib.util

from src.config import ROOT
from src.log import info, warn

SCRIPT = ROOT / "scripts" / "islamabad_weather.py"


def fetch_weather() -> dict | None:
    spec = importlib.util.spec_from_file_location("islamabad_weather", SCRIPT)
    if spec is None or spec.loader is None:
        warn("could not load islamabad_weather.py")
        return None
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = mod.get_weather()
    except Exception as exc:
        warn(f"weather failed: {exc}")
        return None
    info("weather loaded")
    return data
