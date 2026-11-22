"""To-do lists of due chores for Shipshape."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import ShipshapeEntity
from .manager import ShipshapeManager
from .models import parse_date


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: ShipshapeManager = hass.data[DOMAIN]["manager"]
    entities = [DueTodoList(manager, entry, None)]
    entities.extend(DueTodoList(manager, entry, person) for person in manager.participants())
    async_add_entities(entities)


class DueTodoList(ShipshapeEntity, TodoListEntity):
    """Due chores as a to-do list; checking an item off completes the chore."""

    _attr_icon = "mdi:broom"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, manager: ShipshapeManager, entry: ConfigEntry, person: str | None) -> None:
        super().__init__(manager, entry, f"todo_{person or 'all'}")
        self._person = person
        self._attr_name = f"{manager.person_name(person)} chores" if person else "Due chores"

    @property
    def todo_items(self) -> list[TodoItem]:
        items = []
        for view in self.manager.due_chores(self._person):
            late = -view["days_left"]
            detail = "Due today" if late <= 0 else f"{late} day{'s' if late != 1 else ''} overdue"
            items.append(
                TodoItem(
                    uid=view["id"],
                    summary=f"{view['zone']}: {view['name']}",
                    status=TodoItemStatus.NEEDS_ACTION,
                    due=parse_date(view["effective_due"]),
                    description=f"{detail} · {view['schedule_label']}",
                )
            )
        return items

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if item.uid and item.status == TodoItemStatus.COMPLETED:
            by = self._person or self.manager.person_for_user(
                self._context.user_id if self._context else None
            )
            self.manager.complete_chore(item.uid, by=by, source="todo")
