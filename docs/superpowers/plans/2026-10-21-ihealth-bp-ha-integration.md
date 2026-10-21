# iHealth BP (KN-550BT) Home Assistant Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A HACS-installable custom integration `ihealth_bp` that syncs an iHealth KN-550BT cuff over Bluetooth (proxies included) and fully replaces the iHealth app.

**Architecture:** A vendored, HA-free protocol package (`custom_components/ihealth_bp/kn550bt/`) with two transports (current `com.jiuan.dev` firmware, verified; legacy `BPAV21/BPAV10`, untested) behind one session API. The HA side is an `ActiveBluetoothDataUpdateCoordinator` that runs one session per cuff wake, a persistent reading log that is the source of truth, external statistics rebuilt from that log, and entities (sensor, binary_sensor, switch, todo) derived from coordinator state + log.

**Tech Stack:** Python 3.14, Home Assistant 2026.10, bleak 3 / bleak-retry-connector 4 (provided by HA), pytest + pytest-homeassistant-custom-component 0.13.373 (in Docker), GitHub Actions (hassfest, HACS action).

**Spec:** `docs/superpowers/specs/2026-10-21-ihealth-bp-ha-integration-design.md`

## Global Constraints

- Domain `ihealth_bp`; display name "iHealth Blood Pressure"; repo `NickLD/hass-ihealth-bp`; MIT licence; codeowner `@NickLD`.
- Target HA 2026.10 (owner runs 2026.10.2). `hacs.json` `"homeassistant": "2026.10.0"`.
- No extra pip requirements in `manifest.json`; use the bleak / bleak-retry-connector that HA ships.
- `kn550bt/` must never import `homeassistant`.
- Never commit `apk/`, `decompiled/`, `native/`, `.venv*/`, or any iHealth binary/decompiled code. Public docs describe the protocol in our own words.
- Measurement sensors (systolic, diastolic, pulse, pulse pressure, MAP) have **no `state_class`**; battery uses `measurement`.
- Option labels (exact copy): "Delete readings from the cuff after importing them (this is what the iHealth app does — turn off if you still use the app)", default on; "Hold new readings for review before importing them", default off.
- Legacy firmware must be labelled **untested** in the README support table, a one-time `WARNING` log on setup, and the Protocol sensor's `untested: true` attribute.
- Event name `ihealth_bp_measurement`; action `ihealth_bp.delete_reading`.
- Cuff timestamps are naive local time; convert with HA's configured time zone.
- Tests: protocol-only tests run on Windows (`.venv/Scripts/python -m pytest tests/kn550bt -q`); everything else via `scripts/test.sh` (Docker, Python 3.14).

## Review Focus

1. **Empty offline-data reply** (`A0 04 .. A1 4A` with no data bytes, seen live) — must yield zero readings, not `IndexError`. Test in Task 3.
2. **Sync interrupted after readings were downloaded** (disconnect, timeout, cuff sleeps) — nothing deleted from the cuff, readings already persisted stay, next wake does not duplicate them. Test in Task 7.
3. **Memory full / multi-page download** (99 readings over several `0x4A` replies with the "more" flag) — all 99 parsed in order. Test in Task 3.
4. **Time zone / DST** — a cuff time of `2026-11-01 01:30:00` in `America/Chicago` maps to one well-defined UTC instant and survives a restart round-trip. Test in Task 4.
5. **Deleting the only reading in an hour** — that hour disappears from the statistics series instead of keeping a stale mean. Test in Task 5.

---

### Task 1: Repository scaffold and vendored protocol package

**Files:**
- Create: `.gitignore`, `LICENSE` (MIT, 2026 NickLD), `hacs.json`, `custom_components/ihealth_bp/manifest.json`, `custom_components/ihealth_bp/const.py`, `custom_components/ihealth_bp/__init__.py` (stub: `async_setup_entry`/`async_unload_entry` returning True), `docker/test.Dockerfile`, `scripts/test.sh`, `requirements_test.txt`, `pyproject.toml` (pytest config only), `tests/kn550bt/conftest.py`
- Move: `ihealth_kn550bt/protocol.py` → `custom_components/ihealth_bp/kn550bt/protocol.py`; `ihealth_kn550bt/client.py` → delete (replaced in Task 3); `tests/test_protocol.py` → `tests/kn550bt/test_protocol_v2.py`
- Delete: `tools/probe.py`, `tools/display.py` (spikes)

