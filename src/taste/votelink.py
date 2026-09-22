"""Record a vote clicked in the PDF, without opening a browser.

The PDF's more/less links use a private scheme, rameen-vote://vote/<id>/<up|down>.
scripts/install-vote-links.sh registers this module as the desktop handler for
that scheme, so a click in the PDF viewer runs it: the vote goes straight into
data/taste.db and a short desktop notification confirms it. No server needed.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse

from src.config import VOTE_SCHEME
from src.taste import db

_PATH = re.compile(r"^/([A-Za-z0-9-]+)/(up|down)/?$")


def parse(url: str) -> tuple[str, int] | None:
    parsed = urlparse(url)
    if parsed.scheme != VOTE_SCHEME or parsed.netloc != "vote":
        return None
    match = _PATH.match(parsed.path)
    if not match:
        return None
    return match.group(1), 1 if match.group(2) == "up" else -1


def notify(title: str, body: str = "") -> None:
    """Best effort: a missing notifier must not lose the vote."""
    exe = shutil.which("notify-send")
    if not exe:
        return
    subprocess.run(
        [exe, "--app-name=The Rameen Times", "--expire-time=3000", title, body],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def record(url: str) -> bool:
    parsed = parse(url)
    if parsed is None:
        notify("Rameen Times: vote not saved", "That link is not a vote link.")
        return False
    story_id, value = parsed
    if not db.vote(story_id, value):
        notify("Rameen Times: vote not saved", "That story is not in the taste log.")
        return False
    story = next((s for s in db.stories_with_votes() if s["id"] == story_id), None)
    title = "More like this" if value > 0 else "Less like this"
    notify(f"Noted: {title.lower()}", story["headline"] if story else "")
    return True


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python -m src.taste.votelink rameen-vote://vote/<id>/<up|down>", file=sys.stderr)
        return 2
    return 0 if record(args[0]) else 1


if __name__ == "__main__":
    sys.exit(main())
