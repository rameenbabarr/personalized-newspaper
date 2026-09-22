from datetime import datetime

from src.config import TZ, karachi_lookahead_bounds
from src.gather.calendar import busy_hours, parse_ics
from src.models import Meeting

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:old-standup
DTSTART:20250116T173000Z
DTEND:20250116T180000Z
RRULE:FREQ=WEEKLY;UNTIL=20250316T185959Z;BYDAY=FR,MO,TH,TU,WE
SUMMARY:Old standup
END:VEVENT
BEGIN:VEVENT
UID:today-once
DTSTART:20260919T060000Z
DTEND:20260919T063000Z
SUMMARY:Coffee
LOCATION:Home
END:VEVENT
BEGIN:VEVENT
UID:cancelled
DTSTART:20260919T090000Z
DTEND:20260919T100000Z
STATUS:CANCELLED
SUMMARY:Cancelled
END:VEVENT
END:VCALENDAR
"""


def test_parse_ics_honors_until_and_skips_cancelled() -> None:
    start = datetime(2026, 9, 19, 0, 0, tzinfo=TZ)
    end = datetime(2026, 9, 19, 23, 59, tzinfo=TZ)
    meetings = parse_ics(ICS, start, end)
    titles = [m.title for m in meetings]
    assert titles == ["Coffee"]
    assert meetings[0].location == "Home"
    assert "Old standup" not in titles


def test_lookahead_bounds_start_today_and_reach_tomorrow_night() -> None:
    now = datetime(2026, 9, 19, 7, 0, tzinfo=TZ)
    start, end = karachi_lookahead_bounds(now)
    assert start == datetime(2026, 9, 19, 0, 0, tzinfo=TZ)
    assert start.tzinfo == TZ
    # Today's 23:59:59.999999 plus one day, so tomorrow's meetings are in range.
    assert end.date() == datetime(2026, 9, 20).date()
    assert end.hour == 23


def test_lookahead_bounds_include_tomorrow_meeting() -> None:
    now = datetime(2026, 9, 19, 7, 0, tzinfo=TZ)
    start, end = karachi_lookahead_bounds(now)
    # "Coffee" is on the 19th; the window must still hold it alongside the 20th.
    meetings = parse_ics(ICS, start, end)
    assert [m.title for m in meetings] == ["Coffee"]


def test_busy_hours_ignores_all_day() -> None:
    start = datetime(2026, 9, 19, 6, 0, tzinfo=TZ)
    end = datetime(2026, 9, 19, 7, 30, tzinfo=TZ)
    hours = busy_hours(
        [
            Meeting(id="a", title="x", start=start, end=end, all_day=False),
            Meeting(id="b", title="y", start=start, end=end, all_day=True),
        ]
    )
    assert hours == 1.5
