import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from src.models import TOPIC_IDS, Edition, Interest, InterestId

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Asia/Karachi")


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or (ROOT / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()
USER_MD_PATH = ROOT / "config" / "user.md"
FEEDS_PATH = ROOT / "config" / "feeds.json"
PAPER_PATH = ROOT / "config" / "paper.yaml"
SAMPLE_EDITION_PATH = ROOT / "config" / "sample-edition.json"
# Personal details for discovery topics. Gitignored; see profile.example.yaml.
PROFILE_PATH = ROOT / "config" / "profile.yaml"

# The local taste server (src/web/app.py): cards, trends, topic buttons.
TASTE_PORT = 8765
# The PDF's more/less links use a private scheme handled by src/taste/votelink.py
# (registered by scripts/install-vote-links.sh), so a click records the vote
# without opening a browser tab.
VOTE_SCHEME = "rameen-vote"
VOTE_BASE = f"{VOTE_SCHEME}://vote"

ISLAMABAD_DROP = [
    "election",
    "by-election",
    "parliament",
    "National Assembly",
    "Senate",
    "PTI",
    "PML-N",
    "PMLN",
    "PPP",
    "cabinet",
    "Imran Khan",
    "Nawaz",
    "Maryam",
    "Bilawal",
    "Sharif",
    "Zardari",
    "protest",
    "sit-in",
    "dharna",
    "assembly",
    "minister",
    "IMF",
    "budget speech",
    "vote of confidence",
    "NAB",
    "ECP",
    "COAS",
    "Asim Munir",
    "Toshakhana",
    "attack",
    "blast",
    "bomb",
    "suicide",
    "militant",
    "terrorist",
    "killed",
    "death toll",
    "gunmen",
    "police compound",
    "security forces",
]

TOPIC_SPECS: list[dict] = [
    {
        "id": "palestine",
        "label": "Palestine",
        "angles": [
            "last 24 hours",
            "humanitarian",
            "aid and reconstruction",
            "culture",
            "Palestinian voices",
        ],
        "prefer_sources": [
            "Al Jazeera",
            "Middle East Eye",
            "+972",
            "Drop Site",
            "Mondoweiss",
            "Electronic Intifada",
            "Middle East Monitor",
            "The New Humanitarian",
        ],
    },
    {
        "id": "art-crafts",
        "label": "Art and crafts",
        "angles": [
            "desi crafts",
            "South Asian artisans",
            "making and process",
            "things to do",
            "short fun items",
        ],
        "prefer_sources": [
            "Hyperallergic",
            "Colossal",
            "Design Milk",
            "STIR",
            "ArtNow",
            "It's Nice That",
        ],
    },
    {
        "id": "islamabad-folk",
        "label": "Islamabad folk",
        "angles": ["galleries", "city culture", "folk", "music and bazaars", "not political"],
        "prefer_sources": ["Youlin", "ArtNow", "Satrang", "Lok Virsa", "PNCA"],
        "require_any": ["Islamabad"],
        "drop_if": ISLAMABAD_DROP,
    },
    {
        "id": "space",
        "label": "Space",
        "angles": ["missions", "astronomy", "science", "sky events", "beautiful images"],
        "prefer_sources": ["NASA", "ESA", "Universe Today", "Sky & Telescope", "JPL", "APOD"],
    },
    {
        "id": "tech-ai",
        "label": "Tech and AI",
        "angles": ["research", "tools", "open source", "industry", "no hype cycle"],
        "prefer_sources": [
            "Ars Technica",
            "404 Media",
            "IEEE Spectrum",
            "Hugging Face",
            "Simon Willison",
        ],
    },
]


def load_user_md(path: Path = USER_MD_PATH) -> str:
    return path.read_text()


def load_feeds(path: Path = FEEDS_PATH) -> dict[InterestId, list[str]]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("feeds.json must be an object keyed by topic")
    missing = [topic for topic in TOPIC_IDS if topic not in raw]
    if missing:
        raise ValueError(f"feeds.json missing topics: {missing}")
    out: dict[InterestId, list[str]] = {}
    for topic in TOPIC_IDS:
        rows = raw[topic] or []
        urls: list[str] = []
        for item in rows:
            if isinstance(item, dict) and item.get("url"):
                urls.append(str(item["url"]))
            elif isinstance(item, str) and item.strip():
                urls.append(item.strip())
        out[topic] = urls
    return out


def load_topics(
    feeds_path: Path = FEEDS_PATH,
) -> list[Interest]:
    feeds = load_feeds(feeds_path)
    return [
        Interest.model_validate({**spec, "feeds": feeds[spec["id"]], "queries": []})
        for spec in TOPIC_SPECS
    ]


def load_paper(path: Path = PAPER_PATH) -> dict:
    return yaml.safe_load(path.read_text())


def age_on(birthday: date, today: date) -> int:
    before_birthday = (today.month, today.day) < (birthday.month, birthday.day)
    return today.year - birthday.year - before_birthday


def load_profile(path: Path | None = None, today: date | None = None) -> dict:
    """The reader's profile for the discovery agent, with age worked out from
    the birthday. A missing or empty file is an empty profile, not an error:
    discovery then guesses from user.md alone."""
    path = path or PROFILE_PATH
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        return {}
    profile = {k: v for k, v in raw.items() if v not in (None, "", [])}
    birthday = profile.pop("birthday", None)
    if isinstance(birthday, str):
        try:
            birthday = date.fromisoformat(birthday)
        except ValueError:
            birthday = None
    if isinstance(birthday, date):
        profile["age"] = age_on(birthday, today or karachi_now().date())
    return profile


def load_sample_edition(path: Path = SAMPLE_EDITION_PATH) -> Edition:
    return Edition.model_validate_json(path.read_text())


def karachi_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=TZ)
    return now.astimezone(TZ)


def karachi_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    moment = karachi_now(now)
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    end = moment.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end


def karachi_lookahead_bounds(
    now: datetime | None = None,
    extra_days: int = 1,
) -> tuple[datetime, datetime]:
    start, today_end = karachi_day_bounds(now)
    return start, today_end + timedelta(days=extra_days)


def iso_date(now: datetime | None = None) -> str:
    return karachi_now(now).date().isoformat()


def volume_for(now: datetime | None = None) -> str:
    return f"Vol. I, No. {karachi_now(now).timetuple().tm_yday}"
