from __future__ import annotations

from datetime import datetime

import httpx

from src.agents.llm import complete_json
from src.config import TZ
from src.log import error
from src.models import CopyChiefIn, CopyChiefOut, Edition

SYSTEM = """You are CopyChief of The Rameen Times. Reply with one JSON object only.

One review pass. You are the only editorial drop after the Chief.
Must leave exactly one lead.
The lead and every secondary must have a photograph. Issue missing-image if one does not.
At most two stories from any one section. Issue unbalanced if one beat dominates.
Kill leftover link-out lines (read more, full story at, see the linked report, click, URL-as-copy). Issue link-out.
A lead under 6 paragraphs or a secondary under 4 is too-thin unless the writer had no article_text.
Do not invent facts. Drop political Islamabad if a Writer slipped.
Keep source_name and source_url on every news story.
Do not trim a finished story just to hit 2 pages.
edition.tagline may use the kicker.
edition.timezone is Asia/Karachi.
edition.paper_name is The Rameen Times.
"""


async def run_copy(client: httpx.AsyncClient, payload: CopyChiefIn) -> CopyChiefOut:
    try:
        out = await complete_json(client, SYSTEM, payload.model_dump_json(), CopyChiefOut, agent="CopyChief")
        return _ensure_lead(out, payload)
    except Exception as exc:
        error(f"copy chief failed: {exc}")
        return _fallback(payload)


def _fallback(payload: CopyChiefIn) -> CopyChiefOut:
    articles = list(payload.articles)
    leads = [a for a in articles if a.role == "lead"]
    if not leads and articles:
        articles[0].role = "lead"
    elif len(leads) > 1:
        keep = next((a for a in leads if a.image_url), leads[0])
        for article in articles:
            if article.role == "lead" and article.id != keep.id:
                article.role = "secondary"
    edition = Edition(
        paper_name="The Rameen Times",
        date=payload.date,
        volume=payload.volume,
        tagline=payload.kicker,
        generated_at=datetime.now(TZ),
        timezone="Asia/Karachi",
        diary=payload.diary,
        desk=payload.desk,
        desk_column=payload.desk_column,
        articles=articles,
        page_mode="thin" if len(articles) < 6 else "news-spread",
        diary_note=payload.diary_note,
        desk_note=payload.desk_note,
    )
    return CopyChiefOut(edition=edition, issues=[], dropped_article_ids=[])


def _ensure_lead(out: CopyChiefOut, payload: CopyChiefIn) -> CopyChiefOut:
    edition = out.edition
    edition.paper_name = "The Rameen Times"
    edition.date = payload.date
    edition.volume = payload.volume
    edition.timezone = "Asia/Karachi"
    edition.diary = payload.diary
    edition.desk = payload.desk
    if payload.desk_column and not edition.desk_column:
        edition.desk_column = payload.desk_column
    if payload.kicker and not edition.tagline:
        edition.tagline = payload.kicker
    leads = [a for a in edition.articles if a.role == "lead"]
    if not leads and edition.articles:
        edition.articles[0].role = "lead"
    elif len(leads) > 1:
        keep = next((a for a in leads if a.image_url), leads[0])
        for article in edition.articles:
            if article.role == "lead" and article.id != keep.id:
                article.role = "secondary"
    return out
