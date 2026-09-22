from datetime import datetime

import pytest

from src.config import TZ, VOTE_BASE
from src.models import Article, Desk, Edition
from src.taste import db, votelink


def test_pdf_links_use_the_private_scheme() -> None:
    assert VOTE_BASE == "rameen-vote://vote"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("rameen-vote://vote/space-3f2a9c/up", ("space-3f2a9c", 1)),
        ("rameen-vote://vote/urdu-calligraphy-3f2a9c/down/", ("urdu-calligraphy-3f2a9c", -1)),
        ("http://localhost:8765/vote/space-3f2a9c/up", None),
        ("rameen-vote://other/space-3f2a9c/up", None),
        ("rameen-vote://vote/space-3f2a9c/sideways", None),
        ("rameen-vote://vote/../../etc/up", None),
    ],
)
def test_parse(url, expected) -> None:
    assert votelink.parse(url) == expected


@pytest.fixture
def notes(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "taste.db")
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(votelink, "notify", lambda title, body="": shown.append((title, body)))
    db.record_edition(
        Edition(
            paper_name="The Rameen Times", date="2026-09-22", volume="Vol. I",
            generated_at=datetime(2026, 9, 22, tzinfo=TZ), timezone="Asia/Karachi",
            diary=[], desk=Desk(pending=[], in_progress=[]),
            articles=[Article(id="space-3f2a9c", headline="Sourdough chemistry", section="Space",
                              body=["b"], role="brief", source_url="", source_name="E")],
        )
    )
    return shown


def test_click_records_vote_and_notifies(notes) -> None:
    assert votelink.main(["rameen-vote://vote/space-3f2a9c/up"]) == 0
    assert db.stories_with_votes()[0]["vote"] == 1
    assert notes == [("Noted: more like this", "Sourdough chemistry")]


def test_unknown_story_or_bad_link_is_not_saved(notes) -> None:
    assert votelink.main(["rameen-vote://vote/space-nope/down"]) == 1
    assert votelink.main(["https://example.com"]) == 1
    assert db.stories_with_votes()[0]["vote"] == 0
    assert all("not saved" in title for title, _ in notes)