**Interfaces:**
- Produces: package `kn550bt` importable as top-level in protocol tests (conftest inserts `custom_components/ihealth_bp` on `sys.path`) and as `custom_components.ihealth_bp.kn550bt` inside HA.
- Produces `const.py`: `DOMAIN = "ihealth_bp"`, `CONF_DELETE_AFTER_IMPORT = "delete_after_import"`, `CONF_REVIEW_MODE = "review_mode"`, `EVENT_MEASUREMENT = "ihealth_bp_measurement"`, `SERVICE_DELETE_READING = "delete_reading"`, `POLL_INTERVAL_S = 30`.

- [ ] **Step 1:** `git init`, write `.gitignore` (`apk/ decompiled/ native/ .venv*/ __pycache__/ *.pyc .pytest_cache/ decompiled.log`). Confirm with `git status --porcelain --ignored` that `apk/`, `decompiled/`, `native/` show as ignored.
- [ ] **Step 2:** Move files as listed; fix the test import to `from kn550bt import protocol as p`; add `tests/kn550bt/conftest.py` that inserts the path.
- [ ] **Step 3:** Run `.venv/Scripts/python -m pytest tests/kn550bt -q` → 7 passed.
- [ ] **Step 4:** Write `manifest.json`: `domain`, `name`, `version "0.1.0"`, `config_flow: true`, `integration_type: "device"`, `iot_class: "local_polling"`, `dependencies: ["bluetooth_adapters", "recorder"]`, `codeowners`, `documentation`/`issue_tracker` URLs for the repo, `requirements: []`, `bluetooth` matchers `{"service_uuid": "636f6d2e-6a69-7561-6e2e-646576000000", "connectable": true}`, same for `…-425041563231` and `…-425041563130`.
- [ ] **Step 5:** `docker/test.Dockerfile`: `FROM python:3.14-slim`, `pip install -r requirements_test.txt`. `requirements_test.txt`: `pytest-homeassistant-custom-component==0.13.373` plus HA's bluetooth/usb/recorder requirements pinned as in 2026.10.2 (`bleak==3.0.2 bleak-retry-connector==4.7.1 bluetooth-adapters==2.4.0 bluetooth-auto-recovery==1.6.4 bluetooth-data-tools==1.29.24 dbus-fast==5.0.22 habluetooth==7.1.2 aiousbwatcher==1.1.2 serialx==1.11.0 SQLAlchemy==2.0.54 fnv-hash-fast==2.0.3 psutil-home-assistant==0.0.1`). `scripts/test.sh`: build image `ihealth-bp-test`, run `pytest "$@"` with the repo mounted at `/src` (`MSYS_NO_PATHCONV=1`, `-w /src`).
- [ ] **Step 6:** Add `tests/ha/test_smoke.py::test_setup_entry` that creates a `MockConfigEntry(domain="ihealth_bp", unique_id="00:4D:32:65:0E:89", data={"address": ...})` and asserts `await hass.config_entries.async_setup(entry.entry_id)` is True (with `enable_custom_integrations` + `enable_bluetooth` fixtures in `tests/ha/conftest.py`). Run `scripts/test.sh -q` → all pass.
- [ ] **Step 7:** Commit (include the spec and this plan): `git add -A && git commit -m "chore: scaffold ihealth_bp integration and vendored protocol package"`

### Task 2: Legacy firmware transport (BPAV21/BPAV10), untested on hardware

**Files:**
- Create: `custom_components/ihealth_bp/kn550bt/xxtea.py`, `custom_components/ihealth_bp/kn550bt/transport_v1.py`, `tests/kn550bt/test_transport_v1.py`, `tests/kn550bt/vectors_v1.json`
- Modify: `kn550bt/protocol.py` — move `xxtea2_*` into `xxtea.py` (re-export to keep imports working)

