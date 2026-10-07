"""Poranny digest ntfy: dziś, najbliższe 7 dni i nowe. Plus alert, gdy źródło nie działa > 3 dni.

Temat ntfy jest sekretem (`NTFY_TOPIC`), opcjonalnie `NTFY_TOKEN`. Nigdy nie trafia do repo ani do logów.
Wysyłka przez JSON (UTF-8 bez problemów z nagłówkami): POST na `https://ntfy.sh/`.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import yaml

from core.models import Event
from core.normalize import TZ

log = logging.getLogger("digest")
ROOT = Path(__file__).resolve().parent.parent
WEEKDAYS = ["pn", "wt", "śr", "cz", "pt", "sb", "nd"]
MAX_WEEK, MAX_NEW, MAX_SHORT = 8, 5, 3
ALERT_AFTER_DAYS = 3


@dataclass
class Message:
    title: str
    body: str
    click: str | None = None
    priority: int = 3
    tags: tuple[str, ...] = ("calendar",)


def _active(events: list[Event]) -> list[Event]:
    return [e for e in events if e.status == "active"]


def _local(e: Event) -> tuple[date, date]:
    start = e.start.astimezone(TZ).date()
    return start, (e.end.astimezone(TZ).date() if e.end else start)


def _time(e: Event) -> str:
    return "" if e.all_day else e.start.astimezone(TZ).strftime("%H:%M")


def _place(e: Event) -> str:
    return f" ({e.venue or e.place})" if (e.venue or e.place) else ""


def _line_today(e: Event) -> str:
    return f"• {_time(e) + ' ' if _time(e) else ''}{e.title}{_place(e)}"


def _line_day(e: Event) -> str:
    d = _local(e)[0]
    return f"• {WEEKDAYS[d.weekday()]} {d.day}.{d.month:02d} {_time(e) + ' ' if _time(e) else ''}{e.title}"


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def build_digest(events: list[Event], today: date, new_ids: list[str], site_url: str | None,
                 when_empty: str = "short") -> Message | None:
    """`when_empty`: gdy nic dziś i nic nowego, `short` (krótka wersja) albo `skip` (nie wysyłaj)."""
    live = _active(events)
    todays = [e for e in live if _local(e)[0] <= today <= _local(e)[1]]
    horizon = today + timedelta(days=7)
    week = sorted((e for e in live if today < _local(e)[0] <= horizon), key=lambda e: e.start)
    new = [e for e in live if e.id in set(new_ids) and _local(e)[1] >= today][:MAX_NEW]
    title = f"Radomsko: dziś {len(todays)}, w tygodniu {len(week)}"
    if not todays and not new:
        if when_empty == "skip":
            return None
        lines = [_line_day(e) for e in week[:MAX_SHORT]] or ["Brak wydarzeń w najbliższych 7 dniach."]
        return Message(title, "\n".join(lines), site_url)
    sections: list[str] = []
    if todays:
        sections.append("Dziś:\n" + "\n".join(_line_today(e) for e in sorted(todays, key=lambda e: e.start)))
    if week:
        shown = [_line_day(e) for e in week[:MAX_WEEK]]
        if len(week) > MAX_WEEK:
            shown.append(f"… i {len(week) - MAX_WEEK} więcej")
        sections.append("Najbliższe 7 dni:\n" + "\n".join(shown))
    if new:
        sections.append("Nowe:\n" + "\n".join(_line_day(e) for e in new))
    return Message(title, "\n\n".join(sections), site_url)


def source_alerts(status: dict, today: date) -> Message | None:
    """Alert, gdy źródło nie działa dłużej niż 3 dni lub zadziałał bezpiecznik (`stale`)."""
    problems = []
    for name, s in status.get("sources", {}).items():
        if s.get("stale"):
            problems.append(f"• {name}: bezpiecznik, używamy starszych danych ({s.get('stale_reason', 'brak danych')})")
        elif not s.get("ok", True) and s.get("first_failure"):
            days = (today - date.fromisoformat(s["first_failure"])).days
            if days > ALERT_AFTER_DAYS:
                problems.append(f"• {name}: nie działa od {days} {_plural(days, 'dnia', 'dni', 'dni')}")
    if not problems:
        return None
    return Message("Radomsko: problem ze źródłem", "\n".join(problems), None, priority=4, tags=("warning",))


def send(msg: Message, topic: str, token: str | None = None, server: str = "https://ntfy.sh",
         client: httpx.Client | None = None) -> None:
    payload = {"topic": topic, "title": msg.title, "message": msg.body, "priority": msg.priority,
               "tags": list(msg.tags)}
    if msg.click:
        payload["click"] = msg.click
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    own = client or httpx.Client(timeout=15)
    resp = own.post(server, json=payload, headers=headers)
    resp.raise_for_status()


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    dry = "--dry-run" in argv
    config = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
    raw = json.loads((ROOT / config["paths"]["events"]).read_text("utf-8"))
    events = [Event.model_validate(e) for e in raw["events"]]
    status = json.loads((ROOT / "data/status.json").read_text("utf-8"))
    override = os.environ.get("DIGEST_TODAY")  # do testów ręcznych
    today = date.fromisoformat(override) if override else datetime.now(TZ).date()
    cfg = config.get("digest", {})
    messages = [
        build_digest(events, today, status.get("new", []), config.get("site_url"), cfg.get("when_empty", "short")),
        source_alerts(status, today),
    ]
    topic, token = os.environ.get("NTFY_TOPIC"), os.environ.get("NTFY_TOKEN")
    for msg in filter(None, messages):
        if dry or not topic:
            print(f"--- {msg.title}\n{msg.body}\n")
            if not dry:
                log.warning("Brak NTFY_TOPIC, nic nie wysłano")
            continue
        send(msg, topic, token, cfg.get("server", "https://ntfy.sh"))
        log.info("wysłano: %s", msg.title)  # tytuł jest publiczny, temat nigdy
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
