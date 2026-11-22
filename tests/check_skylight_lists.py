"""Scenario check for the Skylight list sync against fakes.

Run inside a Home Assistant container, like check_skylight_sync.py.
"""

import asyncio
import sys

from homeassistant.components.todo import TodoItem, TodoItemStatus

from custom_components.shipshape import skylight_lists

skylight_lists.WRITE_PAUSE = 0

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name, "" if cond else detail)
    if not cond:
        FAILED.append(name)


class FakeTodo:
    available = True

    def __init__(self):
        self.todo_items = []
        self.n = 0

    async def async_create_todo_item(self, item):
        self.n += 1
        self.todo_items.append(TodoItem(uid=f"u{self.n}", summary=item.summary, status=item.status))

    async def async_update_todo_item(self, item):
        self.todo_items = [
            TodoItem(uid=i.uid, summary=item.summary or i.summary, status=item.status or i.status)
            if i.uid == item.uid else i
            for i in self.todo_items
        ]

    async def async_delete_todo_items(self, uids):
        self.todo_items = [i for i in self.todo_items if i.uid not in uids]

    # helpers for the test
    def add(self, summary, done=False):
        self.n += 1
        status = TodoItemStatus.COMPLETED if done else TodoItemStatus.NEEDS_ACTION
        self.todo_items.append(TodoItem(uid=f"u{self.n}", summary=summary, status=status))
        return f"u{self.n}"

    def by_name(self, summary):
        return next((i for i in self.todo_items if i.summary == summary), None)

    def set(self, summary, done):
        i = self.by_name(summary)
        status = TodoItemStatus.COMPLETED if done else TodoItemStatus.NEEDS_ACTION
        self.todo_items = [TodoItem(uid=x.uid, summary=x.summary, status=status) if x.uid == i.uid else x
                           for x in self.todo_items]


class FakeComponent:
    def __init__(self, entities):
        self.entities = entities

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


class FakeSkylight:
    def __init__(self):
        self.lists_data = {"L1": {"id": "L1", "label": "Grocery List", "kind": "shopping", "items": []}}
        self.n = 500
        self.writes = []

    async def lists(self, frame):
        return [{**l, "items": [dict(i) for i in l["items"]]} for l in self.lists_data.values()]

    def _items(self, list_id):
        return self.lists_data[list_id]["items"]

    async def add_list_item(self, frame, list_id, label):
        self.n += 1
        self._items(list_id).append({"id": str(self.n), "label": label, "status": "pending", "section": None})
        self.writes.append(("add", label))
        return str(self.n)

    async def update_list_item(self, frame, list_id, item_id, status=None, label=None):
        for i in self._items(list_id):
            if i["id"] == item_id:
                if status is not None:
                    i["status"] = status
                if label is not None:
                    i["label"] = label
        self.writes.append(("update", item_id, status, label))

    async def delete_list_item(self, frame, list_id, item_id):
        self.lists_data[list_id]["items"] = [i for i in self._items(list_id) if i["id"] != item_id]
        self.writes.append(("delete", item_id))

    # helpers
    def add(self, label, done=False):
        self.n += 1
        self._items("L1").append({"id": str(self.n), "label": label, "status": "completed" if done else "pending", "section": None})
        return str(self.n)

    def by_name(self, label):
        return next((i for i in self._items("L1") if i["label"] == label), None)


class FakeSync:
    signed_in = True
    frame = "1"
    needs_login = False
    backing_off = False

    def __init__(self, client):
        self._client = client

    def client(self):
        return self._client

    def back_off(self, seconds=1800):
        self.backing_off = True


class FakeManager:
    def __init__(self):
        self.options = {"skylight_grocery_enabled": True, "skylight_grocery_todo": "todo.shopping",
                        "skylight_grocery_list": "L1"}
        self.data = {"skylight": {}}

    def async_save_quietly(self):
        pass


class FakeHass:
    def __init__(self, todo):
        self.data = {"todo": FakeComponent({"todo.shopping": todo})}


def names(todo, done=None):
    return sorted(i.summary for i in todo.todo_items
                  if done is None or (i.status == TodoItemStatus.COMPLETED) == done)


def rnames(sky, status=None):
    return sorted(i["label"] for i in sky._items("L1") if status is None or i["status"] == status)


