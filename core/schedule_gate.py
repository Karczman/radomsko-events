"""Strażnik zaplanowanych przebiegów `daily`.

GitHub opóźnia zdarzenia `schedule` przy dużym obciążeniu (najbardziej o pełnych godzinach), a czasem je
pomija. Dlatego `daily.yml` ma kilka godzin startu: pierwszy przebieg danego dnia (czas polski), który
doszedł do wysłania digestu, wykonuje pracę, a kolejne kończą się od razu. Dzięki temu dane pobieramy raz
dziennie i nie wysyłamy podwójnych powiadomień. Uruchomienie ręczne (`workflow_dispatch`) działa zawsze.

Tylko biblioteka standardowa: job `gate` nie instaluje zależności.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections.abc import Callable, Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Warsaw")
API = "https://api.github.com"


def local_midnight_utc(now: datetime) -> datetime:
    """Początek dzisiejszego dnia w Polsce, wyrażony w UTC (uwzględnia CET/CEST)."""
    local = now.astimezone(TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("UTC"))


def digest_already_sent(runs: Iterable[dict], current_id: int, since: datetime,
                        notify_succeeded: Callable[[int], bool]) -> bool:
    """Czy inny dzisiejszy przebieg zakończył się sukcesem joba `notify`.
    Przebiegi przerwane przez strażnika też mają status `success`, ale ich `notify` jest pominięty."""
    for run in runs:
        if run["id"] == current_id or run.get("conclusion") != "success":
            continue
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        if created >= since and notify_succeeded(run["id"]):
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
    since = local_midnight_utc(datetime.now(TZ))

    def already_sent() -> bool:
        stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        runs = _get(f"{API}/repos/{repo}/actions/workflows/daily.yml/runs?created=%3E%3D{stamp}&per_page=50",
                    token)["workflow_runs"]

        def notify_ok(run_id: int) -> bool:
            jobs = _get(f"{API}/repos/{repo}/actions/runs/{run_id}/jobs", token)["jobs"]
            return any(j["name"] == "notify" and j.get("conclusion") == "success" for j in jobs)
        return digest_already_sent(runs, current, since, notify_ok)

    run = should_run(event, already_sent)
    print("Przebieg wykonuje pracę." if run else "Dzisiejszy digest już wysłany: kończę bez pobierania danych.")
    with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write(f"run={'true' if run else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
