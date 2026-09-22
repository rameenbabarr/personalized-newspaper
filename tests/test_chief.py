from src.agents.chief import balanced_assignments, clamp_slate, fallback_slate
from src.models import InterestId, NewsCandidate, NewsChiefOut, WriterAssignment


def _candidate(interest_id: InterestId, n: int, image: bool = True) -> NewsCandidate:
    return NewsCandidate(
        id=f"{interest_id}-{n}",
        interest_id=interest_id,
        title=f"{interest_id} story {n}",
        snippet="A short snippet.",
        source_name="Example",
        source_url=f"https://example.com/{interest_id}/{n}",
        image_url=f"https://img.example/{interest_id}-{n}.jpg" if image else None,
    )


def test_fallback_caps_palestine_and_keeps_other_beats() -> None:
    candidates = [_candidate("palestine", i) for i in range(6)]
    candidates.extend(
        [
            _candidate("space", 1),
            _candidate("art-crafts", 1),
            _candidate("tech-ai", 1),
            _candidate("islamabad-folk", 1),
        ]
    )
    slate = fallback_slate(candidates, "2026-09-19")
    lookup = {c.id: c for c in candidates}
    palestine = [a for a in slate.assignments if lookup[a.candidate_id].interest_id == "palestine"]
    beats = {lookup[a.candidate_id].interest_id for a in slate.assignments}
    assert len(palestine) <= 2
    assert len(beats) >= 2
    assert "space" in beats or "art-crafts" in beats or "tech-ai" in beats


def test_clamp_swaps_lead_without_photo() -> None:
    candidates = [_candidate("palestine", 1, image=False), _candidate("space", 1, image=True)]
    raw = NewsChiefOut(
        lead_id="palestine-1",
        kicker="A clear morning.",
        page_mode="thin",
        assignments=[
            WriterAssignment(candidate_id="palestine-1", role="lead", section="Palestine"),
            WriterAssignment(
                candidate_id="space-1",
                role="secondary",
                section="Space",
                use_image=True,
            ),
        ],
    )
    out = clamp_slate(raw, candidates)
    assert out.lead_id == "space-1"
    lead = next(a for a in out.assignments if a.role == "lead")
    assert lead.use_image is True


def test_secondaries_require_photos() -> None:
    candidates = [
        _candidate("space", 1, image=True),
        _candidate("palestine", 1, image=False),
        _candidate("art-crafts", 1, image=True),
    ]
    assignments = balanced_assignments(candidates, preferred_lead_id="space-1")
    lookup = {c.id: c for c in candidates}
    secondaries = [a for a in assignments if a.role == "secondary"]
    assert secondaries
    assert all(lookup[a.candidate_id].image_url for a in secondaries)
    assert all(a.use_image for a in secondaries)
    assert "palestine-1" not in {a.candidate_id for a in secondaries}
