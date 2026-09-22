from src.agents.copy import SYSTEM as COPY
from src.agents.writer import SYSTEM as WRITER
from src.agents.writer import _forced_article
from src.models import Article, NewsCandidate, WriterAssignment, WriterOut


def test_writer_prompt_is_broadsheet_and_on_page() -> None:
    lowered = WRITER.lower()
    assert "6 to 10" in WRITER
    assert "4 to 6" in WRITER
    assert "2 to 3" in WRITER
    assert "read more" in lowered
    assert "see the linked report" in lowered
    assert "finish the story on the page" in lowered
    assert "if the snippet is thin, write a shorter body and link out" not in lowered


def test_copy_prompt_flags_link_out_and_thin() -> None:
    assert "link-out" in COPY
    assert "too-thin" in COPY
    assert "unbalanced" in COPY
    assert "missing-image" in COPY


def test_forced_article_does_not_link_out() -> None:
    article = _forced_article(
        WriterAssignment(candidate_id="x", role="lead", section="Space", use_image=True),
        NewsCandidate(
            id="x",
            interest_id="space",
            title="A nebula",
            snippet="A bright cloud.",
            source_name="NASA",
            source_url="https://apod.nasa.gov/x",
            article_text="Dust and gas in a nearby cloud.",
        ),
    )
    body = " ".join(article.body).lower()
    assert "see the linked report" not in body
    assert "read more" not in body


def test_writer_out_unwraps_nested_article() -> None:
    article = {
        "id": "space-1",
        "headline": "A nebula",
        "section": "Space",
        "body": ["It shone."],
        "role": "brief",
        "source_url": "https://nasa.gov/x",
        "source_name": "NASA",
    }
    nested = WriterOut.model_validate({"article": {"article": article}})
    bare = WriterOut.model_validate(article)
    assert nested.article.headline == "A nebula"
    assert bare.article.headline == "A nebula"
    assert isinstance(nested.article, Article)