async def main():
    todo = FakeTodo()
    sky = FakeSkylight()
    mgr = FakeManager()
    lists = skylight_lists.SkylightLists(FakeHass(todo), mgr, FakeSync(sky))
    pairs = lambda: mgr.data["skylight"]["lists"]["grocery"]["pairs"]

    print("1. first link: open Skylight items come in, old ticked ones stay out")
    for i in range(30):
        sky.add(f"old {i}", done=True)
    sky.add("Milk")
    sky.add("Eggs")
    await lists.async_sync()
    check("open items copied here", names(todo) == ["Eggs", "Milk"], names(todo))
    check("history not copied", len(todo.todo_items) == 2)
    check("nothing written to Skylight", sky.writes == [], sky.writes)
    check("pairs remembered", len(pairs()) == 2)
    await lists.async_sync()
    check("second sync changes nothing", names(todo) == ["Eggs", "Milk"] and sky.writes == [])

    print("2. added here -> appears on Skylight")
    todo.add("Bread")
    await lists.async_sync()
    check("created on Skylight", sky.by_name("Bread") and sky.by_name("Bread")["status"] == "pending")
    check("no duplicate here", names(todo) == ["Bread", "Eggs", "Milk"], names(todo))

    print("3. ticked here -> ticked on Skylight")
    todo.set("Milk", True)
    await lists.async_sync()
    check("ticked on Skylight", sky.by_name("Milk")["status"] == "completed")

    print("4. ticked on Skylight -> ticked here")
    sky.by_name("Eggs")["status"] = "completed"
    await lists.async_sync()
    check("ticked here", todo.by_name("Eggs").status == TodoItemStatus.COMPLETED)

    print("5. un-ticked on Skylight -> open again here")
    sky.by_name("Eggs")["status"] = "pending"
    await lists.async_sync()
    check("open again here", todo.by_name("Eggs").status == TodoItemStatus.NEEDS_ACTION)

    print("6. renamed on either side")
    sky.by_name("Bread")["label"] = "Sourdough"
    await lists.async_sync()
    check("rename came here", todo.by_name("Sourdough") is not None and todo.by_name("Bread") is None, names(todo))
    uid = todo.by_name("Eggs").uid
    todo.todo_items = [TodoItem(uid=i.uid, summary="Eggs x12" if i.uid == uid else i.summary, status=i.status)
                       for i in todo.todo_items]
    await lists.async_sync()
    check("rename went to Skylight", sky.by_name("Eggs x12") is not None, rnames(sky, "pending"))

    print("7. deleted here -> deleted on Skylight")
    todo.todo_items = [i for i in todo.todo_items if i.summary != "Sourdough"]
    await lists.async_sync()
    check("gone from Skylight", sky.by_name("Sourdough") is None)

    print("8. deleted on Skylight -> deleted here")
    sky.lists_data["L1"]["items"] = [i for i in sky._items("L1") if i["label"] != "Eggs x12"]
    await lists.async_sync()
    check("gone here", todo.by_name("Eggs x12") is None, names(todo))

    print("9. clearing ticked items here removes only the paired ones on Skylight")
    before = len(sky._items("L1"))
    todo.todo_items = [i for i in todo.todo_items if i.status != TodoItemStatus.COMPLETED]  # Milk
    await lists.async_sync()
    check("paired ticked item removed", sky.by_name("Milk") is None)
    check("old history untouched", len(sky._items("L1")) == before - 1 and sky.by_name("old 3") is not None)

    print("10. re-adding something from the history reuses that item")
    todo.add("old 7")
    n = len(sky._items("L1"))
    await lists.async_sync()
    check("reopened, not duplicated", len(sky._items("L1")) == n and sky.by_name("old 7")["status"] == "pending")

    print("11. same item added on both sides at once -> one pair, no duplicates")
    todo.add("Butter")
    sky.add("butter")
    await lists.async_sync()
    check("one here", len([i for i in todo.todo_items if i.summary.lower() == "butter"]) == 1, names(todo))
    check("one on Skylight", len([i for i in sky._items("L1") if i["label"].lower() == "butter"]) == 1)

    print("12. ticked on both sides between syncs -> stays ticked")
    todo.add("Rice")
    await lists.async_sync()
    todo.set("Rice", True)
    sky.by_name("Rice")["status"] = "completed"
    await lists.async_sync()
    check("ticked on both", todo.by_name("Rice").status == TodoItemStatus.COMPLETED and sky.by_name("Rice")["status"] == "completed")

    print("13. relinking to another list starts clean instead of deleting")
    sky.lists_data["L2"] = {"id": "L2", "label": "Other", "kind": "to_do", "items": []}
    mgr.options["skylight_grocery_list"] = "L2"
    here = names(todo)
    await lists.async_sync()
    check("nothing deleted here", set(here) <= set(names(todo)), names(todo))
    check("open items sent to the new list", "Butter" in [i["label"] for i in sky.lists_data["L2"]["items"]])

    print("14. missing Skylight list or to-do entity is survivable")
    mgr.options["skylight_grocery_list"] = "nope"
    await lists.async_sync()
    check("no crash, no error state", lists.last_error is None, lists.last_error)
    mgr.options["skylight_grocery_todo"] = "todo.gone"
    await lists.async_sync()
    check("still fine", lists.last_error is None)

    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all scenarios passed'}")
    sys.exit(1 if FAILED else 0)


asyncio.run(main())
