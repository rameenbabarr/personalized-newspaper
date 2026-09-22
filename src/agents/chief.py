from __future__ import annotations

from collections import defaultdict

import httpx

from src.agents.llm import complete_json
from src.models import ArticleRole, NewsCandidate, NewsChiefIn, NewsChiefOut, WriterAssignment

MAX_PER_INTEREST = 2

SYSTEM = """You are NewsChief of The Rameen Times. Reply with one JSON object only.

Standing beats: palestine, art-crafts, space, tech-ai, islamabad-folk.

Rules you may not invent around:
1. Lead is the story Hash would stop and read, and it must have image_url. If several pass, pick the better photo. If no candidate has an image, pick the strongest story and set use_image false. Do not reserve the front page for Palestine or rotate by weekday.
2. Candidates are already fresh. Do not bring old stories back. Drop same-day duplicates.
3. Aim for all five standing beats when each has a fresh candidate. Omit a beat only if gather returned nothing usable. Never pad.
4. At most two assignments from any one interest_id. Extra Palestine (or any) candidates are omitted, not briefs. After the lead, walk the other beats for secondaries. Do not stack one interest.
5. Thin paper is honest. If the slate is small, keep it small. page_mode is thin when assignments < 6 or more than one standing section is omitted.
6. Hard rejects: political Islamabad; US-cable tone; Dawn or Tribune as the voice; anything you cannot explain in one sentence without inventing facts.
7. kicker is one factual weather-or-day line, not a joke.
8. Every secondary must have image_url. If a beat's only fresh story has no photo, skip it. Briefs may be text-only.
9. use_image is true for the lead when that candidate has image_url, and true for every secondary.

assignments: exactly one role=lead. Target: 1 lead plus about one secondary per other beat that has an imaged story. Remaining slots are briefs, still under the cap of two per interest.
lead_id must match the lead assignment's candidate_id.
"""


def _section(candidate: NewsCandidate) -> str:
    return candidate.interest_id.replace("-", " ").title()


def _assignment(
    candidate: NewsCandidate,
    role: ArticleRole,
    use_image: bool,
) -> WriterAssignment:
    notes = {
        "lead": "lead; keep the photo if it is real",
        "secondary": "secondary; finish the story on the page",
        "brief": "brief; two to three short paragraphs",
    }
    return WriterAssignment(
        candidate_id=candidate.id,
        role=role,
        section=_section(candidate),
        assignment=notes[role],
        use_image=use_image,
    )


def balanced_assignments(
    candidates: list[NewsCandidate],
    preferred_lead_id: str | None = None,
) -> list[WriterAssignment]:
    if not candidates:
        return []

    by_beat: dict[str, list[NewsCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_beat[candidate.interest_id].append(candidate)
    for rows in by_beat.values():
        rows.sort(key=lambda c: (0 if c.image_url else 1, c.published_at is None))

    imaged = [c for c in candidates if c.image_url]
    lead: NewsCandidate | None = None
    if preferred_lead_id:
        preferred = next((c for c in candidates if c.id == preferred_lead_id), None)
        if preferred and (preferred.image_url or not imaged):
            lead = preferred
        elif imaged:
            lead = imaged[0]
    if lead is None:
        lead = imaged[0] if imaged else candidates[0]

    used = {lead.id}
    counts = {lead.interest_id: 1}
    assignments = [_assignment(lead, "lead", bool(lead.image_url))]

    beats = list(dict.fromkeys(c.interest_id for c in candidates))
    ordered = [b for b in beats if b != lead.interest_id] + [lead.interest_id]

    for beat in ordered:
        if counts.get(beat, 0) >= MAX_PER_INTEREST:
            continue
        pick = next((c for c in by_beat[beat] if c.id not in used and c.image_url), None)
        if not pick:
            continue
        used.add(pick.id)
        counts[beat] = counts.get(beat, 0) + 1
        assignments.append(_assignment(pick, "secondary", True))

    for beat in ordered:
        if counts.get(beat, 0) >= MAX_PER_INTEREST:
            continue
        pick = next((c for c in by_beat[beat] if c.id not in used), None)
        if not pick:
            continue
        used.add(pick.id)
        counts[beat] = counts.get(beat, 0) + 1
        assignments.append(_assignment(pick, "brief", False))

    return assignments


def clamp_slate(slate: NewsChiefOut, candidates: list[NewsCandidate]) -> NewsChiefOut:
    assignments = balanced_assignments(candidates, preferred_lead_id=slate.lead_id)
    if not assignments:
        raise RuntimeError("no assignments after clamp")
    kept_ids = {a.candidate_id for a in assignments}
    return NewsChiefOut(
        lead_id=assignments[0].candidate_id,
        kicker=slate.kicker,
        page_mode="thin" if len(assignments) < 6 else "news-spread",
        assignments=assignments,
        omitted_candidate_ids=[c.id for c in candidates if c.id not in kept_ids],
        omitted_reason=slate.omitted_reason,
    )


def drop_imageless_secondaries(
    slate: NewsChiefOut,
    candidates: list[NewsCandidate],
) -> NewsChiefOut:
    lookup = {c.id: c for c in candidates}
    kept: list[WriterAssignment] = []
    for assignment in slate.assignments:
        candidate = lookup.get(assignment.candidate_id)
        if assignment.role == "secondary" and (candidate is None or not candidate.image_url):
            continue
        if assignment.role == "lead" and candidate:
            assignment.use_image = bool(candidate.image_url)
        elif assignment.role == "secondary":
            assignment.use_image = True
        kept.append(assignment)
    if not kept:
        return slate
    lead = next((a for a in kept if a.role == "lead"), kept[0])
    if lead.role != "lead":
        lead.role = "lead"
    return NewsChiefOut(
        lead_id=lead.candidate_id,
        kicker=slate.kicker,
        page_mode="thin" if len(kept) < 6 else slate.page_mode,
        assignments=kept,
        omitted_candidate_ids=slate.omitted_candidate_ids,
        omitted_reason=slate.omitted_reason,
    )


async def run_chief(client: httpx.AsyncClient, payload: NewsChiefIn) -> NewsChiefOut:
    user = payload.model_dump_json()
    raw = await complete_json(client, SYSTEM, user, NewsChiefOut, agent="NewsChief")
    return clamp_slate(raw, payload.candidates)


def fallback_slate(candidates: list[NewsCandidate], date: str) -> NewsChiefOut:
    assignments = balanced_assignments(candidates)
    if not assignments:
        raise RuntimeError("no candidates for a fallback slate")
    kept_ids = {a.candidate_id for a in assignments}
    return NewsChiefOut(
        lead_id=assignments[0].candidate_id,
        kicker=f"Morning edition, {date}.",
        page_mode="thin" if len(assignments) < 6 else "news-spread",
        assignments=assignments,
        omitted_candidate_ids=[c.id for c in candidates if c.id not in kept_ids],
        omitted_reason="fallback slate after NewsChief failed",
    )
