"""Deduplikacja między źródłami: ta sama data + podobny tytuł (rapidfuzz) + zgodna miejscowość.

Priorytet źródeł: ręczne > organizator > bilety > agregator. Zwycięzca zachowuje swoje pola, braki
(godzina, cena, link do biletów, koniec) uzupełniamy z pozostałych. Dwa wydarzenia z tego samego źródła
nigdy się nie łączą (np. dwa seanse tego samego filmu tego samego dnia).
"""

from __future__ import annotations

from rapidfuzz import fuzz

from core.models import Event
from core.normalize import fold

SOURCE_PRIORITY = {
    "manual": 0,
    "mdk": 1, "radomsko_pl": 1, "muzeum": 1, "mbp": 1, "kamiensk": 1, "przedborz": 1,
    "ebilet": 2, "biletyna": 2,
    "radomskoogloszenia": 3,
}
MAX_TIME_GAP_MIN = 180  # dwa wydarzenia z godzinami dalej niż 3 h to różne wydarzenia


def priority(source: str) -> int:
    return SOURCE_PRIORITY.get(source, 9)


def _minutes(e: Event) -> int:
    return e.start.hour * 60 + e.start.minute


def same_event(a: Event, b: Event, threshold: int = 90) -> bool:
    if set(a.sources) & set(b.sources):
        return False
    if a.start.date() != b.start.date():
        return False
    if a.place and b.place and fold(a.place) != fold(b.place):
        return False
    if not a.all_day and not b.all_day and abs(_minutes(a) - _minutes(b)) > MAX_TIME_GAP_MIN:
        return False
    return fuzz.token_set_ratio(fold(a.title), fold(b.title)) >= threshold


def merge(group: list[Event]) -> Event:
    group = sorted(group, key=lambda e: (priority(e.source), e.all_day, e.confidence == "low"))
    win = group[0].model_copy(deep=True)
    for other in group[1:]:
        if win.all_day and not other.all_day:  # godzina z innego źródła (MDK często ma 00:00)
            win.start, win.all_day = other.start, False
            win.end = win.end or other.end
        for field in ("end", "venue", "url", "ticket_url", "price_text"):
            if getattr(win, field) is None and getattr(other, field) is not None:
                setattr(win, field, getattr(other, field))
        if win.category == "inne" and other.category != "inne":
            win.category = other.category
        if win.confidence == "low" and other.confidence == "high" and not other.all_day:
            win.confidence = "high"
    win.sources = sorted({s for e in group for s in e.sources}, key=lambda s: (priority(s), s))
    return win


def dedupe(events: list[Event], threshold: int = 90) -> list[Event]:
    """Grupowanie zachłanne po dacie; O(n^2) w obrębie dnia, dla setek wydarzeń w zupełności wystarcza."""
    ordered = sorted(events, key=lambda e: (priority(e.source), e.start, e.title))
    groups: list[list[Event]] = []
    for ev in ordered:
        for g in groups:
            used = {src for member in g for src in member.sources}
            if not (set(ev.sources) & used) and same_event(ev, g[0], threshold):
                g.append(ev)
                break
        else:
            groups.append([ev])
    return [merge(g) if len(g) > 1 else g[0] for g in groups]
