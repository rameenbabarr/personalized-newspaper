from src.agents.briefing import apply_headline, apply_rank, fallback_rank, leftover_for_topic
from src.models import HeadlineOut, NewsCandidate, TopicRank


def _row(interest_id: str, n: int) -> NewsCandidate:
    return NewsCandidate(
        id=f"{interest_id}-{n}",
        interest_id=interest_id,  # type: ignore[arg-type]
        title=f"{interest_id} story {n}",
        snippet="A short snippet.",
        source_name="Example",
        source_url=f"https://example.com/{interest_id}/{n}",
    )


def test_headline_out_is_id_only() -> None:
    out = HeadlineOut(headline_id="palestine-1")
    assert out.model_dump() == {"headline_id": "palestine-1"}
    assert set(HeadlineOut.model_fields) == {"headline_id"}


def test_apply_headline_rejects_unknown_id() -> None:
    rows = [_row("palestine", 1), _row("space", 1)]
    assert apply_headline(rows, "space-1") == "space-1"
    assert apply_headline(rows, "missing") == "palestine-1"


def test_topic_rank_excludes_headline() -> None:
    palestine = [_row("palestine", n) for n in range(1, 5)]
    leftover = leftover_for_topic(palestine + [_row("space", 1)], "palestine", "palestine-1")
    assert [row.id for row in leftover] == ["palestine-2", "palestine-3", "palestine-4"]
    rank = apply_rank(
        leftover,
        TopicRank(best_id="palestine-3", candidates=["palestine-2", "palestine-1", "palestine-4"]),
    )
    assert rank.best_id == "palestine-3"
    assert "palestine-1" not in rank.candidates
    assert set(rank.candidates) == {"palestine-2", "palestine-4"}


def test_single_leftover_is_best_with_empty_candidates() -> None:
    leftover = leftover_for_topic([_row("space", 1), _row("space", 2)], "space", "space-1")
    rank = fallback_rank(leftover)
    assert rank is not None
    assert rank.best_id == "space-2"
    assert rank.candidates == []


def test_topic_omitted_when_only_story_is_headline() -> None:
    rows = [_row("islamabad-folk", 1)]
    leftover = leftover_for_topic(rows, "islamabad-folk", "islamabad-folk-1")
    assert leftover == []
    assert fallback_rank(leftover) is None
