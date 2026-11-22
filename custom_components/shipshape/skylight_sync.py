"""Best-effort two-way sync of due chores with Skylight's Chores.

Home Assistant -> Skylight: every due chore becomes a one-off Skylight chore,
and completing it here ticks it there.
Skylight -> Home Assistant: ticking it on the display completes it here,
un-ticking it again reopens it here, and deleting it snoozes it for a day.

Built on Skylight's private API (see skylight.py), so every failure is logged
and swallowed. Nothing else in Shipshape depends on this.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SKYLIGHT_DEFAULT_PROFILE,
    CONF_SKYLIGHT_ENABLED,
    CONF_SKYLIGHT_FRAME,
    CONF_SKYLIGHT_PROFILE_MAP,
)
from .manager import ShipshapeError, ShipshapeManager
from .models import parse_date
from .skylight import SkylightAuthError, SkylightClient, SkylightError, SkylightRateLimited

_LOGGER = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 30
INTERVAL = timedelta(minutes=5)
MAX_CREATES_PER_RUN = 10
MAX_OPEN_ON_SKYLIGHT = 30
WRITE_PAUSE = 2.0
# How long a finished chore stays watched so that un-ticking it on the display
# can still reopen it here.
DONE_KEEP_DAYS = 1


class SkylightSync:
    """Mirrors due chores to a Skylight frame and reads changes back."""

    def __init__(self, hass: HomeAssistant, manager: ShipshapeManager) -> None:
        self.hass = hass
        self.manager = manager
        self._unsubs: list[CALLBACK_TYPE] = []
        self._debounce: CALLBACK_TYPE | None = None
        self._lock = asyncio.Lock()
        self._client: SkylightClient | None = None
        self._backoff_until = 0.0
        self.last_error: str | None = None
        self.needs_login = False

    # ------------------------------------------------------------------
    @property
    def _state(self) -> dict[str, Any]:
        return self.manager.data["skylight"]

    @property
    def frame(self) -> str:
        return str(self.manager.options.get(CONF_SKYLIGHT_FRAME) or "")

    @property
    def enabled(self) -> bool:
        return bool(
            self.manager.options.get(CONF_SKYLIGHT_ENABLED)
            and self.frame
            and self.manager.options.get(CONF_SKYLIGHT_DEFAULT_PROFILE)
            and (self._state.get("auth") or {}).get("access_token")
        )

    @callback
    def store_tokens(self, tokens: dict[str, Any]) -> None:
        """Persist tokens (called by the client on refresh and by the config flow)."""
        self._state["auth"] = tokens
        self._client = None
        self.needs_login = False
        self.manager.async_save_quietly()

    def client(self) -> SkylightClient:
        if self._client is None:
            self._client = SkylightClient(
                async_get_clientsession(self.hass), self._state.get("auth") or {}, self._save_refreshed
            )
        return self._client

    @callback
    def _save_refreshed(self, tokens: dict[str, Any]) -> None:
        self._state["auth"] = tokens
        self.manager.async_save_quietly()

    # ------------------------------------------------------------------
    @callback
    def async_start(self) -> None:
        if not self.enabled:
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

    async def async_sync(self) -> None:
        if not self.enabled or self.needs_login:
            return
        if self.hass.loop.time() < self._backoff_until:
            return
        async with self._lock:
            try:
                await self._sync()
                self.last_error = None
            except SkylightAuthError as err:
                self.needs_login = True
                self.last_error = str(err)
                _LOGGER.error(
                    "Skylight sign-in is no longer valid (%s). Open Shipshape's options and sign in to Skylight again",
                    err,
                )
            except SkylightRateLimited as err:
                self._backoff_until = self.hass.loop.time() + 1800
                self.last_error = str(err)
                _LOGGER.warning("Skylight sync paused for 30 minutes: %s", err)
            except (SkylightError, ShipshapeError, asyncio.TimeoutError, OSError) as err:
                self.last_error = str(err)
                _LOGGER.warning("Skylight sync failed: %s", err)

    # ------------------------------------------------------------------
    def _category_for(self, view: dict[str, Any]) -> str:
        profile_map: dict[str, str] = self.manager.options.get(CONF_SKYLIGHT_PROFILE_MAP) or {}
        for person in view.get("responsible") or []:
            if profile_map.get(person):
                return str(profile_map[person])
        return str(self.manager.options.get(CONF_SKYLIGHT_DEFAULT_PROFILE))

    def _person_for(self, category_id: str | None) -> str | None:
        if not category_id:
            return None
        profile_map: dict[str, str] = self.manager.options.get(CONF_SKYLIGHT_PROFILE_MAP) or {}
        for person, category in profile_map.items():
            if str(category) == str(category_id):
                return person
        return None

    def _last_history_id(self, chore_id: str) -> str | None:
        for entry in reversed(self.manager.data["history"]):
            if entry.get("chore_id") == chore_id:
                return entry.get("id")
        return None

    def _due_view(self, chore_id: str) -> dict[str, Any] | None:
        return next((v for v in self.manager.due_chores() if v["id"] == chore_id), None)

    async def _sync(self) -> None:
        if self.manager.vacation:
            # Everything is frozen; leave the display exactly as it is.
            return
        client = self.client()
        frame = self.frame
        mapped: dict[str, dict[str, Any]] = self._state["chores"]
        done: dict[str, dict[str, Any]] = self._state.setdefault("done", {})
        today = dt_util.now().date()
        due = {view["id"]: view for view in self.manager.due_chores()}

        # --- stop watching finished chores that are old news ---------------
        for chore_id, rec in list(done.items()):
            day = parse_date(rec.get("day")) or today
            if (today - day).days > DONE_KEEP_DAYS or chore_id not in self.manager.data["chores"]:
                done.pop(chore_id)

        # --- read Skylight ------------------------------------------------
        remote: dict[str, dict[str, Any]] = {}
        if mapped or done:
            days = [
                parse_date(rec.get("start")) or today for rec in (*mapped.values(), *done.values())
            ]
            after = min([today, *days]).isoformat()
            for item in await client.chores(frame, after, today.isoformat()):
                remote[item["id"]] = item

        # --- finished chores that were un-ticked on the display ------------
        for chore_id, rec in list(done.items()):
            item = remote.get(rec["sid"])
            if item is None or item.get("status") != "pending":
                continue
            done.pop(chore_id)
            current = mapped.get(chore_id)
            if current is not None and current["sid"] != rec["sid"]:
                # The chore is already open again under a newer Skylight chore,
                # so this one is a duplicate on the display.
                try:
                    await client.delete_chore(frame, rec["sid"])
                except SkylightError as err:
                    _LOGGER.warning("Could not remove a duplicate Skylight chore: %s", err)
                await asyncio.sleep(WRITE_PAUSE)
                continue
            if chore_id not in due:
                _LOGGER.info("Chore %s was un-ticked on Skylight; reopening it", chore_id)
                try:
                    if not rec.get("history_id"):
                        raise ShipshapeError("no completion on record")
                    self.manager.undo(rec["history_id"])
                except ShipshapeError:
                    self.manager.make_due(chore_id)
                view = self._due_view(chore_id)
                if view is None:
                    continue
                due[chore_id] = view
            mapped[chore_id] = {"sid": rec["sid"], "start": rec.get("start") or today.isoformat()}

        # --- chores we are tracking as open on the display ----------------
        for chore_id, rec in list(mapped.items()):
            item = remote.get(rec["sid"])
            view = due.get(chore_id)
            if item is None:
                # Missing from Skylight's list. Only believe it after it stays
                # missing twice, and never when the whole list came back empty
                # (that looks like an API change, not a person deleting things).
                if not remote:
                    continue
                rec["misses"] = int(rec.get("misses", 0)) + 1
                if rec["misses"] < 2:
                    continue
                # Deleted on the display: stop nagging about it until tomorrow.
                mapped.pop(chore_id)
                if view is not None:
                    self.manager.snooze_chore(chore_id, 1)
                    due.pop(chore_id, None)
                continue
            rec["misses"] = 0
            if item.get("status") == "complete":
                mapped.pop(chore_id)
                history_id = self._last_history_id(chore_id)
                if view is not None:
                    by = self._person_for(item.get("completed_category_id") or item.get("category_id"))
                    entry = self.manager.complete_chore(chore_id, by=by, source="skylight")
                    history_id = entry["id"]
                    due.pop(chore_id, None)
                if chore_id in self.manager.data["chores"]:
                    done[chore_id] = {
                        "sid": rec["sid"],
                        "start": rec.get("start"),
                        "history_id": history_id,
                        "day": today.isoformat(),
                    }
                continue
            if view is None:
                # Handled in Home Assistant: tick it off on the display too,
                # or remove it if the chore itself no longer exists.
                exists = chore_id in self.manager.data["chores"]
                snoozed = exists and self.manager.data["chores"][chore_id].get("snooze_until")
                if exists and not snoozed:
                    await client.set_chore_status(frame, rec["sid"], "complete")
                    done[chore_id] = {
                        "sid": rec["sid"],
                        "start": rec.get("start"),
                        "history_id": self._last_history_id(chore_id),
                        "day": today.isoformat(),
                    }
                else:
                    await client.delete_chore(frame, rec["sid"])
                mapped.pop(chore_id)
                await asyncio.sleep(WRITE_PAUSE)

        # --- push what is newly due ---------------------------------------
        created = 0
        for chore_id, view in due.items():
            if chore_id in mapped:
                continue
            if created >= MAX_CREATES_PER_RUN or len(mapped) >= MAX_OPEN_ON_SKYLIGHT:
                break
            sid = await client.create_chore(
                frame,
                f"{view['zone']}: {view['name']}",
                self._category_for(view),
                today.isoformat(),
            )
            mapped[chore_id] = {"sid": sid, "start": today.isoformat()}
            self.manager.async_save_quietly()
            created += 1
            await asyncio.sleep(WRITE_PAUSE)

        self.manager.async_save_quietly()
        if created >= MAX_CREATES_PER_RUN:
            self._schedule()
