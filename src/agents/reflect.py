from __future__ import annotations

import json

import httpx

from src.agents.llm import complete_json
from src.log import warn
from src.models import TasteReport

OPUS = "claude-opus-5"
# Below this many votes a "trend" is noise, and the agent would narrate it anyway.
MIN_VOTES = 10

SYSTEM = """You are the reader's editor at The Rameen Times. Once a week you read how Rameen voted on the stories she was given and say how her taste is moving.

You get: vote counts per topic per week (including discovery topics she adopted), the history of discovery topics (adopted, waiting, rejected, skipped), themes whose net votes rose or fell between the last four weeks and the four before, her all-time liked and disliked themes, her most recent liked and disliked headlines, and her current interests file (user.md).

Return:
- summary: 3 to 5 plain sentences. What she is reading more of, what less, and anything that has stayed steady. Name specific themes, not just topics.
- rising / fading: themes with a one-line evidence note that cites the numbers you were given.
- suggested_edits: concrete changes to user.md. section is the user.md heading (Palestine, Art and crafts, Islamabad folk, Space, Tech and AI). change is the exact wording to add or remove. Suggest nothing that her votes do not support.

Use only the data given. Do not invent stories, numbers, or themes. If the data is thin, say so in the summary and keep suggestions to a minimum.
"""


def thin_report(votes: int) -> TasteReport:
    return TasteReport(
        summary=(
            f"Only {votes} vote{'s' if votes != 1 else ''} so far. "
            f"Trends need at least {MIN_VOTES}; keep tapping more or less on stories you read."
        ),
    )


async def reflect(client: httpx.AsyncClient, trends: dict, user_md: str) -> TasteReport:
    if trends.get("votes", 0) < MIN_VOTES:
        return thin_report(trends.get("votes", 0))
    user = f"TRENDS\n{json.dumps(trends, indent=2)}\n\nUSER.MD\n{user_md}"
    try:
        return await complete_json(
            client,
            SYSTEM,
            user,
            TasteReport,
            agent="reflect",
            model=OPUS,
        )
    except Exception as exc:
        warn(f"reflect agent failed: {exc}")
        return fallback_report(trends)


def fallback_report(trends: dict) -> TasteReport:
    """Plain-rule report from the numbers alone, used when the agent fails."""
    shift = trends.get("shift") or {}
    rising = [r["theme"] for r in shift.get("rising", [])[:3]]
    fading = [r["theme"] for r in shift.get("fading", [])[:3]]
    parts = [f"{trends.get('up', 0)} liked and {trends.get('down', 0)} disliked so far."]
    if rising:
        parts.append(f"Rising: {', '.join(rising)}.")
    if fading:
        parts.append(f"Fading: {', '.join(fading)}.")
    return TasteReport(summary=" ".join(parts))
