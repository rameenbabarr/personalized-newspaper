import asyncio
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from src import pipeline
from src.agents import briefing as briefing_mod
from src.agents import discover as discover_mod
from src.agents.discover import discover_topic
from src.agents.queries import apply_queries, ensure_queries, fallback_plan
from src.agents.stories import story_jobs
from src.config import TZ, load_profile
from src.models import (
    Article,
    Desk,
    DiscoveryPick,
    Edition,
    GatherBriefing,
    Interest,
    LongPiece,
    NewsCandidate,
    StoriesOut,
    TopicCopy,
    TopicRank,
)
from src.render.edition import TRIAL_LIMIT, stories_to_edition, topic_from_id
from src.render.tex import prepare_edition, trial_links
from src.taste import db

TODAY = "2026-09-22"


def _pick(slug: str = "urdu-calligraphy", label: str = "Urdu calligraphy") -> DiscoveryPick:
    return DiscoveryPick(slug=slug, label=label, why="You like desi crafts.",
                         queries=["a", "b", "c", "d"])


def _edition(day: str, articles: list[Article]) -> Edition:
    return Edition(
        paper_name="The Rameen Times", date=day, volume="Vol. I",
        generated_at=datetime(2026, 9, 22, tzinfo=TZ), timezone="Asia/Karachi",
        diary=[], desk=Desk(pending=[], in_progress=[]), articles=articles,
    )


def _article(story_id: str, topic: str, trial: bool = False) -> Article:
    return Article(id=story_id, headline="h", section="s", body=["b"], role="secondary",
                   source_url="https://e.com", source_name="E", topic=topic, trial=trial)


def _trial_with_vote(path: Path, slug: str, value: int, day: str = "2026-09-21") -> None:
    db.start_trial(_pick(slug, slug.title()), day, path)
    story = f"{slug}-aaaaaaaaaaaa"
    db.record_edition(_edition(day, [_article(story, slug, trial=True)]), path)
    if value:
        db.vote(story, value, path)


# --- profile ------------------------------------------------------------------------

def test_missing_profile_is_empty(tmp_path) -> None:
    assert load_profile(tmp_path / "nope.yaml") == {}


