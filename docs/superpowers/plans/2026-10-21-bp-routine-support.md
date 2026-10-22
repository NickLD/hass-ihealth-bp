# Measurement-Routine Support (v0.2.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the `ihealth_bp` integration about the morning/evening measurement routine (sessions, periods, context flags and notes, clean baseline averages, slot status, richer events and services) so users can build reminders and dashboards on top of it.

**Architecture:** A new pure-logic module `routine.py` (periods, BP days, sessions, baseline and slot summary) computed on demand from the existing reading log. `LoggedReading` gains `flags` and `note`. The coordinator exposes the summary, context and session-delete operations, and an enriched event. Entities on the existing `sensor`/`switch` platforms plus new `text` and `button` platforms read the summary. Options gain the four window times and a routine start date.

**Tech Stack:** Python 3.14, Home Assistant 2026.10, pytest + pytest-homeassistant-custom-component 0.13.373 (Docker via `scripts/test.sh`).

**Spec:** `docs/superpowers/specs/2026-10-21-bp-routine-support-design.md`

## Global Constraints

- Nothing about any particular user (routine, phone, presence, entity IDs, other automations) goes in code, tests, README or commits. The repo is public.
- The integration sends no notifications and knows nothing about presence or schedules beyond the period windows.
- Existing guarantees stay: no lost or duplicated readings, atomic store writes (`atomic_writes=True`), statistics rebuilt correctly after deletes. Existing tests keep passing unchanged.
- Diagnostics keep reporting only reading counts. Notes and flags are health data and never appear there.
- Default windows: morning 05:00–12:30, evening 21:00–03:00 (wraps midnight). A BP day starts at the morning window's start (05:00 by default). *(Plan's call: tying the day boundary to `morning_start`, rather than a fixed 05:00, keeps windows valid when a user moves them. Identical at the defaults.)*
- Session: readings no more than 10 minutes apart, chained.
- Fixed flag set, in this order: `caffeine`, `ate`, `exertion`, `after_shower`, `poor_sleep`, `alcohol`, `stressed`, `missed_meds`, `sick`.
- Clean reading: imported, in a `morning`/`evening` session, no flags, no `body_movement`, BP day ≥ routine start date. Baseline = mean of per-slot values, where a slot value is the mean of that slot's clean session means, and a session mean is the mean of its clean readings. Averages are rounded to 1 decimal.
- New measurement-style sensors have no `state_class` (matches the existing reading sensors).
- Run HA tests with `scripts/test.sh -q` (Docker). Bump `manifest.json` to `0.2.0`.
- Every new user-visible string goes in `strings.json` **and** `translations/en.json` (identical). Every new entity or service gets an icon in `icons.json`.

## Review Focus

1. **Backlog sync**: several readings from earlier days arrive in one sync. Every event's `session_index` and `period` must be right, and past days' slots count as filled. Test: Task 5, `test_backlog_events_have_correct_sessions`.
2. **After-midnight evening reading**: a 00:30 reading fills the *previous* BP day's evening slot. The evening slot sensor stays `filled` until 05:00, then the new day's morning slot is `open`. Test: Task 3, `test_after_midnight_reading_fills_previous_evening`.
3. **Deleting a slot's only reading** (from the to-do list, the service or the button) puts the slot back to `open`/`closed` and recomputes the baseline. Test: Task 6, `test_deleting_only_reading_reopens_slot`.
4. **Double Discard** (notification tapped twice, two concurrent `delete_session` calls): the second raises `reading_not_found`. Nothing crashes, and statistics are rebuilt once correctly. Test: Task 5, `test_concurrent_delete_session`.
5. **Upgrade and restart**: v0.1.x storage (no `flags`/`note` keys) loads. Flags and notes survive a reload. An entry without `routine_start` gets today's date once, without a reload loop. Tests: Task 2, `test_loads_v01_data_without_context`, `test_context_survives_reload`; Task 4, `test_routine_start_defaults_to_today_once`.

