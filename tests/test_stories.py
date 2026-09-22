import asyncio
from datetime import datetime

import httpx

from src.agents.stories import (
    LONG_SYSTEM,
    _fallback_note,
    stamp_brief,
    stamp_long,
    story_jobs,
    write_reader_note,
    write_stories,
)
from src.models import (
    BriefDraft,
    GatherBriefing,
    LongDraft,
    Meeting,
    NewsCandidate,
    ReaderNote,
    StoriesOut,
    TaskItem,
    TopicRank,
)


def _row(interest_id: str, n: int, image: bool = True) -> NewsCandidate:
    return NewsCandidate(
        id=f"{interest_id}-{n}",
        interest_id=interest_id,  # type: ignore[arg-type]
        title=f"{interest_id} story {n}",
        snippet="A short snippet.",
        source_name="Example",
        source_url=f"https://example.com/{interest_id}/{n}",
        image_url=f"https://img.example/{interest_id}-{n}.jpg" if image else None,
        article_text="Source text here.",
    )


def test_long_writer_asks_for_two_thousand_characters() -> None:
    assert "2000" in LONG_SYSTEM
    assert "10000" not in LONG_SYSTEM


def test_story_jobs_are_headline_lead_and_first_two_briefs() -> None:
    briefing = GatherBriefing(
        headline_id="palestine-1",
        topics={
            "palestine": TopicRank(
                best_id="palestine-2",
                candidates=["palestine-3", "palestine-4", "palestine-5"],
            ),
            "space": TopicRank(best_id="space-1", candidates=["space-2"]),
        },
    )
    candidates = [
        _row("palestine", 1),
        _row("palestine", 2),
        _row("palestine", 3),
        _row("palestine", 4),
        _row("palestine", 5),
        _row("space", 1),
        _row("space", 2),
    ]
    jobs = story_jobs(briefing, candidates)
    kinds = [(kind, topic, row.id) for kind, topic, row in jobs]
    assert kinds[0] == ("headline", None, "palestine-1")
    assert ("lead", "palestine", "palestine-2") in kinds
    assert ("brief", "palestine", "palestine-3") in kinds
    assert ("brief", "palestine", "palestine-4") in kinds
    assert ("brief", "palestine", "palestine-5") not in kinds
    assert ("lead", "space", "space-1") in kinds
    assert ("brief", "space", "space-2") in kinds
    assert len(jobs) == 6


def test_story_jobs_skip_missing_ids_and_empty_topic() -> None:
    briefing = GatherBriefing(
        headline_id="missing-headline",
        topics={
            "space": TopicRank(best_id="space-1", candidates=["gone", "space-2"]),
        },
    )
    jobs = story_jobs(briefing, [_row("space", 1), _row("space", 2)])
    kinds = [(kind, row.id) for kind, _, row in jobs]
    assert kinds == [("lead", "space-1"), ("brief", "space-2")]


def test_stamp_copies_image_url() -> None:
    with_image = _row("tech-ai", 1, image=True)
    long = stamp_long(with_image, LongDraft(title="A chip", author="Jane Doe", body="A" * 200))
    assert long.image_url == with_image.image_url
    assert long.id == with_image.id
    assert long.source_url == with_image.source_url


def test_missing_image_uses_duckduckgo(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.agents.stories.ensure_image",
        lambda image_url, article_text, title="": image_url or "https://ddg.example/first.jpg",
    )
    without = _row("tech-ai", 2, image=False)
    brief = stamp_brief(without, BriefDraft(title="A note", body="B" * 80))
    assert brief.image_url == "https://ddg.example/first.jpg"
    assert brief.id == without.id


