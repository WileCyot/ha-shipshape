"""Reminders for Shipshape: morning digest, actionable pushes, announcements."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .const import (
    ACTION_DONE,
    ACTION_SNOOZE,
    CONF_ANNOUNCE_ENABLED,
    CONF_ANNOUNCE_TARGETS,
    CONF_ANNOUNCE_TIME,
    CONF_DASHBOARD_PATH,
    CONF_DIGEST_ENABLED,
    CONF_DIGEST_TIME,
    CONF_NOTIFY_MAP,
    CONF_PUSH_ENABLED,
    CONF_PUSH_MAX,
    CONF_PUSH_TIME,
    EVENT_CHORE_COMPLETED,
)
from .manager import ShipshapeError, ShipshapeManager

_LOGGER = logging.getLogger(__name__)


def _parse_time(value: Any, fallback: tuple[int, int]) -> tuple[int, int]:
    try:
        parts = str(value).split(":")
        return int(parts[0]) % 24, int(parts[1]) % 60
    except (ValueError, IndexError):
        return fallback


def _late_text(view: dict[str, Any]) -> str:
    late = -view["days_left"]
    if late <= 0:
        return "due today"
    return f"{late} day{'s' if late != 1 else ''} overdue"


class Notifier:
    """Sends the reminders that are switched on in the options."""

    def __init__(self, hass: HomeAssistant, manager: ShipshapeManager) -> None:
        self.hass = hass
        self.manager = manager
        self._unsubs: list[CALLBACK_TYPE] = []
        self._pushed: set[str] = set()

    @callback
    def async_start(self) -> None:
        opts = self.manager.options
        if opts.get(CONF_DIGEST_ENABLED):
            hour, minute = _parse_time(opts.get(CONF_DIGEST_TIME), (7, 30))
            self._unsubs.append(
                async_track_time_change(self.hass, self._digest, hour=hour, minute=minute, second=0)
            )
        if opts.get(CONF_PUSH_ENABLED):
            hour, minute = _parse_time(opts.get(CONF_PUSH_TIME), (18, 0))
            self._unsubs.append(
                async_track_time_change(self.hass, self._push, hour=hour, minute=minute, second=0)
            )
        if opts.get(CONF_ANNOUNCE_ENABLED) and opts.get(CONF_ANNOUNCE_TARGETS):
            hour, minute = _parse_time(opts.get(CONF_ANNOUNCE_TIME), (17, 30))
            self._unsubs.append(
                async_track_time_change(self.hass, self._announce, hour=hour, minute=minute, second=0)
            )
        self._unsubs.append(
            self.hass.bus.async_listen("mobile_app_notification_action", self._handle_action)
        )
        self._unsubs.append(self.hass.bus.async_listen(EVENT_CHORE_COMPLETED, self._handle_completed))

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # ------------------------------------------------------------------
    def service_for(self, person: str) -> str | None:
        """notify service name (without domain) for a person's phone."""
        mapped = (self.manager.options.get(CONF_NOTIFY_MAP) or {}).get(person)
        if mapped:
            name = mapped.split(".", 1)[-1]
            return name if self.hass.services.has_service("notify", name) else None
        state = self.hass.states.get(person)
        if state is None:
            return None
        for tracker in state.attributes.get("device_trackers") or []:
            name = f"mobile_app_{tracker.split('.', 1)[-1]}"
            if self.hass.services.has_service("notify", name):
                return name
        return None

    async def _send(self, service: str, payload: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call("notify", service, payload, blocking=True)
        except Exception as err:  # noqa: BLE001 - a broken phone must not stop the others
            _LOGGER.warning("Shipshape could not notify via notify.%s: %s", service, err)

    def _url(self) -> str:
        return self.manager.options.get(CONF_DASHBOARD_PATH) or "/shipshape-chores"

    # ------------------------------------------------------------------
    async def _digest(self, _now: datetime) -> None:
        await self.async_send_digest()

    async def async_send_digest(self) -> int:
        """One summary push per person. Returns how many were sent."""
        if self.manager.vacation:
            return 0
        sent = 0
        for person in self.manager.participants():
            service = self.service_for(person)
            if service is None:
                continue
            due = self.manager.due_chores(person)
            if not due:
                continue
            overdue = sum(1 for v in due if v["state"] == "overdue")
            lines = [f"• {v['zone']}: {v['name']}" for v in due[:8]]
            if len(due) > 8:
                lines.append(f"…and {len(due) - 8} more")
            title = f"{len(due)} chore{'s' if len(due) != 1 else ''} due"
            if overdue:
                title += f", {overdue} overdue"
            await self._send(
                service,
                {
                    "title": title,
                    "message": "\n".join(lines),
                    "data": {
                        "tag": "shipshape_digest",
                        "group": "shipshape",
                        "url": self._url(),
                        "clickAction": self._url(),
                    },
                },
            )
            sent += 1
        return sent

    async def _push(self, _now: datetime) -> None:
        await self.async_send_pushes()

    async def async_send_pushes(self) -> int:
        """Actionable Done/Snooze pushes for the most urgent chores per person."""
        if self.manager.vacation:
            return 0
        limit = int(self.manager.options.get(CONF_PUSH_MAX) or 3)
        sent = 0
        for person in self.manager.participants():
            service = self.service_for(person)
            if service is None:
                continue
            for view in self.manager.due_chores(person)[:limit]:
                self._pushed.add(view["id"])
                await self._send(
                    service,
                    {
                        "title": f"{view['zone']}: {view['name']}",
                        "message": f"{_late_text(view).capitalize()} · {view['schedule_label'].lower()}",
                        "data": {
                            "tag": f"shipshape_{view['id']}",
                            "group": "shipshape",
                            "url": self._url(),
                            "clickAction": self._url(),
                            "actions": [
                                {"action": f"{ACTION_DONE}{view['id']}", "title": "Done"},
                                {"action": f"{ACTION_SNOOZE}{view['id']}", "title": "Snooze 1 day"},
                            ],
                        },
                    },
                )
                sent += 1
        return sent

    async def _announce(self, _now: datetime) -> None:
        await self.async_announce()

    async def async_announce(self) -> bool:
        """Speak a short summary on the configured speakers."""
        if self.manager.vacation:
            return False
        due = self.manager.due_chores()
        if not due:
            return False
        names = [f"{v['zone']}, {v['name']}" for v in due[:3]]
        message = (
            f"Chore check. {len(due)} chore{'s are' if len(due) != 1 else ' is'} due. "
            f"Top of the list: {'; '.join(names)}."
        )
        for target in self.manager.options.get(CONF_ANNOUNCE_TARGETS) or []:
            service = str(target).split(".", 1)[-1]
            if not self.hass.services.has_service("notify", service):
                _LOGGER.warning("Shipshape announce target notify.%s does not exist", service)
                continue
            payload: dict[str, Any] = {"message": message}
            if service.startswith("alexa_media"):
                payload["data"] = {"type": "announce"}
            await self._send(service, payload)
        return True

    # ------------------------------------------------------------------
    @callback
    def _handle_action(self, event: Event) -> None:
        action = str(event.data.get("action") or "")
        by = self.manager.person_for_user(event.context.user_id)
        try:
            if action.startswith(ACTION_DONE):
                self.manager.complete_chore(action[len(ACTION_DONE) :], by=by, source="notification")
            elif action.startswith(ACTION_SNOOZE):
                self.manager.snooze_chore(action[len(ACTION_SNOOZE) :], 1)
                self.hass.async_create_task(self._clear(action[len(ACTION_SNOOZE) :]))
        except ShipshapeError as err:
            _LOGGER.debug("Ignoring notification action %s: %s", action, err)

    @callback
    def _handle_completed(self, event: Event) -> None:
        chore_id = event.data.get("chore_id")
        if chore_id in self._pushed:
            self.hass.async_create_task(self._clear(chore_id))

    async def _clear(self, chore_id: str) -> None:
        """Remove a chore's push from every phone once it is handled."""
        self._pushed.discard(chore_id)
        for person in self.manager.participants():
            service = self.service_for(person)
            if service is not None:
                await self._send(
                    service,
                    {"message": "clear_notification", "data": {"tag": f"shipshape_{chore_id}"}},
                )
