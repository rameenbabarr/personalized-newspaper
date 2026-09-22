from src.models import BriefPiece, LongPiece, StoriesOut, TaskItem, TopicCopy
from src.render.edition import stories_to_edition, trim_body


def _headline() -> LongPiece:
    return LongPiece(
        id="palestine-1",
        title="West Bank debts forgiven",
        author="Qassam Muaddi",
        body="First paragraph.\n\nSecond paragraph.",
        source_name="Mondoweiss",
        source_url="https://mondoweiss.net/x",
        image_url="https://img.example/h.jpg",
    )


def test_stories_to_edition_maps_roles_and_skips_duplicate_headline() -> None:
    headline = _headline()
    stories = StoriesOut(
        date="2026-09-20",
        headline=headline,
        topics={
            # The same story is both the front page and its beat's lead. It must
            # be printed once, as the lead.
            "palestine": TopicCopy(lead=_headline()),
            "space": TopicCopy(
                lead=LongPiece(
                    id="space-1",
                    title="A pulsar",
                    author="NASA",
                    body="The wind feeds the compact object.",
                    source_name="NASA",
                    source_url="https://nasa.gov/x",
                    image_url="https://img.example/s.jpg",
                ),
                briefs=[
                    BriefPiece(
                        id="space-2",
                        title="A brief sky",
                        body="Two sentences on the stones.",
                    )
                ],
            ),
        },
        tasks=[
            TaskItem(id="t1", title="Lock the render", status="in-progress"),
            TaskItem(id="t2", title="Read the paper", status="pending"),
        ],
        reader_note="Good morning, Rameen!\n\nA clear Saturday.",
        diary_note="No meetings on the calendar today.",
    )

    edition = stories_to_edition(stories)

    assert edition.date == "2026-09-20"

    article = edition.articles[0]
    assert article.role == "lead"
    assert article.id == "palestine-1"
    assert article.byline == "By Qassam Muaddi"

    ids = [item.id for item in edition.articles]
    assert ids.count("palestine-1") == 1

    space_lead = next(item for item in edition.articles if item.id == "space-1")
    assert space_lead.role == "secondary"

    brief = next(item for item in edition.articles if item.id == "space-2")
    assert brief.role == "brief"

    # in-progress cards outrank pending ones
    assert edition.desk.ranked_ids == ["t1", "t2"]
    assert edition.desk_column is not None
    assert edition.tagline.startswith("Good morning")
    assert edition.page_mode == "thin"


def test_trim_body_clips_a_single_overlong_paragraph() -> None:
    # Keeping one whole paragraph is the floor, but every brief the writers
    # return is a single paragraph, so that floor silently disabled the limit
    # and the briefs ran a page longer than they should have.
    para = "One sentence here. " * 40
    out = trim_body([para], 200)
    assert len(out) == 1
    assert len(out[0]) <= 200
    assert out[0].endswith(".")


def test_trim_body_keeps_whole_paragraphs_under_the_limit() -> None:
    paras = ["a" * 80, "b" * 80, "c" * 80]
    assert trim_body(paras, 200) == paras[:2]
    # Never returns nothing, even when the first paragraph busts the budget.
    assert trim_body(["x" * 500], 100) != []
