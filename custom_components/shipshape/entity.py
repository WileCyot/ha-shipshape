"""Shared entity base for Shipshape."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, VERSION
from .manager import ShipshapeManager


class ShipshapeEntity(Entity):
    """An entity that refreshes whenever Shipshape data changes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: ShipshapeManager, entry: ConfigEntry, key: str) -> None:
        self.manager = manager
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Shipshape",
            manufacturer="Shipshape",
            model="Household chores",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.async_add_listener(self._handle_change))

    @callback
    def _handle_change(self) -> None:
        self.async_write_ha_state()
