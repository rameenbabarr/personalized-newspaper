import threading
from datetime import datetime
from http.server import ThreadingHTTPServer

import httpx
import pytest

from src.config import TZ
from src.models import Article, Desk, Edition
from src.taste import db
from src.web import app

DAY = "2026-09-20"


@pytest.fixture
def server(tmp_path, monkeypatch):
    editions = tmp_path / "editions"
    (editions / DAY).mkdir(parents=True)
    edition = Edition(
        paper_name="The Rameen Times",
        date=DAY,
        volume="Vol. I",
        generated_at=datetime(2026, 9, 20, tzinfo=TZ),
        timezone="Asia/Karachi",
        diary=[],
        desk=Desk(pending=[], in_progress=[]),
        articles=[
            Article(id="space-abc", headline="Comet <b>bright</b>", section="Space",
                    body=["A comet."], role="lead", source_url="https://e.com/c",
                    source_name="NASA", themes=["comets"]),
        ],
    )
    (editions / DAY / f"{DAY}.json").write_text(edition.model_dump_json())
    monkeypatch.setattr(app, "EDITIONS", editions)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "taste.db")
    db.record_edition(edition)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_day_page_lists_stories_escaped(server) -> None:
    page = httpx.get(f"{server}/")
    assert page.status_code == 200
    assert "Comet &lt;b&gt;bright&lt;/b&gt;" in page.text
    assert "/vote/space-abc/up" in page.text
    assert "comets" in page.text


def test_pdf_vote_link_records_and_confirms(server) -> None:
    page = httpx.get(f"{server}/vote/space-abc/up")
    assert page.status_code == 200 and "Noted" in page.text
    assert db.stories_with_votes()[0]["vote"] == 1


def test_card_vote_redirects_back(server) -> None:
    page = httpx.get(f"{server}/vote/space-abc/down?back=/day/{DAY}")
    assert page.status_code == 303
    assert page.headers["location"] == f"/day/{DAY}#space-abc"
    assert db.stories_with_votes()[0]["vote"] == -1


def test_unknown_story_vote_is_404(server) -> None:
    assert httpx.get(f"{server}/vote/space-nope/up").status_code == 404


def test_trends_page_and_api(server) -> None:
    httpx.get(f"{server}/vote/space-abc/up")
    assert httpx.get(f"{server}/trends").status_code == 200
    api = httpx.get(f"{server}/api/trends").json()
    assert api["up"] == 1 and api["top_themes"][0]["theme"] == "comets"


def test_image_path_traversal_is_refused(server) -> None:
    assert httpx.get(f"{server}/images/{DAY}/..%2F..%2Fkeys.txt").status_code == 404
    assert httpx.get(f"{server}/images/../x.jpg").status_code == 404


def test_topic_actions_redirect_and_change_status(server) -> None:
    from src.models import DiscoveryPick

    db.start_trial(DiscoveryPick(slug="urdu-calligraphy", label="Urdu calligraphy", why="w",
                                 queries=["a", "b", "c", "d"]), "2026-09-19")
    db.set_topic("urdu-calligraphy", "adopt")
    page = httpx.get(f"{server}/topic/urdu-calligraphy/drop")
    assert page.status_code == 303 and page.headers["location"] == "/trends#topics"
    assert db.get_topic("urdu-calligraphy")["status"] == "rejected"
    trends_page = httpx.get(f"{server}/trends").text
    assert "Urdu calligraphy" in trends_page and "/topic/urdu-calligraphy/undo" in trends_page


def test_topic_action_on_bad_slug_is_404(server) -> None:
    assert httpx.get(f"{server}/topic/Bad_Slug/drop").status_code == 404
    assert httpx.get(f"{server}/topic/unknown/drop").status_code == 404
