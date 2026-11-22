"""Two-way sync between Home Assistant to-do lists and Skylight lists.

Each link pairs one Home Assistant to-do entity with one Skylight list. Items
are matched by an id pair remembered from the last run, so a change on either
side (add, tick, un-tick, rename, delete) can be told apart from a change on
the other and carried across.

Old completed items that were never paired are left alone, so linking a
Skylight grocery list with years of ticked-off history does not flood the
Home Assistant list.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import (
    CONF_SKYLIGHT_GROCERY_ENABLED,
    CONF_SKYLIGHT_GROCERY_LIST,
    CONF_SKYLIGHT_GROCERY_TODO,
    CONF_SKYLIGHT_TODO_ENABLED,
    CONF_SKYLIGHT_TODO_LIST,
    CONF_SKYLIGHT_TODO_TODO,
)
from .manager import ShipshapeManager
from .skylight import SkylightAuthError, SkylightError, SkylightRateLimited

_LOGGER = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 4
INTERVAL = timedelta(minutes=5)
MAX_WRITES_PER_RUN = 40
WRITE_PAUSE = 0.4

PENDING = "pending"
COMPLETED = "completed"


def _status_of(item: TodoItem) -> str:
    return COMPLETED if item.status == TodoItemStatus.COMPLETED else PENDING


def _same(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _ha_status(status: str) -> TodoItemStatus:
    return TodoItemStatus.COMPLETED if status == COMPLETED else TodoItemStatus.NEEDS_ACTION


class SkylightLists:
    """Keeps linked to-do lists in step with Skylight lists."""

    def __init__(self, hass: HomeAssistant, manager: ShipshapeManager, sync: Any) -> None:
        self.hass = hass
        self.manager = manager
        self.sync = sync  # SkylightSync: owns the client, the frame and sign-in state
        self._unsubs: list[CALLBACK_TYPE] = []
        self._debounce: CALLBACK_TYPE | None = None
        self._lock = asyncio.Lock()
        self.last_error: str | None = None

    # ------------------------------------------------------------------
    def links(self) -> list[tuple[str, str, str]]:
        """(key, todo entity id, Skylight list id) for every active link."""
        opts = self.manager.options
        out = []
        for key, enabled, todo, lst in (
            ("grocery", CONF_SKYLIGHT_GROCERY_ENABLED, CONF_SKYLIGHT_GROCERY_TODO, CONF_SKYLIGHT_GROCERY_LIST),
            ("todo", CONF_SKYLIGHT_TODO_ENABLED, CONF_SKYLIGHT_TODO_TODO, CONF_SKYLIGHT_TODO_LIST),
        ):
            if opts.get(enabled) and opts.get(todo) and opts.get(lst):
                out.append((key, str(opts[todo]), str(opts[lst])))
        return out

    @property
    def enabled(self) -> bool:
        return bool(self.sync.signed_in and self.sync.frame and self.links())

    @property
    def _state(self) -> dict[str, Any]:
        return self.manager.data["skylight"].setdefault("lists", {})

    @callback
    def async_start(self) -> None:
        if not self.enabled:
            return
        entities = [todo for _key, todo, _lst in self.links()]
        self._unsubs.append(async_track_state_change_event(self.hass, entities, self._on_change))
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
    def _on_change(self, _event: Event) -> None:
        self._schedule()

    @callback
    def _schedule(self) -> None:
        if self._debounce:
            self._debounce()
        self._debounce = async_call_later(self.hass, DEBOUNCE_SECONDS, self._tick)

    async def _tick(self, _now: datetime) -> None:
        self._debounce = None
        await self.async_sync()

    # ------------------------------------------------------------------
    async def async_sync(self) -> None:
        if not self.enabled or self.sync.needs_login or self.sync.backing_off:
            return
        async with self._lock:
            try:
                remote_lists = {lst["id"]: lst for lst in await self.sync.client().lists(self.sync.frame)}
                for key, todo_entity, list_id in self.links():
                    await self._sync_link(key, todo_entity, list_id, remote_lists.get(list_id))
                self.last_error = None
            except SkylightAuthError as err:
                self.sync.needs_login = True
                self.last_error = str(err)
                _LOGGER.error("Skylight sign-in is no longer valid (%s)", err)
            except SkylightRateLimited as err:
                self.sync.back_off()
                self.last_error = str(err)
                _LOGGER.warning("Skylight list sync paused: %s", err)
            except (SkylightError, asyncio.TimeoutError, OSError) as err:
                self.last_error = str(err)
                _LOGGER.warning("Skylight list sync failed: %s", err)
            finally:
                self.manager.async_save_quietly()

    def _entity(self, entity_id: str) -> Any | None:
        component = self.hass.data.get("todo")
        if component is None:
            return None
        entity = component.get_entity(entity_id)
        if entity is None or not entity.available or entity.todo_items is None:
            return None
        return entity

    async def _sync_link(
        self, key: str, todo_entity: str, list_id: str, remote_list: dict[str, Any] | None
    ) -> None:
        entity = self._entity(todo_entity)
        if entity is None:
            _LOGGER.debug("To-do list %s is not available yet", todo_entity)
            return
        if remote_list is None:
            _LOGGER.warning("Skylight list %s no longer exists; open Shipshape's options to relink", list_id)
            return
        client = self.sync.client()
        frame = self.sync.frame
        link = self._state.setdefault(key, {})
        if link.get("todo") != todo_entity or link.get("list") != list_id:
            # Linked to something else now: start again rather than deleting
            # items because old pairs no longer match.
            link.clear()
            link.update({"todo": todo_entity, "list": list_id, "pairs": {}})
        pairs: dict[str, dict[str, Any]] = link.setdefault("pairs", {})

        ha_items: dict[str, TodoItem] = {i.uid: i for i in entity.todo_items if i.uid}
        remote: dict[str, dict[str, Any]] = {i["id"]: i for i in remote_list["items"]}
        writes = 0

        async def remote_write(coro) -> None:
            nonlocal writes
            await coro
            writes += 1
            await asyncio.sleep(WRITE_PAUSE)

        # --- items both sides already know about --------------------------
        for uid, pair in list(pairs.items()):
            if writes >= MAX_WRITES_PER_RUN:
                break
            here = ha_items.get(uid)
            there = remote.get(pair["sid"])
            if here is None and there is None:
                pairs.pop(uid)
                continue
            if here is None:
                await remote_write(client.delete_list_item(frame, list_id, pair["sid"]))
                remote.pop(pair["sid"], None)
                pairs.pop(uid)
                continue
            if there is None:
                await entity.async_delete_todo_items(uids=[uid])
                ha_items.pop(uid, None)
                pairs.pop(uid)
                continue

            here_status = _status_of(here)
            status = pair.get("status", here_status)
            if here_status != there["status"]:
                if here_status != status and there["status"] == status:
                    status = here_status          # changed here
                elif there["status"] != status and here_status == status:
                    status = there["status"]      # changed on Skylight
                else:
                    status = COMPLETED            # changed on both: done wins
            else:
                status = here_status

            # Names that differ only in capitals or spacing count as the same,
            # so "Butter" here and "butter" there never fight over a rename.
            here_label = here.summary or ""
            label = pair.get("label", here_label)
            if not _same(here_label, there["label"]):
                if not _same(here_label, label) and _same(there["label"], label):
                    label = here_label            # renamed here
                else:
                    label = there["label"]        # renamed on Skylight (or both)
            else:
                label = here_label

            rename_there = not _same(label, there["label"])
            rename_here = not _same(label, here_label)
            if status != there["status"] or rename_there:
                await remote_write(
                    client.update_list_item(
                        frame,
                        list_id,
                        pair["sid"],
                        status=status if status != there["status"] else None,
                        label=label if rename_there else None,
                    )
                )
            if status != here_status or rename_here:
                await entity.async_update_todo_item(
                    item=TodoItem(
                        uid=uid, summary=label if rename_here else here_label, status=_ha_status(status)
                    )
                )
            pair["status"] = status
            pair["label"] = label

        paired_remote = {pair["sid"] for pair in pairs.values()}

        # --- new here: send to Skylight -----------------------------------
        for uid, here in ha_items.items():
            if uid in pairs or writes >= MAX_WRITES_PER_RUN:
                continue
            if _status_of(here) == COMPLETED or not (here.summary or "").strip():
                continue
            label = here.summary.strip()
            candidates = [
                r for r in remote.values()
                if r["id"] not in paired_remote and r["label"].strip().casefold() == label.casefold()
            ]
            candidates.sort(key=lambda r: r["status"] != PENDING)  # prefer one that is still open
            if candidates:
                match = candidates[0]
                if match["status"] != PENDING:
                    await remote_write(client.update_list_item(frame, list_id, match["id"], status=PENDING))
                    match["status"] = PENDING
                sid = match["id"]
            else:
                sid = await client.add_list_item(frame, list_id, label)
                writes += 1
                await asyncio.sleep(WRITE_PAUSE)
            pairs[uid] = {"sid": sid, "label": label, "status": PENDING}
            paired_remote.add(sid)

        # --- new on Skylight: add here ------------------------------------
        for sid, there in remote.items():
            if sid in paired_remote or there["status"] != PENDING or writes >= MAX_WRITES_PER_RUN:
                continue
            label = (there["label"] or "").strip()
            if not label:
                continue
            before = {i.uid for i in entity.todo_items or []}
            await entity.async_create_todo_item(
                item=TodoItem(summary=label, status=TodoItemStatus.NEEDS_ACTION)
            )
            writes += 1
            created = [
                i for i in entity.todo_items or [] if i.uid and i.uid not in before and i.summary == label
            ]
            if created:
                pairs[created[0].uid] = {"sid": sid, "label": label, "status": PENDING}
                paired_remote.add(sid)
            # If the new item cannot be found yet it is paired by name next run.

        if writes >= MAX_WRITES_PER_RUN:
            self._schedule()
