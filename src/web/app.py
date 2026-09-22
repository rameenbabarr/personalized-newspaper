"""The taste server: one-click votes from the PDF, a card view, and trends.

Standard library only. It binds to 127.0.0.1 and has no auth, because it is a
single-reader tool on this laptop; do not expose the port.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import ROOT, TASTE_PORT
from src.log import info
from src.models import Edition
from src.render.edition import SECTION_LABELS
from src.taste import db, trends

HOST = "127.0.0.1"
PORT = TASTE_PORT
EDITIONS = ROOT / "editions"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FILE = re.compile(r"^[\w.-]+$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_env = Environment(
    loader=FileSystemLoader(ROOT / "templates" / "web"),
    autoescape=select_autoescape(["html"]),
)


def topic_labels() -> dict[str, str]:
    """Core beat labels plus every discovery topic's label."""
    return {**SECTION_LABELS, **{t["slug"]: t["label"] for t in db.topics()}}


_env.filters["topic_label"] = lambda topic: topic_labels().get(topic, topic)


def load_edition(day: str) -> Edition | None:
    if not _DATE.match(day):
        return None
    path = EDITIONS / day / f"{day}.json"
    if not path.is_file():
        return None
    try:
        return Edition.model_validate_json(path.read_text())
    except ValueError:
        return None


def edition_dates() -> list[str]:
    return sorted(
        (p.name for p in EDITIONS.glob("*/") if _DATE.match(p.name) and (p / f"{p.name}.json").is_file()),
        reverse=True,
    )


def _image_for(day: str, url: str | None) -> str | None:
    """Reuse the photo the renderer already downloaded, named by URL hash."""
    if not url:
        return None
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    folder = EDITIONS / day / "images"
    found = sorted(folder.glob(f"{digest}*")) if folder.is_dir() else []
    # Prefer the cropped variant the paper printed; fall back to the original.
    cropped = [p for p in found if "_r" in p.stem]
    pick = (cropped or found or [None])[0]
    return f"/images/{day}/{pick.name}" if pick else None


def page_day(day: str | None) -> tuple[int, str]:
    dates = edition_dates()
    day = day or (dates[0] if dates else None)
    edition = load_edition(day) if day else None
    if edition is None:
        return 404, _env.get_template("empty.html").render(dates=dates)
    votes = {s["id"]: s["vote"] for s in db.stories_with_votes()}
    cards = [
        {
            "article": article,
            "topic": article.topic or db.topic_of(article.id),
            "vote": votes.get(article.id, 0),
            "image": _image_for(edition.date, article.image_url),
        }
        for article in edition.articles
    ]
    return 200, _env.get_template("day.html").render(edition=edition, cards=cards, dates=dates)


def page_trends() -> tuple[int, str]:
    topics = db.topics()
    summary = trends.summarize(db.stories_with_votes(), date.today(), topics)
    labels = topic_labels()
    shown = summary["weeks"][-1]["topics"].keys() if summary["weeks"] else SECTION_LABELS.keys()
    by_status: dict[str, list[dict]] = {}
    for topic in topics:
        by_status.setdefault(topic["status"], []).append(topic)
    return 200, _env.get_template("trends.html").render(
        summary=summary,
        chart=json.dumps(summary["weeks"]),
        labels=json.dumps({key: labels.get(key, key) for key in shown}),
        topics=by_status,
        max_adopted=db.MAX_ADOPTED,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "RameenTaste/1.0"

    def log_message(self, fmt: str, *args: object) -> None:  # quiet by default
        return

    def _send(self, status: int, body: str | bytes, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, where: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", where)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = parse_qs(url.query)
        try:
            if not parts:
                self._send(*page_day(None))
            elif parts[0] == "day" and len(parts) == 2:
                self._send(*page_day(parts[1]))
            elif parts[0] == "trends" and len(parts) == 1:
                self._send(*page_trends())
            elif parts[0] == "api" and parts[1:] == ["trends"]:
                summary = trends.summarize(db.stories_with_votes(), date.today())
                self._send(200, json.dumps(summary, indent=2), "application/json")
            elif parts[0] == "vote" and len(parts) == 3 and parts[2] in {"up", "down"}:
                self._vote(parts[1], 1 if parts[2] == "up" else -1, query)
            elif parts[0] == "topic" and len(parts) == 3 and parts[2] in {"drop", "adopt", "undo"}:
                self._topic(parts[1], parts[2])
            elif parts[0] == "images" and len(parts) == 3:
                self._image(parts[1], parts[2])
            else:
                self._send(404, "not found", "text/plain")
        except Exception as exc:  # a bad request must not kill the server
            self._send(500, f"error: {exc}", "text/plain")

    def _vote(self, story_id: str, value: int, query: dict) -> None:
        recorded = db.vote(story_id, value)
        back = (query.get("back") or [""])[0]
        if recorded and back.startswith("/"):
            self._redirect(f"{back}#{story_id}")
            return
        story = next((s for s in db.stories_with_votes() if s["id"] == story_id), None)
        html = _env.get_template("voted.html").render(
            recorded=recorded, value=value, story=story
        )
        self._send(200 if recorded else 404, html)

    def _topic(self, slug: str, action: str) -> None:
        if not _SLUG.match(slug) or db.get_topic(slug) is None:
            self._send(404, "not found", "text/plain")
            return
        db.set_topic(slug, action)
        self._redirect("/trends#topics")

    def _image(self, day: str, name: str) -> None:
        if not _DATE.match(day) or not _FILE.match(name):
            self._send(404, "not found", "text/plain")
            return
        path = EDITIONS / day / "images" / name
        if not path.is_file():
            self._send(404, "not found", "text/plain")
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype)


def serve(host: str = HOST, port: int = PORT) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    info(f"taste server on http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
