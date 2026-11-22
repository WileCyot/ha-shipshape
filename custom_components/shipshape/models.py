"""Pure scheduling logic for Shipshape.

Nothing in this module imports Home Assistant, so it can be unit tested with
plain pytest.

A chore's *condition* is modelled the way Tody does it: it starts clean when the
chore is done and drifts towards "due" as the configured interval elapses.
``ratio`` is elapsed / interval, so 0.0 is spotless, 1.0 is due and anything
above is overdue.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any

UNITS = ("days", "weeks", "months")
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

KIND_INTERVAL = "interval"
KIND_MONTHS = "months"
# Never comes due on its own; something (a device trigger, a person, an
# automation) has to make it due each time.
KIND_MANUAL = "manual"
FAR_FUTURE = date(2999, 12, 31)

# A fixed-month chore finished this close to its next start counts for that
# upcoming period (doing the October swap on September 25th is not "late April").
EARLY_GRACE_DAYS = 21


class ScheduleError(ValueError):
    """Raised for a schedule that cannot be understood."""


def add_months(d: date, n: int) -> date:
    """Add calendar months, clamping the day (Jan 31 + 1 month = Feb 28/29)."""
    index = d.month - 1 + n
    year = d.year + index // 12
    month = index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def parse_dt(value: Any) -> datetime | None:
    """Parse an ISO datetime string; None/invalid gives None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    """Parse an ISO date (or datetime) string."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def normalize_schedule(raw: Any) -> dict[str, Any]:
    """Coerce any accepted schedule shape into the stored one.

    Accepted:
      {"every": 6, "unit": "days"}            interval
      {"months": [4, 10]}                     fixed months
      {"kind": "interval"|"months", ...}      already normalized
    """
    if not isinstance(raw, dict):
        raise ScheduleError("schedule must be an object")
    if raw.get("kind") == KIND_MANUAL or (raw.get("kind") is None and raw.get("on_demand")):
        return {"kind": KIND_MANUAL}
    months = raw.get("months")
    kind = raw.get("kind")
    if kind == KIND_MONTHS or (kind is None and months):
        try:
            cleaned = sorted({int(m) for m in (months or [])})
        except (TypeError, ValueError) as err:
            raise ScheduleError("months must be numbers 1-12") from err
        if not cleaned or any(m < 1 or m > 12 for m in cleaned):
            raise ScheduleError("months must be numbers 1-12")
        return {"kind": KIND_MONTHS, "months": cleaned}
    try:
        every = int(raw.get("every", 0))
    except (TypeError, ValueError) as err:
        raise ScheduleError("every must be a whole number") from err
    unit = str(raw.get("unit", "days")).lower().rstrip()
    if unit in ("day", "week", "month"):
        unit += "s"
    if unit not in UNITS:
        raise ScheduleError(f"unit must be one of {', '.join(UNITS)}")
    if every < 1 or every > 3650:
        raise ScheduleError("every must be between 1 and 3650")
    return {"kind": KIND_INTERVAL, "every": every, "unit": unit}


def schedule_label(schedule: dict[str, Any]) -> str:
    """Human label, e.g. 'Every 6 days' or 'Apr, Oct'."""
    if schedule.get("kind") == KIND_MANUAL:
        return "When triggered"
    if schedule.get("kind") == KIND_MONTHS:
        return ", ".join(MONTH_ABBR[m - 1] for m in schedule.get("months", []))
    every = schedule.get("every", 1)
    unit = schedule.get("unit", "days")
    if every == 1:
        return f"Every {unit[:-1]}"
    return f"Every {every} {unit}"


def next_due_date(schedule: dict[str, Any], last_done: date) -> date:
    """The date a chore next comes due, given the date it was last done."""
    if schedule.get("kind") == KIND_MANUAL:
        return FAR_FUTURE
    if schedule.get("kind") == KIND_MONTHS:
        months = schedule.get("months") or [1]
        for step in range(1, 25):
            candidate = add_months(date(last_done.year, last_done.month, 1), step)
            if candidate.month in months:
                return candidate
        return add_months(last_done, 12)
    every = int(schedule.get("every", 1))
    unit = schedule.get("unit", "days")
    if unit == "weeks":
        return last_done + timedelta(days=7 * every)
    if unit == "months":
        return add_months(last_done, every)
    return last_done + timedelta(days=every)


def approx_interval_days(schedule: dict[str, Any]) -> float:
    """Rough length of one cycle in days (used for staggering and sorting)."""
    if schedule.get("kind") == KIND_MANUAL:
        return 0.0
    if schedule.get("kind") == KIND_MONTHS:
        return 365.0 / max(1, len(schedule.get("months") or [1]))
    every = int(schedule.get("every", 1))
    return float(every * {"days": 1, "weeks": 7, "months": 30.44}[schedule.get("unit", "days")])


def chore_status(chore: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Compute the live condition of one chore at ``now`` (an aware datetime)."""
    schedule = chore["schedule"]
    today = now.date()
    if schedule.get("kind") == KIND_MANUAL:
        return _manual_status(chore, today)
    last = parse_dt(chore.get("last_done"))
    if last is not None and last.tzinfo is not None and now.tzinfo is not None:
        last = last.astimezone(now.tzinfo)

    if last is None:
        due = today
        span = max(1, round(approx_interval_days(schedule)))
        ratio = 1.0
    else:
        due = next_due_date(schedule, last.date())
        span = max(1, (due - last.date()).days)
        if (last.tzinfo is None) != (now.tzinfo is None):
            delta = now.replace(tzinfo=None) - last.replace(tzinfo=None)
        else:
            delta = now - last
        ratio = max(0.0, delta.total_seconds() / 86400 / span)

    if chore.get("force_due"):
        due = min(due, today)
        ratio = max(ratio, 1.0)

    snooze = parse_date(chore.get("snooze_until"))
    effective_due = max(due, snooze) if snooze else due
    days_left = (effective_due - today).days
    paused = bool(chore.get("paused"))
    is_due = days_left <= 0 and not paused

    overdue_after = max(1, round(span * 0.25))
    soon_within = max(1, round(span * 0.15))
    if paused:
        state = "paused"
    elif is_due and days_left <= -overdue_after:
        state = "overdue"
    elif is_due:
        state = "due"
    elif days_left <= soon_within:
        state = "soon"
    else:
        state = "ok"

    return {
        "due_date": due.isoformat(),
        "effective_due": effective_due.isoformat(),
        "days_left": days_left,
        "ratio": round(ratio, 3),
        "span_days": span,
        "state": state,
        "is_due": is_due,
        "snoozed": bool(snooze and snooze > today and due <= today),
    }


