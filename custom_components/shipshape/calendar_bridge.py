"""Mirror due chores into another calendar entity (e.g. Google Calendar).

The target calendar is what a wall display such as Skylight syncs. Each due
chore becomes one all-day event. When an event disappears from the calendar
(someone deleted it on the display) the chore is treated as done, if that option
is on.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CALENDAR_MARKER,
    CONF_CALENDAR_DONE_ON_DELETE,
    CONF_CALENDAR_ENTITY,
    CONF_CALENDAR_HORIZON,
)
from .manager import ShipshapeManager
from .models import parse_date

_LOGGER = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 20
INTERVAL = timedelta(minutes=10)
MAX_WRITES_PER_RUN = 25
MISSES_BEFORE_GONE = 2


class CalendarBridge:
    """Keeps one all-day event per due chore in the target calendar."""

    def __init__(self, hass: HomeAssistant, manager: ShipshapeManager) -> None:
        self.hass = hass
        self.manager = manager
        self._unsubs: list[CALLBACK_TYPE] = []
        self._debounce: CALLBACK_TYPE | None = None
        self._lock = asyncio.Lock()
        self.last_error: str | None = None

    @property
    def entity_id(self) -> str | None:
        return self.manager.options.get(CONF_CALENDAR_ENTITY) or None

    @callback
    def async_start(self) -> None:
        if not self.entity_id:
            return
        self._unsubs.append(self.manager.async_add_listener(self._schedule))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, INTERVAL))
        self._schedule()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._debounce:
            self._debounce()
            self._debounce = None

    @callback
    def _schedule(self) -> None:
        if self._debounce:
            self._debounce()
        self._debounce = async_call_later(self.hass, DEBOUNCE_SECONDS, self._tick)

    async def _tick(self, _now: datetime) -> None:
        self._debounce = None
        await self.async_sync()

    def _entity(self) -> CalendarEntity | None:
        component = self.hass.data.get("calendar")
        if component is None or not self.entity_id:
            return None
        entity = component.get_entity(self.entity_id)
        if entity is None or not entity.available:
            return None
        return entity

    def _desired(self) -> dict[str, tuple[date, str, str]]:
        """chore_id -> (event day, summary, real due date)."""
        if self.manager.vacation:
            return {}
        today = dt_util.now().date()
        horizon = max(0, int(self.manager.options.get(CONF_CALENDAR_HORIZON) or 0))
        last_day = today + timedelta(days=horizon)
        out: dict[str, tuple[date, str, str]] = {}
        for view in self.manager.chore_views():
            if view["state"] == "paused":
                continue
            effective = parse_date(view["effective_due"]) or today
            day = max(effective, today)
            if day <= last_day:
                out[view["id"]] = (day, f"{view['zone']}: {view['name']}", view["due_date"])
        return out

    async def async_sync(self) -> None:
        """Reconcile the target calendar with what is due."""
        if not self.entity_id:
            return
        async with self._lock:
            try:
                await self._sync()
                self.last_error = None
            except Exception as err:  # noqa: BLE001 - never let a calendar hiccup break Shipshape
                self.last_error = str(err)
                _LOGGER.warning("Shipshape calendar sync failed: %s", err)

    async def _sync(self) -> None:
        entity = self._entity()
        if entity is None:
            _LOGGER.debug("Calendar %s is not available yet", self.entity_id)
            return
        features = entity.supported_features or 0
        if not features & CalendarEntityFeature.CREATE_EVENT or not features & CalendarEntityFeature.DELETE_EVENT:
            raise RuntimeError(
                f"{self.entity_id} is read-only. Give Home Assistant read/write access to that calendar."
            )

        store: dict[str, Any] = self.manager.data["calendar"]
        mapped: dict[str, dict[str, Any]] = store["events"]
        skip: dict[str, str] = store["skip"]
        desired = self._desired()
        today = dt_util.now().date()
        horizon = max(0, int(self.manager.options.get(CONF_CALENDAR_HORIZON) or 0))

        # --- what is really on the calendar -------------------------------
        mapped_days = [parse_date(rec.get("date")) or today for rec in mapped.values()]
        first_day = min([today, *mapped_days]) - timedelta(days=1)
        last_day = today + timedelta(days=horizon + 2)
        start = dt_util.start_of_local_day(first_day)
        end = dt_util.start_of_local_day(last_day)
        actual = await entity.async_get_events(self.hass, start, end)
        by_uid = {event.uid: event for event in actual if event.uid}
        by_marker: dict[str, Any] = {}
        for event in actual:
            description = event.description or ""
            index = description.find(CALENDAR_MARKER)
            if index >= 0:
                chore_id = description[index + len(CALENDAR_MARKER) :].split(")")[0].split()[0]
                by_marker[chore_id] = event

        # --- events that vanished (deleted on the display) ----------------
        for chore_id, rec in list(mapped.items()):
            if rec.get("uid") and rec["uid"] in by_uid:
                rec["misses"] = 0
                continue
            adopted = by_marker.get(chore_id)
            if adopted is not None and adopted.uid:
                rec["uid"] = adopted.uid
                rec["misses"] = 0
                continue
            rec["misses"] = int(rec.get("misses", 0)) + 1
            if rec["misses"] < MISSES_BEFORE_GONE:
                continue
            mapped.pop(chore_id)
            want = desired.get(chore_id)
            if want is None:
                continue
            if not rec.get("uid"):
                # We never saw this event come back, so its absence proves
                # nothing about what a person did. Do not recreate it in a loop.
                _LOGGER.warning(
                    "Calendar %s did not return the event created for '%s'", self.entity_id, want[1]
                )
                skip[chore_id] = want[2]
                continue
            rec_day = parse_date(rec.get("date")) or today
            if self.manager.options.get(CONF_CALENDAR_DONE_ON_DELETE) and rec_day <= today:
                _LOGGER.info("Calendar event for chore %s was removed; marking it done", chore_id)
                self.manager.complete_chore(chore_id, source="calendar")
                desired.pop(chore_id, None)
            else:
                skip[chore_id] = want[2]

        # --- events that are stale or on the wrong day --------------------
        writes = 0
        for chore_id, rec in list(mapped.items()):
            want = desired.get(chore_id)
            if want is not None and want[0].isoformat() == rec.get("date") and want[1] == rec.get("summary"):
                continue
            if writes >= MAX_WRITES_PER_RUN:
                break
            if rec.get("uid"):
                try:
                    await entity.async_delete_event(rec["uid"])
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Could not delete calendar event %s: %s", rec["uid"], err)
            mapped.pop(chore_id)
            writes += 1

        # --- forget dismissals that no longer apply -----------------------
        for chore_id in list(skip):
            want = desired.get(chore_id)
            if want is None or want[2] != skip[chore_id]:
                skip.pop(chore_id)

        # --- create what is missing ---------------------------------------
        created: list[str] = []
        for chore_id, (day, summary, _due) in desired.items():
            if chore_id in mapped or chore_id in skip:
                continue
            if writes >= MAX_WRITES_PER_RUN:
                break
            await entity.async_create_event(
                summary=summary,
                dtstart=day,
                dtend=day + timedelta(days=1),
                description=f"Managed by Shipshape ({CALENDAR_MARKER}{chore_id})",
            )
            mapped[chore_id] = {
                "uid": None,
                "date": day.isoformat(),
                "summary": summary,
                "misses": -1,
            }
            created.append(chore_id)
            writes += 1
            await asyncio.sleep(0.3)

        # --- learn the ids of what was just created -----------------------
        if created:
            fresh = await entity.async_get_events(self.hass, start, end)
            for event in fresh:
                description = event.description or ""
                index = description.find(CALENDAR_MARKER)
                if index < 0 or not event.uid:
                    continue
                chore_id = description[index + len(CALENDAR_MARKER) :].split(")")[0].split()[0]
                if chore_id in mapped and not mapped[chore_id].get("uid"):
                    mapped[chore_id]["uid"] = event.uid
                    mapped[chore_id]["misses"] = 0

        self.manager.async_save_quietly()
        if writes >= MAX_WRITES_PER_RUN:
            self._schedule()
