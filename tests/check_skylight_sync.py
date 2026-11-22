"""Scenario check for the Skylight sync against a fake Skylight.

Needs Home Assistant importable, so run it inside a Home Assistant container:

    docker run --rm --entrypoint python3 -e PYTHONPATH=/repo -v <repo>:/repo \
        homeassistant/home-assistant:<version> /repo/tests/check_skylight_sync.py
"""

import asyncio
from datetime import timedelta
import sys

from homeassistant.util import dt as dt_util

from custom_components.shipshape import skylight_sync
from custom_components.shipshape.manager import ShipshapeError
from custom_components.shipshape.skylight import SkylightError

skylight_sync.WRITE_PAUSE = 0

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name, "" if cond else detail)
    if not cond:
        FAILED.append(name)


class FakeSkylight:
    """Remembers chores the way the real API would."""

    def __init__(self):
        self.items = {}
        self.n = 100
        self.calls = []
        self.fail_delete = False

    async def chores(self, frame, after, before):
        self.calls.append(("list", after, before))
        return [dict(v) for v in self.items.values()]

    async def create_chore(self, frame, summary, start, category_id=None, reward_points=None,
                           up_for_grabs=False):
        self.n += 1
        sid = str(self.n)
        self.items[sid] = {"id": sid, "summary": summary, "status": "pending", "start": start,
                           "category_id": category_id, "completed_category_id": None,
                           "up_for_grabs": up_for_grabs, "reward_points": reward_points}
        self.calls.append(("create", sid))
        return sid

    async def set_chore_status(self, frame, chore_id, status="complete", category_id=None):
        self.items[chore_id]["status"] = status
        self.items[chore_id]["completed_category_id"] = (
            (category_id or self.items[chore_id]["category_id"]) if status == "complete" else None
        )
        self.calls.append(("status", chore_id, status, category_id))

    async def delete_chore(self, frame, chore_id):
        self.calls.append(("delete", chore_id))
        if self.fail_delete:
            raise SkylightError("boom")
        self.items.pop(chore_id, None)


class FakeManager:
    def __init__(self):
        self.options = {"skylight_enabled": True, "skylight_frame": "1", "skylight_default_profile": "9",
                        "skylight_profile_map": {"person.alex": "7", "person.sam": "8"},
                        "skylight_up_for_grabs": True, "skylight_stars": 2}
        self.data = {"chores": {}, "history": [], "skylight": {"chores": {}, "auth": {"access_token": "x"}}}
        self.vacation = False
        self._h = 0

    def add(self, cid, due=True, effort=1, responsible=()):
        self.data["chores"][cid] = {"id": cid, "name": cid.title(), "due": due, "snooze_until": None,
                                    "effort": effort, "responsible": list(responsible)}

    def due_chores(self, person=None):
        if self.vacation:
            return []
        return [{"id": c["id"], "zone": "Zone", "name": c["name"], "responsible": c["responsible"],
                 "effort": c["effort"]}
                for c in self.data["chores"].values() if c["due"] and not c["snooze_until"]]

    def complete_chore(self, chore_id, by=None, when=None, source="manual"):
        self._h += 1
        chore = self.data["chores"][chore_id]
        entry = {"id": f"h{self._h}", "chore_id": chore_id, "by": by, "source": source, "prev_due": chore["due"]}
        chore["due"] = False
        self.data["history"].append(entry)
        return entry

    def undo(self, history_id=None):
        entry = next((h for h in self.data["history"] if h["id"] == history_id), None)
        if entry is None:
            raise ShipshapeError("gone")
        self.data["chores"][entry["chore_id"]]["due"] = entry["prev_due"]
        self.data["history"].remove(entry)
        return entry

    def make_due(self, chore_id):
        self.data["chores"][chore_id]["due"] = True

    def snooze_chore(self, chore_id, days=1):
        self.data["chores"][chore_id]["snooze_until"] = "tomorrow"

    def async_save_quietly(self):
        pass


class FakeHass:
    loop = None


