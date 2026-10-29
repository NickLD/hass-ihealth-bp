# iHealth Blood Pressure (KN-550BT) for Home Assistant

A HACS custom integration that syncs an **iHealth KN-550BT** blood pressure monitor with Home
Assistant over Bluetooth — locally, through any Bluetooth adapter or ESPHome Bluetooth proxy, with no
iHealth app or cloud account. It can replace the iHealth app completely: it imports every reading
with the time it was taken, keeps the cuff's clock right, clears the cuff's memory after importing
(like the app does), and lets you change the cuff's display settings.

> **Unofficial.** This project is not affiliated with or endorsed by iHealth Labs / Andon Health.
> The Bluetooth protocol was reverse engineered for interoperability. It is not a medical device;
> do not use it for diagnosis.

## Supported devices

| Device | Advertised service | Status |
| :--- | :--- | :---: |
| KN-550BT (firmware 303, hardware 300) | `com.jiuan.dev` | ✅ Tested |
| KN-550BT, older firmware | `com.jiuan.BPAV21` | ⚠️ **Untested** |
| KN-550BT, older firmware | `com.jiuan.BPAV10` (name contains "550") | ⚠️ **Untested** |

The older firmware uses a different protocol that was implemented from the iHealth app's code and
checked against its own test vectors, but has never been run against a real cuff. If you have one,
please [open an issue](https://github.com/NickLD/hass-ihealth-bp/issues) with
[debug logs](#troubleshooting) and the device diagnostics, whether it works or not. The **Protocol**
sensor shows which variant your cuff uses.

## Requirements

- Home Assistant 2026.10 or newer.
- A Bluetooth adapter or ESPHome Bluetooth proxy **with active connections enabled** within range of
  where you take readings. ESP32-C3 boards work fine:

  ```yaml
  esp32_ble_tracker:
    scan_parameters:
      active: true
  bluetooth_proxy:
    active: true
  ```

The cuff only switches its radio on for about **10 seconds** after a measurement (or when woken), and
Home Assistant has to connect within that window. A full sync takes about a quarter of a second, but
a weak signal (below roughly −90 dBm, e.g. a proxy tucked into a ceiling corner of another room) can
make connections unreliable. Nothing is lost when a sync fails: readings stay on the cuff and are
picked up after the next measurement.

## Installation

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=NickLD&repository=hass-ihealth-bp&category=integration)

1. Click the button above (or in HACS, open the menu → **Custom repositories** and add
   `https://github.com/NickLD/hass-ihealth-bp` as an **Integration**), then download
   **iHealth Blood Pressure**.
2. Restart Home Assistant.
3. Take a measurement. The cuff appears under **Settings → Devices & services → Discovered**; click
   **Add**. Or, right after waking the cuff:

   [![Open your Home Assistant instance and start setting up iHealth Blood Pressure.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ihealth_bp)

There is no pairing step. If you used the iHealth app before, you do not need to unpair it, but read
the [options](#options) about sharing the cuff with the app.

## How it works

Every time the cuff wakes up and advertises, Home Assistant connects through the proxy that hears it
best and, in one short session:

1. authenticates with the cuff,
2. sets the cuff's clock to Home Assistant's local time,
3. reads the battery level and display settings (and applies any change you made in HA),
4. downloads every stored reading,
5. saves new readings, then (by default) deletes them from the cuff.

## Measurement routine

Readings taken at random times are mostly noise. Home monitoring guidelines (the 2017 ACC/AHA
guideline and the "722" protocol used in most studies) ask for a fixed routine: a **morning** and an
**evening** session each day, **two readings per session, 1 minute apart**, averaged, for 7 days. The
morning session is within about an hour of waking, before caffeine, food and medication; the evening
one is before bed. Sit quietly for 5 minutes first, back supported, feet flat, arm at heart level, no
talking, no caffeine or exercise in the previous 30 minutes. The integration organises your readings
around that routine. It sends no reminders itself; you build those with ordinary automations (see the
[example](#example-take-a-second-reading)). Sources:
[PMC9532917](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9532917/),
[AHA handout](https://cpr.heart.org/-/media/Files/Health-Topics/High-Blood-Pressure/measuringbpathome.pdf),
[AMA handout](https://map.ama-assn.org/sites/default/files/2024-05/How%20to%20measure%20blood%20pressure%20at%20home.pdf).

### Periods and BP days

Every reading gets a period from the time on the cuff (so a late sync does not matter):

| Period | Default window | Notes |
| :--- | :--- | :--- |
| `morning` | 05:00-12:30 | |
| `evening` | 21:00-03:00 | Wraps midnight: a 01:30 reading belongs to the previous day's evening |
| `extra` | anything else | Never counts toward the baseline |

A **BP day** starts when the morning window starts (05:00 by default) and lasts 24 hours. One reading
fills a slot. The windows can be changed in the [options](#options).

### Sessions

Readings no more than **10 minutes apart** (chained) form one session. Each reading gets a
`session_index` (1, 2, 3...), and the session has a mean systolic and diastolic. The session takes its
period and BP day from its first reading that falls inside the morning or evening window, so a session
started at 20:59 and finished at 21:01 fills the evening slot. A session with no reading inside a
window is `extra` and belongs to the BP day of its first reading.

### Flags and notes

Each reading can carry context **flags** and a free-text **note** (up to 255 characters). The flags
are: had caffeine, just ate, after exertion, after shower, poor sleep, alcohol last night, stressed,
missed meds, sick. Set them from the entities below or with the `ihealth_bp.set_reading_context`
action for any reading. They are stored with the reading and survive restarts.

The flag switches, the session note and the discard button act on the **latest session**: the newest
session by cuff time, the one you have already taken. They never apply to the next session. Flag a
session after taking it (once Home Assistant has imported it), not before.

### What counts toward the baseline

A reading counts when all of these hold:

- it is imported (not held for review, not deleted);
- its session is in the `morning` or `evening` period;
- it has **no flags**;
- the cuff did not mark it with **body movement** (the reading still fills the slot);
- it was taken on or after the **routine start date**.

Irregular pulse does *not* exclude a reading, because it is clinically meaningful rather than a
measurement error; a sensor counts those readings instead. The baseline is the mean of the **session
means**, one value per filled slot, so a three-reading session does not outweigh a two-reading one.
The routine start date defaults to the day you upgraded to v0.2.0, so older readings never enter the
baseline. Change it in the [options](#options).

### Routine entities

| Entity | Notes |
| :--- | :--- |
| Baseline systolic/diastolic (7 days), (30 days) | Mean of clean session means over the trailing window (mmHg) |
| Morning systolic/diastolic (7 days), Evening systolic/diastolic (7 days) | Same, for one period only |
| Baseline category (7 days) | ACC/AHA category of the 7-day baseline |
| Routine slots filled (7 days) | 0-14 |
| Irregular pulse readings (7 days) | Count of readings with the irregular-pulse flag |
| Morning slot, Evening slot | Today's state: `filled`, `open`, `upcoming` or `closed`. Attributes: `window_start`, `window_end`, `first_reading_at`, `mean_systolic`, `mean_diastolic`, `reading_count`. Automations can read the window from these |
| Had caffeine, Just ate, After exertion, After shower, Poor sleep, Alcohol last night, Stressed, Missed meds, Sick (switches) | Flag every reading of the latest session (newest by cuff time) |
| Session note (text) | Note for the latest session |
| Discard latest session (button) | Deletes the latest session's readings |

The trailing 7- and 30-day windows count BP days (which start at the morning window start), not
calendar days. The sensors are recalculated after every new reading, flag change and delete, at every
window start and end, and at local midnight.

## Entities

| Entity | Notes |
| :--- | :--- |
| Systolic, Diastolic (mmHg), Pulse (bpm) | Newest imported reading |
| Pulse pressure, Mean arterial pressure (mmHg) | Derived from the newest reading |
| Blood pressure category | ACC/AHA 2017: normal, elevated, hypertension stage 1/2, hypertensive crisis |
| Measured at | When the newest reading was taken |
| Irregular pulse, Body movement | Flags reported by the cuff for the newest reading |
| Battery | Updated each sync |
| Backlight, Clock display (switches) | Applied the next time the cuff connects; `pending: true` until then |
| Readings (to-do list) | Every reading, newest first — see below |
| Protocol, Last sync, Last failure, Connected via, Signal strength | Diagnostics: *Connected via* names the adapter/proxy used for the last session (signal strength is disabled by default) |

Sensor values survive restarts. The measurement sensors deliberately have no `state_class`; long-term
history is recorded separately at the time each reading was **taken** (see Statistics).

### Statistics

Readings are written to long-term statistics at their measurement time, so graphs line up with when
you actually measured rather than when the cuff happened to sync. Use a **Statistics graph** card with:

- `ihealth_bp:<address>_systolic`
- `ihealth_bp:<address>_diastolic`
- `ihealth_bp:<address>_pulse`

where `<address>` is the cuff's Bluetooth address in lowercase without colons (e.g. `004d32650e89`).

### Event

Each imported reading fires an `ihealth_bp_measurement` event, oldest first:

| Field | Meaning |
| :--- | :--- |
| `device_id`, `address` | The cuff |
| `measured_at` | When the reading was taken (ISO 8601, Home Assistant time zone) |
| `systolic`, `diastolic`, `pulse` | The reading |
| `irregular_pulse`, `body_movement` | Flags |
| `uid` | Unique id of the reading |
| `bp_category` | ACC/AHA category of this reading |
| `period` | `morning`, `evening` or `extra` |
| `session_index` | Position of this reading in its session (1, 2, ...) |
| `session_start` | Local time of the session's first reading (ISO 8601) |
| `session_mean_systolic`, `session_mean_diastolic` | Mean of the session so far, including this reading |
| `session_measured_at` | Times of the session's readings so far, up to and including this one (ISO 8601) |

The session fields are only present when the reading belongs to a session.

## Removing and annotating readings

Open the **Readings** list (it shows up in the To-do panel) and delete the reading. Home Assistant
removes it from the statistics, and if it was the newest reading the sensors fall back to the previous
one. A deleted reading is never imported again. The same is available as actions for scripts:

```yaml
action: ihealth_bp.delete_reading
data:
  device_id: <your cuff's device id>
  measured_at: "2026-10-21 15:09:02"
```

`ihealth_bp.delete_session` deletes every reading of the session that contains `measured_at`, and
rebuilds the statistics:

```yaml
action: ihealth_bp.delete_session
data:
  device_id: <your cuff's device id>
  measured_at: "2026-10-21 15:09:02"
```

`ihealth_bp.set_reading_context` sets flags and a note on a reading, or on its whole session with
`session: true`. `flags` replaces the existing flags, `add_flags` adds to them, and an empty `note`
clears the note. Give at least one of `flags`, `add_flags` or `note`.

```yaml
action: ihealth_bp.set_reading_context
data:
  device_id: <your cuff's device id>
  measured_at: "2026-10-21 15:09:02"
  session: true
  add_flags: [caffeine, ate]
  note: Measured after breakfast
```

The flag names are `caffeine`, `ate`, `exertion`, `after_shower`, `poor_sleep`, `alcohol`,
`stressed`, `missed_meds` and `sick`.

Deleting cannot undo an `ihealth_bp_measurement` event that already fired (or automations it
triggered), and the sensors' short-term history keeps the old value until the recorder purges it.

### Adding a reading by hand

If a reading never reached Home Assistant (for example because the iHealth app took it off the cuff,
see [troubleshooting](#troubleshooting)), add it with `ihealth_bp.add_reading`. It is treated like a
reading from the cuff: it joins its session, counts toward its slot and the baseline, updates the
statistics and fires `ihealth_bp_measurement`. `irregular_pulse` and `body_movement` are optional
and default to `false`. A naive `measured_at` is in Home Assistant's time zone. The action refuses a
time in the future, a time that already has a reading, and a systolic pressure that is not above the
diastolic. Readings added this way are marked as manual in the reading log.

```yaml
action: ihealth_bp.add_reading
data:
  device_id: <your cuff's device id>
  measured_at: "2026-10-21 21:40:00"
  systolic: 121
  diastolic: 78
  pulse: 70
```

### Example: take a second reading

After the first reading of a session, notify the phone and offer to discard the session. The second
condition skips old readings that arrive in a backlog sync (for example after Home Assistant was
offline), so you are not asked to retake a measurement from hours ago. `wait_for_trigger` stores the
reply in `wait.trigger`, so `trigger` still refers to the reading afterwards:

```yaml
automation:
  - alias: Blood pressure - take a second reading
    triggers:
      - trigger: event
        event_type: ihealth_bp_measurement
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.session_index == 1 }}"
      - condition: template
        value_template: >-
          {{ now() - as_datetime(trigger.event.data.measured_at) < timedelta(minutes=5) }}
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "{{ trigger.event.data.systolic }}/{{ trigger.event.data.diastolic }}"
          message: Take a second reading in 1 minute
          data:
            actions:
              - action: DISCARD_BP_SESSION
                title: Discard
      - wait_for_trigger:
          - trigger: event
            event_type: mobile_app_notification_action
            event_data:
              action: DISCARD_BP_SESSION
        timeout: "00:05:00"
        continue_on_timeout: false
      - action: ihealth_bp.delete_session
        data:
          device_id: "{{ trigger.event.data.device_id }}"
          measured_at: "{{ trigger.event.data.measured_at }}"
```

## Options

**Settings → Devices & services → iHealth Blood Pressure → Configure**

- **Delete readings from the cuff after importing them** (default **on**). This is what the iHealth
  app does. Readings are only deleted after Home Assistant has saved them. Turn it off if you still
  use the iHealth app as well; the cuff then keeps up to 99 readings until something else clears it,
  and Home Assistant skips the ones it already has. The iHealth app clears the cuff itself whenever
  it syncs (see [troubleshooting](#troubleshooting)), so this option cannot protect readings from it.
- **Hold new readings for review before importing them** (default **off**). New readings arrive
  unticked in the Readings list. Tick one to import it (sensors, statistics and event), or delete it
  to discard it.
- **Morning window starts / ends, Evening window starts / ends.** Defaults 05:00, 12:30, 21:00 and
  03:00. The evening may end after midnight. The windows must not overlap and must fit within 24
  hours from the morning start, which is also when a new BP day begins.
- **Count readings toward the baseline from this date.** The routine start date; readings taken
  before it are left out of the baseline.

## Troubleshooting

Turn on debug logging (**Settings → Devices & services → iHealth Blood Pressure → ⋮ → Enable debug
logging**), take a measurement, then disable it to download the log. The **Last failure** sensor shows
which stage of the last failed sync broke (`connect`, `auth`, `readings`, …), and the device page has
**Download diagnostics** (the Bluetooth address and serial are redacted).

From v0.1.1, a failed *connection* is only recorded as a failure if the cuff goes back to sleep
without any successful sync, because the first attempt usually reaches the cuff while it is still
measuring. Failures at any other stage are recorded immediately.

- **Never syncs:** check that a proxy with `bluetooth_proxy: active: true` is close enough to the cuff,
  and that the iHealth app is not connected to the cuff at the same moment.
- **Readings missing:** the iHealth app (checked with version 4.17.0) syncs as soon as it connects to
  the cuff on its KN-550BT screen, without tapping anything. It downloads every reading, uploads them
  to iHealth's cloud as unassigned readings, and then deletes them from the cuff, so Home Assistant
  never sees them. Their upload button only assigns readings that are already uploaded to your
  account. Keep the app away from the cuff (or remove it), and add any lost readings with
  [`ihealth_bp.add_reading`](#adding-a-reading-by-hand).
- **Readings at the wrong time:** the cuff stores local time with no time zone; it is set from Home
  Assistant's time zone on every sync. Home Assistant can only correct the clock when it connects, so
  after a daylight-saving change, or a battery swap that resets the cuff's clock, a reading taken
  before the next sync is stamped with the cuff's stale clock. That reading keeps the wrong time;
  later readings are correct.

The wire protocol is documented in [docs/protocol.md](docs/protocol.md).

## License

MIT
