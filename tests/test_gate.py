from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.agents.gate import fallback_picks, section_for
from src.models import Interest, NewsCandidate, TopicGateOut


def test_section_for_reads_one_heading() -> None:
    md = "# User\n\n## Palestine\nPrefer today.\n\n## Space\nMissions.\n"
    assert section_for(md, "Palestine") == "Prefer today."
    assert section_for(md, "Space") == "Missions."


def test_fallback_picks_preferred_sources_first() -> None:
    interest = Interest(
        id="space",
        label="Space",
        prefer_sources=["NASA"],
    )
    other = NewsCandidate(
        id="space-1",
        interest_id="space",
        title="A comet",
        snippet="Night sky.",
        source_name="Blog",
        source_url="https://example.com/comet",
        published_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
    )
    nasa = NewsCandidate(
        id="space-2",
        interest_id="space",
        title="A nebula",
        snippet="Pretty.",
        source_name="NASA",
        source_url="https://nasa.gov/nebula",
        published_at=None,
    )
    extra = [
        NewsCandidate(
            id=f"space-{n}",
            interest_id="space",
            title=f"Other {n}",
            snippet="More.",
            source_name="Blog",
            source_url=f"https://example.com/{n}",
        )
        for n in range(3, 7)
    ]
    picked = fallback_picks(interest, [other, nasa, *extra])
    assert len(picked) == 4
    assert picked[0].id == "space-2"


def test_topic_gate_out_caps_at_four() -> None:
    out = TopicGateOut(candidate_ids=["a", "b", "c", "d"])
    assert out.candidate_ids == ["a", "b", "c", "d"]
    with pytest.raises(ValidationError):
        TopicGateOut(candidate_ids=["a", "b", "c", "d", "e"])
