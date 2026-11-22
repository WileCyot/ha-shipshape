"""Reads the Skylight calendar so Home Assistant can show what is happening."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import CONF_SKYLIGHT_CALENDAR, CONF_SKYLIGHT_DEFAULT_PROFILE
from .manager import ShipshapeManager
from .skylight import SkylightAuthError, SkylightError, SkylightRateLimited

_LOGGER = logging.getLogger(__name__)

INTERVAL = timedelta(minutes=15)
DAYS_AHEAD = 8
MAX_RANGE_DAYS = 62


class SkylightAgenda:
    """A small cache of upcoming Skylight calendar events."""

    def __init__(self, hass: HomeAssistant, manager: ShipshapeManager, sync: Any) -> None:
        self.hass = hass
        self.manager = manager
        self.sync = sync
        self.events: list[dict[str, Any]] = []
        self.updated: datetime | None = None
        self.last_error: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []

    @property
    def enabled(self) -> bool:
        return bool(
            self.manager.options.get(CONF_SKYLIGHT_CALENDAR) and self.sync.signed_in and self.sync.frame
        )

    @callback
    def async_start(self) -> None:
        if not self.enabled:
            return
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, INTERVAL))
        self._unsubs.append(async_call_later(self.hass, 8, self._tick))

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    async def _tick(self, _now: datetime) -> None:
        await self.async_refresh()

    async def async_refresh(self) -> None:
        if not self.enabled or self.sync.needs_login or self.sync.backing_off:
            return
        today = dt_util.now().date()
        try:
            self.events = await self.async_fetch(today, today + timedelta(days=DAYS_AHEAD))
            self.updated = dt_util.now()
            self.last_error = None
        except SkylightAuthError as err:
            self.sync.needs_login = True
            self.last_error = str(err)
            _LOGGER.error("Skylight sign-in is no longer valid (%s)", err)
        except SkylightRateLimited as err:
            self.sync.back_off()
            self.last_error = str(err)
        except (SkylightError, asyncio.TimeoutError, OSError) as err:
            self.last_error = str(err)
            _LOGGER.warning("Could not read the Skylight calendar: %s", err)
        for listener in list(self._listeners):
            listener()

    async def async_fetch(self, start: date, end: date) -> list[dict[str, Any]]:
        """Events from start (inclusive) to end (exclusive), sorted."""
        if (end - start).days > MAX_RANGE_DAYS:
            end = start + timedelta(days=MAX_RANGE_DAYS)
        raw = await self.sync.client().calendar_events(
            self.sync.frame, start.isoformat(), end.isoformat(), str(dt_util.DEFAULT_TIME_ZONE)
        )
        default_profile = str(self.manager.options.get(CONF_SKYLIGHT_DEFAULT_PROFILE) or "")
        events = []
        for item in raw:
            parsed = _parse_event(item, default_profile)
            if parsed is not None:
                events.append(parsed)
        events.sort(key=lambda e: (_as_datetime(e["start"]), e["summary"]))
        return events

    def on_day(self, day: date) -> list[dict[str, Any]]:
        """Cached events that touch a given day."""
        day_start = dt_util.start_of_local_day(day)
        day_end = day_start + timedelta(days=1)
        return [
            e
            for e in self.events
            if _as_datetime(e["start"]) < day_end and _as_datetime(e["end"]) > day_start
        ]


def _as_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return dt_util.start_of_local_day(value)


def _parse_event(item: dict[str, Any], default_profile: str) -> dict[str, Any] | None:
    start = dt_util.parse_datetime(str(item.get("starts_at") or ""))
    end = dt_util.parse_datetime(str(item.get("ends_at") or ""))
    if start is None:
        return None
    start = dt_util.as_local(start)
    end = dt_util.as_local(end) if end is not None else start + timedelta(hours=1)
    who = item.get("category") if str(item.get("category_id") or "") != default_profile else None
    base = {
        "uid": item["id"],
        "summary": item.get("summary") or "(no title)",
        "description": item.get("description"),
        "location": item.get("location"),
        "who": who,
        "all_day": bool(item.get("all_day")),
    }
    if base["all_day"]:
        first = start.date()
        last = end.date() if end.time() == time(0, 0) else end.date() + timedelta(days=1)
        if last <= first:
            last = first + timedelta(days=1)
        return {**base, "start": first, "end": last}
    if end <= start:
        end = start + timedelta(minutes=30)
    return {**base, "start": start, "end": end}


def describe(event: dict[str, Any]) -> dict[str, Any]:
    """A JSON-friendly, display-ready version of an event for sensor attributes."""
    if event["all_day"]:
        when = "All day"
    else:
        when = event["start"].strftime("%I:%M %p").lstrip("0")
    return {
        "summary": event["summary"],
        "when": when,
        "start": event["start"].isoformat(),
        "end": event["end"].isoformat(),
        "all_day": event["all_day"],
        "who": event["who"],
        "location": event["location"],
    }
