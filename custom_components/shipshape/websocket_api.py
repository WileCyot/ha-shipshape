"""WebSocket API used by the Shipshape dashboard card."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .library import STARTER_LIBRARY
from .manager import ShipshapeError, ShipshapeManager


def _manager(hass: HomeAssistant) -> ShipshapeManager | None:
    return hass.data.get(DOMAIN, {}).get("manager")


def _with_manager(func):
    """Resolve the manager, turning Shipshape errors into websocket errors."""

    @callback
    def wrapper(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
    ) -> None:
        manager = _manager(hass)
        if manager is None:
            connection.send_error(msg["id"], "not_loaded", "Shipshape is not set up")
            return
        try:
            result = func(hass, connection, msg, manager)
        except ShipshapeError as err:
            connection.send_error(msg["id"], "shipshape_error", str(err))
            return
        except (TypeError, ValueError, KeyError) as err:
            connection.send_error(msg["id"], "invalid_format", str(err))
            return
        if result is not _HANDLED:
            connection.send_result(msg["id"], result)

    return wrapper


_HANDLED = object()


def _snapshot(manager: ShipshapeManager, connection: websocket_api.ActiveConnection) -> dict:
    snap = dict(manager.snapshot())
    snap["me"] = manager.person_for_user(connection.user.id if connection.user else None)
    return snap


@websocket_api.websocket_command({vol.Required("type"): "shipshape/state"})
@_with_manager
def ws_state(hass, connection, msg, manager):
    return _snapshot(manager, connection)


@websocket_api.websocket_command({vol.Required("type"): "shipshape/subscribe"})
@_with_manager
def ws_subscribe(hass, connection, msg, manager):
    @callback
    def forward() -> None:
        current = _manager(hass)
        if current is not None:
            connection.send_message(
                websocket_api.event_message(msg["id"], _snapshot(current, connection))
            )

    connection.subscriptions[msg["id"]] = manager.async_add_listener(forward)
    connection.send_result(msg["id"])
    forward()
    return _HANDLED


@websocket_api.websocket_command(
    {
        vol.Required("type"): "shipshape/chore/complete",
        vol.Required("chore_id"): str,
        vol.Optional("by"): vol.Any(str, None),
    }
)
@_with_manager
def ws_complete(hass, connection, msg, manager):
    by = msg.get("by") or manager.person_for_user(connection.user.id if connection.user else None)
    entry = manager.complete_chore(msg["chore_id"], by=by, source="card")
    return {"history_id": entry["id"]}


@websocket_api.websocket_command(
    {vol.Required("type"): "shipshape/undo", vol.Optional("history_id"): vol.Any(str, None)}
)
@_with_manager
def ws_undo(hass, connection, msg, manager):
    entry = manager.undo(msg.get("history_id"))
    return {"chore": entry["chore"]}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "shipshape/chore/snooze",
        vol.Required("chore_id"): str,
        vol.Optional("days", default=1): vol.All(int, vol.Range(min=1, max=365)),
    }
)
@_with_manager
def ws_snooze(hass, connection, msg, manager):
    manager.snooze_chore(msg["chore_id"], msg["days"])
    return {}


@websocket_api.websocket_command(
    {vol.Required("type"): "shipshape/chore/save", vol.Required("chore"): dict}
)
@_with_manager
def ws_chore_save(hass, connection, msg, manager):
    chore = manager.save_chore(msg["chore"])
    return {"id": chore["id"]}


@websocket_api.websocket_command(
    {vol.Required("type"): "shipshape/chore/delete", vol.Required("chore_id"): str}
)
@_with_manager
def ws_chore_delete(hass, connection, msg, manager):
    manager.remove_chore(msg["chore_id"])
    return {}


@websocket_api.websocket_command(
    {vol.Required("type"): "shipshape/zone/save", vol.Required("zone"): dict}
)
@_with_manager
def ws_zone_save(hass, connection, msg, manager):
    zone = manager.save_zone(msg["zone"])
    return {"id": zone["id"]}


@websocket_api.websocket_command(
    {vol.Required("type"): "shipshape/zone/delete", vol.Required("zone_id"): str}
)
@_with_manager
def ws_zone_delete(hass, connection, msg, manager):
    manager.remove_zone(msg["zone_id"])
    return {}


@websocket_api.websocket_command(
    {vol.Required("type"): "shipshape/vacation", vol.Required("active"): bool}
)
@_with_manager
def ws_vacation(hass, connection, msg, manager):
    manager.set_vacation(msg["active"])
    return {}


@websocket_api.websocket_command({vol.Required("type"): "shipshape/library"})
@_with_manager
def ws_library(hass, connection, msg, manager):
    return STARTER_LIBRARY


@websocket_api.websocket_command({vol.Required("type"): "shipshape/export"})
@_with_manager
def ws_export(hass, connection, msg, manager):
    return manager.export_data()


@websocket_api.websocket_command(
    {
        vol.Required("type"): "shipshape/import",
        vol.Required("data"): dict,
        vol.Optional("replace", default=False): bool,
        vol.Optional("stagger", default=True): bool,
    }
)
@websocket_api.require_admin
@_with_manager
def ws_import(hass, connection, msg, manager):
    return manager.import_data(msg["data"], replace=msg["replace"], stagger=msg["stagger"])


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    for command in (
        ws_state,
        ws_subscribe,
        ws_complete,
        ws_undo,
        ws_snooze,
        ws_chore_save,
        ws_chore_delete,
        ws_zone_save,
        ws_zone_delete,
        ws_vacation,
        ws_library,
        ws_export,
        ws_import,
    ):
        websocket_api.async_register_command(hass, command)
