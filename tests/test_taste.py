import asyncio
from datetime import date, datetime, timedelta

import pytest

from src.agents import reflect as reflect_mod
from src.agents.reflect import MIN_VOTES, fallback_report, reflect
from src.config import TZ
from src.models import Article, Desk, Edition, LongDraft, TasteReport
from src.render.tex import vote_links
from src.taste import db
from src.taste.trends import like_rate, summarize, theme_shift, week_of, weekly_topics


def _article(story_id: str, themes: list[str], role: str = "secondary") -> Article:
    return Article(
        id=story_id,
        headline=f"Headline {story_id}",
        section="Space",
        body=["Body."],
        role=role,  # type: ignore[arg-type]
        source_url=f"https://example.com/{story_id}",
        source_name="Example",
        themes=themes,
    )


def _edition(day: str, articles: list[Article]) -> Edition:
    return Edition(
        paper_name="The Rameen Times",
        date=day,
        volume="Vol. I",
        generated_at=datetime(2026, 9, 20, tzinfo=TZ),
        timezone="Asia/Karachi",
        diary=[],
        desk=Desk(pending=[], in_progress=[]),
        articles=articles,
    )


def _story(day: str, topic: str, vote: int, themes: list[str]) -> dict:
    return {"id": f"{topic}-{day}-{themes}", "date": day, "topic": topic, "role": "brief",
            "source": "x", "headline": "h", "themes": themes, "vote": vote}


# --- themes on the writer's draft -------------------------------------------------

def test_themes_are_cleaned_and_capped() -> None:
    draft = LongDraft(title="t", author="a", body="b",
                      themes=[" Pakistani  Ceramics", "pakistani ceramics", "a", "b", "c", "d"])
    assert draft.themes == ["pakistani ceramics", "a", "b", "c"]


def test_old_edition_json_without_themes_still_loads() -> None:
    article = Article.model_validate(
        {"id": "x", "headline": "h", "section": "s", "body": "b", "role": "brief",
         "source_url": "", "source_name": "s"}
    )
    assert article.themes == []


# --- store ------------------------------------------------------------------------

def test_record_vote_and_latest_vote_wins(tmp_path) -> None:
    path = tmp_path / "taste.db"
    db.record_edition(_edition("2026-09-20", [_article("space-abc", ["mars rovers"])]), path)
    assert db.vote("space-abc", 1, path)
    assert db.vote("space-abc", -1, path)
    rows = db.stories_with_votes(path)
    assert len(rows) == 1
    assert rows[0]["topic"] == "space"
    assert rows[0]["themes"] == ["mars rovers"]
    assert rows[0]["vote"] == -1


def test_vote_on_unknown_story_is_refused(tmp_path) -> None:
    path = tmp_path / "taste.db"
    assert db.vote("space-nope", 1, path) is False
    with pytest.raises(ValueError):
        db.vote("space-nope", 2, path)


def test_rerecording_a_day_keeps_votes(tmp_path) -> None:
    path = tmp_path / "taste.db"
    edition = _edition("2026-09-20", [_article("space-abc", [])])
    db.record_edition(edition, path)
    db.vote("space-abc", 1, path)
    edition.articles[0].themes = ["comets"]
    db.record_edition(edition, path)
    [row] = db.stories_with_votes(path)
    assert row["vote"] == 1 and row["themes"] == ["comets"]


def test_backfill_reads_archived_editions(tmp_path) -> None:
    editions = tmp_path / "editions"
    for day, story in (("2026-09-19", "space-a"), ("2026-09-20", "tech-ai-b")):
        (editions / day).mkdir(parents=True)
        (editions / day / f"{day}.json").write_text(
            _edition(day, [_article(story, [])]).model_dump_json()
        )
    (editions / "2026-09-21").mkdir()  # a failed run with no JSON
    path = tmp_path / "taste.db"
    assert db.backfill(editions, path) == 2
    assert {r["topic"] for r in db.stories_with_votes(path)} == {"space", "tech-ai"}


def test_report_round_trip(tmp_path) -> None:
    path = tmp_path / "taste.db"
    assert db.latest_report(path) is None
    db.save_report({"summary": "one"}, path)
    db.save_report({"summary": "two"}, path)
    report = db.latest_report(path)
    assert report and report["summary"] == "two" and report["created_at"]


