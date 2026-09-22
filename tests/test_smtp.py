from datetime import datetime

import pytest

from src.config import TZ
from src.deliver import smtp
from src.models import Desk, Edition


class FakeSMTP:
    logins: list[tuple[str, str]] = []

    def __init__(self, host: str, port: int) -> None:
        pass

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def starttls(self) -> None:
        pass

    def login(self, user: str, password: str) -> None:
        FakeSMTP.logins.append((user, password))

    def send_message(self, message: object) -> None:
        pass


@pytest.fixture
def send(tmp_path, monkeypatch):
    FakeSMTP.logins = []
    monkeypatch.setattr(smtp.smtplib, "SMTP", FakeSMTP)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("RAMEEN_APP_PASSWORD", raising=False)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    edition = Edition(
        paper_name="The Rameen Times",
        date="2026-09-22",
        volume="Vol. I",
        generated_at=datetime(2026, 9, 22, tzinfo=TZ),
        timezone="Asia/Karachi",
        diary=[],
        desk=Desk(pending=[], in_progress=[]),
        articles=[],
    )

    def run() -> str:
        smtp.send_pdf(edition, pdf)
        return FakeSMTP.logins[-1][1]

    return run


def test_gmail_app_password_is_used(send, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh")
    assert send() == "abcdefgh"


def test_old_rameen_name_still_works(send, monkeypatch) -> None:
    monkeypatch.setenv("RAMEEN_APP_PASSWORD", "old")
    assert send() == "old"


def test_gmail_name_wins_when_both_are_set(send, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "new")
    monkeypatch.setenv("RAMEEN_APP_PASSWORD", "old")
    assert send() == "new"


def test_missing_password_names_the_documented_variable(send) -> None:
    with pytest.raises(RuntimeError, match="GMAIL_APP_PASSWORD"):
        send()