**Interfaces:**
- Produces `xxtea.py`: `xxtea2_encrypt(data, key) -> bytes`, `xxtea2_decrypt(data, key) -> bytes | None` (existing), `xxtea_be_encrypt(data: bytes, key: bytes) -> bytes` (standard XXTEA, big-endian 32-bit words, no length word; matches `com.ihealth.communication.ins.XXTEA.encrypt(byte[],byte[])`).
- Produces `transport_v1.py`:
  - `LEGACY_KEYS = {"KN-550BT": bytes.fromhex("5835d27714e6e2da4de3795f6565ceb4"), "KN-550BT_BPAV21": bytes.fromhex("b51dfe0438ba4f897837979124e23fcc")}`; `KEY_WRAP = b"Ch/HQ4LzItYT42s="`
  - `legacy_ka(name: str) -> bytes` = `xxtea_be_encrypt(nibble_swap(LEGACY_KEYS[name]), nibble_swap(KEY_WRAP))`
  - `legacy_identify_answer(challenge48: bytes, name: str) -> bytes` — mirrors `IdentifyIns.deciphering`: split into blocks b0,b1,b2; `k = xxtea_be_encrypt(word_swap(b0), ka)`; (b1 encryption result is discarded in the app — do the same, i.e. ignore b1); `out = word_swap(xxtea_be_encrypt(word_swap(b2), k))`; return `bytes([0xA1, 0xFC]) + out`. `word_swap` reverses byte order within each 4-byte word.
  - `class V1Framer`: `build(payload: bytes) -> list[bytes]` (single frame ≤15 bytes; else 14-byte fragments with flag `(n<<4)+n-i`, header `B0 len flag seq A1`, per-fragment checksum = sum of bytes[2:-1]), `ack_for(frame: bytes) -> bytes | None` (`B0 03 (A0|flag&0F) seq+1 A1 sum`; None for flag `F0` and 6-byte ACK frames), `feed(chunk: bytes) -> list[Packet]` (reassemble fragments by index per `BleUnPackageData`), with the sequence rules from `BleCommProtocol.b/c/d/unPackageData`.

- [ ] **Step 1:** Generate `vectors_v1.json` with a throwaway Java harness compiled from the local decompiled `XXTEA.java`, `IdentifyIns.c/d/deciphering` and the two key tables: 20 random 48-byte challenges × both names → expected 18-byte answers; 50 random `xxtea_be_encrypt` cases. Keep the harness in the scratchpad, not the repo.
- [ ] **Step 2:** Write tests: `test_xxtea_be_matches_java_vectors`, `test_legacy_identify_matches_java_vectors` (parametrised over `vectors_v1.json`), `test_v1_single_frame` (`build(A1 20 00 00 00)` with seq 1 → `B0 07 00 01 A1 20 00 00 00 C2`), `test_v1_fragmented_identify_has_two_fragments_flags_11_10`, `test_v1_ack_for_data_frame` (rx `A0 07 00 05 A1 20 64 00 00 2A` → `B0 03 A0 06 A1 47`), `test_v1_no_ack_for_ack_frame`, `test_v1_reassembles_two_fragment_reply`.
- [ ] **Step 3:** Run `.venv/Scripts/python -m pytest tests/kn550bt/test_transport_v1.py -q` → FAIL (module missing).
- [ ] **Step 4:** Implement `xxtea.py` and `transport_v1.py` to the interfaces above.
- [ ] **Step 5:** Run the protocol tests → all pass.
- [ ] **Step 6:** Commit `feat(kn550bt): legacy BPAV21/BPAV10 transport (untested on hardware)`.

### Task 3: Session API over both transports

**Files:**
- Create: `kn550bt/variants.py`, `kn550bt/transport_v2.py` (current framing/auth extracted from `protocol.py`), `kn550bt/session.py`, `tests/kn550bt/fake_cuff.py`, `tests/kn550bt/test_session.py`
- Modify: `kn550bt/protocol.py` (keep commands, records, parsing; framing moves to transport_v2), `tools/scan.py`, `tools/sync.py` (use `session.py`)

