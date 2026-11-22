"""Sensors for Shipshape."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import ShipshapeEntity
from .manager import ShipshapeManager
from .skylight_agenda import describe


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: ShipshapeManager = hass.data[DOMAIN]["manager"]
    entities: list[SensorEntity] = [
        SummarySensor(manager, entry, "due", "Due chores", "mdi:broom"),
        SummarySensor(manager, entry, "overdue", "Overdue chores", "mdi:alert-circle-outline"),
        SummarySensor(manager, entry, "on_track", "On track", "mdi:sparkles"),
    ]
    entities.extend(PersonPointsSensor(manager, entry, person) for person in manager.participants())
    agenda = hass.data[DOMAIN].get("agenda")
    if agenda is not None and agenda.enabled:
        entities.append(SkylightTodaySensor(manager, entry, agenda))
    async_add_entities(entities)

    known: dict[str, ZoneSensor] = {}

    @callback
    def sync_zones() -> None:
        zones = manager.data["zones"]
        new = [ZoneSensor(manager, entry, zone_id) for zone_id in zones if zone_id not in known]
        for sensor in new:
            known[sensor.zone_id] = sensor
        if new:
            async_add_entities(new)
        registry = er.async_get(hass)
        for zone_id in [z for z in known if z not in zones]:
            sensor = known.pop(zone_id)
            if sensor.entity_id and registry.async_get(sensor.entity_id):
                registry.async_remove(sensor.entity_id)

    sync_zones()
    entry.async_on_unload(manager.async_add_listener(sync_zones))


class SummarySensor(ShipshapeEntity, SensorEntity):
    """House-wide counts."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager, entry, key: str, name: str, icon: str) -> None:
        super().__init__(manager, entry, f"summary_{key}")
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = PERCENTAGE if key == "on_track" else "chores"

    @property
    def native_value(self) -> int:
        return self.manager.snapshot()["summary"][self._key]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._key != "due":
            return None
        due = self.manager.due_chores()
        return {
            "chores": [f"{v['zone']}: {v['name']}" for v in due[:15]],
            "vacation": self.manager.vacation,
        }


class ZoneSensor(ShipshapeEntity, SensorEntity):
    """Due chores in one zone."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "chores"

    def __init__(self, manager, entry, zone_id: str) -> None:
        super().__init__(manager, entry, f"zone_{zone_id}")
        self.zone_id = zone_id

    def _zone(self) -> dict[str, Any] | None:
        for zone in self.manager.snapshot()["zones"]:
            if zone["id"] == self.zone_id:
                return zone
        return None

    @property
    def available(self) -> bool:
        return self.zone_id in self.manager.data["zones"]

    @property
    def name(self) -> str:
        zone = self.manager.data["zones"].get(self.zone_id)
        return zone["name"] if zone else "Zone"

    @property
    def icon(self) -> str:
        zone = self.manager.data["zones"].get(self.zone_id)
        return (zone or {}).get("icon") or "mdi:home"

    @property
    def native_value(self) -> int | None:
        zone = self._zone()
        return zone["due"] if zone else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        zone = self._zone()
        if zone is None:
            return None
        return {
            "total": zone["total"],
            "overdue": zone["overdue"],
            "on_track": zone["on_track"],
            "zone_id": self.zone_id,
        }


class PersonPointsSensor(ShipshapeEntity, SensorEntity):
    """Effort points a person earned over the last 7 days."""

    _attr_icon = "mdi:star-circle-outline"
    _attr_native_unit_of_measurement = "points"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager, entry, person: str) -> None:
        super().__init__(manager, entry, f"points_{person}")
        self._person = person
        self._attr_name = f"{manager.person_name(person)} points"

    @property
    def native_value(self) -> int:
        return self.manager.points(self._person, 7)[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p7, c7 = self.manager.points(self._person, 7)
        p30, c30 = self.manager.points(self._person, 30)
        return {
            "person": self._person,
            "completed_7d": c7,
            "points_30d": p30,
            "completed_30d": c30,
            "due": len(self.manager.due_chores(self._person)),
        }


class SkylightTodaySensor(ShipshapeEntity, SensorEntity):
    """How many Skylight calendar events are on today, with the details as attributes."""

    _attr_name = "Skylight today"
    _attr_icon = "mdi:calendar-today"
    _attr_native_unit_of_measurement = "events"

    def __init__(self, manager, entry, agenda) -> None:
        super().__init__(manager, entry, "skylight_today")
        self._agenda = agenda

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._agenda.async_add_listener(self._handle_change))

    @property
    def available(self) -> bool:
        return self._agenda.updated is not None

    @property
    def native_value(self) -> int:
        return len(self._agenda.on_day(dt_util.now().date()))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        today = dt_util.now().date()
        return {
            "events": [describe(e) for e in self._agenda.on_day(today)][:25],
            "tomorrow": [describe(e) for e in self._agenda.on_day(today + timedelta(days=1))][:25],
            "updated": self._agenda.updated.isoformat() if self._agenda.updated else None,
        }
