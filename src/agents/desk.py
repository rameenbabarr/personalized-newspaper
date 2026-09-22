from __future__ import annotations

import httpx

from src.agents.llm import complete_json
from src.log import error
from src.models import Desk, DeskColumn, DeskEditorIn, DeskEditorOut, RankedTask, TaskItem

SYSTEM = """You are DeskEditor of The Rameen Times. Reply with one JSON object only.

Keep every open card in desk.pending and desk.in_progress.
ranked covers all of them. rank 1 is first. ranked_ids is those ids in order.
Top two or three get real next_moves (at most two each) and when of now, after-lunch, or can-wait.
desk_column is 3 to 5 sentences: what matters this morning, what can wait, the next move on urgent cards.
Write as an editor, not a productivity influencer. Do not joke-rewrite card titles.
Use the calendar and busy_hours so the advice fits the day.
"""


async def run_desk(client: httpx.AsyncClient, payload: DeskEditorIn) -> DeskEditorOut:
    try:
        out = await complete_json(client, SYSTEM, payload.model_dump_json(), DeskEditorOut, agent="DeskEditor")
        return _normalize(out, payload.tasks, payload.desk_note)
    except Exception as exc:
        error(f"desk editor failed: {exc}")
        return fallback_desk(payload.tasks, payload.desk_note)


def fallback_desk(tasks: list[TaskItem], note: str | None) -> DeskEditorOut:
    doing = [t for t in tasks if t.status == "in-progress"]
    pending = [t for t in tasks if t.status == "pending"]
    ordered = doing + pending
    ranked = [
        RankedTask(
            task_id=task.id,
            rank=i + 1,
            why="Already moving." if task.status == "in-progress" else "On the board.",
            next_moves=["Open the card and do the first visible step."] if i < 3 else [],
            when="now" if task.status == "in-progress" else "after-lunch" if i < 3 else "can-wait",
        )
        for i, task in enumerate(ordered)
    ]
    if ordered:
        headline = "Move the work already in progress"
        body = [
            f"The board has {len(doing)} in progress and {len(pending)} waiting.",
            f"Start with {ordered[0].title}. The rest can wait until that card moves.",
        ]
    else:
        headline = "The desk is clear"
        body = [note or "No open cards. Leave the board alone and read the paper."]
    return DeskEditorOut(
        desk=Desk(
            pending=pending,
            in_progress=doing,
            ranked_ids=[t.id for t in ordered],
        ),
        ranked=ranked,
        desk_column=DeskColumn(headline=headline, body=body),
        desk_note=note,
    )


def _normalize(out: DeskEditorOut, tasks: list[TaskItem], note: str | None) -> DeskEditorOut:
    by_id = {t.id: t for t in tasks}
    pending = [t for t in tasks if t.status == "pending"]
    doing = [t for t in tasks if t.status == "in-progress"]
    ranked_ids = [item.task_id for item in sorted(out.ranked, key=lambda r: r.rank) if item.task_id in by_id]
    for task in doing + pending:
        if task.id not in ranked_ids:
            ranked_ids.append(task.id)
    out.desk = Desk(pending=pending, in_progress=doing, ranked_ids=ranked_ids)
    if note and not out.desk_note:
        out.desk_note = note
    return out