**Interfaces:**
- Produces `variants.py`: `class Variant(StrEnum): DEV = "com.jiuan.dev"; BPAV21 = "com.jiuan.BPAV21"; BPAV10 = "com.jiuan.BPAV10"`; `SERVICE_UUIDS: dict[Variant, str]`; `variant_from_service_uuids(uuids: Iterable[str], local_name: str | None) -> Variant | None` (BPAV10 only if `"550" in local_name`); `Variant.untested -> bool` (True for BPAV21/BPAV10); `write_uuid(v)`, `notify_uuid(v)`.
- Produces `session.py`:
  - `@dataclass DeviceInfo(model: str, serial: str, firmware: str, hardware: str, protocol_string: str, variant: Variant)`; `protocol_label` property → e.g. `"com.jiuan.dev (BPAV21)"`.
  - `@dataclass DisplaySettings(backlight: bool, clock: bool)`
  - `@dataclass Capabilities(memory_groups: int, capacity: int, display_settable: bool)`
  - `class SessionError(Exception)` with `stage: str`.
  - `class KN550BTSession(client: BleakClient, variant: Variant, *, timeout: float = 5.0)`: `async read_device_info() -> DeviceInfo`; `async open() -> None` (notify + authenticate; legacy name = `"KN-550BT_BPAV21"` if protocol string in {BPAV21, BPAV22} else `"KN-550BT"`); `async set_clock(now: datetime) -> Capabilities`; `async battery() -> int`; `async get_display() -> DisplaySettings`; `async set_display(s: DisplaySettings) -> None` (`0x61`, bit0 backlight, bit1 clock); `async read_readings() -> list[Reading]` (count via `0x40` memory 1; if 0 return []; `0x4A` for BPAV21 protocol string else `0x46`; loop while data[1] != 0; tolerate empty data); `async delete_readings() -> None` (`0x47`).
- Consumes: `transport_v1.V1Framer`, `legacy_identify_answer`, `protocol.Reading`, `parse_records_av21`, `parse_records_legacy`.

- [ ] **Step 1:** Write `fake_cuff.py`: a fake BleakClient (`start_notify`, `write_gatt_char`, `read_gatt_char`, `services.get_characteristic`) driving a scripted `com.jiuan.dev` cuff from the captured frames in `test_protocol_v2.py`, plus configurable stored readings, display mask, and a `fail_on_cmd` hook.
- [ ] **Step 2:** Write tests: `test_full_sync_against_fake` (info, auth, set_clock returns `Capabilities(1, 99, True)`, battery 100, display `(True, True)`, two readings 125/64 and 121/71), `test_empty_offline_reply_returns_no_readings` (Review Focus 1), `test_ninety_nine_readings_over_multiple_pages` (Review Focus 3: 99 records split across 5 replies, all returned in order), `test_set_display_sends_mask` (both off → payload `A1 61 00 00 00`), `test_error_reply_raises_session_error_with_stage`, `test_variant_detection` (dev UUID → DEV; AV10 without "550" → None; AV10 with "KN-550BT" → BPAV10).
- [ ] **Step 3:** Run → FAIL. Implement. Run `.venv/Scripts/python -m pytest tests/kn550bt -q` → all pass.
- [ ] **Step 4:** Update `tools/sync.py` to use the session (flags `--set-clock`, `--delete`, `--display MASK`), and live-check with the owner: one read-only run against the real cuff (`tools/sync.py --wait 180`) prints device info and readings.
- [ ] **Step 5:** Commit `feat(kn550bt): session API over current and legacy transports`.

### Task 4: Reading log storage and derived values

**Files:**
- Create: `custom_components/ihealth_bp/storage.py`, `custom_components/ihealth_bp/derived.py`, `tests/ha/test_storage.py`, `tests/ha/test_derived.py`

