from __future__ import annotations

import asyncio
import json

import httpx

from src.agents.llm import complete_json
from src.log import info, warn
from src.models import (
    GatherBriefing,
    HeadlineOut,
    Interest,
    NewsCandidate,
    TopicId,
    TopicRank,
)

OPUS = "claude-opus-5"

HEADLINE_SYSTEM = """You pick the front-page story for The Rameen Times.

You see only titles and snippets. Return one headline_id from the list. That is the story Hash would stop and read this morning. Do not invent an id. Do not write a headline.
"""

RANK_SYSTEM = """You rank the leftover stories for one beat of The Rameen Times.

You see only titles and snippets. The front-page story is already chosen and is not in this list.

Return best_id (the strongest leftover for this beat) and candidates (the remaining ids, not including best_id). Use only ids from the list. Do not invent ids.
"""


def _cards(rows: list[NewsCandidate]) -> list[dict]:
    return [{"id": row.id, "title": row.title, "snippet": row.snippet} for row in rows]


def leftover_for_topic(
    candidates: list[NewsCandidate],
    interest_id: TopicId,
    headline_id: str,
) -> list[NewsCandidate]:
    return [
        row
        for row in candidates
        if row.interest_id == interest_id and row.id != headline_id
    ]


def apply_headline(candidates: list[NewsCandidate], headline_id: str) -> str:
    allowed = {row.id for row in candidates}
    if headline_id in allowed:
        return headline_id
    return candidates[0].id


def fallback_rank(rows: list[NewsCandidate]) -> TopicRank | None:
    if not rows:
        return None
    return TopicRank(best_id=rows[0].id, candidates=[row.id for row in rows[1:]])


def apply_rank(rows: list[NewsCandidate], out: TopicRank) -> TopicRank:
    allowed = [row.id for row in rows]
    allowed_set = set(allowed)
    best = out.best_id if out.best_id in allowed_set else allowed[0]
    rest: list[str] = []
    for candidate_id in out.candidates:
        if candidate_id in allowed_set and candidate_id != best and candidate_id not in rest:
            rest.append(candidate_id)
    for candidate_id in allowed:
        if candidate_id != best and candidate_id not in rest:
            rest.append(candidate_id)
    return TopicRank(best_id=best, candidates=rest)


async def pick_headline(
    client: httpx.AsyncClient,
    candidates: list[NewsCandidate],
) -> str:
    if not candidates:
        raise RuntimeError("no candidates for headline")
    fallback = candidates[0].id
    try:
        out = await complete_json(
            client,
            HEADLINE_SYSTEM,
            json.dumps(_cards(candidates), ensure_ascii=True),
            HeadlineOut,
            agent="headline",
            model=OPUS,
        )
        return apply_headline(candidates, out.headline_id)
    except Exception as exc:
        warn(f"headline pick failed: {exc}")
        return fallback


async def rank_topic(
    client: httpx.AsyncClient,
    interest: Interest,
    rows: list[NewsCandidate],
) -> TopicRank | None:
    if not rows:
        return None
    if len(rows) == 1:
        return TopicRank(best_id=rows[0].id, candidates=[])
    user = (
        f"Beat: {interest.id} ({interest.label})\n\n"
        f"Candidates:\n{json.dumps(_cards(rows), ensure_ascii=True)}"
    )
    try:
        out = await complete_json(
            client,
            RANK_SYSTEM,
            user,
            TopicRank,
            agent=f"rank {interest.id}",
        )
        return apply_rank(rows, out)
    except Exception as exc:
        warn(f"rank {interest.id} failed: {exc}")
        return fallback_rank(rows)


async def build_briefing(
    client: httpx.AsyncClient,
    interests: list[Interest],
    candidates: list[NewsCandidate],
) -> GatherBriefing:
    # A trial topic is an experiment; it never leads the paper.
    trial_ids = {interest.id for interest in interests if interest.kind == "trial"}
    front_pool = [row for row in candidates if row.interest_id not in trial_ids] or candidates
    headline_id = await pick_headline(client, front_pool)
    info(f"headline {headline_id}")
    jobs = [
        (interest, leftover_for_topic(candidates, interest.id, headline_id))
        for interest in interests
    ]
    ranks = await asyncio.gather(
        *(rank_topic(client, interest, rows) for interest, rows in jobs)
    )
    topics: dict[TopicId, TopicRank] = {}
    for (interest, rows), rank in zip(jobs, ranks):
        if rank is None:
            continue
        topics[interest.id] = rank
        info(f"rank {interest.id}: best={rank.best_id} rest={len(rank.candidates)}")
    return GatherBriefing(headline_id=headline_id, topics=topics)
