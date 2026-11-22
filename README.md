# Shipshape

Condition-based household chores for Home Assistant.

Most chore trackers nag you on fixed dates. Shipshape works the other way round: every chore has an interval, and its condition drifts from clean to due as that interval elapses. Mark it done, whenever that happens to be, and the clock starts again from that moment. Nothing piles up because you were a day late.

## What you get

- **Zones and chores.** Group chores by room or anything else. Repeat every N days, weeks or months, or in fixed months (for example April and October).
- **A dashboard card** with a to-do list sorted by urgency, a room overview, and scores. Add, edit, snooze and complete chores from the card.
- **People.** Assign chores, take turns automatically, earn effort points, see a weekly leaderboard.
- **Vacation mode.** Freezes every chore so you do not come home to a wall of red.
- **Reminders**, each optional: a morning digest, pushes with Done and Snooze buttons, and spoken announcements.
- **Device triggers.** Let an entity complete a chore (robot vacuum docks) or make one due (dishwasher finishes).
- **Native entities.** To-do lists, a calendar, sensors per zone and per person, so chores work with voice assistants, automations and other dashboards.
- **Calendar bridge.** Mirrors due chores into any writable calendar, such as a Google calendar that a Skylight display syncs. Deleting the event on the display can mark the chore done.
- **Skylight Chores sync** (unofficial, best effort). Sends due chores to Skylight's own Chores and reads completions back.

## Install

1. In HACS, open the menu, choose **Custom repositories**, and add `https://github.com/WileCyot/ha-shipshape` as an **Integration**.
2. Download **Shipshape** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and pick **Shipshape**. Keep the starter library on to begin with ready-made rooms and chores, or turn it off to start empty.
4. Add the card to a dashboard:

```yaml
type: custom:shipshape-card
title: Chores
```

The card is registered automatically; there is no dashboard resource to add.

### Card options

| Option | Default | Meaning |
| --- | --- | --- |
| `title` | `Chores` | Heading |
| `default_tab` | `todo` | `todo`, `rooms` or `scores` |
| `zone` | | Show only this zone (by name) |
| `person` | | Show only this person's chores (`person.x`) |

## Settings

**Settings → Devices & services → Shipshape → Configure** has four sections.

- **People and phones.** Who takes part, and which phone each person's pushes go to. Left empty, Shipshape uses the phone linked to the person.
- **Reminders.** Switch the digest, pushes and announcements on or off and set their times.
- **Calendar bridge.** Pick a calendar to mirror chores into, how many days ahead to show, and whether deleting an event marks the chore done.
- **Skylight Chores.** Sign in to Skylight and map people to Skylight profiles.

## Skylight

There are two ways to get chores onto a Skylight display. They can be used together.

**Calendar bridge (dependable).** Add Home Assistant's Google Calendar integration with read/write access, create a calendar for chores in the Google account your Skylight syncs, and select it under *Calendar bridge*. Each due chore appears as an all-day event and overdue ones roll forward to today. Skylight supports two-way sync for Google calendars the account owns.

**Skylight Chores (unofficial).** Skylight has no public API. This talks to the private API the Skylight app uses, as worked out by community projects. It can break whenever Skylight changes their app, and Skylight does not support it. When it works: due chores show up as real Skylight chores, ticking one off on the display completes it in Home Assistant, and deleting one snoozes it for a day. Sign-in may ask for a code that Skylight emails to the account owner. Your password is used once and is not stored; only the session tokens are kept.

## Actions

| Action | Purpose |
| --- | --- |
| `shipshape.complete_chore` | Mark done, by id or by name and zone |
| `shipshape.snooze_chore` | Hide a due chore for some days |
| `shipshape.make_due` | Make a chore due now |
| `shipshape.add_chore` | Add a chore, creating the zone if needed |
| `shipshape.import_data` / `export_data` | Bulk load or dump zones and chores |
| `shipshape.set_vacation` | Freeze or resume all chores |
| `shipshape.send_reminders` | Send a digest, push or announcement now |
| `shipshape.sync_now` | Run the calendar bridge and Skylight sync now |

Completing a chore fires a `shipshape_chore_completed` event with the chore, zone, person and points.

### Import format

```yaml
action: shipshape.import_data
data:
  data:
    zones:
      - name: Kitchen
        icon: mdi:silverware-fork-knife
        chores:
          - { name: Wipe counters, every: 4, unit: days }
          - { name: Clean oven, every: 6, unit: months, effort: 3 }
      - name: Entrance
        chores:
          - { name: Seasonal coat change, months: [4, 10] }
```

Imported chores without a `last_done` date get staggered starting conditions so they do not all come due on the same day.

## Entities

- `todo.shipshape_due_chores` and one to-do list per person
- `calendar.shipshape`
- `sensor.shipshape_due_chores`, `sensor.shipshape_overdue_chores`, `sensor.shipshape_on_track`
- one sensor per zone and a points sensor per person
- `switch.shipshape_vacation_mode`

## Development

The scheduling logic in `custom_components/shipshape/models.py` has no Home Assistant imports and is covered by `tests/test_models.py`:

```
pytest tests
```

## License

MIT
