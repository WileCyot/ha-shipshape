"""Starter library of zones and chores with sensible default frequencies."""

from __future__ import annotations

from typing import Any


def _c(name: str, every: int, unit: str, effort: int = 1) -> dict[str, Any]:
    return {"name": name, "every": every, "unit": unit, "effort": effort}


STARTER_LIBRARY: dict[str, Any] = {
    "zones": [
        {
            "name": "Kitchen",
            "icon": "mdi:silverware-fork-knife",
            "chores": [
                _c("Wipe counters", 2, "days"),
                _c("Clean sink", 1, "weeks"),
                _c("Clean stove top", 1, "weeks"),
                _c("Change towels", 1, "weeks"),
                _c("Mop floor", 2, "weeks", 2),
                _c("Clean microwave", 1, "months"),
                _c("Organize fridge", 2, "weeks"),
                _c("Clean fridge", 2, "months", 2),
                _c("Clean trash can", 1, "months"),
                _c("Wipe cupboards and drawers", 1, "months"),
                _c("Clean range hood", 2, "months", 2),
                _c("Clean oven", 6, "months", 3),
                _c("Organize pantry", 3, "months", 2),
                _c("Clean freezer", 12, "months", 3),
            ],
        },
        {
            "name": "Living Room",
            "icon": "mdi:sofa",
            "chores": [
                _c("Tidy up", 1, "weeks"),
                _c("Vacuum floor", 1, "weeks"),
                _c("Dust", 2, "weeks"),
                _c("Vacuum furniture", 1, "months", 2),
                _c("Clean windows", 2, "months", 2),
                _c("Wash blankets and covers", 1, "months"),
                _c("Clean ceiling fan", 4, "months"),
                _c("Declutter", 6, "months", 2),
            ],
        },
        {
            "name": "Bedroom",
            "icon": "mdi:bed-king",
            "chores": [
                _c("Change bed linen", 2, "weeks"),
                _c("Tidy up", 1, "weeks"),
                _c("Vacuum floor", 1, "weeks"),
                _c("Dust", 3, "weeks"),
                _c("Clean mirror", 6, "weeks"),
                _c("Clean windows", 2, "months", 2),
                _c("Organize closet", 3, "months", 2),
                _c("Wash quilt and pillows", 4, "months", 2),
                _c("Clean ceiling fan", 4, "months"),
            ],
        },
        {
            "name": "Bathroom",
            "icon": "mdi:shower",
            "chores": [
                _c("Clean toilet", 1, "weeks"),
                _c("Clean sink", 10, "days"),
                _c("Change towels", 1, "weeks"),
                _c("Clean mirrors", 3, "weeks"),
                _c("Mop floor", 2, "weeks", 2),
                _c("Change bath mat", 3, "weeks"),
                _c("Clean shower", 2, "weeks", 2),
                _c("Clean shower glass", 2, "months", 2),
                _c("Clean drains", 2, "months"),
                _c("Descale tiles", 6, "months", 3),
            ],
        },
        {
            "name": "Laundry",
            "icon": "mdi:washing-machine",
            "chores": [
                _c("Wipe appliances", 2, "weeks"),
                _c("Clean washer seal", 1, "months"),
                _c("Run washer cleaning cycle", 2, "months"),
                _c("Clean dryer vent", 6, "months", 2),
                _c("Mop floor", 2, "weeks", 2),
            ],
        },
        {
            "name": "Entrance",
            "icon": "mdi:door",
            "chores": [
                _c("Sweep entry", 1, "weeks"),
                _c("Clean door glass", 3, "weeks"),
                _c("Shake out mats", 2, "weeks"),
                {"name": "Seasonal coat and shoe change", "months": [4, 10], "effort": 2},
            ],
        },
        {
            "name": "Outdoors / Yard",
            "icon": "mdi:tree",
            "chores": [
                _c("Take trash cans to the curb", 1, "weeks"),
                _c("Wash trash cans", 3, "months", 2),
                _c("Sweep porch", 2, "weeks"),
                _c("Clean exterior windows", 6, "months", 3),
                _c("Clean gutters", 6, "months", 3),
            ],
        },
        {
            "name": "Home Maintenance",
            "icon": "mdi:wrench",
            "chores": [
                _c("Change air filters", 90, "days"),
                _c("Test smoke and gas detectors", 6, "months"),
                _c("Flush water heater", 12, "months", 3),
                _c("Clean fridge coils", 12, "months", 2),
                _c("Check fire extinguishers", 12, "months"),
            ],
        },
    ]
}
