from __future__ import annotations

import httpx

from src.agents.llm import complete_json
from src.log import error
from src.models import DiaryClerkIn, DiaryClerkOut, Meeting

SYSTEM = """You are DiaryClerk of The Rameen Times. Reply with one JSON object only.

Meetings stay as gathered. You may sort them and write a one-line intro.
Do not rename titles or invent events.
If meetings is empty, diary is [] and intro says there are no meetings.
"""


async def run_diary(client: httpx.AsyncClient, payload: DiaryClerkIn) -> DiaryClerkOut:
    try:
        return await complete_json(client, SYSTEM, payload.model_dump_json(), DiaryClerkOut, agent="DiaryClerk")
    except Exception as exc:
        error(f"diary clerk failed: {exc}")
        return fallback_diary(payload.meetings, payload.diary_note)


def fallback_diary(meetings: list[Meeting], note: str | None) -> DiaryClerkOut:
    ordered = sorted(meetings, key=lambda m: m.start)
    intro = "No meetings today." if not ordered else f"{len(ordered)} items on the diary."
    return DiaryClerkOut(diary=ordered, diary_note=note, intro=intro)