async def main():
    hass = FakeHass()
    hass.loop = asyncio.get_running_loop()
    mgr = FakeManager()
    sky = FakeSkylight()
    sync = skylight_sync.SkylightSync(hass, mgr)
    sync.client = lambda: sky
    mapped = lambda: mgr.data["skylight"]["chores"]
    done = lambda: mgr.data["skylight"].get("done", {})
    creates = lambda: [c for c in sky.calls if c[0] == "create"]

    print("1. due chore is created on Skylight")
    mgr.add("sink")
    await sync.async_sync()
    a = mapped()["sink"]["sid"]
    check("created and mapped", a in sky.items and len(creates()) == 1)
    await sync.async_sync()
    check("second sync creates nothing", len(creates()) == 1)

    print("2. ticked on Skylight -> completed here")
    sky.items[a]["status"] = "complete"
    sky.items[a]["completed_category_id"] = "7"
    await sync.async_sync()
    check("completed here", not mgr.data["chores"]["sink"]["due"])
    check("credited through the profile map", mgr.data["history"][-1]["by"] == "person.alex", mgr.data["history"][-1])
    check("no longer mapped, now watched", "sink" not in mapped() and done()["sink"]["sid"] == a, done())

    print("3. un-ticked on Skylight -> reopened here, same Skylight chore reused")
    sky.items[a]["status"] = "pending"
    await sync.async_sync()
    check("reopened here", mgr.data["chores"]["sink"]["due"])
    check("completion removed from history", mgr.data["history"] == [], mgr.data["history"])
    check("mapped to the same Skylight chore", mapped().get("sink", {}).get("sid") == a, mapped())
    check("no duplicate created", len(creates()) == 1 and len(sky.items) == 1, sky.items)
    await sync.async_sync()
    check("stable on the next sync", len(sky.items) == 1 and mgr.data["chores"]["sink"]["due"])

    print("4. completed here -> ticked on Skylight")
    mgr.complete_chore("sink", by="person.alex")
    await sync.async_sync()
    check("ticked on Skylight", sky.items[a]["status"] == "complete")
    check("watched for an un-tick", done()["sink"]["history_id"] == mgr.data["history"][-1]["id"], done())
    await sync.async_sync()
    check("stays done on the next sync", not mgr.data["chores"]["sink"]["due"] and sky.items[a]["status"] == "complete")

    print("5. un-ticked on Skylight after completing here -> reopened here")
    sky.items[a]["status"] = "pending"
    await sync.async_sync()
    check("reopened here", mgr.data["chores"]["sink"]["due"] and mgr.data["history"] == [])
    check("same Skylight chore, no duplicate", mapped()["sink"]["sid"] == a and len(sky.items) == 1)

    print("6. finished chore comes due again, then the old one is un-ticked -> duplicate removed")
    sky.items[a]["status"] = "complete"
    await sync.async_sync()                      # completes here, watches A
    mgr.make_due("sink")
    await sync.async_sync()                      # creates B
    b = mapped()["sink"]["sid"]
    check("a new Skylight chore was created", b != a and len(sky.items) == 2)
    history_before = list(mgr.data["history"])
    sky.items[a]["status"] = "pending"           # person un-ticks the old one
    await sync.async_sync()
    check("old duplicate removed from Skylight", a not in sky.items and b in sky.items, sky.items)
    check("still due here, history untouched", mgr.data["chores"]["sink"]["due"] and mgr.data["history"] == history_before)
    check("still mapped to the new one", mapped()["sink"]["sid"] == b)

    print("7. un-tick arrives before the re-create -> old chore adopted, nothing created")
    sky.items[b]["status"] = "complete"
    await sync.async_sync()                      # completes here, watches B
    n = len(creates())
    mgr.make_due("sink")
    sky.items[b]["status"] = "pending"           # both happen before the next sync
    await sync.async_sync()
    check("adopted the existing Skylight chore", mapped()["sink"]["sid"] == b and len(creates()) == n, mapped())

    print("8. history entry gone -> falls back to making it due")
    sky.items[b]["status"] = "complete"
    await sync.async_sync()
    mgr.data["history"].clear()
    sky.items[b]["status"] = "pending"
    await sync.async_sync()
    check("reopened without a history entry", mgr.data["chores"]["sink"]["due"] and mapped()["sink"]["sid"] == b)

    print("9. failed duplicate delete is survivable")
    sky.items[b]["status"] = "complete"
    await sync.async_sync()
    mgr.make_due("sink")
    await sync.async_sync()
    c = mapped()["sink"]["sid"]
    sky.fail_delete = True
    sky.items[b]["status"] = "pending"
    await sync.async_sync()
    check("sync carried on", sync.last_error is None and mapped()["sink"]["sid"] == c, sync.last_error)
    sky.fail_delete = False

    print("10. watched chores are forgotten after a day")
    sky.items[c]["status"] = "complete"
    await sync.async_sync()
    done()["sink"]["day"] = (dt_util.now().date() - timedelta(days=2)).isoformat()
    sky.items[c]["status"] = "pending"
    await sync.async_sync()
    check("old un-tick ignored", not mgr.data["chores"]["sink"]["due"] and "sink" not in done())

    print("11. vacation leaves Skylight alone")
    mgr.add("oven")
    await sync.async_sync()
    o = mapped()["oven"]["sid"]
    calls = len(sky.calls)
    mgr.vacation = True
    await sync.async_sync()
    check("no API calls during vacation", len(sky.calls) == calls and sky.items[o]["status"] == "pending")
    mgr.vacation = False

    print("12. deleted on Skylight -> snoozed here after two misses")
    del sky.items[o]
    await sync.async_sync()
    check("first miss does nothing", "oven" in mapped() and not mgr.data["chores"]["oven"]["snooze_until"])
    await sync.async_sync()
    check("second miss snoozes", "oven" not in mapped() and mgr.data["chores"]["oven"]["snooze_until"])

    print("13. unassigned chores go up for grabs with stars; assigned ones go to the profile")
    mgr.add("mop", effort=3)
    mgr.add("bins", effort=1, responsible=["person.sam"])
    await sync.async_sync()
    mop = sky.items[mapped()["mop"]["sid"]]
    bins = sky.items[mapped()["bins"]["sid"]]
    check("unassigned is up for grabs", mop["up_for_grabs"] and mop["category_id"] is None, mop)
    check("stars are effort times the setting", mop["reward_points"] == 6 and bins["reward_points"] == 2, (mop, bins))
    check("assigned goes to that profile", bins["category_id"] == "8" and not bins["up_for_grabs"], bins)

    print("14. up for grabs ticked on Skylight -> whoever ticked gets the credit")
    mop["status"] = "complete"
    mop["completed_category_id"] = "8"
    await sync.async_sync()
    check("credited to the person who ticked it", mgr.data["history"][-1]["by"] == "person.sam", mgr.data["history"][-1])

    print("15. up for grabs completed here -> Skylight is told who did it")
    mgr.add("dust", effort=2)
    await sync.async_sync()
    dust_sid = mapped()["dust"]["sid"]
    mgr.complete_chore("dust", by="person.alex")
    await sync.async_sync()
    check("credited to that profile on Skylight", sky.items[dust_sid]["status"] == "complete"
          and sky.items[dust_sid]["completed_category_id"] == "7", sky.items[dust_sid])
    mgr.add("wipe")
    await sync.async_sync()
    wipe_sid = mapped()["wipe"]["sid"]
    mgr.complete_chore("wipe", by=None)
    await sync.async_sync()
    check("unknown person falls back to the default profile", sky.items[wipe_sid]["completed_category_id"] == "9", sky.items[wipe_sid])
    mgr.complete_chore("bins", by="person.alex")
    await sync.async_sync()
    last = [c for c in sky.calls if c[0] == "status"][-1]
    check("assigned chore is ticked without naming anyone", last[3] is None, last)

    print("16. up for grabs switched off -> default profile")
    mgr.options["skylight_up_for_grabs"] = False
    mgr.options["skylight_stars"] = 0
    mgr.add("fan")
    await sync.async_sync()
    fan = sky.items[mapped()["fan"]["sid"]]
    check("goes to the default profile with no stars", fan["category_id"] == "9" and not fan["up_for_grabs"] and fan["reward_points"] is None, fan)

    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all scenarios passed'}")
    sys.exit(1 if FAILED else 0)


asyncio.run(main())
