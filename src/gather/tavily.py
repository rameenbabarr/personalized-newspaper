from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from src.log import info
from src.models import Interest, NewsCandidate, TopicId

SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"
NEWS_BEATS = {"palestine", "tech-ai", "islamabad-folk"}
EXCLUDE_DOMAINS = ["dawn.com", "tribune.com.pk"]
MAX_EXTRACT = 20


def tavily_key() -> str:
    key = os.environ.get("TVLY_API_KEY")
    if not key:
        raise RuntimeError("TVLY_API_KEY is not set")
    return key


def _candidate_id(interest_id: str, url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f"{interest_id}-{digest}"


def _first_image(value: object) -> str | None:
    if isinstance(value, str) and value.startswith("http"):
        return value
    if isinstance(value, list):
        for item in value:
            found = _first_image(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("url", "src", "image"):
            found = _first_image(value.get(key))
            if found:
                return found
    return None


def _source_name(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host or "Unknown"


def _parse_date(raw: object) -> datetime | None:
    if not raw:
        return None
    text = str(raw)
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            value = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def topic_for(interest_id: TopicId) -> str:
    return "news" if interest_id in NEWS_BEATS else "general"


def candidate_from_search(interest: Interest, hit: dict) -> NewsCandidate | None:
    title = str(hit.get("title") or "").strip()
    url = str(hit.get("url") or "").strip()
    if not title or not url:
        return None
    snippet = str(hit.get("content") or hit.get("snippet") or "")[:400]
    source_name = _source_name(url)
    host = urlparse(url).netloc.lower()
    if any(blocked in host for blocked in EXCLUDE_DOMAINS):
        return None
    image = _first_image(hit.get("images") or hit.get("image"))
    return NewsCandidate(
        id=_candidate_id(interest.id, url),
        interest_id=interest.id,
        title=title,
        snippet=snippet,
        source_name=source_name,
        source_url=url,
        image_url=image,
        published_at=_parse_date(hit.get("published_date") or hit.get("published_at")),
    )


def apply_extract(candidate: NewsCandidate, row: dict) -> None:
    raw = str(row.get("raw_content") or row.get("content") or "").strip()
    if raw:
        candidate.article_text = raw
    if not candidate.image_url:
        image = _first_image(row.get("images") or row.get("image"))
        if image:
            candidate.image_url = image


async def search(
    client: httpx.AsyncClient,
    query: str,
    interest: Interest,
    max_results: int = 5,
) -> list[NewsCandidate]:
    response = await client.post(
        SEARCH_URL,
        headers={
            "Authorization": f"Bearer {tavily_key()}",
            "Content-Type": "application/json",
        },
        json={
            "query": query,
            "topic": topic_for(interest.id),
            "time_range": "day",
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_images": True,
            "exclude_domains": EXCLUDE_DOMAINS,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    hits = response.json().get("results") or []
    out: list[NewsCandidate] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        candidate = candidate_from_search(interest, hit)
        if candidate:
            out.append(candidate)
    info(f"tavily search {interest.id!r} {query!r}: {len(out)} hits")
    return out


async def extract(client: httpx.AsyncClient, urls: list[str]) -> list[dict]:
    if not urls:
        return []
    response = await client.post(
        EXTRACT_URL,
        headers={
            "Authorization": f"Bearer {tavily_key()}",
            "Content-Type": "application/json",
        },
        json={
            "urls": urls[:MAX_EXTRACT],
            "extract_depth": "advanced",
            "format": "text",
            "include_images": True,
        },
        timeout=60.0,
    )
    response.raise_for_status()
    rows = response.json().get("results") or []
    return [row for row in rows if isinstance(row, dict)]


def _match_row(url: str, rows: list[dict]) -> dict | None:
    for row in rows:
        found = str(row.get("url") or "")
        if found == url or found.rstrip("/") == url.rstrip("/"):
            return row
    for row in rows:
        found = str(row.get("url") or "")
        if found and (found in url or url in found):
            return row
    return None


async def fill_extracts(client: httpx.AsyncClient, candidates: list[NewsCandidate]) -> None:
    need = [c for c in candidates if not c.article_text]
    if not need:
        return
    rows = await extract(client, [c.source_url for c in need])
    info(f"tavily extract requested {len(need)}, got {len(rows)} rows")
    for candidate in need:
        row = _match_row(candidate.source_url, rows)
        if row:
            apply_extract(candidate, row)
            n = len(candidate.article_text or "")
            photo = "photo" if candidate.image_url else "no-photo"
            info(f"extract {candidate.id}: {n} chars, {photo}")
        else:
            info(f"extract miss {candidate.id}")
