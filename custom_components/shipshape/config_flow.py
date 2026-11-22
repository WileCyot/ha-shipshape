"""Config and options flows for Shipshape."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    CONF_ANNOUNCE_ENABLED,
    CONF_ANNOUNCE_TARGETS,
    CONF_ANNOUNCE_TIME,
    CONF_CALENDAR_DONE_ON_DELETE,
    CONF_CALENDAR_ENTITY,
    CONF_CALENDAR_HORIZON,
    CONF_DASHBOARD_PATH,
    CONF_DIGEST_ENABLED,
    CONF_DIGEST_TIME,
    CONF_NOTIFY_MAP,
    CONF_PARTICIPANTS,
    CONF_PUSH_ENABLED,
    CONF_PUSH_MAX,
    CONF_PUSH_TIME,
    CONF_SKYLIGHT_DEFAULT_PROFILE,
    CONF_SKYLIGHT_ENABLED,
    CONF_SKYLIGHT_FRAME,
    CONF_SKYLIGHT_PROFILE_MAP,
    DEFAULTS,
    DOMAIN,
)
from .skylight import (
    SkylightAuthError,
    SkylightClient,
    SkylightError,
    SkylightLogin,
    SkylightRateLimited,
)

_LOGGER = logging.getLogger(__name__)

CONF_STARTER = "starter_library"


class ShipshapeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup: one instance, one question."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Shipshape", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_STARTER, default=True): selector.BooleanSelector()}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ShipshapeOptionsFlow()


class ShipshapeOptionsFlow(OptionsFlow):
    """People, reminders, calendar bridge and Skylight."""

    def __init__(self) -> None:
        self._login: SkylightLogin | None = None
        self._session: aiohttp.ClientSession | None = None
        self._pending: dict[str, Any] = {}
        self._frames: list[dict[str, Any]] = []
        self._categories: list[dict[str, Any]] = []
        self._person_fields: dict[str, str] = {}

    # ------------------------------------------------------------------
    def _opts(self) -> dict[str, Any]:
        return {**DEFAULTS, **self.config_entry.options}

    def _finish(self, updates: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(title="", data={**self.config_entry.options, **updates})

    def _people(self) -> list[tuple[str, str]]:
        return sorted(
            ((state.entity_id, state.name) for state in self.hass.states.async_all("person")),
            key=lambda item: item[1],
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["people", "reminders", "calendar", "skylight"]
        )

    # ------------------------------------------------------------------
    async def async_step_people(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self._opts()
        people = self._people()
        fields = {f"Phone for {name}": person for person, name in people}
        if user_input is not None:
            notify_map = {
                person: user_input[label]
                for label, person in fields.items()
                if user_input.get(label)
            }
            return self._finish(
                {
                    CONF_PARTICIPANTS: user_input.get(CONF_PARTICIPANTS, []),
                    CONF_NOTIFY_MAP: notify_map,
                }
            )
        services = sorted(
            f"notify.{name}"
            for name in self.hass.services.async_services().get("notify", {})
            if name.startswith("mobile_app_")
        )
        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_PARTICIPANTS,
                description={"suggested_value": opts[CONF_PARTICIPANTS] or [p for p, _ in people]},
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="person", multiple=True)),
        }
        current_map: dict[str, str] = opts[CONF_NOTIFY_MAP] or {}
        for label, person in fields.items():
            schema[
                vol.Optional(label, description={"suggested_value": current_map.get(person)})
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=services, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
                )
            )
        return self.async_show_form(step_id="people", data_schema=vol.Schema(schema))

    # ------------------------------------------------------------------
    async def async_step_reminders(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self._opts()
        if user_input is not None:
            user_input.setdefault(CONF_ANNOUNCE_TARGETS, [])
            user_input[CONF_PUSH_MAX] = int(user_input.get(CONF_PUSH_MAX, 3))
            return self._finish(user_input)
        targets = sorted(
            f"notify.{name}"
            for name in self.hass.services.async_services().get("notify", {})
            if name not in ("persistent_notification", "send_message", "notify")
            and not name.startswith("mobile_app_")
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_DIGEST_ENABLED, default=opts[CONF_DIGEST_ENABLED]): selector.BooleanSelector(),
                vol.Required(CONF_DIGEST_TIME, default=opts[CONF_DIGEST_TIME]): selector.TimeSelector(),
                vol.Required(CONF_PUSH_ENABLED, default=opts[CONF_PUSH_ENABLED]): selector.BooleanSelector(),
                vol.Required(CONF_PUSH_TIME, default=opts[CONF_PUSH_TIME]): selector.TimeSelector(),
                vol.Required(CONF_PUSH_MAX, default=opts[CONF_PUSH_MAX]): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=10, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_ANNOUNCE_ENABLED, default=opts[CONF_ANNOUNCE_ENABLED]
                ): selector.BooleanSelector(),
                vol.Required(CONF_ANNOUNCE_TIME, default=opts[CONF_ANNOUNCE_TIME]): selector.TimeSelector(),
                vol.Optional(
                    CONF_ANNOUNCE_TARGETS, description={"suggested_value": opts[CONF_ANNOUNCE_TARGETS]}
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=targets,
                        multiple=True,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_DASHBOARD_PATH, default=opts[CONF_DASHBOARD_PATH]): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id="reminders", data_schema=schema)

    # ------------------------------------------------------------------
    async def async_step_calendar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self._opts()
        if user_input is not None:
            return self._finish(
                {
                    CONF_CALENDAR_ENTITY: user_input.get(CONF_CALENDAR_ENTITY) or None,
                    CONF_CALENDAR_HORIZON: int(user_input.get(CONF_CALENDAR_HORIZON, 7)),
                    CONF_CALENDAR_DONE_ON_DELETE: bool(user_input.get(CONF_CALENDAR_DONE_ON_DELETE)),
                }
            )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CALENDAR_ENTITY, description={"suggested_value": opts[CONF_CALENDAR_ENTITY]}
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="calendar", exclude_entities=["calendar.shipshape"])
                ),
                vol.Required(CONF_CALENDAR_HORIZON, default=opts[CONF_CALENDAR_HORIZON]): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_CALENDAR_DONE_ON_DELETE, default=opts[CONF_CALENDAR_DONE_ON_DELETE]
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="calendar", data_schema=schema)

    # ------------------------------------------------------------------
    def _sync(self):
        return self.hass.data[DOMAIN]["skylight"]

    def _signed_in(self) -> bool:
        return bool((self._sync()._state.get("auth") or {}).get("access_token"))

    async def async_step_skylight(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self._opts()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_SKYLIGHT_ENABLED):
                return self._finish({CONF_SKYLIGHT_ENABLED: False})
            email = (user_input.get("email") or "").strip()
            password = user_input.get("password") or ""
            if email and password:
                self._session = async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar())
                self._login = SkylightLogin(self._session)
                try:
                    outcome = await self._login.start(email, password)
                except SkylightRateLimited:
                    errors["base"] = "rate_limited"
                except SkylightAuthError:
                    errors["base"] = "invalid_auth"
                except (SkylightError, aiohttp.ClientError, asyncio.TimeoutError) as err:
                    _LOGGER.warning("Skylight sign-in failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if outcome == "mfa":
                        return await self.async_step_skylight_code()
                    return await self._skylight_tokens()
            elif self._signed_in():
                return await self.async_step_skylight_frame()
            else:
                errors["base"] = "credentials_needed"
        schema = vol.Schema(
            {
                vol.Required(CONF_SKYLIGHT_ENABLED, default=True): selector.BooleanSelector(),
                vol.Optional("email"): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
                ),
                vol.Optional("password"): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="skylight",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "status": "Signed in" if self._signed_in() else "Not signed in",
                "enabled": "on" if opts[CONF_SKYLIGHT_ENABLED] else "off",
            },
        )

    async def async_step_skylight_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and self._login is not None:
            try:
                await self._login.submit_code(str(user_input["code"]))
            except SkylightAuthError:
                errors["base"] = "invalid_code"
            except (SkylightError, aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Skylight verification failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return await self._skylight_tokens()
        return self.async_show_form(
            step_id="skylight_code",
            data_schema=vol.Schema({vol.Required("code"): selector.TextSelector()}),
            errors=errors,
        )

    async def _skylight_tokens(self) -> ConfigFlowResult:
        assert self._login is not None
        try:
            tokens = await self._login.finish()
        except (SkylightError, aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.warning("Skylight token exchange failed: %s", err)
            return self.async_abort(reason="skylight_failed")
        finally:
            if self._session is not None:
                await self._session.close()
                self._session = None
        self._sync().store_tokens(tokens)
        return await self.async_step_skylight_frame()

    async def async_step_skylight_frame(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self._opts()
        client: SkylightClient = self._sync().client()
        if user_input is None or not self._frames:
            try:
                self._frames = await client.frames()
            except (SkylightError, aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Could not list Skylight frames: %s", err)
                return self.async_abort(reason="skylight_failed")
            if not self._frames:
                return self.async_abort(reason="skylight_no_frames")
        if user_input is not None:
            self._pending[CONF_SKYLIGHT_FRAME] = user_input[CONF_SKYLIGHT_FRAME]
            return await self.async_step_skylight_profiles()
        if len(self._frames) == 1:
            self._pending[CONF_SKYLIGHT_FRAME] = self._frames[0]["id"]
            return await self.async_step_skylight_profiles()
        options = [selector.SelectOptionDict(value=f["id"], label=f["name"]) for f in self._frames]
        current = opts[CONF_SKYLIGHT_FRAME] or self._frames[0]["id"]
        return self.async_show_form(
            step_id="skylight_frame",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SKYLIGHT_FRAME, default=current): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_skylight_profiles(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self._opts()
        frame = self._pending[CONF_SKYLIGHT_FRAME]
        if not self._categories:
            try:
                self._categories = await self._sync().client().categories(frame)
            except (SkylightError, aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Could not list Skylight profiles: %s", err)
                return self.async_abort(reason="skylight_failed")
            if not self._categories:
                return self.async_abort(reason="skylight_no_profiles")
        fields = {f"Skylight profile for {name}": person for person, name in self._people()}
        if user_input is not None:
            profile_map = {
                person: user_input[label] for label, person in fields.items() if user_input.get(label)
            }
            return self._finish(
                {
                    CONF_SKYLIGHT_ENABLED: True,
                    CONF_SKYLIGHT_FRAME: frame,
                    CONF_SKYLIGHT_DEFAULT_PROFILE: user_input[CONF_SKYLIGHT_DEFAULT_PROFILE],
                    CONF_SKYLIGHT_PROFILE_MAP: profile_map,
                }
            )
        ordered = sorted(self._categories, key=lambda c: (not c["person"], c["label"]))
        options = [selector.SelectOptionDict(value=c["id"], label=c["label"]) for c in ordered]
        by_label = {c["label"].casefold(): c["id"] for c in ordered}
        valid = {c["id"] for c in ordered}
        current_map: dict[str, str] = opts[CONF_SKYLIGHT_PROFILE_MAP] or {}
        default_profile = opts[CONF_SKYLIGHT_DEFAULT_PROFILE]
        if default_profile not in valid:
            default_profile = ordered[0]["id"]
        schema: dict[Any, Any] = {
            vol.Required(CONF_SKYLIGHT_DEFAULT_PROFILE, default=default_profile): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
            )
        }
        for label, person in fields.items():
            name = label.removeprefix("Skylight profile for ").casefold()
            guess = current_map.get(person) if current_map.get(person) in valid else by_label.get(name)
            schema[vol.Optional(label, description={"suggested_value": guess})] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
            )
        return self.async_show_form(step_id="skylight_profiles", data_schema=vol.Schema(schema))
