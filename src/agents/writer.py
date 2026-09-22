from __future__ import annotations

import re

import httpx

from src.agents.llm import complete_json
from src.log import error
from src.models import Article, NewsCandidate, WriterAssignment, WriterIn, WriterOut

SYSTEM = """You are a Writer at The Rameen Times. Reply with one JSON object: { "article": { ... } }.

You do not pick the story. Write the assignment from the source text you were given.
- Lead body: 6 to 10 short paragraphs. Secondary: 4 to 6. Brief: 2 to 3.
- Rewrite the source. Do not paste. Do not invent quotes, death tolls, or diplomacy.
- Finish the story on the page. The reader should not need another tab.
- Ban these: "read more", "full story at", "see the linked report", "click", a URL used as copy.
- If article_text is empty, write shorter from title and snippet. Still no link-out language.
- article.id equals candidate.id.
- Copy source_name and source_url from the candidate. Copy image_url only if use_image is true and the image is related. Do not invent a URL.
- Short newspaper English. First sentence carries the news.
- Byline is "By the night editor".
- dek is one sentence, shown as the photo's caption when the story runs with an image. It should say what the photo shows or why it matters, in different words than the headline. Do not also spend the body's opening paragraph describing the photo; the caption already does that. Write about substance instead: context, stakes, what happens next.
"""

_LIMITS = {"lead": 10, "secondary": 6, "brief": 3}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def _forced_article(assignment: WriterAssignment, candidate: NewsCandidate) -> Article:
    limit = _LIMITS.get(assignment.role, 3)
    snippet = (candidate.snippet or "").strip()
    paras: list[str] = [snippet] if snippet else []
    # Pull whole, clean sentences from the extracted text rather than pasting a raw
    # slice, which can land mid-word or mid-navigation-menu. Skip anything that
    # duplicates the snippet already used for the dek.
    if candidate.article_text:
        for sentence in _sentences(candidate.article_text):
            if len(paras) >= limit:
                break
            if len(sentence) < 25 or sentence in paras:
                continue
            paras.append(sentence)
    if not paras:
        paras = [candidate.title]
    return Article(
        id=candidate.id,
        headline=candidate.title,
        dek="" if assignment.role == "brief" else (candidate.snippet[:160] if candidate.snippet else ""),
        byline="By the night editor",
        section=assignment.section,
        body=paras[: _LIMITS.get(assignment.role, 3)],
        role=assignment.role,
        image_url=candidate.image_url if assignment.use_image else None,
        source_url=candidate.source_url,
        source_name=candidate.source_name,
    )


async def run_writer(
    client: httpx.AsyncClient,
    assignment: WriterAssignment,
    candidate: NewsCandidate,
) -> Article | None:
    payload = WriterIn(assignment=assignment, candidate=candidate)
    name = f"Writer {assignment.role} {candidate.id}"
    try:
        out = await complete_json(client, SYSTEM, payload.model_dump_json(), WriterOut, agent=name)
        article = out.article
        article.id = candidate.id
        article.source_url = candidate.source_url
        article.source_name = candidate.source_name
        article.role = assignment.role
        if assignment.use_image:
            if not article.image_url:
                article.image_url = candidate.image_url
        else:
            article.image_url = None
        if not article.body:
            return _forced_article(assignment, candidate)
        return article
    except Exception as exc:
        error(f"writer failed {assignment.role} {candidate.id}: {exc}")
        try:
            return _forced_article(assignment, candidate)
        except Exception:
            return None
