from __future__ import annotations

from src.config import karachi_now, load_paper, volume_for
from src.render.tex import clip_sentences
from src.models import (
    _as_paragraphs,
    Article,
    BriefPiece,
    Desk,
    DeskColumn,
    Edition,
    LongPiece,
    StoriesOut,
    TaskItem,
)

SECTION_LABELS = {
    "palestine": "Palestine",
    "art-crafts": "Art and crafts",
    "islamabad-folk": "Islamabad folk",
    "space": "Space",
    "tech-ai": "Tech and AI",
}

# The writers are asked for about 2000 characters and routinely return 3000+.
# Sixteen stories at that length is a forty-thousand-character paper, which is
# what pushed the A4 edition to fifteen pages. Trim on whole paragraphs here so
# the cut is deterministic and never strands half a sentence: a model asked to
# self-edit would be neither.
BODY_LIMITS = {"lead": 2100, "secondary": 1500, "brief": 420}
# The trial box sets its text beside a photo in one unbreakable block.
TRIAL_LIMIT = 1100

# The strapline sits under the masthead on one line.
TAGLINE_LIMIT = 90


def trim_body(paragraphs: list[str], limit: int) -> list[str]:
    """Keep whole paragraphs up to `limit` characters, always at least one."""
    kept: list[str] = []
    used = 0
    for para in paragraphs:
        if kept and used + len(para) > limit:
            break
        kept.append(para)
        used += len(para)
    if not kept:
        kept = paragraphs[:1]
    # Keeping one whole paragraph is the floor, but a lone paragraph longer than
    # the whole budget still has to be cut, or the limit does nothing at all for
    # single-paragraph copy -- which every brief is.
    if len(kept) == 1 and len(kept[0]) > limit:
        kept = [clip_sentences(kept[0], limit)]
    return kept


def section_for(story_id: str, fallback: str = "News") -> str:
    for key, label in SECTION_LABELS.items():
        if story_id.startswith(key):
            return label
    return fallback


def topic_from_id(story_id: str) -> str:
    """Candidate ids are "<topic>-<12 hex>" (src/gather/news.py), so the topic
    is everything before the last hyphen -- core beat or discovery slug alike."""
    return story_id.rsplit("-", 1)[0] if "-" in story_id else ""


def _long_article(piece: LongPiece, role: str, section: str) -> Article:
    author = (piece.author or "").strip()
    return Article(
        id=piece.id,
        headline=piece.title,
        byline=f"By {author}" if author else "By the night editor",
        section=section,
        body=trim_body(_as_paragraphs(piece.body), BODY_LIMITS[role]),
        role=role,  # type: ignore[arg-type]
        image_url=piece.image_url,
        source_url=piece.source_url,
        source_name=piece.source_name,
        themes=piece.themes,
        topic=topic_from_id(piece.id),
    )


def _brief_article(piece: BriefPiece, section: str) -> Article:
    return Article(
        id=piece.id,
        headline=piece.title,
        byline="By the night editor",
        section=section,
        body=trim_body(_as_paragraphs(piece.body), BODY_LIMITS["brief"]),
        role="brief",
        image_url=piece.image_url,
        source_url="",
        source_name=section,
        themes=piece.themes,
        topic=topic_from_id(piece.id),
    )


def _tagline(stories: StoriesOut) -> str:
    """One short line under the masthead.

    Splitting on newlines alone is not enough: a note written as a single
    paragraph has none, and the whole note ends up set as the strapline.
    """
    note = " ".join((stories.reader_note or "").split())
    first = note.split("\n", 1)[0].strip()
    for stop in (". ", "! ", "? "):
        found = first.find(stop)
        if 0 < found <= TAGLINE_LIMIT:
            return first[: found + 1].strip()
    if first and len(first) <= TAGLINE_LIMIT:
        return first
    return str(load_paper().get("tagline") or "All the news that fits the morning")


def _desk(tasks: list[TaskItem]) -> Desk:
    pending = [task for task in tasks if task.status == "pending"]
    in_progress = [task for task in tasks if task.status == "in-progress"]
    ranked = [task.id for task in [*in_progress, *pending]]
    return Desk(pending=pending, in_progress=in_progress, ranked_ids=ranked)


def _desk_column(stories: StoriesOut) -> DeskColumn | None:
    note = (stories.reader_note or "").strip()
    if not note:
        return None
    return DeskColumn(headline="This morning", body=note)


def _trial_note(label: str, why: str) -> str:
    why = why.strip()
    return f"We guessed you might like {label}. {why}".strip() if why else f"We guessed you might like {label}."


def stories_to_edition(stories: StoriesOut) -> Edition:
    labels = {**SECTION_LABELS, **{tid: t.label for tid, t in stories.topics.items() if t.label}}
    used: set[str] = set()
    articles: list[Article] = []
    trial_note: str | None = None
    if stories.headline:
        topic = topic_from_id(stories.headline.id)
        articles.append(
            _long_article(stories.headline, "lead", labels.get(topic) or section_for(stories.headline.id))
        )
        used.add(stories.headline.id)
    for topic_id, topic in stories.topics.items():
        section = labels.get(topic_id, topic_id)
        if topic.lead and topic.lead.id not in used:
            article = _long_article(topic.lead, "secondary", section)
            if topic.kind == "trial":
                article.trial = True
                article.body = trim_body(article.body, TRIAL_LIMIT)
                trial_note = _trial_note(section, topic.why)
            articles.append(article)
            used.add(topic.lead.id)
        for brief in topic.briefs:
            if brief.id in used:
                continue
            articles.append(_brief_article(brief, section))
            used.add(brief.id)
    return Edition(
        paper_name=str(load_paper().get("paper_name") or "The Rameen Times"),
        date=stories.date,
        volume=volume_for(),
        tagline=_tagline(stories),
        generated_at=karachi_now(),
        timezone="Asia/Karachi",
        diary=list(stories.meetings),
        desk=_desk(stories.tasks),
        desk_column=_desk_column(stories),
        articles=articles,
        page_mode="thin" if len(articles) < 6 else "news-spread",
        diary_note=stories.diary_note,
        desk_note=stories.desk_note,
        weather=stories.weather,
        reader_note=stories.reader_note,
        trial_note=trial_note,
    )
