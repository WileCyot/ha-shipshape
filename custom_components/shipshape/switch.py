"""Vacation mode switch for Shipshape."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import ShipshapeEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([VacationSwitch(hass.data[DOMAIN]["manager"], entry, "vacation")])


class VacationSwitch(ShipshapeEntity, SwitchEntity):
    """Freeze every chore's clock while the household is away."""

    _attr_name = "Vacation mode"
    _attr_icon = "mdi:beach"

    @property
    def is_on(self) -> bool:
        return self.manager.vacation

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.manager.set_vacation(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.manager.set_vacation(False)
