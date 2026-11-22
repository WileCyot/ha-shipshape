"""State manager for Shipshape: storage, mutations and snapshots."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
import secrets
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_PARTICIPANTS,
    DEFAULTS,
    DOMAIN,
    EVENT_CHORE_COMPLETED,
    HISTORY_LIMIT,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .models import (
    ScheduleError,
    approx_interval_days,
    chore_status,
    completion_timestamp,
    normalize_schedule,
    parse_date,
    parse_dt,
    schedule_label,
    staggered_last_done,
)

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 5


class ShipshapeError(HomeAssistantError):
    """A user-facing Shipshape error."""


def _new_id() -> str:
    return secrets.token_hex(5)


def _clean_str(value: Any, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


class ShipshapeManager:
    """Owns all Shipshape data."""

    def __init__(self, hass: HomeAssistant, options: dict[str, Any]) -> None:
        self.hass = hass
        self.options: dict[str, Any] = {**DEFAULTS, **options}
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, Any] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._trigger_unsub: CALLBACK_TYPE | None = None
        self._snap: tuple[float, dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self.data = {
            "zones": stored.get("zones", {}),
            "chores": stored.get("chores", {}),
            "history": stored.get("history", []),
            "vacation": stored.get("vacation", {"active": False, "since": None}),
            "calendar": stored.get("calendar", {"events": {}, "skip": {}}),
            "skylight": stored.get("skylight", {"chores": {}}),
        }
        self.data["calendar"].setdefault("events", {})
        self.data["calendar"].setdefault("skip", {})
        self.data["skylight"].setdefault("chores", {})

    @callback
    def async_start(self) -> None:
        """Start timers and entity triggers."""
        self._unsubs.append(
            async_track_time_interval(self.hass, self._handle_tick, timedelta(minutes=10))
        )
        self._unsubs.append(
            async_track_time_change(self.hass, self._handle_tick, hour=0, minute=0, second=10)
        )
        self._rebuild_triggers()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._trigger_unsub:
            self._trigger_unsub()
            self._trigger_unsub = None

    async def async_flush(self) -> None:
        await self._store.async_save(self.data)

    @callback
    def _handle_tick(self, _now: datetime) -> None:
        self._notify()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def _notify(self) -> None:
        self._snap = None
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - one bad listener must not break the rest
                _LOGGER.exception("Shipshape listener failed")

    @callback
    def _changed(self) -> None:
        """Persist and tell everyone."""
        self._store.async_delay_save(lambda: self.data, SAVE_DELAY)
        self._notify()

    @callback
    def async_save_quietly(self) -> None:
        """Persist bookkeeping (sync maps) without waking listeners."""
        self._store.async_delay_save(lambda: self.data, SAVE_DELAY)

    # ------------------------------------------------------------------
    # time
    # ------------------------------------------------------------------
    def now(self) -> datetime:
        """Effective clock: frozen while vacation mode is on."""
        vac = self.data.get("vacation") or {}
        if vac.get("active"):
            since = parse_dt(vac.get("since"))
            if since is not None:
                return dt_util.as_local(since)
        return dt_util.now()

    @property
    def vacation(self) -> bool:
        return bool((self.data.get("vacation") or {}).get("active"))

    # ------------------------------------------------------------------
    # people
    # ------------------------------------------------------------------
    def participants(self) -> list[str]:
        chosen = [p for p in self.options.get(CONF_PARTICIPANTS) or [] if self.hass.states.get(p)]
        if chosen:
            return chosen
        return sorted(state.entity_id for state in self.hass.states.async_all("person"))

    def person_name(self, person: str | None) -> str | None:
        if not person:
            return None
        state = self.hass.states.get(person)
        if state is None:
            return person.split(".", 1)[-1].replace("_", " ").title()
        return state.name

    def person_for_user(self, user_id: str | None) -> str | None:
        if not user_id:
            return None
        for state in self.hass.states.async_all("person"):
            if state.attributes.get("user_id") == user_id:
                return state.entity_id
        return None

    def responsible(self, chore: dict[str, Any]) -> list[str]:
        """People currently on the hook for a chore ([] means anyone)."""
        assignees = [a for a in chore.get("assignees") or [] if a]
        if not assignees:
            return []
        if chore.get("rotate"):
            return [assignees[int(chore.get("rot_index", 0)) % len(assignees)]]
        return assignees

    # ------------------------------------------------------------------
    # zones
    # ------------------------------------------------------------------
    def _zone(self, zone_id: str) -> dict[str, Any]:
        zone = self.data["zones"].get(zone_id)
        if zone is None:
            raise ShipshapeError(f"Unknown zone: {zone_id}")
        return zone

    def find_zone(self, name: str) -> dict[str, Any] | None:
        wanted = name.strip().casefold()
        for zone in self.data["zones"].values():
            if zone["name"].casefold() == wanted or zone["id"] == name:
                return zone
        return None

    @callback
    def save_zone(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create (no id) or update a zone."""
        zone_id = payload.get("id")
        if zone_id:
            zone = self._zone(zone_id)
        else:
            zone = {
                "id": _new_id(),
                "name": "",
                "icon": "mdi:home",
                "area_id": None,
                "order": len(self.data["zones"]),
            }
        if "name" in payload or not zone_id:
            name = _clean_str(payload.get("name"), 60)
            if not name:
                raise ShipshapeError("A zone needs a name")
            clash = self.find_zone(name)
            if clash is not None and clash["id"] != zone["id"]:
                raise ShipshapeError(f"A zone called {name} already exists")
            zone["name"] = name
        if "icon" in payload:
            zone["icon"] = _clean_str(payload.get("icon"), 60) or "mdi:home"
        if "area_id" in payload or "area" in payload:
            zone["area_id"] = payload.get("area_id", payload.get("area")) or None
        if "order" in payload:
            zone["order"] = int(payload["order"])
        self.data["zones"][zone["id"]] = zone
        self._changed()
        return zone

    @callback
    def remove_zone(self, zone_id: str) -> None:
        self._zone(zone_id)
        for chore_id in [c["id"] for c in self.data["chores"].values() if c["zone_id"] == zone_id]:
            self.data["chores"].pop(chore_id, None)
        self.data["zones"].pop(zone_id)
        self._rebuild_triggers()
        self._changed()

    # ------------------------------------------------------------------
    # chores
    # ------------------------------------------------------------------
    def _chore(self, chore_id: str) -> dict[str, Any]:
        chore = self.data["chores"].get(chore_id)
        if chore is None:
            raise ShipshapeError(f"Unknown chore: {chore_id}")
        return chore

    def find_chore(self, name: str, zone: str | None = None) -> dict[str, Any] | None:
        wanted = name.strip().casefold()
        zone_id = None
        if zone:
            found = self.find_zone(zone)
            if found is None:
                return None
            zone_id = found["id"]
        matches = [
            c
            for c in self.data["chores"].values()
            if c["name"].casefold() == wanted and (zone_id is None or c["zone_id"] == zone_id)
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _clean_trigger(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict) or not raw.get("entity_id"):
            return None
        action = raw.get("action") if raw.get("action") in ("complete", "make_due") else "complete"
        return {
            "entity_id": str(raw["entity_id"]),
            "to": _clean_str(raw.get("to"), 60),
            "from": _clean_str(raw.get("from"), 60),
            "action": action,
        }

    @callback
    def save_chore(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create (no id) or update a chore."""
        chore_id = payload.get("id")
        creating = not chore_id
        if creating:
            chore: dict[str, Any] = {
                "id": _new_id(),
                "zone_id": None,
                "name": "",
                "schedule": {"kind": "interval", "every": 1, "unit": "weeks"},
                "last_done": None,
                "last_done_by": None,
                "created": dt_util.now().isoformat(),
                "assignees": [],
                "rotate": False,
                "rot_index": 0,
                "effort": 1,
                "paused": False,
                "snooze_until": None,
                "force_due": False,
                "trigger": None,
                "notes": "",
            }
        else:
            chore = self._chore(chore_id)

        if "zone_id" in payload or creating:
            zone_id = payload.get("zone_id")
            self._zone(zone_id or "")
            chore["zone_id"] = zone_id
        if "name" in payload or creating:
            name = _clean_str(payload.get("name"))
            if not name:
                raise ShipshapeError("A chore needs a name")
            chore["name"] = name
        if "schedule" in payload:
            try:
                chore["schedule"] = normalize_schedule(payload["schedule"])
            except ScheduleError as err:
                raise ShipshapeError(str(err)) from err
        if "assignees" in payload:
            chore["assignees"] = [str(a) for a in payload.get("assignees") or [] if a]
            chore["rot_index"] = 0
        if "rotate" in payload:
            chore["rotate"] = bool(payload["rotate"])
        if "effort" in payload:
            chore["effort"] = min(3, max(1, int(payload.get("effort") or 1)))
        if "paused" in payload:
            chore["paused"] = bool(payload["paused"])
        if "notes" in payload:
            chore["notes"] = _clean_str(payload.get("notes"), 500)
        if "trigger" in payload:
            chore["trigger"] = self._clean_trigger(payload.get("trigger"))
        if "last_done" in payload:
            raw = payload.get("last_done")
            if not raw:
                chore["last_done"] = None
            else:
                parsed = parse_dt(raw)
                if parsed is None:
                    day = parse_date(raw)
                    if day is None:
                        raise ShipshapeError("last_done is not a date")
                    parsed = datetime(day.year, day.month, day.day, 12, 0)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                if parsed > dt_util.now():
                    parsed = dt_util.now()
                chore["last_done"] = parsed.isoformat()
            chore["snooze_until"] = None
            chore["force_due"] = False
        elif creating and payload.get("condition") is not None:
            fraction = float(payload["condition"])
            chore["last_done"] = staggered_last_done(
                chore["schedule"], dt_util.now(), fraction
            ).isoformat()

        self.data["chores"][chore["id"]] = chore
        self._rebuild_triggers()
        self._changed()
        return chore

    @callback
    def remove_chore(self, chore_id: str) -> None:
        self._chore(chore_id)
        self.data["chores"].pop(chore_id)
        self._rebuild_triggers()
        self._changed()

    @callback
    def complete_chore(
        self,
        chore_id: str,
        by: str | None = None,
        when: datetime | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        """Mark a chore done and return the history entry."""
        chore = self._chore(chore_id)
        now = when or dt_util.now()
        if by is None:
            responsible = self.responsible(chore)
            if len(responsible) == 1 and source in ("manual", "notification", "todo"):
                by = responsible[0]
        stamp = completion_timestamp(chore, now)
        zone = self.data["zones"].get(chore["zone_id"], {})
        entry = {
            "id": _new_id(),
            "chore_id": chore_id,
            "chore": chore["name"],
            "zone_id": chore["zone_id"],
            "zone": zone.get("name", ""),
            "at": now.isoformat(),
            "by": by,
            "points": int(chore.get("effort", 1)),
            "source": source,
            "prev": {
                "last_done": chore.get("last_done"),
                "last_done_by": chore.get("last_done_by"),
                "rot_index": chore.get("rot_index", 0),
                "snooze_until": chore.get("snooze_until"),
                "force_due": chore.get("force_due", False),
            },
        }
        chore["last_done"] = stamp.isoformat()
        chore["last_done_by"] = by
        chore["snooze_until"] = None
        chore["force_due"] = False
        assignees = chore.get("assignees") or []
        if chore.get("rotate") and assignees:
            chore["rot_index"] = (int(chore.get("rot_index", 0)) + 1) % len(assignees)
        history: list[dict[str, Any]] = self.data["history"]
        history.append(entry)
        if len(history) > HISTORY_LIMIT:
            del history[: len(history) - HISTORY_LIMIT]
        self.hass.bus.async_fire(
            EVENT_CHORE_COMPLETED,
            {
                "chore_id": chore_id,
                "chore": chore["name"],
                "zone": entry["zone"],
                "by": by,
                "by_name": self.person_name(by),
                "points": entry["points"],
                "source": source,
            },
        )
        self._changed()
        return entry

    @callback
    def undo(self, history_id: str | None = None) -> dict[str, Any]:
        """Undo a completion (the latest one when no id is given)."""
        history: list[dict[str, Any]] = self.data["history"]
        if not history:
            raise ShipshapeError("Nothing to undo")
        if history_id is None:
            entry = history[-1]
        else:
            entry = next((h for h in history if h["id"] == history_id), None)
            if entry is None:
                raise ShipshapeError("That completion is no longer in the history")
        chore = self.data["chores"].get(entry["chore_id"])
        if chore is not None:
            later = [
                h for h in history if h["chore_id"] == entry["chore_id"] and h["at"] > entry["at"]
            ]
            if not later:
                chore.update(entry.get("prev") or {})
        history.remove(entry)
        self._changed()
        return entry

    @callback
    def snooze_chore(self, chore_id: str, days: int = 1) -> dict[str, Any]:
        chore = self._chore(chore_id)
        days = min(365, max(1, int(days)))
        chore["snooze_until"] = (dt_util.now().date() + timedelta(days=days)).isoformat()
        self._changed()
        return chore

    @callback
    def make_due(self, chore_id: str) -> dict[str, Any]:
        chore = self._chore(chore_id)
        chore["force_due"] = True
        chore["snooze_until"] = None
        self._changed()
        return chore

    # ------------------------------------------------------------------
    # vacation
    # ------------------------------------------------------------------
    @callback
    def set_vacation(self, active: bool) -> None:
        """Freeze or resume every chore's clock."""
        vac = self.data["vacation"]
        if active == bool(vac.get("active")):
            return
        if active:
            vac["active"] = True
            vac["since"] = dt_util.now().isoformat()
        else:
            since = parse_dt(vac.get("since"))
            vac["active"] = False
            vac["since"] = None
            if since is not None:
                delta = dt_util.now() - since
                for chore in self.data["chores"].values():
                    last = parse_dt(chore.get("last_done"))
                    if last is not None:
                        chore["last_done"] = (last + delta).isoformat()
                    snooze = parse_date(chore.get("snooze_until"))
                    if snooze is not None:
                        chore["snooze_until"] = (snooze + timedelta(days=delta.days)).isoformat()
        self._changed()

    # ------------------------------------------------------------------
    # import / export
    # ------------------------------------------------------------------
    @callback
    def import_data(
        self, payload: dict[str, Any], replace: bool = False, stagger: bool = True
    ) -> dict[str, int]:
        """Load zones and chores.

        ``payload`` is {"zones": [{"name", "icon", "area", "chores": [...]}]}.
        Existing zones are matched by name; chores already present in a zone
        (same name) are left alone unless ``replace`` is set, which wipes
        everything first.
        """
        zones_in = payload.get("zones")
        if not isinstance(zones_in, list):
            raise ShipshapeError("Import needs a 'zones' list")
        # Validate everything before touching stored data.
        prepared: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for zone_in in zones_in:
            if not isinstance(zone_in, dict) or not _clean_str(zone_in.get("name")):
                raise ShipshapeError("Every zone needs a name")
            chores: list[dict[str, Any]] = []
            for chore_in in zone_in.get("chores") or []:
                if not isinstance(chore_in, dict) or not _clean_str(chore_in.get("name")):
                    raise ShipshapeError(f"A chore in {zone_in['name']} has no name")
                try:
                    schedule = normalize_schedule(chore_in.get("schedule") or chore_in)
                except ScheduleError as err:
                    raise ShipshapeError(
                        f"{zone_in['name']} / {chore_in['name']}: {err}"
                    ) from err
                chores.append({**chore_in, "schedule": schedule})
            prepared.append((zone_in, chores))

        if replace:
            self.data["zones"] = {}
            self.data["chores"] = {}
            self.data["calendar"]["skip"] = {}

        now = dt_util.now()
        added_zones = added_chores = 0
        index = 0
        for zone_in, chores in prepared:
            zone = self.find_zone(zone_in["name"])
            if zone is None:
                zone = {
                    "id": _new_id(),
                    "name": _clean_str(zone_in["name"], 60),
                    "icon": _clean_str(zone_in.get("icon"), 60) or "mdi:home",
                    "area_id": zone_in.get("area") or zone_in.get("area_id") or None,
                    "order": len(self.data["zones"]),
                }
                self.data["zones"][zone["id"]] = zone
                added_zones += 1
            existing = {
                c["name"].casefold()
                for c in self.data["chores"].values()
                if c["zone_id"] == zone["id"]
            }
            for chore_in in chores:
                name = _clean_str(chore_in["name"])
                if name.casefold() in existing:
                    continue
                schedule = chore_in["schedule"]
                last_done = chore_in.get("last_done")
                if last_done:
                    parsed = parse_dt(last_done)
                    if parsed is not None and parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                    last_done = parsed.isoformat() if parsed else None
                elif schedule["kind"] == "manual":
                    last_done = None
                elif stagger:
                    # Deterministic spread between 10% and 90% of the interval.
                    fraction = 0.1 + ((index * 37) % 81) / 100
                    last_done = staggered_last_done(schedule, now, fraction).isoformat()
                index += 1
                chore = {
                    "id": _new_id(),
                    "zone_id": zone["id"],
                    "name": name,
                    "schedule": schedule,
                    "last_done": last_done,
                    "last_done_by": None,
                    "created": now.isoformat(),
                    "assignees": [str(a) for a in chore_in.get("assignees") or []],
                    "rotate": bool(chore_in.get("rotate", False)),
                    "rot_index": 0,
                    "effort": min(3, max(1, int(chore_in.get("effort", 1) or 1))),
                    "paused": bool(chore_in.get("paused", False)),
                    "snooze_until": None,
                    "force_due": False,
                    "trigger": self._clean_trigger(chore_in.get("trigger")),
                    "notes": _clean_str(chore_in.get("notes"), 500),
                }
                self.data["chores"][chore["id"]] = chore
                existing.add(name.casefold())
                added_chores += 1
        self._rebuild_triggers()
        self._changed()
        return {"zones": added_zones, "chores": added_chores}

    def export_data(self) -> dict[str, Any]:
        zones = []
        for zone in sorted(self.data["zones"].values(), key=lambda z: z.get("order", 0)):
            chores = []
            for chore in self.data["chores"].values():
                if chore["zone_id"] != zone["id"]:
                    continue
                schedule = chore["schedule"]
                item: dict[str, Any] = {"name": chore["name"]}
                if schedule["kind"] == "months":
                    item["months"] = schedule["months"]
                elif schedule["kind"] == "manual":
                    item["on_demand"] = True
                else:
                    item["every"] = schedule["every"]
                    item["unit"] = schedule["unit"]
                for key in ("last_done", "assignees", "rotate", "effort", "paused", "notes", "trigger"):
                    if chore.get(key):
                        item[key] = chore[key]
                chores.append(item)
            zones.append(
                {
                    "name": zone["name"],
                    "icon": zone.get("icon"),
                    "area": zone.get("area_id"),
                    "chores": sorted(chores, key=lambda c: c["name"].casefold()),
                }
            )
        return {"zones": zones}

    # ------------------------------------------------------------------
    # entity triggers (auto-complete / auto-due)
    # ------------------------------------------------------------------
    @callback
    def _rebuild_triggers(self) -> None:
        if self._trigger_unsub:
            self._trigger_unsub()
            self._trigger_unsub = None
        entities = sorted(
            {
                c["trigger"]["entity_id"]
                for c in self.data.get("chores", {}).values()
                if c.get("trigger")
            }
        )
        if entities:
            self._trigger_unsub = async_track_state_change_event(
                self.hass, entities, self._handle_trigger
            )

    @callback
    def _handle_trigger(self, event: Event) -> None:
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        if new is None or old is None or new.state == old.state:
            return
        if old.state in ("unavailable", "unknown"):
            return
        entity_id = event.data.get("entity_id")
        for chore in list(self.data["chores"].values()):
            trig = chore.get("trigger")
            if not trig or trig["entity_id"] != entity_id:
                continue
            if trig.get("to") and new.state != trig["to"]:
                continue
            if trig.get("from") and old.state != trig["from"]:
                continue
            if self.vacation:
                continue
            if trig.get("action") == "make_due":
                self.make_due(chore["id"])
            else:
                self.complete_chore(chore["id"], source="trigger")

    # ------------------------------------------------------------------
    # read side
    # ------------------------------------------------------------------
    def chore_view(self, chore: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        """A chore with its computed status merged in."""
        status = chore_status(chore, now or self.now())
        zone = self.data["zones"].get(chore["zone_id"], {})
        view = {k: v for k, v in chore.items()}
        view.update(status)
        if self.vacation:
            view["is_due"] = False
        view["zone"] = zone.get("name", "")
        view["zone_icon"] = zone.get("icon", "mdi:home")
        view["schedule_label"] = schedule_label(chore["schedule"])
        view["responsible"] = self.responsible(chore)
        view["interval_days"] = round(approx_interval_days(chore["schedule"]), 1)
        return view

    def chore_views(self) -> list[dict[str, Any]]:
        now = self.now()
        views = [self.chore_view(c, now) for c in self.data["chores"].values()]
        views.sort(key=lambda v: (-v["ratio"], v["zone"], v["name"]))
        return views

    def due_chores(self, person: str | None = None) -> list[dict[str, Any]]:
        """Due chores, most urgent first; optionally only those a person owns."""
        if self.vacation:
            return []
        out = []
        for view in self.chore_views():
            if not view["is_due"]:
                continue
            if person is not None and view["responsible"] and person not in view["responsible"]:
                continue
            out.append(view)
        return out

    def points(self, person: str, days: int) -> tuple[int, int]:
        """(points, completions) for a person over the trailing ``days``."""
        cutoff = dt_util.now() - timedelta(days=days)
        pts = count = 0
        for entry in reversed(self.data["history"]):
            at = parse_dt(entry.get("at"))
            if at is None:
                continue
            if at < cutoff:
                break
            if entry.get("by") == person:
                pts += int(entry.get("points", 1))
                count += 1
        return pts, count

    def snapshot(self) -> dict[str, Any]:
        """Everything the dashboard card needs (cached briefly between changes)."""
        if self._snap is not None and self.hass.loop.time() - self._snap[0] < 60:
            return self._snap[1]
        snap = self._build_snapshot()
        self._snap = (self.hass.loop.time(), snap)
        return snap

    def _build_snapshot(self) -> dict[str, Any]:
        views = self.chore_views()
        zones = []
        for zone in sorted(self.data["zones"].values(), key=lambda z: (z.get("order", 0), z["name"])):
            mine = [v for v in views if v["zone_id"] == zone["id"]]
            active = [v for v in mine if v["state"] != "paused"]
            due = sum(1 for v in active if v["state"] in ("due", "overdue"))
            overdue = sum(1 for v in active if v["state"] == "overdue")
            zones.append(
                {
                    **zone,
                    "total": len(mine),
                    "due": due,
                    "overdue": overdue,
                    "on_track": round(100 * (len(active) - due) / len(active)) if active else 100,
                    "worst": max((v["ratio"] for v in active), default=0),
                }
            )
        active_all = [v for v in views if v["state"] != "paused"]
        due_all = sum(1 for v in active_all if v["state"] in ("due", "overdue"))
        people = []
        for person in self.participants():
            state = self.hass.states.get(person)
            p7, c7 = self.points(person, 7)
            p30, c30 = self.points(person, 30)
            people.append(
                {
                    "id": person,
                    "name": self.person_name(person),
                    "picture": state.attributes.get("entity_picture") if state else None,
                    "points_7d": p7,
                    "done_7d": c7,
                    "points_30d": p30,
                    "done_30d": c30,
                    "due": sum(
                        1
                        for v in active_all
                        if v["state"] in ("due", "overdue")
                        and (not v["responsible"] or person in v["responsible"])
                    ),
                }
            )
        recent = [
            {k: v for k, v in entry.items() if k != "prev"} | {"by_name": self.person_name(entry.get("by"))}
            for entry in self.data["history"][-25:][::-1]
        ]
        return {
            "now": dt_util.now().isoformat(),
            "vacation": dict(self.data["vacation"]),
            "zones": zones,
            "chores": views,
            "people": people,
            "recent": recent,
            "summary": {
                "total": len(views),
                "due": due_all,
                "overdue": sum(1 for v in active_all if v["state"] == "overdue"),
                "on_track": round(100 * (len(active_all) - due_all) / len(active_all))
                if active_all
                else 100,
            },
        }


def get_manager(hass: HomeAssistant) -> ShipshapeManager:
    manager = hass.data.get(DOMAIN, {}).get("manager")
    if manager is None:
        raise ShipshapeError("Shipshape is not set up")
    return manager