---

### Task 1: Periods, BP days and sessions

**Files:**
- Create: `custom_components/ihealth_bp/routine.py`
- Modify: `custom_components/ihealth_bp/const.py` (add `FLAGS`, option keys)
- Test: `tests/ha/test_routine.py`

**Interfaces:**
- Produces (`const.py`): `FLAGS: tuple[str, ...]` (order above); `CONF_MORNING_START = "morning_start"`, `CONF_MORNING_END = "morning_end"`, `CONF_EVENING_START = "evening_start"`, `CONF_EVENING_END = "evening_end"`, `CONF_ROUTINE_START = "routine_start"`.
- Produces (`routine.py`):
  - `class Period(StrEnum)`: `MORNING="morning"`, `EVENING="evening"`, `EXTRA="extra"`; `ROUTINE_PERIODS = (Period.MORNING, Period.EVENING)`.
  - `SESSION_GAP = timedelta(minutes=10)`.
  - `@dataclass(frozen=True) class Windows` with fields `morning_start: time = time(5)`, `morning_end: time = time(12, 30)`, `evening_start: time = time(21)`, `evening_end: time = time(3)`, and methods `valid() -> bool`, `slot_bounds(day: date, period: Period) -> tuple[datetime, datetime]` (aware, HA local time zone).
  - `windows_from_options(options: Mapping[str, Any]) -> Windows` (values are `"HH:MM:SS"` strings; missing keys use the defaults).
  - `bp_day(moment: datetime, windows: Windows) -> date` (aware input).
  - `period_of(moment: datetime, windows: Windows) -> Period`.
  - `@dataclass(frozen=True) class Session`: `readings: tuple[LoggedReading, ...]` (oldest first), `period: Period`, `day: date`; properties `start -> datetime`, `mean_systolic -> float`, `mean_diastolic -> float`, `mean_pulse -> float` (rounded to 1 decimal); `index_of(uid: str) -> int` (1-based); `measured_at -> list[datetime]`.
  - `group_sessions(readings: Iterable[LoggedReading], windows: Windows) -> list[Session]` (oldest first; a session's `period` and `day` come from its first reading).

All window maths uses each time's offset from `morning_start`, modulo 24 h, with an evening-end offset of 0 meaning 24 h. `valid()` is `0 < me <= es < ee`. `period_of`: offset `< me` → morning; `es <= offset < ee` → evening; otherwise extra. `bp_day` = local date of `moment − morning_start`.

- [ ] **Step 1: Write the failing tests.** Use the `hass` fixture and `await hass.config.async_set_time_zone("America/Chicago")`. Build `LoggedReading`s with a small local helper `reading(local_naive, sys, dia, pulse=70, **kw)` that converts with `storage.cuff_time_to_utc`.
  - `test_period_of_defaults`: 05:00 → morning; 12:29:59 → morning; 12:30 → extra; 20:59 → extra; 21:00 → evening; 00:30 → evening; 02:59:59 → evening; 03:00 → extra; 04:59 → extra.
  - `test_bp_day_shifts_at_morning_start`: 2026-10-22 00:30 → `date(2026, 10, 21)`; 2026-10-22 05:00 → `date(2026, 10, 22)`.
  - `test_windows_valid`: defaults valid; `Windows(morning_end=time(4))` invalid (end before start); `Windows(evening_start=time(12))` invalid (overlaps morning); `Windows(evening_end=time(6))` invalid (runs into the next morning); `Windows(evening_start=time(18), evening_end=time(23))` valid.
  - `test_slot_bounds`: `slot_bounds(date(2026,10,21), Period.EVENING)` == (2026-10-21 21:00, 2026-10-22 03:00) local aware.
  - `test_windows_from_options`: `{"morning_end": "11:00:00"}` → `Windows(morning_end=time(11))`, the others default.
  - `test_group_sessions_chains_within_10_min`: readings at 09:50:00, 09:51:10, 09:59:00, 10:12:00 → two sessions with sizes 3 and 1. The first has `period == Period.MORNING` and `index_of(third.uid) == 3`. Means of (120/80, 124/82, 122/78) → `mean_systolic == 122.0`, `mean_diastolic == 80.0`.
  - `test_session_period_from_first_reading`: 12:25 and 12:31 readings form one morning session.
- [ ] **Step 2:** Run `scripts/test.sh tests/ha/test_routine.py -q` → FAIL (module missing).
- [ ] **Step 3:** Implement `const.py` additions and `routine.py` per the Interfaces block. `routine.py` may import `homeassistant.util.dt` and `.storage.LoggedReading`.
- [ ] **Step 4:** Run `scripts/test.sh tests/ha/test_routine.py -q` → PASS.
- [ ] **Step 5:** Commit: `git commit -m "feat: routine periods, BP days and sessions"`.

### Task 2: Context flags and notes in the reading log

**Files:**
- Modify: `custom_components/ihealth_bp/storage.py`
- Modify: `custom_components/ihealth_bp/todo.py` (`reading_description`)
- Test: `tests/ha/test_storage.py`, `tests/ha/test_todo.py`

**Interfaces:**
- Consumes: `const.FLAGS`.
- Produces: `LoggedReading.flags: tuple[str, ...] = ()` and `LoggedReading.note: str | None = None` (last fields, with defaults); `as_dict` writes both; `from_dict` uses `.get` defaults. `CuffStore.async_set_context(uids: Iterable[str], *, flags: Iterable[str] | None = None, add_flags: Iterable[str] = (), remove_flags: Iterable[str] = (), note: str | None = None) -> list[LoggedReading]`: `flags` replaces the set, then `add_flags`/`remove_flags` apply. The result is deduplicated and kept in `FLAGS` order. `note=None` leaves the note unchanged, `note=""` clears it (stored as `None`). One save for all uids; returns the updated readings.

- [ ] **Step 1: Write the failing tests** in `test_storage.py`:
  - `test_set_context_flags_and_note`: after `async_set_context([uid], add_flags=["stressed", "caffeine"], note="after stairs")`, `find(uid).flags == ("caffeine", "stressed")` and `.note == "after stairs"`. Then `remove_flags=["caffeine"]` → `("stressed",)`; `note=""` → `None`; `note=None` → unchanged.
  - `test_context_survives_reload`: set context, build a new `CuffStore` on the same key, `async_load`, values equal.
  - `test_loads_v01_data_without_context`: seed the `Store` with a v0.1 reading dict (no `flags`/`note`). It loads with `flags == ()` and `note is None`.

  In `test_todo.py`:
  - `test_description_lists_context`: a reading with `irregular_pulse`, flag `caffeine` and note `"x"` has description `"Irregular pulse, Had caffeine — x"`.
- [ ] **Step 2:** Run `scripts/test.sh tests/ha/test_storage.py tests/ha/test_todo.py -q` → new tests FAIL.
- [ ] **Step 3:** Implement. In `todo.py`, add `FLAG_LABELS` (English, like the existing labels): caffeine "Had caffeine", ate "Just ate", exertion "After exertion", after_shower "After shower", poor_sleep "Poor sleep", alcohol "Alcohol last night", stressed "Stressed", missed_meds "Missed meds", sick "Sick". The description is the comma-joined cuff markers then flag labels, then `" — " + note` if a note exists, or `None` when all are empty.
- [ ] **Step 4:** Run `scripts/test.sh tests/ha -q` → all PASS.
- [ ] **Step 5:** Commit: `git commit -m "feat: store context flags and notes with readings"`.

### Task 3: Baseline and slot summary

**Files:**
- Modify: `custom_components/ihealth_bp/routine.py`
- Test: `tests/ha/test_routine.py`

**Interfaces:**
- Consumes: Task 1 types; `LoggedReading.flags`.
- Produces:
  - `class SlotStatus(StrEnum)`: `FILLED="filled"`, `OPEN="open"`, `UPCOMING="upcoming"`, `CLOSED="closed"`.
  - `@dataclass(frozen=True) class Mean`: `systolic: float`, `diastolic: float`.
  - `@dataclass(frozen=True) class SlotInfo`: `status: SlotStatus`, `window_start: datetime`, `window_end: datetime`, `first_reading_at: datetime | None`, `mean: Mean | None` (all readings in the slot, clean or not, for display), `reading_count: int`.
  - `@dataclass(frozen=True) class RoutineSummary`: `baseline_7d`, `baseline_30d`, `morning_7d`, `evening_7d`: `Mean | None`; `slots_filled_7d: int`; `irregular_pulse_7d: int`; `morning: SlotInfo`; `evening: SlotInfo`.
  - `is_clean(reading: LoggedReading, routine_start: date, windows: Windows) -> bool` (flags, body movement, routine start; the period check is the session's).
  - `summarize(readings: Iterable[LoggedReading], windows: Windows, routine_start: date, now: datetime) -> RoutineSummary`. The caller passes imported readings only. "Last N days" means BP days `d` with `today − N < d <= today`, where `today = bp_day(now)`. `slots_filled_7d` counts distinct `(day, period)` routine slots with any reading. `irregular_pulse_7d` counts readings with `irregular_pulse` in the last 7 BP days. Each `SlotInfo` is for `today`. Status: filled if any session matches, otherwise upcoming/open/closed against `slot_bounds`.

- [ ] **Step 1: Write the failing tests** (`now` passed explicitly, routine start `date(2026, 10, 1)` unless stated):
  - `test_baseline_mean_of_slot_means`: Morning 10-20: (130/85, 126/81) → session 128/83. Evening 10-20: (120/80). Morning 10-21: (124/80). Now 2026-10-21 14:00. `baseline_7d == Mean(124.0, 81.0)` (mean of 128, 120, 124 and 83, 80, 80). `morning_7d == Mean(126.0, 81.5)`. `evening_7d == Mean(120.0, 80.0)`. `slots_filled_7d == 3`.
  - `test_baseline_excludes_unclean`: a flagged reading, a body-movement reading, an extra-period (15:00) reading, and a reading dated before `routine_start` are each excluded from `baseline_7d`. A session with one body-movement reading and one clean reading uses the clean one only.
  - `test_baseline_none_without_clean_readings`: only flagged readings → `baseline_7d is None`, `slots_filled_7d == 1`.
  - `test_7_day_window_edges`: a slot 6 BP days ago counts toward 7d, 7 days ago does not; 29 days ago counts toward 30d.
  - `test_irregular_pulse_7d_counts_all_periods`: two irregular readings (one extra-period) → 2.
  - `test_slot_status_progression`: no readings. `now` 2026-10-21 02:00 → BP day 10-20, morning `closed`, evening `open`. At 04:00 → both `closed`. At 06:00 → BP day 10-21, morning `open`, evening `upcoming`. At 13:00 → morning `closed`. With a 09:50 reading at 13:00 → morning `filled`, `first_reading_at` 09:50, `reading_count == 1`.
  - `test_after_midnight_reading_fills_previous_evening`: reading 2026-10-22 00:30, `now` 00:31 → `evening.status == FILLED` and `evening.window_start` is 2026-10-21 21:00. With `now` 2026-10-22 05:00 → morning `open`, evening `upcoming`.
- [ ] **Step 2:** Run `scripts/test.sh tests/ha/test_routine.py -q` → new tests FAIL.
- [ ] **Step 3:** Implement in `routine.py`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `git commit -m "feat: baseline averages and slot status"`.

### Task 4: Options (windows, routine start) and coordinator wiring

**Files:**
- Modify: `custom_components/ihealth_bp/config_flow.py`, `custom_components/ihealth_bp/__init__.py`, `custom_components/ihealth_bp/coordinator.py`, `strings.json`, `translations/en.json`
- Test: `tests/ha/test_config_flow.py`, `tests/ha/test_coordinator.py`

**Interfaces:**
- Consumes: `windows_from_options`, `Windows.valid`, `summarize`, `group_sessions`.
- Produces (coordinator): properties `windows -> Windows` and `routine_start -> date` (from options; ISO date string). Methods `sessions() -> list[Session]` (over `store.imported()`), `session_of(uid: str) -> Session | None`, and `routine_summary(now: datetime | None = None) -> RoutineSummary` (`now` defaults to `dt_util.now()`). `async_start()` additionally registers `async_track_time_change` listeners at each window boundary and at 00:00:00, each calling `async_update_listeners()`, and cancels them in the returned callback.

- [ ] **Step 1: Write the failing tests:**
  - `test_options_flow_routine_fields` (`test_config_flow.py`): the init form contains the existing two booleans plus `morning_start`, `morning_end`, `evening_start`, `evening_end` (TimeSelector) and `routine_start` (DateSelector), pre-filled from current options. Submitting valid values stores them as strings.
  - `test_options_flow_rejects_invalid_windows`: `evening_start="12:00:00"` → form re-shown with `errors == {"base": "invalid_windows"}`.
  - `test_routine_start_defaults_to_today_once` (`test_coordinator.py`): with the clock frozen at 2026-10-21 10:00 local, an entry set up without `routine_start` gets `options["routine_start"] == "2026-10-21"`. It is set up exactly once (patch `async_reload` and assert it was not called), and setting up again later keeps the date.
  - `test_boundary_listeners_update`: with `coordinator.async_update_listeners` patched, `async_fire_time_changed` at 05:00:00, 12:30:00, 21:00:00, 03:00:00 and 00:00:00 each call it, and 10:00:00 does not. (The end-to-end sensor check is Task 6's `test_slot_sensor_refreshes_at_boundary`.)
- [ ] **Step 2:** Run `scripts/test.sh tests/ha/test_config_flow.py tests/ha/test_coordinator.py -q` → new tests FAIL.
- [ ] **Step 3:** Implement:
  - `DEFAULT_OPTIONS` gains the four window strings. The options schema adds `TimeSelector()` and `DateSelector()` fields, and validation uses `windows_from_options(user_input).valid()`.
  - In `__init__.async_setup_entry`, before anything else, if `CONF_ROUTINE_START` is missing, call `hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_ROUTINE_START: dt_util.now().date().isoformat()})`. The update listener is registered later in the same function, so this does not reload.
  - Add the strings `options.step.init.data.*` with data descriptions ("Morning window starts (also when a new BP day begins)", "Morning window ends", "Evening window starts", "Evening window ends (may be after midnight)", "Count readings toward the baseline from this date") and `options.error.invalid_windows` ("The windows must not overlap: morning, then evening, all within 24 hours starting at the morning start.").
- [ ] **Step 4:** Run `scripts/test.sh tests/ha -q` → all PASS.
- [ ] **Step 5:** Commit: `git commit -m "feat: routine window and start-date options"`.

### Task 5: Context and session services, enriched event

**Files:**
- Modify: `custom_components/ihealth_bp/coordinator.py`, `services.py`, `services.yaml`, `const.py`, `strings.json`, `translations/en.json`, `icons.json`
- Test: `tests/ha/test_routine_services.py` (new)

**Interfaces:**
- Consumes: `CuffStore.async_set_context`, `Session`, `session_of`.
- Produces:
  - `const.SERVICE_SET_READING_CONTEXT = "set_reading_context"`, `const.SERVICE_DELETE_SESSION = "delete_session"`.
  - `IHealthBPCoordinator.async_set_context(uid: str, *, session: bool = False, flags: Iterable[str] | None = None, add_flags: Iterable[str] = (), remove_flags: Iterable[str] = (), note: str | None = None) -> None`. It applies to the session's uids when `session` is true and the reading belongs to an imported session, otherwise to the reading alone, then calls `async_update_listeners()`. It raises `KeyError` for an unknown or deleted uid.
  - `IHealthBPCoordinator.async_delete_session(uid: str) -> None`. It marks every reading in the session DELETED (a pending reading with no session: that reading alone) and runs **one** `async_refresh_statistics` with all their hours. It raises `KeyError` if the uid is unknown or already deleted.
  - `fire_measurement_event` adds `uid`, `period`, `session_index`, `session_start`, `session_mean_systolic`, `session_mean_diastolic`, `session_measured_at` (list), and `bp_category` (`derived.bp_category`). Times are local ISO, like `measured_at`.
  - Service `ihealth_bp.set_reading_context`: `device_id` (required), `measured_at` (required), `session` (bool, default false), `flags` (list, each `vol.In(FLAGS)`), `add_flags` (same), `note` (string, max 255). None of `flags`/`add_flags`/`note` → `ServiceValidationError(translation_key="nothing_to_set")`. An unknown time → `reading_not_found`.
  - Service `ihealth_bp.delete_session`: `device_id`, `measured_at`. Unknown, or already deleted → `reading_not_found`.

- [ ] **Step 1: Write the failing tests** (FakeCuff + `async_setup_cuff`/`async_sync` from `tests/ha/helpers.py`; capture events with `async_capture_events(hass, EVENT_MEASUREMENT)`):
  - `test_event_includes_session_fields`: two readings 70 s apart at 09:50 local, synced together. The second event has `session_index == 2`, `period == "morning"`, `session_mean_systolic` equal to the mean, `len(session_measured_at) == 2`, and `bp_category` set.
  - `test_backlog_events_have_correct_sessions`: one sync with readings from 2026-10-19 09:50, 2026-10-19 22:30 and 2026-10-20 09:50 + 09:51. Events have periods morning/evening/morning/morning and session indexes 1/1/1/2. `routine_summary(now=2026-10-20 13:00).slots_filled_7d == 3`.
  - `test_set_reading_context_session`: the service with `session: true, add_flags: ["caffeine"], note: "x"` on reading 2's time flags and notes both readings.
  - `test_set_reading_context_requires_something`: only `device_id`/`measured_at` → `ServiceValidationError`.
  - `test_set_reading_context_rejects_unknown_flag`: `flags: ["coffee"]` → `vol.Invalid`.
  - `test_delete_session`: deletes both readings, the latest sensors fall back to the previous session, statistics are rebuilt (assert via `get_instance(hass)`/`statistics_during_period` as `test_statistics.py` does, or patch `async_refresh_statistics` and assert it was called once with both hours).
  - `test_concurrent_delete_session`: two concurrent `delete_session` calls on the same session (as `test_todo.py` does for `delete_reading`) → exactly one raises `ServiceValidationError`, and statistics refresh ran once.
- [ ] **Step 2:** Run `scripts/test.sh tests/ha/test_routine_services.py -q` → FAIL.
- [ ] **Step 3:** Implement. Reuse `_coordinator_for_device` and the `measured_at` tz handling in `services.py`, and add `services.yaml` entries with selectors (`device` integration filter, `datetime`, `boolean`, `select` multiple with the nine flags, `text`). Add strings for both services and their fields, the exception `nothing_to_set` ("Give at least one of flags, add_flags or note."), and icons `mdi:tag-text-outline` and `mdi:delete-sweep-outline`.
- [ ] **Step 4:** Run `scripts/test.sh tests/ha -q` → all PASS.
- [ ] **Step 5:** Commit: `git commit -m "feat: reading context and session actions; session info in events"`.

### Task 6: Routine entities

**Files:**
- Modify: `custom_components/ihealth_bp/sensor.py`, `switch.py`, `__init__.py` (`PLATFORMS` += `BUTTON`, `TEXT`), `strings.json`, `translations/en.json`, `icons.json`
- Create: `custom_components/ihealth_bp/text.py`, `custom_components/ihealth_bp/button.py`
- Test: `tests/ha/test_routine_entities.py` (new)

**Interfaces:**
- Consumes: `coordinator.routine_summary()`, `coordinator.sessions()`, `coordinator.async_set_context`, `coordinator.async_delete_session`, `derived.bp_category`, `BP_CATEGORIES`.
- Produces entities (names → entity IDs with the test cuff `kn_550bt`):

| Key / translation_key | Name | Entity ID | Value |
|---|---|---|---|
| `baseline_7d_systolic` | Baseline systolic (7 days) | `sensor.kn_550bt_baseline_systolic_7_days` | `baseline_7d.systolic` |
| `baseline_7d_diastolic` | Baseline diastolic (7 days) | `sensor.kn_550bt_baseline_diastolic_7_days` | |
| `baseline_30d_systolic` | Baseline systolic (30 days) | `sensor.kn_550bt_baseline_systolic_30_days` | |
| `baseline_30d_diastolic` | Baseline diastolic (30 days) | `sensor.kn_550bt_baseline_diastolic_30_days` | |
| `morning_7d_systolic` | Morning systolic (7 days) | `sensor.kn_550bt_morning_systolic_7_days` | |
| `morning_7d_diastolic` | Morning diastolic (7 days) | `sensor.kn_550bt_morning_diastolic_7_days` | |
| `evening_7d_systolic` | Evening systolic (7 days) | `sensor.kn_550bt_evening_systolic_7_days` | |
| `evening_7d_diastolic` | Evening diastolic (7 days) | `sensor.kn_550bt_evening_diastolic_7_days` | |
| `baseline_7d_category` | Baseline category (7 days) | `sensor.kn_550bt_baseline_category_7_days` | enum `BP_CATEGORIES`, `bp_category(round(sys), round(dia))` |
| `slots_filled_7d` | Routine slots filled (7 days) | `sensor.kn_550bt_routine_slots_filled_7_days` | int |
| `irregular_pulse_7d` | Irregular pulse readings (7 days) | `sensor.kn_550bt_irregular_pulse_readings_7_days` | int |
| `morning_slot` | Morning slot | `sensor.kn_550bt_morning_slot` | enum `SlotStatus` |
| `evening_slot` | Evening slot | `sensor.kn_550bt_evening_slot` | enum `SlotStatus` |
| `flag_<flag>` | Had caffeine / Just ate / After exertion / After shower / Poor sleep / Alcohol last night / Stressed / Missed meds / Sick | `switch.kn_550bt_had_caffeine` … `switch.kn_550bt_sick` | on if any reading in the latest session has the flag |
| `session_note` | Session note | `text.kn_550bt_session_note` | first non-empty note in the latest session, else `""` |
| `discard_latest_session` | Discard latest session | `button.kn_550bt_discard_latest_session` | |

  - Pressure sensors: unit mmHg, `suggested_display_precision=0`, no `state_class`, `None` when the mean is `None`.
  - Slot sensors' attributes: `window_start`, `window_end`, `first_reading_at` (ISO local or `None`), `mean_systolic`, `mean_diastolic`, `reading_count`.
  - The flag switches, note and button act on `coordinator.sessions()[-1]`. When there is no session, the switches are `unknown` (`is_on` → `None`) and the note is `""`. Turning a switch on or off or setting the note calls `async_set_context(<latest uid>, session=True, add_flags=/remove_flags=/note=)`. The text uses `native_max=255`, and an empty value clears the note. Pressing the button with no session raises `ServiceValidationError(translation_key="no_session")` ("There is no session to discard.").
  - `switch.py` docstring becomes "Cuff display settings, and context flags for the latest session." The display switches stay `EntityCategory.CONFIG`, and the flag switches have no category.

- [ ] **Step 1: Write the failing tests** (time frozen via the `freezer` fixture; FakeCuff readings):
  - `test_routine_sensors_after_sync`: two clean morning readings 120/80 and 124/82 at 09:50/09:51, now 10:00. Baseline 7d systolic `"122.0"`, diastolic `"81.0"`, category `"hypertension_stage_1"`, slots filled `"1"`, morning slot `"filled"` with `reading_count == 2`, evening slot `"upcoming"`.
  - `test_flag_switch_excludes_from_baseline`: turning on `switch.kn_550bt_had_caffeine` flags both readings in the store, and the baseline sensors become `unknown`.
  - `test_session_note_roundtrip`: `text.set_value` `"walked upstairs"` → both readings carry the note and the entity shows it; setting `""` clears it.
  - `test_discard_button`: press → the session's readings are deleted, the morning slot is back to `open`, and a second press with no sessions raises `ServiceValidationError`.
  - `test_deleting_only_reading_reopens_slot`: delete the only morning reading via `todo.remove_item` → morning slot `open`, baseline `unknown`.
  - `test_slot_sensor_refreshes_at_boundary`: no readings, freeze at 04:59:59 → morning `closed`. Move to 05:00:00 and `async_fire_time_changed` → morning `open`.
  - `test_diagnostics_has_no_context`: after setting a note and a flag, the diagnostics JSON contains neither the note text nor the flag name.
- [ ] **Step 2:** Run `scripts/test.sh tests/ha/test_routine_entities.py -q` → FAIL.
- [ ] **Step 3:** Implement. Add entity names and the enum state names to strings (slot states: Filled / Open / Upcoming / Closed; category reuses the existing labels). Icons: pressure sensors `mdi:heart-pulse`, category `mdi:clipboard-pulse-outline`, slots filled `mdi:calendar-check`, irregular `mdi:heart-off-outline`, slots `mdi:weather-sunset-up` / `mdi:weather-night`, flags `mdi:tag-outline`, note `mdi:note-text-outline`, button `mdi:delete-sweep-outline`.
- [ ] **Step 4:** Run `scripts/test.sh tests/ha -q` → all PASS (including the full existing suite).
- [ ] **Step 5:** Commit: `git commit -m "feat: routine sensors, session flag switches, note and discard"`.

### Task 7: Docs and release prep

**Files:**
- Modify: `README.md`, `custom_components/ihealth_bp/manifest.json` (`"version": "0.2.0"`)

- [ ] **Step 1:** Add a README section **"Measurement routine"** after "How it works". It covers: the protocol summary (with the three source links from the spec), periods and BP days, sessions, flags and notes, what counts toward the baseline, the routine start date, and a table of the new entities. Extend **Event** with the new fields and **Options** with the window and start-date options. Document both new actions under "Removing bad readings" (renamed "Removing and annotating readings"). Add one **generic** example automation (no personal entity IDs: use `notify.mobile_app_your_phone`) that, on `ihealth_bp_measurement` with `session_index == 1`, sends "Take a second reading in 1 minute" with a Discard action calling `ihealth_bp.delete_session`.
- [ ] **Step 2:** Bump the version. Run `scripts/test.sh -q` → all pass. Run hassfest: `MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)":/github/workspace ghcr.io/home-assistant/hassfest` → no errors.
- [ ] **Step 3:** Grep the diff for the owner's personal identifiers (phone, person and routine entity names; the list is kept in the local, git-ignored ledger) → no hits.
- [ ] **Step 4:** Commit: `git commit -m "docs: measurement routine; v0.2.0"`.
- [ ] **Step 5:** Test-deploy to the owner's HA with the local, git-ignored deploy script `.superpowers/deploy_ha.sh` (pre-authorized), restart, and confirm the new entities appear and a real cuff reading fires the enriched event.
- [ ] **Step 6:** **Ask the owner before pushing and tagging** `v0.2.0` (public). After approval: push, tag, create the GitHub release, and update via HACS.