def test_profile_turns_birthday_into_age_and_drops_blanks(tmp_path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text("birthday: 2004-05-12\ngender: ''\nlocation: Islamabad\nhobbies: []\n")
    assert load_profile(path, today=date(2026, 9, 22)) == {"location": "Islamabad", "age": 22}


# --- pick schema and agent ----------------------------------------------------------

def test_pick_needs_slug_shape_and_four_queries() -> None:
    with pytest.raises(ValidationError):
        DiscoveryPick(slug="Urdu Calligraphy", label="x y", why="", queries=["a", "b", "c", "d"])
    with pytest.raises(ValidationError):
        DiscoveryPick(slug="urdu", label="Urdu", why="", queries=["a", "b", "c"])


def test_pick_stores_plain_text_not_html_entities() -> None:
    pick = DiscoveryPick(slug="food-science", label="Food science &amp; fermentation",
                         why="Bread &amp; chemistry.", queries=["a", "b", "c", "d"])
    assert pick.label == "Food science & fermentation" and pick.why == "Bread & chemistry."


def test_discover_retries_once_on_an_excluded_slug(monkeypatch) -> None:
    picks = iter([_pick("space", "Space"), _pick()])
    prompts: list[str] = []

    async def fake(client, system, user, out_type, **kwargs):
        prompts.append(user)
        return next(picks)

    monkeypatch.setattr(discover_mod, "complete_json", fake)
    pick = asyncio.run(discover_topic(None, {"age": 22}, "md", ["Space"], {"space"}))  # type: ignore[arg-type]
    assert pick and pick.slug == "urdu-calligraphy"
    assert "'space' is excluded" in prompts[1]
    assert '"age": 22' in prompts[0]


def test_discover_gives_up_quietly(monkeypatch) -> None:
    async def excluded(*args, **kwargs):
        return _pick("space", "Space")

    monkeypatch.setattr(discover_mod, "complete_json", excluded)
    assert asyncio.run(discover_topic(None, {}, "", [], {"space"})) is None  # type: ignore[arg-type]

    async def boom(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(discover_mod, "complete_json", boom)
    assert asyncio.run(discover_topic(None, {}, "", [], set())) is None  # type: ignore[arg-type]


# --- lifecycle ----------------------------------------------------------------------

@pytest.mark.parametrize("value,status", [(1, "adopted"), (-1, "rejected"), (0, "skipped")])
def test_resolve_trial_by_vote(tmp_path, value, status) -> None:
    path = tmp_path / "taste.db"
    _trial_with_vote(path, "urdu-calligraphy", value)
    assert db.resolve_trials(TODAY, path) == [("urdu-calligraphy", status)]


def test_a_liked_fourth_topic_waits(tmp_path) -> None:
    path = tmp_path / "taste.db"
    for slug in ("one", "two", "three", "four"):
        _trial_with_vote(path, slug, 1)
    statuses = dict(db.resolve_trials(TODAY, path))
    assert sorted(statuses.values()) == ["adopted", "adopted", "adopted", "waiting"]


def test_todays_trial_is_not_judged_yet(tmp_path) -> None:
    path = tmp_path / "taste.db"
    db.start_trial(_pick(), TODAY, path)
    assert db.resolve_trials(TODAY, path) == []
    assert db.trial_for(TODAY, path)["slug"] == "urdu-calligraphy"  # type: ignore[index]


def test_excluded_slugs(tmp_path) -> None:
    path = tmp_path / "taste.db"
    _trial_with_vote(path, "nope", -1)
    _trial_with_vote(path, "recent", 0)
    _trial_with_vote(path, "ancient", 0, day="2026-01-01")
    db.resolve_trials(TODAY, path)
    excluded = db.excluded_slugs(date(2026, 9, 22), path)
    assert {"space", "palestine", "nope", "recent"} <= excluded
    assert "ancient" not in excluded


def test_page_actions(tmp_path) -> None:
    path = tmp_path / "taste.db"
    _trial_with_vote(path, "kept", 1)
    db.resolve_trials(TODAY, path)
    assert [i.id for i in db.adopted_interests(path)] == ["kept"]
    assert db.adopted_interests(path)[0].kind == "adopted"
    assert db.set_topic("kept", "drop", path) == "rejected"
    assert db.set_topic("kept", "undo", path) == "skipped"
    assert db.set_topic("kept", "adopt", path) == "adopted"
    assert db.set_topic("kept", "undo", path) is None
    assert db.set_topic("missing", "drop", path) is None


def test_record_edition_uses_article_topic(tmp_path) -> None:
    path = tmp_path / "taste.db"
    db.record_edition(_edition(TODAY, [_article("urdu-calligraphy-aaaaaaaaaaaa", "urdu-calligraphy")]), path)
    assert db.stories_with_votes(path)[0]["topic"] == "urdu-calligraphy"


# --- pipeline -----------------------------------------------------------------------

def test_discovery_topics_reuses_the_days_trial_and_judges_it_next_day(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "taste.db")
    monkeypatch.setattr(pipeline, "load_profile", lambda today=None: {})
    calls: list[set[str]] = []

    async def fake_discover(client, profile, user_md, reading, excluded):
        calls.append(excluded)
        return _pick() if len(calls) == 1 else _pick("film-photography", "Film photography")

    monkeypatch.setattr(pipeline, "discover_topic", fake_discover)
    core = [Interest(id="space", label="Space")]
    day1, day2 = date(2026, 9, 21), date(2026, 9, 22)

    first = asyncio.run(pipeline.discovery_topics(None, "", core, day1))  # type: ignore[arg-type]
    again = asyncio.run(pipeline.discovery_topics(None, "", core, day1))  # type: ignore[arg-type]
    assert [(i.id, i.kind) for i in first] == [("urdu-calligraphy", "trial")]
    assert [i.id for i in again] == ["urdu-calligraphy"] and len(calls) == 1

    story = "urdu-calligraphy-aaaaaaaaaaaa"
    db.record_edition(_edition("2026-09-21", [_article(story, "urdu-calligraphy", trial=True)]))
    db.vote(story, 1)
    nxt = asyncio.run(pipeline.discovery_topics(None, "", core, day2))  # type: ignore[arg-type]
    assert [(i.id, i.kind) for i in nxt] == [("urdu-calligraphy", "adopted"), ("film-photography", "trial")]
    assert "urdu-calligraphy" in calls[1]


def test_core_query_helpers_leave_discovery_topics_alone() -> None:
    interests = [Interest(id="space", label="Space"),
                 Interest(id="urdu-calligraphy", label="Urdu", kind="trial", queries=["q"])]
    apply_queries(interests, fallback_plan())
    ensure_queries(interests)
    assert len(interests[0].queries) == 4
    assert interests[1].queries == ["q"]


# --- choose and write ---------------------------------------------------------------

def _cand(topic: str, n: int) -> NewsCandidate:
    return NewsCandidate(id=f"{topic}-{n:012d}", interest_id=topic, title="t", snippet="s",
                         source_name="E", source_url=f"https://e.com/{topic}/{n}")


def test_story_jobs_brief_limits_by_kind() -> None:
    interests = [Interest(id="space", label="Space"),
                 Interest(id="kept", label="Kept", kind="adopted"),
                 Interest(id="trial", label="Trial", kind="trial")]
    rows = [_cand(t, n) for t in ("space", "kept", "trial") for n in range(4)]
    brief = GatherBriefing(
        headline_id=rows[0].id,
        topics={t: TopicRank(best_id=f"{t}-{1:012d}", candidates=[f"{t}-{n:012d}" for n in (2, 3)])
                for t in ("space", "kept", "trial")},
    )
    jobs = story_jobs(brief, rows, interests)
    count = lambda t, k: sum(1 for kind, topic, _ in jobs if topic == t and kind == k)  # noqa: E731
    assert (count("space", "brief"), count("kept", "brief"), count("trial", "brief")) == (2, 1, 0)
    assert count("trial", "lead") == 1


def test_trial_never_leads_the_paper(monkeypatch) -> None:
    async def fail(*args, **kwargs):
        raise RuntimeError("use fallbacks")

    monkeypatch.setattr(briefing_mod, "complete_json", fail)
    interests = [Interest(id="trial", label="Trial", kind="trial"), Interest(id="space", label="Space")]
    rows = [_cand("trial", 1), _cand("space", 1)]
    out = asyncio.run(briefing_mod.build_briefing(None, interests, rows))  # type: ignore[arg-type]
    assert out.headline_id == rows[1].id


# --- print --------------------------------------------------------------------------

def _piece(story_id: str, body: str = "Para.") -> LongPiece:
    return LongPiece(id=story_id, title="T", author="A", body=body,
                     source_name="E", source_url="https://e.com")


def test_trial_story_becomes_a_flagged_trimmed_article() -> None:
    long_body = "\n\n".join(["A sentence that runs on for a while. " * 6] * 8)
    stories = StoriesOut(
        date=TODAY,
        headline=_piece("kept-000000000001"),
        topics={
            "kept": TopicCopy(label="Film photography", kind="adopted", why="w"),
            "urdu-calligraphy": TopicCopy(lead=_piece("urdu-calligraphy-000000000002", long_body),
                                          label="Urdu calligraphy", kind="trial", why="You like crafts."),
        },
    )
    edition = stories_to_edition(stories)
    lead, trial = edition.articles
    assert lead.section == "Film photography" and lead.topic == "kept"
    assert trial.trial and trial.topic == "urdu-calligraphy" and trial.section == "Urdu calligraphy"
    assert sum(len(p) for p in trial.body) <= TRIAL_LIMIT
    assert edition.trial_note == "We guessed you might like Urdu calligraphy. You like crafts."


def test_prepare_edition_takes_trial_out_of_the_paper(tmp_path) -> None:
    edition = _edition(TODAY, [_article("space-000000000001", "space"),
                               _article("urdu-000000000002", "urdu", trial=True)])
    context = prepare_edition(edition, tmp_path)
    assert [a.id for a in context["secondaries"]] == ["space-000000000001"]
    assert context["trial"].id == "urdu-000000000002"


def test_topic_from_id_and_trial_links() -> None:
    assert topic_from_id("urdu-calligraphy-3f2a9c000000") == "urdu-calligraphy"
    assert topic_from_id("space-apod") == "space"
    assert trial_links("urdu-3f2a") == r"\triallinks{urdu-3f2a}"
    assert trial_links("bad id") == ""


def test_editions_from_before_discovery_still_load() -> None:
    sample = Path("config/sample-edition.json").read_text()
    edition = Edition.model_validate_json(sample)
    assert edition.trial_note is None
    assert all(not a.trial for a in edition.articles)
