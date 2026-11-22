"""Unit tests for the pure scheduling logic (no Home Assistant needed)."""

from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys

import pytest

_PATH = Path(__file__).parent.parent / "custom_components" / "shipshape" / "models.py"
_SPEC = importlib.util.spec_from_file_location("shipshape_models", _PATH)
models = importlib.util.module_from_spec(_SPEC)
sys.modules["shipshape_models"] = models
_SPEC.loader.exec_module(models)

TZ = timezone(timedelta(hours=-6))
NOW = datetime(2026, 11, 22, 15, 0, tzinfo=TZ)


def chore(schedule, last_done=None, **extra):
    return {"schedule": models.normalize_schedule(schedule), "last_done": last_done, **extra}


def ago(days, hours=0):
    return (NOW - timedelta(days=days, hours=hours)).isoformat()


def test_add_months_clamps_day():
    assert models.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert models.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert models.add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"every": 6, "unit": "days"}, {"kind": "interval", "every": 6, "unit": "days"}),
        ({"every": "2", "unit": "Week"}, {"kind": "interval", "every": 2, "unit": "weeks"}),
        ({"months": [10, 4, 4]}, {"kind": "months", "months": [4, 10]}),
        ({"kind": "months", "months": [1]}, {"kind": "months", "months": [1]}),
    ],
)
def test_normalize_schedule(raw, expected):
    assert models.normalize_schedule(raw) == expected


@pytest.mark.parametrize(
    "raw", [{"every": 0, "unit": "days"}, {"every": 3, "unit": "years"}, {"months": [13]}, "weekly", {"every": "x"}]
)
def test_normalize_schedule_rejects(raw):
    with pytest.raises(models.ScheduleError):
        models.normalize_schedule(raw)


def test_schedule_label():
    assert models.schedule_label({"kind": "interval", "every": 1, "unit": "months"}) == "Every month"
    assert models.schedule_label({"kind": "interval", "every": 6, "unit": "days"}) == "Every 6 days"
    assert models.schedule_label({"kind": "months", "months": [4, 10]}) == "Apr, Oct"


def test_next_due_interval():
    assert models.next_due_date({"kind": "interval", "every": 6, "unit": "days"}, date(2026, 11, 20)) == date(2026, 11, 26)
    assert models.next_due_date({"kind": "interval", "every": 2, "unit": "weeks"}, date(2026, 11, 20)) == date(2026, 12, 4)
    assert models.next_due_date({"kind": "interval", "every": 3, "unit": "months"}, date(2026, 11, 30)) == date(2027, 2, 28)


def test_next_due_fixed_months():
    sched = {"kind": "months", "months": [4, 10]}
    assert models.next_due_date(sched, date(2026, 10, 3)) == date(2027, 4, 1)
    assert models.next_due_date(sched, date(2026, 11, 22)) == date(2027, 4, 1)
    assert models.next_due_date(sched, date(2027, 4, 1)) == date(2027, 10, 1)
    assert models.next_due_date(sched, date(2027, 3, 31)) == date(2027, 4, 1)


def test_status_fresh_chore_is_ok():
    status = models.chore_status(chore({"every": 6, "unit": "days"}, ago(1)), NOW)
    assert status["state"] == "ok"
    assert not status["is_due"]
    assert status["days_left"] == 5
    assert 0.1 < status["ratio"] < 0.25


def test_status_due_on_the_day():
    status = models.chore_status(chore({"every": 6, "unit": "days"}, ago(6)), NOW)
    assert status["is_due"]
    assert status["state"] == "due"
    assert status["days_left"] == 0


def test_status_soon_then_overdue():
    weekly = {"every": 1, "unit": "weeks"}
    assert models.chore_status(chore(weekly, ago(6)), NOW)["state"] == "soon"
    assert models.chore_status(chore(weekly, ago(8)), NOW)["state"] == "due"
    assert models.chore_status(chore(weekly, ago(9)), NOW)["state"] == "overdue"


def test_status_never_done_is_due_now():
    status = models.chore_status(chore({"every": 2, "unit": "months"}), NOW)
    assert status["is_due"] and status["ratio"] == 1.0


def test_status_done_late_at_night_is_due_by_date_not_hour():
    # Done at 23:30 yesterday with a 1-day interval: due today, even at 00:05.
    last = datetime(2026, 11, 21, 23, 30, tzinfo=TZ).isoformat()
    just_after_midnight = datetime(2026, 11, 22, 0, 5, tzinfo=TZ)
    assert models.chore_status(chore({"every": 1, "unit": "days"}, last), just_after_midnight)["is_due"]


