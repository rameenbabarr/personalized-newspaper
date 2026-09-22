from __future__ import annotations

import asyncio
import hashlib
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from time import struct_time
from typing import Iterable
from urllib.parse import urlparse

import feedparser
import httpx

from src.agents.queries import ensure_queries
from src.config import load_topics
from src.gather.tavily import search as tavily_search
from src.log import info, warn
from src.models import Interest, NewsCandidate, SeenEntry
from src.seen import is_seen, load_seen

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
FEED_LIMIT = 5
BLOCKED_HOSTS = ("dawn.com", "tribune.com.pk")
BLOCKED_SOURCES = {
    "dawn",
    "dawn.com",
    "the tribune",
    "express tribune",
    "the express tribune",
}


def _candidate_id(interest_id: str, url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f"{interest_id}-{digest}"


def _strip_html(raw: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", raw or ""))
    return re.sub(r"\s+", " ", text).strip()


def _feed_urls(interest: Interest) -> list[str]:
    return list(interest.feeds)


def _parse_published(entry: dict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if isinstance(parsed, struct_time):
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    raw = entry.get("published") or entry.get("updated") or entry.get("pubDate")
    if not raw:
        return None
    try:
        value = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _entry_url(entry: dict) -> str:
    link = entry.get("link")
    if isinstance(link, str) and link.strip():
        return link.strip()
    links = entry.get("links") or []
    for item in links:
        href = item.get("href") if isinstance(item, dict) else None
        if href:
            return str(href)
    return ""


def _entry_source(entry: dict, title: str) -> str:
    source = entry.get("source")
    if isinstance(source, dict) and source.get("title"):
        return str(source["title"]).strip()
    if isinstance(source, str) and source.strip():
        return source.strip()
    author = entry.get("author")
    if isinstance(author, str) and author.strip() and "google" not in author.lower():
        return author.strip()
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return "Unknown"


def _entry_image(entry: dict) -> str | None:
    for media in entry.get("media_content") or []:
        url = media.get("url") if isinstance(media, dict) else None
        typ = str(media.get("type") or "") if isinstance(media, dict) else ""
        if url and (typ.startswith("image") or not typ):
            return str(url)
    for thumb in entry.get("media_thumbnail") or []:
        url = thumb.get("url") if isinstance(thumb, dict) else None
        if url:
            return str(url)
    for enc in entry.get("enclosures") or []:
        url = enc.get("href") if isinstance(enc, dict) else None
        typ = str(enc.get("type") or "") if isinstance(enc, dict) else ""
        if url and typ.startswith("image"):
            return str(url)
    return None


def parse_feed(xml: str, interest: Interest) -> list[NewsCandidate]:
    parsed = feedparser.parse(xml)
    out: list[NewsCandidate] = []
    for entry in parsed.entries:
        title = _strip_html(str(entry.get("title") or "")).strip()
        url = _entry_url(entry)
        if not title or not url:
            continue
        snippet = _strip_html(str(entry.get("summary") or entry.get("description") or ""))[:400]
        source_name = _entry_source(entry, title)
        if source_name != "Unknown" and title.endswith(f" - {source_name}"):
            title = title[: -len(source_name) - 3].strip()
        out.append(
            NewsCandidate(
                id=_candidate_id(interest.id, url),
                interest_id=interest.id,
                title=title,
                snippet=snippet,
                source_name=source_name,
                source_url=url,
                image_url=_entry_image(entry),
                published_at=_parse_published(entry),
            )
        )
    dated = [item for item in out if item.published_at]
    undated = [item for item in out if not item.published_at]
    dated.sort(key=lambda item: item.published_at or datetime.min, reverse=True)
    return (dated + undated)[:FEED_LIMIT]


def _host(url: str) -> str:
    return urlparse(url).netloc.lower()


def is_blocked_source(source_name: str, url: str) -> bool:
    host = _host(url)
    if any(blocked in host for blocked in BLOCKED_HOSTS):
        return True
    return source_name.strip().lower() in BLOCKED_SOURCES


def should_drop(interest: Interest, candidate: NewsCandidate) -> bool:
    if is_blocked_source(candidate.source_name, candidate.source_url):
        return True
    hay = f"{candidate.title} {candidate.snippet}".casefold()
    if interest.require_any and not any(word.casefold() in hay for word in interest.require_any):
        return True
    if not interest.drop_if:
        return False
    return any(word.casefold() in hay for word in interest.drop_if)


def _preferred(interest: Interest, candidate: NewsCandidate) -> bool:
    name = candidate.source_name.casefold()
    return any(pref.casefold() in name for pref in interest.prefer_sources)


def rank_candidates(interest: Interest, rows: list[NewsCandidate]) -> list[NewsCandidate]:
    ranked = list(rows)
    ranked.sort(key=lambda c: (0 if _preferred(interest, c) else 1, c.published_at is None))
    return ranked


def select_candidates(
    collected: Iterable[NewsCandidate],
    interests: list[Interest],
    seen: list[SeenEntry],
) -> list[NewsCandidate]:
    by_id = {item.id: item for item in interests}
    unique: list[NewsCandidate] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    for candidate in collected:
        interest = by_id.get(candidate.interest_id)
        url = candidate.source_url
        title_key = candidate.title.casefold()
        if url in seen_urls or title_key in seen_titles:
            continue
        if is_seen(seen, url, candidate.title):
            continue
        if interest and should_drop(interest, candidate):
            continue
        seen_urls.add(url)
        seen_titles.add(title_key)
        unique.append(candidate)
    return unique


async def _fetch_text(client: httpx.AsyncClient, url: str, timeout: float = 12.0) -> str | None:
    try:
        response = await client.get(url, timeout=timeout)
        if response.status_code >= 400:
            return None
        return response.text
    except httpx.HTTPError:
        return None


async def gather_news(
    interests: list[Interest] | None = None,
    seen: list[SeenEntry] | None = None,
) -> list[NewsCandidate]:
    interests = interests if interests is not None else load_topics()
    ensure_queries(interests)
    seen = seen if seen is not None else load_seen()
    collected: list[NewsCandidate] = []
    headers = {"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, text/html"}

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        jobs = [(interest, url) for interest in interests for url in _feed_urls(interest)]
        bodies = await asyncio.gather(*[_fetch_text(client, url) for _, url in jobs])
        for (interest, _), xml in zip(jobs, bodies):
            if not xml:
                continue
            try:
                collected.extend(parse_feed(xml, interest))
            except Exception:
                continue

        tavily_key = os.environ.get("TVLY_API_KEY")
        if not tavily_key:
            raise RuntimeError("TVLY_API_KEY is not set")
        search_jobs = [
            (interest, query)
            for interest in interests
            for query in interest.queries
        ]

        async def one_search(interest: Interest, query: str) -> list[NewsCandidate]:
            try:
                return await tavily_search(client, query, interest)
            except Exception as exc:
                warn(f"tavily search failed {interest.id} {query!r}: {exc}")
                return []

        info(f"rss collected {len(collected)} raw entries")
        searched = await asyncio.gather(*(one_search(i, q) for i, q in search_jobs))
        for rows in searched:
            collected.extend(rows)
        info(f"search+rss collected {len(collected)} raw entries")
        picked = select_candidates(collected, interests, seen)

    return picked


def main() -> None:
    candidates = asyncio.run(gather_news())
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.interest_id] = counts.get(candidate.interest_id, 0) + 1
    print(f"{len(candidates)} fresh candidates")
    for interest_id, count in counts.items():
        print(f"  {interest_id}: {count}")
    for candidate in candidates:
        photo = "photo" if candidate.image_url else "no-photo"
        print(f"- [{candidate.interest_id}] {candidate.title} ({candidate.source_name}, {photo})")


if __name__ == "__main__":
    main()
