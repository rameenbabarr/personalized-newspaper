from __future__ import annotations

import json

import httpx

from src.agents.llm import complete_json
from src.log import warn
from src.models import DiscoveryPick

OPUS = "claude-opus-5"

SYSTEM = """You pick one new topic for tomorrow's edition of The Rameen Times, as an experiment.

The reader chose five standing beats. Your job is to guess one topic she has NOT asked for but would plausibly enjoy, so the paper can learn whether to add it. You get her profile (every field optional), her interests file (user.md), the topics she already reads, and topics that must not be suggested.

Rules:
- Adjacent but new. Reach from what she already likes and who she is, but do not pick a sub-topic of an existing beat (no "Gaza aid" when Palestine is a beat, no "Mars rovers" when Space is).
- Concrete enough to have fresh news or new work this week. "Urdu calligraphy" or "independent bookshops", not "culture" or "lifestyle".
- Treat age and gender as weak hints at most. Never pick a topic because of a stereotype.
- Nothing political, military or security-related. No celebrity gossip, crypto, betting, or diet culture.
- Never use a slug, or a near-synonym of a label, from the excluded list.

Return:
- slug: lowercase words joined by hyphens, at most 40 characters.
- label: the topic as a short section name, e.g. "Urdu calligraphy".
- why: one sentence addressed to her, saying what in her profile or interests suggested it. Printed in the paper.
- queries: exactly 4 short news-search strings for this topic.
"""


def _payload(profile: dict, user_md: str, reading: list[str], excluded: set[str]) -> str:
    return (
        f"PROFILE\n{json.dumps(profile, indent=2, default=str)}\n\n"
        f"ALREADY READS\n{json.dumps(reading)}\n\n"
        f"EXCLUDED SLUGS\n{json.dumps(sorted(excluded))}\n\n"
        f"USER.MD\n{user_md}"
    )


async def discover_topic(
    client: httpx.AsyncClient,
    profile: dict,
    user_md: str,
    reading: list[str],
    excluded: set[str],
) -> DiscoveryPick | None:
    """One new trial topic, or None: a day without a trial is fine, a trial
    that repeats a rejected topic is not."""
    user = _payload(profile, user_md, reading, excluded)
    for _ in range(2):
        try:
            pick = await complete_json(
                client,
                SYSTEM,
                user,
                DiscoveryPick,
                agent="discover",
                model=OPUS,
            )
        except Exception as exc:
            warn(f"discover failed: {exc}")
            return None
        if pick.slug not in excluded:
            return pick
        warn(f"discover picked excluded topic {pick.slug!r}")
        user += f"\n\n{pick.slug!r} is excluded. Pick a different topic."
    return None
