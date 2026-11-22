"""Constants for Shipshape."""

from __future__ import annotations

DOMAIN = "shipshape"
VERSION = "0.2.0"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

URL_BASE = "/shipshape_static"
CARD_FILENAME = "shipshape-card.js"

EVENT_CHORE_COMPLETED = "shipshape_chore_completed"
EVENT_CHORE_DUE = "shipshape_chore_due"

HISTORY_LIMIT = 3000

# --- options -----------------------------------------------------------
CONF_PARTICIPANTS = "participants"
CONF_NOTIFY_MAP = "notify_map"  # {person_entity_id: "notify.mobile_app_x"}

CONF_DIGEST_ENABLED = "digest_enabled"
CONF_DIGEST_TIME = "digest_time"
CONF_PUSH_ENABLED = "push_enabled"
CONF_PUSH_TIME = "push_time"
CONF_PUSH_MAX = "push_max"
CONF_ANNOUNCE_ENABLED = "announce_enabled"
CONF_ANNOUNCE_TIME = "announce_time"
CONF_ANNOUNCE_TARGETS = "announce_targets"
CONF_DASHBOARD_PATH = "dashboard_path"

CONF_CALENDAR_ENTITY = "calendar_entity"
CONF_CALENDAR_HORIZON = "calendar_horizon"
CONF_CALENDAR_DONE_ON_DELETE = "calendar_done_on_delete"

CONF_SKYLIGHT_ENABLED = "skylight_enabled"
CONF_SKYLIGHT_EMAIL = "skylight_email"
CONF_SKYLIGHT_PASSWORD = "skylight_password"
CONF_SKYLIGHT_FRAME = "skylight_frame"
CONF_SKYLIGHT_PROFILE_MAP = "skylight_profile_map"  # {person_entity_id: category_id}
CONF_SKYLIGHT_DEFAULT_PROFILE = "skylight_default_profile"
CONF_SKYLIGHT_UP_FOR_GRABS = "skylight_up_for_grabs"
CONF_SKYLIGHT_STARS = "skylight_stars"
CONF_SKYLIGHT_CALENDAR = "skylight_calendar"
CONF_SKYLIGHT_GROCERY_ENABLED = "skylight_grocery_enabled"
CONF_SKYLIGHT_GROCERY_TODO = "skylight_grocery_todo"
CONF_SKYLIGHT_GROCERY_LIST = "skylight_grocery_list"
CONF_SKYLIGHT_TODO_ENABLED = "skylight_todo_enabled"
CONF_SKYLIGHT_TODO_TODO = "skylight_todo_todo"
CONF_SKYLIGHT_TODO_LIST = "skylight_todo_list"

DEFAULTS: dict = {
    CONF_PARTICIPANTS: [],
    CONF_NOTIFY_MAP: {},
    CONF_DIGEST_ENABLED: True,
    CONF_DIGEST_TIME: "07:30:00",
    CONF_PUSH_ENABLED: True,
    CONF_PUSH_TIME: "18:00:00",
    CONF_PUSH_MAX: 3,
    CONF_ANNOUNCE_ENABLED: False,
    CONF_ANNOUNCE_TIME: "17:30:00",
    CONF_ANNOUNCE_TARGETS: [],
    CONF_DASHBOARD_PATH: "/shipshape-chores",
    CONF_CALENDAR_ENTITY: None,
    CONF_CALENDAR_HORIZON: 7,
    CONF_CALENDAR_DONE_ON_DELETE: True,
    CONF_SKYLIGHT_ENABLED: False,
    CONF_SKYLIGHT_EMAIL: "",
    CONF_SKYLIGHT_PASSWORD: "",
    CONF_SKYLIGHT_FRAME: "",
    CONF_SKYLIGHT_PROFILE_MAP: {},
    CONF_SKYLIGHT_DEFAULT_PROFILE: "",
    CONF_SKYLIGHT_UP_FOR_GRABS: True,
    CONF_SKYLIGHT_STARS: 1,
    CONF_SKYLIGHT_CALENDAR: True,
    CONF_SKYLIGHT_GROCERY_ENABLED: False,
    CONF_SKYLIGHT_GROCERY_TODO: None,
    CONF_SKYLIGHT_GROCERY_LIST: "",
    CONF_SKYLIGHT_TODO_ENABLED: False,
    CONF_SKYLIGHT_TODO_TODO: None,
    CONF_SKYLIGHT_TODO_LIST: "",
}

ACTION_DONE = "SHIPSHAPE_DONE_"
ACTION_SNOOZE = "SHIPSHAPE_SNOOZE_"

CALENDAR_MARKER = "shipshape:"