def test_stories_out_includes_calendar_and_trello() -> None:
    meeting = Meeting(
        id="m1",
        title="Standup",
        start=datetime(2026, 9, 20, 9, 0),
        end=datetime(2026, 9, 20, 9, 30),
    )
    task = TaskItem(id="t1", title="Write the paper", status="pending")
    out = StoriesOut(
        date="2026-09-20",
        meetings=[meeting],
        tasks=[task],
        diary_note=None,
        desk_note="Trello not connected.",
        weather={"current": {"temperature_2m": 28}},
        reader_note="Good morning, Rameen.",
    )
    dumped = out.model_dump(mode="json")
    assert dumped["meetings"][0]["title"] == "Standup"
    assert dumped["tasks"][0]["title"] == "Write the paper"
    headline = stamp_long(
        _row("palestine", 1),
        LongDraft(title="Aid", author="Example", body="Body"),
    )
    assert "image_url" in headline.model_dump()
    assert dumped["weather"]["current"]["temperature_2m"] == 28
    assert dumped["reader_note"] == "Good morning, Rameen."
    assert list(dumped)[-2:] == ["weather", "reader_note"]


def test_fallback_note_uses_rameen_and_schedule() -> None:
    meeting = Meeting(
        id="m1",
        title="Standup",
        start=datetime(2026, 9, 20, 9, 0),
        end=datetime(2026, 9, 20, 9, 30),
    )
    task = TaskItem(id="t1", title="Write the paper", status="pending")
    note = _fallback_note({"current": {"temperature_2m": 28.4}}, [meeting], [task])
    assert note.startswith("Good morning, Rameen.")
    assert "28C" in note
    assert "1 meeting" in note
    assert "1 task" in note


def test_write_reader_note_sends_rameen_weather_meetings_tasks(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_complete(client, system, user, out_type, **kwargs):
        captured["system"] = system
        captured["user"] = user
        assert out_type is ReaderNote
        return ReaderNote(note="Good morning, Rameen. Clear skies, one meeting, then the paper.")

    monkeypatch.setattr("src.agents.stories.complete_json", fake_complete)
    meeting = Meeting(
        id="m1",
        title="Standup",
        start=datetime(2026, 9, 20, 9, 0),
        end=datetime(2026, 9, 20, 9, 30),
    )
    task = TaskItem(id="t1", title="Write the paper", status="pending")
    note = asyncio.run(
        write_reader_note(
            None,  # type: ignore[arg-type]
            {"current": {"temperature_2m": 30}, "daily": {"time": ["2026-09-20"]}, "hourly": {"time": []}},
            [meeting],
            [task],
        )
    )
    assert "Rameen" in captured["system"]
    assert "Standup" in captured["user"]
    assert "Write the paper" in captured["user"]
    assert "temperature_2m" in captured["user"]
    assert "hourly" not in captured["user"]
    assert note.startswith("Good morning, Rameen.")


def test_write_stories_appends_raw_weather_and_note(monkeypatch) -> None:
    raw = {"latitude": 33.6844, "current": {"temperature_2m": 28.1}, "hourly": {"time": ["x"]}}
    monkeypatch.setattr("src.agents.stories.fetch_weather", lambda: raw)

    async def fake_note(client, weather, meetings, tasks):
        assert weather == raw
        assert meetings[0].title == "Standup"
        assert tasks[0].title == "Write the paper"
        return "Good morning, Rameen. Warm air, a short standup, then the paper."

    monkeypatch.setattr("src.agents.stories.write_reader_note", fake_note)
    meeting = Meeting(
        id="m1",
        title="Standup",
        start=datetime(2026, 9, 20, 9, 0),
        end=datetime(2026, 9, 20, 9, 30),
    )
    task = TaskItem(id="t1", title="Write the paper", status="pending")

    async def run():
        async with httpx.AsyncClient() as client:
            return await write_stories(client, "2026-09-20", None, [], [meeting], [task])

    out = asyncio.run(run())
    dumped = out.model_dump(mode="json")
    assert dumped["weather"] == raw
    assert dumped["reader_note"].startswith("Good morning, Rameen.")
    assert list(dumped)[-2:] == ["weather", "reader_note"]
