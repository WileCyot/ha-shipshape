"""Service actions for Shipshape."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .manager import ShipshapeError, get_manager
from .skylight import SkylightError

CHORE_REF = {
    vol.Optional("chore_id"): cv.string,
    vol.Optional("chore"): cv.string,
    vol.Optional("zone"): cv.string,
}


def _resolve(hass: HomeAssistant, call: ServiceCall) -> str:
    manager = get_manager(hass)
    chore_id = call.data.get("chore_id")
    if chore_id:
        return chore_id
    name = call.data.get("chore")
    if not name:
        raise ShipshapeError("Give either chore_id or chore (name)")
    found = manager.find_chore(name, call.data.get("zone"))
    if found is None:
        raise ShipshapeError(
            f"No single chore matches '{name}'. Add the zone if the name is used in several rooms."
        )
    return found["id"]


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register Shipshape services (once)."""

    @callback
    def complete(call: ServiceCall) -> None:
        get_manager(hass).complete_chore(
            _resolve(hass, call), by=call.data.get("by"), source="service"
        )

    @callback
    def snooze(call: ServiceCall) -> None:
        get_manager(hass).snooze_chore(_resolve(hass, call), call.data.get("days", 1))

    @callback
    def make_due(call: ServiceCall) -> None:
        get_manager(hass).make_due(_resolve(hass, call))

    @callback
    def add_chore(call: ServiceCall) -> None:
        manager = get_manager(hass)
        zone = manager.find_zone(call.data["zone"])
        if zone is None:
            zone = manager.save_zone({"name": call.data["zone"]})
        schedule: dict[str, Any]
        if call.data.get("months"):
            schedule = {"months": call.data["months"]}
        else:
            schedule = {"every": call.data.get("every", 1), "unit": call.data.get("unit", "weeks")}
        payload: dict[str, Any] = {
            "zone_id": zone["id"],
            "name": call.data["name"],
            "schedule": schedule,
            "effort": call.data.get("effort", 1),
            "assignees": call.data.get("assignees", []),
            "rotate": call.data.get("rotate", False),
            "condition": 0.0,
        }
        manager.save_chore(payload)

    @callback
    def import_data(call: ServiceCall) -> ServiceResponse:
        return get_manager(hass).import_data(
            call.data["data"],
            replace=call.data.get("replace", False),
            stagger=call.data.get("stagger", True),
        )

    @callback
    def export_data(call: ServiceCall) -> ServiceResponse:
        return get_manager(hass).export_data()

    @callback
    def set_vacation(call: ServiceCall) -> None:
        get_manager(hass).set_vacation(call.data["active"])

    async def sync_now(call: ServiceCall) -> None:
        data = hass.data.get(DOMAIN, {})
        if (bridge := data.get("calendar_bridge")) is not None:
            await bridge.async_sync()
        if (skylight := data.get("skylight")) is not None:
            await skylight.async_sync()

    async def send_reminders(call: ServiceCall) -> ServiceResponse:
        notifier = hass.data.get(DOMAIN, {}).get("notifier")
        if notifier is None:
            raise ShipshapeError("Shipshape is not set up")
        kind = call.data["kind"]
        if kind == "digest":
            sent = await notifier.async_send_digest()
        elif kind == "push":
            sent = await notifier.async_send_pushes()
        else:
            sent = int(await notifier.async_announce())
        return {"sent": sent}

    async def _require_admin(call: ServiceCall) -> None:
        if call.context.user_id:
            user = await hass.auth.async_get_user(call.context.user_id)
            if user is None or not user.is_admin:
                raise Unauthorized

    def _skylight():
        sync = hass.data.get(DOMAIN, {}).get("skylight")
        if sync is None:
            raise ShipshapeError("Shipshape is not set up")
        return sync

    async def skylight_status(call: ServiceCall) -> ServiceResponse:
        """What the Skylight sync currently believes. No secrets."""
        await _require_admin(call)
        sync = _skylight()
        state = sync.manager.data["skylight"]
        opts = sync.manager.options
        return {
            "enabled": sync.enabled,
            "signed_in": bool((state.get("auth") or {}).get("access_token")),
            "needs_login": sync.needs_login,
            "last_error": sync.last_error,
            "frame": sync.frame,
            "options": {k: v for k, v in opts.items() if k.startswith("skylight_")},
            "open": state.get("chores", {}),
            "watching": state.get("done", {}),
            "lists": state.get("lists", {}),
        }

    async def skylight_api(call: ServiceCall) -> ServiceResponse:
        """Raw call to Skylight's private API on the configured frame (diagnostics)."""
        await _require_admin(call)
        sync = _skylight()
        if not (sync.manager.data["skylight"].get("auth") or {}).get("access_token"):
            raise ShipshapeError("Not signed in to Skylight")
        path = str(call.data["path"]).replace("{frame}", sync.frame)
        if not (path == "/frames" or path == "/user" or path.startswith(f"/frames/{sync.frame}")) or ".." in path:
            raise ShipshapeError("Only paths on the configured Skylight frame are allowed")
        try:
            result = await sync.client().request(
                call.data.get("method", "GET"), path, call.data.get("params"), call.data.get("body")
            )
        except SkylightError as err:
            return {"ok": False, "error": str(err)}
        return {"ok": True, "result": result}

    hass.services.async_register(
        DOMAIN, "skylight_status", skylight_status, vol.Schema({}), supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN,
        "skylight_api",
        skylight_api,
        vol.Schema(
            {
                vol.Required("path"): cv.string,
                vol.Optional("method", default="GET"): vol.In(["GET", "POST", "PUT", "PATCH", "DELETE"]),
                vol.Optional("params"): dict,
                vol.Optional("body"): dict,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "send_reminders",
        send_reminders,
        vol.Schema({vol.Required("kind"): vol.In(["digest", "push", "announce"])}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "complete_chore", complete, vol.Schema({**CHORE_REF, vol.Optional("by"): cv.entity_id})
    )
    hass.services.async_register(
        DOMAIN,
        "snooze_chore",
        snooze,
        vol.Schema({**CHORE_REF, vol.Optional("days", default=1): vol.All(int, vol.Range(1, 365))}),
    )
    hass.services.async_register(DOMAIN, "make_due", make_due, vol.Schema(CHORE_REF))
    hass.services.async_register(
        DOMAIN,
        "add_chore",
        add_chore,
        vol.Schema(
            {
                vol.Required("zone"): cv.string,
                vol.Required("name"): cv.string,
                vol.Optional("every"): vol.All(int, vol.Range(1, 3650)),
                vol.Optional("unit"): vol.In(["days", "weeks", "months"]),
                vol.Optional("months"): [vol.All(int, vol.Range(1, 12))],
                vol.Optional("effort"): vol.All(int, vol.Range(1, 3)),
                vol.Optional("assignees"): cv.entity_ids,
                vol.Optional("rotate"): cv.boolean,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "import_data",
        import_data,
        vol.Schema(
            {
                vol.Required("data"): dict,
                vol.Optional("replace", default=False): cv.boolean,
                vol.Optional("stagger", default=True): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "export_data", export_data, vol.Schema({}), supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, "set_vacation", set_vacation, vol.Schema({vol.Required("active"): cv.boolean})
    )
    hass.services.async_register(DOMAIN, "sync_now", sync_now, vol.Schema({}))
