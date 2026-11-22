"""Calendar of upcoming chores for Shipshape."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import ShipshapeEntity
from .manager import ShipshapeManager
from .models import projected_dues


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager = hass.data[DOMAIN]["manager"]
    entities: list[CalendarEntity] = [ChoreCalendar(manager, entry, "calendar")]
    agenda = hass.data[DOMAIN].get("agenda")
    if agenda is not None and agenda.enabled:
        entities.append(SkylightCalendar(manager, entry, "skylight_calendar", agenda))
    async_add_entities(entities)


class ChoreCalendar(ShipshapeEntity, CalendarEntity):
    """All-day events on the day each chore comes due."""

    _attr_name = None
    _attr_icon = "mdi:broom"

    manager: ShipshapeManager

    def _events(self, start, end) -> list[CalendarEvent]:
        if self.manager.vacation:
            return []
        now = self.manager.now()
        events: list[CalendarEvent] = []
        for chore in self.manager.data["chores"].values():
            zone = self.manager.data["zones"].get(chore["zone_id"], {})
            for day in projected_dues(chore, now, start, end):
                events.append(
                    CalendarEvent(
                        start=day,
                        end=day + timedelta(days=1),
                        summary=f"{zone.get('name', '')}: {chore['name']}",
                        uid=f"{chore['id']}-{day.isoformat()}",
                    )
                )
        events.sort(key=lambda e: (e.start, e.summary))
        return events

    @property
    def event(self) -> CalendarEvent | None:
        today = dt_util.now().date()
        events = self._events(today, today + timedelta(days=14))
        return events[0] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        start = dt_util.as_local(start_date).date()
        end = dt_util.as_local(end_date).date() + timedelta(days=1)
        return self._events(start, end)


class SkylightCalendar(ShipshapeEntity, CalendarEntity):
    """What is on the Skylight calendar, read through its private API."""

    _attr_name = "Skylight"
    _attr_icon = "mdi:calendar-star"

    def __init__(self, manager, entry, key, agenda) -> None:
        super().__init__(manager, entry, key)
        self._agenda = agenda

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._agenda.async_add_listener(self._handle_change))

    @staticmethod
    def _convert(event) -> CalendarEvent:
        summary = event["summary"]
        if event.get("who"):
            summary = f"{summary} ({event['who']})"
        return CalendarEvent(
            start=event["start"],
            end=event["end"],
            summary=summary,
            description=event.get("description"),
            location=event.get("location"),
            uid=str(event["uid"]),
        )

    @property
    def available(self) -> bool:
        return self._agenda.updated is not None

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        today = now.date()
        for event in self._agenda.events:
            end = event["end"]
            if (end > today) if event["all_day"] else (end > now):
                return self._convert(event)
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        start = dt_util.as_local(start_date).date()
        end = dt_util.as_local(end_date).date() + timedelta(days=1)
        try:
            events = await self._agenda.async_fetch(start, end)
        except Exception:  # noqa: BLE001 - fall back to what we already have
            events = self._agenda.events
        return [self._convert(event) for event in events]
