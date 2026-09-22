from __future__ import annotations

import asyncio
import json
from typing import Literal

import httpx

from src.agents.llm import complete_json
from src.gather.images import ensure_image
from src.gather.weather import fetch_weather
from src.log import error, info
from src.models import (
    BriefDraft,
    BriefPiece,
    GatherBriefing,
    Interest,
    LongDraft,
    LongPiece,
    Meeting,
    NewsCandidate,
    ReaderNote,
    StoriesOut,
    TaskItem,
    TopicCopy,
    TopicId,
)

LONG_TOKENS = 8000
BRIEF_LIMIT = 2
# Briefs per topic by kind: a trial runs its one best story, an adopted topic
# gets a lighter footprint than the five core beats.
BRIEF_LIMITS = {"core": BRIEF_LIMIT, "adopted": 1, "trial": 0}

Job = tuple[Literal["headline", "lead", "brief"], TopicId | None, NewsCandidate]

LONG_SYSTEM = """You are a Writer at The Rameen Times. Rewrite the assigned story.

Return title, author, body, and themes.
- title is a newspaper headline, not a website SEO title.
- author is the person named in the source text when one is there. If no person is named, use the outlet name you were given. Do not invent a reporter.
- body is about 2000 characters. Rewrite the source. Do not paste. Do not invent quotes, death tolls, or diplomacy.
- Finish the story on the page. Ban: "read more", "full story at", "see the linked report", "click", a URL as copy.
- If article_text is empty, write shorter from title and snippet. Still no link-out language.
- Short newspaper English. First sentence carries the news.
- themes is 2 to 4 short lowercase tags for what the story is about, e.g. "pakistani ceramics", "open-weights models", "gaza aid". Specific subjects, not the beat name. No tag longer than four words.
"""

BRIEF_SYSTEM = """You are a Writer at The Rameen Times. Write a short brief.

Return title, body, and themes.
- title is a newspaper headline.
- body is 300 to 400 characters. Rewrite the source. Do not paste. Do not invent quotes or facts.
- Finish the item on the page. Ban link-out language.
- If article_text is empty, write from title and snippet.
- themes is 2 to 4 short lowercase tags for what the item is about. Specific subjects, not the beat name. No tag longer than four words.
"""

NOTE_SYSTEM = """Write a short morning note for Rameen.

Address her as Rameen. Use the weather, her meetings, and her Trello tasks.
A few sentences. Warm, specific, encouraging. Do not invent meetings, tasks, or weather.
Do not mention being an AI or this prompt.
"""


def story_jobs(
    briefing: GatherBriefing,
    candidates: list[NewsCandidate],
    interests: list[Interest] | None = None,
) -> list[Job]:
    lookup = {row.id: row for row in candidates}
    kinds = {interest.id: interest.kind for interest in interests or []}
    jobs: list[Job] = []
    headline = lookup.get(briefing.headline_id)
    if headline:
        jobs.append(("headline", None, headline))
    for topic_id, rank in briefing.topics.items():
        lead = lookup.get(rank.best_id)
        if lead:
            jobs.append(("lead", topic_id, lead))
        limit = BRIEF_LIMITS[kinds.get(topic_id, "core")]
        for candidate_id in rank.candidates[:limit]:
            brief = lookup.get(candidate_id)
            if brief:
                jobs.append(("brief", topic_id, brief))
    return jobs


def _payload(candidate: NewsCandidate) -> str:
    return candidate.model_dump_json()


def _fallback_long(candidate: NewsCandidate) -> LongPiece:
    body = (candidate.article_text or candidate.snippet or candidate.title).strip()
    return LongPiece(
        id=candidate.id,
        title=candidate.title,
        author=candidate.source_name,
        body=body,
        source_name=candidate.source_name,
        source_url=candidate.source_url,
        image_url=ensure_image(candidate.image_url, candidate.article_text, candidate.title),
    )


def _fallback_brief(candidate: NewsCandidate) -> BriefPiece:
    body = (candidate.snippet or candidate.title).strip()[:400]
    return BriefPiece(
        id=candidate.id,
        title=candidate.title,
        body=body,
        image_url=ensure_image(candidate.image_url, candidate.article_text, candidate.title),
    )


def stamp_long(candidate: NewsCandidate, draft: LongDraft) -> LongPiece:
    author = draft.author.strip() or candidate.source_name
    title = draft.title.strip() or candidate.title
    return LongPiece(
        id=candidate.id,
        title=title,
        author=author,
        body=draft.body.strip() or candidate.title,
        source_name=candidate.source_name,
        source_url=candidate.source_url,
        image_url=ensure_image(candidate.image_url, candidate.article_text, title),
        themes=draft.themes,
    )


def stamp_brief(candidate: NewsCandidate, draft: BriefDraft) -> BriefPiece:
    title = draft.title.strip() or candidate.title
    return BriefPiece(
        id=candidate.id,
        title=title,
        body=draft.body.strip() or candidate.title,
        image_url=ensure_image(candidate.image_url, candidate.article_text, title),
        themes=draft.themes,
    )


