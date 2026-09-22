from __future__ import annotations

from datetime import date

import httpx

from src.agents.briefing import build_briefing
from src.agents.discover import discover_topic
from src.agents.gate import gate_topics
from src.agents.queries import apply_queries, generate_queries
from src.agents.stories import write_stories
from src.config import iso_date, karachi_now, load_paper, load_profile, load_topics, load_user_md
from src.gather.calendar import gather_calendar
from src.gather.news import gather_news
from src.gather.tavily import fill_extracts
from src.gather.trello import gather_trello
from src.log import error, info, ok, step, warn
from src.models import Interest, PipelineState, StoriesOut
from src.seen import load_seen
from src.taste import db as taste_db


async def compose(state: PipelineState) -> PipelineState:
    step("compose", f"{len(state.candidates)} candidates, {len(state.meetings)} meetings, {len(state.tasks)} tasks")
    async with httpx.AsyncClient() as client:
        state.stories = await write_stories(
            client,
            state.date,
            state.briefing,
            state.candidates,
            state.meetings,
            state.tasks,
            diary_note=state.diary_note,
            desk_note=state.desk_note,
            interests=state.interests,
        )
        headline = state.stories.headline.title if state.stories.headline else "(none)"
        ok(f"stories headline={headline}  topics={len(state.stories.topics)}")
        info(state.stories.model_dump_json(indent=2))
    return state


async def discovery_topics(
    client: httpx.AsyncClient,
    user_md: str,
    core: list[Interest],
    today: date,
) -> list[Interest]:
    """Adopted topics plus today's trial topic.

    Yesterday's trial is judged first, so a topic you liked is already adopted
    and runs today. A second run the same morning reuses the day's trial. Any
    failure here costs only the extra topics, never the paper.
    """
    day = today.isoformat()
    try:
        for slug, status in taste_db.resolve_trials(day):
            info(f"topic {slug}: {status}")
        extra = taste_db.adopted_interests()
        trial = taste_db.trial_for(day)
        if trial is None:
            pick = await discover_topic(
                client,
                load_profile(today=today),
                user_md,
                [interest.label for interest in core + extra],
                taste_db.excluded_slugs(today),
            )
            if pick is not None:
                taste_db.start_trial(pick, day)
                trial = taste_db.get_topic(pick.slug)
        if trial is not None:
            extra.append(
                Interest(
                    id=trial["slug"],
                    label=trial["label"],
                    kind="trial",
                    brief=trial["why"],
                    queries=trial["queries"],
                )
            )
            ok(f"discover: {trial['label']}")
        adopted = [interest.label for interest in extra if interest.kind == "adopted"]
        if adopted:
            info(f"adopted topics: {', '.join(adopted)}")
        return extra
    except Exception as exc:
        warn(f"discovery topics failed: {exc}")
        return []


async def build_state() -> PipelineState:
    interests = load_topics()
    user_md = load_user_md()
    seen = load_seen()
    now = karachi_now()
    date = iso_date(now)
    step("gather", "calendar")
    meetings, diary_note, hours = await gather_calendar()
    info(f"calendar: {len(meetings)} meetings, {hours} busy hours")
    if diary_note:
        warn(f"calendar: {diary_note}")
    step("gather", "trello")
    tasks, desk_note = await gather_trello(load_paper())
    info(f"trello: {len(tasks)} cards")
    if desk_note:
        warn(f"trello: {desk_note}")
    async with httpx.AsyncClient() as client:
        step("gather", "topics")
        interests = interests + await discovery_topics(client, user_md, interests, now.date())
        step("gather", "queries")
        plan = await generate_queries(client, user_md, date)
        apply_queries(interests, plan)
        counts = "  ".join(f"{topic}={len(rows)}" for topic, rows in plan.queries.items())
        ok(f"queries  {counts}")
        step("gather", "news")
        candidates = await gather_news(interests, seen)
        raw_counts: dict[str, int] = {}
        for candidate in candidates:
            raw_counts[candidate.interest_id] = raw_counts.get(candidate.interest_id, 0) + 1
        raw_beats = "  ".join(f"{k}={v}" for k, v in raw_counts.items()) or "none"
        info(f"news pool: {len(candidates)}  {raw_beats}")
        step("gather", "gate")
        candidates = await gate_topics(client, user_md, interests, candidates)
        briefing = None
        if candidates:
            step("gather", "briefing")
            briefing = await build_briefing(client, interests, candidates)
            ok(f"headline {briefing.headline_id}  topics={len(briefing.topics)}")
        step("gather", "extract")
        try:
            await fill_extracts(client, candidates)
            filled = sum(1 for item in candidates if item.article_text)
            ok(f"extract filled {filled}/{len(candidates)}")
        except Exception as exc:
            error(f"tavily extract failed: {exc}")
    counts = {}
    for candidate in candidates:
        counts[candidate.interest_id] = counts.get(candidate.interest_id, 0) + 1
    beats = "  ".join(f"{k}={v}" for k, v in counts.items()) or "none"
    ok(f"news: {len(candidates)} candidates  {beats}")
    return PipelineState(
        date=iso_date(now),
        interests=interests,
        candidates=candidates,
        meetings=meetings,
        tasks=tasks,
        diary_note=diary_note,
        desk_note=desk_note,
        busy_hours=hours,
        briefing=briefing,
    )


async def build_edition_live() -> StoriesOut:
    state = await compose(await build_state())
    if state.stories is None:
        raise RuntimeError("compose finished without stories")
    ok(f"stories ready  topics={len(state.stories.topics)}")
    return state.stories
