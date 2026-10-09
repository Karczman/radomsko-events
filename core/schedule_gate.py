"""Strażnik zaplanowanych przebiegów `daily` i plan dostarczenia digestu.

GitHub opóźnia zdarzenia `schedule` (9.10.2026: o 6 h 24 min do 7 h 02 min, dwa dni z rzędu). Dlatego dane
pobieramy wieczorem, a digest na NASTĘPNY dzień ntfy dostarcza o 7:00 (zaplanowana wysyłka). Przebieg po
południu przygotowuje digest na jutro, przebieg do południa (np. mocno spóźniony wieczorny) na dziś.

`daily.yml` ma kilka godzin startu: pierwszy przebieg, który wyśle digest na dany dzień, wykonuje pracę,
a kolejne kończą się od razu (jedno pobranie danych na dzień, bez podwójnych powiadomień). Uruchomienie
ręczne (`workflow_dispatch`) działa zawsze.

Tylko biblioteka standardowa: job `gate` nie instaluje zależności.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Warsaw")
API = "https://api.github.com"
DELIVER_AT = time(7, 0)          # o tej godzinie (czas polski) ntfy dostarcza digest
NEXT_DAY_FROM = time(12, 0)      # przebieg od południa przygotowuje digest na jutro
# Przebiegi sprzed przejścia na wieczorne pobieranie wysyłały digest na dzień przebiegu: nie liczymy ich.
GATE_EPOCH = datetime(2026, 10, 9, 15, 0, tzinfo=UTC)  # ostatni stary przebieg: 13:43 UTC


def digest_day(when: datetime) -> date:
    """Dzień, którego dotyczy digest przygotowany w chwili `when`."""
    local = when.astimezone(TZ)
    return local.date() + timedelta(days=1) if local.time() >= NEXT_DAY_FROM else local.date()


def delivery_time(day: date) -> datetime:
    return datetime.combine(day, DELIVER_AT, tzinfo=TZ)


def digest_already_sent(runs: Iterable[dict], current_id: int, day: date,
                        notify_succeeded: Callable[[int], bool]) -> bool:
    """Czy inny przebieg wysłał już (zaplanował) digest na `day`.
    Przebiegi przerwane przez strażnika też mają status `success`, ale ich `notify` jest pominięty."""
    for run in runs:
        if run["id"] == current_id or run.get("conclusion") != "success":
            continue
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        if created >= GATE_EPOCH and digest_day(created) == day and notify_succeeded(run["id"]):
            return True
    return False


def should_run(event: str, already_sent: Callable[[], bool]) -> bool:
    """Gdy sprawdzenie zawiedzie (API, sieć), przepuszczamy przebieg: lepiej dwa digesty niż żaden."""
    if event != "schedule":
        return True
    try:
        return not already_sent()
    except Exception as exc:  # noqa: BLE001 - celowo: awaria strażnika nie może zablokować przebiegu
        print(f"Strażnik nie mógł sprawdzić dzisiejszych przebiegów ({type(exc).__name__}: {exc}); uruchamiam.")
        return True


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "radomsko-events-gate",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - stały adres API GitHuba
        return json.load(resp)


def main() -> int:
    env = os.environ
    repo, token, event, current = env["REPO"], env["GH_TOKEN"], env["EVENT"], int(env["RUN_ID"])
    day = digest_day(datetime.now(TZ))
    since = delivery_time(day) - timedelta(days=2)

    def already_sent() -> bool:
        stamp = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        runs = _get(f"{API}/repos/{repo}/actions/workflows/daily.yml/runs?created=%3E%3D{stamp}&per_page=50",
                    token)["workflow_runs"]

        def notify_ok(run_id: int) -> bool:
            jobs = _get(f"{API}/repos/{repo}/actions/runs/{run_id}/jobs", token)["jobs"]
            return any(j["name"] == "notify" and j.get("conclusion") == "success" for j in jobs)
        return digest_already_sent(runs, current, day, notify_ok)

    run = should_run(event, already_sent)
    print(f"Digest na {day}: " + ("przebieg wykonuje pracę." if run else "już wysłany, kończę bez pobierania danych."))
    with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write(f"run={'true' if run else 'false'}\nday={day.isoformat()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
