import html
from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

KARACHI = ZoneInfo("Asia/Karachi")

# The five standing beats. Feeds, the query agent and fallbacks are keyed on these.
InterestId = Literal["palestine", "art-crafts", "islamabad-folk", "space", "tech-ai"]
# Any topic the pipeline can carry: a core beat, or a discovery slug such as
# "urdu-calligraphy" that was trialled or adopted (src/taste/db.py topics table).
TopicId = str
TopicKind = Literal["core", "adopted", "trial"]


class Interest(BaseModel):
    id: TopicId
    label: str
    kind: TopicKind = "core"
    # What the gate judges against when user.md has no section for this topic.
    brief: str = ""
    angles: list[str] = []
    queries: list[str] = []
    feeds: list[str] = []
    prefer_sources: list[str] = []
    drop_if: list[str] = []
    require_any: list[str] = []


TOPIC_IDS: tuple[InterestId, ...] = ("palestine", "art-crafts", "islamabad-folk", "space", "tech-ai")


class QueryPlan(BaseModel):
    queries: dict[InterestId, list[str]]

    @field_validator("queries")
    @classmethod
    def _all_topics_four(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        missing = [topic for topic in TOPIC_IDS if topic not in value]
        if missing:
            raise ValueError(f"missing topics: {missing}")
        extra = sorted(set(value) - set(TOPIC_IDS))
        if extra:
            raise ValueError(f"unknown topics: {extra}")
        cleaned: dict[str, list[str]] = {}
        for topic, rows in value.items():
            queries = [str(item).strip() for item in rows if str(item).strip()]
            if len(queries) != 4:
                raise ValueError(f"{topic} needs exactly 4 queries")
            cleaned[topic] = queries
        return cleaned


class TopicGateOut(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=4)


class HeadlineOut(BaseModel):
    headline_id: str


class TopicRank(BaseModel):
    best_id: str
    candidates: list[str] = []


class GatherBriefing(BaseModel):
    headline_id: str
    topics: dict[TopicId, TopicRank] = {}


class NewsCandidate(BaseModel):
    id: str
    interest_id: TopicId
    title: str
    snippet: str
    source_name: str
    source_url: str
    image_url: Optional[str] = None
    published_at: Optional[datetime] = None
    article_text: Optional[str] = None

    @field_validator("published_at")
    @classmethod
    def _aware(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=KARACHI)
        return value


class SeenEntry(BaseModel):
    url: str
    title_key: str = Field(alias="titleKey")
    used_at: str = Field(alias="usedAt")

    model_config = {"populate_by_name": True}


ArticleRole = Literal["lead", "secondary", "brief"]
TaskStatus = Literal["pending", "in-progress"]


class Meeting(BaseModel):
    id: str
    title: str
    start: datetime
    end: datetime
    location: Optional[str] = None
    all_day: bool = False


class TaskItem(BaseModel):
    id: str
    title: str
    status: TaskStatus
    due: Optional[datetime] = None
    url: Optional[str] = None
    list_name: Optional[str] = None


def _clean_themes(value: object) -> list[str]:
    """Lowercase, trim, dedupe, cap at four. A theme is a reading-taste tag, so
    'Pakistani Ceramics' and 'pakistani ceramics ' must count as one."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        tag = " ".join(str(item).split()).casefold()
        if tag and tag not in out:
            out.append(tag)
    return out[:4]


class LongDraft(BaseModel):
    title: str
    author: str
    body: str
    themes: list[str] = []

    @field_validator("themes", mode="before")
    @classmethod
    def _themes(cls, value: object) -> list[str]:
        return _clean_themes(value)


class BriefDraft(BaseModel):
    title: str
    body: str
    themes: list[str] = []

    @field_validator("themes", mode="before")
    @classmethod
    def _themes(cls, value: object) -> list[str]:
        return _clean_themes(value)


class ReaderNote(BaseModel):
    note: str


class TexFile(BaseModel):
    tex: str


class LongPiece(BaseModel):
    id: str
    title: str
    author: str
    body: str
    source_name: str
    source_url: str
    image_url: Optional[str] = None
    themes: list[str] = []


class BriefPiece(BaseModel):
    id: str
    title: str
    body: str
    image_url: Optional[str] = None
    themes: list[str] = []


class TopicCopy(BaseModel):
    lead: Optional[LongPiece] = None
    briefs: list[BriefPiece] = []
    label: str = ""
    kind: TopicKind = "core"
    # Why discovery guessed this topic; printed in the "Something new" box.
    why: str = ""


class StoriesOut(BaseModel):
    date: str
    headline: Optional[LongPiece] = None
    topics: dict[TopicId, TopicCopy] = {}
    meetings: list[Meeting] = []
    tasks: list[TaskItem] = []
    diary_note: Optional[str] = None
    desk_note: Optional[str] = None
    weather: Optional[dict] = None
    reader_note: Optional[str] = None


def _as_paragraphs(value: object) -> list[str]:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split("\n\n") if part.strip()]
        return parts or [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


class Article(BaseModel):
    id: str
    headline: str
    dek: str = ""
    byline: str = "By the night editor"
    section: str
    body: list[str]
    role: ArticleRole
    image_url: Optional[str] = None
    source_url: str
    source_name: str
    # Reading-taste tags from the writer; src/taste tracks them over time.
    themes: list[str] = []
    # Topic slug (core beat or discovery topic); empty on editions before discovery.
    topic: str = ""
    trial: bool = False

    @field_validator("body", mode="before")
    @classmethod
    def _body(cls, value: object) -> list[str]:
        return _as_paragraphs(value)


class DeskColumn(BaseModel):
    headline: str
    body: list[str]

    @field_validator("body", mode="before")
    @classmethod
    def _body(cls, value: object) -> list[str]:
        return _as_paragraphs(value)


class Desk(BaseModel):
    pending: list[TaskItem]
    in_progress: list[TaskItem]
    ranked_ids: list[str] = []


class Edition(BaseModel):
    paper_name: str
    date: str
    volume: str
    tagline: Optional[str] = None
    generated_at: datetime
    timezone: Literal["Asia/Karachi"]
    diary: list[Meeting]
    desk: Desk
    desk_column: Optional[DeskColumn] = None
    articles: list[Article]
    page_mode: Literal["news-spread", "thin"] = "news-spread"
    diary_note: Optional[str] = None
    desk_note: Optional[str] = None
    # Carried through to the front-page rail. The raw Open-Meteo blob stays as
    # gathered; src/render/tex.py reduces it to the handful of printed numbers.
    weather: Optional[dict] = None
    reader_note: Optional[str] = None
    # "We guessed you might like ..." line for the day's trial topic, if any.
    trial_note: Optional[str] = None


class NewsChiefIn(BaseModel):
    date: str
    interests: list[Interest]
    candidates: list[NewsCandidate]
    meeting_count: int
    busy_hours: float
    desk_note: Optional[str] = None
    diary_note: Optional[str] = None
    briefing: Optional[GatherBriefing] = None


class WriterAssignment(BaseModel):
    candidate_id: str
    role: ArticleRole
    section: str
    assignment: str = "write the assigned story"
    use_image: bool = False


class NewsChiefOut(BaseModel):
    lead_id: str
    kicker: str
    page_mode: Literal["news-spread", "thin"]
    assignments: list[WriterAssignment] = Field(min_length=1, max_length=14)
    omitted_candidate_ids: list[str] = []
    omitted_reason: Optional[str] = None

    @field_validator("page_mode", mode="before")
    @classmethod
    def _page_mode(cls, value: object) -> object:
        if value in {"full", "spread", "normal", "wide"}:
            return "news-spread"
        return value


class WriterIn(BaseModel):
    assignment: WriterAssignment
    candidate: NewsCandidate


class WriterOut(BaseModel):
    article: Article

    @model_validator(mode="before")
    @classmethod
    def _unwrap(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        inner = value.get("article")
        if isinstance(inner, dict) and "headline" not in inner and isinstance(inner.get("article"), dict):
            return {"article": inner["article"]}
        if "article" not in value and "headline" in value:
            return {"article": value}
        return value


class DiaryClerkIn(BaseModel):
    date: str
    meetings: list[Meeting]
    diary_note: Optional[str] = None


class DiaryClerkOut(BaseModel):
    diary: list[Meeting]
    diary_note: Optional[str] = None
    intro: Optional[str] = None


class DeskEditorIn(BaseModel):
    date: str
    tasks: list[TaskItem]
    meetings: list[Meeting]
    busy_hours: float
    desk_note: Optional[str] = None


class RankedTask(BaseModel):
    task_id: str
    rank: int
    why: str = ""
    next_moves: list[str] = Field(default_factory=list, max_length=2)
    when: Literal["now", "after-lunch", "can-wait"] = "can-wait"

    @field_validator("next_moves", mode="before")
    @classmethod
    def _moves(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(str(item.get("move") or item.get("text") or item))
            else:
                out.append(item)
        return out


class DeskEditorOut(BaseModel):
    desk: Desk
    ranked: list[RankedTask]
    desk_column: DeskColumn
    desk_note: Optional[str] = None

    @field_validator("desk_column", mode="before")
    @classmethod
    def _column(cls, value: object) -> object:
        if isinstance(value, str):
            return {"headline": "The desk", "body": [value]}
        return value

    @field_validator("ranked", mode="before")
    @classmethod
    def _ranked(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        fixed = []
        for item in value:
            if isinstance(item, dict) and "task_id" not in item and "id" in item:
                item = {**item, "task_id": item["id"]}
            fixed.append(item)
        return fixed


class CopyChiefIn(BaseModel):
    date: str
    volume: str
    kicker: str
    articles: list[Article]
    diary: list[Meeting]
    diary_note: Optional[str] = None
    diary_intro: Optional[str] = None
    desk: Desk
    desk_column: Optional[DeskColumn] = None
    desk_note: Optional[str] = None


class CopyIssue(BaseModel):
    article_id: Optional[str] = None
    code: Literal[
        "invented-fact",
        "wrong-voice",
        "islamabad-politics",
        "missing-source",
        "no-lead-image",
        "missing-image",
        "too-long",
        "too-thin",
        "link-out",
        "unbalanced",
        "duplicate-lead",
    ]
    fix: str


class CopyChiefOut(BaseModel):
    edition: Edition
    issues: list[CopyIssue] = []
    dropped_article_ids: list[str] = []


class PipelineState(BaseModel):
    date: str
    interests: list[Interest]
    candidates: list[NewsCandidate] = []
    meetings: list[Meeting] = []
    tasks: list[TaskItem] = []
    diary_note: Optional[str] = None
    desk_note: Optional[str] = None
    busy_hours: float = 0
    briefing: Optional[GatherBriefing] = None
    stories: Optional[StoriesOut] = None
    slate: Optional[NewsChiefOut] = None
    articles: list[Article] = []
    diary: list[Meeting] = []
    desk: Optional[Desk] = None
    desk_column: Optional[DeskColumn] = None
    edition: Optional[Edition] = None


class ThemeNote(BaseModel):
    theme: str
    evidence: str


class InterestEdit(BaseModel):
    section: str
    change: str
    reason: str


class TasteReport(BaseModel):
    summary: str
    rising: list[ThemeNote] = Field(default_factory=list, max_length=6)
    fading: list[ThemeNote] = Field(default_factory=list, max_length=6)
    suggested_edits: list[InterestEdit] = Field(default_factory=list, max_length=5)


class DiscoveryPick(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=40)
    label: str = Field(min_length=2, max_length=40)
    why: str
    queries: list[str]

    @field_validator("label", "why", mode="before")
    @classmethod
    def _plain_text(cls, value: object) -> object:
        # The model sometimes answers "Food science &amp; fermentation"; the page
        # and the PDF escape on their own, so store plain text.
        return html.unescape(value) if isinstance(value, str) else value

    @field_validator("queries")
    @classmethod
    def _four(cls, value: list[str]) -> list[str]:
        queries = [q.strip() for q in value if q.strip()]
        if len(queries) != 4:
            raise ValueError("needs exactly 4 queries")
        return queries