# --- trends -----------------------------------------------------------------------

def test_like_rate_is_smoothed() -> None:
    assert like_rate(0, 0) == 0.5
    assert like_rate(1, 1) == pytest.approx(0.667, abs=0.001)


def test_weekly_topics_counts_votes() -> None:
    stories = [
        _story("2026-09-14", "space", 1, []),
        _story("2026-09-15", "space", -1, []),
        _story("2026-09-15", "space", 0, []),
    ]
    [week] = weekly_topics(stories)
    assert week["week"] == week_of("2026-09-14")
    assert week["topics"]["space"] == {"shown": 3, "up": 1, "down": 1, "rate": 0.4}
    assert week["topics"]["palestine"]["shown"] == 0


def test_theme_shift_finds_rising_and_fading() -> None:
    today = date(2026, 9, 22)
    old = (today - timedelta(days=40)).isoformat()
    new = (today - timedelta(days=5)).isoformat()
    stories = [
        _story(old, "art-crafts", 1, ["galleries"]),
        _story(old, "art-crafts", 1, ["galleries"]),
        _story(new, "art-crafts", 1, ["ceramics"]),
        _story(new, "art-crafts", 1, ["ceramics"]),
        _story(new, "art-crafts", -1, ["galleries"]),
    ]
    shift = theme_shift(stories, today)
    assert shift["rising"][0] == {"theme": "ceramics", "recent": 2, "previous": 0, "change": 2}
    assert shift["fading"][0]["theme"] == "galleries"
    assert shift["fading"][0]["change"] == -3


def test_summarize_is_json_ready() -> None:
    summary = summarize([_story("2026-09-20", "space", 1, ["comets"])], date(2026, 9, 22))
    assert summary["votes"] == 1 and summary["up"] == 1
    assert summary["top_themes"] == [{"theme": "comets", "up": 1, "down": 0}]
    assert summary["recent_liked"][0]["themes"] == ["comets"]


# --- reflect agent ----------------------------------------------------------------

def test_reflect_skips_the_agent_when_votes_are_thin(monkeypatch) -> None:
    async def boom(*args, **kwargs):
        raise AssertionError("agent should not be called")

    monkeypatch.setattr(reflect_mod, "complete_json", boom)
    report = asyncio.run(reflect(None, {"votes": MIN_VOTES - 1}, ""))  # type: ignore[arg-type]
    assert "Only" in report.summary and not report.suggested_edits


def test_reflect_sends_trends_and_user_md(monkeypatch) -> None:
    seen = {}

    async def fake(client, system, user, out_type, **kwargs):
        seen["user"] = user
        seen["model"] = kwargs.get("model")
        return TasteReport(summary="More ceramics.")

    monkeypatch.setattr(reflect_mod, "complete_json", fake)
    trends = {"votes": MIN_VOTES, "shift": {"rising": [{"theme": "ceramics"}]}}
    report = asyncio.run(reflect(None, trends, "## Art and crafts\nDesi crafts."))  # type: ignore[arg-type]
    assert report.summary == "More ceramics."
    assert "ceramics" in seen["user"] and "Desi crafts" in seen["user"]
    assert seen["model"] == reflect_mod.OPUS


def test_reflect_falls_back_to_numbers(monkeypatch) -> None:
    async def fail(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(reflect_mod, "complete_json", fail)
    trends = {"votes": 12, "up": 9, "down": 3,
              "shift": {"rising": [{"theme": "ceramics"}], "fading": [{"theme": "galleries"}]}}
    report = asyncio.run(reflect(None, trends, ""))  # type: ignore[arg-type]
    assert report.summary == fallback_report(trends).summary
    assert "ceramics" in report.summary and "galleries" in report.summary


# --- PDF links --------------------------------------------------------------------

def test_vote_links_only_for_url_safe_ids() -> None:
    assert vote_links("space-3f2a9c") == r"\hfill\votelinks{space-3f2a9c}"
    assert vote_links("bad_id#1") == ""
    assert vote_links("") == ""