def test_status_respects_timezone_of_now():
    # 03:00 UTC on the 22nd is still the 21st in UTC-6.
    last = datetime(2026, 11, 22, 3, 0, tzinfo=timezone.utc).isoformat()
    status = models.chore_status(chore({"every": 1, "unit": "days"}, last), NOW)
    assert status["due_date"] == "2026-11-22"


def test_snooze_hides_due_chore():
    c = chore({"every": 6, "unit": "days"}, ago(10), snooze_until="2026-11-24")
    status = models.chore_status(c, NOW)
    assert not status["is_due"]
    assert status["snoozed"]
    assert status["days_left"] == 2
    assert status["ratio"] > 1  # still dirty, just quiet


def test_expired_snooze_is_ignored():
    c = chore({"every": 6, "unit": "days"}, ago(10), snooze_until="2026-11-20")
    assert models.chore_status(c, NOW)["is_due"]


def test_paused_chore_is_never_due():
    status = models.chore_status(chore({"every": 1, "unit": "days"}, ago(30), paused=True), NOW)
    assert status["state"] == "paused" and not status["is_due"]


def test_force_due():
    status = models.chore_status(chore({"every": 30, "unit": "days"}, ago(1), force_due=True), NOW)
    assert status["is_due"] and status["ratio"] >= 1


def test_fixed_month_status():
    sched = {"months": [4, 10]}
    done_in_oct = datetime(2026, 10, 5, 9, 0, tzinfo=TZ).isoformat()
    status = models.chore_status(chore(sched, done_in_oct), NOW)
    assert status["due_date"] == "2027-04-01" and not status["is_due"]
    not_done_since_spring = datetime(2026, 4, 3, 9, 0, tzinfo=TZ).isoformat()
    status = models.chore_status(chore(sched, not_done_since_spring), NOW)
    assert status["due_date"] == "2026-10-01" and status["is_due"]


def test_completion_timestamp_early_fixed_month():
    sched = {"months": [4, 10]}
    c = chore(sched, datetime(2026, 4, 3, 9, 0, tzinfo=TZ).isoformat())
    early = datetime(2026, 9, 25, 10, 0, tzinfo=TZ)  # 6 days before Oct 1
    stamp = models.completion_timestamp(c, early)
    assert stamp.date() == date(2026, 10, 1)
    c["last_done"] = stamp.isoformat()
    assert models.chore_status(c, early)["due_date"] == "2027-04-01"
    # Far from the next period: recorded as-is.
    far = datetime(2026, 6, 1, 10, 0, tzinfo=TZ)
    assert models.completion_timestamp(chore(sched, c["last_done"]), far) == far


def test_completion_timestamp_interval_is_now():
    c = chore({"every": 6, "unit": "days"}, ago(2))
    assert models.completion_timestamp(c, NOW) == NOW


def test_projected_dues_rolls_overdue_to_today_and_repeats():
    c = chore({"every": 1, "unit": "weeks"}, ago(10))
    days = models.projected_dues(c, NOW, date(2026, 11, 1), date(2026, 12, 15))
    assert days[0] == date(2026, 11, 22)
    assert days[1] == date(2026, 11, 29)
    assert all(b - a == timedelta(days=7) for a, b in zip(days, days[1:]))


def test_projected_dues_window_and_pause():
    c = chore({"every": 2, "unit": "days"}, ago(1))
    days = models.projected_dues(c, NOW, date(2026, 11, 25), date(2026, 11, 30))
    assert days == [date(2026, 11, 25), date(2026, 11, 27), date(2026, 11, 29)]
    assert models.projected_dues({**c, "paused": True}, NOW, date(2026, 11, 1), date(2026, 12, 1)) == []


def test_staggered_last_done_spreads():
    sched = models.normalize_schedule({"every": 10, "unit": "days"})
    last = models.staggered_last_done(sched, NOW, 0.5)
    status = models.chore_status({"schedule": sched, "last_done": last.isoformat()}, NOW)
    assert status["days_left"] == 5 and not status["is_due"]
    # Never produces an already-due chore.
    capped = models.staggered_last_done(sched, NOW, 5)
    assert not models.chore_status({"schedule": sched, "last_done": capped.isoformat()}, NOW)["is_due"]
