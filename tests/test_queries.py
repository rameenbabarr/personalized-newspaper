import pytest
from pydantic import ValidationError

from src.agents.queries import FALLBACK_QUERIES, apply_queries, ensure_queries, fallback_plan
from src.models import Interest, QueryPlan, TOPIC_IDS


def _full_queries(**overrides: list[str]) -> dict[str, list[str]]:
    queries = {topic: list(FALLBACK_QUERIES[topic]) for topic in TOPIC_IDS}
    queries.update(overrides)
    return queries


def test_query_plan_rejects_missing_topic() -> None:
    queries = _full_queries()
    queries.pop("space")
    with pytest.raises(ValidationError, match="missing topics"):
        QueryPlan(queries=queries)  # type: ignore[arg-type]


def test_query_plan_rejects_wrong_count() -> None:
    queries = _full_queries(palestine=["Gaza", "West Bank", "aid"])
    with pytest.raises(ValidationError, match="exactly 4"):
        QueryPlan(queries=queries)  # type: ignore[arg-type]


def test_fallback_plan_covers_every_topic() -> None:
    plan = fallback_plan()
    assert set(plan.queries) == set(TOPIC_IDS)
    assert all(len(rows) == 4 for rows in plan.queries.values())


def test_apply_and_ensure_queries() -> None:
    interests = [
        Interest(id="palestine", label="Palestine"),
        Interest(id="space", label="Space", queries=["keep me", "a", "b", "c"]),
    ]
    apply_queries(interests, fallback_plan())
    assert interests[0].queries == FALLBACK_QUERIES["palestine"]
    assert interests[1].queries == FALLBACK_QUERIES["space"]
    empty = Interest(id="tech-ai", label="Tech")
    ensure_queries([empty])
    assert empty.queries == FALLBACK_QUERIES["tech-ai"]