**Interfaces:**
- Produces `derived.py` (no HA imports): `pulse_pressure(sys, dia) -> int`; `mean_arterial_pressure(sys, dia) -> float` (`round(dia + (sys - dia) / 3, 1)`); `bp_category(sys, dia) -> str` in `("normal","elevated","hypertension_stage_1","hypertension_stage_2","hypertensive_crisis")` per ACC/AHA 2017 (crisis: sys>180 or dia>120; stage 2: sys≥140 or dia≥90; stage 1: sys 130–139 or dia 80–89; elevated: sys 120–129 and dia<80; else normal).
- Produces `storage.py`:
  - `class ReadingStatus(StrEnum): IMPORTED, PENDING, DELETED`
  - `@dataclass LoggedReading(uid: str, measured_at: datetime  # aware UTC, systolic: int, diastolic: int, pulse: int, irregular_pulse: bool, body_movement: bool, status: ReadingStatus)`
  - `reading_uid(r: Reading) -> str` = `f"{r.time:%Y%m%d%H%M%S}-{r.systolic}-{r.diastolic}-{r.pulse}"`
  - `class CuffStore(hass, entry_id)` (HA `Store`, version 1, key `f"ihealth_bp.{entry_id}"`, document `{"readings": [...], "pending_display": {...} | None}`): `async async_load()`; `async async_add(readings: list[Reading], *, review: bool) -> list[LoggedReading]` (returns only new ones, oldest first, saved before returning; cuff naive time → `dt_util.as_utc(t.replace(tzinfo=dt_util.get_default_time_zone()))`); `async async_set_status(uid: str, status: ReadingStatus) -> LoggedReading`; `latest_imported() -> LoggedReading | None`; `visible() -> list[LoggedReading]` (not deleted, newest first); `imported() -> list[LoggedReading]`; `find(uid) -> LoggedReading | None`; `find_by_time(measured_at: datetime) -> LoggedReading | None`; `pending_display` get/`async_set_pending_display(DisplaySettings | None)`.

- [ ] **Step 1:** Tests: `test_bp_category_boundaries` (119/79 normal, 120/79 elevated, 130/79 stage_1, 129/80 stage_1, 140/80 stage_2, 181/80 crisis, 120/121 crisis), `test_map_and_pulse_pressure` (125/64 → 61 and 83.0), `test_add_dedupes_including_deleted`, `test_review_mode_adds_pending`, `test_latest_imported_ignores_pending_and_deleted`, `test_store_round_trip_after_reload`, `test_dst_ambiguous_time_round_trip` (Review Focus 4: tz `America/Chicago`, cuff `2026-11-01 01:30:00` → stored aware UTC, reload gives the same instant).
- [ ] **Step 2:** Run `scripts/test.sh tests/ha/test_storage.py tests/ha/test_derived.py -q` → FAIL. Implement. Re-run → pass.
- [ ] **Step 3:** Commit `feat: reading log storage and derived BP values`.

### Task 5: External statistics from the log

**Files:**
- Create: `custom_components/ihealth_bp/statistics.py`, `tests/ha/test_statistics.py`

**Interfaces:**
- Produces: `statistic_id(address: str, metric: str) -> str` = `f"ihealth_bp:{address.replace(':','').lower()}_{metric}"` for metrics `systolic`, `diastolic`, `pulse`; `hourly_buckets(readings: list[LoggedReading]) -> dict[str, list[StatisticData]]` (pure: per metric, per hour start, `mean/min/max/state` where state = last reading in the hour); `async async_update_statistics(hass, address: str, device_name: str, readings: list[LoggedReading], hours: set[datetime]) -> None` (re-adds the given hour buckets from `readings`; if any hour in `hours` now has no readings, clear the three ids via `recorder.get_instance(hass).async_clear_statistics` and re-add every hour). Metadata: `source=DOMAIN`, `has_sum=False`, `mean_type=StatisticMeanType.ARITHMETIC`, `unit_class=None`, units `mmHg`/`mmHg`/`bpm`, `name=f"{device_name} {Metric}"`.
- Consumes: `storage.LoggedReading` (only `IMPORTED` ones are passed in).

