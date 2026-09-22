from __future__ import annotations

import asyncio
import json

import httpx

from src.agents.llm import complete_json
from src.gather.news import rank_candidates
from src.log import info, warn
from src.models import Interest, NewsCandidate, TopicGateOut

OPUS = "claude-opus-5"
TOP_N = 4

SYSTEM = """You are the topic gate for The Rameen Times.

You see only titles, snippets, and URLs for one beat. Pick the best stories for this morning using the user profile for that beat.

Return up to 4 candidate ids, ranked best first. Prefer fresh, on-beat, preferred voices. Drop celebrity, hype, and anything the profile says to skip. Do not invent ids.
"""


def section_for(user_md: str, heading: str) -> str:
    marker = f"## {heading}"
    start = user_md.find(marker)
    if start < 0:
        return user_md.strip()
    start = start + len(marker)
    nxt = user_md.find("\n## ", start)
    body = user_md[start:] if nxt < 0 else user_md[start:nxt]
    return body.strip()


def fallback_picks(interest: Interest, rows: list[NewsCandidate], n: int = TOP_N) -> list[NewsCandidate]:
    return rank_candidates(interest, rows)[:n]


def _apply_ids(rows: list[NewsCandidate], ids: list[str]) -> list[NewsCandidate]:
    lookup = {candidate.id: candidate for candidate in rows}
    picked: list[NewsCandidate] = []
    seen: set[str] = set()
    for candidate_id in ids:
        candidate = lookup.get(candidate_id)
        if candidate is None or candidate.id in seen:
            continue
        picked.append(candidate)
        seen.add(candidate.id)
        if len(picked) == TOP_N:
            break
    return picked


async def gate_topic(
    client: httpx.AsyncClient,
    interest: Interest,
    section: str,
    candidates: list[NewsCandidate],
) -> list[NewsCandidate]:
    if not candidates:
        return []
    payload = [
        {
            "id": candidate.id,
            "title": candidate.title,
            "snippet": candidate.snippet,
            "source_url": candidate.source_url,
            "image_url": candidate.image_url,
        }
        for candidate in candidates
    ]
    user = (
        f"Beat: {interest.id} ({interest.label})\n\n"
        f"{section}\n\n"
        f"Candidates:\n{json.dumps(payload, ensure_ascii=True)}"
    )
    try:
        out = await complete_json(
            client,
            SYSTEM,
            user,
            TopicGateOut,
            agent=f"gate {interest.id}",
            model=OPUS,
        )
        picked = _apply_ids(candidates, out.candidate_ids)
        if picked:
            return picked
        warn(f"gate {interest.id}: no valid ids, using fallback")
    except Exception as exc:
        warn(f"gate {interest.id} failed: {exc}")
    return fallback_picks(interest, candidates)


async def gate_topics(
    client: httpx.AsyncClient,
    user_md: str,
    interests: list[Interest],
    candidates: list[NewsCandidate],
) -> list[NewsCandidate]:
    grouped: dict[str, list[NewsCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.interest_id, []).append(candidate)

    jobs: list[tuple[Interest, list[NewsCandidate]]] = []
    for interest in interests:
        rows = grouped.get(interest.id, [])
        if rows:
            jobs.append((interest, rows))
    if not jobs:
        return []

    results = await asyncio.gather(
        *(
            gate_topic(client, interest, interest.brief or section_for(user_md, interest.label), rows)
            for interest, rows in jobs
        )
    )
    picked: list[NewsCandidate] = []
    for (interest, _), rows in zip(jobs, results):
        info(f"gate {interest.id}: {len(rows)} of {len(grouped.get(interest.id, []))}")
        picked.extend(rows)
    return picked
