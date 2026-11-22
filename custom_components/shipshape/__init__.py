"""Shipshape: condition-based household chores for Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .calendar_bridge import CalendarBridge
from .const import CARD_FILENAME, DOMAIN, URL_BASE, VERSION
from .library import STARTER_LIBRARY
from .manager import ShipshapeManager
from .notifications import Notifier
from .services import async_register_services
from .skylight_agenda import SkylightAgenda
from .skylight_lists import SkylightLists
from .skylight_sync import SkylightSync
from .websocket_api import async_register_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR, Platform.SWITCH, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the things that must only ever be registered once."""
    hass.data.setdefault(DOMAIN, {})
    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(frontend_dir), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILENAME}?v={VERSION}")
    async_register_websocket(hass)
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Shipshape from its config entry."""
    manager = ShipshapeManager(hass, {**entry.data, **entry.options})
    await manager.async_load()

    if entry.data.get("starter_library") and not manager.data["zones"]:
        manager.import_data(STARTER_LIBRARY, stagger=True)

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data["manager"] = manager
    domain_data["notifier"] = notifier = Notifier(hass, manager)
    domain_data["calendar_bridge"] = bridge = CalendarBridge(hass, manager)
    domain_data["skylight"] = skylight = SkylightSync(hass, manager)
    domain_data["skylight_lists"] = lists = SkylightLists(hass, manager, skylight)
    domain_data["agenda"] = agenda = SkylightAgenda(hass, manager, skylight)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    manager.async_start()
    notifier.async_start()
    bridge.async_start()
    skylight.async_start()
    lists.async_start()
    agenda.async_start()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Shipshape."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        domain_data = hass.data.get(DOMAIN, {})
        for key in ("agenda", "skylight_lists", "skylight", "calendar_bridge", "notifier"):
            part = domain_data.pop(key, None)
            if part is not None:
                part.async_stop()
        manager: ShipshapeManager | None = domain_data.pop("manager", None)
        if manager is not None:
            manager.async_stop()
            await manager.async_flush()
    return unloaded