def _manual_status(chore: dict[str, Any], today: date) -> dict[str, Any]:
    """Status of a chore that is only ever due when something makes it due."""
    forced = bool(chore.get("force_due"))
    paused = bool(chore.get("paused"))
    snooze = parse_date(chore.get("snooze_until"))
    due = today if forced else FAR_FUTURE
    effective_due = max(due, snooze) if (snooze and forced) else due
    days_left = (effective_due - today).days
    is_due = forced and days_left <= 0 and not paused
    return {
        "due_date": due.isoformat(),
        "effective_due": effective_due.isoformat(),
        "days_left": days_left,
        "ratio": 1.0 if forced else 0.0,
        "span_days": 1,
        "state": "paused" if paused else ("due" if is_due else "ok"),
        "is_due": is_due,
        "snoozed": bool(forced and snooze and snooze > today),
        "on_demand": True,
    }


def projected_dues(
    chore: dict[str, Any], now: datetime, start: date, end: date, limit: int = 40
) -> list[date]:
    """Dates in [start, end) on which the chore would show on a calendar.

    The first occurrence is the real due date (rolled forward to today when it
    is already overdue); later ones assume it gets done on time.
    """
    if chore.get("paused"):
        return []
    status = chore_status(chore, now)
    today = now.date()
    if chore["schedule"].get("kind") == KIND_MANUAL:
        return [today] if status["is_due"] and start <= today < end else []
    current = max(parse_date(status["effective_due"]) or today, today)
    out: list[date] = []
    for _ in range(limit * 4):
        if current >= end or len(out) >= limit:
            break
        if current >= start:
            out.append(current)
        nxt = next_due_date(chore["schedule"], current)
        if nxt <= current:
            break
        current = nxt
    return out


def completion_timestamp(chore: dict[str, Any], now: datetime) -> datetime:
    """When to record a completion.

    Normally ``now``. A fixed-month chore finished shortly *before* its period
    starts is recorded at the period start so it does not come due again days
    later.
    """
    schedule = chore["schedule"]
    if schedule.get("kind") != KIND_MONTHS or not chore.get("last_done"):
        return now
    status = chore_status(chore, now)
    if 0 < status["days_left"] <= EARLY_GRACE_DAYS:
        due = parse_date(status["due_date"])
        if due is not None:
            return now.replace(year=due.year, month=due.month, day=due.day, hour=0, minute=0, second=0, microsecond=0)
    return now


def staggered_last_done(schedule: dict[str, Any], now: datetime, fraction: float) -> datetime:
    """A plausible last-done time that leaves the chore ``fraction`` used up.

    Used when importing a list with no history so 100 chores do not all come
    due on the same day.
    """
    fraction = min(max(fraction, 0.0), 0.95)
    if schedule.get("kind") in (KIND_MONTHS, KIND_MANUAL):
        return now
    return now - timedelta(days=approx_interval_days(schedule) * fraction)
