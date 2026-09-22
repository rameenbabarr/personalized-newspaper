from __future__ import annotations

import os
from datetime import datetime

import httpx
from icalendar import Calendar
from recurring_ical_events import of as recurring_of

from src.config import TZ, karachi_lookahead_bounds
from src.models import Meeting

UA = "RameenTimes/1.0 (personal morning paper)"


def parse_ics(raw: bytes, start: datetime, end: datetime) -> list[Meeting]:
    calendar = Calendar.from_ical(raw)
    meetings: list[Meeting] = []
    for event in recurring_of(calendar).between(start, end):
        status = str(event.get("STATUS", "")).upper()
        if status == "CANCELLED":
            continue
        ev_start = event.decoded("DTSTART")
        ev_end = event.decoded("DTEND") if event.get("DTEND") else ev_start
        if not isinstance(ev_start, datetime):
            all_day = True
            ev_start = datetime(ev_start.year, ev_start.month, ev_start.day, tzinfo=TZ)
            if not isinstance(ev_end, datetime):
                ev_end = datetime(ev_end.year, ev_end.month, ev_end.day, 23, 59, tzinfo=TZ)
        else:
            all_day = False
            if ev_start.tzinfo is None:
                ev_start = ev_start.replace(tzinfo=TZ)
            if isinstance(ev_end, datetime) and ev_end.tzinfo is None:
                ev_end = ev_end.replace(tzinfo=TZ)
        uid = str(event.get("UID", event.get("SUMMARY", "event")))
        meetings.append(
            Meeting(
                id=f"{uid}-{ev_start.isoformat()}",
                title=str(event.get("SUMMARY", "(no title)")),
                start=ev_start,
                end=ev_end if isinstance(ev_end, datetime) else ev_start,
                location=str(event.get("LOCATION")) if event.get("LOCATION") else None,
                all_day=all_day,
            )
        )
    meetings.sort(key=lambda m: m.start)
    return meetings


def busy_hours(meetings: list[Meeting]) -> float:
    total = 0.0
    for meeting in meetings:
        if meeting.all_day:
            continue
        total += max(0.0, (meeting.end - meeting.start).total_seconds() / 3600)
    return round(total, 2)


async def gather_calendar() -> tuple[list[Meeting], str | None, float]:
    url = os.environ.get("GOOGLE_ICAL")
    if not url:
        return [], "Calendar not connected.", 0.0
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True) as client:
            response = await client.get(url, timeout=20.0)
            response.raise_for_status()
        start, end = karachi_lookahead_bounds()
        meetings = parse_ics(response.content, start, end)
        note = "No meetings today or tomorrow." if not meetings else None
        return meetings, note, busy_hours(meetings)
    except Exception as exc:
        return [], str(exc), 0.0
