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

1. In HACS, open the menu → **Custom repositories**, add `https://github.com/NickLD/hass-ihealth-bp`
   as an **Integration**, then download **iHealth Blood Pressure**.
2. Restart Home Assistant.
3. Take a measurement. The cuff appears under **Settings → Devices & services → Discovered**; click
   **Add**. (Or **Add integration → iHealth Blood Pressure** right after waking the cuff.)

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

## Removing bad readings

Open the **Readings** list (it shows up in the To-do panel) and delete the reading. Home Assistant
removes it from the statistics, and if it was the newest reading the sensors fall back to the previous
one. A deleted reading is never imported again. The same is available as an action for scripts:

```yaml
action: ihealth_bp.delete_reading
data:
  device_id: <your cuff's device id>
  measured_at: "2026-10-21 15:09:02"
```

Deleting cannot undo an `ihealth_bp_measurement` event that already fired (or automations it
triggered), and the sensors' short-term history keeps the old value until the recorder purges it.

## Options

**Settings → Devices & services → iHealth Blood Pressure → Configure**

- **Delete readings from the cuff after importing them** (default **on**). This is what the iHealth
  app does. Readings are only deleted after Home Assistant has saved them. Turn it off if you still
  use the iHealth app as well; the cuff then keeps up to 99 readings until something else clears it,
  and Home Assistant skips the ones it already has.
- **Hold new readings for review before importing them** (default **off**). New readings arrive
  unticked in the Readings list. Tick one to import it (sensors, statistics and event), or delete it
  to discard it.

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
- **Readings at the wrong time:** the cuff stores local time with no time zone; it is set from Home
  Assistant's time zone on every sync. Home Assistant can only correct the clock when it connects, so
  after a daylight-saving change, or a battery swap that resets the cuff's clock, a reading taken
  before the next sync is stamped with the cuff's stale clock. That reading keeps the wrong time;
  later readings are correct.

The wire protocol is documented in [docs/protocol.md](docs/protocol.md).

## License

MIT
