from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from src.config import ROOT
from src.models import SeenEntry

SEEN_PATH = ROOT / "data" / "seen.json"
KEEP_DAYS = 45


def normalize_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\s]", "", title.casefold(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _cutoff(now: datetime | None = None) -> datetime:
    moment = now or datetime.now()
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment - timedelta(days=KEEP_DAYS)


def _parse_used_at(value: str) -> datetime:
    used = datetime.fromisoformat(value)
    if used.tzinfo is None:
        return used.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return used


def prune(entries: list[SeenEntry], now: datetime | None = None) -> list[SeenEntry]:
    cutoff = _cutoff(now)
    kept: list[SeenEntry] = []
    for entry in entries:
        try:
            used = _parse_used_at(entry.used_at)
        except ValueError:
            continue
        if used >= cutoff:
            kept.append(entry)
    return kept


def load_seen(path: Path = SEEN_PATH) -> list[SeenEntry]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    entries: list[SeenEntry] = []
    for item in raw:
        try:
            entries.append(SeenEntry.model_validate(item))
        except Exception:
            continue
    return prune(entries)


def is_seen(entries: list[SeenEntry], url: str, title: str) -> bool:
    key = normalize_title(title)
    for entry in entries:
        if entry.url == url:
            return True
        if key and len(key) > 12 and entry.title_key == key:
            return True
    return False


def remember(
    items: list[tuple[str, str]],
    path: Path = SEEN_PATH,
    now: datetime | None = None,
) -> list[SeenEntry]:
    moment = now or datetime.now().astimezone()
    used_at = moment.isoformat()
    merged = load_seen(path)
    for url, title in items:
        if is_seen(merged, url, title):
            continue
        merged.append(SeenEntry(url=url, title_key=normalize_title(title), used_at=used_at))
    merged = prune(merged, now=moment)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([e.model_dump(by_alias=True) for e in merged], indent=2) + "\n"
    )
    return merged
