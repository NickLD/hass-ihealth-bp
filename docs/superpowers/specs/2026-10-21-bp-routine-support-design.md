# Measurement-routine support (v0.2.0) — design

Date: 2026-10-21 · Owner: NickLD · Status: draft for review

## Intent

Readings taken at random times of day are mostly noise. Guideline home monitoring uses a fixed
routine: a morning and an evening session, two readings each, averaged. v0.2.0 teaches the
integration about that routine, so users can build reminders, notifications and dashboards on
top of it with ordinary Home Assistant automations:

- group back-to-back readings into **sessions**;
- label each reading **morning**, **evening** or **extra** (off-schedule);
- store **context flags** and a **note** with each reading (just ate, had caffeine, after a shower…);
- compute a **baseline average** from clean routine readings only, the number worth showing a
  doctor;
- expose today's **slot status** (has this morning's or this evening's session happened yet?);
- richer **events** and **services**, so an automation can react to a reading, prompt for the
  second one, tag it, or discard it.

The integration itself sends no notifications and knows nothing about presence or schedules.
Reminders and dashboards are the user's own automations.

## Measurement protocol (research basis)

From the 2017 ACC/AHA guideline, the AHA/ASH/PCNA home-monitoring statement and the "722"
protocol used in most studies
([PMC9532917](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9532917/),
[AHA handout](https://cpr.heart.org/-/media/Files/Health-Topics/High-Blood-Pressure/measuringbpathome.pdf),
[AMA handout](https://map.ama-assn.org/sites/default/files/2024-05/How%20to%20measure%20blood%20pressure%20at%20home.pdf)):

- Two sessions a day: **morning** within ~1 h of waking, after the bathroom, before caffeine,
  food and any medication; **evening** before bed.
- **Two readings per session, 1 minute apart**, averaged. The first is often higher; the AHA
  suggests 2–3 readings.
- Before each session: no caffeine, nicotine or exercise for 30 min; sit quietly 5 min, back
  supported, feet flat, arm supported at heart level, same arm each time, no talking.
- A hot shower lowers BP for a while afterwards; measure before it, or wait.

## Goals

1. **Slots, not appointments.** Any reading whose *cuff timestamp* falls inside a period's window
   fills that day's slot, even if it syncs late. One reading fills a slot.
2. **Sessions** with per-reading index and session mean, available in the event payload, so an
   automation can prompt "take #2" after the first reading and show the average after the second.
3. **Context** (fixed flags plus a free-text note) stored durably with each reading, settable from
   an automation (for example a notification reply) and from dashboard entities.
4. **Discard** a whole session or a single reading.
5. **Baseline averages** from clean routine readings only (7- and 30-day, and morning vs evening),
   with the ACC/AHA category label.

## Non-goals

- Notifications, reminders, presence, bedtime or any schedule beyond the period windows.
- Medical advice beyond the existing category label.
- Medication tracking ("missed meds" exists only as a flag).
- Multiple users.

## Anti-goals

- **Polluted baseline.** Flagged, off-schedule, movement-marked, pre-routine or discarded readings
  counted in the baseline averages.
- **Losing context.** Flags or notes that vanish on restart, or that disagree between the services
  and the entities.
- **Regressions** in the existing guarantees: no lost or duplicated readings, atomic store
  writes, statistics rebuilt correctly after deletes.

## Sessions

Readings no more than **10 minutes** apart (chained) form one session. A session has an index per
reading (1, 2, 3…), a mean systolic/diastolic/pulse, and a period and BP day. Both come from the
session's first reading that falls in a routine window (morning or evening), using that reading's
period and BP day; a session with no reading in a routine window is `extra` and takes the BP day of
its first reading. So 12:25/12:31 is morning, 20:59:30/21:00:40 is evening, and 04:59:30/05:00:40
is the morning of the new BP day.

## Periods

Every reading gets a period from its local cuff time:

| Period | Default window | |
|---|---|---|
| `morning` | 05:00–12:30 | |
| `evening` | 21:00–03:00 (wraps midnight) | a 01:30 reading belongs to the previous day's evening |
| `extra` | anything else | |

A "BP day" runs 05:00 → 05:00 local. Windows are options in the options flow (defaults above).

## Context: flags and note

Stored per reading in `LoggedReading` (new fields `flags: tuple[str, ...]`, `note: str | None`;
old stored data loads with empty defaults). Flags apply to a whole session when set from the
session-level entities or services.

Fixed flag set: `caffeine`, `ate`, `exertion`, `after_shower`, `poor_sleep`, `alcohol`, `stressed`,
`missed_meds`, `sick`.

## Clean routine readings and baseline

A reading counts toward the baseline when it is imported (not pending or deleted), its period is
`morning` or `evening`, it has **no flags**, it does **not** carry the cuff's `body_movement`
marker, and it was taken on or after the **routine start date**.

- **Routine start date**: an options-flow setting. It defaults to the date the v0.2.0 migration
  runs, so readings taken before the user adopted a routine never enter the baseline.
- **Body movement** means the measurement itself is unreliable. The reading still fills the slot
  but is left out of the baseline.
- **Irregular pulse** is clinically meaningful rather than a measurement error, so the reading
  stays in the baseline. The 7-day sensors expose a count of irregular-pulse readings so a pattern
  is visible.

Baseline = mean of **session means** (one value per filled slot, so a three-reading session
doesn't outweigh a two-reading one) over a trailing window.

## New sensors

Numeric, mmHg, recomputed on every new reading, flag change and delete, and at local midnight so
the window slides:

- 7-day and 30-day baseline systolic and diastolic
- 7-day morning systolic/diastolic, 7-day evening systolic/diastolic
- 7-day baseline category (enum, reusing `derived.bp_category`)
- Routine slots filled in the last 7 days (0–14)
- Irregular-pulse readings in the last 7 days
- Morning slot and evening slot for the current BP day: state `filled` / `open` / `upcoming` /
  `closed`; attributes: window start/end, first reading time, session mean, reading count.
  Automations read window bounds from these attributes rather than duplicating them.

## Latest-session entities (for dashboards)

- One switch per flag, bound to the latest session (turning one on flags every reading in it).
- A text entity for the latest session's note.
- A button: discard latest session.

## Event payload

`ihealth_bp_measurement` gains: `uid`, `period`, `session_index`, `session_start` (local ISO),
`session_mean_systolic`, `session_mean_diastolic`, `session_measured_at` (list of local ISO
timestamps in the session), `bp_category`. Existing keys unchanged. The session mean and
`session_measured_at` cover the session so far, up to and including the event's reading, even when
later readings of the session arrived in the same sync.

## Services

- `ihealth_bp.set_reading_context(device_id, measured_at, flags?, add_flags?, note?, session?)`:
  replace or add flags and set the note on one reading, or on its whole session when `session: true`.
- `ihealth_bp.delete_session(device_id, measured_at)`: delete every reading in the session that
  contains `measured_at`.
- Existing `delete_reading` unchanged.

## Constraints

- Tests in the existing pytest suite (`tests/ha/`), matching current style.
- Bump to v0.2.0. The README documents the routine support, entities, services and options, with
  a generic example automation (reading notification with "take #2" and Discard).

## Left to the builder

Exact entity IDs and names, translation strings, and the storage-migration mechanics.