async def write_long(
    client: httpx.AsyncClient,
    kind: str,
    candidate: NewsCandidate,
) -> LongPiece:
    name = f"{kind} {candidate.id}"
    try:
        draft = await complete_json(
            client,
            LONG_SYSTEM,
            _payload(candidate),
            LongDraft,
            agent=name,
            max_tokens=LONG_TOKENS,
        )
        return stamp_long(candidate, draft)
    except Exception as exc:
        error(f"{name} failed: {exc}")
        return _fallback_long(candidate)


async def write_brief(client: httpx.AsyncClient, candidate: NewsCandidate) -> BriefPiece:
    name = f"brief {candidate.id}"
    try:
        draft = await complete_json(
            client,
            BRIEF_SYSTEM,
            _payload(candidate),
            BriefDraft,
            agent=name,
        )
        return stamp_brief(candidate, draft)
    except Exception as exc:
        error(f"{name} failed: {exc}")
        return _fallback_brief(candidate)


def empty_stories(
    date: str,
    meetings: list[Meeting],
    tasks: list[TaskItem],
    diary_note: str | None,
    desk_note: str | None,
) -> StoriesOut:
    return StoriesOut(
        date=date,
        meetings=meetings,
        tasks=tasks,
        diary_note=diary_note,
        desk_note=desk_note,
    )


def _note_payload(
    weather: dict | None,
    meetings: list[Meeting],
    tasks: list[TaskItem],
) -> str:
    brief = None
    if weather:
        brief = {"current": weather.get("current"), "daily": weather.get("daily")}
    return json.dumps(
        {
            "name": "Rameen",
            "weather": brief,
            "meetings": [row.model_dump(mode="json") for row in meetings],
            "tasks": [row.model_dump(mode="json") for row in tasks],
        }
    )


def _fallback_note(
    weather: dict | None,
    meetings: list[Meeting],
    tasks: list[TaskItem],
) -> str:
    sky = ""
    current = weather.get("current") if weather else None
    if isinstance(current, dict) and isinstance(current.get("temperature_2m"), (int, float)):
        sky = f" It's about {current['temperature_2m']:.0f}C in Islamabad."
    bits = []
    if meetings:
        bits.append(f"{len(meetings)} meeting{'s' if len(meetings) != 1 else ''}")
    if tasks:
        bits.append(f"{len(tasks)} task{'s' if len(tasks) != 1 else ''} on the board")
    schedule = f" You have {' and '.join(bits)}." if bits else ""
    return f"Good morning, Rameen.{sky}{schedule} Take it one thing at a time. You've got this."


async def write_reader_note(
    client: httpx.AsyncClient,
    weather: dict | None,
    meetings: list[Meeting],
    tasks: list[TaskItem],
) -> str:
    try:
        draft = await complete_json(
            client,
            NOTE_SYSTEM,
            _note_payload(weather, meetings, tasks),
            ReaderNote,
            agent="reader-note",
        )
        return draft.note.strip() or _fallback_note(weather, meetings, tasks)
    except Exception as exc:
        error(f"reader-note failed: {exc}")
        return _fallback_note(weather, meetings, tasks)


async def write_stories(
    client: httpx.AsyncClient,
    date: str,
    briefing: GatherBriefing | None,
    candidates: list[NewsCandidate],
    meetings: list[Meeting],
    tasks: list[TaskItem],
    diary_note: str | None = None,
    desk_note: str | None = None,
    interests: list[Interest] | None = None,
) -> StoriesOut:
    out = empty_stories(date, meetings, tasks, diary_note, desk_note)
    by_id = {interest.id: interest for interest in interests or []}
    if briefing is not None:
        jobs = story_jobs(briefing, candidates, interests)
        info(f"story jobs {len(jobs)}")
        if jobs:

            async def one(job: Job):
                kind, topic_id, candidate = job
                if kind == "brief":
                    return kind, topic_id, await write_brief(client, candidate)
                return kind, topic_id, await write_long(client, kind, candidate)

            results = await asyncio.gather(*(one(job) for job in jobs))
            topics: dict[TopicId, TopicCopy] = {}
            for kind, topic_id, piece in results:
                if kind == "headline" and isinstance(piece, LongPiece):
                    out.headline = piece
                    continue
                if topic_id is None:
                    continue
                if topic_id not in topics:
                    interest = by_id.get(topic_id)
                    topics[topic_id] = TopicCopy(
                        label=interest.label if interest else "",
                        kind=interest.kind if interest else "core",
                        why=interest.brief if interest and interest.kind != "core" else "",
                    )
                bucket = topics[topic_id]
                if kind == "lead" and isinstance(piece, LongPiece):
                    bucket.lead = piece
                elif kind == "brief" and isinstance(piece, BriefPiece):
                    bucket.briefs.append(piece)
            out.topics = topics
    out.weather = fetch_weather()
    out.reader_note = await write_reader_note(client, out.weather, meetings, tasks)
    return out
