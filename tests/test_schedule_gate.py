from datetime import UTC, datetime

from core.schedule_gate import digest_already_sent, local_midnight_utc, should_run


def test_local_midnight_respects_summer_and_winter_time():
    assert local_midnight_utc(datetime(2026, 10, 8, 4, 41, tzinfo=UTC)) == datetime(2026, 10, 7, 22, 0, tzinfo=UTC)
    assert local_midnight_utc(datetime(2026, 12, 8, 4, 41, tzinfo=UTC)) == datetime(2026, 12, 7, 23, 0, tzinfo=UTC)
    # 23:30 UTC 8.10 to już 9.10 w Polsce
    assert local_midnight_utc(datetime(2026, 10, 8, 23, 30, tzinfo=UTC)) == datetime(2026, 10, 8, 22, 0, tzinfo=UTC)


SINCE = datetime(2026, 10, 7, 22, 0, tzinfo=UTC)


def run(id_, created, conclusion="success"):
    return {"id": id_, "created_at": created, "conclusion": conclusion}


def test_backup_run_skips_when_todays_digest_was_sent():
    runs = [run(2, "2026-10-08T04:41:30Z"), run(3, "2026-10-08T05:41:10Z")]
    assert digest_already_sent(runs, current_id=3, since=SINCE, notify_succeeded=lambda i: i == 2)


def test_runs_that_were_skipped_by_the_gate_do_not_count():
    """Przerwany przez strażnika przebieg ma status success, ale bez wysłanego digestu."""
    runs = [run(2, "2026-10-08T04:41:30Z")]
    assert not digest_already_sent(runs, 3, SINCE, notify_succeeded=lambda i: False)


def test_failed_yesterday_and_current_runs_do_not_count():
    runs = [run(1, "2026-10-07T21:59:00Z"), run(2, "2026-10-08T04:41:30Z", "failure"), run(3, "2026-10-08T05:41:00Z")]
    assert not digest_already_sent(runs, current_id=3, since=SINCE, notify_succeeded=lambda i: True)


def test_manual_runs_always_execute_and_schedule_respects_gate():
    assert should_run("workflow_dispatch", lambda: True)
    assert should_run("schedule", lambda: False)
    assert not should_run("schedule", lambda: True)


def test_gate_fails_open_when_api_check_breaks():
    def broken():
        raise OSError("GitHub API 503")
    assert should_run("schedule", broken)
