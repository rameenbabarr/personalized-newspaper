from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from src.models import TOPIC_IDS

# Rising / fading compares the last WINDOW days with the WINDOW before it.
WINDOW = 28
TOP_HEADLINES = 10


def week_of(day: str) -> str:
    year, week, _ = date.fromisoformat(day).isocalendar()
    return f"{year}-W{week:02d}"


def like_rate(up: int, shown: int) -> float:
    """Smoothed share of stories liked. The +1/+2 keeps a week with one story
    and one like from reading as a perfect 100%."""
    return round((up + 1) / (shown + 2), 3)


def weekly_topics(stories: list[dict]) -> list[dict]:
    """Per ISO week, per topic: how many stories ran and how you voted. The
    five core beats always appear; discovery topics appear once printed."""
    extra = sorted({s["topic"] for s in stories} - set(TOPIC_IDS) - {"other", ""})
    keys = [*TOPIC_IDS, *extra]
    weeks: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {topic: {"shown": 0, "up": 0, "down": 0} for topic in keys}
    )
    for story in stories:
        topic = story["topic"]
        bucket = weeks[week_of(story["date"])]
        if topic not in bucket:
            continue
        bucket[topic]["shown"] += 1
        if story["vote"] > 0:
            bucket[topic]["up"] += 1
        elif story["vote"] < 0:
            bucket[topic]["down"] += 1
    out: list[dict] = []
    for week in sorted(weeks):
        topics = {
            topic: {**counts, "rate": like_rate(counts["up"], counts["shown"])}
            for topic, counts in weeks[week].items()
        }
        out.append({"week": week, "topics": topics})
    return out


def _theme_net(stories: list[dict]) -> dict[str, int]:
    net: dict[str, int] = defaultdict(int)
    for story in stories:
        if not story["vote"]:
            continue
        for theme in story["themes"]:
            net[theme] += story["vote"]
    return net


def theme_shift(stories: list[dict], today: date, window: int = WINDOW) -> dict:
    """Themes whose net votes grew or shrank between the previous window and
    the recent one. Only voted stories count: printed-but-ignored says more
    about the gate than about you."""
    recent_start = today - timedelta(days=window)
    previous_start = recent_start - timedelta(days=window)
    recent = [s for s in stories if date.fromisoformat(s["date"]) > recent_start]
    previous = [
        s
        for s in stories
        if previous_start < date.fromisoformat(s["date"]) <= recent_start
    ]
    now, before = _theme_net(recent), _theme_net(previous)
    rows = [
        {"theme": theme, "recent": now.get(theme, 0), "previous": before.get(theme, 0),
         "change": now.get(theme, 0) - before.get(theme, 0)}
        for theme in set(now) | set(before)
    ]
    rising = sorted((r for r in rows if r["change"] > 0), key=lambda r: (-r["change"], r["theme"]))
    fading = sorted((r for r in rows if r["change"] < 0), key=lambda r: (r["change"], r["theme"]))
    return {"rising": rising[:10], "fading": fading[:10]}


def top_themes(stories: list[dict], limit: int = 15) -> list[dict]:
    """All-time liked and disliked counts per theme."""
    tally: dict[str, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0})
    for story in stories:
        for theme in story["themes"]:
            if story["vote"] > 0:
                tally[theme]["up"] += 1
            elif story["vote"] < 0:
                tally[theme]["down"] += 1
    rows = [{"theme": t, **c} for t, c in tally.items() if c["up"] or c["down"]]
    rows.sort(key=lambda r: (-(r["up"] - r["down"]), -r["up"], r["theme"]))
    return rows[:limit]


def _headline(story: dict) -> dict:
    return {
        "date": story["date"],
        "topic": story["topic"],
        "headline": story["headline"],
        "themes": story["themes"],
    }


def summarize(
    stories: list[dict],
    today: date | None = None,
    topics: list[dict] | None = None,
) -> dict:
    """Everything the trends page and the reflect agent read, as plain JSON.
    `topics` is the discovery history from src/taste/db.py topics()."""
    today = today or date.today()
    voted = [s for s in stories if s["vote"]]
    liked = [s for s in reversed(stories) if s["vote"] > 0][:TOP_HEADLINES]
    disliked = [s for s in reversed(stories) if s["vote"] < 0][:TOP_HEADLINES]
    return {
        "as_of": today.isoformat(),
        "stories": len(stories),
        "votes": len(voted),
        "up": sum(1 for s in voted if s["vote"] > 0),
        "down": sum(1 for s in voted if s["vote"] < 0),
        "weeks": weekly_topics(stories),
        "shift": theme_shift(stories, today),
        "top_themes": top_themes(stories),
        "recent_liked": [_headline(s) for s in liked],
        "recent_disliked": [_headline(s) for s in disliked],
        "discovery": [
            {"slug": t["slug"], "label": t["label"], "status": t["status"], "trial_date": t["trial_date"]}
            for t in topics or []
        ],
    }
