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
    async_add_entities([ChoreCalendar(hass.data[DOMAIN]["manager"], entry, "calendar")])


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
