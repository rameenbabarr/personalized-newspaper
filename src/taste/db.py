from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from src.config import ROOT, TZ
from src.models import TOPIC_IDS, DiscoveryPick, Edition, Interest

DB_PATH = ROOT / "data" / "taste.db"
EDITIONS_DIR = ROOT / "editions"
# Discovery topics kept at once; a liked topic past this waits for a free slot.
MAX_ADOPTED = 3
# A trial you ignored may be suggested again after this many days.
SKIP_COOLDOWN_DAYS = 90

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id       TEXT PRIMARY KEY,
    date     TEXT NOT NULL,
    topic    TEXT NOT NULL,
    role     TEXT NOT NULL,
    source   TEXT NOT NULL,
    headline TEXT NOT NULL,
    themes   TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS votes (
    story_id TEXT NOT NULL,
    value    INTEGER NOT NULL CHECK (value IN (-1, 1)),
    at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS votes_story ON votes(story_id);
-- Discovery topics. status: trial | adopted | waiting | rejected | skipped
CREATE TABLE IF NOT EXISTS topics (
    slug       TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    why        TEXT NOT NULL,
    queries    TEXT NOT NULL,
    status     TEXT NOT NULL,
    trial_date TEXT NOT NULL,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    body       TEXT NOT NULL
);
"""

# A vote can be changed, so only the newest one per story counts.
LATEST_VOTES = """
SELECT v.story_id, v.value, v.at FROM votes v
JOIN (SELECT story_id, MAX(rowid) AS last FROM votes GROUP BY story_id) m
  ON v.rowid = m.last
"""


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open, commit on success, always close. The server runs for weeks, so a
    connection left open per request would pile up."""
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def topic_of(story_id: str) -> str:
    for topic in TOPIC_IDS:
        if story_id.startswith(f"{topic}-"):
            return topic
    return "other"


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def record_edition(edition: Edition, path: Path | None = None) -> int:
    """Remember every printed story. Re-running a day refreshes its rows."""
    with connect(path) as conn:
        for article in edition.articles:
            conn.execute(
                """
                INSERT INTO stories (id, date, topic, role, source, headline, themes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    role=excluded.role, source=excluded.source,
                    headline=excluded.headline, themes=excluded.themes
                """,
                (
                    article.id,
                    edition.date,
                    article.topic or topic_of(article.id),
                    article.role,
                    article.source_name,
                    article.headline,
                    json.dumps(article.themes),
                ),
            )
    return len(edition.articles)


def backfill(editions_dir: Path | None = None, path: Path | None = None) -> int:
    """Load every archived edition JSON, so history starts before the tracker."""
    total = 0
    for day in sorted((editions_dir or EDITIONS_DIR).glob("*/")):
        edition_json = day / f"{day.name}.json"
        if not edition_json.is_file():
            continue
        try:
            edition = Edition.model_validate_json(edition_json.read_text())
        except ValueError:
            continue
        total += record_edition(edition, path)
    return total


def vote(story_id: str, value: int, path: Path | None = None) -> bool:
    """Record a vote. False when the story was never printed."""
    if value not in (-1, 1):
        raise ValueError("vote must be 1 or -1")
    with connect(path) as conn:
        known = conn.execute("SELECT 1 FROM stories WHERE id = ?", (story_id,)).fetchone()
        if not known:
            return False
        conn.execute(
            "INSERT INTO votes (story_id, value, at) VALUES (?, ?, ?)",
            (story_id, value, _now()),
        )
    return True


def _story(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["themes"] = json.loads(out.get("themes") or "[]")
    return out


def stories_with_votes(path: Path | None = None) -> list[dict]:
    """Every printed story, with `vote` = latest vote (1, -1) or 0."""
    with connect(path) as conn:
        rows = conn.execute(
            f"""
            SELECT s.*, COALESCE(v.value, 0) AS vote
            FROM stories s LEFT JOIN ({LATEST_VOTES}) v ON v.story_id = s.id
            ORDER BY s.date, s.id
            """
        ).fetchall()
    return [_story(row) for row in rows]


def save_report(body: dict, path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO reports (created_at, body) VALUES (?, ?)",
            (_now(), json.dumps(body)),
        )


def latest_report(path: Path | None = None) -> dict | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT created_at, body FROM reports ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {"created_at": row["created_at"], **json.loads(row["body"])}


# --- discovery topics -------------------------------------------------------------

def _topic(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["queries"] = json.loads(out.get("queries") or "[]")
    return out


def topics(path: Path | None = None) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute("SELECT * FROM topics ORDER BY trial_date DESC, slug").fetchall()
    return [_topic(row) for row in rows]


def get_topic(slug: str, path: Path | None = None) -> dict | None:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM topics WHERE slug = ?", (slug,)).fetchone()
    return _topic(row) if row else None


def trial_for(day: str, path: Path | None = None) -> dict | None:
    """The trial already chosen for `day`, so a second run that morning (preview
    then send) prints the same trial instead of asking for a new one."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM topics WHERE status = 'trial' AND trial_date = ?", (day,)
        ).fetchone()
    return _topic(row) if row else None


def start_trial(pick: DiscoveryPick, day: str, path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO topics (slug, label, why, queries, status, trial_date)
            VALUES (?, ?, ?, ?, 'trial', ?)
            ON CONFLICT(slug) DO UPDATE SET
                label=excluded.label, why=excluded.why, queries=excluded.queries,
                status='trial', trial_date=excluded.trial_date, decided_at=NULL
            """,
            (pick.slug, pick.label, pick.why, json.dumps(pick.queries), day),
        )


def _adopted_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM topics WHERE status = 'adopted'").fetchone()[0]


def resolve_trials(today: str, path: Path | None = None) -> list[tuple[str, str]]:
    """Judge every earlier trial by the latest vote on its stories.

    more -> adopted (or waiting when MAX_ADOPTED are already kept),
    less -> rejected for good, no vote or nothing printed -> skipped.
    """
    decided: list[tuple[str, str]] = []
    with connect(path) as conn:
        trials = conn.execute(
            "SELECT slug, trial_date FROM topics WHERE status = 'trial' AND trial_date < ?",
            (today,),
        ).fetchall()
        for trial in trials:
            vote = conn.execute(
                f"""
                SELECT v.value FROM stories s JOIN ({LATEST_VOTES}) v ON v.story_id = s.id
                WHERE s.topic = ? ORDER BY v.at DESC LIMIT 1
                """,
                (trial["slug"],),
            ).fetchone()
            value = vote["value"] if vote else 0
            if value > 0:
                status = "adopted" if _adopted_count(conn) < MAX_ADOPTED else "waiting"
            elif value < 0:
                status = "rejected"
            else:
                status = "skipped"
            conn.execute(
                "UPDATE topics SET status = ?, decided_at = ? WHERE slug = ?",
                (status, _now(), trial["slug"]),
            )
            decided.append((trial["slug"], status))
    return decided


def adopted_interests(path: Path | None = None) -> list[Interest]:
    return [
        Interest(id=t["slug"], label=t["label"], kind="adopted", brief=t["why"], queries=t["queries"])
        for t in topics(path)
        if t["status"] == "adopted"
    ]


def excluded_slugs(today: date, path: Path | None = None) -> set[str]:
    """Slugs discovery must not suggest: core beats, anything kept, waiting,
    rejected or on trial, and anything skipped inside the cooldown."""
    cooldown = (today - timedelta(days=SKIP_COOLDOWN_DAYS)).isoformat()
    out = set(TOPIC_IDS)
    for t in topics(path):
        if t["status"] != "skipped" or t["trial_date"] > cooldown:
            out.add(t["slug"])
    return out


def set_topic(slug: str, action: str, path: Path | None = None) -> str | None:
    """Page actions. drop: stop an adopted topic and never suggest it again.
    adopt: keep a waiting (or earlier) topic if there is a free slot.
    undo: take back a rejection, so it can be suggested again later.
    Returns the new status, or None when the action does not apply."""
    with connect(path) as conn:
        row = conn.execute("SELECT status FROM topics WHERE slug = ?", (slug,)).fetchone()
        if not row:
            return None
        current = row["status"]
        if action == "drop" and current in {"adopted", "waiting"}:
            status = "rejected"
        elif action == "adopt" and current != "adopted":
            if _adopted_count(conn) >= MAX_ADOPTED:
                return None
            status = "adopted"
        elif action == "undo" and current == "rejected":
            status = "skipped"
        else:
            return None
        conn.execute(
            "UPDATE topics SET status = ?, decided_at = ? WHERE slug = ?",
            (status, _now(), slug),
        )
    return status
