from src.gather.tavily import apply_extract, candidate_from_search, topic_for
from src.models import Interest


def _interest(interest_id: str = "palestine") -> Interest:
    return Interest.model_validate(
        {
            "id": interest_id,
            "label": interest_id,
            "angles": ["test"],
            "queries": ["Gaza"],
        }
    )


def test_search_hit_maps_to_candidate() -> None:
    hit = {
        "title": "Aid trucks reach Gaza",
        "url": "https://www.aljazeera.com/news/1",
        "content": "Trucks crossed this morning.",
        "images": ["https://img.example/aid.jpg"],
        "published_date": "2026-09-19T06:00:00Z",
    }
    candidate = candidate_from_search(_interest(), hit)
    assert candidate is not None
    assert candidate.title == "Aid trucks reach Gaza"
    assert candidate.source_url == "https://www.aljazeera.com/news/1"
    assert candidate.source_name == "aljazeera.com"
    assert candidate.image_url == "https://img.example/aid.jpg"
    assert candidate.snippet.startswith("Trucks crossed")
    assert candidate.published_at is not None


def test_search_drops_dawn() -> None:
    hit = {
        "title": "Cabinet",
        "url": "https://www.dawn.com/news/1",
        "content": "Politics.",
    }
    assert candidate_from_search(_interest(), hit) is None


def test_extract_keeps_full_text_and_fills_image() -> None:
    body = "A" * 7000
    candidate = candidate_from_search(
        _interest("space"),
        {"title": "A nebula", "url": "https://apod.nasa.gov/x", "content": "Pretty."},
    )
    assert candidate is not None
    assert candidate.image_url is None
    apply_extract(
        candidate,
        {"raw_content": body, "images": [{"url": "https://img.example/nebula.jpg"}]},
    )
    assert candidate.article_text == body
    assert candidate.image_url == "https://img.example/nebula.jpg"


def test_topic_split() -> None:
    assert topic_for("palestine") == "news"
    assert topic_for("tech-ai") == "news"
    assert topic_for("art-crafts") == "general"
    assert topic_for("space") == "general"