- [ ] **Step 1:** Tests (with `recorder_mock`): `test_two_readings_same_hour_mean_min_max`, `test_reading_lands_in_its_measurement_hour_not_sync_hour`, `test_deleting_only_reading_in_hour_removes_that_hour` (Review Focus 5: after delete, `statistics_during_period` has no row for that hour), `test_deleting_one_of_two_recomputes_hour`.
- [ ] **Step 2:** Run → FAIL. Implement. Run → pass.
- [ ] **Step 3:** Commit `feat: long-term statistics keyed by measurement time`.

### Task 6: Config flow, options flow, translations

**Files:**
- Create: `custom_components/ihealth_bp/config_flow.py`, `strings.json`, `translations/en.json`, `tests/ha/test_config_flow.py`

**Interfaces:**
- Produces: config entry `data = {"address": str, "variant": Variant value}`; `options = {CONF_DELETE_AFTER_IMPORT: bool, CONF_REVIEW_MODE: bool}`; abort reasons `already_configured`, `not_supported`, `no_devices_found`.
- Consumes: `variants.variant_from_service_uuids`, `session.KN550BTSession.read_device_info`.

Flow: `async_step_bluetooth` (set unique id = address, abort if configured; variant from advertisement or `not_supported`; for `DEV`, try reading model 0x2A24 within 10 s while the cuff is awake — a model other than `KN-550BT` aborts `not_supported`, an unreadable model continues and is re-checked on first sync) → `async_step_bluetooth_confirm` (title "KN-550BT"; untested variants show a description placeholder warning) → entry. `async_step_user` lists discovered matching addresses. Options flow: the two booleans with the exact labels from Global Constraints.

- [ ] **Step 1:** Tests: `test_bluetooth_discovery_creates_entry` (patched model read → "KN-550BT"), `test_bluetooth_discovery_aborts_for_other_model` ("BG5S" → `not_supported`), `test_unreadable_model_still_offers_setup`, `test_user_step_lists_discovered`, `test_already_configured`, `test_options_defaults_and_update` (defaults True/False).
- [ ] **Step 2:** Run → FAIL. Implement. Run → pass.
- [ ] **Step 3:** Commit `feat: config and options flow`.

### Task 7: Sync coordinator

**Files:**
- Create: `custom_components/ihealth_bp/coordinator.py`, `tests/ha/test_coordinator.py`
- Modify: `custom_components/ihealth_bp/__init__.py` (create store + coordinator, forward platforms `sensor, binary_sensor, switch, todo`, one-time legacy warning, options update listener reloads entry)

**Interfaces:**
- Produces `coordinator.py`:
  - `@dataclass CuffState(info: DeviceInfo | None, battery: int | None, display: DisplaySettings | None, capabilities: Capabilities | None, last_sync: datetime | None, last_failure: datetime | None, failure_stage: str | None, failure_reason: str | None, rssi: int | None)`
  - `class IHealthBPCoordinator(ActiveBluetoothDataUpdateCoordinator[None])`: `state: CuffState`; `store: CuffStore`; `needs_poll(service_info, seconds_since_last_poll) -> bool` (hass running and (None or > `POLL_INTERVAL_S`)); `async _async_poll(service_info) -> None` runs one session: connect with `bleak_retry_connector.establish_connection(BleakClientWithServiceCache, ble_device, name, max_attempts=2)`; read info (abort with repair issue `unsupported_device` if model ≠ "KN-550BT"); open; `set_clock(dt_util.now())`; battery; get_display; apply `store.pending_display` if set and differs, then clear it; `read_readings()`; `store.async_add(..., review=options[CONF_REVIEW_MODE])`; for each new IMPORTED reading oldest-first call `async_import_reading`; `async_update_statistics` for affected hours; if `options[CONF_DELETE_AFTER_IMPORT]` and readings were read, `delete_readings()`; set `last_sync`; on any exception record `last_failure/stage/reason`, log, re-raise nothing (next wake retries). Always disconnect.
  - `async_import_reading(r: LoggedReading) -> None`: fire `EVENT_MEASUREMENT` with `device_id, address, measured_at (isoformat, HA tz), systolic, diastolic, pulse, irregular_pulse, body_movement`; notify listeners.
  - `async_request_display(s: DisplaySettings) -> None` (persists pending), `async_delete_reading(uid) -> None`, `async_approve_reading(uid) -> None` (used by Task 9).
