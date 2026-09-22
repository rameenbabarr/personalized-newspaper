from __future__ import annotations

from urllib.parse import urlparse

from src.log import info, warn

_DEAD_HOSTS = (
    "instagram.com",
    "cdninstagram.com",
    "facebook.com",
    "fb.com",
    "fbcdn.net",
    "fbsbx.com",
)


def is_unusable_image(url: str | None) -> bool:
    if not url or not url.strip():
        return True
    host = urlparse(url).netloc.lower()
    return any(dead in host for dead in _DEAD_HOSTS)


def image_query(article_text: str | None, title: str = "") -> str:
    text = (article_text or "").strip()
    if text:
        return text[:200]
    return title.strip()


def first_web_image(query: str) -> str | None:
    query = query.strip()
    if not query:
        return None
    try:
        from ddgs import DDGS
    except ImportError:
        warn("ddgs is not installed")
        return None
    try:
        rows = DDGS().images(query, max_results=5)
        for row in rows or []:
            url = row.get("image") or row.get("thumbnail")
            if url and not is_unusable_image(str(url)):
                info(f"ddg image {url}")
                return str(url)
    except Exception as exc:
        warn(f"ddg image failed: {exc}")
    return None


def ensure_image(image_url: str | None, article_text: str | None, title: str = "") -> str | None:
    if image_url and not is_unusable_image(image_url):
        return image_url
    return first_web_image(image_query(article_text, title))
