from datetime import UTC, date, datetime, timedelta

from core.digest import delivery_delay
from core.schedule_gate import GATE_EPOCH, delivery_time, digest_already_sent, digest_day, should_run


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def test_evening_run_prepares_tomorrow_and_late_runs_prepare_today():
    assert digest_day(utc(2026, 10, 9, 16, 41)) == date(2026, 10, 10)   # 18:41 czasu polskiego
    assert digest_day(utc(2026, 10, 9, 23, 41)) == date(2026, 10, 10)   # 1:41 w nocy (spóźniony)
    assert digest_day(utc(2026, 10, 10, 7, 30)) == date(2026, 10, 10)   # 9:30 rano (bardzo spóźniony)
    assert digest_day(utc(2026, 10, 10, 9, 59)) == date(2026, 10, 10)   # 11:59
    assert digest_day(utc(2026, 10, 10, 10, 0)) == date(2026, 10, 11)   # 12:00 = już na jutro


def test_delivery_is_at_seven_local_in_summer_and_winter():
    assert delivery_time(date(2026, 10, 10)) == utc(2026, 10, 10, 5, 0)   # CEST
    assert delivery_time(date(2026, 12, 10)) == utc(2026, 12, 10, 6, 0)   # CET
    assert delivery_time(date(2026, 10, 25)) == utc(2026, 10, 25, 6, 0)   # dzień zmiany czasu


def test_delay_scheduled_in_future_and_immediate_when_already_past():
    seven = delivery_time(date(2026, 10, 10))
    assert delivery_delay(seven, utc(2026, 10, 9, 16, 45)) == str(int(seven.timestamp()))
    assert delivery_delay(seven, utc(2026, 10, 10, 7, 30)) is None      # po 7:00: wyślij od razu
    assert delivery_delay(seven, seven - timedelta(seconds=5)) is None  # za blisko: od razu
    assert delivery_delay(seven, seven - timedelta(days=4)) is None     # ntfy: maks. 3 dni


def run(id_, created, conclusion="success"):
    return {"id": id_, "created_at": created, "conclusion": conclusion}


def test_backup_run_skips_when_digest_for_that_day_was_already_scheduled():
    runs = [run(2, "2026-10-09T18:41:30Z")]  # wieczorny: digest na 10.10
    assert digest_already_sent(runs, 3, date(2026, 10, 10), notify_succeeded=lambda i: i == 2)
    assert not digest_already_sent(runs, 3, date(2026, 10, 11), notify_succeeded=lambda i: True)


def test_late_night_backup_recognises_evening_run_for_the_same_day():
    runs = [run(2, "2026-10-09T18:41:00Z")]  # 20:41 czasu polskiego -> 10.10
    assert digest_already_sent(runs, 3, digest_day(utc(2026, 10, 10, 1, 41)), lambda i: True)


def test_runs_from_before_the_evening_switch_do_not_block_the_first_evening():
    """9.10 o 13:29 stary przebieg wysłał digest na 9.10; nowa reguła policzyłaby go jako 10.10."""
    old = run(2, "2026-10-09T11:29:04Z")
    assert datetime.fromisoformat(old["created_at"].replace("Z", "+00:00")) < GATE_EPOCH
    assert not digest_already_sent([old], 3, date(2026, 10, 10), notify_succeeded=lambda i: True)


def test_skipped_failed_and_current_runs_do_not_count():
    day = date(2026, 10, 10)
    assert not digest_already_sent([run(2, "2026-10-09T18:41:30Z")], 3, day, notify_succeeded=lambda i: False)
    assert not digest_already_sent([run(2, "2026-10-09T18:41:30Z", "failure")], 3, day, lambda i: True)
    assert not digest_already_sent([run(3, "2026-10-09T18:41:30Z")], 3, day, lambda i: True)


def test_manual_runs_always_execute_and_schedule_respects_gate():
    assert should_run("workflow_dispatch", lambda: True)
    assert should_run("schedule", lambda: False)
    assert not should_run("schedule", lambda: True)


def test_gate_fails_open_when_api_check_breaks():
    def broken():
        raise OSError("GitHub API 503")
    assert should_run("schedule", broken)
