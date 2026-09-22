from __future__ import annotations

import httpx

from src.agents.llm import complete_json
from src.log import warn
from src.models import Interest, InterestId, QueryPlan

FALLBACK_QUERIES: dict[InterestId, list[str]] = {
    "palestine": [
        "Gaza humanitarian",
        "West Bank",
        "Palestinian culture",
        "Palestine aid",
    ],
    "art-crafts": [
        "South Asian crafts",
        "Pakistani crafts",
        "printmaking",
        "ceramics workshop",
    ],
    "islamabad-folk": [
        "Islamabad art gallery",
        "Lok Virsa",
        "PNCA Islamabad",
        "Islamabad craft bazaar",
    ],
    "space": [
        "NASA launch",
        "ESA mission",
        "astronomy discovery",
        "James Webb",
    ],
    "tech-ai": [
        "artificial intelligence research",
        "open source AI",
        "open weights model",
        "local LLM",
    ],
}

SYSTEM = """You write search queries for The Rameen Times morning gather.

Read the user profile. Emit exactly 4 search queries for each of these topics: palestine, art-crafts, islamabad-folk, space, tech-ai.

Every topic must have 4 queries. Cover the angles in that section. No empty topic. Queries are short search strings, not sentences.
"""


def fallback_plan() -> QueryPlan:
    return QueryPlan(queries=dict(FALLBACK_QUERIES))


def apply_queries(interests: list[Interest], plan: QueryPlan) -> None:
    # Only the five core beats are in the plan; discovery topics bring their own.
    for interest in interests:
        if interest.id in plan.queries:
            interest.queries = list(plan.queries[interest.id])


def ensure_queries(interests: list[Interest]) -> None:
    for interest in interests:
        if not interest.queries and interest.id in FALLBACK_QUERIES:
            interest.queries = list(FALLBACK_QUERIES[interest.id])  # type: ignore[index]


async def generate_queries(
    client: httpx.AsyncClient,
    user_md: str,
    date: str,
) -> QueryPlan:
    try:
        return await complete_json(
            client,
            SYSTEM,
            f"Date: {date}\n\n{user_md}",
            QueryPlan,
            agent="queries",
        )
    except Exception as exc:
        warn(f"query agent failed: {exc}")
        return fallback_plan()
