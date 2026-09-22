from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pathlib import Path

from src.gather.news import parse_feed, select_candidates, should_drop
from src.models import Interest, NewsCandidate
from src.seen import load_seen, normalize_title, remember

KARACHI = ZoneInfo("Asia/Karachi")


def _interest(interest_id: str = "art-crafts", **kwargs) -> Interest:
    defaults = dict(
        id=interest_id,
        label=interest_id,
        angles=["test"],
        queries=[],
        feeds=[],
    )
    defaults.update(kwargs)
    return Interest.model_validate(defaults)


def _candidate(**kwargs) -> NewsCandidate:
    defaults = dict(
        id="art-crafts-aaa",
        interest_id="art-crafts",
        title="A block-print workshop in Lahore",
        snippet="A short class.",
        source_name="Hyperallergic",
        source_url="https://hyperallergic.com/workshop",
    )
    defaults.update(kwargs)
    return NewsCandidate.model_validate(defaults)


RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Clay cups in Karachi</title>
      <link>https://hyperallergic.com/clay-cups</link>
      <description>A weekend workshop.</description>
      <pubDate>Sat, 19 Sep 2026 01:00:00 +0500</pubDate>
      <enclosure url="https://img.example/clay.jpg" type="image/jpeg" />
    </item>
  </channel>
</rss>
"""


def test_parse_feed_reads_rss_item() -> None:
    interest = _interest()
    [candidate] = parse_feed(RSS, interest)
    assert candidate.title == "Clay cups in Karachi"
    assert candidate.source_url == "https://hyperallergic.com/clay-cups"
    assert candidate.image_url == "https://img.example/clay.jpg"
    assert candidate.snippet.startswith("A weekend workshop")
    assert candidate.interest_id == "art-crafts"


def test_select_candidates_skips_seen_url_and_title(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    remember([("https://hyperallergic.com/workshop", "A block-print workshop in Lahore")], path=path)

    interest = _interest()
    duplicate_title = _candidate(
        id="art-crafts-bbb",
        source_url="https://hyperallergic.com/other",
        title="A block-print workshop in Lahore!",
    )
    fresh = _candidate(
        id="art-crafts-ccc",
        title="New indigo dye class",
        source_url="https://hyperallergic.com/indigo",
    )
    picked = select_candidates(
        [_candidate(), duplicate_title, fresh],
        [interest],
        load_seen(path),
    )
    assert [c.source_url for c in picked] == ["https://hyperallergic.com/indigo"]


def test_drops_dawn_and_islamabad_politics() -> None:
    dawn = _candidate(
        interest_id="palestine",
        id="palestine-dawn",
        source_name="Dawn",
        source_url="https://www.dawn.com/news/1",
        title="Aid trucks",
    )
    politics = _candidate(
        interest_id="islamabad-folk",
        id="islamabad-folk-pol",
        title="Cabinet meets in Islamabad",
        source_url="https://example.com/cabinet",
        snippet="The cabinet met.",
    )
    palestine = _interest("palestine")
    folk = _interest("islamabad-folk", drop_if=["cabinet", "washington"])
    politics_us = _candidate(
        interest_id="islamabad-folk",
        id="islamabad-folk-us",
        title="Islamabad talks failed, but Washington won",
        source_url="https://example.com/talks",
        snippet="A diplomatic post-mortem.",
    )
    assert should_drop(palestine, dawn)
    assert should_drop(folk, politics)
    assert should_drop(folk, politics_us)


def test_palestine_keeps_stories_older_than_24_hours() -> None:
    now = datetime(2026, 9, 19, 19, 0, tzinfo=KARACHI)
    stale = _candidate(
        interest_id="palestine",
        id="palestine-old",
        title="Old crossing story",
        source_url="https://www.aljazeera.com/old",
        published_at=now - timedelta(hours=25),
    )
    fresh = _candidate(
        interest_id="palestine",
        id="palestine-new",
        title="New crossing story",
        source_url="https://www.aljazeera.com/new",
        published_at=now - timedelta(hours=2),
    )
    picked = select_candidates([stale, fresh], [_interest("palestine")], [])
    assert {c.id for c in picked} == {"palestine-old", "palestine-new"}
    assert normalize_title(fresh.title) == "new crossing story"


def test_parse_feed_keeps_latest_five() -> None:
    items = []
    for hour in range(6):
        items.append(
            f"""    <item>
      <title>Story {hour}</title>
      <link>https://hyperallergic.com/story-{hour}</link>
      <pubDate>Sat, 19 Sep 2026 {hour:02d}:00:00 +0000</pubDate>
    </item>"""
        )
    items.append(
        """    <item>
      <title>Undated</title>
      <link>https://hyperallergic.com/undated</link>
    </item>"""
    )
    xml = (
        '<?xml version="1.0"?><rss version="2.0"><channel>\n'
        + "\n".join(items)
        + "\n</channel></rss>"
    )
    picked = parse_feed(xml, _interest())
    assert len(picked) == 5
    assert [c.title for c in picked] == [f"Story {hour}" for hour in range(5, 0, -1)]
    assert all(c.title != "Undated" for c in picked)
    assert all(c.title != "Story 0" for c in picked)


def test_select_candidates_does_not_cap_per_interest() -> None:
    rows = [
        _candidate(
            id=f"art-crafts-{n}",
            title=f"Workshop {n}",
            source_url=f"https://hyperallergic.com/workshop-{n}",
        )
        for n in range(5)
    ]
    picked = select_candidates(rows, [_interest()], [])
    assert len(picked) == 5