- Consumes: Tasks 3–5.

- [ ] **Step 1:** Tests (patch `establish_connection` to return the fake cuff client from Task 3): `test_sync_imports_events_and_deletes` (2 events, cuff empty afterwards, `last_sync` set), `test_coexist_mode_does_not_delete_and_second_sync_adds_nothing`, `test_failure_after_download_does_not_delete_and_no_duplicates_next_time` (Review Focus 2: fake raises on `0x47`… and separately on disconnect after readings; cuff still holds them; second sync imports 0 new, deletes them), `test_failure_before_download_persists_nothing`, `test_pending_display_applied_and_cleared`, `test_wrong_model_raises_repair_issue`, `test_needs_poll_threshold`.
- [ ] **Step 2:** Run → FAIL. Implement. Run → pass.
- [ ] **Step 3:** Commit `feat: sync coordinator`.

### Task 8: Sensors, binary sensors, switches, diagnostics

**Files:**
- Create: `entity.py`, `sensor.py`, `binary_sensor.py`, `switch.py`, `diagnostics.py`, `icons.json`, `tests/ha/test_entities.py`, `tests/ha/test_diagnostics.py`
- Modify: `strings.json`, `translations/en.json` (entity names)

**Interfaces:**
- Consumes: `IHealthBPCoordinator.state`, `store.latest_imported()`, `derived.*`, `async_request_display`.
- Entities (translation keys → behaviour): sensors `systolic` (mmHg), `diastolic` (mmHg), `pulse` (bpm), `measured_at` (TIMESTAMP), `battery` (BATTERY, `measurement`), `pulse_pressure` (mmHg), `mean_arterial_pressure` (mmHg, 1 decimal), `bp_category` (ENUM, options as in Task 4); diagnostic sensors `protocol` (state = `protocol_label`, attribute `untested`), `last_sync` (TIMESTAMP), `last_failure` (TIMESTAMP, attributes `stage`, `reason`), `signal_strength` (SIGNAL_STRENGTH dBm, disabled by default); binary sensors `irregular_pulse`, `body_movement` (PROBLEM device class off); switches `backlight`, `clock_display` (CONFIG category; `is_on` = pending value if pending else actual; attribute `pending: true` while waiting). Measurement sensors restore last value via `RestoreSensor`. Device info: manufacturer "iHealth", model "KN-550BT", sw/hw versions, connection `bluetooth` address.
- Diagnostics: entry options, `CuffState` (address redacted), store counts by status, last 5 readings.

- [ ] **Step 1:** Tests: `test_sensors_after_sync` (125/64/69 then 121/71/68 → state shows latest, category "elevated" for 121/71, MAP 87.7), `test_measurement_sensors_have_no_state_class`, `test_values_restore_after_restart`, `test_switch_toggle_sets_pending_then_reflects_device_after_sync`, `test_protocol_sensor_untested_attribute_for_legacy`, `test_diagnostics_redacts_address`.
- [ ] **Step 2:** Run → FAIL. Implement. Run → pass.
- [ ] **Step 3:** Commit `feat: sensor, binary sensor, switch entities and diagnostics`.

### Task 9: Readings to-do list, delete action, review mode

**Files:**
- Create: `todo.py`, `services.yaml`, `tests/ha/test_todo.py`
- Modify: `__init__.py` (`async_setup` registers `delete_reading`), `strings.json`, `translations/en.json`

