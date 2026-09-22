from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.seen import is_seen, load_seen, normalize_title, prune, remember
from src.models import SeenEntry


def test_normalize_title_strips_punctuation() -> None:
    assert normalize_title("  Clay Cups: a Workshop! ") == "clay cups a workshop"


def test_is_seen_matches_url_or_long_title(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    remember([("https://example.com/a", "A long enough craft title")], path=path)
    entries = load_seen(path)
    assert is_seen(entries, "https://example.com/a", "unused")
    assert is_seen(entries, "https://other.example/b", "A long enough craft title")
    assert not is_seen(entries, "https://other.example/b", "Short")


def test_remember_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    item = ("https://example.com/a", "A long enough craft title")
    remember([item], path=path)
    remember([item], path=path)
    assert len(load_seen(path)) == 1


def test_prune_drops_entries_older_than_45_days() -> None:
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    old = SeenEntry(
        url="https://example.com/old",
        title_key="old craft project",
        used_at=(now - timedelta(days=46)).isoformat(),
    )
    fresh = SeenEntry(
        url="https://example.com/new",
        title_key="new craft project",
        used_at=(now - timedelta(days=10)).isoformat(),
    )
    kept = prune([old, fresh], now=now)
    assert [e.url for e in kept] == ["https://example.com/new"]
