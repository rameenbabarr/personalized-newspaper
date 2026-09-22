from src.config import load_feeds, load_topics, load_user_md
from src.models import TOPIC_IDS


def test_load_feeds_groups_urls_by_topic() -> None:
    feeds = load_feeds()
    assert set(feeds) == set(TOPIC_IDS)
    assert feeds["islamabad-folk"] == []
    assert "https://www.aljazeera.com/xml/rss/all.xml" in feeds["palestine"]
    assert "https://www.nasa.gov/rss/dyn/lg_image_of_the_day.rss" in feeds["space"]
    assert "https://simonwillison.net/atom/everything/" in feeds["tech-ai"]


def test_load_topics_keeps_islamabad_house_rules() -> None:
    topics = {item.id: item for item in load_topics()}
    assert set(topics) == set(TOPIC_IDS)
    folk = topics["islamabad-folk"]
    assert folk.require_any == ["Islamabad"]
    assert "cabinet" in folk.drop_if
    assert topics["palestine"].drop_if == []
    assert topics["palestine"].feeds
    assert folk.feeds == []


def test_load_user_md_has_standing_sections() -> None:
    text = load_user_md()
    assert "## Palestine" in text
    assert "## Islamabad folk" in text
    assert "## Tech and AI" in text