**Interfaces:**
- Consumes: `CuffStore.visible/find/find_by_time`, `IHealthBPCoordinator.async_delete_reading/async_approve_reading`.
- Todo entity `readings`: features `DELETE_TODO_ITEM | UPDATE_TODO_ITEM`; items newest first; `uid` = reading uid; `summary` = local time as "Oct 21 15:09" (day without leading zero) + `f" — {sys}/{dia}, pulse {pulse}"`; `description` lists flags when set ("Irregular pulse", "Body movement"); `status` COMPLETED for imported, NEEDS_ACTION for pending. `async_update_todo_item`: only allowed change is NEEDS_ACTION→COMPLETED on a pending item (→ approve); anything else raises `ServiceValidationError`. `async_delete_todo_items(uids)` → delete each.
- `async_delete_reading(uid)`: mark DELETED; if it was imported, `async_update_statistics` for its hour and notify sensors (they fall back to the new `latest_imported`). `async_approve_reading(uid)`: PENDING→IMPORTED, `async_import_reading`, statistics for its hour.
- Action `ihealth_bp.delete_reading`: fields `device_id` (device selector, integration ihealth_bp) and `measured_at` (datetime selector, HA local time, matched to the second); raises `ServiceValidationError` if not found.

- [ ] **Step 1:** Tests: `test_todo_lists_readings_newest_first_completed`, `test_delete_latest_rolls_sensors_back`, `test_delete_action_by_time`, `test_review_mode_pending_then_approve_fires_event`, `test_review_mode_delete_pending_never_imports`, `test_cannot_create_or_rename_items`.
- [ ] **Step 2:** Run → FAIL. Implement. Run → pass.
- [ ] **Step 3:** Commit `feat: readings list, delete action and review mode`.

### Task 10: Docs, HACS metadata, CI

**Files:**
- Create: `README.md`, `docs/protocol.md`, `.github/workflows/validate.yml` (hassfest + `hacs/action` category integration), `.github/workflows/tests.yml` (Python 3.14, `pip install -r requirements_test.txt`, `pytest -q`)
- Modify: `hacs.json` (`name`, `render_readme: true`, `homeassistant: "2026.10.0"`)

README must cover: what it does; supported table (KN-550BT `com.jiuan.dev` fw 303 ✅ tested; `com.jiuan.BPAV21` / `BPAV10` ⚠️ untested — please open an issue with debug logs and diagnostics); install via HACS custom repository; proxy requirements (`bluetooth_proxy: active: true`, ESP32-C3 fine) and placement advice; the ~10 s wake window; delete-after-import and review options; Readings list and `ihealth_bp.delete_reading`; what deletion cannot undo (fired events, short-term sensor history); `ihealth_bp_measurement` event fields; statistics ids; unofficial/reverse-engineered disclaimer and "not a medical device". `docs/protocol.md`: the protocol in our own words from the spec (both variants), no decompiled code.

- [ ] **Step 1:** Write files. Run `scripts/test.sh -q` → all pass. Run hassfest locally: `MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)":/github/workspace ghcr.io/home-assistant/hassfest` → no errors.
- [ ] **Step 2:** Commit `docs: README, protocol notes, HACS metadata and CI`.

### Task 11: Live verification on the owner's Home Assistant

- [ ] **Step 1:** With the owner's OK, copy `custom_components/ihealth_bp/` into their HA config (`/config/custom_components/ihealth_bp/`) via the HA file tools, then ask before restarting HA.
- [ ] **Step 2:** Owner takes a reading in the office; confirm discovery → add → first sync: sensors populated, event in logbook/dev tools, cuff count 0 afterwards (delete on), `last_sync` set, statistics ids present.
- [ ] **Step 3:** Toggle Backlight off in HA, wake cuff, confirm the cuff display changed and the switch is no longer pending; toggle back.
- [ ] **Step 4:** Take a "bad" reading, delete it from the Readings list, confirm sensors roll back and the statistics hour updates.
- [ ] **Step 5:** Record results (and any fixes, each with a regression test) and commit.

### Task 12: Publish

- [ ] **Step 1:** Confirm with the owner, then `gh repo create NickLD/hass-ihealth-bp --public --source . --push`; verify `git ls-files | grep -E '^(apk|decompiled|native)/'` is empty **before** pushing.
- [ ] **Step 2:** Watch both workflows go green (`gh run watch`).
- [ ] **Step 3:** Tag `v0.1.0`, `gh release create v0.1.0 --generate-notes`.
- [ ] **Step 4:** Owner reinstalls through HACS (custom repository) to confirm the HACS path; HACS default-list submission is a later step after it has run reliably.
