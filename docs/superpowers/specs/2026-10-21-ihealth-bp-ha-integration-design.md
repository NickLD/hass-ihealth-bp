# iHealth KN-550BT Home Assistant integration — design

Date: 2026-10-21 · Owner: NickLD · Status: draft for review

## Intent

Bring readings from an iHealth KN-550BT blood pressure cuff into Home Assistant locally, over
Bluetooth (ESPHome Bluetooth proxies), with no iHealth app or cloud involved. HA should be able to
**replace the iHealth app entirely** for this cuff: import every reading with its true time, keep
the cuff's clock right, clear the cuff's memory after import (as the app does), and expose the
cuff's display settings. Someone who still wants the app can turn the clearing off.

The integration will be **published on GitHub and installable through HACS** for other KN-550BT
owners, modelled on the existing community BP integrations
([eigger/hass-omron](https://github.com/eigger/hass-omron),
[bkbilly/medisanabp_ble](https://github.com/bkbilly/medisanabp_ble)).

## Goals

- Zero-config discovery: the cuff shows up under Settings → Devices & Services when any
  connectable Bluetooth adapter or proxy hears it; one click to add. No pairing ritual.
- Every reading the cuff stores reaches HA exactly once, with the time it was taken — including
  backlogs from when no proxy was in range.
- Sensors that read like the Omron integration's, so dashboards and automations feel familiar.
- Cuff housekeeping the app normally does: set the clock every connection; delete imported
  readings (default on, can be turned off); backlight and clock-display switches.
- Bad readings can be removed afterwards from a list in the HA UI; optionally, readings can be held
  for review before import (as the iHealth app does).
- Support the older KN-550BT firmware variant too, clearly marked untested, inviting feedback.
- Publishable quality: HACS-installable, validated in CI, tested, documented.

## Non-goals

- Multiple users. The cuff reports one memory group (capacity 99); asking for groups 2/3 returns
  group 1's data. No per-user setup.
- Starting/stopping a measurement from HA (the protocol has commands for it; out of scope).
- Firmware updates, iHealth cloud upload, or any network traffic beyond HA.
- Medical interpretation beyond the standard derived values below.
- Upstreaming to HA core in this round (no PyPI library requirement).

## Anti-goals (failure even if it "works")

- **Losing a reading.** Deleting from the cuff before the reading is durably stored in HA, or
  skipping readings when several arrive at once.
- **Duplicating readings** on re-sync, restart, or when coexist mode leaves them on the cuff.
- **Silently surprising app users.** The deletion behaviour must be stated plainly in the option
  label and README.
- **Shipping the iHealth APK, decompiled sources, or extracted native library** in the public repo.

## Verified device facts (live, 2026-10-21, cuff fw 303 / hw 300)

Protocol was reverse engineered from iHealth MyVitals Pro 4.17.0 and confirmed against the owner's
cuff from a Windows PC with bleak. The working Python implementation and regression tests already
exist in `ihealth_kn550bt/` and `tests/test_protocol.py`.

- **Advertisement:** connectable, no local name, single 128-bit service
  `636f6d2e-6a69-7561-6e2e-646576000000` ("com.jiuan.dev"). iHealth reuses this UUID for other
  products (e.g. BG5S), so the model must be confirmed by reading Device Information 0x2A24
  (`"KN-550BT"`) before accepting a device.
- **Awake window:** the cuff advertises and accepts connections for ~10 s after a measurement or
  wake. A full session (connect excluded) takes ~250 ms.
- **GATT:** write `7265632e-…-646576000000` (write-without-response), notify
  `7365642e-…-646576000000`. Device Information: model 0x2A24, serial 0x2A25 (= MAC without
  colons), firmware 0x2A26, hardware 0x2A27, manufacturer 0x2A29; protocol string at 0xFF01
  (`com.jiuan.BPAV21`).
- **Framing:** TX `B0 len 00 seq A1 cmd args… sum`, written in 20-byte chunks; seq starts at 1 and
  steps by 2. RX is a byte stream of `A0 len flag seq A1 cmd data… sum` frames; no link ACK needed.
- **Auth:** mutual challenge with XXTEA (little-endian, length-suffixed variant) and a fixed key from
  the app; the cuff's challenge embeds its MAC. Success `0xFD`, failure `0xFE`. Verified working.
- **Commands used:** battery `0x20`; function info / set clock `0x21` (Y-2000, M, D, h, m, s; reply
  includes memory groups = 1, capacity = 99, backlight/clock settable); offline count `0x40`;
  offline data `0x4A` (BPAV21: 11-byte records `Y M D h m s (sys−dia) dia pulse scheme flags`,
  flags bit7 arrhythmia, bit4 body movement; reply byte 1 = "more pages" flag); transfer finished
  `0x47`; display get `0x60` / set `0x61` (bit0 backlight, bit1 clock); get time `0x62`; error
  `0x38`.
- **`0x47` permanently deletes** the downloaded readings: count drops to 0 immediately, stays 0
  after reconnect, and they no longer appear under the cuff's M button.
- **Display settings persist** and are visible on the cuff (verified off → on round trip).
- Cuff timestamps are naive local time with 1-second resolution.
- The cuff cannot delete individual readings; `0x47` is all-or-nothing.

## Older firmware variant (implement, untested)

Static analysis of the app shows KN-550BT units that advertise service
`636f6d2e-6a69-7561-6e2e-425041563231` ("com.jiuan.BPAV21") or
`…-425041563130` ("com.jiuan.BPAV10", only when the advertised name contains "550"). The app drives
them through a different stack (`BleCommProtocol` + `IdentifyIns`); the owner's cuff does not use it,
so nothing here has been run against hardware. Implementation reference: the local decompiled
sources (not published) and the summary below, which also goes into `docs/protocol.md`.

- GATT: same service UUID suffix pattern — write `7265632e-…`, notify `7365642e-…` with the matching
  `BPAV21`/`BPAV10` suffix.
- Framing: TX `B0 len flag seq A1 cmd … sum`; payloads over 15 bytes split into 14-byte fragments
  whose flag byte counts down (`(n<<4)+n-i`); seq starts at 1, steps by 2. RX frames `A0 …` must be
  acknowledged with `B0 03 (A0|flag&0F) rxseq+1 A1 sum` (except flag `F0`), and 6-byte RX frames are
  ACKs. Multi-fragment RX payloads are reassembled by fragment index.
- Auth: send `A1 FA R1[16]`; cuff answers `0xFB` with 48 bytes (three 16-byte blocks). Key =
  standard big-endian XXTEA encrypt of `nibbleswap(getKey(name))` under `nibbleswap("Ch/HQ4LzItYT42s=")`,
  where `getKey` is a fixed 16-byte table from the app's native library: name `KN-550BT_BPAV21` when
  the protocol string is BPAV21/BPAV22, otherwise `KN-550BT`. The answer is `A1 FC` + 16 bytes
  computed exactly as `IdentifyIns.deciphering` does (including its word-order swaps). `0xFD` = ok.
- Commands and record formats are the same `A1InSet_KN550BT` set; protocol string BPAV21 uses `0x4A`
  with 11-byte records, others use `0x46` with 10-byte records (`Y|arrhythmia M|hsd D h m (sys−dia)
  dia pulse …`).

Untested must be unmissable: README support table, a one-time log warning on setup, and the
Protocol diagnostic sensor; issues with debug logs are explicitly invited.

## How it behaves

### Setup
Bluetooth discovery on the service UUID → config flow connects once, reads 0x2A24, and only offers
devices whose model is `KN-550BT`. The entry's unique ID is the BLE address. Manual add lists
matching discovered devices. Setup confirms with the device name; no other questions.

### Each sync
Triggered when HA sees an advertisement from the cuff after it had gone quiet (i.e. once per wake),
using HA's active-Bluetooth coordinator pattern and `bleak-retry-connector`, through whichever
connectable adapter/proxy hears it best. In one connection:

1. Read Device Information (model, firmware, serial) — refreshes device registry info.
2. Authenticate.
3. Set the cuff clock to HA's local time (`0x21`); keep the capability info it returns.
4. Read battery, display settings; apply any pending display change (see Switches).
5. Read all stored readings (following the "more pages" flag).
6. Store new readings durably in HA (see De-duplication), then publish them.
7. If **delete after import** is on and step 6 succeeded, send `0x47`.

A failure at any step ends the session without deleting anything; the next wake retries. Readings
stay on the cuff until a later sync succeeds.

### Reading log (source of truth)
The integration keeps its own persistent log (HA `Store`) of every reading it has received: cuff
timestamp, values, flags, and a status (`imported`, `pending`, `deleted`). Sensors, statistics and
the Readings list are all derived from this log.

- **De-duplication:** a reading's identity is its cuff timestamp plus its values. Anything already
  in the log (any status, including `deleted`) is skipped, so readings left on the cuff in coexist
  mode are never re-imported and deleted ones never come back.
- The log is retained indefinitely (a few readings a day is small); `deleted` entries can be
  reduced to their identity only.

### Importing a reading (oldest first)
- Fire an `ihealth_bp_measurement` event: `device_id`, `address`, `measured_at` (aware, HA time
  zone), `systolic`, `diastolic`, `pulse`, `irregular_pulse`, `body_movement`.
- Update the measurement sensors if it is now the newest imported reading.
- Add it to the long-term statistics series keyed by **measurement** time, so history graphs show
  when readings were actually taken (see "Builder's choices" for the mechanism).

### Readings list and deleting bad readings
- A **to-do list entity** ("Readings") on the device lists readings newest first, e.g.
  `Oct 21 15:09 — 121/71, pulse 68` (irregular pulse / movement noted in the text or description).
  Imported readings are ticked (completed).
- Deleting an item marks the reading `deleted`, removes it from the statistics (recompute the
  affected hour), and if it was the newest, rolls the measurement sensors back to the previous
  imported reading.
- Action `ihealth_bp.delete_reading` (target: device; field: `measured_at`) does the same from
  scripts.
- Cannot be undone by deletion: events already fired (and automations they triggered), and the
  sensors' short-term state history (ages out with recorder retention). Documented in the README.
- Users should not be able to create or rename items; only tick (in review mode) and delete.

### Review mode (option, default off)
**Hold new readings for review before importing them** (as the iHealth app does). New readings enter
the log as `pending` and appear unticked in the Readings list. Ticking imports (sensors, statistics,
event); deleting discards. Cuff deletion (`0x47`) is unaffected: pending readings are safe in the log.
With the option off, readings are imported immediately and appear already ticked.

### Entities
- Sensors: systolic (mmHg), diastolic (mmHg), pulse (bpm), measured at (timestamp), battery (%),
  pulse pressure, mean arterial pressure, blood pressure category (ACC/AHA 2017, same bands as
  hass-omron).
- Binary sensors: irregular pulse, body movement (from the latest reading).
- Switches (configuration category): **Backlight**, **Clock display**.
- To-do list: **Readings** (above).
- Diagnostics: **Protocol** (service variant + protocol string, e.g. `com.jiuan.dev (BPAV21)`, with
  an `untested` attribute for the older variant), last sync (timestamp), last failure (with
  stage/reason as attributes), signal strength of the last connection, firmware version via device
  registry.
- Measurement sensors restore their last value after an HA restart (the cuff is unreachable most of
  the time).

### Switches (backlight, clock display)
The cuff is asleep almost always, so a toggle is stored as a desired value and applied at the next
connection. Each connection reads the actual setting and the switch reflects it (so a change made
from the app shows up). While a change is waiting, the switch shows the requested value with a
"pending until the cuff next connects" attribute.

### Options
- **Delete readings from the cuff after importing them** — default **on**, labelled to say this is
  what the iHealth app does and that turning it off is for people who also use the app. With it off,
  the cuff's 99-reading memory keeps filling until something else clears it.
- **Hold new readings for review before importing them** — default **off** (see Review mode).
- Clock sync is always on (not an option): the app does it and a wrong clock corrupts reading times.

## Publishing

- Repo `NickLD/hass-ihealth-bp` (name is my call), MIT licence, HACS custom-repository install
  first; submission to the HACS default list once it has run reliably.
- CI: hassfest, HACS action, pytest (protocol tests + integration tests with HA's test harness).
- README: supported model/firmware, proxy requirements (`bluetooth_proxy: active: true`; ESP32-C3
  works), placement advice (weak signal from ceiling-mounted proxies), the delete-after-import
  behaviour, unofficial/reverse-engineered disclaimer, troubleshooting with debug logging.
- `docs/protocol.md`: the protocol as documented above (clean-room description, no decompiled code).
- `apk/`, `decompiled/`, `native/` and other RE artefacts stay out of git (`.gitignore`).

## Builder's choices (decided by me, not the owner — flag if wrong)

- Domain `ihealth_bp`, display name "iHealth Blood Pressure"; leaves room for other iHealth BP models.
- Protocol code vendored inside the custom component as a package with no HA imports (the existing
  `ihealth_kn550bt` module, extended), plus the standalone CLI scripts in `tools/`.
- Statistics mechanism: external statistics (`async_add_external_statistics`) per metric, hourly
  mean/min/max at measurement time, alongside normal sensor state history. The builder may pick a
  different mechanism if it gives correct-time graphs without double-counting.
- Because of that, the systolic/diastolic/pulse/derived sensors carry **no `state_class`**, so the
  recorder does not compile a second, sync-time statistics series for them. Battery keeps
  `measurement`.
- "Once per wake" sync trigger: poll when an advertisement arrives and the last successful or
  attempted session is older than ~30 s (exact threshold left to the builder).
- Minimum HA version: whatever the coordinator/statistics APIs need, no newer than the owner's
  2026.10; target current stable.
- The Readings list uses a to-do entity because it is HA's built-in, mobile-friendly list with
  per-item delete; no custom card required.

## Left to the builder

Entity naming/translation keys, code structure, coordinator class choice, retry/backoff details
inside the awake window, test layout, icons, README wording (within the constraints above).

## Still unverified (test during build)

- Multi-page offline download (needs several stored readings; only 1–2 have been tested).
- Behaviour with the cuff's memory full (99 readings).
- Connection reliability through the office ceiling proxy at about −90 dBm.
- The entire older-firmware path (no hardware available; unit-test against hand-built frames and
  the Java implementation where possible, as was done for XXTEA2).
