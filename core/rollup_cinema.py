"""Seanse kinowe tego samego filmu w jednym miejscu zwijamy do jednej pozycji (CLAUDE.md).

start = pierwszy seans, end = ostatni seans, `times` = godziny seansów (HH:MM). Id jest stabilne
mimo upływu dni (seanse z przeszłości odpadają), więc nie zależy od daty pierwszego seansu.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import timedelta

from core.models import Event
from core.normalize import fold

MAX_GAP = timedelta(days=21)  # dłuższa przerwa = osobny „wyświetlanie” (np. powrót filmu)


def _cinema_id(e: Event, first: bool, group_start) -> str:
    key = f"kino|{fold(e.title)}|{fold(e.place or '')}" + ("" if first else f"|{group_start.date().isoformat()}")
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def rollup_cinema(events: list[Event]) -> list[Event]:
    cinema: dict[tuple[str, str], list[Event]] = defaultdict(list)
    rest: list[Event] = []
    for e in events:
        if e.category == "kino":
            cinema[(fold(e.title), fold(e.place or ""))].append(e)
        else:
            rest.append(e)
    for screenings in cinema.values():
        screenings.sort(key=lambda e: e.start)
        runs: list[list[Event]] = [[screenings[0]]]
        for s in screenings[1:]:
            if s.start - runs[-1][-1].start > MAX_GAP:
                runs.append([])
            runs[-1].append(s)
        for i, run in enumerate(runs):
            first = run[0].model_copy(deep=True)
            first.id = _cinema_id(first, i == 0, run[0].start)
            first.times = sorted({s.start.strftime("%H:%M") for s in run if not s.all_day})
            first.end = max((s.start for s in run), default=first.start)
            if first.end.date() == first.start.date():
                first.end = None  # jeden dzień: nie udajemy zakresu
            first.sources = sorted({src for s in run for src in s.sources})
            first.ticket_url = first.ticket_url or next((s.ticket_url for s in run if s.ticket_url), None)
            first.first_seen = min(s.first_seen for s in run)
            rest.append(first)
    return sorted(rest, key=lambda e: (e.start, e.title))
